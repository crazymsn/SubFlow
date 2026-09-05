import json
import os
import stat
from pathlib import Path

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.adapters.ffmpeg import find_ffmpeg, probe_video, run_cmd
from bilingual_sub.config import AppSettings
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.models import JobConfig, Segment


def replace_same_metadata(path, contents):
    before = path.stat()
    assert before.st_size == len(contents)
    path.write_bytes(contents)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


@pytest.fixture
def job(tmp_path, monkeypatch):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"original source")
    cfg = JobConfig(video, tmp_path / "output.mp4", tmp_path / "output.srt", tmp_path / "work",
                    source_lang="zh", target_lang="zh", subtitle_mode="single:zh", burn=True)
    settings = AppSettings()
    monkeypatch.setattr(p, "probe_video", lambda path: {
        "duration": 2, "has_audio": True, "width": 640, "height": 360})
    monkeypatch.setattr(p, "extract_wav", lambda source, output, **k: output.write_bytes(b"audio"))
    monkeypatch.setattr(p, "detect_silences", lambda *a, **k: [])
    calls = {"asr": 0}
    def asr(wav, **kwargs):
        calls["asr"] += 1
        segment = Segment(0.2, 1.8, "这是中文测试。")
        kwargs["out_json"].write_text(json.dumps({"language": "zh", "segments": [segment.__dict__]}))
        return [segment]
    def burn(source, ass, output, **kwargs):
        output.write_bytes(source.read_bytes() + b" subtitles")
    monkeypatch.setattr(p, "transcribe", asr)
    monkeypatch.setattr(p, "burn_subtitles", burn)
    return cfg, settings, asr, calls


@pytest.mark.parametrize("ascii_copy", [True, False])
def test_original_changed_during_processing_does_not_change_snapshot_identity(job, monkeypatch, ascii_copy):
    cfg, settings, asr, calls = job
    settings.video.copy_to_ascii_path = ascii_copy
    settings.video.work_dir = str(cfg.work_dir)
    cfg.work_dir = Path("auto")
    before = p.video_fingerprint(cfg.input_video)
    key = p.artifact_key(cfg)
    def change(wav, **kwargs):
        result = asr(wav, **kwargs)
        if calls["asr"] == 1:
            replace_same_metadata(cfg.input_video, b"replaced source")
        return result
    monkeypatch.setattr(p, "transcribe", change)
    first = p.run(cfg, settings)
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["input_fingerprint"] == before
    assert first.output_mp4.read_bytes() == b"original source subtitles"
    assert p.artifact_key(cfg) != key
    assert not p._same_fingerprint(report["input_fingerprint"], cfg)
    second = p.run(cfg, settings)
    assert not second.reused and calls["asr"] == 2
    assert second.output_mp4.read_bytes() == b"replaced source subtitles"


@pytest.mark.parametrize("burn", [False, True])
def test_changed_work_source_cannot_complete_or_burn_old_cues(job, monkeypatch, burn):
    cfg, settings, asr, _ = job
    cfg.burn = burn
    cfg.output_video.write_bytes(b"keep previous movie")
    def change(wav, **kwargs):
        result = asr(wav, **kwargs)
        replace_same_metadata(cfg.work_dir / "source.mp4", b"replaced source")
        return result
    monkeypatch.setattr(p, "transcribe", change)
    with pytest.raises(RuntimeError, match="工作源视频内容发生变化"):
        p.run(cfg, settings)
    assert not (cfg.work_dir / "report.json").exists()
    assert cfg.output_video.read_bytes() == b"keep previous movie"
    assert cfg.input_video.read_bytes() == b"original source"


def test_resume_rechecks_identity_after_initial_validation(job, monkeypatch):
    cfg, settings, _, _ = job
    first = p.run(cfg, settings)
    identity_path = first.report_path.parent / "job_input.json"
    before = identity_path.read_bytes()
    original = p._run_job
    def race(*args, **kwargs):
        replace_same_metadata(cfg.input_video, b"replaced source")
        return original(*args, **kwargs)
    monkeypatch.setattr(p, "_run_job", race)
    cfg.resume_from = "render"
    with pytest.raises(RuntimeError, match="恢复前输入内容"):
        p.run(cfg, settings)
    assert identity_path.read_bytes() == before
    assert (cfg.work_dir / "source.mp4").read_bytes() == b"original source"


def test_corrupt_work_source_reexport_uses_verified_original(job, monkeypatch):
    cfg, settings, _, _ = job
    first = p.run(cfg, settings)
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    replace_same_metadata(cfg.work_dir / "source.mp4", b"replaced source")
    # Force a re-burn rather than using the independently verified old movie.
    monkeypatch.setattr(p, "_style_same", lambda *a: False)
    cfg.output_video = cfg.output_video.with_name("another.mp4")
    p._copy_or_burn(cfg, cfg.work_dir, settings, report)
    assert cfg.output_video.read_bytes() == b"original source subtitles"
    replace_same_metadata(cfg.input_video, b"replaced source")
    with pytest.raises(RuntimeError, match="缓存源视频"):
        p._copy_or_burn(cfg, cfg.work_dir, settings, report)


def test_source_hash_during_cache_key_creation_can_be_stopped(job, monkeypatch, tmp_path):
    cfg, settings, _, _ = job
    cfg.input_video.write_bytes(b"x" * (3 * 1024 * 1024))
    cfg.work_dir = Path("auto")
    cache = tmp_path / "unused-cache"
    monkeypatch.setattr(p.tempfile, "gettempdir", lambda: str(cache))
    class StopWhileHashing(JobControl):
        calls = 0
        def wait_if_paused(self):
            self.calls += 1
            if self.calls == 3:
                self.stop()
            super().wait_if_paused()
    with pytest.raises(JobStopped):
        p.run(cfg, settings, control=StopWhileHashing())
    assert not cache.exists()


