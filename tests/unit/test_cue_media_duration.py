import math

import pytest

from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.models import Segment, WordSpan


@pytest.mark.parametrize("duration,expected", [(1.15, 1.15), (1.685, 1.68), (1.005, 1.0), (.009, None), (0, None)])
def test_media_end_rounds_inward_at_ass_precision(duration, expected):
    cues = build_cues([Segment(0, 2, "你好")], [], Glossary(), media_duration=duration)
    if expected is None:
        assert cues == []
    else:
        assert len(cues) == 1 and cues[0].end == expected and cues[0].end <= duration


@pytest.mark.parametrize("duration", [-1, math.nan, math.inf, -math.inf])
def test_invalid_media_end_is_rejected(duration):
    with pytest.raises(ValueError, match="时长"):
        build_cues([], [], Glossary(), media_duration=duration)


def test_late_aligned_segment_is_excluded_before_words_are_joined():
    segments = [Segment(0, 1, "有效台词", (WordSpan(0, 1, "有效台词"),)),
                Segment(2, 3, "越界台词", (WordSpan(2, 3, "越界台词"),))]
    cues = build_cues(segments, [], Glossary(), media_duration=1.5)
    assert [c.zh for c in cues] == ["有效台词"]
    assert len(cues[0].words) == 1
    assert segments[1].text == "越界台词"


def test_partial_alignment_is_removed_without_losing_recognized_text():
    segment = Segment(0, 2, "保留全文。", (WordSpan(0, 1, "保留全文"), WordSpan(1, 2, "。")))
    cues = build_cues([segment], [], Glossary(), media_duration=1.5)
    assert len(cues) == 1 and cues[0].zh == "保留全文。" and cues[0].end == 1.5
    assert not cues[0].words and len(segment.words) == 2


def test_subcentisecond_remaining_cue_is_not_extended_past_end():
    assert build_cues([Segment(1.679, 2, "太短")], [], Glossary(), media_duration=1.685) == []
