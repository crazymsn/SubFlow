import json
from pathlib import Path

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.adapters.ffmpeg import FfmpegError
from bilingual_sub.config import AppSettings
from bilingual_sub.core.audio import detect_silences
from bilingual_sub.core.control import JobStopped
from bilingual_sub.models import JobConfig, Segment


@pytest.fixture
def job(tmp_path, monkeypatch):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"old input")
    cfg = JobConfig(video, None, tmp_path / "out.srt", tmp_path / "work", burn=False,
                    source_lang="en", target_lang="en", subtitle_mode="single:en")
    settings = AppSettings()
    calls = {"asr": 0, "silence": 0}
    monkeypatch.setattr(p, "probe_video", lambda path: {
        "duration": 3, "has_audio": True, "width": 640, "height": 480})
    def extract(source, path, **kwargs):
        path.write_bytes(b"audio fixture")
    def silence(*args, **kwargs):
        calls["silence"] += 1
        return []
    def asr(wav, **kwargs):
        calls["asr"] += 1
        seg = Segment(0.2, 1.6, f"recognized version {calls['asr']}")
        kwargs["out_json"].write_text(json.dumps({"segments": [seg.__dict__]}))
        return [seg]
    monkeypatch.setattr(p, "extract_wav", extract)
    monkeypatch.setattr(p, "detect_silences", silence)
    monkeypatch.setattr(p, "transcribe", asr)
    return cfg, settings, calls, asr, extract


def test_failed_new_input_cannot_resume_from_old_transcript(job, monkeypatch):
    cfg, settings, calls, asr, _ = job
    first = p.run(cfg, settings)
    previous_transcript = (cfg.work_dir / "transcript.json").read_bytes()
    cfg.input_video.write_bytes(b"a different input video")
    def fail(*args, **kwargs):
        raise RuntimeError("recognition failed")
    monkeypatch.setattr(p, "transcribe", fail)
    with pytest.raises(RuntimeError, match="recognition failed"):
        p.run(cfg, settings)
    state = json.loads((cfg.work_dir / "job_state.json").read_text())
    assert state["completed_stage"] == "silence" and state["job_id"] != first.job_id
    assert (cfg.work_dir / "transcript.json").read_bytes() == previous_transcript
    cfg.resume_from = "build_cues"
    with pytest.raises(ValueError, match="尚未完成"):
        p.run(cfg, settings)
    assert (cfg.work_dir / "transcript.json").read_bytes() == previous_transcript
    cfg.resume_from = "transcribe"
    monkeypatch.setattr(p, "transcribe", asr)
    second = p.run(cfg, settings)
    assert second.job_id != first.job_id and calls["asr"] == 2
    assert "version 2" in cfg.output_srt.read_text()


def test_cancelled_rewind_cannot_skip_the_failed_stage(job, monkeypatch):
    cfg, settings, calls, _, extract = job
    p.run(cfg, settings)
    cfg.resume_from = "extract"
    def cancel(*args, **kwargs):
        raise JobStopped()
    monkeypatch.setattr(p, "extract_wav", cancel)
    with pytest.raises(JobStopped):
        p.run(cfg, settings)
    state = json.loads((cfg.work_dir / "job_state.json").read_text())
    assert state["stage"] == "stopped" and state["completed_stage"] == "ingest"
    cfg.resume_from = "transcribe"
    with pytest.raises(ValueError, match="尚未完成"):
        p.run(cfg, settings)
    cfg.resume_from = "extract"
    monkeypatch.setattr(p, "extract_wav", extract)
    p.run(cfg, settings)
    assert calls == {"asr": 2, "silence": 2}


def test_corrupt_finished_cues_trigger_processing_instead_of_empty_export(job):
    cfg, settings, calls, _, _ = job
    settings.video.work_dir = str(cfg.work_dir)
    cfg.work_dir = Path("auto")
    first = p.run(cfg, settings)
    (first.report_path.parent / "cues.bilingual.json").write_text("{}")
    second = p.run(cfg, settings)
    assert not second.reused and calls["asr"] == 2
    assert "version 2" in cfg.output_srt.read_text()


def test_silence_detection_surfaces_actual_ffmpeg_failure(tmp_path):
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not an audio file")
    with pytest.raises(FfmpegError):
        detect_silences(broken)
