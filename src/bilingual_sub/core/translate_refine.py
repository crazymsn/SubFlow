from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from bilingual_sub.adapters.meding import (
    MedingAuthError,
    MedingClient,
    MedingError,
    MedingServiceError,
    TranslationCache,
)
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.langs import prompt_name
from bilingual_sub.core.netflix import cpl_limit
from bilingual_sub.core.prompts import PROMPT_ADAPT, PROMPT_REFLECT
from bilingual_sub.core.translate import TranslateStats, _checked_lines, translation_cache_key
from bilingual_sub.models import Cue

logger = logging.getLogger(__name__)

_INDEX = re.compile(r"^(\d+)[\.\)\:]\s+(.*)$")
_REFINE_KEYS = ("lines", "translations", "adapted", "output")


@dataclass
class RefineStats(TranslateStats):
    degraded: bool = False


def refine_cache_key(source_lang: str, target_lang: str, text: str, *, glossary_block: str = "") -> str:
    return "refine-v3|" + translation_cache_key(source_lang, target_lang, text,
        glossary_block=glossary_block, max_en_chars=cpl_limit(target_lang))


def _as_issue_list(payload: object) -> list:
    if isinstance(payload, dict) and isinstance(payload.get("issues"), list):
        return payload["issues"]
    return []


def _as_lines(payload: object, expected: int) -> list[str] | None:
    if not isinstance(payload, dict):
        return None
    raw = None
    for key in _REFINE_KEYS:
        if key in payload:
            raw = payload[key]
            break
    if isinstance(raw, str):
        raw = [ln for ln in raw.splitlines() if ln.strip()]
    if not isinstance(raw, list):
        return None
    if any(not isinstance(x, str) or not x.strip() for x in raw):
        return None
    lines = [x.strip() for x in raw]
    indices = [_INDEX.match(line) for line in lines]
    if indices and all(match and int(match[1]) == i for i, match in enumerate(indices, 1)):
        lines = [match[2].strip() for match in indices if match]
    elif lines and all(line.startswith(("- ", "* ")) for line in lines):
        lines = [line[2:].strip() for line in lines]
    if not all(lines):
        return None
    if len(lines) == expected:
        return lines
    if expected == 1 and lines:
        return [" ".join(lines)]
    return None


def _translate_pending(
    client: MedingClient,
    texts: list[str],
    *,
    model: str,
    max_chars: int,
    source_lang: str,
    target_lang: str,
    block: str,
    stats: RefineStats,
    control: JobControl | None = None,
) -> list[str] | None:
    if control:
        control.wait_if_paused()
    try:
        lines = client.translate_batch(
            texts,
            model=model,
            max_en_chars=max_chars,
            source_lang=source_lang,
            target_lang=target_lang,
            glossary_block=block,
        )
        if control:
            control.wait_if_paused()
        stats.api_calls += 1
        return _checked_lines(lines, len(texts))
    except (MedingAuthError, MedingServiceError):
        raise
    except TypeError:
        try:
            lines = client.translate_batch(texts, model=model, max_en_chars=max_chars)
            if control:
                control.wait_if_paused()
            stats.api_calls += 1
            return _checked_lines(lines, len(texts))
        except (MedingAuthError, MedingServiceError):
            raise
        except MedingError as exc:
            logger.warning("refine first pass failed: %s", exc)
            stats.degraded = True
            return None
    except MedingError as exc:
        logger.warning("refine first pass failed: %s", exc)
        stats.degraded = True
        return None


