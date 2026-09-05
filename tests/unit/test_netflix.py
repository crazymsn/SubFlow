import pytest

from bilingual_sub.config import StylePreset
from bilingual_sub.core.langs import screen_line
from bilingual_sub.core.netflix import (
    cpl_ok,
    cps_ok,
    fit_cues,
    fit_warnings,
    needs_split,
    split_text,
)
from bilingual_sub.core.render import render_ass_srt
from bilingual_sub.models import Cue, WordSpan

PRESET = StylePreset(
    name="test",
    style={
        "zh": {"size": 80, "font": "Arial", "bold": True, "color": "#FFFFFF", "outline": 3},
        "en": {"size": 56, "font": "Arial", "color": "#F2F2F2", "outline": 2},
        "layout": {"cn_y": 100, "en_y": 200, "margin_lr": 10},
        "scale_to_fit_width": 2000,
    },
)


def test_long_english_needs_split():
    text = "This is a very long English subtitle that clearly exceeds forty two characters."
    assert not cpl_ok(text, "en")
    assert needs_split(text, 0.0, 2.0, "en")


def test_cps_ok_short():
    assert cps_ok("Hello", 2.0, "en")


def test_split_text_with_words():
    words = [
        WordSpan(0.0, 0.4, "Hello"),
        WordSpan(0.4, 0.8, "world"),
        WordSpan(0.8, 1.2, "again"),
        WordSpan(1.2, 1.6, "today"),
    ]
    parts = split_text("Hello world again today", 0.0, 1.6, "en", words)
    assert len(parts) >= 2


def test_bilingual_two_dialogues():
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="bilingual")
    assert ass.count("Dialogue:") == 2
    assert ",CN," in ass and ",EN," in ass
    assert srt.index("大家好") < srt.index("Hello.")


def test_bilingual_does_not_stack_two_english_lines():
    cues = [Cue(1.0, 3.0, "Hello everyone", "Hello")]
    ass, srt = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="bilingual")
    assert ass.count("Dialogue:") == 1
    assert "Hello everyone" in ass
    assert srt.count("Hello") == 1


def test_enzh_english_above_chinese():
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="enzh")
    assert ass.count("Dialogue:") == 2
    assert ",CN," in ass and ",EN," in ass
    en_at = ass.index(",EN,")
    cn_at = ass.index(",CN,")
    assert en_at < cn_at
    assert srt.index("Hello.") < srt.index("大家好")


def test_netflix_single_one_dialogue():
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(
        cues, PRESET, play_res=(1920, 1080), mode="netflix_single", target_lang="en", source_lang="zh"
    )
    assert ass.count("Dialogue:") == 1
    assert "Hello." in ass
    assert "大家好" not in ass or ass.count("大家好") == 0
    assert "Hello." in srt


def test_netflix_single_uses_target_lang_not_en_field():
    # English ASR parked in cue.en; Chinese translation in cue.zh.
    cues = [Cue(1.0, 3.0, "大家好", "Hello everyone")]
    ass, srt = render_ass_srt(
        cues, PRESET, play_res=(1920, 1080), mode="netflix_single", target_lang="zh", source_lang="en"
    )
    assert ass.count("Dialogue:") == 1
    assert "大家好" in ass
    assert "Hello everyone" not in ass
    assert "大家好" in srt
    assert "Hello" not in srt


def test_single_english_one_dialogue():
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="single:en")
    assert ass.count("Dialogue:") == 1
    assert "Hello." in ass
    assert "大家好" not in ass
    assert "Hello." in srt
    assert "大家好" not in srt


def test_single_zh_keeps_chinese_when_en_dub_exists():
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="single:zh")
    assert ass.count("Dialogue:") == 1
    assert "大家好" in ass
    assert "Hello." not in ass
    assert "大家好" in srt
    assert "Hello." not in srt


def test_fit_cues_splits_long():
    long = "This English line is intentionally longer than the Netflix CPL limit for sure."
    cues = [Cue(0.0, 2.0, "源", long)]
    fitted = fit_cues(cues, "en", use_target=True)
    assert len(fitted) > 1
    assert all(cpl_ok(c.zh, "en") for c in fitted)
    assert " ".join(c.zh for c in fitted) == long


def test_fit_cues_falls_back_to_source_when_target_empty():
    long = "这是一句超过七秒还没有目标译文的中文对白所以必须按源语拆开。"
    cues = [Cue(0.0, 8.0, long, None)]
    fitted = fit_cues(cues, "zh", use_target=True)
    assert all(part.zh for part in fitted)
    assert sum(part.end - part.start for part in fitted) > 0


def compact(text):
    return "".join(text.split())


