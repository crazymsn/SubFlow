from __future__ import annotations

import logging
from dataclasses import dataclass

from bilingual_sub.adapters.meding import MedingClient, MedingError, TranslationCache
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.langs import prompt_name
from bilingual_sub.core.netflix import cpl_limit
from bilingual_sub.core.prompts import PROMPT_ADAPT, PROMPT_REFLECT, PROMPT_SPLIT, PROMPT_TRANSLATE
from bilingual_sub.core.translate import TranslateStats
from bilingual_sub.models import Cue

logger = logging.getLogger(__name__)


@dataclass
class RefineStats(TranslateStats):
    degraded: bool = False


def split_by_meaning(
    cue: Cue,
    *,
    client: MedingClient,
    model: str,
    source_lang: str,
) -> list[str] | None:
    try:
        data = client.chat_json(
            model=model,
            system=PROMPT_SPLIT.format(source_name=prompt_name(source_lang)),
            user=cue.source,
        )
    except Exception as exc:
        logger.warning("meaning split skipped: %s", exc)
        return None
    parts = data.get("parts") if isinstance(data, dict) else None
    if not isinstance(parts, list):
        return None
    clean = [str(p).strip() for p in parts if str(p).strip()]
    return clean if 2 <= len(clean) <= 4 else None


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
    block = gloss.block() or "(none)"
    out: list[Cue] = []

    for i in range(0, len(cues), batch_size):
        if control:
            control.wait_if_paused()
        batch = cues[i : i + batch_size]
        texts = [c.source for c in batch]
        cached_map: dict[str, str] = {}
        pending_idx: list[int] = []
        for j, text in enumerate(texts):
            key = f"refine|{source_lang}|{target_lang}|{text}"
            if cache:
                hit = cache.get(model, key)
                if hit:
                    cached_map[text] = hit
                    stats.cache_hits += 1
                    continue
            pending_idx.append(j)

        translated = list(texts)
        for j, text in enumerate(texts):
            if text in cached_map:
                translated[j] = cached_map[text]

        if pending_idx:
            pending_texts = [texts[j] for j in pending_idx]
            try:
                raw = client.translate_batch(
                    pending_texts,
                    model=model,
                    max_en_chars=max_chars,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    glossary_block=block,
                )
                stats.api_calls += 1
                for j, line in zip(pending_idx, raw):
                    translated[j] = line
            except (MedingError, TypeError):
                try:
                    raw = client.translate_batch(pending_texts, model=model, max_en_chars=max_chars)
                    stats.api_calls += 1
                    for j, line in zip(pending_idx, raw):
                        translated[j] = line
                except MedingError:
                    for j in pending_idx:
                        missing.append(texts[j])
                    stats.degraded = True
                    for cue, line in zip(batch, translated):
                        out.append(Cue(start=cue.start, end=cue.end, zh=cue.zh, en=line, words=cue.words))
                    continue

            numbered = "\n".join(f"{n + 1}. {src} => {dst}" for n, (src, dst) in enumerate(zip(texts, translated)))
            issues: list = []
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
                stats.api_calls += 1
                if isinstance(reflected, dict) and isinstance(reflected.get("issues"), list):
                    issues = reflected["issues"]
            except Exception as exc:
                logger.warning("reflect skipped: %s", exc)
                stats.degraded = True

            try:
                adapted = client.chat_json(
                    model=model,
                    system=PROMPT_ADAPT.format(
                        source_name=prompt_name(source_lang),
                        target_name=prompt_name(target_lang),
                        max_chars=max_chars,
                        glossary_block=block,
                    ),
                    user=numbered + "\nISSUES:" + str(issues),
                )
                stats.api_calls += 1
                lines = adapted.get("lines") if isinstance(adapted, dict) else None
                if isinstance(lines, list) and len(lines) == len(translated):
                    translated = [str(x).strip() for x in lines]
                else:
                    stats.degraded = True
            except Exception as exc:
                logger.warning("adapt skipped: %s", exc)
                stats.degraded = True

            if cache:
                for text, line in zip(texts, translated):
                    cache.set(model, f"refine|{source_lang}|{target_lang}|{text}", line)

        for cue, line in zip(batch, translated):
            out.append(
                Cue(
                    start=cue.start,
                    end=cue.end,
                    zh=cue.zh,
                    en=gloss.apply_to_text(line),
                    words=cue.words,
                )
            )
    return out, stats, list(dict.fromkeys(missing))
