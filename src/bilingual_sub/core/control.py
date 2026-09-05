"""Cooperative pause / resume / stop for pipeline stages."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable

import psutil

from bilingual_sub.adapters.procwin import signal_posix_process, terminate_process_tree


class JobStopped(RuntimeError):
    def __init__(self, message: str = "job stopped") -> None:
        super().__init__(message)


class JobPaused(RuntimeError):
    def __init__(self, message: str = "job paused") -> None:
        super().__init__(message)


def _suspend_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        if not isinstance(proc.pid, int):
            return
        root = psutil.Process(proc.pid)
        root.suspend()
        seen = {proc.pid}
        while True:
            children = [p for p in root.children(recursive=True) if p.pid not in seen]
            if not children:
                break
            for child in children:
                try:
                    child.suspend()
                except psutil.NoSuchProcess:
                    pass
                seen.add(child.pid)
    else:
        signal_posix_process(proc, signal.SIGSTOP)


def _resume_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        if not isinstance(proc.pid, int):
            return
        root = psutil.Process(proc.pid)
        for child in reversed(root.children(recursive=True)):
            try:
                child.resume()
            except psutil.NoSuchProcess:
                pass
        root.resume()
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
    timeout: float | None = None,
) -> int:
    """Own a logged worker until exit, including callback errors and cancellation."""
    try:
        if control:
            control.attach_proc(proc)
        deadline = time.monotonic() + timeout if timeout is not None else None
        while proc.poll() is None:
            if control:
                paused_at = time.monotonic()
                control.wait_if_paused()
                if deadline is not None:
                    deadline += time.monotonic() - paused_at
            remaining = deadline - time.monotonic() if deadline is not None else interval
            if timeout is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(proc.args, timeout)
            if on_tick:
                on_tick()
            try:
                proc.wait(timeout=min(interval, remaining))
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
            except (OSError, psutil.Error):
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

    def wait_seconds(self, seconds: float) -> None:
        """Cancellable retry backoff; never start another request while paused."""
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self.wait_if_paused()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._stop.wait(min(remaining, 0.1))

    def attach_proc(self, proc: subprocess.Popen[str]) -> None:
        with self._lock:
            if proc not in self._procs:
                self._procs.append(proc)
            stopped = self._stop.is_set()
            if not stopped and self.is_paused():
                try:
                    _suspend_proc(proc)
                except (OSError, psutil.Error):
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
