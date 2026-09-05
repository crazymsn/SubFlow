import json

import pytest

from bilingual_sub.adapters.transcript_io import normalize_transcript, write_transcript
from bilingual_sub.adapters.whisper_backend import load_transcript
from bilingual_sub.core.control import JobStopped
from bilingual_sub.core.cues import build_cues, cues_from_words
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.render import ass_time, srt_time
from bilingual_sub.models import Segment, WordSpan


@pytest.mark.parametrize("data", [None, [], {}, {"segments": {}}, {"segments": [None]},
    {"segments": [{"start": 0, "end": 1, "text": 42}]}])
def test_bad_transcript_shape_is_not_silently_empty(data):
    with pytest.raises(ValueError, match="Invalid ASR"):
        normalize_transcript(data)


@pytest.mark.parametrize("start,end", [(float("nan"), 1), (0, float("inf")), (-1, 1),
    (True, 2), (0, None), (2, 1), (1, 1), ("nan", 1)])
def test_invalid_segment_timing_is_rejected(start, end):
    with pytest.raises(ValueError, match="Invalid ASR"):
        normalize_transcript({"segments": [{"start": start, "end": end, "text": "完整文字"}]})


def test_invalid_word_timing_keeps_the_full_sentence(tmp_path):
    path = tmp_path / "transcript.json"
    write_transcript(path, {"segments": [{"start": 0, "end": 2, "text": "有对齐和没有对齐", "words": [
        {"start": 0, "end": 1, "word": "有对齐"}, {"word": "和没有对齐"},
    ]}]})
    segs = load_transcript(path)
    assert segs[0].text == "有对齐和没有对齐" and not segs[0].words
    assert "没有对齐" in build_cues(segs, [], Glossary())[0].zh


def test_mixed_alignment_preserves_sentences_and_good_word_timing():
    segs = [Segment(0, 2, "第一句。", (WordSpan(0.2, 1.1, "第一句。"),)),
            Segment(3, 4, "不能丢失的中间句。"),
            Segment(5, 7, "第三句。", (WordSpan(5.3, 6.2, "第三句。"),))]
    assert cues_from_words(segs, Glossary()) is None
    cues = build_cues(segs, [], Glossary())
    assert [c.zh for c in cues] == [s.text for s in segs]
    assert (cues[0].start, cues[0].end) == (0.2, 1.1)
    assert (cues[-1].start, cues[-1].end) == (5.3, 6.2)


def test_incomplete_alignment_does_not_drop_unaligned_words():
    cues = build_cues([Segment(0, 3, "Keep every word.", (WordSpan(0, 1, "Keep"),))], [], Glossary())
    assert cues[0].zh == "Keep every word."


def test_word_start_at_zero_survives_round_trip(tmp_path):
    path = tmp_path / "t.json"
    write_transcript(path, {"segments": [{"start": 0, "end": 1, "text": "hi", "words": [
        {"start": 0, "end": 0.4, "word": "hi"}]}]})
    assert load_transcript(path)[0].words[0].start == 0


def test_transcript_replace_failure_preserves_previous_result(tmp_path, monkeypatch):
    path = tmp_path / "t.json"
    old = b'{"language":"zh","segments":[]}'
    path.write_bytes(old)
    def fail(*args):
        raise OSError("disk commit failed")
    monkeypatch.setattr(type(path), "replace", fail)
    with pytest.raises(OSError, match="disk commit"):
        write_transcript(path, {"segments": [{"start": 0, "end": 1, "text": "new"}]})
    assert path.read_bytes() == old
    assert not list(tmp_path.glob(".transcript-*"))


def test_cancel_before_atomic_commit_preserves_previous_result(tmp_path):
    path = tmp_path / "t.json"
    path.write_bytes(b"previous transcript")
    def cancel():
        raise JobStopped()
    with pytest.raises(JobStopped):
        write_transcript(path, {"segments": []}, before_commit=cancel)
    assert path.read_bytes() == b"previous transcript"
    assert not list(tmp_path.glob(".transcript-*"))


def test_reversed_word_ends_use_sentence_timing():
    data = normalize_transcript({"segments": [{"start": 0, "end": 3, "text": "one two", "words": [
        {"start": 0, "end": 2, "word": "one"}, {"start": 1, "end": 1.5, "word": "two"}]}]})
    assert data["segments"][0]["words"] == []
    cues = build_cues([Segment(0, 3, "one two", (WordSpan(0, 2, "one"), WordSpan(1, 1.5, "two")))], [], Glossary())
    assert cues[0].zh == "one two" and not cues[0].words


def test_unordered_cache_rejected(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"segments": [
        {"start": 2, "end": 3, "text": "later"}, {"start": 0, "end": 1, "text": "earlier"}]}))
    with pytest.raises(ValueError, match="unordered"):
        load_transcript(path)


@pytest.mark.parametrize("seconds,srt,ass", [
    (59.9996, "00:01:00,000", "0:01:00.00"),
    (3599.9996, "01:00:00,000", "1:00:00.00"),
    (59.996, "00:00:59,996", "0:01:00.00"),
    (3600.123, "01:00:00,123", "1:00:00.12"),
])
def test_subtitle_timestamp_rounding_carries_minutes_and_hours(seconds, srt, ass):
    assert srt_time(seconds) == srt
    assert ass_time(seconds) == ass


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf")])
def test_nonfinite_or_negative_subtitle_time_is_rejected(seconds):
    with pytest.raises(ValueError, match="timestamp"):
        srt_time(seconds)
    with pytest.raises(ValueError, match="timestamp"):
        ass_time(seconds)