def _reflect_adapt(
    client: MedingClient,
    *,
    model: str,
    source_lang: str,
    target_lang: str,
    max_chars: int,
    block: str,
    sources: list[str],
    drafts: list[str],
    stats: RefineStats,
    control: JobControl | None = None,
) -> tuple[list[str], bool]:
    numbered = "\n".join(f"{n + 1}. {src} => {dst}" for n, (src, dst) in enumerate(zip(sources, drafts)))
    issues: list = []
    if control:
        control.wait_if_paused()
    try:
        reflected = client.chat_json(
            model=model,
            system=PROMPT_REFLECT.format(
                source_name=prompt_name(source_lang),
                target_name=prompt_name(target_lang),
                max_chars=max_chars,
            ),
            user=numbered,
        )
        if control:
            control.wait_if_paused()
        stats.api_calls += 1
        issues = _as_issue_list(reflected)
    except (MedingAuthError, MedingServiceError, JobStopped):
        raise
    except Exception as exc:
        logger.warning("reflect skipped: %s", exc)

    try:
        if control:
            control.wait_if_paused()
        adapted = client.chat_json(
            model=model,
            system=PROMPT_ADAPT.format(
                source_name=prompt_name(source_lang),
                target_name=prompt_name(target_lang),
                max_chars=max_chars,
                glossary_block=block or "(none)",
            ),
            user=numbered + "\nISSUES:" + str(issues),
        )
        if control:
            control.wait_if_paused()
        stats.api_calls += 1
        lines = _as_lines(adapted, len(drafts))
        if lines:
            return lines, True
        logger.warning("adapt line count mismatch: expected %s", len(drafts))
        return drafts, False
    except (MedingAuthError, MedingServiceError, JobStopped):
        raise
    except Exception as exc:
        logger.warning("adapt skipped: %s", exc)
        return drafts, False


def translate_cues_refined(
    cues: list[Cue],
    *,
    model: str,
    source_lang: str,
    target_lang: str,
    glossary: Glossary | None = None,
    client: MedingClient,
    cache: TranslationCache | None = None,
    batch_size: int = 10,
    control: JobControl | None = None,
) -> tuple[list[Cue], RefineStats, list[str]]:
    gloss = glossary or Glossary()
    stats = RefineStats()
    missing: list[str] = []
    max_chars = cpl_limit(target_lang)
    block = gloss.block() or ""
    out: list[Cue] = []
    step = max(1, int(batch_size or 10))

    for i in range(0, len(cues), step):
        if control:
            control.wait_if_paused()
        batch = cues[i : i + step]
        drafts = [""] * len(batch)
        pending_idx: list[int] = []
        for j, cue in enumerate(batch):
            if cache:
                hit = cache.get(model, refine_cache_key(source_lang, target_lang, cue.source, glossary_block=block))
                if hit:
                    drafts[j] = hit
                    stats.cache_hits += 1
                    continue
            pending_idx.append(j)

        if pending_idx:
            raw = _translate_pending(
                client,
                [batch[j].source for j in pending_idx],
                model=model,
                max_chars=max_chars,
                source_lang=source_lang,
                target_lang=target_lang,
                block=block,
                stats=stats,
                control=control,
            )
            ok_idx: list[int] = []
            if raw is None:
                missing.extend(batch[j].source for j in pending_idx)
            else:
                for offset, j in enumerate(pending_idx):
                    line = raw[offset].strip() if offset < len(raw) and raw[offset] else ""
                    if line:
                        drafts[j] = line
                        ok_idx.append(j)
                    else:
                        missing.append(batch[j].source)
                        stats.degraded = True

            if ok_idx:
                polished, adapted_ok = _reflect_adapt(
                    client,
                    model=model,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    max_chars=max_chars,
                    block=block,
                    sources=[batch[j].source for j in ok_idx],
                    drafts=[drafts[j] for j in ok_idx],
                    stats=stats,
                    control=control,
                )
                if adapted_ok:
                    for j, line in zip(ok_idx, polished):
                        drafts[j] = line
                    if cache:
                        for j in ok_idx:
                            cache.set(
                                model,
                                refine_cache_key(source_lang, target_lang, batch[j].source, glossary_block=block),
                                drafts[j],
                            )
                else:
                    stats.degraded = True

        for cue, line in zip(batch, drafts):
            target = gloss.apply_to_text(line) if line else None
            out.append(
                Cue(
                    start=cue.start,
                    end=cue.end,
                    zh=cue.zh,
                    en=target,
                    words=list(cue.words),
                )
            )
    return out, stats, list(dict.fromkeys(missing))
