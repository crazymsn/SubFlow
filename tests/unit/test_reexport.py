from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bilingual_sub.config import AppSettings
from bilingual_sub.core.cache_records import FILES
from bilingual_sub.core.file_io import file_digest
from bilingual_sub.core.job_profile import processing_profile, render_profile
from bilingual_sub.models import JobConfig
from bilingual_sub.pipeline import artifact_key, run, video_fingerprint


def _record_artifacts(work: Path, *stages: str) -> None:
    state = json.loads((work / "job_state.json").read_text(encoding="utf-8"))
    state["artifact_schema"] = 1
    records = state.setdefault("artifacts", {})
    for stage in stages:
        records[stage] = {name: file_digest(work / name) for name in FILES[stage]}
    (work / "job_state.json").write_text(json.dumps(state), encoding="utf-8")


def _plant_job(work: Path, video: Path, prev_mp4: Path, *, whisper: str, translate: str, cfg: JobConfig) -> None:
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
    for name in FILES["build_cues"]:
        (work / name).write_text(
            json.dumps([{"start": 0.0, "end": 1.0, "zh": "你好", "en": None}], ensure_ascii=False),
            encoding="utf-8",
        )
    _record_artifacts(work, "build_cues", "translate", "render")
    prev_mp4.write_bytes(b"burned-mp4")
    (work / "report.json").write_text(
        json.dumps(
            {
                "job_id": "reuse1",
                "tts_model_revision": "a" * 32,
                "duration_sec": 1.2,
                "play_res": [1280, 720],
                "output_mp4": str(prev_mp4),
                "output_video_sha256": file_digest(prev_mp4),
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
                "burn": True,
                "processing_profile": processing_profile(cfg, AppSettings()),
                "render_profile": render_profile(cfg, AppSettings()),
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
    _plant_job(work, video, prev, whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)

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
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
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

    noburn_cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "noburn.mp4",
        output_srt=tmp_path / "noburn.srt",
        work_dir=Path("auto"),
        whisper_model=cfg.whisper_model,
        translate_model=cfg.translate_model,
        burn=False,
    )
    assert _can_reexport(noburn_cfg, work) is False

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


def test_reexport_rechecks_the_bytes_copied_from_previous_movie(tmp_path, video, monkeypatch):
    from bilingual_sub import pipeline as p
    cfg = JobConfig(video, tmp_path / "new.mp4", tmp_path / "new.srt", Path("auto"), burn=True)
    previous, work = tmp_path / "previous.mp4", tmp_path / "work"
    _plant_job(work, video, previous, whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    report = json.loads((work / "report.json").read_text())
    cfg.output_video.write_bytes(b"old destination")
    original = p.copy_file
    def replace_after_validation(source, target, **kwargs):
        if source == previous:
            stamp = source.stat()
            source.write_bytes(b"x" * stamp.st_size)
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return original(source, target, **kwargs)
    monkeypatch.setattr(p, "copy_file", replace_after_validation)
    with pytest.raises(ValueError, match="内容"):
        p._copy_or_burn(cfg, work, AppSettings(), report)
    assert cfg.output_video.read_bytes() == b"old destination"


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
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["subtitle_mode"] = "single:zh"
    report["translated"] = False
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (work / "cues.bilingual.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "zh": "你好", "en": "Hello"}], ensure_ascii=False),
        encoding="utf-8",
    )
    assert _can_reexport(cfg, work) is False


@pytest.mark.parametrize("revision", ["a" * 32, "b" * 32, None])
def test_single_zh_with_en_dub_line_can_reexport(tmp_path: Path, video: Path, monkeypatch, revision):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "a.mp4",
        output_srt=tmp_path / "a.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
        target_lang="en",
        subtitle_mode="single:zh",
        enable_dub=True,
        tts_provider="gptsovits",
    )
    work = tmp_path / "dub-ok"
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    (work / "dubbed.mp4").write_bytes(b"dubbed")
    _record_artifacts(work, "dub")
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["subtitle_mode"] = "single:zh"
    report["target_lang"] = "en"
    report["translated"] = False
    report["tts_fingerprint"] = None
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: revision)
    assert _can_reexport(cfg, work) is (revision == "a" * 32)


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
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
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
    _plant_job(work, video, tmp_path / "a.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["target_lang"] = "en"
    report["detected_spoken"] = "zh"
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    assert _can_reexport(cfg, work) is False
    (work / "dubbed.mp4").write_bytes(b"en-dub")
    _record_artifacts(work, "dub")
    assert _can_reexport(cfg, work) is True
    cfg.subtitle_zh_color = "#00AAFF"
    assert _can_reexport(cfg, work) is False


def test_reexport_uses_fitted_cues_for_netflix(tmp_path: Path, video: Path, monkeypatch):
    monkeypatch.setattr("bilingual_sub.pipeline.tempfile.gettempdir", lambda: str(tmp_path))

    def boom(*_args, **_kwargs):
        raise AssertionError("full pipeline should not run")

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", boom)
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", boom)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", boom)
    seen: list[str] = []

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        seen.extend(c.zh for c in cues)
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("1\n", encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.burn_subtitles",
        lambda *a, **k: Path(k.get("output") or a[2]).write_bytes(b"burned"),
    )
    cfg = JobConfig(
        input_video=video,
        output_video=tmp_path / "nf.mp4",
        output_srt=tmp_path / "nf.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
        source_lang="zh",
        target_lang="zh",
        subtitle_mode="netflix_single",
    )
    work = tmp_path / "bilingual-sub" / artifact_key(cfg)
    prev = tmp_path / "old-nf.mp4"
    _plant_job(work, video, prev, whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["subtitle_mode"] = "netflix_single"
    report["translated"] = False
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (work / "cues.bilingual.json").write_text(
        json.dumps([{"start": 0.0, "end": 2.0, "zh": "这是一句很长很长需要拆开的中文对白", "en": None}], ensure_ascii=False),
        encoding="utf-8",
    )
    (work / "cues.fitted.json").write_text(
        json.dumps([{"start": 0.0, "end": 2.0, "zh": "拆开后的短句", "en": None}], ensure_ascii=False),
        encoding="utf-8",
    )
    _record_artifacts(work, "translate", "fit_subs")
    result = run(cfg)
    assert result.reused is True
    assert "拆开后的短句" in seen
    assert "很长很长" not in "".join(seen)


def test_url_job_reexport_matches_work_copy(tmp_path: Path, monkeypatch):
    from bilingual_sub.pipeline import _can_reexport

    work = tmp_path / "url-work"
    source = work / "source.mp4"
    prev = tmp_path / "old-url.mp4"
    cfg = JobConfig(
        input_video=Path("https://youtu.be/abc123XYZ"),
        source_url="https://youtu.be/abc123XYZ",
        output_video=tmp_path / "new-url.mp4",
        output_srt=tmp_path / "new-url.srt",
        work_dir=Path("auto"),
        whisper_model="medium",
        translate_model="gpt-4o-mini",
        burn=True,
    )
    _plant_job(work, source, prev, whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    source.write_bytes(b"downloaded-source")
    (work / "source.url.txt").write_text(cfg.source_url, encoding="utf-8")
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    report["input_fingerprint"] = {
        "path": str(source),
        "size": source.stat().st_size,
        "mtime_ns": source.stat().st_mtime_ns,
        "sha256": file_digest(source),
    }
    report["source_url"] = cfg.source_url
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("bilingual_sub.pipeline.tempfile.gettempdir", lambda: str(tmp_path))
    assert _can_reexport(cfg, work) is True


def test_no_burn_dub_reexport_reports_new_sidecar_on_every_relocation(tmp_path, video, monkeypatch):
    from bilingual_sub.gui.output_path import resolve_dub_sidecar

    monkeypatch.setattr("bilingual_sub.pipeline.tempfile.gettempdir", lambda: str(tmp_path))
    cfg = JobConfig(video, None, tmp_path / "new.srt", Path("auto"), burn=False,
                    source_lang="zh", target_lang="en", subtitle_mode="single:zh")
    work = tmp_path / "bilingual-sub" / artifact_key(cfg)
    _plant_job(work, video, tmp_path / "old.mp4", whisper=cfg.whisper_model, translate=cfg.translate_model, cfg=cfg)
    (work / "dubbed.mp4").write_bytes(b"dubbed video")
    _record_artifacts(work, "dub")
    report = json.loads((work / "report.json").read_text())
    report.update(burn=False, target_lang="en", subtitle_mode="single:zh", translated=False,
                  dubbed=True, detected_spoken="zh", output_dub=str(tmp_path / "old-dub.mp4"))
    (work / "report.json").write_text(json.dumps(report))
    for name in ("new.srt", "another.srt"):
        cfg.output_srt = tmp_path / name
        result = run(cfg, AppSettings())
        expected = resolve_dub_sidecar(None, cfg.output_srt)
        assert result.reused and result.output_mp4 is None
        assert result.output_dub == expected
        assert expected.read_bytes() == b"dubbed video"
        saved = json.loads(result.report_path.read_text(encoding="utf-8"))
        assert saved["output_dub"] == str(expected) and saved["output_mp4"] is None


def test_changed_processing_settings_invalidates_reexport_and_resume(tmp_path, video):
    from bilingual_sub.pipeline import _can_reexport, _resume_dir_matches

    cfg = JobConfig(video, tmp_path / "old.mp4", tmp_path / "out.srt", Path("auto"))
    work = tmp_path / "cache"
    _plant_job(work, video, cfg.output_video, whisper=cfg.whisper_model,
               translate=cfg.translate_model, cfg=cfg)
    settings = AppSettings()
    assert _can_reexport(cfg, work, settings)
    assert _resume_dir_matches(cfg, work, settings)
    settings.cues.max_duration = 2.0
    assert not _can_reexport(cfg, work, settings)
    assert not _resume_dir_matches(cfg, work, settings)


def test_old_truncated_translation_report_is_not_reused(tmp_path, video):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(video, tmp_path / 'old.mp4', tmp_path / 'out.srt', Path('auto'))
    work = tmp_path / 'cache'
    _plant_job(work, video, cfg.output_video, whisper=cfg.whisper_model,
               translate=cfg.translate_model, cfg=cfg)
    assert _can_reexport(cfg, work, AppSettings())
    path = work / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8'))
    report['processing_profile']['processing_revision'] = 'standard-voices-balanced-captions-v24'
    path.write_text(json.dumps(report), encoding='utf-8')
    assert not _can_reexport(cfg, work, AppSettings())


def test_changed_burn_quality_reencodes_without_recognition(tmp_path, video, monkeypatch):
    monkeypatch.setattr("bilingual_sub.pipeline.tempfile.gettempdir", lambda: str(tmp_path))
    cfg = JobConfig(video, tmp_path / "new.mp4", tmp_path / "new.srt", Path("auto"))
    work = tmp_path / "bilingual-sub" / artifact_key(cfg)
    _plant_job(work, video, tmp_path / "old.mp4", whisper=cfg.whisper_model,
               translate=cfg.translate_model, cfg=cfg)
    (work / "source.mp4").write_bytes(video.read_bytes())
    seen = []

    def burn(source, ass, output, **kwargs):
        seen.append(kwargs["cq"])
        output.write_bytes(b"new encoding")

    monkeypatch.setattr("bilingual_sub.pipeline.burn_subtitles", burn)
    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", lambda *a, **kw: pytest.fail("ASR should be reused"))
    settings = AppSettings()
    settings.burn.cq = 25
    result = run(cfg, settings)
    assert result.reused and seen == [25]
    assert cfg.output_video.read_bytes() == b"new encoding"
    # A second export under the same settings can copy the reencoded result.
    run(cfg, settings)
    assert seen == [25]


def test_changed_style_file_content_reencodes_same_named_preset(tmp_path, video, monkeypatch):
    import shutil

    from bilingual_sub.config import _bundled_config_dir

    preset_root = tmp_path / "config"
    shutil.copytree(_bundled_config_dir() / "presets", preset_root / "presets")
    monkeypatch.setattr("bilingual_sub.config._bundled_config_dir", lambda: preset_root)
    monkeypatch.setattr("bilingual_sub.pipeline.tempfile.gettempdir", lambda: str(tmp_path))
    cfg = JobConfig(video, tmp_path / "new.mp4", tmp_path / "new.srt", Path("auto"))
    work = tmp_path / "bilingual-sub" / artifact_key(cfg)
    _plant_job(work, video, tmp_path / "old.mp4", whisper=cfg.whisper_model,
               translate=cfg.translate_model, cfg=cfg)
    (work / "source.mp4").write_bytes(video.read_bytes())
    path = preset_root / "presets" / f"{cfg.style_preset}.yaml"
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["style"]["layout"]["margin_lr"] = 220
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    burns = []

    def burn(source, ass, output, **kwargs):
        burns.append(ass.read_text(encoding="utf-8"))
        output.write_bytes(b"new style")

    monkeypatch.setattr("bilingual_sub.pipeline.burn_subtitles", burn)
    result = run(cfg, AppSettings())
    assert result.reused and len(burns) == 1
    assert cfg.output_video.read_bytes() == b"new style"


@pytest.mark.parametrize("key,value", [("job_id", "old-attempt"), ("cue_count", 0),
    ("play_res", []), ("duration_sec", float("nan")), ("translate_api_calls", "broken"),
    ("missing_en_samples", {}), ("burn", "false")])
def test_invalid_cached_report_cannot_be_reexported(tmp_path, video, key, value):
    from bilingual_sub.pipeline import _can_reexport

    cfg = JobConfig(video, tmp_path / "out.mp4", tmp_path / "out.srt", Path("auto"))
    work = tmp_path / "cache"
    _plant_job(work, video, cfg.output_video, whisper=cfg.whisper_model,
               translate=cfg.translate_model, cfg=cfg)
    assert _can_reexport(cfg, work, AppSettings())
    report = work / "report.json"
    data = json.loads(report.read_text())
    data[key] = value
    report.write_text(json.dumps(data))
    assert not _can_reexport(cfg, work, AppSettings())
