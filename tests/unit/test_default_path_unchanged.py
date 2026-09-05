from pathlib import Path

from bilingual_sub.models import JobConfig, STAGES
from bilingual_sub.pipeline import artifact_key


def _fake_dub(*_a, output, **_k):
    dest = Path(output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"dub")
    return dest


def test_jobconfig_defaults_match_legacy_path():
    cfg = JobConfig(
        input_video=Path("a.mp4"),
        output_video=Path("b.mp4"),
        output_srt=Path("c.srt"),
        work_dir=Path("work"),
    )
    assert cfg.source_lang == "zh"
    assert cfg.target_lang == "zh"
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


def test_pipeline_uses_refine_when_enabled(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    called = {"refine": 0, "plain": 0}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("\n".join(c.en or "" for c in cues), encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)

    def fake_transcribe(wav, **kwargs):
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return [Segment(0.2, 1.6, "大家好")]

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)

    def fake_refine(cues, **k):
        called["refine"] += 1
        return (
            [Cue(c.start, c.end, c.zh, "Polished hello") for c in cues],
            TranslateStats(api_calls=3),
            [],
        )

    def boom_plain(*a, **k):
        called["plain"] += 1
        raise AssertionError("plain translate should not run when refine is on")

    monkeypatch.setattr("bilingual_sub.secrets.store.get_api_key", lambda: "test-key")
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues_refined", fake_refine)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", boom_plain)
    monkeypatch.setattr("bilingual_sub.pipeline.ytdlp_download", lambda *a, **k: video)
    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", _fake_dub)

    cfg = JobConfig(
        input_video=video,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
        refine_translate=True,
        target_lang="en",
    )
    result = run(cfg)
    assert called == {"refine": 1, "plain": 0}
    assert "Polished hello" in result.output_srt.read_text(encoding="utf-8")


def test_pipeline_skips_translate_when_single_source_lang(tmp_path: Path, monkeypatch):
    from bilingual_sub.models import Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    called = {"translate": 0}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("\n".join(c.zh for c in cues), encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)

    def fake_transcribe(wav, **kwargs):
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return [Segment(0.2, 1.6, "大家好")]

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)

    def boom_translate(*a, **k):
        called["translate"] += 1
        raise AssertionError("single-language Chinese jobs should skip translate")

    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", boom_translate)
    monkeypatch.setattr("bilingual_sub.pipeline.ytdlp_download", lambda *a, **k: video)
    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", _fake_dub)

    cfg = JobConfig(
        input_video=video,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
        target_lang="zh",
        subtitle_mode="single:zh",
    )
    result = run(cfg)
    assert called["translate"] == 0
    assert "大家好" in result.output_srt.read_text(encoding="utf-8")


def test_pipeline_translates_bilingual_when_target_is_chinese(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    seen = {"target": ""}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("\n".join(f"{c.zh}\n{c.en}" for c in cues), encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)

    def fake_transcribe(wav, **kwargs):
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return [Segment(0.2, 1.6, "大家好")]

    def fake_translate(cues, **kwargs):
        seen["target"] = kwargs.get("target_lang")
        return [Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", fake_translate)
    monkeypatch.setattr("bilingual_sub.pipeline.ytdlp_download", lambda *a, **k: video)
    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", _fake_dub)

    cfg = JobConfig(
        input_video=video,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
        source_lang="zh",
        target_lang="zh",
        subtitle_mode="bilingual",
    )
    result = run(cfg)
    assert seen["target"] == "en"
    text = result.output_srt.read_text(encoding="utf-8")
    assert "大家好" in text
    assert "Hello" in text


def test_pipeline_dubs_onto_burned_output(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"source")
    dest = tmp_path / "out.mp4"
    seen: dict[str, Path] = {}

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

    def fake_burn(src, ass, out, **k):
        Path(out).write_bytes(b"burned")
        seen["burn"] = Path(out)

    def fake_dub(cues, *, video, output, **k):
        seen["dub_src"] = Path(video)
        Path(output).write_bytes(b"dubbed")
        return Path(output)

    monkeypatch.setattr("bilingual_sub.pipeline.burn_subtitles", fake_burn)
    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", fake_dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *_a, **_k: object())

    cfg = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=True,
        enable_dub=True,
        tts_provider="openai",
        target_lang="en",
    )
    result = run(cfg)
    assert seen["burn"] != dest
    assert seen["burn"].name == "burned.mp4"
    assert seen["dub_src"] == seen["burn"]
    assert result.output_mp4 == dest
    assert dest.read_bytes() == b"dubbed"
    assert result.output_dub is None


def test_same_lang_job_does_not_dub(tmp_path: Path, monkeypatch):
    from bilingual_sub.models import Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    dest = tmp_path / "out.mp4"
    called = {"dub": 0}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("\n".join(f"{c.zh}\n{c.en or ''}" for c in cues), encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)

    def fake_transcribe(wav, **kwargs):
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return [Segment(0.2, 1.6, "大家好")]

    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue

    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []),
    )
    monkeypatch.setattr("bilingual_sub.pipeline.burn_subtitles", lambda src, ass, out, **k: Path(out).write_bytes(b"zh"))

    def boom_dub(*a, **k):
        called["dub"] += 1
        raise AssertionError("same-language jobs must keep original audio")

    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", boom_dub)

    cfg = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=True,
        enable_dub=True,
        tts_provider="openai",
        source_lang="zh",
        target_lang="zh",
        subtitle_mode="bilingual",
    )
    result = run(cfg)
    assert called["dub"] == 0
    assert dest.read_bytes() == b"zh"
    text = result.output_srt.read_text(encoding="utf-8")
    assert "大家好" in text
    assert "Hello" in text


