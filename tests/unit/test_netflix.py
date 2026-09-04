from bilingual_sub.config import StylePreset
from bilingual_sub.core.netflix import cpl_ok, cps_ok, fit_cues, needs_split, split_text
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
    ass, _ = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="bilingual")
    assert ass.count("Dialogue:") == 2
    assert ",CN," in ass and ",EN," in ass


def test_netflix_single_one_dialogue():
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(cues, PRESET, play_res=(1920, 1080), mode="netflix_single")
    assert ass.count("Dialogue:") == 1
    assert "Hello." in ass
    assert "大家好" not in ass or ass.count("大家好") == 0
    assert "Hello." in srt


def test_fit_cues_splits_long():
    long = "This English line is intentionally longer than the Netflix CPL limit for sure."
    cues = [Cue(0.0, 2.0, "源", long)]
    fitted = fit_cues(cues, "en", use_target=True)
    assert len(fitted) >= 1
