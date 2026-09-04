"""Language codes for UI locale and subtitle source/target."""

from __future__ import annotations

UI_LOCALES = (
    ("en", "English"),
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("ja", "日本語"),
    ("es", "Español"),
    ("ru", "Русский"),
    ("fr", "Français"),
)

SUB_LANGS = (
    ("zh", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("es", "Español"),
    ("ru", "Русский"),
    ("fr", "Français"),
)

SOURCE_LANGS = (("auto", "Auto"),) + SUB_LANGS

WHISPER_LANG = {
    "auto": "auto",
    "zh": "zh",
    "zh-Hant": "zh",
    "en": "en",
    "ja": "ja",
    "es": "es",
    "ru": "ru",
    "fr": "fr",
}

PROMPT_NAME = {
    "zh": "Chinese",
    "zh-Hant": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "es": "Spanish",
    "ru": "Russian",
    "fr": "French",
    "auto": "the detected spoken language",
}

AZURE_LOCALE = {
    "zh": "zh-CN",
    "zh-Hant": "zh-TW",
    "en": "en-US",
    "ja": "ja-JP",
    "es": "es-ES",
    "ru": "ru-RU",
    "fr": "fr-FR",
}


def whisper_language(code: str) -> str:
    return WHISPER_LANG.get(code, "zh")


def prompt_name(code: str) -> str:
    return PROMPT_NAME.get(code, code)


def display_name(code: str) -> str:
    for key, label in SUB_LANGS:
        if key == code:
            return label
    if code == "auto":
        return "Auto"
    for key, label in UI_LOCALES:
        if key == code:
            return label
    return code


def is_cjk(code: str) -> bool:
    return code in {"zh", "zh-Hant", "ja"}


def convert_han(text: str, lang: str) -> str:
    """Convert Simplified ↔ Traditional when OpenCC is installed."""
    if not text or lang not in {"zh-Hant", "zh"}:
        return text
    try:
        import opencc
    except ImportError:
        return text
    config = "s2t" if lang == "zh-Hant" else "t2s"
    try:
        return opencc.OpenCC(config).convert(text)
    except Exception:
        return text
