from bilingual_sub.core.cues import build_cues, cues_from_words
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.models import Segment, WordSpan


def test_cues_from_words_joins_english_with_spaces():
    segs = [
        Segment(
            0.0,
            2.0,
            "Hello world.",
            words=(
                WordSpan(0.0, 0.4, "Hello"),
                WordSpan(0.4, 0.9, "world"),
                WordSpan(0.9, 1.1, "."),
            ),
        )
    ]
    cues = cues_from_words(segs, Glossary())
    assert cues is not None
    assert cues[0].zh == "Hello world."


def test_cues_from_words_splits_on_punct():
    segs = [
        Segment(
            0.0,
            3.0,
            "你好。世界",
            words=(
                WordSpan(0.0, 0.8, "你好"),
                WordSpan(0.8, 1.0, "。"),
                WordSpan(1.2, 2.0, "世界"),
            ),
        )
    ]
    cues = cues_from_words(segs, Glossary())
    assert cues is not None
    assert len(cues) == 2
    assert cues[0].zh == "你好。"
    assert cues[1].zh == "世界"


def test_build_cues_prefers_words():
    segs = [
        Segment(
            0.0,
            2.0,
            "第一句。第二句",
            words=(
                WordSpan(0.0, 0.6, "第一句"),
                WordSpan(0.6, 0.8, "。"),
                WordSpan(1.0, 1.8, "第二句"),
            ),
        )
    ]
    cues = build_cues(segs, [], Glossary())
    assert len(cues) == 2


def test_build_cues_without_words_keeps_legacy():
    segs = [Segment(1.0, 3.0, "第一个叫Prefill")]
    cues = build_cues(segs, [], Glossary())
    assert len(cues) >= 1
    assert "Prefill" in cues[0].zh or "prefill" in cues[0].zh.lower()


def test_build_cues_keeps_short_chinese_clause():
    segs = [Segment(12.0, 12.8, "然后去")]
    cues = build_cues(segs, [], Glossary())
    assert [cue.zh for cue in cues] == ["然后去"]
