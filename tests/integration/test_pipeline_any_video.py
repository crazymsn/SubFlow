"""End-to-end pipeline on a generated clip (no live Whisper / meding)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bilingual_sub.adapters.ffmpeg import FfmpegError, find_ffmpeg, probe_video, run_cmd
from bilingual_sub.core.translate import TranslateStats
from bilingual_sub.models import Cue, JobConfig, Segment
from bilingual_sub.pipeline import run


def _make_clip(path: Path, *, width: int = 1280, height: int = 720, seconds: float = 2.0) -> None:
    try:
        ffmpeg = find_ffmpeg()
    except FfmpegError:
        pytest.skip("ffmpeg not in PATH")
    run_cmd(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=30",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-t",
            str(seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )


@pytest.fixture
def clip(tmp_path: Path) -> Path:
    dest = tmp_path / "测试视频.mp4"
    _make_clip(dest)
    return dest


def test_chinese_path_probe(clip: Path):
    meta = probe_video(clip)
    assert meta["width"] == 1280
    assert meta["height"] == 720
    assert 1.5 <= float(meta["duration"]) <= 2.5
    assert meta["has_audio"] is True


def test_full_pipeline_with_mocks(clip: Path, tmp_path: Path, monkeypatch):
    work = tmp_path / "work"
    out_mp4 = tmp_path / "out.mp4"
    out_srt = tmp_path / "out.bilingual.srt"

    def fake_transcribe(wav, **kwargs):
        segs = [Segment(0.2, 1.6, "大家好,第一个叫prefuel")]
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text(
                json.dumps(
                    {
                        "language": "zh",
                        "segments": [s.__dict__ for s in segs],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return segs

    def fake_translate(cues, **kwargs):
        out = [Cue(c.start, c.end, c.zh, "Hello, the first is Prefill.") for c in cues]
        return out, TranslateStats(api_calls=1), []

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", fake_translate)

    cfg = JobConfig(
        input_video=clip,
        output_video=out_mp4,
        output_srt=out_srt,
        work_dir=work,
        burn=True,
        whisper_model="tiny",
        device="cpu",
    )
    result = run(cfg)
    assert result.cue_count >= 1
    assert result.output_mp4 and result.output_mp4.is_file()
    assert out_srt.is_file()
    text = out_srt.read_text(encoding="utf-8")
    assert "Prefill" in text or "prefuel" in text.lower() or "大家好" in text
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["missing_en_count"] == 0
    assert "api_key" not in json.dumps(report).lower()
    source = work / "source.mp4"
    assert source.is_file()


def test_resume_from_translate(clip: Path, tmp_path: Path, monkeypatch):
    work = tmp_path / "work2"
    calls = {"transcribe": 0}

    def fake_transcribe(wav, **kwargs):
        calls["transcribe"] += 1
        segs = [Segment(0.2, 1.6, "大家好")]
        if kwargs.get("out_json"):
            kwargs["out_json"].parent.mkdir(parents=True, exist_ok=True)
            kwargs["out_json"].write_text(
                json.dumps({"language": "zh", "segments": [segs[0].__dict__]}, ensure_ascii=False),
                encoding="utf-8",
            )
        return segs

    def fake_translate(cues, **kwargs):
        return [Cue(c.start, c.end, c.zh, "Hello.") for c in cues], TranslateStats(api_calls=1), []

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", fake_translate)

    cfg = JobConfig(
        input_video=clip,
        output_video=None,
        output_srt=tmp_path / "a.srt",
        work_dir=work,
        burn=False,
    )
    run(cfg)
    assert calls["transcribe"] == 1

    cfg2 = JobConfig(
        input_video=clip,
        output_video=None,
        output_srt=tmp_path / "b.srt",
        work_dir=work,
        burn=False,
        resume_from="translate",
    )
    run(cfg2)
    assert calls["transcribe"] == 1
