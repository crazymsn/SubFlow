"""Short TTS audition clips. Sample text follows dub target language, not UI locale."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from bilingual_sub.adapters.tts.base import TtsRequest, select_tts
from bilingual_sub.config import user_config_dir
from bilingual_sub.core.control import JobControl

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


def preview_cache_path(voice: str, lang: str, provider: str = "gptsovits", extra: str = "") -> Path:
    token = _SAFE.sub("_", f"{provider}-{voice or 'default'}-{lang or 'zh'}-{extra}")
    digest = hashlib.sha256(token.encode()).hexdigest()[:16]
    return preview_cache_dir() / f"{token[:64]}-{digest}.wav"


def _preview_extra(provider: str, ref_audio: str, prompt_text: str, prompt_lang: str = "") -> str:
    if (provider or "").lower() != "gptsovits":
        return ""
    digest = hashlib.sha1(f"{ref_audio}|{prompt_text}|{prompt_lang}".encode()).hexdigest()[:10]
    name = Path(ref_audio).stem if ref_audio else "noref"
    return f"{name}-{digest}"


def synth_voice_preview(
    *,
    provider: str,
    voice: str,
    lang: str,
    endpoint: str = "",
    dest: Path | None = None,
    ref_audio: str = "",
    prompt_text: str = "",
    prompt_lang: str = "",
    control: JobControl | None = None,
) -> Path:
    from bilingual_sub.adapters.tts.gptsovits import tts_job_fingerprint

    if control:
        control.check()
    extra = tts_job_fingerprint(provider, voice=voice, endpoint=endpoint, ref_audio=ref_audio, prompt_text=prompt_text, prompt_lang=prompt_lang)
    dest = dest or preview_cache_path(voice, lang, provider, extra)
    if dest.is_file() and dest.stat().st_size > 64:
        from bilingual_sub.adapters.ffmpeg import is_pcm_wav

        if is_pcm_wav(dest) or dest.suffix.lower() not in {".wav", ".wave"}:
            return dest
    text = preview_sample(lang)
    engine = (provider or "gptsovits").lower()
    if engine == "gptsovits":
        from bilingual_sub.adapters.tts.gptsovits_runtime import ensure_running

        ensure_running(endpoint or None, wait_sec=300, control=control)
    tts = select_tts(
        engine,
        endpoint=endpoint,
        ref_audio=ref_audio,
        prompt_text=prompt_text,
        prompt_lang=prompt_lang,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    raw = tts.synth(TtsRequest(text=text, lang=lang or "zh", voice=voice or "", dest=dest), control=control)
    from bilingual_sub.adapters.ffmpeg import is_pcm_wav, to_pcm_wav

    if dest.suffix.lower() in {".wav", ".wave"} and not is_pcm_wav(Path(raw)):
        return to_pcm_wav(Path(raw), dest, control=control)
    return Path(raw)