def test_pipeline_pair_translates_english_asr_into_chinese(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    seen: list[tuple[str | None, str | None]] = []

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("\n".join(f"{c.zh}\n{c.en or ''}" for c in cues), encoding="utf-8")

    def fake_transcribe(wav, **kwargs):
        if kwargs.get("out_json"):
            kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8")
        return [Segment(0.2, 1.6, "Hello everyone")]

    def fake_translate(cues, **kwargs):
        seen.append((kwargs.get("source_lang"), kwargs.get("target_lang")))
        if kwargs.get("target_lang") == "zh":
            return [Cue(c.start, c.end, c.zh, "大家好") for c in cues], TranslateStats(), []
        return [Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)
    monkeypatch.setattr("bilingual_sub.pipeline.transcribe", fake_transcribe)
    monkeypatch.setattr("bilingual_sub.pipeline.translate_cues", fake_translate)
    monkeypatch.setattr("bilingual_sub.pipeline.ytdlp_download", lambda *a, **k: video)
    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", _fake_dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *_a, **_k: object())

    cfg = JobConfig(
        input_video=video,
        output_video=None,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=False,
        source_lang="zh",
        target_lang="zh",
        subtitle_mode="bilingual",
    )
    result = run(cfg)
    assert ("en", "zh") in seen
    text = result.output_srt.read_text(encoding="utf-8")
    assert "大家好" in text
    assert "Hello everyone" in text


def test_english_speech_target_zh_dubs(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    dest = tmp_path / "out.mp4"
    called = {"dub": 0}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.write_subtitles",
        lambda cues, preset, ass_path, srt_path, **k: (
            Path(ass_path).write_text("[Script Info]\n", encoding="utf-8"),
            Path(srt_path).write_text("1\n", encoding="utf-8"),
        ),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.transcribe",
        lambda wav, **kwargs: (
            kwargs.get("out_json")
            and kwargs["out_json"].write_text('{"language":"zh","segments":[]}', encoding="utf-8"),
            [Segment(0.2, 1.6, "Hello everyone")],
        )[1],
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: (
            [Cue(c.start, c.end, "大家好" if k.get("target_lang") == "zh" else c.zh, "Hello everyone") for c in cues],
            TranslateStats(),
            [],
        ),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.burn_subtitles",
        lambda src, ass, out, **k: Path(out).write_bytes(b"burned"),
    )

    def fake_dub(cues, *, video, output, **k):
        called["dub"] += 1
        Path(output).write_bytes(b"zh-dub")
        return Path(output)

    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", fake_dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *_a, **_k: object())

    cfg = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=True,
        enable_dub=False,
        tts_provider="none",
        source_lang="zh",
        target_lang="zh",
        subtitle_mode="bilingual",
    )
    result = run(cfg)
    assert called["dub"] == 1
    assert dest.read_bytes() == b"zh-dub"
    assert result.output_mp4 == dest


