from __future__ import annotations

import json
from pathlib import Path

import pytest

from bilingual_sub.config import AppSettings
from bilingual_sub.models import JobConfig
from bilingual_sub.pipeline import artifact_key, run, video_fingerprint


def _plant_job(work: Path, video: Path, prev_mp4: Path, *, whisper: str, translate: str) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "cues.bilingual.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "zh": "你好", "en": "Hello"}], ensure_ascii=False),
        encoding="utf-8",
    )
    (work / "subs.ass").write_text("[Script Info]\n", encoding="utf-8")
    (work / "job_state.json").write_text(
        json.dumps({"stage": "done", "job_id": "reuse1"}),
        encoding="utf-8",
    )
    prev_mp4.write_bytes(b"burned-mp4")
    (work / "report.json").write_text(
        json.dumps(
            {
                "job_id": "reuse1",
                "duration_sec": 1.2,
                "play_res": [1280, 720],
                "output_mp4": str(prev_mp4),
                "missing_en_count": 0,
                "missing_en_samples": [],
                "translate_cache_hits": 3,
                "translate_api_calls": 1,
                "input_fingerprint": video_fingerprint(video),
                "whisper_model": whisper,
                "translate_model": translate,
                "style_preset": "no-plate-large",
                "subtitle_pack": "han-layout-v3",
                "source_lang": "zh",
                "target_lang": "zh",
                "subtitle_mode": "bilingual",
                "translated": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "lecture.mp4"
    path.write_bytes(b"fake-video")
    return path


def test_same_video_new_path_copies_without_pipeline(tmp_path: Path, video: Path, monkeypatch):
    monkeypatch.setattr("bilingual_sub.pipeline.tempfile.gettempdir", lambda: str(tmp_path))

    def boom(*_args, **_kwargs):
        raise AssertionError("full pipeline should not run")

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", boom)
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", boom)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", boom)
    monkeypatch.setattr("bilingual_sub.pipeline.burn_subtitles", boom)

    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "old" / "out.mp4",
        output_srt=tmp_path / "old" / "out.bilingual.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
    )
    work = tmp_path / "bilingual-sub" / artifact_key(cfg)
    prev = tmp_path / "old" / "out.mp4"
    prev.parent.mkdir(parents=True)
    _plant_job(work, video, prev, whisper=cfg.whisper_model, translate=cfg.translate_model)

    dest = tmp_path / "exports" / "final.mp4"
    srt = tmp_path / "exports" / "final.bilingual.srt"
    cfg2 = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=srt,
        work_dir=Path("auto"),
        whisper_model=cfg.whisper_model,
        translate_model=cfg.translate_model,
        burn=True,
    )
    result = run(cfg2, settings=AppSettings())
    assert result.reused is True
    assert dest.is_file()
    assert dest.read_bytes() == b"burned-mp4"
    assert srt.is_file()
    assert "你好" in srt.read_text(encoding="utf-8")
    assert "transcribe_sec" not in result.stages
    assert "export_sec" in result.stages


def test_different_video_or_model_skips_reuse(tmp_path: Path, video: Path):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "a.mp4",
        output_srt=tmp_path / "a.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
    )
    work = tmp_path / "work"
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model)
    assert _can_reexport(cfg, work) is True

    other = tmp_path / "other.mp4"
    other.write_bytes(b"other-video")
    other_cfg = JobConfig(
        input_video=other,
        output_video=tmp_path / "b.mp4",
        output_srt=tmp_path / "b.srt",
        work_dir=Path("auto"),
        whisper_model=cfg.whisper_model,
        translate_model=cfg.translate_model,
        burn=True,
    )
    assert _can_reexport(other_cfg, work) is False

    model_cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "c.mp4",
        output_srt=tmp_path / "c.srt",
        work_dir=Path("auto"),
        whisper_model="large",
        translate_model=cfg.translate_model,
        burn=True,
    )
    assert _can_reexport(model_cfg, work) is False

    lang_cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "d.mp4",
        output_srt=tmp_path / "d.srt",
        work_dir=Path("auto"),
        whisper_model=cfg.whisper_model,
        translate_model=cfg.translate_model,
        burn=True,
        target_lang="ja",
    )
    assert _can_reexport(lang_cfg, work) is False


def test_stale_english_cues_block_single_chinese_reuse(tmp_path: Path, video: Path):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "a.mp4",
        output_srt=tmp_path / "a.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
        target_lang="zh",
        subtitle_mode="single:zh",
    )
    work = tmp_path / "stale"
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model)
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["subtitle_mode"] = "single:zh"
    report["translated"] = False
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (work / "cues.bilingual.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "zh": "你好", "en": "Hello"}], ensure_ascii=False),
        encoding="utf-8",
    )
    assert _can_reexport(cfg, work) is False


def test_english_in_chinese_field_blocks_bilingual_reuse(tmp_path: Path, video: Path):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "a.mp4",
        output_srt=tmp_path / "a.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
        target_lang="zh",
        subtitle_mode="bilingual",
    )
    work = tmp_path / "polluted"
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model)
    (work / "cues.bilingual.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "zh": "Hello everyone", "en": "Hello everyone"}], ensure_ascii=False),
        encoding="utf-8",
    )
    assert _can_reexport(cfg, work) is False


def test_english_target_without_dubbed_file_blocks_reuse(tmp_path: Path, video: Path):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "a.mp4",
        output_srt=tmp_path / "a.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
        source_lang="zh",
        target_lang="en",
        subtitle_mode="bilingual",
    )
    work = tmp_path / "undubbed"
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model)
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["target_lang"] = "en"
    report["detected_spoken"] = "zh"
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert _can_reexport(cfg, work) is False
    (work / "dubbed.mp4").write_bytes(b"en-dub")
    assert _can_reexport(cfg, work) is True
