from pathlib import Path
from unittest.mock import patch

from bilingual_sub.adapters.asr_protocol import AsrResult
from bilingual_sub.adapters.whisperx_backend import (
    WhisperXBackend,
    ensure_whisperx_runtime,
    whisperx_available,
)
from bilingual_sub.models import JobConfig, Segment


def test_gpu_oom_reduces_batch_before_cpu(monkeypatch):
    from types import SimpleNamespace

    from bilingual_sub.adapters import whisperx_worker as worker
    batches, devices = [], []
    def transcribe(audio, **kwargs):
        batches.append(kwargs['batch_size'])
        if kwargs['batch_size'] > 2:
            raise RuntimeError('CUDA out of memory')
        return {'language': 'zh', 'segments': []}
    def load(name, device, **kwargs):
        devices.append(device)
        return SimpleNamespace(transcribe=transcribe)
    monkeypatch.setattr(worker, 'release_accelerator', lambda _: None)
    result, device = worker.transcribe_audio(SimpleNamespace(load_model=load), 'medium', [], 'cuda', 'zh')
    assert batches == [8, 4, 2] and devices == ['cuda'] and device == 'cuda'
    assert result['language'] == 'zh'


def test_gpu_load_failure_retries_cpu_but_network_failure_does_not(monkeypatch):
    from types import SimpleNamespace

    import pytest

    from bilingual_sub.adapters import whisperx_worker as worker
    devices = []
    def load(name, device, **kwargs):
        devices.append(device)
        if device == 'cuda':
            raise RuntimeError('CUDA out of memory')
        return SimpleNamespace(transcribe=lambda *a, **kw: {'segments': []})
    monkeypatch.setattr(worker, 'release_accelerator', lambda _: None)
    assert worker.transcribe_audio(SimpleNamespace(load_model=load), 'medium', [], 'cuda', 'zh')[1] == 'cpu'
    assert devices == ['cuda', 'cpu']
    def network(*a, **kw):
        raise OSError('model download connection failed')
    with pytest.raises(OSError, match='connection'):
        worker.transcribe_audio(SimpleNamespace(load_model=network), 'medium', [], 'cuda', 'zh')


def test_backend_protocol_shape():
    assert hasattr(WhisperXBackend, "transcribe")
    assert hasattr(WhisperXBackend, "available")
    backend = WhisperXBackend()
    assert backend.name == "whisperx"
    assert hasattr(backend, "transcribe") and hasattr(backend, "available")


def test_verified_interpreter_is_reused(tmp_path, monkeypatch):
    import bilingual_sub.adapters.whisperx_backend as wx

    calls = []
    python = tmp_path / "python.exe"
    def find(control=None):
        calls.append(True)
        return python if len(calls) == 1 else None
    monkeypatch.setattr(wx, "find_whisperx_python", find)
    monkeypatch.setattr(wx, "run_asr_worker", lambda *a, **k: {
        "language": "en", "segments": [{"start": 0, "end": 1, "text": "hello", "words": []}]})
    wav = tmp_path / "source.wav"
    wav.write_bytes(b"fixture")
    backend = wx.WhisperXBackend()
    assert backend.available() and backend.available()
    result = backend.transcribe(wav, model_name="small", language="en", device="auto", out_json=tmp_path / "asr.json")
    assert result.segments[0].text == "hello" and len(calls) == 1


def test_cold_import_has_time_and_keeps_cancellation(monkeypatch, tmp_path):
    import subprocess

    import pytest

    from bilingual_sub.adapters import whisper_backend as wb
    from bilingual_sub.core.control import JobControl, JobStopped

    def probe(args, **kwargs):
        assert kwargs["timeout"] >= 60
        assert kwargs["control"] is control
        return subprocess.CompletedProcess(args, 0, "", "")
    control = JobControl()
    monkeypatch.setattr(wb, "_run_probe", probe)
    assert wb._python_has_module(tmp_path / "python.exe", "whisperx", control)
    control.stop()
    with pytest.raises(JobStopped):
        wb._python_has_module(tmp_path / "python.exe", "whisperx", control)


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
    monkeypatch.setattr("bilingual_sub.adapters.whisperx_backend.find_whisperx_python", lambda control=None: None)
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
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda src, path, **k: path.write_bytes(b"audio fixture"))
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work, **kw: src)

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
        lambda self, control=None: False,
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


def test_pipeline_whisperx_gets_normalized_language(tmp_path, monkeypatch):
    from bilingual_sub.adapters.asr_protocol import AsrResult
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue
    from bilingual_sub.pipeline import run

    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"x")
    seen = {"language": None}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda src, path, **k: path.write_bytes(b"audio fixture"))
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work, **kw: src)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.write_subtitles",
        lambda cues, preset, ass_path, srt_path, **k: (
            Path(ass_path).write_text("[Script Info]\n", encoding="utf-8"),
            Path(srt_path).write_text("1\n", encoding="utf-8"),
        ),
    )
    monkeypatch.setattr(
        "bilingual_sub.adapters.whisperx_backend.WhisperXBackend.available",
        lambda self, control=None: True,
    )

    def fake_x(self, wav, **kwargs):
        seen["language"] = kwargs.get("language")
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text(
                '{"language":"zh","segments":[{"start":0.2,"end":1.6,"text":"大家好"}]}',
                encoding="utf-8",
            )
        return AsrResult(
            language="zh",
            segments=[Segment(0.2, 1.6, "大家好")],
            detected_language="zh",
            backend="whisperx",
        )

    monkeypatch.setattr("bilingual_sub.adapters.whisperx_backend.WhisperXBackend.transcribe", fake_x)

    cfg = JobConfig(
        input_video=clip,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
        asr_backend="whisperx",
        source_lang="zh-Hant",
        target_lang="zh",
        subtitle_mode="single:zh",
    )
    run(cfg)
    assert seen["language"] == "zh"
