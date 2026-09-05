"""Validate export destinations before any file is changed."""
import os
import sys
import unicodedata
from pathlib import Path


def same_file(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


def path_comparison_key(path: str) -> str:
    """Conservative reservation key; never use this to skip a file copy."""
    key = os.path.normcase(path)
    if sys.platform == "darwin":
        # APFS normally ignores case and canonical Unicode representation.
        # Reserve these aliases even on case-sensitive or non-APFS Mac volumes.
        key = unicodedata.normalize("NFD", key).casefold()
    return key


def paths_conflict(left: Path, right: Path) -> bool:
    return same_file(left, right) or (
        path_comparison_key(str(left.resolve())) == path_comparison_key(str(right.resolve()))
    )


def validate_outputs(outputs: dict[str, Path], protected: list[Path]) -> None:
    seen: list[tuple[str, Path]] = []
    for label, path in outputs.items():
        if any(paths_conflict(path, source) for source in protected):
            raise ValueError(f"{label}输出路径会覆盖输入文件：{path}，请选择其他路径")
        for other_label, other in seen:
            if paths_conflict(path, other):
                raise ValueError(f"{label}与{other_label}输出路径冲突：{path}")
        seen.append((label, path))