@pytest.mark.parametrize(("source", "target", "lang"), [
    ("这是中文源语。", "This translated sentence must survive splitting even though the word times are Chinese.", "en"),
    ("English original.", "这是必须保留的完整中文译文，不能让英语识别词条替换掉任何文字。", "zh"),
    ("English original.", "這是必須保留的完整繁體中文譯文，不能讓英語識別詞條替換掉任何文字。", "zh-Hant"),
    ("这是中文源语。", "Dies ist eine lange deutsche Übersetzung, deren Wörter vollständig erhalten bleiben müssen.", "de"),
])
def test_translated_text_never_replaced_with_source_words(source, target, lang):
    cue = Cue(1, 6, source, target if lang == "en" else None,
              words=[WordSpan(1, 3, source[:4]), WordSpan(3, 6, source[4:])],
              spoken=target if lang == "de" else None)
    if lang.startswith("zh"):
        cue.zh, cue.en = target, source
    fitted = fit_cues([cue], lang)
    lines = [screen_line(c, "netflix_single", target_lang=lang) for c in fitted]
    assert len(lines) > 1
    assert compact("".join(lines)) == compact(target)
    assert all(cpl_ok(line, lang) for line in lines)
    ass, srt = render_ass_srt(fitted, PRESET, mode="netflix_single", target_lang=lang)
    assert source not in srt and source not in ass
    assert all(line in srt for line in lines)
    assert fitted[0].start == 1 and fitted[-1].end == 6
    assert all(a.end == b.start for a, b in zip(fitted, fitted[1:]))


@pytest.mark.parametrize(("text", "lang", "end"), [
    ("一二三四五六七八九十" * 32, "zh", 35),
    ("Long sentences need repeated splitting without losing words or clipping the end. " * 12, "en", 90),
    ("x" * 320, "en", 40),
    ("Hello world", "en", 20),
])
def test_recursive_fit_preserves_all_text_and_interval(text, lang, end):
    fitted = fit_cues([Cue(0, end, text)], lang)
    assert compact("".join(c.zh for c in fitted)) == compact(text)
    assert fitted[0].start == 0 and fitted[-1].end == end
    assert all(c.start < c.end and cpl_ok(c.zh, lang) for c in fitted)
    assert all(a.end == b.start for a, b in zip(fitted, fitted[1:]))
    # Sparse speech may exceed the duration limit; retain its interval and report it.
    if text == "Hello world":
        assert all("maximum_duration" in w["issues"] for w in fit_warnings(fitted, lang))
    else:
        assert all(c.end - c.start <= 7 for c in fitted)


@pytest.mark.parametrize("duration", [0.001, 0.01, 0.02, 0.2, 0.83])
def test_short_intervals_never_extend_or_collapse(duration):
    text = "长字幕不能为了满足最短显示时间而覆盖后面的字幕内容。" * 3
    following = Cue(duration, 1, "下一句")
    fitted = fit_cues([Cue(0, duration, text), following], "zh")
    assert compact("".join(c.zh for c in fitted)) == text + "下一句"
    assert fitted[0].start == 0 and fitted[-1].end == 1
    assert all(c.start < c.end for c in fitted)
    assert all(a.end == b.start for a, b in zip(fitted, fitted[1:]))
    assert "minimum_duration" in fit_warnings(fitted, "zh")[0]["issues"]


def test_reading_speed_cannot_be_fixed_by_splitting():
    cues = [Cue(1, 2, "This is spoken far too quickly.")]
    fitted = fit_cues(cues, "en")
    assert len(fitted) == 1
    assert fitted[0].start == 1 and fitted[0].end == 2
    assert fit_warnings(fitted, "en") == [{"cue": 1, "issues": ["characters_per_second"]}]


def test_matching_word_times_are_used_without_adding_chinese_spaces():
    text = "这是第一句中文这是第二句中文"
    words = [WordSpan(1, 2, text[:7]), WordSpan(4, 5, text[7:])]
    parts = split_text(text, 0, 6, "zh", words)
    assert len(parts) == 2
    assert parts[0].end == parts[1].start == 3
    assert "".join(c.zh for c in parts) == text
    assert parts[0].start == 0 and parts[-1].end == 6


@pytest.mark.parametrize("words", [
    [WordSpan(-1, 2, "Hello"), WordSpan(2, 4, "world")],
    [WordSpan(0, 3, "Hello"), WordSpan(2, 4, "world")],
    [WordSpan(0, 2, "Hello"), WordSpan(2, float("nan"), "world")],
    [WordSpan(0, 1, "Hello"), WordSpan(1, 2, "missing")],
])
def test_invalid_or_incomplete_alignment_uses_text_and_original_interval(words):
    parts = split_text("Hello world", 0, 4, "en", words)
    assert [p.zh for p in parts] == ["Hello", "world"]
    assert parts[0].end == 2 and parts[-1].end == 4


def test_source_selection_and_spoken_duplicate_cannot_repeat_full_sentence():
    text = "This is the complete source sentence and it is longer than the allowed line length."
    cue = Cue(0, 5, text, "不应显示的其他译文", spoken=text)
    fitted = fit_cues([cue], "en", use_target=False)
    _, srt = render_ass_srt(fitted, PRESET, mode="netflix_single", target_lang="en")
    assert compact("".join(c.zh for c in fitted)) == compact(text)
    assert text not in srt
    assert "不应显示" not in srt


def test_split_does_not_separate_combining_marks_or_joined_emoji():
    atom = "e\u0301👩\u200d💻"
    fitted = fit_cues([Cue(0, 7, atom * 30)], "en")
    assert "".join(c.zh for c in fitted) == atom * 30
    assert all(not c.zh.startswith(("\u0301", "\u200d", "💻")) for c in fitted)
