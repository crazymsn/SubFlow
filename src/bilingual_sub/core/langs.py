"""Language codes for UI locale and subtitle source/target."""

from __future__ import annotations

import re
from typing import Protocol

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
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
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


def spoken_han_lang(target_lang: str) -> str | None:
    """Han variant for Chinese speech only. Never force OpenCC onto ja/ko/en."""
    return _han_variant(target_lang)


def text_family(text: str) -> str:
    """Classify a subtitle line as zh, en, ja, ko, or empty."""
    raw = text or ""
    if _KANA_RE.search(raw):
        return "ja"
    if _HANGUL_RE.search(raw):
        return "ko"
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
    votes: dict[str, int] = {}
    for cue in cues:
        raw = getattr(cue, "zh", None) or getattr(cue, "en", None) or ""
        fam = text_family(raw)
        if fam:
            votes[fam] = votes.get(fam, 0) + max(1, len(raw))
    if not votes:
        if declared_source == "auto":
            return "zh"
        fam = lang_family(declared_source)
        return "zh" if fam == "zh" else fam
    if set(votes) <= {"zh", "en"}:
        return "zh" if votes.get("zh", 0) >= votes.get("en", 0) else "en"
    return max(votes, key=lambda family: votes[family])


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
    return (code or "").strip().replace("_", "-").lower().split("-", 1)[0]


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
    # Original ASR text takes precedence over a stale source dropdown. Brief
    # English terms in a Chinese video must not turn Chinese exports into dubs.
    if target == "zh" and cues and any(text_family(getattr(c, "zh", "") or "") for c in cues):
        if spoken_family(cues, detected_spoken or declared_source) == "zh":
            return False
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
    """Only a change of spoken language requires dubbing, regardless of UI state."""
    return should_dub(declared_source, detected_spoken, target_lang, cues=cues)


def effective_tts_provider(
    declared_source: str,
    detected_spoken: str,
    target_lang: str,
    *,
    cues=None,
    enable_dub: bool = False,
    tts_provider: str = "",
) -> str:
    """Engine that will actually run. Cloud TTS names collapse to GPT-SoVITS."""
    if not job_needs_dub(
        declared_source,
        detected_spoken,
        target_lang,
        cues=cues,
        enable_dub=enable_dub,
        tts_provider=tts_provider,
    ):
        return "none"
    engine = (tts_provider or "").strip().lower()
    if engine in {"", "none", "openai", "azure"}:
        return "gptsovits"
    return engine


def coerce_requested_tts(tts_provider: str, *, enable_dub: bool = False) -> str:
    """Map leftover cloud names and an explicit --dub flag onto GPT-SoVITS."""
    name = (tts_provider or "").strip().lower() or "none"
    if name in {"openai", "azure"}:
        name = "gptsovits"
    if enable_dub and name in {"", "none"}:
        name = "gptsovits"
    return name


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


def spoken_translation_needed(
    source_lang: str,
    target_lang: str,
    *,
    detected_spoken: str | None = None,
) -> bool:
    """True when dubbed speech needs a language the soundtrack does not already give."""
    heard = detected_spoken if detected_spoken and detected_spoken != "auto" else source_lang
    return wants_spoken_target(heard, target_lang)


def job_needs_translation(
    source_lang: str,
    target_lang: str,
    mode: str,
    *,
    detected_spoken: str | None = None,
    cues=None,
    enable_dub: bool = False,
    tts_provider: str = "",
) -> bool:
    """Screen translation or the target-language line required by dubbing."""
    if translation_needed(source_lang, target_lang, mode):
        return True
    heard = source_lang if detected_spoken is None else detected_spoken
    return job_needs_dub(
        source_lang,
        heard,
        target_lang,
        cues=cues,
        enable_dub=enable_dub,
        tts_provider=tts_provider,
    ) and spoken_translation_needed(source_lang, target_lang, detected_spoken=heard)


def has_distinct_target_line(cues) -> bool:
    for cue in cues:
        target = (getattr(cue, "en", None) or "").strip()
        source = (getattr(cue, "zh", None) or "").strip()
        if target and target != source:
            return True
    return False


def line_matching(cue, lang: str) -> str:
    """Return the cue slot whose script matches lang, or empty."""
    target = lang_family(lang)
    for text in (
        (getattr(cue, "zh", None) or "").strip(),
        (getattr(cue, "en", None) or "").strip(),
    ):
        if text and text_family(text) == target:
            return text
    return ""


