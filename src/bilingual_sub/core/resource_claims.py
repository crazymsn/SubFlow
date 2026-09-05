"""Cooperating SubFlow processes reserve inputs, outputs and work directories."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from bilingual_sub.core.file_io import Checkpoint
from bilingual_sub.core.output_guard import path_comparison_key, same_file
from bilingual_sub.core.persistence import write_json


def registry_dir() -> Path:
    override = os.environ.get("SUBFLOW_LOCK_DIR")
    return (Path(override).expanduser() if override else
            Path.home() / ".cache" / "bilingual-sub" / "resource-locks").resolve()


def _key(path: str) -> str:
    return path_comparison_key(path)


def _overlap(left: tuple[str, bool], right: tuple[str, bool]) -> bool:
    a, a_tree = left
    b, b_tree = right
    ka, kb = Path(_key(a)), Path(_key(b))
    if ka == kb or (a_tree and kb.is_relative_to(ka)) or (b_tree and ka.is_relative_to(kb)):
        return True
    return same_file(Path(a), Path(b))


def _entries(record: dict, field: str) -> list[tuple[str, bool]]:
    values = record.get(field)
    if not isinstance(values, list) or any(not isinstance(p, str) for p in values):
        raise ValueError("invalid resource claim")
    if any(not Path(p).is_absolute() for p in values):
        raise ValueError("resource claim paths must be absolute")
    return [(p, field == "trees") for p in values]


@contextmanager
def _guard(root: Path, checkpoint: Checkpoint) -> Iterator[None]:
    gate = FileLock(str(root / "registry.lock"))
    deadline = time.monotonic() + 10
    while True:
        if checkpoint:
            checkpoint()
        try:
            gate.acquire(timeout=0.1)
            break
        except Timeout as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("文件使用登记繁忙，请稍后重试") from exc
    try:
        yield
    finally:
        gate.release()


def _live_records(root: Path) -> Iterator[dict]:
    # A process may stop after taking ownership but before publishing a record.
    for orphan in root.glob("*.lock"):
        if not re.fullmatch(r"[0-9a-f]{32}", orphan.stem) or orphan.with_suffix(".json").exists():
            continue
        probe = FileLock(str(orphan))
        try:
            probe.acquire(timeout=0)
        except Timeout:
            continue
        probe.release()
        orphan.unlink(missing_ok=True)
    for record_path in root.glob("*.json"):
        if not re.fullmatch(r"[0-9a-f]{32}", record_path.stem):
            continue
        owner_path = record_path.with_suffix(".lock")
        probe = FileLock(str(owner_path))
        try:
            probe.acquire(timeout=0)
        except Timeout:
            try:
                record = json.loads(record_path.read_text(encoding="utf-8"))
                if not isinstance(record, dict) or record.get("version") != 1:
                    raise ValueError("invalid resource claim version")
                for field in ("reads", "writes", "trees"):
                    _entries(record, field)
            except (OSError, ValueError) as exc:
                raise RuntimeError("正在运行的任务登记无法读取；请等待该任务退出后重试") from exc
            yield record
        else:
            probe.release()
            # OS ownership, not a PID or timestamp, proves that this record is stale.
            record_path.unlink(missing_ok=True)
            owner_path.unlink(missing_ok=True)


@contextmanager
def claim_resources(
    *, reads: list[Path], writes: list[Path], trees: list[Path] | None = None,
    checkpoint: Checkpoint = None,
) -> Iterator[None]:
    if checkpoint:
        checkpoint()
    record = {"version": 1, "reads": [str(p.resolve()) for p in reads],
              "writes": [str(p.resolve()) for p in writes],
              "trees": [str(p.resolve()) for p in trees or []]}
    mine_read = _entries(record, "reads")
    mine_write = _entries(record, "writes") + _entries(record, "trees")
    root = registry_dir()
    registry = (str(root.resolve()), True)
    if any(_overlap(entry, registry) for entry in mine_write):
        raise ValueError("输出或工作目录不能覆盖文件使用登记目录；请调整目录或 SUBFLOW_LOCK_DIR")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = uuid.uuid4().hex
    record_path = root / f"{token}.json"
    owner_path = root / f"{token}.lock"
    owner = FileLock(str(owner_path))
    owner.acquire(timeout=0)
    try:
        with _guard(root, checkpoint):
            for other in _live_records(root):
                other_read = _entries(other, "reads")
                other_write = _entries(other, "writes") + _entries(other, "trees")
                pairs = ((a, b) for a in mine_write for b in other_read + other_write)
                for a, b in pairs:
                    if _overlap(a, b):
                        raise RuntimeError(f"文件正在被另一任务使用：{a[0]}；请等待任务结束或选择其他输出")
                for a in mine_read:
                    if any(_overlap(a, b) for b in other_write):
                        raise RuntimeError(f"输入文件正在被另一任务写入：{a[0]}；请等待任务结束")
            write_json(record_path, record)
        if checkpoint:
            checkpoint()
        yield
    finally:
        # Cleanup must not keep a cancelled/failed job alive waiting for the
        # registry. If busy, leave a stale record for the next acquisition.
        gate = FileLock(str(root / "registry.lock"))
        acquired = False
        removed = False
        try:
            gate.acquire(timeout=0)
            acquired = True
            record_path.unlink(missing_ok=True)
            removed = True
        except (Timeout, OSError):
            pass
        finally:
            owner.release()
            if removed:
                try:
                    owner_path.unlink(missing_ok=True)
                except OSError:
                    pass
            if acquired:
                gate.release()
