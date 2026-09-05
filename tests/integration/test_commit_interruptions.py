import os
import subprocess
import sys
from pathlib import Path

import pytest

from bilingual_sub.core.file_io import write_text_files


@pytest.mark.parametrize("kind", ["plain", "hardlink", "symlink"])
@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit, OSError])
@pytest.mark.parametrize("after_replace", [False, True])
def test_interrupted_commit_restores_both_outputs(tmp_path, monkeypatch, kind, error, after_replace):
    first, second, alias = tmp_path / "first.ass", tmp_path / "second.srt", tmp_path / "alias.ass"
    if kind == "symlink":
        alias.write_bytes(b"old first")
        try:
            first.symlink_to(alias.name)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"Host cannot create symlinks: {exc}")
    else:
        first.write_bytes(b"old first")
        if kind == "hardlink":
            alias.hardlink_to(first)
    second.write_bytes(b"old second")
    replace = Path.replace
    def interrupt(path, target):
        if target == second and path.name.startswith(".subflow-output-"):
            if after_replace:
                replace(path, target)
            raise error("injected interruption")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", interrupt)
    with pytest.raises(error, match="injected interruption"):
        write_text_files([(first, "new first", "utf-8"), (second, "new second", "utf-8")])
    assert first.read_bytes() == b"old first"
    assert second.read_bytes() == b"old second"
    if kind != "plain":
        assert first.samefile(alias)
    assert first.is_symlink() == (kind == "symlink")
    assert not list(tmp_path.glob(".subflow-*.tmp"))


def test_interruption_during_rollback_keeps_backup(tmp_path, monkeypatch):
    first, second = tmp_path / "first.ass", tmp_path / "second.srt"
    first.write_bytes(b"old first")
    second.write_bytes(b"old second")
    replace = Path.replace
    def interrupt(path, target):
        if target == second:
            raise OSError("second commit failed")
        if path.name.startswith(".subflow-backup-"):
            raise KeyboardInterrupt("rollback interrupted")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", interrupt)
    with pytest.raises(BaseException) as error:
        write_text_files([(first, "new first", "utf-8"), (second, "new second", "utf-8")])
    assert isinstance(error.value, OSError) and "保留备份" in str(error.value)
    backups = list(tmp_path.glob(".subflow-backup-*.tmp"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old first"
    assert str(backups[0]) in str(error.value)
    assert second.read_bytes() == b"old second"


def test_real_sigint_after_replace_restores_outputs(tmp_path):
    script = '''import signal,sys
from pathlib import Path
from bilingual_sub.core.file_io import write_text_files
folder=Path(sys.argv[1]); first=folder/'first.ass'; second=folder/'second.srt'
first.write_bytes(b'old first'); second.write_bytes(b'old second')
replace=Path.replace
def interrupt(path,target):
    result=replace(path,target)
    if target==second and path.name.startswith('.subflow-output-'):
        signal.raise_signal(signal.SIGINT)
    return result
Path.replace=interrupt
try:
    write_text_files([(first,'new first','utf-8'),(second,'new second','utf-8')])
except KeyboardInterrupt:
    print('KeyboardInterrupt')
else:
    raise AssertionError('SIGINT was not delivered')
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "KeyboardInterrupt"
    assert (tmp_path / "first.ass").read_bytes() == b"old first"
    assert (tmp_path / "second.srt").read_bytes() == b"old second"
    assert not list(tmp_path.glob(".subflow-*.tmp"))


def test_second_interrupt_between_rollback_entries_retains_unrestored_backup(tmp_path, monkeypatch):
    from bilingual_sub.core import file_io

    first, second = tmp_path / "first.ass", tmp_path / "second.srt"
    first.write_bytes(b"old first")
    second.write_bytes(b"old second")
    replace = Path.replace
    def fail_after_replace(path, target):
        result = replace(path, target)
        if target == second and path.name.startswith(".subflow-output-"):
            raise OSError("commit failed after replacement")
        return result
    def interrupt_iteration(items):
        yield items[-1]
        raise KeyboardInterrupt("second interrupt between rollback operations")
    monkeypatch.setattr(Path, "replace", fail_after_replace)
    monkeypatch.setattr(file_io, "reversed", interrupt_iteration, raising=False)
    with pytest.raises(KeyboardInterrupt, match="second interrupt"):
        write_text_files([(first, "new first", "utf-8"), (second, "new second", "utf-8")])
    backups = list(tmp_path.glob(".subflow-backup-*.tmp"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old first"
    assert second.read_bytes() == b"old second"
