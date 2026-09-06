"""Truthful completed-work progress, with a heartbeat during slow operations."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

Progress = Callable[[str, float], None] | None


class DubProgress:
    def __init__(self, callback: Progress, *, interval: float = 1.0):
        self.callback = callback
        self.interval = interval
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = ("prepare", 0, 0, 0.0)
        self._since = time.monotonic()
        self._error: Exception | None = None

    def __enter__(self):
        if self.callback:
            self._thread = threading.Thread(target=self._pulse, name="subflow-dub-progress", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, kind, value, traceback):
        self._stop.set()
        if self._thread:
            self._thread.join()
        if kind is None and self._error:
            raise self._error

    def set(self, phase: str, current: int, total: int, fraction: float) -> None:
        with self._lock:
            if self._error:
                raise self._error
            self._state = (phase, current, total, fraction)
            self._since = time.monotonic()
            self._emit()

    def _emit(self):
        if self.callback:
            phase, current, total, fraction = self._state
            elapsed = max(0, int(time.monotonic() - self._since))
            self.callback(f"dub|{phase}|{current}|{total}|{elapsed}", fraction)

    def _pulse(self):
        while not self._stop.wait(self.interval):
            with self._lock:
                try:
                    self._emit()
                except Exception as exc:
                    self._error = exc
                    return
