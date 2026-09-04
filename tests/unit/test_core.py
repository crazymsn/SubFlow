from bilingual_sub.config import StylePreset
from bilingual_sub.core.cues import build_cues, clauses, snap, split_by_punct
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.render import ass_esc, render_ass_srt
from bilingual_sub.models import Cue, Segment


def test_clauses_keeps_number_comma():
    parts = clauses("竟然要 86,749 元")
    assert len(parts) == 1
    assert "86,749" in parts[0]


def test_split_by_punct_single():
    out = split_by_punct(0.0, 2.0, "第一个叫 Prefill")
    assert len(out) == 1
    assert out[0][2] == "第一个叫 Prefill"


def test_snap_extends_short():
    t0, t1 = snap(1.0, 1.5, [], min_duration=0.9)
    assert t1 - t0 >= 0.89


def test_snap_to_silence_end():
    t0, t1 = snap(1.10, 3.0, [(0.0, 1.119)], tolerance=0.22)
    assert t0 >= 1.119


def test_glossary_correct():
    g = Glossary(replacements=[("prefuel", "Prefill")], regex_rules=[], punctuation={})
    assert g.correct("prefuel test") == "Prefill test"


def test_ass_esc():
    assert ass_esc("a\\b{c}") == r"a\\b\{c\}"


def test_render_ass_contains_dialogue():
    preset = StylePreset(
        name="test",
        style={
            "zh": {"size": 80, "font": "Arial", "bold": True, "color": "#FFFFFF", "outline": 3},
            "en": {"size": 56, "font": "Arial", "color": "#F2F2F2", "outline": 2},
            "layout": {"cn_y": 100, "en_y": 200, "margin_lr": 10},
            "scale_to_fit_width": 2000,
        },
    )
    cues = [Cue(1.0, 3.0, "大家好", "Hello.")]
    ass, srt = render_ass_srt(cues, preset, play_res=(1920, 1080))
    assert "Dialogue:" in ass
    assert "大家好" in ass
    assert "Hello." in srt


def test_build_cues_basic():
    g = Glossary()
    segs = [Segment(1.0, 3.0, "第一个叫Prefill")]
    cues = build_cues(segs, [], g)
    assert len(cues) >= 1
    assert "Prefill" in cues[0].zh or "prefill" in cues[0].zh.lower()
