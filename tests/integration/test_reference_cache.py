import os
from pathlib import Path

import pytest

from bilingual_sub.adapters.tts import gptsovits_runtime as rt
from bilingual_sub.adapters.tts.base import TtsUnavailable
from bilingual_sub.core.control import JobStopped
from bilingual_sub.models import Cue


def test_reference_tracks_source_content_and_extraction_window(tmp_path, monkeypatch, pcm_wav):
    source, dest = tmp_path / "source.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(5))
    calls = []
    original = rt.extract_ref_audio
    def extract(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(rt, "extract_ref_audio", extract)
    rt.ensure_ref_audio(source, dest)
    rt.ensure_ref_audio(source, dest)
    assert len(calls) == 1
    stamp = source.stat()
    data = bytearray(source.read_bytes())
    data[-2:] = b"\x10\x00"
    source.write_bytes(data)
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    rt.ensure_ref_audio(source, dest)
    assert len(calls) == 2
    rt.ensure_ref_audio(source, dest, [Cue(1, 4, "reference phrase")])
    assert len(calls) == 3 and calls[-1]["start"] == 1 and calls[-1]["duration"] == 3


def test_unrecorded_or_replaced_reference_is_regenerated(tmp_path, pcm_wav):
    source, dest = tmp_path / "source.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(5))
    unrelated = pcm_wav(3)
    dest.write_bytes(unrelated)
    rt.ensure_ref_audio(source, dest)
    expected = dest.read_bytes()
    assert expected != unrelated
    dest.write_bytes(unrelated)
    rt.ensure_ref_audio(source, dest)
    assert dest.read_bytes() == expected


def test_short_reference_extraction_keeps_previous_audio(tmp_path, pcm_wav):
    source, dest = tmp_path / "short.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(1))
    old = pcm_wav(5)
    dest.write_bytes(old)
    with pytest.raises(TtsUnavailable, match="3–10"):
        rt.extract_ref_audio(source, dest)
    assert dest.read_bytes() == old
    assert not list(tmp_path.glob(".subflow-output-*"))


def test_three_second_source_is_not_shortened_by_an_arbitrary_offset(tmp_path, pcm_wav):
    from bilingual_sub.core.audio_cache import pcm_duration

    source, dest = tmp_path / "short-valid.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(3.1))
    rt.ensure_ref_audio(source, dest)
    assert 3 <= pcm_duration(dest) <= 3.11


def test_cancelled_reference_extraction_keeps_previous_audio(tmp_path, monkeypatch, pcm_wav):
    source, dest = tmp_path / "source.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(5))
    old = pcm_wav(3)
    dest.write_bytes(old)
    def fail(args, **kwargs):
        Path(args[-1]).write_bytes(b"partial")
        raise JobStopped()
    monkeypatch.setattr("bilingual_sub.adapters.ffmpeg.run_cmd", fail)
    with pytest.raises(JobStopped):
        rt.extract_ref_audio(source, dest)
    assert dest.read_bytes() == old and not list(tmp_path.glob(".subflow-output-*"))


def test_source_changed_during_reference_extraction_is_not_committed(tmp_path, monkeypatch, pcm_wav):
    source, dest = tmp_path / "source.wav", tmp_path / "reference.wav"
    source.write_bytes(pcm_wav(5))
    old = pcm_wav(3)
    dest.write_bytes(old)
    original = rt.extract_ref_audio
    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        source.write_bytes(pcm_wav(6))
        return result
    monkeypatch.setattr(rt, "extract_ref_audio", change)
    with pytest.raises(RuntimeError, match="源视频发生变化"):
        rt.ensure_ref_audio(source, dest)
    assert dest.read_bytes() == old and not dest.with_suffix(".wav.json").exists()


@pytest.mark.parametrize("extractor", [rt.extract_ref_audio, rt.ensure_ref_audio])
def test_reference_output_cannot_overwrite_source(tmp_path, pcm_wav, extractor):
    source = tmp_path / "source.wav"
    old = pcm_wav(5)
    source.write_bytes(old)
    with pytest.raises(ValueError, match="覆盖输入"):
        extractor(source, source)
    assert source.read_bytes() == old


def test_preview_worker_keys_automatic_reference_by_full_source_content(tmp_path, monkeypatch, pcm_wav):
    from bilingual_sub.gui.workers import VoicePreviewWorker

    source, cache = tmp_path / "source.wav", tmp_path / "references"
    cache.mkdir()
    source.write_bytes(pcm_wav(5))
    monkeypatch.setattr("bilingual_sub.core.voice_preview.preview_cache_dir", lambda: cache)
    monkeypatch.setattr("bilingual_sub.core.voice_preview.synth_voice_preview", lambda **kw: Path(kw["ref_audio"]))
    results, errors = [], []
    def run():
        worker = VoicePreviewWorker("gptsovits", "", "en", video=source)
        worker.ok.connect(results.append)
        worker.fail.connect(errors.append)
        worker.run()
    run()
    run()
    stamp = source.stat()
    data = bytearray(source.read_bytes())
    data[-2:] = b"\x10\x00"
    source.write_bytes(data)
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    run()
    assert not errors and len(results) == 3
    assert results[0] == results[1] and results[2] != results[0]


def test_preview_worker_respects_active_source_writer(tmp_path, monkeypatch, pcm_wav):
    from bilingual_sub.core.resource_claims import claim_resources
    from bilingual_sub.gui.workers import VoicePreviewWorker

    source = tmp_path / "source.wav"
    source.write_bytes(pcm_wav(5))
    monkeypatch.setattr("bilingual_sub.core.voice_preview.preview_cache_dir", lambda: tmp_path)
    monkeypatch.setattr("bilingual_sub.core.voice_preview.synth_voice_preview", lambda **kw: pytest.fail("must reject busy source"))
    errors = []
    worker = VoicePreviewWorker("gptsovits", "", "en", video=source)
    worker.fail.connect(errors.append)
    with claim_resources(reads=[], writes=[source]):
        worker.run()
    assert len(errors) == 1 and "另一任务" in errors[0]
