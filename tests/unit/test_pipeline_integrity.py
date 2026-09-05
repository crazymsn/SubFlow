import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.config import AppSettings
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.gui.output_path import copy_finished_outputs
from bilingual_sub.models import JobConfig


def config(tmp_path):
    video = tmp_path / "original.mp4"
    video.write_bytes(b"original video")
    return JobConfig(video, tmp_path / "out.mp4", tmp_path / "out.srt", tmp_path / "work")


def test_glossary_generation_changes_artifact_identity(tmp_path):
    cfg = config(tmp_path)
    assert p.artifact_key(cfg) != p.artifact_key(replace(cfg, glossary_generate=True))


@pytest.mark.parametrize("destination", ["video", "srt", "hardlink", "duplicate"])
def test_reject_output_collision_before_changing_files(tmp_path, monkeypatch, destination):
    cfg = config(tmp_path)
    if destination == "video":
        cfg.output_video = cfg.input_video
    elif destination == "srt":
        cfg.output_srt = cfg.input_video
    elif destination == "hardlink":
        os.link(cfg.input_video, cfg.output_video)
    else:
        cfg.output_srt = cfg.output_video
    monkeypatch.setattr(p, "_run_job", lambda *a: pytest.fail("processing must not start"))
    with pytest.raises(ValueError, match="覆盖|冲突"):
        p.run(cfg, AppSettings())
    assert cfg.input_video.read_bytes() == b"original video"
    assert not cfg.work_dir.exists()


def test_gui_relocation_protects_original_video(tmp_path):
    original = tmp_path / "original.mp4"
    exported = tmp_path / "exported.mp4"
    original.write_bytes(b"original")
    exported.write_bytes(b"exported")
    with pytest.raises(ValueError, match="覆盖"):
        copy_finished_outputs(original, src_mp4=exported, src_srt=None, src_ass=None,
                              protected_inputs=(original,))
    assert original.read_bytes() == b"original"


def test_resume_rejects_same_size_different_video_even_with_explicit_work(tmp_path):
    cfg = config(tmp_path)
    cfg.work_dir.mkdir()
    identity = {"input_fingerprint": p.video_fingerprint(cfg.input_video)}
    (cfg.work_dir / "report.json").write_text(json.dumps(identity))
    other = tmp_path / "different.mp4"
    other.write_bytes(b"different film")
    assert other.stat().st_size == cfg.input_video.stat().st_size
    wrong = replace(cfg, input_video=other, resume_from="translate")
    assert not p._resume_dir_matches(wrong, cfg.work_dir)
    with pytest.raises(FileNotFoundError, match="不是这部片子"):
        p.run(wrong, AppSettings())
    correct = replace(cfg, resume_from="translate")
    assert p._resume_dir_matches(correct, cfg.work_dir)
    stat = cfg.input_video.stat()
    os.utime(cfg.input_video, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert not p._resume_dir_matches(correct, cfg.work_dir)


def test_missing_input_does_not_silently_use_old_work_video(tmp_path):
    cfg = config(tmp_path)
    cfg.input_video.unlink()
    cfg.work_dir.mkdir()
    (cfg.work_dir / "source.mp4").write_bytes(b"unrelated old video")
    with pytest.raises(FileNotFoundError, match="选择本地视频"):
        p.run(cfg, AppSettings())


def test_failed_new_url_download_keeps_old_url_and_video_then_retries(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    cfg.source_url = "https://youtu.be/new-video"
    cfg.work_dir.mkdir()
    source = cfg.work_dir / "source.mp4"
    source.write_bytes(b"old video")
    marker = cfg.work_dir / "source.url.txt"
    marker.write_text("https://youtu.be/old-video")
    calls = []

    def download(url, dest, **kwargs):
        calls.append(url)
        path = dest / "source.mp4"
        path.write_bytes(b"new video")
        if len(calls) == 1:
            raise RuntimeError("connection interrupted")
        return path

    monkeypatch.setattr(p, "ytdlp_download", download)
    with pytest.raises(RuntimeError, match="connection interrupted"):
        p._download_source(cfg, cfg.work_dir, None, None)
    assert source.read_bytes() == b"old video"
    assert marker.read_text() == "https://youtu.be/old-video"
    assert p._download_source(cfg, cfg.work_dir, None, None) == source
    assert source.read_bytes() == b"new video"
    assert marker.read_text() == cfg.source_url
    assert len(calls) == 2


def test_stopped_reexport_does_not_touch_outputs(tmp_path):
    cfg = config(tmp_path)
    control = JobControl()
    control.stop()
    with pytest.raises(JobStopped):
        p.run(cfg, AppSettings(), control=control)
    assert not cfg.output_srt.exists()


def test_corrupt_cached_url_video_cannot_resume_by_size_only(tmp_path):
    cfg = config(tmp_path)
    cfg.source_url = "https://youtu.be/video"
    cfg.input_video = Path("missing-placeholder")
    cfg.work_dir.mkdir()
    source = cfg.work_dir / "source.mp4"
    source.write_bytes(b"downloaded")
    (cfg.work_dir / "source.url.txt").write_text(cfg.source_url)
    (cfg.work_dir / "report.json").write_text(json.dumps({
        "source_url": cfg.source_url, "input_fingerprint": p.video_fingerprint(source),
    }))
    assert p._resume_dir_matches(cfg, cfg.work_dir)
    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    assert not p._resume_dir_matches(cfg, cfg.work_dir)


def test_gui_no_burn_relocation_ignores_unrelated_existing_mp4(tmp_path):
    pytest.importorskip("PySide6")
    from bilingual_sub.gui.app import MainWindow
    from bilingual_sub.gui.output_path import sidecar_dub
    from bilingual_sub.models import JobResult

    srt = tmp_path / "old.srt"
    ass = tmp_path / "old.ass"
    dub = tmp_path / "old-dub.mp4"
    for path in (srt, ass, dub):
        path.write_bytes(b"exported")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"output_dub": str(dub)}))
    result = JobResult("test", None, srt, ass, 1, [], 1, report, output_dub=dub)
    dest = tmp_path / "new.mp4"
    dest.write_bytes(b"unrelated existing movie")
    window = SimpleNamespace(_last_result=result, _video=None, open_btn=Mock(), out_edit=Mock())
    window._reuse_sources = lambda: (None, srt, ass, dub)
    window._patch_report_outputs = lambda: MainWindow._patch_report_outputs(window)
    assert MainWindow._try_relocate_outputs(window, dest)
    assert dest.read_bytes() == b"unrelated existing movie"
    assert window._last_result.output_mp4 is None
    assert window._last_result.output_dub == sidecar_dub(dest)
    assert window._last_output == sidecar_dub(dest)
    saved = json.loads(report.read_text())
    assert saved["output_mp4"] is None and saved["output_dub"] == str(sidecar_dub(dest))
