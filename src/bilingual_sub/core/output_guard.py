"""Validate export destinations before any file is changed."""
from pathlib import Path


def same_file(left: Path, right: Path) -> bool:
    if left.resolve() == right.resolve():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


def validate_outputs(outputs: dict[str, Path], protected: list[Path]) -> None:
    seen: list[tuple[str, Path]] = []
    for label, path in outputs.items():
        if any(same_file(path, source) for source in protected):
            raise ValueError(f"{label}输出路径会覆盖输入文件：{path}，请选择其他路径")
        for other_label, other in seen:
            if same_file(path, other):
                raise ValueError(f"{label}与{other_label}输出路径冲突：{path}")
        seen.append((label, path))