def test_english_target_dubs_even_when_asr_looks_english(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    dest = tmp_path / "out.mp4"
    seen: dict = {"dub": 0, "mode": None, "lang": None}

    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)

    def fake_write(cues, preset, ass_path, srt_path, **kwargs):
        seen["mode"] = kwargs.get("mode")
        Path(ass_path).write_text("[Script Info]\n", encoding="utf-8")
        Path(srt_path).write_text("1\n", encoding="utf-8")

    monkeypatch.setattr("bilingual_sub.pipeline.write_subtitles", fake_write)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.transcribe",
        lambda wav, **kwargs: (
            kwargs.get("out_json")
            and kwargs["out_json"].write_text('{"language":"en","segments":[]}', encoding="utf-8"),
            [Segment(0.2, 1.6, "Hello everyone")],
        )[1],
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, "大家好", "Hello everyone") for c in cues], TranslateStats(), []),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.burn_subtitles",
        lambda src, ass, out, **k: Path(out).write_bytes(b"burned"),
    )

    def fake_dub(cues, *, video, output, lang, **k):
        seen["dub"] += 1
        seen["lang"] = lang
        Path(output).write_bytes(b"en-dub")
        return Path(output)

    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", fake_dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *_a, **_k: object())

    cfg = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=True,
        enable_dub=True,
        tts_provider="openai",
        source_lang="zh",
        target_lang="en",
        subtitle_mode="enzh",
    )
    result = run(cfg)
    assert seen["dub"] == 1
    assert seen["lang"] == "en"
    assert seen["mode"] == "enzh"
    assert dest.read_bytes() == b"en-dub"
    assert result.output_mp4 == dest


def test_dub_failure_does_not_keep_original_audio_quietly(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    dest = tmp_path / "out.mp4"
    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.write_subtitles",
        lambda cues, preset, ass_path, srt_path, **k: (
            Path(ass_path).write_text("[Script Info]\n", encoding="utf-8"),
            Path(srt_path).write_text("1\n", encoding="utf-8"),
        ),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.transcribe",
        lambda wav, **kwargs: [Segment(0.2, 1.6, "大家好")],
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, c.zh, "Hello") for c in cues], TranslateStats(), []),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.burn_subtitles",
        lambda src, ass, out, **k: Path(out).write_bytes(b"burned"),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.dub_cues",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tts-1 missing")),
    )
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *_a, **_k: object())
    cfg = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=True,
        source_lang="zh",
        target_lang="en",
        subtitle_mode="enzh",
    )
    try:
        run(cfg)
    except RuntimeError as exc:
        assert "配音失败" in str(exc)
        assert "tts-1" in str(exc)
    else:
        raise AssertionError("cross-language dub failure must surface")
    assert not dest.is_file() or dest.read_bytes() != b"burned"


def test_chinese_transcript_dubs_to_english_even_if_source_combo_is_en(tmp_path: Path, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue, Segment
    from bilingual_sub.pipeline import run

    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    dest = tmp_path / "out.mp4"
    seen = {"dub": 0, "lang": None}
    monkeypatch.setattr(
        "bilingual_sub.pipeline.probe_video",
        lambda p: {"width": 1280, "height": 720, "duration": 2, "has_audio": True},
    )
    monkeypatch.setattr("bilingual_sub.pipeline.extract_wav", lambda *a, **k: None)
    monkeypatch.setattr("bilingual_sub.pipeline.detect_silences", lambda *a, **k: [])
    monkeypatch.setattr("bilingual_sub.pipeline.copy_to_ascii_workdir", lambda src, work: src)
    monkeypatch.setattr(
        "bilingual_sub.pipeline.write_subtitles",
        lambda cues, preset, ass_path, srt_path, **k: (
            Path(ass_path).write_text("[Script Info]\n", encoding="utf-8"),
            Path(srt_path).write_text("1\n", encoding="utf-8"),
        ),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.transcribe",
        lambda wav, **kwargs: [Segment(0.2, 1.6, "大家好，欢迎回来")],
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.translate_cues",
        lambda cues, **k: ([Cue(c.start, c.end, c.zh, "Hello, welcome back") for c in cues], TranslateStats(), []),
    )
    monkeypatch.setattr(
        "bilingual_sub.pipeline.burn_subtitles",
        lambda src, ass, out, **k: Path(out).write_bytes(b"burned"),
    )

    def fake_dub(cues, *, output, lang, **k):
        seen["dub"] += 1
        seen["lang"] = lang
        Path(output).write_bytes(b"en-dub")
        return Path(output)

    monkeypatch.setattr("bilingual_sub.pipeline.dub_cues", fake_dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *_a, **_k: object())
    cfg = JobConfig(
        input_video=video,
        output_video=dest,
        output_srt=tmp_path / "o.srt",
        work_dir=tmp_path / "work",
        burn=True,
        enable_dub=False,
        tts_provider="none",
        source_lang="en",
        target_lang="en",
        subtitle_mode="bilingual",
    )
    result = run(cfg)
    assert seen["dub"] == 1
    assert seen["lang"] == "en"
    assert dest.read_bytes() == b"en-dub"
    assert result.output_mp4 == dest


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
