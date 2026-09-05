"""Cooperative pause / resume / stop for pipeline stages."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
from collections.abc import Callable

from bilingual_sub.adapters.procwin import signal_posix_process, terminate_process_tree


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
        signal_posix_process(proc, signal.SIGSTOP)


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
        signal_posix_process(proc, signal.SIGCONT)


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


def wait_for_process(
    proc: subprocess.Popen, *, control: JobControl | None = None,
    on_tick: Callable[[], None] | None = None, interval: float = 0.2,
) -> int:
    """Own a logged worker until exit, including callback errors and cancellation."""
    try:
        if control:
            control.attach_proc(proc)
        while proc.poll() is None:
            if control:
                control.wait_if_paused()
            if on_tick:
                on_tick()
            try:
                proc.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                pass
        if control:
            control.check()
        return proc.returncode
    finally:
        if proc.poll() is None:
            _force_kill(proc)
        try:
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if control:
            control.detach_proc(proc)


class JobControl:
    def __init__(self) -> None:
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        self._lock = threading.RLock()
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
        with self._lock:
            self._pause.clear()
            self._each_proc(_suspend_proc)

    def resume(self) -> None:
        with self._lock:
            self._each_proc(_resume_proc)
            self._pause.set()

    def stop(self) -> None:
        with self._lock:
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
            stopped = self._stop.is_set()
            if not stopped and self.is_paused():
                try:
                    _suspend_proc(proc)
                except (OSError, ProcessLookupError):
                    pass
        if stopped:
            self.kill_attached()

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
        errors: list[Exception] = []

        def _read() -> None:
            try:
                box["io"] = proc.communicate()
            except Exception as exc:
                errors.append(exc)

        reader = threading.Thread(target=_read, name="subflow-proc-io", daemon=True)
        reader.start()
        try:
            while reader.is_alive():
                self.wait_if_paused()
                reader.join(timeout=0.2)
            if self.is_stopped():
                raise JobStopped()
            if errors:
                raise RuntimeError("读取子进程输出失败") from errors[0]
            if "io" not in box:
                raise RuntimeError("子进程没有返回输出状态")
            return box["io"]
        finally:
            if proc.poll() is None:
                _force_kill(proc)
            reader.join(timeout=3)
            try:
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
            self.detach_proc(proc)
