"""Cooperative pause / resume / stop for pipeline stages."""

from __future__ import annotations

import subprocess
import threading


class JobStopped(RuntimeError):
    def __init__(self, message: str = "job stopped") -> None:
        super().__init__(message)


class JobPaused(RuntimeError):
    def __init__(self, message: str = "job paused") -> None:
        super().__init__(message)


class JobControl:
    def __init__(self) -> None:
        self._pause = threading.Event()
        self._pause.set()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._procs: list[subprocess.Popen[str]] = []

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def stop(self) -> None:
        self._stop.set()
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
            self._procs.append(proc)
        if self._stop.is_set():
            self.kill_attached()

    def kill_attached(self) -> None:
        with self._lock:
            procs = list(self._procs)
            self._procs.clear()
        for proc in procs:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
