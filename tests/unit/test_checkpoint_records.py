import json

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.persistence import write_json
from bilingual_sub.core.render import load_cues_json, save_cues_json
from bilingual_sub.models import Cue, JobConfig, Segment, WordSpan


@pytest.mark.parametrize("data", [{}, None, [None], [{"start": 0, "end": 1, "source": ["bad"]}],
    [{"start": 0, "end": 1, "zh": "ok", "target": {"bad": 1}}],
    [{"start": 0, "end": float("nan"), "zh": "bad"}],
    [{"start": -1, "end": 1, "zh": "bad"}],
    [{"start": 1, "end": 1, "zh": "bad"}],
    [{"start": 0, "end": 1, "zh": "bad", "words": [None]}]])
def test_malformed_cue_cache_is_not_a_successful_empty_result(tmp_path, data):
    path = tmp_path / "cues.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_cues_json(path)


def test_failed_record_commit_keeps_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "job_state.json"
    write_json(path, {"stage": "transcribe"})
    before = path.read_bytes()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(type(path), "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        write_json(path, {"stage": "done"})
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".subflow-json-*"))


def test_invalid_generated_cue_does_not_replace_previous_cache(tmp_path):
    path = tmp_path / "cues.json"
    save_cues_json([Cue(0, 1, "previous")], path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_cues_json([Cue(0, float("inf"), "invalid")], path)
    assert path.read_bytes() == before


def test_stopped_state_retains_last_completed_stage(tmp_path):
    p._save_state(tmp_path, "transcribe", {"job_id": "current"})
    p._save_state(tmp_path, "stopped", {"job_id": "current", "stopped": True})
    data = json.loads((tmp_path / "job_state.json").read_text())
    assert data["stage"] == "stopped" and data["completed_stage"] == "transcribe"


@pytest.mark.parametrize("data", [{}, [None], [[0]], [[0, float("nan")]], [[-1, 1]], [[2, 1]]])
def test_invalid_silence_cache_is_rejected(tmp_path, data):
    path = tmp_path / "silences.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="静音缓存"):
        p._load_silences(path)


def test_very_short_word_cue_remains_serializable(tmp_path):
    cues = build_cues([Segment(0, 1, "字。", (WordSpan(0.001, 0.004, "字。"),))], [], Glossary())
    assert cues[0].end > cues[0].start
    save_cues_json(cues, tmp_path / "cues.json")
    assert load_cues_json(tmp_path / "cues.json")[0].zh == "字。"


def test_unknown_resume_stage_is_rejected_before_creating_work(tmp_path):
    cfg = JobConfig(tmp_path / "video.mp4", None, tmp_path / "out.srt", tmp_path / "work",
                    resume_from="transcirbe")
    with pytest.raises(ValueError, match="未知恢复阶段"):
        p.run(cfg)
    assert not cfg.work_dir.exists()
