import os
import stat
from pathlib import Path

import pytest

from bilingual_sub.config import load_style_preset
from bilingual_sub.core import file_io
from bilingual_sub.core.control import JobStopped
from bilingual_sub.core.render import write_subtitles
from bilingual_sub.models import Cue


@pytest.fixture
def media(tmp_path):
    source, target = tmp_path / "source.mp4", tmp_path / "target.mp4"
    source.write_bytes(b"new" * 1024 * 1024)
    target.write_bytes(b"previous complete video")
    return source, target


def assert_no_temps(folder):
    assert not list(folder.glob(".subflow-*-*.tmp"))


def test_copy_cancelled_between_chunks_preserves_old_video(media):
    source, target = media
    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        assert target.read_bytes() == b"previous complete video"
        if calls == 3:
            pending = list(target.parent.glob(".subflow-output-*.tmp"))
            assert len(pending) == 1 and pending[0].stat().st_size == 1024 * 1024
            raise JobStopped()
    with pytest.raises(JobStopped):
        file_io.copy_file(source, target, checkpoint=checkpoint)
    assert target.read_bytes() == b"previous complete video"
    assert_no_temps(target.parent)


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_copy_io_failure_preserves_old_video(media, monkeypatch, failure):
    source, target = media
    def fail(*args):
        raise OSError("injected disk error")
    monkeypatch.setattr(os if failure == "fsync" else Path, failure, fail)
    with pytest.raises(OSError, match="injected disk error"):
        file_io.copy_file(source, target)
    assert target.read_bytes() == b"previous complete video"
    assert_no_temps(target.parent)


def test_copy_detects_source_change_without_committing(media):
    source, target = media
    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 3:
            with source.open("ab") as stream:
                stream.write(b"changed")
    with pytest.raises(OSError, match="源文件发生变化"):
        file_io.copy_file(source, target, checkpoint=checkpoint)
    assert target.read_bytes() == b"previous complete video"
    assert_no_temps(target.parent)


def test_copy_success_and_hardlink_alias(media):
    source, target = media
    file_io.copy_file(source, target)
    assert target.read_bytes() == source.read_bytes()
    assert target.stat().st_mtime_ns == source.stat().st_mtime_ns
    alias = source.with_name("alias.mp4")
    os.link(source, alias)
    file_io.copy_file(source, alias)
    assert source.samefile(alias)
    assert_no_temps(target.parent)


@pytest.mark.parametrize("when", ["before", "during"])
def test_recorded_copy_rejects_changed_content_with_same_metadata(media, when):
    source, target = media
    expected = file_io.file_digest(source)
    stamp = source.stat()
    def replace_tail():
        with source.open("r+b") as stream:
            stream.seek(2 * 1024 * 1024)
            stream.write(b"x" * 1024 * 1024)
        os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    calls = 0
    def checkpoint():
        nonlocal calls
        calls += 1
        if when == "during" and calls == 3:
            replace_tail()
    if when == "before":
        replace_tail()
    with pytest.raises(ValueError, match="内容"):
        file_io.copy_file(source, target, checkpoint=checkpoint, expected_sha256=expected)
    assert target.read_bytes() == b"previous complete video"
    assert_no_temps(target.parent)


@pytest.mark.parametrize("same", [False, True])
def test_recorded_copy_validates_even_when_destination_is_same_inode(media, same):
    source, target = media
    if same:
        target.unlink()
        os.link(source, target)
    expected = file_io.file_digest(source)
    file_io.copy_file(source, target, expected_sha256=expected)
    assert file_io.file_digest(target) == expected
    with pytest.raises(ValueError, match="内容"):
        file_io.copy_file(source, target, expected_sha256="0" * 64)
    assert file_io.file_digest(target) == expected
    assert_no_temps(target.parent)


def test_missing_same_path_copy_is_an_error(tmp_path):
    missing = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        file_io.copy_file(missing, missing)


