"""UI locale strings. Missing keys fall back to zh-Hans."""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_LOCALE = "zh-Hans"


def _locales_dir() -> Path:
    here = Path(__file__).with_name("locales")
    if here.is_dir():
        return here
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = Path(meipass) / "bilingual_sub" / "i18n" / "locales"
        if cand.is_dir():
            return cand
    return here


_LOCALES_DIR = _locales_dir()
_cache: dict[str, dict[str, str]] = {}
_current = DEFAULT_LOCALE


def available_locales() -> list[str]:
    return ["zh-Hans", "zh-Hant", "en", "ja", "es", "ru", "fr", "de"]


def _load(locale: str) -> dict[str, str]:
    if locale in _cache:
        return _cache[locale]
    path = _LOCALES_DIR / f"{locale}.json"
    data: dict[str, str] = {}
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data = {str(k): str(v) for k, v in raw.items()}
    _cache[locale] = data
    return data


def set_locale(locale: str) -> str:
    global _current
    _current = locale if locale in available_locales() else DEFAULT_LOCALE
    return _current


def current_locale() -> str:
    return _current


def tr(key: str, locale: str | None = None) -> str:
    loc = locale or _current
    value = _load(loc).get(key)
    if value:
        return value
    if loc != DEFAULT_LOCALE:
        return _load(DEFAULT_LOCALE).get(key, key)
    return key
