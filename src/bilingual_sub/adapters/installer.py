"""Locate the pinned installer used by source runs and packaged clients."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.core.control import JobControl, JobStopped, wait_for_process

UV_VERSION = "0.11.8"
# macOS may inspect a newly mounted executable before its first instruction,
# particularly through Rosetta. Keep cancellation active during this allowance.
UV_VERSION_TIMEOUT = 60.0 if sys.platform == "darwin" else 5.0


def _package_uv() -> Path | None:
    try:
        from uv import find_uv_bin

        return Path(find_uv_bin())
    except (ImportError, OSError):
        return None


def _uv_version(path: Path, control: JobControl | None = None) -> str:
    if control:
        control.wait_if_paused()
    deadline = time.monotonic() + UV_VERSION_TIMEOUT
    def check_timeout() -> None:
        if time.monotonic() >= deadline:
            raise RuntimeError("uv 版本检查超时")
    with tempfile.TemporaryFile() as output:
        with owned_process([str(path), "--version"], stdin=subprocess.DEVNULL,
                           stdout=output, stderr=subprocess.STDOUT) as proc:
            code = wait_for_process(proc, control=control, on_tick=check_timeout)
        output.seek(0)
        lines = output.read(512).decode("utf-8", errors="replace").splitlines()
    if code:
        raise RuntimeError("uv 版本检查失败")
    match = re.fullmatch(r"uv (\d+\.\d+\.\d+)(?:[ \t].*)?", lines[0] if lines else "")
    if not match:
        raise RuntimeError("无法识别 uv 版本")
    return match[1]


def find_uv(*, control: JobControl | None = None) -> Path:
    if control:
        control.wait_if_paused()
    frozen = bool(getattr(sys, "frozen", False))
    name = "uv.exe" if os.name == "nt" else "uv"
    candidates: list[Path] = []
    if frozen:
        resources = getattr(sys, "_MEIPASS", None)
        if resources:
            candidates.append(Path(resources) / name)
        candidates.append(Path(sys.executable).parent / name)
    else:
        packaged = _package_uv()
        if packaged is not None:
            candidates.append(packaged)
        found = shutil.which("uv")
        if found:
            candidates.append(Path(found))
    failures = []
    seen = set()
    for path in candidates:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            version = _uv_version(path, control)
            if version == UV_VERSION:
                return path
            failures.append(f"{path}: uv {version}")
        except JobStopped:
            raise
        except (OSError, RuntimeError) as exc:
            failures.append(f"{path}: {exc}")
    guidance = ("内置安装器缺失或版本不符，请重新下载完整客户端" if frozen else
                f"请在运行 SubFlow 的 Python 环境执行 python -m pip install uv=={UV_VERSION}")
    detail = "；".join(failures)
    raise RuntimeError(f"需要 uv {UV_VERSION}。{guidance}" + (f"。检查结果：{detail}" if detail else ""))
