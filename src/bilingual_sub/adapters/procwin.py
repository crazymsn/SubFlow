"""Hide console windows for child processes on Windows GUI builds."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def hidden_run_kwargs() -> dict:
    if os.name != "nt":
        return {}
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": info,
        "stdin": subprocess.DEVNULL,
    }


def gui_python(python: Path) -> Path:
    """Keep python.exe. pythonw + Torch/CUDA often looks frozen and hides errors."""
    return python


def terminate_process_tree(proc: subprocess.Popen) -> None:
    """Windows venv launchers spawn another python.exe; stop that child too."""
    if proc.poll() is not None:
        return
    pid = getattr(proc, "pid", None)
    if os.name == "nt" and pid:
        killer = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"
        subprocess.run(
            [str(killer), "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=10, check=False, **hidden_run_kwargs(),
        )
    if proc.poll() is None and hasattr(proc, "terminate"):
        proc.terminate()


def is_hidden_kwargs(kwargs: dict) -> bool:
    if sys.platform != "win32":
        return True
    flags = kwargs.get("creationflags", 0)
    return bool(flags & subprocess.CREATE_NO_WINDOW)
