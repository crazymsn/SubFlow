from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from bilingual_sub.adapters.meding import (
    MedingAuthError,
    MedingClient,
    MedingError,
    MedingServiceError,
    TranslationCache,
    create_client,
)
from bilingual_sub.core.langs import (
    lang_family,
    normalize_pair_fields,
    park_pair_source,
    spoken_family,
    text_family,
)
from bilingual_sub.models import Cue
from bilingual_sub.secrets.store import get_api_key

logger = logging.getLogger(__name__)


@dataclass
class TranslateStats:
    cache_hits: int = 0
    api_calls: int = 0


def translation_cache_key(source_lang: str, target_lang: str, text: str, *,
                          glossary_block: str = "", max_en_chars: int = 120) -> str:
    return json.dumps({"schema": "translate-v2", "source": source_lang, "target": target_lang,
                       "text": text, "glossary": glossary_block, "max_chars": max_en_chars},
                      ensure_ascii=False, sort_keys=True)


def _checked_lines(lines, count: int) -> list[str]:
    if (not isinstance(lines, list) or len(lines) != count
            or any(not isinstance(line, str) or not line.strip() for line in lines)):
        raise MedingError("translation response has missing or invalid lines")
    return [line.strip() for line in lines]


def translate_cues(
    cues: list[Cue],
    *,
    model: str = "gpt-4o-mini",
    batch_size: int = 30,
    max_en_chars: int = 120,
    cache_enabled: bool = True,
    api_key: str | None = None,
    client: MedingClient | None = None,
    source_lang: str = "zh",
    target_lang: str = "en",
    glossary_block: str = "",
    control=None,
) -> tuple[list[Cue], TranslateStats, list[str]]:
    if control:
        control.wait_if_paused()
    if batch_size <= 0 or max_en_chars <= 0:
        raise ValueError("translation batch size and character limit must be positive")
    key = api_key or get_api_key()
    if not key and client is None:
        raise MedingAuthError("API key not configured. Run: bilingual-sub config set-api-key")

    meding = client or create_client(key, control=control)  # type: ignore[arg-type]
    cache = TranslationCache() if cache_enabled else None
    stats = TranslateStats()
    missing: list[str] = []

    unique_zh: list[str] = []
    seen: set[str] = set()
    for c in cues:
        if c.zh not in seen:
            seen.add(c.zh)
            unique_zh.append(c.zh)

    zh_to_en: dict[str, str] = {}
    pending: list[str] = []

    def _ck(text: str) -> str:
        return translation_cache_key(source_lang, target_lang, text,
                                     glossary_block=glossary_block, max_en_chars=max_en_chars)

    for zh in unique_zh:
        if cache:
            hit = cache.get(model, _ck(zh))
            if hit:
                zh_to_en[zh] = hit
                stats.cache_hits += 1
                continue
        pending.append(zh)

    for i in range(0, len(pending), batch_size):
        if control:
            control.wait_if_paused()
        batch = pending[i : i + batch_size]
        try:
            results = meding.translate_batch(
                batch,
                model=model,
                max_en_chars=max_en_chars,
                source_lang=source_lang,
                target_lang=target_lang,
                glossary_block=glossary_block,
            )
            if control:
                control.wait_if_paused()
            results = _checked_lines(results, len(batch))
            stats.api_calls += 1
            for zh, en in zip(batch, results):
                zh_to_en[zh] = en
                if cache:
                    cache.set(model, _ck(zh), en)
        except (MedingAuthError, MedingServiceError):
            raise
        except MedingError as exc:
            logger.error("batch translate failed: %s", exc)
            for zh in batch:
                if control:
                    control.wait_if_paused()
                try:
                    single = meding.translate_batch(
                        [zh],
                        model=model,
                        max_en_chars=max_en_chars,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        glossary_block=glossary_block,
                    )
                    if control:
                        control.wait_if_paused()
                    single = _checked_lines(single, 1)
                    stats.api_calls += 1
                    zh_to_en[zh] = single[0]
                    if cache:
                        cache.set(model, _ck(zh), single[0])
                except (MedingAuthError, MedingServiceError):
                    raise
                except MedingError:
                    missing.append(zh)

    out: list[Cue] = []
    for c in cues:
        translated = zh_to_en.get(c.zh)
        if not translated:
            missing.append(c.zh)
        out.append(Cue(start=c.start, end=c.end, zh=c.zh, en=translated, words=list(c.words)))
    return out, stats, list(dict.fromkeys(missing))


