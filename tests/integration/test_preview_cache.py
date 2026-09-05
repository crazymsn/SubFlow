import json
import os

import pytest

from bilingual_sub.core import voice_preview as p
from bilingual_sub.core.control import JobStopped
from bilingual_sub.core.resource_claims import claim_resources


@pytest.fixture
def preview(tmp_path, monkeypatch, pcm_wav):
    calls = {"synth": 0, "boot": 0}
    class Provider:
        def synth(self, req, **kwargs):
            calls["synth"] += 1
            req.dest.write_bytes(pcm_wav(0.2 + calls["synth"] / 10))
            return req.dest
    provider = Provider()
    monkeypatch.setattr(p, "select_tts", lambda *a, **kw: provider)
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime.ensure_running",
                        lambda *a, **kw: calls.update(boot=calls["boot"] + 1))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(pcm_wav(1))
    kwargs = dict(provider="gptsovits", voice="", lang="en", dest=tmp_path / "preview.wav",
                  ref_audio=str(ref), endpoint="http://127.0.0.1:9880", prompt_text="reference")
    return kwargs, calls, provider


@pytest.mark.parametrize("field,value", [("lang", "zh"), ("voice", "changed"),
    ("endpoint", "http://127.0.0.1:9881"), ("prompt_text", "changed"), ("prompt_lang", "ja")])
def test_explicit_preview_destination_is_bound_to_request(preview, field, value):
    kwargs, calls, _ = preview
    first = p.synth_voice_preview(**kwargs).read_bytes()
    p.synth_voice_preview(**kwargs)
    assert calls == {"synth": 1, "boot": 1}
    kwargs[field] = value
    assert p.synth_voice_preview(**kwargs).read_bytes() != first
    assert calls == {"synth": 2, "boot": 2}


@pytest.mark.parametrize("which", ["reference", "preview"])
def test_changed_valid_audio_with_same_metadata_is_not_reused(preview, which):
    from pathlib import Path
    kwargs, calls, _ = preview
    p.synth_voice_preview(**kwargs)
    path = Path(kwargs["ref_audio"]) if which == "reference" else kwargs["dest"]
    stamp = path.stat()
    data = bytearray(path.read_bytes())
    data[-2:] = b"\x10\x00"
    path.write_bytes(data)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    p.synth_voice_preview(**kwargs)
    assert calls["synth"] == 2


def test_changed_preview_sample_invalidates_explicit_cache(preview, monkeypatch):
    kwargs, calls, _ = preview
    p.synth_voice_preview(**kwargs)
    monkeypatch.setitem(p.PREVIEW_SAMPLES, "en", "A different preview sample.")
    p.synth_voice_preview(**kwargs)
    assert calls["synth"] == 2


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_preview_replacement_preserves_previous_audio(preview, monkeypatch, cancel):
    kwargs, _, provider = preview
    path = p.synth_voice_preview(**kwargs)
    before, manifest = path.read_bytes(), path.with_suffix(".wav.json").read_bytes()
    kwargs["lang"] = "zh"
    def fail(req, **kw):
        req.dest.write_bytes(b"incomplete")
        if cancel:
            raise JobStopped()
    monkeypatch.setattr(provider, "synth", fail)
    with pytest.raises((ValueError, JobStopped)):
        p.synth_voice_preview(**kwargs)
    assert path.read_bytes() == before and path.with_suffix(".wav.json").read_bytes() == manifest
    assert not list(path.parent.glob(".subflow-output-*"))


@pytest.mark.parametrize("target", ["audio", "record"])
def test_preview_protects_reference_from_output(preview, target):
    from pathlib import Path
    kwargs, calls, _ = preview
    dest = kwargs["dest"]
    ref = dest if target == "audio" else dest.with_suffix(".wav.json")
    original = Path(kwargs["ref_audio"]).read_bytes()
    ref.write_bytes(original)
    kwargs["ref_audio"] = str(ref)
    with pytest.raises(ValueError, match="覆盖输入"):
        p.synth_voice_preview(**kwargs)
    assert ref.read_bytes() == original and calls["synth"] == 0


def test_preview_claims_destination_before_using_cache(preview):
    kwargs, calls, _ = preview
    p.synth_voice_preview(**kwargs)
    with claim_resources(reads=[], writes=[kwargs["dest"]]):
        with pytest.raises(RuntimeError, match="另一任务"):
            p.synth_voice_preview(**kwargs)
    assert calls["synth"] == 1


def test_preview_reference_change_during_synthesis_is_not_committed(preview, monkeypatch):
    from pathlib import Path
    kwargs, _, provider = preview
    original = provider.synth
    def change(req, **kw):
        original(req, **kw)
        Path(kwargs["ref_audio"]).write_bytes(b"changed reference")
    monkeypatch.setattr(provider, "synth", change)
    with pytest.raises(RuntimeError, match="参考音频"):
        p.synth_voice_preview(**kwargs)
    assert not kwargs["dest"].exists()


def test_preview_paths_hash_unsanitized_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "preview_cache_dir", lambda: tmp_path)
    assert p.preview_cache_path("甲", "en") != p.preview_cache_path("乙", "en")
    assert p.preview_cache_path("a/b", "en") != p.preview_cache_path("a?b", "en")


def test_old_unrecorded_valid_preview_is_regenerated(preview, pcm_wav):
    kwargs, calls, _ = preview
    kwargs["dest"].write_bytes(pcm_wav(1))
    p.synth_voice_preview(**kwargs)
    assert calls["synth"] == 1
    assert json.loads(kwargs["dest"].with_suffix(".wav.json").read_text())["schema"] == 1


def test_switching_loaded_model_invalidates_preview(preview, monkeypatch):
    kwargs, calls, _ = preview
    before = p.synth_voice_preview(**kwargs).read_bytes()
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: "b" * 32)
    assert p.synth_voice_preview(**kwargs).read_bytes() != before
    assert calls["synth"] == 2


def test_unidentified_service_never_reuses_preview(preview, monkeypatch):
    kwargs, calls, _ = preview
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: None)
    p.synth_voice_preview(**kwargs)
    p.synth_voice_preview(**kwargs)
    assert calls["synth"] == 2


@pytest.mark.parametrize("continuous", [False, True])
def test_preview_model_change_retries_without_overwriting_old_output(preview, monkeypatch, continuous):
    from bilingual_sub.adapters.tts.model_identity import ModelChanged
    kwargs, calls, provider = preview
    old = p.synth_voice_preview(**kwargs).read_bytes()
    revision = [1]
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: f"{revision[0]:032x}")
    original = provider.synth
    def change(req, **kw):
        original(req, **kw)
        if continuous or revision[0] == 1:
            revision[0] += 1
    monkeypatch.setattr(provider, "synth", change)
    if continuous:
        with pytest.raises(ModelChanged):
            p.synth_voice_preview(**kwargs)
        assert kwargs["dest"].read_bytes() == old
    else:
        assert p.synth_voice_preview(**kwargs).read_bytes() != old
    assert calls["synth"] == 3
