"""Real PCM/FFmpeg fitting with controlled synthesis and failure injection."""
import json
import os

import pytest

from bilingual_sub.core import dub as d
from bilingual_sub.core.audio_cache import cache_digest, pcm_duration, produce_audio
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.models import Cue


@pytest.fixture
def job(tmp_path, monkeypatch, pcm_wav):
    calls = {"synth": 0, "fit": 0}
    class Provider:
        name = "fake"
        def synth(self, request, **kwargs):
            calls["synth"] += 1
            request.dest.write_bytes(pcm_wav(0.6 + calls["synth"] * 0.1))
            return request.dest
    provider = Provider()
    original_fit = d.fit_clip
    def fit(*args, **kwargs):
        calls["fit"] += 1
        return original_fit(*args, **kwargs)
    monkeypatch.setattr(d, "fit_clip", fit)
    mixed = []
    def mix(video, clips, output, duration, **kwargs):
        mixed.append(clips)
        output.write_bytes(b"complete movie")
    monkeypatch.setattr(d, "mix_timeline", mix)
    def run():
        return d.dub_cues([Cue(0, 1, "你好", "Hello")], video=tmp_path / "input.mp4",
                          work=tmp_path, output=tmp_path / "out.mp4", provider=provider,
                          lang="en", voice="", duration=2)
    return run, calls, provider, mixed


def test_verified_audio_is_reused_and_replaced_raw_rebuilds_fitted(job, tmp_path, pcm_wav):
    run, calls, _, mixed = job
    run()
    first_fit = mixed[-1][0][1]
    run()
    assert calls == {"synth": 1, "fit": 1}
    raw = next(p for p in (tmp_path / "tts").glob("*.wav") if not p.name.endswith(".fit.wav"))
    stamp = raw.stat()
    # Preserve length and timestamps while changing valid PCM samples.
    data = bytearray(raw.read_bytes())
    data[-2:] = b"\x10\x00"
    raw.write_bytes(data)
    os.utime(raw, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    run()
    assert calls == {"synth": 2, "fit": 2}
    assert mixed[-1][0][1] != first_fit
    assert pcm_duration(raw) == pytest.approx(0.8)


def test_all_clips_restart_after_cpu_fallback_model_reload(job, tmp_path, monkeypatch):
    _, calls, provider, _ = job
    provider.name = "gptsovits"
    revision, seen = ["a" * 32], []
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: revision[0])
    original = provider.synth
    def change(req, **kw):
        seen.append((req.text, req.model_revision))
        original(req, **kw)
        if len(seen) == 2:
            revision[0] = "b" * 32
    monkeypatch.setattr(provider, "synth", change)
    d.dub_cues([Cue(0, 1, "一", "one"), Cue(1, 2, "二", "two")], video=tmp_path / "in.mp4",
               work=tmp_path, output=tmp_path / "out.mp4", provider=provider, lang="en", voice="", duration=3)
    assert seen == [("one", "a" * 32), ("two", "a" * 32), ("one", "b" * 32), ("two", "b" * 32)]
    assert provider.cache_model_revision == "b" * 32 and calls["synth"] == 4


def test_model_change_during_mix_never_publishes_partial_movie(job, tmp_path, monkeypatch):
    from bilingual_sub.adapters.tts.model_identity import ModelChanged
    run, _, provider, _ = job
    provider.name = "gptsovits"
    revision = [1]
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: f"{revision[0]:032x}")
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous movie")
    def mix(video, clips, output, duration, **kw):
        output.write_bytes(b"mixed using old model")
        revision[0] += 1
    monkeypatch.setattr(d, "mix_timeline", mix)
    with pytest.raises(ModelChanged):
        run()
    assert output.read_bytes() == b"previous movie"


@pytest.mark.parametrize("target", ["video", "reference"])
def test_staged_dub_cannot_overwrite_source_or_reference(job, tmp_path, target):
    _, calls, provider, _ = job
    video, reference = tmp_path / "input.mp4", tmp_path / "ref.wav"
    video.write_bytes(b"original movie")
    reference.write_bytes(b"original voice")
    provider.ref_audio = str(reference)
    output = video if target == "video" else reference
    original = output.read_bytes()
    with pytest.raises(ValueError, match="覆盖输入"):
        d.dub_cues([Cue(0, 1, "一", "one")], video=video, work=tmp_path, output=output,
                   provider=provider, lang="en", voice="", duration=2)
    assert output.read_bytes() == original and calls["synth"] == 0


@pytest.mark.parametrize("damage", ["replace", "missing_record", "bad_record", "wrong_key"])
def test_damaged_fit_rebuilt_without_resynthesis(job, damage, pcm_wav):
    run, calls, _, mixed = job
    run()
    fitted = mixed[-1][0][1]
    record = fitted.with_suffix(".wav.json")
    if damage == "replace":
        fitted.write_bytes(pcm_wav(0.2))
    elif damage == "missing_record":
        record.unlink()
    elif damage == "bad_record":
        record.write_text("{")
    else:
        data = json.loads(record.read_text())
        data["key"] = "different request"
        record.write_text(json.dumps(data))
    run()
    assert calls == {"synth": 1, "fit": 2}
    assert pcm_duration(fitted) > 0.4