def place_translated_line(cue: Cue, text: str, dest_lang: str) -> None:
    """Store a translation. zh/en stay on-screen slots; any other language goes to spoken."""
    text = (text or "").strip()
    if not text:
        return
    fam = lang_family(dest_lang)
    cue.language_texts[fam] = text
    if fam == "zh":
        if text_family(cue.zh or "") not in {"", "zh"} and not (cue.en or "").strip():
            cue.en = cue.zh
        cue.zh = text
        return
    if fam == "en":
        cue.en = text
        return
    cue.spoken = text


def fill_translated_languages(
    cues: list[Cue],
    dest_langs: list[str],
    *,
    translator=None,
    source_lang: str = "zh",
    **kwargs,
) -> tuple[list[Cue], TranslateStats, list[str]]:
    """Translate the original ASR line into each destination language."""
    work = translator or translate_cues
    originals = [(cue.zh or cue.en or "") for cue in cues]
    for cue, original in zip(cues, originals):
        cue.language_texts.setdefault(spoken_family([cue], source_lang), original)
    stats = TranslateStats()
    missing: list[str] = []
    for dest in dest_langs:
        subset = [
            Cue(start=cues[i].start, end=cues[i].end, zh=originals[i], en=None)
            for i in range(len(cues))
        ]
        out, st, miss = work(subset, source_lang=source_lang, target_lang=dest, **kwargs)
        stats.cache_hits += getattr(st, "cache_hits", 0)
        stats.api_calls += getattr(st, "api_calls", 0)
        missing.extend(miss)
        for index, updated in enumerate(out):
            place_translated_line(cues[index], (updated.en or "").strip(), dest)
    return cues, stats, list(dict.fromkeys(missing))


def translate_pair_cues(
    cues: list[Cue],
    *,
    translator=None,
    source_lang: str = "",
    **kwargs,
) -> tuple[list[Cue], TranslateStats, list[str]]:
    """Fill a 中英 pair from whatever script ASR actually produced."""
    work = translator or translate_cues
    # Capture third-language originals before either paired translation mutates
    # the display slots. Group scripts separately for mixed-language clips.
    other_sources: dict[str, list[tuple[int, str]]] = {}
    for i, cue in enumerate(cues):
        original = (cue.zh or cue.en or "").strip()
        family = spoken_family([cue], source_lang) if text_family(original) else ""
        if family:
            cue.language_texts.setdefault(family, original)
        if family not in {"", "zh", "en"}:
            other_sources.setdefault(family, []).append((i, original))
    need_en, need_zh = park_pair_source(cues, source_lang)
    stats = TranslateStats()
    missing: list[str] = []

    if need_en:
        subset = [cues[i] for i in need_en]
        out, st, miss = work(subset, source_lang="zh", target_lang="en", **kwargs)
        stats.cache_hits += getattr(st, "cache_hits", 0)
        stats.api_calls += getattr(st, "api_calls", 0)
        missing.extend(miss)
        for index, updated in zip(need_en, out):
            cues[index].en = updated.en
            if updated.en:
                cues[index].language_texts["en"] = updated.en
            if updated.zh:
                cues[index].zh = updated.zh

    if need_zh:
        subset = [
            Cue(start=cues[i].start, end=cues[i].end, zh=cues[i].en or cues[i].zh or "", en=None)
            for i in need_zh
        ]
        out, st, miss = work(subset, source_lang="en", target_lang="zh", **kwargs)
        stats.cache_hits += getattr(st, "cache_hits", 0)
        stats.api_calls += getattr(st, "api_calls", 0)
        missing.extend(miss)
        for index, updated in zip(need_zh, out):
            cand_en = (updated.en or "").strip()
            cand_zh = (updated.zh or "").strip()
            chinese = cand_en if text_family(cand_en) == "zh" else cand_zh
            if text_family(chinese) == "zh":
                cues[index].zh = chinese
                cues[index].language_texts["zh"] = chinese

    for src, originals in other_sources.items():
        for index, _original in originals:
            # Missing translations must not masquerade as an English line.
            cues[index].zh = ""
            cues[index].en = None
        for dest in ("zh", "en"):
            subset = [Cue(cues[i].start, cues[i].end, original) for i, original in originals]
            out, st, miss = work(subset, source_lang=src, target_lang=dest, **kwargs)
            stats.cache_hits += getattr(st, "cache_hits", 0)
            stats.api_calls += getattr(st, "api_calls", 0)
            missing.extend(miss)
            for (index, _original), updated in zip(originals, out):
                translated = (updated.en or "").strip()
                if translated and (dest == "en" or text_family(translated) == "zh"):
                    place_translated_line(cues[index], translated, dest)

    normalize_pair_fields(cues)
    return cues, stats, list(dict.fromkeys(missing))
