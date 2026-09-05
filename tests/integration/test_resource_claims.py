import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from filelock import FileLock

from bilingual_sub import pipeline as p
from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.config import AppSettings
from bilingual_sub.core.control import JobStopped
from bilingual_sub.core.resource_claims import claim_resources, registry_dir
from bilingual_sub.gui.output_path import copy_finished_outputs
from bilingual_sub.models import JobConfig

CHILD = """
import os, sys, time
from pathlib import Path
from bilingual_sub.core.resource_claims import claim_resources
target, ready, finish = map(Path, sys.argv[1:4])
with claim_resources(reads=[target] if sys.argv[4] == 'read' else [],
                     writes=[target] if sys.argv[4] == 'write' else []):
    ready.write_text('ready')
    while not finish.exists():
        time.sleep(0.03)
    if sys.argv[5] == 'crash':
        os._exit(7)
"""


@contextmanager
def child_claim(tmp_path, target, *, mode="write", crash=False):
    ready, finish = tmp_path / "ready", tmp_path / "finish"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(p.__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    log = tmp_path / "child.log"
    with log.open("w", encoding="utf-8") as stream, owned_process(
        [sys.executable, "-c", CHILD, str(target), str(ready), str(finish), mode,
         "crash" if crash else "normal"], stdout=stream, stderr=subprocess.STDOUT, env=env,
    ) as proc:
        deadline = time.monotonic() + 10
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.03)
        assert ready.exists(), log.read_text(encoding="utf-8")
        try:
            yield proc, finish
        finally:
            finish.touch()
            proc.wait(timeout=10)


def test_actual_process_conflict_and_crash_release(tmp_path):
    target = tmp_path / "movie.mp4"
    target.write_bytes(b"previous")
    with child_claim(tmp_path, target, crash=True) as (proc, finish):
        with pytest.raises(RuntimeError, match="另一任务"):
            with claim_resources(reads=[], writes=[target]):
                pytest.fail("second writer entered")
        assert target.read_bytes() == b"previous"
        finish.touch()
        assert proc.wait(timeout=10) == 7
        # The crashed process leaves metadata but its OS lock has been released.
        assert list(registry_dir().glob("*.json"))
        with claim_resources(reads=[], writes=[target]):
            target.write_bytes(b"recovered")
    assert target.read_bytes() == b"recovered"
    assert not list(registry_dir().glob("*.json"))


def test_shared_readers_allowed_but_hardlink_writer_blocked(tmp_path):
    source, alias = tmp_path / "source.mp4", tmp_path / "alias.mp4"
    source.write_bytes(b"input")
    os.link(source, alias)
    with child_claim(tmp_path, source, mode="read"):
        with claim_resources(reads=[alias], writes=[tmp_path / "other.srt"]):
            pass
        with pytest.raises(RuntimeError, match="另一任务"):
            with claim_resources(reads=[], writes=[alias]):
                pytest.fail("writer replaced an active input")


def test_writer_blocks_readers_and_work_tree_overlap(tmp_path):
    work = tmp_path / "work"
    with claim_resources(reads=[], writes=[], trees=[work]):
        with pytest.raises(RuntimeError, match="写入"):
            with claim_resources(reads=[work / "source.mp4"], writes=[]):
                pass
        with pytest.raises(RuntimeError, match="另一任务"):
            with claim_resources(reads=[], writes=[work / "nested" / "out.srt"]):
                pass
        with claim_resources(reads=[], writes=[tmp_path / "work-other" / "out.srt"]):
            pass


def test_distinct_work_dirs_cannot_export_to_busy_destination(tmp_path, monkeypatch):
    target, source = tmp_path / "out.srt", tmp_path / "input.mp4"
    source.write_bytes(b"input")
    cfg = JobConfig(source, None, target, tmp_path / "another-work", burn=False)
    monkeypatch.setattr(p, "_run_in_work", lambda *a: pytest.fail("processing started"))
    with child_claim(tmp_path, target):
        with pytest.raises(RuntimeError, match="另一任务"):
            p.run(cfg, AppSettings())
    assert not target.exists() and not (cfg.work_dir / "job_state.json").exists()


def test_registry_wait_can_be_cancelled_and_orphan_is_pruned(tmp_path):
    root = registry_dir()
    root.mkdir(exist_ok=True)
    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise JobStopped()
    with FileLock(str(root / "registry.lock")):
        with pytest.raises(JobStopped):
            with claim_resources(reads=[], writes=[tmp_path / "out"], checkpoint=checkpoint):
                pass
    with claim_resources(reads=[], writes=[tmp_path / "out"]):
        pass
    assert {path.name for path in root.iterdir()} <= {"registry.lock"}


def test_live_corrupt_claim_fails_closed_but_dead_one_is_reclaimed(tmp_path):
    with child_claim(tmp_path, tmp_path / "busy"):
        record = next(registry_dir().glob("*.json"))
        record.write_text("broken")
        with pytest.raises(RuntimeError, match="登记无法读取"):
            with claim_resources(reads=[], writes=[tmp_path / "unrelated"]):
                pass
    # Dead, even invalid records are safe to remove because ownership is released.
    record.write_text("broken")
    with claim_resources(reads=[], writes=[tmp_path / "unrelated"]):
        pass
    assert not record.exists()


