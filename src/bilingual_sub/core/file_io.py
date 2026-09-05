"""Stage output beside its destination before replacing existing user files."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

Checkpoint = Callable[[], None] | None


def discard_temporary(path: Path) -> None:
    """Remove only a temporary file owned by the calling operation."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        # copystat/copy2 can make our private temporary file read-only on Windows.
        if path.is_file():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        path.unlink(missing_ok=True)


@contextmanager
def staged_path(destination: Path, *, suffix: str = ".tmp") -> Iterator[Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".subflow-output-", suffix=suffix)
    os.close(fd)
    pending = Path(name)
    try:
        yield pending
    finally:
        discard_temporary(pending)


def _check(checkpoint: Checkpoint) -> None:
    if checkpoint:
        checkpoint()


def file_digest(path: Path, *, checkpoint: Checkpoint = None) -> str:
    """Hash all content without loading a video into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while True:
            _check(checkpoint)
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino
        ):
            raise OSError(f"校验时文件发生变化，请重试：{path}")
    return digest.hexdigest()


def copy_file(source: Path, destination: Path, *, checkpoint: Checkpoint = None) -> None:
    """Copy in bounded chunks; a failed or cancelled copy keeps the old target."""
    _check(checkpoint)
    if not source.is_file():
        raise FileNotFoundError(f"复制源文件不存在或不是普通文件：{source}")
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        return
    with staged_path(destination) as pending:
        with source.open("rb") as reader, pending.open("wb") as writer:
            before = os.fstat(reader.fileno())
            while True:
                _check(checkpoint)
                chunk = reader.read(1024 * 1024)
                if not chunk:
                    break
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                after.st_size, after.st_mtime_ns, after.st_ino
            ):
                raise OSError(f"复制时源文件发生变化，请重试：{source}")
        shutil.copystat(source, pending)
        _check(checkpoint)
        pending.replace(destination)


def write_text_files(
    files: list[tuple[Path, str, str]], *, checkpoint: Checkpoint = None,
) -> None:
    """Prepare all text outputs; restore earlier files if a later replace fails.

    This is rollback for reported I/O errors, not a filesystem-wide atomic
    transaction or protection against process termination during the commit.
    """
    paths = [path for path, _, _ in files]
    for i, path in enumerate(paths):
        for other in paths[:i]:
            if path.resolve() == other.resolve() or (
                path.exists() and other.exists() and path.samefile(other)
            ):
                raise ValueError(f"字幕输出路径不能重复：{path}")
    pending: dict[Path, Path] = {}
    backups: dict[Path, Path | None] = {}
    committed: list[Path] = []
    retained: set[Path] = set()
    try:
        for path, text, encoding in files:
            _check(checkpoint)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=path.parent, prefix=".subflow-output-", suffix=".tmp")
            pending[path] = Path(name)
            with os.fdopen(fd, "wb") as stream:
                stream.write(text.encode(encoding))
                stream.flush()
                os.fsync(stream.fileno())
            backups[path] = None
            if path.exists():
                fd, name = tempfile.mkstemp(dir=path.parent, prefix=".subflow-backup-", suffix=".tmp")
                os.close(fd)
                backups[path] = Path(name)
                shutil.copy2(path, name)
        _check(checkpoint)
        try:
            for path in paths:
                pending[path].replace(path)
                committed.append(path)
        except OSError as exc:
            failures = []
            for path in reversed(committed):
                backup = backups[path]
                try:
                    if backup is None:
                        path.unlink(missing_ok=True)
                    else:
                        backup.replace(path)
                except OSError:
                    if backup is not None:
                        retained.add(backup)
                    failures.append(f"{path} (备份：{backup})")
            if failures:
                raise OSError("字幕提交失败，部分文件需从保留备份恢复：" + "; ".join(failures)) from exc
            raise
    finally:
        for temp in [*pending.values(), *backups.values()]:
            if temp is not None and temp not in retained:
                discard_temporary(temp)
