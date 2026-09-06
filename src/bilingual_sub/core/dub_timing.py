"""Fit measured speech to a bounded, non-overlapping narration timeline."""
from __future__ import annotations

import math

MAX_SHIFT = 0.6


def plan_speech(windows: list[tuple[float, float, float]], duration: float) -> list[tuple[float, float]]:
    """Return (start, available seconds), borrowing pauses before increasing tempo.

    Each start stays within 600 ms of its subtitle; speech may use the following
    pause. A backwards deadline pass reserves room for all subsequent phrases.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be positive and finite")
    if not windows:
        return []
    releases, deadlines, lengths = [], [], []
    previous = -1.0
    for i, (start, end, seconds) in enumerate(windows):
        if (not all(math.isfinite(x) for x in (start, end, seconds))
                or start < previous or start < 0 or start >= duration or end <= start or seconds <= 0):
            raise ValueError("invalid or unordered narration interval")
        previous = start
        next_start = windows[i + 1][0] if i + 1 < len(windows) else duration
        releases.append(max(0.0, start - MAX_SHIFT))
        deadlines.append(min(duration, max(end, next_start - .08) + MAX_SHIFT))
        lengths.append(seconds)

    def latest_starts(rate):
        latest = [0.0] * len(windows)
        following = duration
        for i in range(len(windows) - 1, -1, -1):
            latest[i] = min(deadlines[i], following) - lengths[i] / rate
            # A narration line cannot drift arbitrarily late just because the
            # next subtitle happens much later.
            latest[i] = min(latest[i], windows[i][0] + MAX_SHIFT)
            following = latest[i]
        return latest

    def feasible(rate):
        return all(t >= release - 1e-9 for t, release in zip(latest_starts(rate), releases))

    rate = 1.0
    if not feasible(rate):
        high = 2.0
        while not feasible(high):
            high *= 2
        low = 1.0
        for _ in range(48):
            mid = (low + high) / 2
            if feasible(mid):
                high = mid
            else:
                low = mid
        rate = high * (1 + 1e-8)
    latest = latest_starts(rate)
    result = []
    finish = 0.0
    for i, (start, _end, seconds) in enumerate(windows):
        placed = max(finish, releases[i], min(start, latest[i]))
        limit = min(deadlines[i], latest[i + 1] if i + 1 < len(windows) else duration)
        available = min(seconds, limit - placed)
        if available <= 0:
            raise ValueError("narration has no available time")
        result.append((placed, available))
        finish = placed + available
    return result
