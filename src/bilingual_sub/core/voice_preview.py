"""Short TTS audition clips. Sample text follows dub target language, not UI locale."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from bilingual_sub.adapters.tts.base import TtsRequest, select_tts
from bilingual_sub.adapters.tts.model_identity import ModelSnapshot, retry_model_change
from bilingual_sub.config import user_config_dir
from bilingual_sub.core.audio_cache import cache_digest, produce_audio
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.output_guard import validate_outputs
from bilingual_sub.core.resource_claims import claim_resources

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
    digest = hashlib.sha256(json.dumps([provider, voice, lang, extra], ensure_ascii=False).encode()).hexdigest()[:16]
    return preview_cache_dir() / f"{token[:64]}-{digest}.wav"


@retry_model_change
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
    lang, voice = lang or "zh", voice or ""
    text = preview_sample(lang)
    engine = (provider or "gptsovits").strip().lower()
    if engine in {"openai", "azure"}:
        engine = "gptsovits"
    tts = select_tts(
        engine,
        endpoint=endpoint,
        ref_audio=ref_audio,
        prompt_text=prompt_text,
        prompt_lang=prompt_lang,
    )
    effective_ref = str(getattr(tts, "ref_audio", ref_audio) or "")
    model = ModelSnapshot(engine, str(getattr(tts, "endpoint", endpoint) or ""))
    booted = False
    if engine == "gptsovits" and model.revision is None:
        from bilingual_sub.adapters.tts.gptsovits_runtime import ensure_running

        ensure_running(model.endpoint or None, wait_sec=300, control=control)
        model = ModelSnapshot(engine, model.endpoint)
        booted = True
    def identity():
        return tts_job_fingerprint(engine, voice=voice,
            **{key: str(getattr(tts, key, fallback) or "") for key, fallback in
               (("endpoint", endpoint), ("ref_audio", ref_audio),
                ("prompt_text", prompt_text), ("prompt_lang", prompt_lang))})
    initial = identity()
    key = hashlib.sha256(json.dumps(["preview-v3", initial, model.cache_id, text, lang, voice], ensure_ascii=False).encode()).hexdigest()
    dest = dest or preview_cache_path(voice, lang, engine, key)
    record = dest.with_suffix(dest.suffix + ".json")
    reads = [Path(effective_ref).expanduser()] if effective_ref else []
    validate_outputs({"试听音频": dest, "试听记录": record}, reads)
    checkpoint = control.wait_if_paused if control else None
    with claim_resources(reads=reads, writes=[dest, record], checkpoint=checkpoint):
        if identity() != initial:
            raise RuntimeError("试听准备期间参考音频或设置发生变化，请重试")
        cached = cache_digest(dest, key, control)
        if cached and identity() == initial:
            model.check()
            return dest
        if engine == "gptsovits" and not booted:
            from bilingual_sub.adapters.tts.gptsovits_runtime import ensure_running

            ensure_running(str(getattr(tts, "endpoint", endpoint) or "") or None, wait_sec=300, control=control)
        def synth(pending):
            model.check()
            tts.synth(TtsRequest(text=text, lang=lang, voice=voice, dest=pending,
                                 model_revision=model.revision or ""), control=control)
            model.check()
            if identity() != initial:
                raise RuntimeError("试听合成期间参考音频或设置发生变化，请重试")
        produce_audio(dest, key, synth, control)
    return dest
