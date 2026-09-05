from __future__ import annotations

import logging
from dataclasses import dataclass

from bilingual_sub.adapters.meding import (
    MedingAuthError,
    MedingClient,
    MedingError,
    TranslationCache,
    create_client,
)
from bilingual_sub.core.langs import normalize_pair_fields, park_pair_source
from bilingual_sub.models import Cue
from bilingual_sub.secrets.store import get_api_key

logger = logging.getLogger(__name__)


@dataclass
class TranslateStats:
    cache_hits: int = 0
    api_calls: int = 0


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
    key = api_key or get_api_key()
    if not key and client is None:
        raise MedingAuthError("API key not configured. Run: bilingual-sub config set-api-key")

    meding = client or create_client(key)  # type: ignore[arg-type]
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
        if source_lang == "zh" and target_lang == "en" and not glossary_block:
            return text
        return f"{source_lang}|{target_lang}|{glossary_block}|{text}"

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
            stats.api_calls += 1
            for zh, en in zip(batch, results):
                zh_to_en[zh] = en
                if cache:
                    cache.set(model, _ck(zh), en)
        except MedingError as exc:
            logger.error("batch translate failed: %s", exc)
            for zh in batch:
                try:
                    single = meding.translate_batch(
                        [zh],
                        model=model,
                        max_en_chars=max_en_chars,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        glossary_block=glossary_block,
                    )
                    stats.api_calls += 1
                    zh_to_en[zh] = single[0]
                    if cache:
                        cache.set(model, _ck(zh), single[0])
                except MedingError:
                    missing.append(zh)

    out: list[Cue] = []
    for c in cues:
        en = zh_to_en.get(c.zh)
        if not en:
            missing.append(c.zh)
        out.append(Cue(start=c.start, end=c.end, zh=c.zh, en=en))
    return out, stats, list(dict.fromkeys(missing))


def translate_pair_cues(
    cues: list[Cue],
    *,
    translator=None,
    **kwargs,
) -> tuple[list[Cue], TranslateStats, list[str]]:
    """Fill a 中英 pair from whatever script ASR actually produced."""
    work = translator or translate_cues
    need_en, need_zh = park_pair_source(cues)
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
            chinese = (updated.en or "").strip()
            if chinese:
                cues[index].zh = chinese

    normalize_pair_fields(cues)
    return cues, stats, list(dict.fromkeys(missing))