@pytest.fixture
def subtitles(tmp_path):
    ass, srt = tmp_path / "a.ass", tmp_path / "srt" / "a.srt"
    srt.parent.mkdir()
    ass.write_bytes(b"old ASS")
    srt.write_bytes(b"old SRT")
    return ass, srt


def texts(ass, srt):
    return [(ass, "new ASS", "utf-8-sig"), (srt, "new SRT", "utf-8")]


def test_second_subtitle_prepare_failure_changes_neither_file(subtitles, monkeypatch):
    ass, srt = subtitles
    sync = os.fsync
    calls = 0
    def fail_second(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        sync(fd)
    monkeypatch.setattr(os, "fsync", fail_second)
    with pytest.raises(OSError, match="disk full"):
        file_io.write_text_files(texts(ass, srt))
    assert ass.read_bytes() == b"old ASS" and srt.read_bytes() == b"old SRT"
    assert_no_temps(ass.parent)
    assert_no_temps(srt.parent)


@pytest.mark.parametrize("existing", [True, False])
def test_second_replace_failure_restores_previous_subtitle_state(subtitles, monkeypatch, existing):
    ass, srt = subtitles
    if not existing:
        ass.unlink()
    replace = Path.replace
    def fail_second(path, target):
        if target == srt:
            raise PermissionError("SRT open in another application")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail_second)
    with pytest.raises(PermissionError):
        file_io.write_text_files(texts(ass, srt))
    assert ass.read_bytes() == b"old ASS" if existing else not ass.exists()
    assert srt.read_bytes() == b"old SRT"
    assert_no_temps(ass.parent)
    assert_no_temps(srt.parent)


def test_failed_rollback_keeps_recoverable_backup(subtitles, monkeypatch):
    ass, srt = subtitles
    replace = Path.replace
    def fail(path, target):
        if target == srt or path.name.startswith(".subflow-backup-"):
            raise PermissionError("destination unavailable")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="保留备份") as exc:
        file_io.write_text_files(texts(ass, srt))
    backups = list(ass.parent.glob(".subflow-backup-*.tmp"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old ASS"
    assert str(backups[0]) in str(exc.value)
    assert srt.read_bytes() == b"old SRT"
    assert_no_temps(srt.parent)


def test_cancel_before_subtitle_commit_preserves_both(subtitles):
    ass, srt = subtitles
    def checkpoint():
        if len(list(ass.parent.rglob(".subflow-output-*.tmp"))) == 2:
            raise JobStopped()
    with pytest.raises(JobStopped):
        file_io.write_text_files(texts(ass, srt), checkpoint=checkpoint)
    assert ass.read_bytes() == b"old ASS" and srt.read_bytes() == b"old SRT"
    assert_no_temps(ass.parent)
    assert_no_temps(srt.parent)


def test_render_creates_both_parents_and_preserves_encoding(tmp_path):
    ass, srt = tmp_path / "ass" / "a.ass", tmp_path / "srt" / "a.srt"
    write_subtitles([Cue(0, 1, "你好", "Hello")], load_style_preset("no-plate-large"), ass, srt)
    assert ass.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not srt.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "你好" in srt.read_text(encoding="utf-8")


def test_subtitle_paths_cannot_alias(subtitles):
    ass, _ = subtitles
    with pytest.raises(ValueError, match="不能重复"):
        file_io.write_text_files(texts(ass, ass))
    assert ass.read_bytes() == b"old ASS"


def test_cancel_readonly_copy_cleans_staging_file(media):
    source, target = media
    old_mode = source.stat().st_mode
    source.chmod(old_mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    def checkpoint():
        for pending in target.parent.glob(".subflow-output-*.tmp"):
            if not pending.stat().st_mode & stat.S_IWUSR:
                raise JobStopped()
    try:
        with pytest.raises(JobStopped):
            file_io.copy_file(source, target, checkpoint=checkpoint)
    finally:
        source.chmod(old_mode)
    assert target.read_bytes() == b"previous complete video"
    assert_no_temps(target.parent)
