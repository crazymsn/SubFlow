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

    for zh in unique_zh:
        if cache:
            hit = cache.get(model, zh)
            if hit:
                zh_to_en[zh] = hit
                stats.cache_hits += 1
                continue
        pending.append(zh)

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        try:
            results = meding.translate_batch(batch, model=model, max_en_chars=max_en_chars)
            stats.api_calls += 1
            for zh, en in zip(batch, results):
                zh_to_en[zh] = en
                if cache:
                    cache.set(model, zh, en)
        except MedingError as exc:
            logger.error("batch translate failed: %s", exc)
            for zh in batch:
                try:
                    single = meding.translate_batch([zh], model=model, max_en_chars=max_en_chars)
                    stats.api_calls += 1
                    zh_to_en[zh] = single[0]
                    if cache:
                        cache.set(model, zh, single[0])
                except MedingError:
                    missing.append(zh)

    out: list[Cue] = []
    for c in cues:
        en = zh_to_en.get(c.zh)
        if not en:
            missing.append(c.zh)
        out.append(Cue(start=c.start, end=c.end, zh=c.zh, en=en))
    return out, stats, list(dict.fromkeys(missing))
