"""Cooperative pause / resume / stop for pipeline stages."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading

from bilingual_sub.adapters.procwin import terminate_process_tree


class JobStopped(RuntimeError):
    def __init__(self, message: str = "job stopped") -> None:
        super().__init__(message)


class JobPaused(RuntimeError):
    def __init__(self, message: str = "job paused") -> None:
        super().__init__(message)


def _proc_handle(proc: subprocess.Popen) -> int | None:
    handle = getattr(proc, "_handle", None)
    if handle is None:
        return None
    try:
        return int(handle)
    except (TypeError, ValueError):
        return None


def _suspend_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        handle = _proc_handle(proc)
        if handle is None:
            return
        import ctypes

        ctypes.windll.ntdll.NtSuspendProcess(handle)
    else:
        os.kill(proc.pid, signal.SIGSTOP)


def _resume_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        handle = _proc_handle(proc)
        if handle is None:
            return
        import ctypes

        ctypes.windll.ntdll.NtResumeProcess(handle)
    else:
        os.kill(proc.pid, signal.SIGCONT)


def _force_kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        terminate_process_tree(proc)
    except (OSError, AttributeError, subprocess.TimeoutExpired):
        pass
    try:
        if proc.poll() is None and hasattr(proc, "kill"):
            proc.kill()
    except (OSError, AttributeError):
        pass


class JobControl:
    def __init__(self) -> None:
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._procs: list[subprocess.Popen[str]] = []

    def _each_proc(self, fn) -> None:
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            try:
                fn(proc)
            except (OSError, ProcessLookupError):
                pass

    def pause(self) -> None:
        self._pause.clear()
        self._each_proc(_suspend_proc)

    def resume(self) -> None:
        self._each_proc(_resume_proc)
        self._pause.set()

    def stop(self) -> None:
        self._stop.set()
        self._each_proc(_resume_proc)
        self._pause.set()
        self.kill_attached()

    def is_paused(self) -> bool:
        return not self._pause.is_set() and not self._stop.is_set()

    def is_stopped(self) -> bool:
        return self._stop.is_set()

    def check(self) -> None:
        if self._stop.is_set():
            raise JobStopped()

    def wait_if_paused(self) -> None:
        self.check()
        self._pause.wait()
        self.check()

    def attach_proc(self, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            if proc not in self._procs:
                self._procs.append(proc)
        if self._stop.is_set():
            self.kill_attached()
            return
        if self.is_paused():
            try:
                _suspend_proc(proc)
            except (OSError, ProcessLookupError):
                pass

    def detach_proc(self, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            self._procs = [item for item in self._procs if item is not proc]

    def kill_attached(self) -> None:
        with self._lock:
            procs = list(self._procs)
            self._procs.clear()
        for proc in procs:
            _force_kill(proc)

    def run_attached(self, proc: subprocess.Popen[str]) -> tuple[str, str]:
        """Wait for a piped process, honoring pause / stop."""
        self.attach_proc(proc)
        box: dict[str, tuple[str, str]] = {}

        def _read() -> None:
            try:
                box["io"] = proc.communicate()
            except Exception:
                box["io"] = ("", "")

        reader = threading.Thread(target=_read, name="subflow-proc-io", daemon=True)
        reader.start()
        try:
            while reader.is_alive():
                self.wait_if_paused()
                reader.join(timeout=0.2)
            if self.is_stopped():
                raise JobStopped()
            return box.get("io", ("", ""))
        finally:
            self.detach_proc(proc)