def spoken_line(cue, target_lang: str) -> str:
    """Text the dubber should speak. Pick the line that matches the target script."""
    spoken = (getattr(cue, "spoken", None) or "").strip()
    target = lang_family(target_lang)
    if spoken and target not in {"zh", "en"}:
        return spoken
    if spoken and text_family(spoken) == target:
        return spoken
    matched = line_matching(cue, target_lang)
    if matched:
        return matched
    zh = (getattr(cue, "zh", None) or "").strip()
    en = (getattr(cue, "en", None) or "").strip()
    if target == "zh":
        return zh
    if target == "en":
        return ""
    if en and text_family(en) != "zh":
        return en
    if zh and text_family(zh) != "zh":
        return zh
    return (en or zh or "").strip()


def screen_line(cue, mode: str, target_lang: str = "", source_lang: str = "") -> str:
    """On-screen text for a single-line style. Dub translations must not steal the frame."""
    lang = single_subtitle_lang(mode)
    if not lang and mode == "netflix_single":
        lang = screen_translate_lang(source_lang or "zh", target_lang or "en", mode)
    if lang:
        matched = line_matching(cue, lang)
        if matched:
            return matched
        spoken = (getattr(cue, "spoken", None) or "").strip()
        if spoken and lang_family(lang) not in {"zh", "en"}:
            return spoken
    return (getattr(cue, "en", None) or getattr(cue, "zh", None) or "").strip()


def job_translation_langs(
    source_lang: str,
    target_lang: str,
    mode: str,
    *,
    detected_spoken: str | None = None,
    cues=None,
    enable_dub: bool = False,
    tts_provider: str = "",
) -> list[str]:
    """Languages this job must produce that the source track does not already give."""
    heard = source_lang if detected_spoken is None else detected_spoken
    if heard and heard != "auto":
        src_fam = lang_family(heard)
    elif source_lang and source_lang != "auto":
        src_fam = lang_family(source_lang)
    else:
        src_fam = ""
    dests: list[str] = []
    if translation_needed(source_lang, target_lang, mode):
        dests.append(screen_translate_lang(source_lang, target_lang, mode))
    if job_needs_dub(
        source_lang,
        heard,
        target_lang,
        cues=cues,
        enable_dub=enable_dub,
        tts_provider=tts_provider,
    ) and spoken_translation_needed(source_lang, target_lang, detected_spoken=heard):
        dests.append(target_lang)
    uniq: list[str] = []
    seen: set[str] = set()
    for lang in dests:
        fam = lang_family(lang)
        if src_fam and fam == src_fam:
            continue
        if fam in seen:
            continue
        seen.add(fam)
        uniq.append(lang)
    return uniq


def token_required_for_job(
    source_lang: str,
    target_lang: str,
    mode: str,
    *,
    enable_dub: bool = False,
    tts_provider: str = "",
) -> bool:
    """True when the client must collect a translation token before starting."""
    if job_needs_translation(
        source_lang,
        target_lang,
        mode,
        enable_dub=enable_dub,
        tts_provider=tts_provider,
    ):
        return True
    if source_lang != "auto":
        return False
    if is_pair_mode(mode):
        return True
    screen = single_subtitle_lang(mode)
    if screen and lang_family(screen) != "zh":
        return True
    if lang_family(target_lang) != "zh":
        return True
    return job_needs_dub(
        source_lang,
        source_lang,
        target_lang,
        enable_dub=enable_dub,
        tts_provider=tts_provider,
    )


def drop_target_if_unneeded(
    cues,
    source_lang: str,
    target_lang: str,
    mode: str,
    *,
    detected_spoken: str | None = None,
    enable_dub: bool = False,
    tts_provider: str = "",
) -> None:
    """Drop leftover target lines unless the screen or the dubber still needs them."""
    if job_needs_translation(
        source_lang,
        target_lang,
        mode,
        detected_spoken=detected_spoken,
        cues=cues,
        enable_dub=enable_dub,
        tts_provider=tts_provider,
    ):
        return
    for cue in cues:
        cue.en = None
        cue.spoken = None


class _HanConverter(Protocol):
    def convert(self, text: str) -> str: ...


_CC: dict[str, _HanConverter] = {}


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
        if text_family(getattr(cue, "en", None) or "") == "zh":
            cue.en = convert_han(cue.en, han_lang)
        if text_family(getattr(cue, "spoken", None) or "") == "zh":
            cue.spoken = convert_han(cue.spoken, han_lang)
