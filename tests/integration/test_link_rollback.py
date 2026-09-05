import stat
from pathlib import Path

import pytest

from bilingual_sub.core.file_io import write_text_files


@pytest.fixture(params=["relative", "absolute", "dangling"])
def outputs(tmp_path, request):
    target = tmp_path / ("missing.txt" if request.param == "dangling" else "original.txt")
    if request.param != "dangling":
        target.write_text("original content", encoding="utf-8")
    link = tmp_path / "output.ass"
    value = target if request.param == "absolute" else Path(target.name)
    try:
        link.symlink_to(value)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Host cannot create test symlinks: {exc}")
    second = tmp_path / "output.srt"
    second.write_text("old SRT", encoding="utf-8")
    return link, second, target, link.readlink()


def assert_target_unchanged(target):
    if target.name == "missing.txt":
        assert not target.exists()
    else:
        assert target.read_text(encoding="utf-8") == "original content"


def assert_no_temps(root):
    assert not list(root.glob(".subflow-*.tmp"))


def test_later_commit_failure_restores_original_link(outputs, monkeypatch):
    link, second, target, value = outputs
    replace = Path.replace
    def fail(path, destination):
        if destination == second:
            raise PermissionError("second output is locked")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(PermissionError, match="second output"):
        write_text_files([(link, "new ASS", "utf-8"), (second, "new SRT", "utf-8")])
    assert link.is_symlink()
    assert link.readlink() == value
    assert second.read_text(encoding="utf-8") == "old SRT"
    assert_target_unchanged(target)
    assert_no_temps(link.parent)


def test_failed_link_rollback_retains_a_restorable_link(outputs, monkeypatch):
    link, second, target, value = outputs
    replace = Path.replace
    def fail(path, destination):
        if destination == second or path.name.startswith(".subflow-backup-"):
            raise PermissionError("output unavailable")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="保留备份") as error:
        write_text_files([(link, "new ASS", "utf-8"), (second, "new SRT", "utf-8")])
    backups = list(link.parent.glob(".subflow-backup-*.tmp"))
    assert len(backups) == 1 and backups[0].is_symlink()
    assert backups[0].readlink() == value
    assert str(backups[0]) in str(error.value)
    assert_target_unchanged(target)


def test_successful_commit_replaces_link_without_changing_target(outputs):
    link, second, target, _ = outputs
    write_text_files([(link, "new ASS", "utf-8"), (second, "new SRT", "utf-8")])
    assert not link.is_symlink() and link.read_text(encoding="utf-8") == "new ASS"
    assert second.read_text(encoding="utf-8") == "new SRT"
    assert_target_unchanged(target)
    assert_no_temps(link.parent)


def test_cancel_before_commit_preserves_link(outputs):
    link, second, target, value = outputs
    def cancel():
        raise RuntimeError("cancel before commit")
    from bilingual_sub.core.file_io import copy_files

    with pytest.raises(RuntimeError, match="cancel before commit"):
        copy_files([], texts=[(link, "new ASS", "utf-8"), (second, "new SRT", "utf-8")], before_commit=cancel)
    assert link.is_symlink() and link.readlink() == value
    assert_target_unchanged(target)
    assert_no_temps(link.parent)


def test_link_backup_creation_failure_leaves_original_outputs(outputs, monkeypatch):
    link, second, target, value = outputs
    def denied(*args, **kwargs):
        raise PermissionError("symlink creation denied")
    monkeypatch.setattr(Path, "symlink_to", denied)
    with pytest.raises(PermissionError, match="symlink creation denied"):
        write_text_files([(link, "new ASS", "utf-8"), (second, "new SRT", "utf-8")])
    assert link.is_symlink() and link.readlink() == value
    assert second.read_text(encoding="utf-8") == "old SRT"
    assert_target_unchanged(target)
    assert_no_temps(link.parent)


def test_failed_link_cleanup_does_not_chmod_its_target(tmp_path, monkeypatch):
    from bilingual_sub.core.file_io import discard_temporary

    target = tmp_path / "readonly.txt"
    target.write_text("keep content", encoding="utf-8")
    original_mode = target.stat().st_mode
    link = tmp_path / "temporary-link"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Host cannot create test symlinks: {exc}")
    target.chmod(original_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    readonly_mode = target.stat().st_mode
    unlink = Path.unlink
    def denied(path, *args, **kwargs):
        if path == link:
            raise PermissionError("link deletion denied")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", denied)
    try:
        with pytest.raises(PermissionError, match="link deletion denied"):
            discard_temporary(link)
        assert target.stat().st_mode == readonly_mode
        assert target.read_text(encoding="utf-8") == "keep content"
    finally:
        target.chmod(original_mode)


def test_existing_directory_link_is_rejected_without_replacing_it(tmp_path):
    target = tmp_path / "directory"
    target.mkdir()
    link = tmp_path / "output.ass"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Host cannot create test symlinks: {exc}")
    with pytest.raises(OSError):
        write_text_files([(link, "new ASS", "utf-8")])
    assert link.is_symlink() and link.resolve() == target
    assert target.is_dir()
    assert_no_temps(link.parent)
