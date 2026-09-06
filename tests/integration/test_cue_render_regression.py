"""Cue and rendering regressions using small synthetic inputs."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from bilingual_sub.adapters.ffmpeg import probe_video
from bilingual_sub.config import default_glossary_path, load_style_preset
from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.render import render_ass_srt
from bilingual_sub.models import Segment


@pytest.fixture
def sample_segments():
    return [Segment(0, 6, "第一步是prefuel，第二步是decode，第三步是KVcatch"),
            Segment(7, 9, "另一条独立字幕。")]


@pytest.fixture
def sample_silences():
    return [(1.8, 2.4), (3.8, 4.4)]


@pytest.fixture
def glossary() -> Glossary:
    return Glossary.load(default_glossary_path())


def test_optional_source_duration():
    video = Path(os.environ.get("BILINGUAL_SUB_VIDEO", ""))
    if not video.is_file():
        pytest.skip("set BILINGUAL_SUB_VIDEO to run duration probe")
    meta = probe_video(video)
    duration = float(meta["duration"])
    assert duration > 1
    assert meta["width"] > 0 and meta["height"] > 0
    assert meta["has_audio"] is True


def test_cue_boundaries_regression(sample_segments, sample_silences, glossary):
    cues = build_cues(sample_segments, sample_silences, glossary)
    assert [(c.start, c.end) for c in cues] == [(0, 1.8), (2.4, 3.8), (4.4, 6), (7, 9)]


def test_prefill_decode_kv_split(sample_segments, sample_silences, glossary):
    cues = build_cues(sample_segments, sample_silences, glossary)
    prefill_cues = [c for c in cues if re.search(r"Prefill|prefuel", c.zh, re.I) and c.start < 15]
    decode_cues = [c for c in cues if re.search(r"Decode|decode", c.zh) and c.start < 15]
    kv_cues = [c for c in cues if re.search(r"KV\s*cache|KVcatch", c.zh, re.I) and c.start < 15]
    assert len(prefill_cues) >= 1
    assert len(decode_cues) >= 1
    assert len(kv_cues) >= 1
    assert prefill_cues[0].zh != decode_cues[0].zh


def test_ass_no_plate_border_style(sample_segments, sample_silences, glossary):
    cues = build_cues(sample_segments, sample_silences, glossary)
    preset = load_style_preset("no-plate-large")
    ass, _ = render_ass_srt(cues[:5], preset, play_res=(2560, 1600))
    cn_line = next(line for line in ass.splitlines() if line.startswith("Style: CN,"))
    fields = cn_line.split(",")
    assert fields[15] == "1"
    assert "\\bord" in ass
    assert "Dialogue:" in ass
    assert "PlayResX: 2560" in ass
