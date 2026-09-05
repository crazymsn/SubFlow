import re

from bilingual_sub.config import load_style_preset
from bilingual_sub.core.render import (
    est_width,
    fit_scale,
    fit_text,
    line_box_width,
    render_ass_srt,
    resolve_play_layout,
    scale_tag,
    wrap_to_width,
)
from bilingual_sub.models import Cue

LONG_ZH = "这是一句非常非常非常非常非常非常非常非常非常非常非常非常长的中文字幕用来检查会不会画出画面"
LONG_EN = (
    "This is an extremely long English subtitle that would previously stretch "
    "straight off both sides of the video frame without wrapping."
)


def _dialogue_payloads(ass: str) -> list[str]:
    payloads = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        start = line.find("{")
        assert start >= 0
        payloads.append(line[start:])
    return payloads


def _painted_width(payload: str, fs: int, *, bold: bool, spacing: float, outline: float) -> float:
    match = re.search(r"\{(?P<tag>[^}]*)\}(?P<body>.*)$", payload)
    assert match is not None
    tag, body = match.group("tag"), match.group("body")
    scale = 100
    found = re.search(r"\\fscx(\d+)", tag)
    if found:
        scale = int(found.group(1))
    widest = 0.0
    for line in body.split(r"\N"):
        widest = max(widest, line_box_width(line, fs, bold=bold, spacing=spacing, outline=outline))
    return widest * scale / 100.0


def test_est_width_counts_spacing_and_wide_glyphs():
    assert est_width("你好", 80) > 150
    spaced = est_width("你好", 80, spacing=2.0)
    assert spaced > est_width("你好", 80)


def test_wrap_long_cjk_and_english():
    zh_lines = wrap_to_width(LONG_ZH, 80, 900, bold=True, outline=3.2)
    assert 2 <= len(zh_lines) <= 4
    assert all(est_width(line, 80, bold=True) <= 980 for line in zh_lines[:-1])
    en_lines = wrap_to_width(LONG_EN, 56, 900, outline=2.6)
    assert len(en_lines) >= 2
    assert all(" " not in line or line.count(" ") >= 0 for line in en_lines)


def test_scale_has_no_eighty_two_floor():
    lines = ["W" * 80]
    pct = fit_scale(lines, 80, 400)
    assert pct < 82
    tag = scale_tag("字" * 60, 80, 400)
    assert "fscx" in tag and "fscy" in tag
    assert int(re.search(r"\\fscx(\d+)", tag).group(1)) < 82


def test_unbreakable_token_still_fits_by_scale():
    token = "Pneumonoultramicroscopicsilicovolcanoconiosis"
    lines, pct = fit_text(token, 56, 220)
    assert "".join(lines) == token
    painted = max(line_box_width(line, 56) for line in lines) * pct / 100.0
    assert painted <= 220 + 0.5


def test_bilingual_simplified_target_converts_traditional():
    preset = load_style_preset("no-plate-large")
    cues = [Cue(0.0, 2.0, "歡迎回來", "Welcome back")]
    ass, srt = render_ass_srt(cues, preset, play_res=(1920, 1080), mode="bilingual", han_lang="zh")
    assert "欢迎回来" in ass
    assert "欢迎回来" in srt
    assert "歡迎回來" not in ass
    assert "Welcome back" in ass


def test_pair_keeps_one_line_per_language():
    preset = load_style_preset("no-plate-large")
    zh = "今天给大家分享网页爬虫和网页分析智能体的实际效能表现"
    en = "Today I will show you the web crawler and the web analysis agent performance"
    play = (3456, 2160)
    geo = resolve_play_layout(preset.style, play)
    ass, srt = render_ass_srt([Cue(0.0, 2.0, zh, en)], preset, play_res=play, mode="bilingual")
    payloads = _dialogue_payloads(ass)
    assert ass.count("Dialogue:") == 2
    for payload in payloads:
        assert r"\N" not in payload
        is_zh = "\\b1" in payload
        fs = geo["zh"]["size"] if is_zh else geo["en"]["size"]
        painted = _painted_width(
            payload,
            fs,
            bold=is_zh,
            spacing=float((geo["zh"] if is_zh else geo["en"])["spacing"]),
            outline=float((geo["zh"] if is_zh else geo["en"])["outline"]),
        )
        assert painted <= geo["max_w"] + 1.0
    assert srt.count("\n") >= 3


def test_pair_stack_keeps_safe_gap():
    play = (3456, 2160)
    preset = load_style_preset("no-plate-large")
    cues = [Cue(0.0, 2.0, "大家好", "Hello everyone")]
    ass, _ = render_ass_srt(cues, preset, play_res=play, mode="bilingual")
    ys = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        found = re.search(r"\\pos\((\d+),(\d+)\)", line)
        assert found is not None
        ys.append((int(found.group(1)), int(found.group(2)), ",CN," in line))
    cn = [y for _, y, is_cn in ys if is_cn]
    en = [y for _, y, is_cn in ys if not is_cn]
    assert cn and en
    assert max(cn) < min(en)
    assert min(en) <= play[1] - int(play[1] * 0.06)
    assert min(en) - max(cn) >= 20


def test_canonical_2560_layout_unchanged():
    preset = load_style_preset("no-plate-large")
    geo = resolve_play_layout(preset.style, (2560, 1600))
    assert geo["cn_y"] == 1376
    assert geo["en_y"] == 1472
    assert geo["zh"]["size"] == 80
    assert geo["en"]["size"] == 56
    assert geo["max_w"] <= 2560 - 2 * geo["margin_lr"]


def test_portrait_type_follows_width():
    preset = load_style_preset("no-plate-large")
    geo = resolve_play_layout(preset.style, (1080, 1920))
    assert geo["zh"]["size"] <= 40
    assert geo["max_w"] <= 1080 - 2 * geo["margin_lr"]


def test_long_cues_stay_inside_every_common_frame():
    preset = load_style_preset("no-plate-large")
    cues = [Cue(0.0, 2.0, LONG_ZH, LONG_EN)]
    frames = [(2560, 1600), (1920, 1080), (1280, 720), (1080, 1920), (720, 1280), (640, 360)]
    for play in frames:
        geo = resolve_play_layout(preset.style, play)
        ass, srt = render_ass_srt(cues, preset, play_res=play)
        assert r"\N" in ass or "\\fscx" in ass
        assert "\n" in srt.split("-->", 1)[1]
        for payload in _dialogue_payloads(ass):
            is_zh = "\\b1" in payload
            fs = geo["zh"]["size"] if is_zh else geo["en"]["size"]
            painted = _painted_width(
                payload,
                fs,
                bold=is_zh,
                spacing=float((geo["zh"] if is_zh else geo["en"])["spacing"]),
                outline=float((geo["zh"] if is_zh else geo["en"])["outline"]),
            )
            assert painted <= geo["max_w"] + 1.0, (play, painted, geo["max_w"], payload)
        if play == (1080, 1920):
            assert "\\pos(540," in ass
