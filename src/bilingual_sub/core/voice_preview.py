"""Short TTS audition clips. Sample text follows dub target language, not UI locale."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from bilingual_sub.adapters.tts.base import TtsRequest, select_tts
from bilingual_sub.adapters.tts.model_identity import ModelSnapshot, retry_model_change
from bilingual_sub.adapters.tts.routing import preview_engine_session
from bilingual_sub.config import user_config_dir
from bilingual_sub.core.audio_cache import cache_digest, produce_audio
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.dub_progress import DubProgress, Progress
from bilingual_sub.core.output_guard import validate_outputs
from bilingual_sub.core.resource_claims import claim_resources

PREVIEW_SAMPLES = {
    "zh": "您好，请问有什么能帮您？",
    "zh-Hans": "您好，请问有什么能帮您？",
    "zh-Hant": "您好，請問有什麼能幫您？",
    "en": "Hello, how can I help you?",
    "ja": "こんにちは。何かお手伝いできることはありますか？",
    "es": "Hola, ¿en qué puedo ayudarle?",
    "ru": "Здравствуйте, чем я могу вам помочь?",
    "fr": "Bonjour, comment puis-je vous aider ?",
    "de": "Guten Tag, wie kann ich Ihnen helfen?",
    "ko": "안녕하세요. 무엇을 도와드릴까요?",
    "yue": "您好，請問有咩可以幫到您？",
}

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def preview_sample(lang: str) -> str:
    code = (lang or "zh").strip().replace("_", "-").lower() or "zh"
    if code.startswith("zh"):
        traditional = any(part in {"hant", "tw", "hk", "mo"} for part in code.split("-"))
        return PREVIEW_SAMPLES["zh-Hant"] if traditional else PREVIEW_SAMPLES["zh"]
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
@preview_engine_session
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
    sample_text: str = "",
    control: JobControl | None = None,
    on_progress: Progress = None,
) -> Path:
    from bilingual_sub.adapters.tts.gptsovits import tts_job_fingerprint
    from bilingual_sub.adapters.tts.routing import (
        ensure_running,
        provider_endpoint,
        resolve_provider,
    )

    if control:
        control.check()
    lang, voice = lang or "zh", voice or ""
    text = sample_text.strip() or preview_sample(lang)
    engine = (provider or "gptsovits").strip().lower()
    if engine in {"openai", "azure"}:
        engine = "gptsovits"
    requested_engine = engine
    engine = resolve_provider(engine, lang, prompt_lang)
    endpoint = (endpoint if requested_engine == engine and engine.startswith("qwen3") and endpoint
                else provider_endpoint(engine, endpoint))
    tts = select_tts(
        engine,
        endpoint=endpoint,
        ref_audio=ref_audio,
        prompt_text=prompt_text,
        prompt_lang=prompt_lang,
    )
    effective_ref = str(getattr(tts, "ref_audio", ref_audio) or "")
    validate_reference = getattr(tts, "_ref_path", None)
    if callable(validate_reference):
        validate_reference()
    model = ModelSnapshot(engine, str(getattr(tts, "endpoint", endpoint) or ""))
    booted = False
    if engine in {"gptsovits", "qwen3", "qwen3-native"} and model.revision is None:
        with DubProgress(on_progress) as preparation:
            preparation.set("prepare", 0, 0, 0)
            ensure_running(engine, model.endpoint, wait_sec=300, control=control)
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
        if engine in {"gptsovits", "qwen3", "qwen3-native"} and not booted:
            ensure_running(engine, str(getattr(tts, "endpoint", endpoint) or ""), wait_sec=300, control=control)
        def synth(pending):
            model.check()
            tts.synth(TtsRequest(text=text, lang=lang, voice=voice, dest=pending,
                                 model_revision=model.revision or ""), control=control)
            model.check()
            if identity() != initial:
                raise RuntimeError("试听合成期间参考音频或设置发生变化，请重试")
        with DubProgress(on_progress) as progress:
            progress.set("synth", 1, 1, 0)
            produce_audio(dest, key, synth, control)
    return dest
