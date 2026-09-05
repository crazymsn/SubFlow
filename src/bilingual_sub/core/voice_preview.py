"""Short TTS audition clips. Sample text follows dub target language, not UI locale."""

from __future__ import annotations

import re
from pathlib import Path

from bilingual_sub.adapters.tts.base import TtsRequest, select_tts
from bilingual_sub.adapters.tts.gptsovits import GptSovitsTts
from bilingual_sub.config import user_config_dir

PREVIEW_SAMPLES = {
    "zh": "你好，这是配音音色试听。",
    "zh-Hans": "你好，这是配音音色试听。",
    "zh-Hant": "你好，這是配音音色試聽。",
    "en": "Hello, this is a voice preview.",
    "ja": "こんにちは。これは音声の試聴です。",
    "es": "Hola, esta es una vista previa de voz.",
    "ru": "Здравствуйте, это пробное прослушивание голоса.",
    "fr": "Bonjour, ceci est un aperçu de la voix.",
    "de": "Hallo, das ist eine Stimmprobe.",
}

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def preview_sample(lang: str) -> str:
    code = (lang or "zh").strip() or "zh"
    if code in PREVIEW_SAMPLES:
        return PREVIEW_SAMPLES[code]
    if code.startswith("zh"):
        return PREVIEW_SAMPLES["zh-Hant"] if "Hant" in code else PREVIEW_SAMPLES["zh"]
    return PREVIEW_SAMPLES.get(code.split("-", 1)[0], PREVIEW_SAMPLES["en"])


def preview_cache_dir() -> Path:
    path = user_config_dir() / "voice-preview"
    path.mkdir(parents=True, exist_ok=True)
    return path


def preview_cache_path(voice: str, lang: str, provider: str = "openai") -> Path:
    token = _SAFE.sub("_", f"{provider}-{voice or 'default'}-{lang or 'zh'}")
    return preview_cache_dir() / f"{token}.wav"


def synth_voice_preview(
    *,
    provider: str,
    voice: str,
    lang: str,
    endpoint: str = "",
    dest: Path | None = None,
) -> Path:
    dest = dest or preview_cache_path(voice, lang, provider)
    if dest.is_file() and dest.stat().st_size > 64:
        try:
            from bilingual_sub.adapters.ffmpeg import is_pcm_wav

            if is_pcm_wav(dest) or dest.suffix.lower() != ".wav":
                return dest
        except Exception:
            return dest
    text = preview_sample(lang)
    engine = (provider or "openai").lower()
    tts = GptSovitsTts(endpoint) if engine == "gptsovits" else select_tts("openai")
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = tts.synth(TtsRequest(text=text, lang=lang or "zh", voice=voice or "alloy", dest=dest))
    try:
        from bilingual_sub.adapters.ffmpeg import is_pcm_wav, to_pcm_wav

        if dest.suffix.lower() in {".wav", ".wave"} and not is_pcm_wav(Path(raw)):
            return to_pcm_wav(Path(raw), dest)
    except Exception:
        pass
    return Path(raw)
