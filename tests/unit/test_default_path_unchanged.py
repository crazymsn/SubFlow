from pathlib import Path

from bilingual_sub.models import JobConfig, STAGES
from bilingual_sub.pipeline import artifact_key


def test_jobconfig_defaults_match_legacy_path():
    cfg = JobConfig(
        input_video=Path("a.mp4"),
        output_video=Path("b.mp4"),
        output_srt=Path("c.srt"),
        work_dir=Path("work"),
    )
    assert cfg.source_lang == "zh"
    assert cfg.target_lang == "en"
    assert cfg.subtitle_mode == "bilingual"
    assert cfg.asr_backend == "whisper"
    assert cfg.refine_translate is False
    assert cfg.enable_dub is False
    assert cfg.source_url is None
    assert cfg.glossary_generate is False
    assert cfg.tts_provider == "none"
    assert cfg.ui_locale == "zh-Hans"


def test_stages_keep_legacy_names():
    assert "translate" in STAGES
    assert "ingest" in STAGES
    assert STAGES.index("translate") < STAGES.index("render")
    assert STAGES.index("burn") < STAGES.index("dub")


def test_default_pipeline_skips_ytdlp_refine_dub(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    called = {"ytdlp": 0, "refine": 0, "dub": 0}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)
    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("1\n", encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)

    def fake_transcribe(wav, **kwargs):
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return [Segment(0.2, 1.6, "大家好")]

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []),
    )

    def boom_ytdlp(*a, **k):
        called["ytdlp"] += 1
        raise AssertionError("yt-dlp should not run")

    def boom_refine(*a, **k):
        called["refine"] += 1
        raise AssertionError("refine should not run")

    def boom_dub(*a, **k):
        called["dub"] += 1
        raise AssertionError("dub should not run")

    monkeypatch.setattr("bilingual_sub.pipeline.ytdlp_download", boom_ytdlp)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues_refined", boom_refine)
    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", boom_dub)

    cfg = JobConfig(
        input_video=video,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
    )
    result = run(cfg)
    assert result.cue_count >= 1
    assert called == {"ytdlp": 0, "refine": 0, "dub": 0}


def test_artifact_key_changes_with_language(tmp_path: Path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    base = dict(
        input_video=video,
        output_video=None,
        output_srt=tmp_path / "a.srt",
        work_dir=tmp_path / "w",
    )
    a = artifact_key(JobConfig(**base))
    b = artifact_key(JobConfig(**base, target_lang="ja"))
    c = artifact_key(JobConfig(**base, refine_translate=True))
    assert a != b
    assert a != c
