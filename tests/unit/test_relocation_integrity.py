import json
import os
import stat
from pathlib import Path

import pytest

from bilingual_sub.core.file_io import copy_files, file_digest
from bilingual_sub.core.resource_claims import claim_resources
from bilingual_sub.gui.output_path import copy_finished_outputs, sidecar_srt


@pytest.fixture
def job(tmp_path):
    video, movie, subs = [tmp_path / name for name in ("input.mp4", "old.mp4", "old.srt")]
    for path in (video, movie, subs):
        path.write_bytes(path.name.encode())
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"job_id": "job", "input_fingerprint": {"sha256": file_digest(video)},
                                 "output_hashes": {"mp4": file_digest(movie), "srt": file_digest(subs)}}))
    report.with_name("job_state.json").write_text('{"job_id":"job","stage":"done"}')
    dest = tmp_path / "export" / "new.mp4"
    dest.parent.mkdir()
    dest.write_bytes(b"previous movie")
    sidecar_srt(dest).write_bytes(b"previous subs")
    return video, movie, subs, report, dest


def relocate(job, **kwargs):
    video, movie, subs, report, dest = job
    return copy_finished_outputs(dest, src_mp4=movie, src_srt=subs, src_ass=None,
                                 report_path=report, job_id="job", source_video=video, **kwargs)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_changed_contents_with_same_stat_rejected(job, index):
    path = job[index]
    original_stat = path.stat()
    path.write_bytes(b"x" * original_stat.st_size)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    old_report = job[3].read_bytes()
    with pytest.raises(ValueError, match="内容"):
        relocate(job)
    assert job[4].read_bytes() == b"previous movie"
    assert sidecar_srt(job[4]).read_bytes() == b"previous subs"
    assert job[3].read_bytes() == old_report


@pytest.mark.parametrize("record,field,value", [("report.json", "job_id", "other"),
                                                ("job_state.json", "job_id", "other"),
                                                ("job_state.json", "stage", "dub"),
                                                ("report.json", "output_hashes", {})])
def test_stale_or_incomplete_records_rejected(job, record, field, value):
    path = job[3].with_name(record)
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        relocate(job)
    assert job[4].read_bytes() == b"previous movie"


@pytest.mark.parametrize("fail_report", [True, False])
def test_commit_failure_rolls_back_all_outputs_and_report(job, monkeypatch, fail_report):
    report, dest = job[3:]
    previous = report.read_bytes()
    failing = report if fail_report else sidecar_srt(dest)
    replace = Path.replace
    def fail(path, target):
        if target == failing:
            raise PermissionError("destination busy")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(PermissionError):
        relocate(job)
    assert dest.read_bytes() == b"previous movie"
    assert sidecar_srt(dest).read_bytes() == b"previous subs"
    assert report.read_bytes() == previous
    assert not list(dest.parent.parent.rglob(".subflow-*.tmp"))


@pytest.mark.parametrize("record", ["report.json", "job_state.json", "input.mp4"])
def test_active_job_prevents_relocation(job, record):
    with claim_resources(reads=[], writes=[job[3].with_name(record)]):
        with pytest.raises(RuntimeError):
            relocate(job)
    assert job[4].read_bytes() == b"previous movie"


def test_success_updates_report_and_verifies_same_destination(job):
    result = relocate(job)
    report = json.loads(job[3].read_text())
    for kind in ("mp4", "srt"):
        assert report["output_" + kind] == str(result[kind])
        assert report["output_hashes"][kind] == file_digest(result[kind])
    same_job = (job[0], result["mp4"], result["srt"], job[3], job[4])
    relocate(same_job)
    result["mp4"].write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="成品内容"):
        relocate(same_job)


def test_readonly_staged_file_can_be_rolled_back(job, monkeypatch):
    source, target = job[1], job[4]
    old_mode = source.stat().st_mode
    source.chmod(old_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    replace = Path.replace
    def fail(path, dest):
        if dest == job[3]:
            raise OSError("report failed")
        return replace(path, dest)
    monkeypatch.setattr(Path, "replace", fail)
    try:
        with pytest.raises(OSError, match="report failed"):
            relocate(job)
        assert target.read_bytes() == b"previous movie"
    finally:
        source.chmod(old_mode)


def test_cannot_overwrite_a_different_copy_source(job):
    with pytest.raises(ValueError):
        copy_files([(job[1], job[2]), (job[2], job[4])])
    assert job[2].read_bytes() == b"old.srt"
