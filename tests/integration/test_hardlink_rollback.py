import os
import stat
from pathlib import Path

import pytest

from bilingual_sub.core.file_io import copy_files, discard_temporary, write_text_files


@pytest.fixture(params=["same-folder", "other-folder"])
def outputs(tmp_path, request):
    first, second = tmp_path / "out.ass", tmp_path / "out.srt"
    first.write_bytes(b"old ASS")
    second.write_bytes(b"old SRT")
    folder = tmp_path if request.param == "same-folder" else tmp_path / "links"
    folder.mkdir(exist_ok=True)
    alias = folder / "alias.ass"
    alias.hardlink_to(first)
    return first, second, alias


def texts(first, second):
    return [(first, "new ASS", "utf-8"), (second, "new SRT", "utf-8")]


def assert_original(first, second, alias):
    assert first.read_bytes() == alias.read_bytes() == b"old ASS"
    assert first.samefile(alias)
    assert second.read_bytes() == b"old SRT"
    assert not list(first.parent.glob(".subflow-*.tmp"))


def fail_second(monkeypatch, second, *, rollback=False):
    replace = Path.replace
    def fail(path, target):
        if target == second or (rollback and path.name.startswith(".subflow-backup-")):
            raise PermissionError("injected output failure")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail)


def test_failed_commit_restores_hardlink_relationship(outputs, monkeypatch):
    first, second, alias = outputs
    fail_second(monkeypatch, second)
    with pytest.raises(PermissionError):
        write_text_files(texts(first, second))
    assert_original(first, second, alias)
    alias.write_bytes(b"edit through alias")
    assert first.read_bytes() == b"edit through alias"


def test_failed_rollback_retains_original_hardlinked_backup(outputs, monkeypatch):
    first, second, alias = outputs
    fail_second(monkeypatch, second, rollback=True)
    with pytest.raises(OSError, match="保留备份") as error:
        write_text_files(texts(first, second))
    backups = list(first.parent.glob(".subflow-backup-*.tmp"))
    assert len(backups) == 1 and backups[0].samefile(alias)
    assert backups[0].read_bytes() == b"old ASS"
    assert str(backups[0]) in str(error.value)
    assert second.read_bytes() == b"old SRT"


def test_cancel_keeps_original_relationship_and_link_count(outputs):
    first, second, alias = outputs
    count = first.stat().st_nlink
    def cancel():
        raise RuntimeError("cancel before commit")
    with pytest.raises(RuntimeError, match="cancel before commit"):
        copy_files([], texts=texts(first, second), before_commit=cancel)
    assert_original(first, second, alias)
    assert first.stat().st_nlink == count


def test_success_detaches_output_but_does_not_modify_existing_alias(outputs):
    first, second, alias = outputs
    write_text_files(texts(first, second))
    assert first.read_bytes() == b"new ASS"
    assert alias.read_bytes() == b"old ASS" and alias.stat().st_nlink == 1
    assert not first.samefile(alias)
    assert second.read_bytes() == b"new SRT"
    assert not list(first.parent.glob(".subflow-*.tmp"))


def test_backup_link_failure_prevents_any_publication(outputs, monkeypatch):
    first, second, alias = outputs
    def denied(*args, **kwargs):
        raise PermissionError("backup hardlink denied")
    monkeypatch.setattr(Path, "hardlink_to", denied)
    with pytest.raises(PermissionError, match="backup hardlink denied"):
        write_text_files(texts(first, second))
    assert_original(first, second, alias)


def test_readonly_new_copy_rolls_back_to_existing_hardlink(outputs, monkeypatch):
    first, second, alias = outputs
    source = first.parent / "readonly-source"
    source.write_bytes(b"new readonly ASS")
    mode = source.stat().st_mode
    source.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    fail_second(monkeypatch, second)
    try:
        with pytest.raises(PermissionError):
            copy_files([(source, first)], texts=[(second, "new SRT", "utf-8")])
        assert_original(first, second, alias)
        assert not source.stat().st_mode & stat.S_IWUSR
    finally:
        source.chmod(mode)


def test_readonly_existing_hardlink_remains_intact_after_failure(outputs, monkeypatch):
    first, second, alias = outputs
    mode = first.stat().st_mode
    first.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    expected_mode = alias.stat().st_mode
    fail_second(monkeypatch, second)
    try:
        with pytest.raises(PermissionError):
            write_text_files(texts(first, second))
        assert_original(first, second, alias)
        assert alias.stat().st_mode == expected_mode
    finally:
        alias.chmod(mode)


def test_cleanup_failure_never_changes_shared_readonly_permissions(outputs, monkeypatch):
    first, _, alias = outputs
    mode = first.stat().st_mode
    first.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    expected_mode = alias.stat().st_mode
    unlink = Path.unlink
    def denied(path, *args, **kwargs):
        if path == first:
            raise PermissionError("delete denied")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", denied)
    try:
        with pytest.raises(PermissionError, match="delete denied"):
            discard_temporary(first)
        assert alias.stat().st_mode == expected_mode
        assert first.samefile(alias) and alias.read_bytes() == b"old ASS"
    finally:
        alias.chmod(mode)


@pytest.mark.skipif(os.name == "nt", reason="Windows rejects replacement of an existing readonly destination")
def test_posix_readonly_hardlink_success_preserves_old_alias_permissions(outputs):
    first, second, alias = outputs
    mode = first.stat().st_mode
    first.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    expected_mode = alias.stat().st_mode
    try:
        write_text_files(texts(first, second))
        assert alias.stat().st_mode == expected_mode and alias.read_bytes() == b"old ASS"
        assert first.read_bytes() == b"new ASS"
        assert not list(first.parent.glob(".subflow-*.tmp"))
    finally:
        alias.chmod(mode)