def test_real_ffmpeg_uses_work_snapshot_after_original_is_replaced(tmp_path, monkeypatch):
    video = tmp_path / "input.mp4"
    run_cmd([find_ffmpeg(), "-y", "-f", "lavfi", "-i", "color=size=640x360:rate=25",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-t", "2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)])
    before = p.video_fingerprint(video)
    def asr(wav, **kwargs):
        segment = Segment(0.2, 1.8, "这是中文测试。")
        kwargs["out_json"].write_text(json.dumps({"language": "zh", "segments": [segment.__dict__]}))
        video.write_bytes(b"external replacement after extraction")
        return [segment]
    monkeypatch.setattr(p, "transcribe", asr)
    settings = AppSettings()
    settings.video.copy_to_ascii_path = False
    cfg = JobConfig(video, tmp_path / "output.mp4", tmp_path / "output.srt", tmp_path / "work",
                    source_lang="zh", target_lang="zh", subtitle_mode="single:zh")
    result = p.run(cfg, settings)
    assert probe_video(result.output_mp4)["width"] == 640
    assert json.loads(result.report_path.read_text(encoding="utf-8"))["input_fingerprint"] == before
    assert p.file_digest(cfg.work_dir / "source.mp4") == before["sha256"]


def test_subtitle_reexport_keeps_original_identity_when_input_changes_in_callback(job):
    cfg, settings, _, calls = job
    cfg.burn = False
    settings.video.work_dir = str(cfg.work_dir)
    cfg.work_dir = Path("auto")
    first = p.run(cfg, settings)
    identity = json.loads(first.report_path.read_text(encoding="utf-8"))["input_fingerprint"]
    def change(stage, progress):
        if stage == "export":
            replace_same_metadata(cfg.input_video, b"replaced source")
    second = p.run(cfg, settings, on_progress=change)
    assert second.reused and calls["asr"] == 1
    assert json.loads(second.report_path.read_text(encoding="utf-8"))["input_fingerprint"] == identity
    assert not p._same_fingerprint(identity, cfg)


def test_glossary_changed_during_job_cannot_be_recorded_as_success(job, monkeypatch):
    cfg, settings, asr, _ = job
    glossary = cfg.input_video.with_name("glossary.yaml")
    glossary.write_text("{}", encoding="utf-8")
    cfg.glossary_path = glossary
    def change(wav, **kwargs):
        result = asr(wav, **kwargs)
        glossary.write_text("# modified\n{}", encoding="utf-8")
        return result
    monkeypatch.setattr(p, "transcribe", change)
    with pytest.raises(RuntimeError, match="术语或配置内容发生变化"):
        p.run(cfg, settings)
    assert not (cfg.work_dir / "report.json").exists()


@pytest.mark.parametrize("saved", [None, "broken", [], {"sha256": "x" * 64, "size": "bad", "mtime_ns": 0}])
def test_malformed_input_identity_is_not_a_valid_cache(job, saved):
    cfg, _, _, _ = job
    assert not p._same_fingerprint(saved, cfg)


def test_epoch_mtime_is_valid_when_content_matches(job):
    cfg, _, _, _ = job
    os.utime(cfg.input_video, ns=(0, 0))
    assert p._same_fingerprint(p.video_fingerprint(cfg.input_video), cfg)


def test_default_glossary_cannot_be_used_as_an_output(job, monkeypatch):
    cfg, settings, _, _ = job
    glossary = cfg.input_video.with_name("builtin-glossary.yaml")
    glossary.write_bytes(b"keep builtin glossary")
    monkeypatch.setattr(p, "default_glossary_path", lambda: glossary)
    cfg.output_srt = glossary
    with pytest.raises(ValueError, match="覆盖输入文件"):
        p.run(cfg, settings)
    assert glossary.read_bytes() == b"keep builtin glossary"


@pytest.mark.parametrize("readonly", [False, True])
def test_cancel_hashing_download_before_commit_preserves_previous_source(job, monkeypatch, readonly):
    cfg, _, _, _ = job
    cfg.source_url = "https://example.invalid/new"
    cfg.work_dir.mkdir()
    source = cfg.work_dir / "source.mp4"
    source.write_bytes(b"old download")
    marker = cfg.work_dir / "source.url.txt"
    marker.write_text("https://example.invalid/old")
    manifest = cfg.work_dir / "source.download.json"
    manifest.write_text("{}")
    downloaded = cfg.input_video.with_name("download.mp4")
    downloaded.write_bytes(b"new download")
    if readonly:
        downloaded.chmod(stat.S_IREAD)
    monkeypatch.setattr(p, "ytdlp_download", lambda *a, **k: downloaded)
    control = JobControl()
    original = p.video_fingerprint
    def stop_hash(path, **kwargs):
        if path.name == "source.download.mp4":
            control.stop()
        return original(path, **kwargs)
    monkeypatch.setattr(p, "video_fingerprint", stop_hash)
    try:
        with pytest.raises(JobStopped):
            p._download_source(cfg, cfg.work_dir, None, control)
    finally:
        downloaded.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert source.read_bytes() == b"old download"
    assert marker.read_text() == "https://example.invalid/old"
    assert manifest.read_text() == "{}"
    assert not (cfg.work_dir / "source.download.mp4").exists()
    assert not (cfg.work_dir / "source.download.pending.json").exists()
