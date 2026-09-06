"""Record the effective inputs to processing and rendering caches."""
import hashlib

from bilingual_sub.config import AppSettings, default_glossary_path, load_style_preset
from bilingual_sub.models import JobConfig


def processing_profile(config: JobConfig, settings: AppSettings) -> dict:
    glossary = config.glossary_path or default_glossary_path()
    return {
        "schema": 1,
        "processing_revision": "complete-translations-adaptive-dubbing-v25",
        "asr": {"backend": config.asr_backend,
                "model": config.whisper_model or settings.asr.model,
                "device": config.device or settings.asr.device,
                "language": config.source_lang},
        "silence": settings.silence.model_dump(),
        "cues": settings.cues.model_dump(),
        "translation": {"model": config.translate_model or settings.translate.model,
                        "batch_size": config.translate_batch_size or settings.translate.batch_size,
                        "max_en_chars": settings.translate.max_en_chars,
                        "refine": config.refine_translate,
                        "target": config.target_lang, "mode": config.subtitle_mode},
        "preview_minutes": config.preview_minutes or 0,
        "glossary_sha256": hashlib.sha256(glossary.read_bytes()).hexdigest() if glossary.is_file() else "",
        "glossary_generate": config.glossary_generate,
    }


def render_profile(config: JobConfig, settings: AppSettings) -> dict:
    from bilingual_sub.core.render import SUBTITLE_PACK, apply_subtitle_colors

    preset = apply_subtitle_colors(load_style_preset(config.style_preset),
                                   config.subtitle_zh_color, config.subtitle_en_color)
    return {"schema": 1, "subtitle_pack": SUBTITLE_PACK,
            "preset": preset.model_dump(), "burn": settings.burn.model_dump()}


def resume_profile_matches(saved: object, current: dict, stage: str | None) -> bool:
    """A translation rewind can change translation options, never ASR inputs."""
    if saved == current:
        return True
    if stage not in {"glossary", "translate"} or not isinstance(saved, dict):
        return False
    old_translation, new_translation = saved.get("translation"), current.get("translation")
    if not isinstance(old_translation, dict) or not isinstance(new_translation, dict):
        return False
    if old_translation.keys() != new_translation.keys():
        return False
    allowed = {"model", "batch_size", "max_en_chars", "refine"}
    old = {**saved, "translation": {k: v for k, v in old_translation.items() if k not in allowed}}
    new = {**current, "translation": {k: v for k, v in new_translation.items() if k not in allowed}}
    return old == new
