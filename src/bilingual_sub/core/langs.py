"""Language codes for UI locale and subtitle source/target."""

from __future__ import annotations

import re

UI_LOCALES = (
    ("zh-Hans", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("es", "Español"),
    ("ru", "Русский"),
    ("fr", "Français"),
    ("de", "Deutsch"),
)

SUB_LANGS = (
    ("zh", "简体中文"),
    ("zh-Hant", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("es", "Español"),
    ("ru", "Русский"),
    ("fr", "Français"),
    ("de", "Deutsch"),
)

SOURCE_LANGS = (("auto", "Auto"),) + SUB_LANGS

SINGLE_SUB_MODES = (
    ("single:en", "English"),
    ("single:zh", "简体中文"),
    ("single:zh-Hant", "繁體中文"),
    ("single:ja", "日本語"),
    ("single:es", "Español"),
    ("single:ru", "Русский"),
    ("single:fr", "Français"),
    ("single:de", "Deutsch"),
)

_HAN = {"zh", "zh-Hans", "zh-Hant"}

WHISPER_LANG = {
    "auto": "auto",
    "zh": "zh",
    "zh-Hant": "zh",
    "en": "en",
    "ja": "ja",
    "es": "es",
    "ru": "ru",
    "fr": "fr",
    "de": "de",
}

PROMPT_NAME = {
    "zh": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "es": "Spanish",
    "ru": "Russian",
    "fr": "French",
    "de": "German",
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
    "de": "de-DE",
}

PAIR_MODES = frozenset({"bilingual", "enzh"})

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


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


def single_subtitle_lang(mode: str) -> str | None:
    if not (mode or "").startswith("single:"):
        return None
    lang = mode.split(":", 1)[1]
    return "zh" if lang == "zh-Hans" else lang


def is_pair_mode(mode: str) -> bool:
    return (mode or "") in PAIR_MODES


def is_valid_subtitle_mode(mode: str) -> bool:
    if mode in PAIR_MODES or mode == "netflix_single":
        return True
    return mode in {code for code, _label in SINGLE_SUB_MODES}


def effective_target_lang(source_lang: str, target_lang: str, mode: str) -> str:
    """Dubbing language. Subtitle style does not override it."""
    return target_lang


def pair_translate_lang(source_lang: str) -> str:
    """The other half of a 中英 / 英中 pair."""
    return "zh" if lang_family(source_lang) == "en" else "en"


def screen_translate_lang(source_lang: str, target_lang: str, mode: str) -> str:
    if is_pair_mode(mode):
        return pair_translate_lang(source_lang)
    return single_subtitle_lang(mode) or target_lang


def _han_variant(code: str) -> str | None:
    if code in {"zh", "zh-Hans"}:
        return "zh"
    if code == "zh-Hant":
        return "zh-Hant"
    return None


def screen_han_lang(source_lang: str, target_lang: str, mode: str) -> str:
    """On-screen Chinese variant. Target/style win; default Simplified."""
    single = single_subtitle_lang(mode)
    if single in {"zh", "zh-Hant"}:
        return single
    for code in (target_lang, source_lang):
        variant = _han_variant(code)
        if variant:
            return variant
    return "zh"


def text_family(text: str) -> str:
    """Classify a subtitle line as zh, en, or empty."""
    raw = text or ""
    cjk = len(_CJK_RE.findall(raw))
    latin = len(_LATIN_RE.findall(raw))
    if cjk == 0 and latin == 0:
        return ""
    if cjk > 0 and cjk * 2 >= latin:
        return "zh"
    if latin > 0:
        return "en"
    return "zh"


def spoken_family(cues, declared_source: str = "zh") -> str:
    """Majority script of ASR text. Declared source is only a fallback."""
    votes = {"zh": 0, "en": 0}
    for cue in cues:
        raw = getattr(cue, "zh", None) or getattr(cue, "en", None) or ""
        fam = text_family(raw)
        if fam in votes:
            votes[fam] += max(1, len(raw))
    if votes["zh"] == 0 and votes["en"] == 0:
        if declared_source == "auto":
            return "zh"
        fam = lang_family(declared_source)
        return "zh" if fam == "zh" else fam
    return "zh" if votes["zh"] >= votes["en"] else "en"


def park_pair_source(cues) -> tuple[list[int], list[int]]:
    """Move English ASR out of cue.zh. Return (need_en_idx, need_zh_idx)."""
    need_en: list[int] = []
    need_zh: list[int] = []
    for i, cue in enumerate(cues):
        spoken = (cue.zh or cue.en or "").strip()
        fam = text_family(spoken)
        if fam == "en":
            if text_family(cue.en or "") != "en":
                cue.en = spoken
            if text_family(cue.zh or "") == "en":
                cue.zh = ""
            if text_family(cue.zh or "") != "zh":
                need_zh.append(i)
        elif fam == "zh":
            if text_family(cue.en or "") != "en":
                need_en.append(i)
    return need_en, need_zh


def normalize_pair_fields(cues) -> None:
    """cue.zh must be Chinese, cue.en must be English."""
    for cue in cues:
        zh_f = text_family(cue.zh or "")
        en_f = text_family(cue.en or "")
        if zh_f == "en" and en_f == "zh":
            cue.zh, cue.en = cue.en, cue.zh
        elif zh_f == "en" and en_f != "zh":
            if en_f != "en":
                cue.en = cue.zh
            cue.zh = ""


def pair_display_texts(cue) -> tuple[str, str]:
    """On-screen 中 / 英. Never put English on the Chinese line."""
    zh = (getattr(cue, "zh", None) or "").strip()
    en = (getattr(cue, "en", None) or "").strip()
    if text_family(zh) == "en":
        if text_family(en) != "en" or len(zh) > len(en):
            en = zh
        zh = ""
    if text_family(en) == "zh":
        if text_family(zh) != "zh":
            zh = en
        en = ""
    return zh, en


def pair_cues_polluted(cues) -> bool:
    """True when a 中英 pair still has English sitting in the Chinese field."""
    for cue in cues:
        if text_family(getattr(cue, "zh", None) or "") == "en":
            return True
    return False


def assign_pair_fields(cues, source_lang: str) -> None:
    """Keep cue.zh = Chinese and cue.en = English after pair translation."""
    if spoken_family(cues, source_lang) == "en":
        for cue in cues:
            spoken = cue.zh
            translated = cue.en
            if text_family(spoken) == "en" and text_family(translated or "") == "zh":
                cue.zh = translated or spoken
                cue.en = spoken
    normalize_pair_fields(cues)


def lang_family(code: str) -> str:
    if code in _HAN:
        return "zh"
    return code


def _lang_family(code: str) -> str:
    return lang_family(code)


def wants_spoken_target(source_lang: str, target_lang: str) -> bool:
    """True when dubbed speech should switch to the target language."""
    if source_lang == "auto":
        return lang_family(target_lang) != "zh"
    return lang_family(source_lang) != lang_family(target_lang)


def original_lang_votes(declared_source: str, detected_spoken: str, cues=None) -> set[str]:
    """Languages the original soundtrack might still be in.

    Declared source, ASR language, and transcript script are votes. A Chinese
    transcript still votes zh even if the user set source=English.
    """
    votes: set[str] = set()
    if declared_source and declared_source != "auto":
        votes.add(lang_family(declared_source))
    heard = (detected_spoken or "").strip()
    if heard and heard != "auto":
        votes.add(lang_family(heard))
    if cues:
        votes.add(spoken_family(cues, declared_source or "zh"))
        for cue in cues:
            raw = getattr(cue, "zh", None) or getattr(cue, "en", None) or ""
            fam = text_family(raw)
            if fam:
                votes.add(fam)
    return votes


def should_dub(declared_source: str, detected_spoken: str, target_lang: str, cues=None) -> bool:
    """Dub unless every signal says the original track is already the target.

    Target language is the spoken language of the export. A Chinese video
    must be dubbed to English even when Whisper or the source combo said en.
    """
    target = lang_family(target_lang)
    votes = original_lang_votes(declared_source, detected_spoken, cues)
    if not votes:
        return wants_spoken_target(declared_source, target_lang)
    return any(vote != target for vote in votes)


def job_needs_dub(
    declared_source: str,
    detected_spoken: str,
    target_lang: str,
    *,
    cues=None,
    enable_dub: bool = False,
    tts_provider: str = "",
) -> bool:
    """Target language is the spoken language. The checkbox cannot skip that.

    Same-language jobs keep the original track even if enable_dub is set.
    """
    return should_dub(declared_source, detected_spoken, target_lang, cues=cues)


def output_stem_suffix(mode: str) -> str:
    """Visible export stem. 中英 / 英中 are different products, not aliases."""
    if mode == "enzh":
        return "-英中字幕"
    if mode == "netflix_single":
        return "-单行字幕"
    if (mode or "").startswith("single:"):
        for code, label in SINGLE_SUB_MODES:
            if code == mode:
                return f"-{label}"
        return f"-{mode.split(':', 1)[1]}"
    return "-中英字幕"


def output_stem_suffixes() -> tuple[str, ...]:
    extras = tuple(f"-{label}" for _code, label in SINGLE_SUB_MODES)
    return ("-中英字幕", "-英中字幕", "-单行字幕") + extras


def translation_needed(source_lang: str, target_lang: str, mode: str) -> bool:
    """True when the subtitle style needs a language the source track does not already give."""
    if is_pair_mode(mode):
        return True
    out = screen_translate_lang(source_lang, target_lang, mode)
    if source_lang == "auto":
        return lang_family(out) != "zh"
    return lang_family(source_lang) != lang_family(out)


def has_distinct_target_line(cues) -> bool:
    for cue in cues:
        target = (getattr(cue, "en", None) or "").strip()
        source = (getattr(cue, "zh", None) or "").strip()
        if target and target != source:
            return True
    return False


def spoken_line(cue, target_lang: str) -> str:
    """Text the dubber should speak. Pick the line that matches the target script."""
    zh = (getattr(cue, "zh", None) or "").strip()
    en = (getattr(cue, "en", None) or "").strip()
    target = lang_family(target_lang)
    if target == "zh":
        if text_family(zh) == "zh":
            return zh
        if text_family(en) == "zh":
            return en
        return zh
    if target == "en":
        if text_family(en) == "en":
            return en
        if text_family(zh) == "en":
            return zh
        return ""
    if en and text_family(en) != "zh":
        return en
    if zh and text_family(zh) != "zh":
        return zh
    return ""


def drop_target_if_unneeded(cues, source_lang: str, target_lang: str, mode: str) -> None:
    """Same-language jobs must not keep a leftover English/target line."""
    if translation_needed(source_lang, target_lang, mode):
        return
    for cue in cues:
        cue.en = None


_CC: dict[str, object] = {}


def convert_han(text: str, lang: str) -> str:
    """Convert Simplified ↔ Traditional. Target zh is always Simplified."""
    if not text or lang not in {"zh-Hant", "zh"}:
        return text
    if text_family(text) != "zh":
        return text
    try:
        import opencc
    except ImportError:
        return text
    config = "s2t" if lang == "zh-Hant" else "t2s"
    try:
        converter = _CC.get(config)
        if converter is None:
            converter = opencc.OpenCC(config)
            _CC[config] = converter
        return converter.convert(text)
    except Exception:
        return text


def apply_han_to_cues(cues, han_lang: str) -> None:
    """Normalize Chinese cue fields to the requested Han variant."""
    if han_lang not in {"zh", "zh-Hant"}:
        return
    for cue in cues:
        if text_family(getattr(cue, "zh", None) or "") == "zh":
            cue.zh = convert_han(cue.zh, han_lang)
