"""Hide console windows for child processes on Windows GUI builds."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path


def hidden_run_kwargs() -> dict:
    if os.name != "nt":
        return {"start_new_session": os.environ.get("SUBFLOW_WORKER_PROCESS_GROUP") != "1"}
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
    if sys.platform != "win32" and isinstance(pid, int):
        signal_posix_process(proc, signal.SIGKILL)
        return
    if os.name == "nt" and pid:
        killer = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"
        subprocess.run(
            [str(killer), "/PID", str(pid), "/T", "/F"],
            capture_output=True, timeout=10, check=False, **hidden_run_kwargs(),
        )
    if proc.poll() is None and hasattr(proc, "terminate"):
        proc.terminate()


def signal_posix_process(proc: subprocess.Popen, sig: int) -> None:
    """Signal an owned session's children; never signal a shared shell group."""
    if sys.platform == "win32":
        raise NotImplementedError("POSIX process signals are unavailable on Windows")
    pid = proc.pid
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except ProcessLookupError:
        pass


def is_hidden_kwargs(kwargs: dict) -> bool:
    if sys.platform != "win32":
        return True
    flags = kwargs.get("creationflags", 0)
    return bool(flags & subprocess.CREATE_NO_WINDOW)
