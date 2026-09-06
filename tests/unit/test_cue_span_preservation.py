import pytest

from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.models import Segment, WordSpan


@pytest.mark.parametrize("text", [
    "这是一句需要从头到尾完整显示而不能只显示前八秒的中文台词",
    "Every spoken word in this long sentence must remain visible through the end of the original interval.",
])
def test_long_unaligned_cue_is_split_without_truncating_text_or_time(text):
    cues = build_cues([Segment(0, 20, text)], [], Glossary(), media_duration=20)
    assert cues[0].start == 0 and cues[-1].end == 20
    assert all(0 < c.end - c.start <= 8 for c in cues)
    assert all(a.end == b.start for a, b in zip(cues, cues[1:]))
    assert "".join(c.zh for c in cues).replace(" ", "") == text.replace(" ", "")
    if text.startswith("Every"):
        assert [w for c in cues for w in c.zh.split()] == text.split()


def aligned(words):
    return Segment(words[0].start, words[-1].end, " ".join(w.text for w in words), tuple(words))


@pytest.mark.parametrize("separate_segments", [False, True])
def test_aligned_english_sentences_keep_their_boundaries(separate_segments):
    first = [WordSpan(0, .5, "First"), WordSpan(.5, 1, "sentence.")]
    second = [WordSpan(1.1, 1.5, "Second"), WordSpan(1.5, 2, "sentence.")]
    segments = [aligned(first), aligned(second)] if separate_segments else [aligned(first + second)]
    cues = build_cues(segments, [], Glossary())
    assert [c.zh for c in cues] == ["First sentence.", "Second sentence."]
    assert [(c.start, c.end) for c in cues] == [(0, 1), (1.1, 2)]


def test_alignment_preserves_a_long_silent_gap_without_punctuation():
    words = [WordSpan(0, 1, "Before"), WordSpan(10, 11, "after")]
    cues = build_cues([aligned(words)], [], Glossary())
    assert [(c.start, c.end, c.zh) for c in cues] == [(0, 1, "Before"), (10, 11, "after")]


def test_long_alignment_splits_at_word_boundaries_and_keeps_every_word():
    words = [WordSpan(i, i + 1, f"word{i}") for i in range(20)]
    cues = build_cues([aligned(words)], [], Glossary())
    assert cues[0].start == 0 and cues[-1].end == 20
    assert all(c.end - c.start <= 8 for c in cues)
    assert [w for c in cues for w in c.words] == words
    assert [w for c in cues for w in c.zh.split()] == [w.text for w in words]


@pytest.mark.parametrize("text", ["Supercalifragilisticexpialidocious", "https://example.test/path"])
def test_indivisible_token_keeps_full_time_without_repetition(text):
    cues = build_cues([Segment(0, 20, text)], [], Glossary())
    assert [(c.start, c.end, c.zh) for c in cues] == [(0, 20, text)]


def test_titles_initials_and_decimal_numbers_do_not_end_sentences():
    tokens = ["Dr.", "J.", "Smith", "measured", "3.14", "metres."]
    words = [WordSpan(i * .2, (i + 1) * .2, w) for i, w in enumerate(tokens)]
    cues = build_cues([aligned(words)], [], Glossary())
    assert [c.zh for c in cues] == ["Dr. J. Smith measured 3.14 metres."]


def test_one_long_aligned_word_is_not_clipped_or_repeated():
    word = WordSpan(0, 12, "Hello")
    cues = build_cues([aligned([word])], [], Glossary())
    assert [(c.start, c.end, c.zh) for c in cues] == [(0, 12, "Hello")]
    assert cues[0].words == [word]


def test_unpunctuated_asr_segments_keep_their_boundaries():
    segments = [aligned([WordSpan(0, 1, "First")]), aligned([WordSpan(1.1, 2, "Second")])]
    cues = build_cues(segments, [], Glossary())
    assert [(c.start, c.end, c.zh) for c in cues] == [(0, 1, "First"), (1.1, 2, "Second")]


def test_overlapping_aligned_words_keep_full_intervals():
    words = [WordSpan(0, 9, "First"), WordSpan(8, 12, "second")]
    cues = build_cues([aligned(words)], [], Glossary())
    assert [(c.start, c.end, c.zh) for c in cues] == [(0, 12, "First second")]
    assert cues[0].words == words


def test_media_clipping_keeps_full_phrase_before_long_cue_split():
    text = "保留整句台词并让后半段出现在视频结尾之前"
    cues = build_cues([Segment(0, 30, text)], [], Glossary(), media_duration=20)
    assert "".join(c.zh for c in cues) == text
    assert cues[-1].end == 20 and all(c.end - c.start <= 8 for c in cues)


def test_long_mixed_text_does_not_split_latin_words_or_combining_kana():
    text = "这是SubFlow字幕か\u3099完整测试内容"
    cues = build_cues([Segment(0, 40, text)], [], Glossary())
    combined = "".join(c.zh for c in cues).replace(" ", "")
    assert combined == text
    assert any("SubFlow" in c.zh for c in cues)
    assert any("か\u3099" in c.zh for c in cues)
    assert cues[-1].end == 40
