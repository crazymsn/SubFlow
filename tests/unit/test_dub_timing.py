import random

import pytest

from bilingual_sub.core.dub_timing import MAX_SHIFT, plan_speech


def test_reported_145_percent_phrase_uses_leading_pause():
    windows = [(1.18, 4.10, 2.92 * 1.45), (4.10, 11.55, 7)]
    plan = plan_speech(windows, 12)
    assert windows[0][2] / plan[0][1] <= 1.25
    assert plan[0][0] + plan[0][1] <= plan[1][0] + 1e-7


def test_short_speech_keeps_natural_tempo_and_original_start():
    assert plan_speech([(1, 3, .8), (4, 6, 1.2)], 8) == [(1, .8), (4, 1.2)]


def test_dense_speech_does_not_fail_or_overlap_at_preferred_speed_limit():
    plan = plan_speech([(0, 1, 1.45), (1, 2, 1.45)], 2)
    assert sum(seconds for _, seconds in plan) == pytest.approx(2)
    assert plan[0][0] + plan[0][1] <= plan[1][0] + 1e-7


def test_random_timeline_never_loses_tail_overlaps_or_drifts_unbounded():
    rng = random.Random(159)
    for _ in range(100):
        windows = []
        time = 0
        for _ in range(20):
            start = time + rng.uniform(0, 2)
            end = start + rng.uniform(.2, 5)
            windows.append((start, end, rng.uniform(.2, 8)))
            time = end
        duration = time + .1
        plan = plan_speech(windows, duration)
        for i, ((source, _, raw), (start, length)) in enumerate(zip(windows, plan)):
            assert abs(start - source) <= MAX_SHIFT + 1e-6
            assert 0 <= start and 0 < length <= raw
            assert start + length <= (plan[i + 1][0] if i + 1 < len(plan) else duration) + 1e-6


@pytest.mark.parametrize('windows', [[(2, 3, 1), (0, 1, 1)], [(0, 1, 0)], [(0, float('nan'), 1)]])
def test_invalid_timing_is_rejected(windows):
    with pytest.raises(ValueError):
        plan_speech(windows, 5)