def test_gui_relocation_cannot_overwrite_active_output(tmp_path):
    target, source = tmp_path / "out.mp4", tmp_path / "previous.mp4"
    target.write_bytes(b"keep")
    source.write_bytes(b"new")
    with child_claim(tmp_path, target):
        with pytest.raises(RuntimeError, match="另一任务"):
            copy_finished_outputs(target, src_mp4=source, src_srt=None, src_ass=None)
    assert target.read_bytes() == b"keep"


def test_missing_relocation_source_is_not_silently_skipped(tmp_path):
    target, source = tmp_path / "out.mp4", tmp_path / "previous.mp4"
    source.write_bytes(b"new")
    target.write_bytes(b"keep")
    with pytest.raises(FileNotFoundError):
        copy_finished_outputs(target, src_mp4=source, src_srt=tmp_path / "missing.srt", src_ass=None)
    assert target.read_bytes() == b"keep"


def test_job_snapshots_configuration_before_callbacks_can_mutate_it(tmp_path, monkeypatch):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    cfg = JobConfig(source, None, tmp_path / "planned.srt", tmp_path / "work", burn=False)
    settings = AppSettings()
    expected_work = settings.video.work_dir
    def run(copy_cfg, copy_settings, *args):
        cfg.output_srt = tmp_path / "unreserved.srt"
        settings.video.work_dir = str(tmp_path / "different-work")
        assert copy_cfg.output_srt == tmp_path / "planned.srt"
        assert copy_settings is not settings
        assert copy_settings.video.work_dir == expected_work
        return "snapshot verified"
    monkeypatch.setattr(p, "_run_in_work", run)
    assert p.run(cfg, settings) == "snapshot verified"


def test_registry_cannot_be_an_output_or_inside_work_tree(tmp_path):
    root = registry_dir()
    with pytest.raises(ValueError, match="登记目录"):
        with claim_resources(reads=[], writes=[root / "registry.lock"]):
            pass
    with pytest.raises(ValueError, match="登记目录"):
        with claim_resources(reads=[], writes=[], trees=[root.parent]):
            pass


def test_gui_copy_io_failure_preserves_existing_movie(tmp_path, monkeypatch):
    target, source = tmp_path / "out.mp4", tmp_path / "previous.mp4"
    target.write_bytes(b"keep")
    source.write_bytes(b"new")
    replace = Path.replace
    def fail(path, destination):
        if destination == target:
            raise OSError("copy commit failed")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="copy commit failed"):
        copy_finished_outputs(target, src_mp4=source, src_srt=None, src_ass=None)
    assert target.read_bytes() == b"keep"
    assert not list(registry_dir().glob("*.json"))
    assert not list(tmp_path.glob(".subflow-output-*.tmp"))


def test_reexport_reserves_previous_movie_against_another_writer(tmp_path, monkeypatch):
    import json

    source, previous = tmp_path / "input.mp4", tmp_path / "old.mp4"
    source.write_bytes(b"input")
    work = tmp_path / "work"
    work.mkdir()
    (work / "report.json").write_text(json.dumps({"output_mp4": str(previous)}))
    cfg = JobConfig(source, tmp_path / "new.mp4", tmp_path / "new.srt", Path("auto"))
    settings = AppSettings()
    settings.video.work_dir = str(work)
    monkeypatch.setattr(p, "_run_in_work", lambda *a: pytest.fail("read busy previous output"))
    with child_claim(tmp_path, previous):
        with pytest.raises(RuntimeError, match="写入"):
            p.run(cfg, settings)


@pytest.mark.parametrize("legacy", [False, True])
def test_overwritten_or_unverified_previous_movie_is_rebuilt(tmp_path, monkeypatch, legacy):
    previous, dest = tmp_path / "old.mp4", tmp_path / "new.mp4"
    previous.write_bytes(b"first movie")
    stamp = previous.stat()
    report = {"output_mp4": str(previous), "output_video_sha256": p.file_digest(previous)}
    if legacy:
        del report["output_video_sha256"]
    else:
        # Same size and timestamp, different content: metadata alone cannot identify it.
        previous.write_bytes(b"other movie")
        os.utime(previous, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    cfg = JobConfig(tmp_path / "input.mp4", dest, tmp_path / "out.srt", tmp_path,
                    source_lang="zh", target_lang="zh")
    (tmp_path / "subs.ass").write_text("subtitles")
    monkeypatch.setattr(p, "_style_same", lambda *a: True)
    burned = []
    def burn(source, ass, output, **kwargs):
        burned.append(output)
        output.write_bytes(b"rebuilt from original input")
    monkeypatch.setattr(p, "burn_subtitles", burn)
    assert p._copy_or_burn(cfg, tmp_path, AppSettings(), report) == dest
    assert burned == [dest] and dest.read_bytes() == b"rebuilt from original input"


def test_hashing_can_be_cancelled_and_detects_source_changes(tmp_path):
    video = tmp_path / "movie.mp4"
    video.write_bytes(b"x" * 2 * 1024 * 1024)
    def stop():
        raise JobStopped()
    with pytest.raises(JobStopped):
        p.file_digest(video, checkpoint=stop)
    calls = 0
    def change():
        nonlocal calls
        calls += 1
        if calls == 2:
            with video.open("ab") as stream:
                stream.write(b"change")
    with pytest.raises(OSError, match="文件发生变化"):
        p.file_digest(video, checkpoint=change)
