import json

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.config import AppSettings
from bilingual_sub.models import JobConfig, Segment, WordSpan


@pytest.mark.parametrize("kind", ["overshoot", "minimum_duration", "aligned", "late_segment", "preview"])
def test_pipeline_bounds_cues_and_resume_to_available_media(tmp_path, monkeypatch, kind):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    duration = 120 if kind == "preview" else 1.685
    limit = 60 if kind == "preview" else duration
    segment = Segment(limit - .4, limit + .5, "保留这句话")
    if kind == "minimum_duration":
        segment = Segment(limit - .4, limit - .2, "保留这句话")
    elif kind == "aligned":
        segment = Segment(limit - .4, limit + .5, "保留这句话。", words=(
            WordSpan(limit - .4, limit + .2, "保留这句话"), WordSpan(limit + .2, limit + .5, "。")))
    segments = [segment]
    if kind in {"late_segment", "preview"}:
        segments.append(Segment(limit + 1, limit + 2, "不应出现的越界识别"))
    calls = []
    def recognize(wav, **kwargs):
        calls.append(1)
        kwargs["out_json"].write_text(json.dumps({"language": "zh", "segments": [
            {"start": s.start, "end": s.end, "text": s.text} for s in segments]}, ensure_ascii=False), encoding="utf-8")
        return segments
    monkeypatch.setattr(p, "probe_video", lambda path: {"duration": duration, "has_audio": True, "width": 640, "height": 360})
    monkeypatch.setattr(p, "extract_wav", lambda src, dest, **kwargs: dest.write_bytes(b"audio fixture"))
    monkeypatch.setattr(p, "detect_silences", lambda *a, **k: [])
    monkeypatch.setattr(p, "transcribe", recognize)
    def forbidden(*a, **k):
        pytest.fail("same-language timing correction must not translate or dub")
    monkeypatch.setattr(p, "translate_cues", forbidden)
    monkeypatch.setattr(p, "dub_cues", forbidden)
    cfg = JobConfig(source, None, tmp_path / "result.srt", tmp_path / "work", burn=False,
                    source_lang="zh", target_lang="zh", subtitle_mode="single:zh",
                    preview_minutes=1 if kind == "preview" else None)
    result = p.run(cfg, AppSettings())
    for filename in ("cues.source.json", "cues.bilingual.json", "cues.fitted.json"):
        cues = p.load_cues_json(cfg.work_dir / filename)
        assert cues and all(0 <= c.start < c.end <= limit for c in cues)
        assert all(0 <= w.start <= w.end <= limit for c in cues for w in c.words)
    text = result.output_srt.read_text(encoding="utf-8")
    assert "保留这句话" in text and "不应出现" not in text
    cfg.resume_from = "done"
    cfg.output_srt = tmp_path / "resumed.srt"
    resumed = p.run(cfg, AppSettings())
    assert resumed.output_srt.read_text(encoding="utf-8") == text and len(calls) == 1