def test_incomplete_synthesis_is_not_committed_or_reused(job, tmp_path, monkeypatch, pcm_wav):
    run, calls, provider, _ = job
    real_synth = provider.synth
    monkeypatch.setattr(provider, "synth", lambda req, **kw: req.dest.write_bytes(pcm_wav(0.7)[:-10]))
    with pytest.raises(ValueError, match="不完整"):
        run()
    assert not list((tmp_path / "tts").iterdir())
    monkeypatch.setattr(provider, "synth", real_synth)
    run()
    assert calls == {"synth": 1, "fit": 1}


def test_fit_input_changed_during_conversion_is_not_certified(job, tmp_path, monkeypatch, pcm_wav):
    run, _, _, _ = job
    original = d.fit_clip
    def change(src, *args, **kwargs):
        original(src, *args, **kwargs)
        src.write_bytes(pcm_wav(0.2))
    monkeypatch.setattr(d, "fit_clip", change)
    with pytest.raises(RuntimeError, match="拟合期间"):
        run()
    assert not list((tmp_path / "tts").glob("*.fit.wav*"))
    assert not (tmp_path / "out.mp4").exists()


def test_changed_reference_during_synthesis_does_not_commit_under_old_identity(job, tmp_path, monkeypatch):
    run, _, provider, _ = job
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"reference one")
    provider.ref_audio = str(reference)
    original = provider.synth
    def change(req, **kwargs):
        result = original(req, **kwargs)
        reference.write_bytes(b"reference two")
        return result
    monkeypatch.setattr(provider, "synth", change)
    with pytest.raises(RuntimeError, match="合成期间参考音频"):
        run()
    assert not list((tmp_path / "tts").iterdir())


def test_manifest_commit_failure_does_not_certify_new_audio(tmp_path, monkeypatch, pcm_wav):
    from bilingual_sub.core import audio_cache
    path = tmp_path / "raw.wav"
    produce_audio(path, "request", lambda p: p.write_bytes(pcm_wav(0.6)))
    def fail(*args, **kwargs):
        raise OSError("manifest replace failed")
    monkeypatch.setattr(audio_cache, "write_json", fail)
    with pytest.raises(OSError, match="manifest replace"):
        produce_audio(path, "request", lambda p: p.write_bytes(pcm_wav(0.8)))
    assert cache_digest(path, "request") is None


def test_fitted_audio_changed_later_in_job_is_rejected_before_mix(tmp_path, monkeypatch, pcm_wav):
    calls = 0
    class Provider:
        name = "fake"
        def synth(self, req, **kwargs):
            nonlocal calls
            calls += 1
            req.dest.write_bytes(pcm_wav(0.6))
            if calls == 2:
                first = next((tmp_path / "tts").glob("*.fit.wav"))
                first.write_bytes(pcm_wav(0.2))
            return req.dest
    monkeypatch.setattr(d, "mix_timeline", lambda *a, **kw: pytest.fail("must reject before mix"))
    with pytest.raises(RuntimeError, match="混音前配音音频"):
        d.dub_cues([Cue(0, 1, "你好", "Hello"), Cue(1, 2, "再见", "Goodbye")],
                   video=tmp_path / "in.mp4", work=tmp_path, output=tmp_path / "out.mp4",
                   provider=Provider(), lang="en", voice="", duration=3)


@pytest.mark.parametrize("failure", ["cancel", "invalid", "error"])
def test_failed_audio_production_preserves_previous_entry(tmp_path, pcm_wav, failure):
    path = tmp_path / "audio.wav"
    old_digest = produce_audio(path, "old", lambda p: p.write_bytes(pcm_wav(0.6)))
    before = path.read_bytes()
    def fail(pending):
        pending.write_bytes(b"partial")
        if failure == "cancel":
            raise JobStopped()
        if failure == "error":
            raise OSError("provider failed")
    with pytest.raises((JobStopped, ValueError, OSError)):
        produce_audio(path, "new", fail)
    assert path.read_bytes() == before and cache_digest(path, "old") == old_digest
    assert not list(tmp_path.glob(".subflow-output-*"))


def test_audio_cache_hash_respects_stop(tmp_path, pcm_wav):
    path = tmp_path / "audio.wav"
    produce_audio(path, "key", lambda p: p.write_bytes(pcm_wav(1)))
    control = JobControl()
    control.stop()
    with pytest.raises(JobStopped):
        cache_digest(path, "key", control)


@pytest.mark.parametrize("target", [0, -1, float("nan"), float("inf")])
def test_bad_target_duration_never_replaces_fitted_audio(tmp_path, target, pcm_wav):
    raw, fitted = tmp_path / "raw.wav", tmp_path / "fit.wav"
    raw.write_bytes(pcm_wav(1))
    fitted.write_bytes(b"old")
    with pytest.raises(ValueError):
        d.fit_clip(raw, fitted, target)
    assert fitted.read_bytes() == b"old"
