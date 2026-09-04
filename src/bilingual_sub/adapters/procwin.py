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


def is_hidden_kwargs(kwargs: dict) -> bool:
    if sys.platform != "win32":
        return True
    flags = kwargs.get("creationflags", 0)
    return bool(flags & subprocess.CREATE_NO_WINDOW)
