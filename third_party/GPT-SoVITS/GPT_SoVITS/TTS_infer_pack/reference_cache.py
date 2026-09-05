"""Content identities and transactional preprocessing for reference features."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def empty_prompt_cache():
    return dict(ref_audio_path=None, reference_identity=None, prompt_semantic=None, refer_spec=[],
                prompt_text=None, prompt_lang=None, prompt_version=None, phones=None,
                bert_features=None, norm_text=None, aux_ref_audio_paths=[], auxiliary_identities=[])


def invalidate_prompt_cache(model):
    if hasattr(model, "prompt_cache"):
        model.prompt_cache = empty_prompt_cache()


def audio_identity(value):
    path = Path(value).expanduser().resolve()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise OSError(f"Reference audio changed while reading: {path}")
    return str(path), digest


def set_reference(model, path):
    identity = audio_identity(path)
    previous = model.prompt_cache
    # Helpers write semantic and raw audio fields. Isolate every such write
    # until both preprocessors and the final identity check succeed.
    pending = dict(previous, refer_spec=[], aux_ref_audio_paths=[], auxiliary_identities=[])
    model.prompt_cache = pending
    try:
        model._set_prompt_semantic(path)
        model._set_ref_spec(path)
        if audio_identity(path) != identity:
            raise OSError("Reference audio changed during preprocessing")
        pending.update(ref_audio_path=path, reference_identity=identity)
    except BaseException:
        model.prompt_cache = previous
        raise


def prepare_references(model, path, auxiliary):
    previous = model.prompt_cache
    try:
        _prepare_references(model, path, auxiliary)
    except BaseException:
        model.prompt_cache = previous
        raise


def _prepare_references(model, path, auxiliary):
    path = path or model.prompt_cache.get("ref_audio_path")
    if not path:
        raise ValueError("A reference audio file is required")
    identity = audio_identity(path)
    specs = model.prompt_cache.get("refer_spec")
    if (identity != model.prompt_cache.get("reference_identity") or not specs
            or (model.is_v2pro and specs[0][1] is None)):
        model.set_ref_audio(path)
    paths = [path for path in (auxiliary or []) if path]
    identities = [audio_identity(path) for path in paths]
    if identities == model.prompt_cache.get("auxiliary_identities"):
        return
    previous = model.prompt_cache
    pending = dict(previous, refer_spec=[previous["refer_spec"][0]])
    model.prompt_cache = pending
    try:
        for path in paths:
            pending["refer_spec"].append(model._get_ref_spec(path))
        if [audio_identity(path) for path in paths] != identities:
            raise OSError("Auxiliary reference changed during preprocessing")
        if audio_identity(model.prompt_cache["ref_audio_path"]) != identity:
            raise OSError("Primary reference changed during auxiliary preprocessing")
        # _get_ref_spec also writes these fields; V3/V4 require the primary
        # reference waveform, not the last auxiliary speaker's waveform.
        for key in ("raw_audio", "raw_sr"):
            if key in previous:
                pending[key] = previous[key]
            else:
                pending.pop(key, None)
        pending.update(aux_ref_audio_paths=list(paths), auxiliary_identities=identities)
    except BaseException:
        model.prompt_cache = previous
        raise


def prepare_prompt(model, text, language, punctuation):
    text = (text or "").strip()
    if not text:
        return
    if text[-1] not in punctuation:
        text += "." if language == "en" else "。"
    cache = model.prompt_cache
    key = (text, language, model.configs.version)
    if key == (cache.get("prompt_text"), cache.get("prompt_lang"), cache.get("prompt_version")):
        return
    phones, features, normalized = model.text_preprocessor.segment_and_extract_feature_for_text(*key)
    cache.update(prompt_text=text, prompt_lang=language, prompt_version=model.configs.version,
                 phones=phones, bert_features=features, norm_text=normalized)
