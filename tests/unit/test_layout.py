from bilingual_sub.config import load_style_preset
from bilingual_sub.core.render import apply_subtitle_colors, normalize_hex, render_ass_srt, resolve_play_layout
from bilingual_sub.models import Cue


def test_layout_scales_to_1080p():
    preset = load_style_preset("no-plate-large")
    geo = resolve_play_layout(preset.style, (1920, 1080))
    assert geo["ph"] == 1080
    assert geo["en_y"] < 1080
    assert geo["cn_y"] < geo["en_y"]
    assert geo["zh"]["size"] < 80
    assert geo["zh"]["size"] >= 18


def test_layout_keeps_canonical_2560x1600():
    preset = load_style_preset("no-plate-large")
    geo = resolve_play_layout(preset.style, (2560, 1600))
    assert geo["cn_y"] == 1376
    assert geo["en_y"] == 1472
    assert geo["zh"]["size"] == 80
    assert geo["en"]["size"] == 56


def test_ass_positions_on_screen_for_vertical():
    preset = load_style_preset("no-plate-large")
    cues = [Cue(1.0, 2.0, "测试字幕", "Test")]
    ass, _ = render_ass_srt(cues, preset, play_res=(1080, 1920))
    assert "PlayResY: 1920" in ass
    assert "\\pos(540," in ass


def test_custom_subtitle_colors_land_in_ass():
    assert normalize_hex("ff0033") == "#FF0033"
    preset = apply_subtitle_colors(load_style_preset("no-plate-large"), "#FF0033", "#00FFAA")
    cues = [Cue(1.0, 2.0, "红字", "green")]
    ass, _ = render_ass_srt(cues, preset, play_res=(1920, 1080))
    assert "&H003300FF" in ass
    assert "&H00AAFF00" in ass
