from pathlib import Path
from unittest.mock import patch

from bilingual_sub.adapters.asr_protocol import AsrResult
from bilingual_sub.adapters.whisperx_backend import (
    WhisperXBackend,
    ensure_whisperx_runtime,
    whisperx_available,
)
from bilingual_sub.models import JobConfig, Segment


def test_backend_protocol_shape():
    assert hasattr(WhisperXBackend, "transcribe")
    assert hasattr(WhisperXBackend, "available")
    backend = WhisperXBackend()
    assert backend.name == "whisperx"
    assert hasattr(backend, "transcribe") and hasattr(backend, "available")


def test_asr_result_holds_segments():
    segs = [Segment(0, 1, "hi")]
    result = AsrResult(language="zh", segments=segs, detected_language="zh", backend="whisperx")
    assert result.segments[0].text == "hi"
    assert result.backend == "whisperx"


def test_default_job_still_whisper():
    cfg = JobConfig(
        input_video=Path("a.mp4"),
        output_video=None,
        output_srt=Path("a.srt"),
        work_dir=Path("w"),
    )
    assert cfg.asr_backend == "whisper"


def test_ensure_skips_when_not_frozen(monkeypatch):
    monkeypatch.delenv("SUBFLOW_PROVISION_WX", raising=False)
    monkeypatch.setattr("bilingual_sub.adapters.whisperx_backend.find_whisperx_python", lambda: None)
    monkeypatch.setattr("bilingual_sub.adapters.whisperx_backend.should_provision_whisperx", lambda: False)
    assert ensure_whisperx_runtime() is None


def test_available_false_when_import_fails():
    with patch("bilingual_sub.adapters.whisperx_backend.find_whisperx_python", return_value=None):
        assert whisperx_available() is False
    backend = WhisperXBackend()
    with patch.object(backend, "available", return_value=False):
        assert backend.available() is False


def test_pipeline_falls_back_without_calling_x(tmp_path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue
    from bilingual_sub.pipeline import run

    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")

    monkeypatch.setattr("bilingual_sub.pipeline.probe_video", lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True})
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_transcribe(wav, **kwargs):
        segs = [Segment(0.2, 1.6, "大家好")]
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return segs

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []),
    )

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("1\n", encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)
    monkeypatch.setattr(
        "bilingual_sub.adapters.whisperx_backend.WhisperXBackend.available",
        lambda self: False,
    )
    called = {"x": 0}

    def boom(*a, **k):
        called["x"] += 1
        raise AssertionError("whisperx should not run")

    monkeypatch.setattr("bilingual_sub.adapters.whisperx_backend.WhisperXBackend.transcribe", boom)

    cfg = JobConfig(
        input_video=clip,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
        asr_backend="whisperx",
    )
    result = run(cfg)
    assert result.cue_count >= 1
    assert called["x"] == 0
