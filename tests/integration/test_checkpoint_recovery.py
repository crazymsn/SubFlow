import json
import os
from pathlib import Path

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.adapters.ffmpeg import FfmpegError
from bilingual_sub.config import AppSettings
from bilingual_sub.core.audio import detect_silences
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.models import JobConfig, Segment


@pytest.fixture
def job(tmp_path, monkeypatch):
    video = tmp_path / "input.mp4"
    video.write_bytes(b"old input")
    cfg = JobConfig(video, None, tmp_path / "out.srt", tmp_path / "work", burn=False,
                    source_lang="en", target_lang="en", subtitle_mode="single:en")
    settings = AppSettings()
    calls = {"asr": 0, "silence": 0}
    monkeypatch.setattr(p, "probe_video", lambda path: {
        "duration": 3, "has_audio": True, "width": 640, "height": 480})
    def extract(source, path, **kwargs):
        path.write_bytes(b"audio fixture")
    def silence(*args, **kwargs):
        calls["silence"] += 1
        return []
    def asr(wav, **kwargs):
        calls["asr"] += 1
        seg = Segment(0.2, 1.6, f"recognized version {calls['asr']}")
        kwargs["out_json"].write_text(json.dumps({"segments": [seg.__dict__]}))
        return [seg]
    monkeypatch.setattr(p, "extract_wav", extract)
    monkeypatch.setattr(p, "detect_silences", silence)
    monkeypatch.setattr(p, "transcribe", asr)
    return cfg, settings, calls, asr, extract


def test_failed_new_input_cannot_resume_from_old_transcript(job, monkeypatch):
    cfg, settings, calls, asr, _ = job
    first = p.run(cfg, settings)
    previous_transcript = (cfg.work_dir / "transcript.json").read_bytes()
    cfg.input_video.write_bytes(b"a different input video")
    def fail(*args, **kwargs):
        raise RuntimeError("recognition failed")
    monkeypatch.setattr(p, "transcribe", fail)
    with pytest.raises(RuntimeError, match="recognition failed"):
        p.run(cfg, settings)
    state = json.loads((cfg.work_dir / "job_state.json").read_text())
    assert state["completed_stage"] == "silence" and state["job_id"] != first.job_id
    assert (cfg.work_dir / "transcript.json").read_bytes() == previous_transcript
    cfg.resume_from = "build_cues"
    with pytest.raises(ValueError, match="尚未完成"):
        p.run(cfg, settings)
    assert (cfg.work_dir / "transcript.json").read_bytes() == previous_transcript
    cfg.resume_from = "transcribe"
    monkeypatch.setattr(p, "transcribe", asr)
    second = p.run(cfg, settings)
    assert second.job_id != first.job_id and calls["asr"] == 2
    assert "version 2" in cfg.output_srt.read_text()


def test_translation_retry_reuses_recognition_and_saved_work(job, monkeypatch):
    from dataclasses import replace

    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue

    cfg, settings, calls, _, _ = job
    cfg.target_lang, cfg.subtitle_mode = "fr", "bilingual"
    # Avoid speech synthesis in this translation checkpoint contract.
    monkeypatch.setattr(p, "job_needs_dub", lambda *a, **k: False)
    attempts = []
    def translate(cues, **kwargs):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("translation service disconnected")
        text = "你好" if kwargs.get("target_lang") == "zh" else "Bonjour"
        return [Cue(c.start, c.end, c.zh, text) for c in cues], TranslateStats(), []
    monkeypatch.setattr(p, "translate_cues", translate)
    ready = []
    with pytest.raises(RuntimeError, match="disconnected"):
        p.run(cfg, settings, on_work_ready=ready.append)
    original = (cfg.work_dir / "transcript.json").read_bytes()
    result = p.run(replace(cfg, resume_from="translate", work_dir=ready[0]), settings)
    assert calls == {"asr": 1, "silence": 1}
    # A bilingual job may translate both caption and spoken-target languages.
    assert len(attempts) >= 2 and not result.missing_en
    assert (cfg.work_dir / "transcript.json").read_bytes() == original
    assert "你好" in cfg.output_srt.read_text(encoding="utf-8")


def test_translation_retry_accepts_new_model_without_repeating_asr(job, monkeypatch):
    from dataclasses import replace

    from bilingual_sub.core.translate import TranslateStats
    from bilingual_sub.models import Cue

    cfg, settings, calls, _, _ = job
    cfg.target_lang, cfg.subtitle_mode = "zh", "single:zh"
    monkeypatch.setattr(p, "job_needs_dub", lambda *a, **k: False)
    attempts = []
    def translate(cues, **kwargs):
        attempts.append(kwargs["model"])
        if kwargs["model"] == cfg.translate_model:
            raise RuntimeError("model temporarily unavailable")
        return [Cue(c.start, c.end, c.zh, "翻译已恢复") for c in cues], TranslateStats(), []
    monkeypatch.setattr(p, "translate_cues", translate)
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        p.run(cfg, settings)
    original = (cfg.work_dir / "transcript.json").read_bytes()
    retry = replace(cfg, resume_from="translate", translate_model="replacement-model", translate_batch_size=1)
    result = p.run(retry, settings)
    assert not result.missing_en
    assert calls == {"asr": 1, "silence": 1}
    assert attempts == [cfg.translate_model, "replacement-model"]
    assert (cfg.work_dir / "transcript.json").read_bytes() == original
    assert "翻译已恢复" in cfg.output_srt.read_text(encoding="utf-8")
    record = json.loads((cfg.work_dir / "job_input.json").read_text())
    assert record["processing_profile"]["translation"]["model"] == "replacement-model"


@pytest.mark.parametrize("change", [
    {"whisper_model": "tiny"}, {"source_lang": "fr"}, {"target_lang": "fr"},
    {"subtitle_mode": "bilingual"}, {"preview_minutes": 1},
    {"resume_from": "render", "translate_model": "another-model"},
])
def test_translation_rewind_still_rejects_incompatible_cached_inputs(job, change):
    from dataclasses import replace

    cfg, settings, calls, _, _ = job
    p.run(cfg, settings)
    retry = replace(cfg, **{"resume_from": "translate", **change})
    with pytest.raises(FileNotFoundError, match="设置不同"):
        p.run(retry, settings)
    assert calls["asr"] == 1


def test_cancelled_rewind_cannot_skip_the_failed_stage(job, monkeypatch):
    cfg, settings, calls, _, extract = job
    p.run(cfg, settings)
    cfg.resume_from = "extract"
    def cancel(*args, **kwargs):
        raise JobStopped()
    monkeypatch.setattr(p, "extract_wav", cancel)
    with pytest.raises(JobStopped):
        p.run(cfg, settings)
    state = json.loads((cfg.work_dir / "job_state.json").read_text())
    assert state["stage"] == "stopped" and state["completed_stage"] == "ingest"
    cfg.resume_from = "transcribe"
    with pytest.raises(ValueError, match="尚未完成"):
        p.run(cfg, settings)
    cfg.resume_from = "extract"
    monkeypatch.setattr(p, "extract_wav", extract)
    p.run(cfg, settings)
    assert calls == {"asr": 2, "silence": 2}


def test_corrupt_finished_cues_trigger_processing_instead_of_empty_export(job):
    cfg, settings, calls, _, _ = job
    settings.video.work_dir = str(cfg.work_dir)
    cfg.work_dir = Path("auto")
    first = p.run(cfg, settings)
    (first.report_path.parent / "cues.bilingual.json").write_text("{}")
    second = p.run(cfg, settings)
    assert not second.reused and calls["asr"] == 2
    assert "version 2" in cfg.output_srt.read_text()


@pytest.mark.parametrize("name,stage,resume", [
    ("speech.wav", "extract", "transcribe"),
    ("silences.json", "silence", "transcribe"),
    ("transcript.json", "transcribe", "build_cues"),
    ("cues.zh.json", "build_cues", "translate"),
    ("cues.source.json", "build_cues", "translate"),
    ("cues.bilingual.json", "translate", "render"),
    ("subs.ass", "render", "burn"),
])
def test_resume_rejects_changed_artifact_before_export(job, name, stage, resume):
    cfg, settings, calls, _, _ = job
    p.run(cfg, settings)
    before = cfg.output_srt.read_bytes()
    artifact = cfg.work_dir / name
    # Whitespace is legal in JSON and ASS; schema-only checks cannot catch this.
    artifact.write_bytes(artifact.read_bytes() + b" \n")
    cfg.resume_from = resume
    with pytest.raises(ValueError, match=f"{stage} 阶段缓存"):
        p.run(cfg, settings)
    assert cfg.output_srt.read_bytes() == before and calls["asr"] == 1
    cfg.resume_from = stage
    p.run(cfg, settings)
    assert cfg.output_srt.is_file()


@pytest.mark.parametrize("name", ["cues.bilingual.json", "cues.source.json"])
def test_valid_replacement_cues_force_processing(job, name):
    cfg, settings, calls, _, _ = job
    settings.video.work_dir = str(cfg.work_dir)
    cfg.work_dir = Path("auto")
    first = p.run(cfg, settings)
    artifact = first.report_path.parent / name
    data = json.loads(artifact.read_text())
    data[0]["zh"] = "unrelated replacement content"
    artifact.write_text(json.dumps(data))
    result = p.run(cfg, settings)
    assert not result.reused and calls["asr"] == 2
    assert "replacement" not in cfg.output_srt.read_text()


def test_reexport_refreshes_render_identity_and_allows_resume(job):
    cfg, settings, calls, _, _ = job
    settings.video.work_dir = str(cfg.work_dir)
    cfg.work_dir = Path("auto")
    first = p.run(cfg, settings)
    cfg.subtitle_en_color = "#ABCDEF"
    assert p.run(cfg, settings).reused
    work = first.report_path.parent
    assert p._verify_cache(work, "render")["subs.ass"] == p.file_digest(work / "subs.ass")
    cfg.resume_from = "burn"
    p.run(cfg, settings)
    assert calls["asr"] == 1


def test_source_cues_changed_after_export_check_are_rejected(job):
    cfg, settings, _, _, _ = job
    settings.video.work_dir, cfg.work_dir = str(cfg.work_dir), Path("auto")
    first = p.run(cfg, settings)
    def change(stage, pct):
        if stage == "export":
            path = first.report_path.parent / "cues.source.json"
            path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="build_cues 阶段缓存"):
        p.run(cfg, settings, on_progress=change)


@pytest.mark.parametrize("missing", [False, True])
def test_netflix_resume_rejects_missing_or_replaced_fitted_cues(job, missing):
    cfg, settings, _, _, _ = job
    cfg.subtitle_mode = "netflix_single"
    p.run(cfg, settings)
    fitted = cfg.work_dir / "cues.fitted.json"
    if missing:
        fitted.unlink()
    else:
        fitted.write_bytes(fitted.read_bytes() + b" ")
    cfg.resume_from = "render"
    with pytest.raises(ValueError, match="fit_subs 阶段缓存"):
        p.run(cfg, settings)


def test_translate_resume_restores_generated_glossary(job, monkeypatch):
    from bilingual_sub.core.glossary import Glossary
    from bilingual_sub.core.translate import TranslateStats

    cfg, settings, calls, _, _ = job
    cfg.glossary_generate = True
    cfg.subtitle_mode = "bilingual"
    monkeypatch.setattr("bilingual_sub.secrets.store.get_api_key", lambda: "test-placeholder")
    monkeypatch.setattr("bilingual_sub.adapters.meding.create_client", lambda *a, **kw: object())
    monkeypatch.setattr(p, "extract_glossary", lambda *a, **kw:
                        Glossary(replacements=[("special term", "固定译法")]))
    blocks = []
    def translate(cues, **kwargs):
        blocks.append(kwargs["glossary_block"])
        if len(blocks) == 1:
            raise RuntimeError("translation interrupted")
        for cue in cues:
            cue.en = "这是翻译。"
        return cues, TranslateStats(), []
    monkeypatch.setattr(p, "translate_cues", translate)
    with pytest.raises(RuntimeError, match="translation interrupted"):
        p.run(cfg, settings)
    monkeypatch.setattr(p, "extract_glossary", lambda *a, **kw: pytest.fail("must reuse glossary"))
    cfg.resume_from = "translate"
    p.run(cfg, settings)
    assert len(blocks) == 2 and blocks[0] == blocks[1]
    assert "special term => 固定译法" in blocks[1] and calls["asr"] == 1
    merged = cfg.work_dir / "glossary.merged.yaml"
    merged.write_bytes(merged.read_bytes() + b"\n# changed after generation\n")
    with pytest.raises(ValueError, match="glossary 阶段缓存"):
        p.run(cfg, settings)
    assert len(blocks) == 2


def test_resume_ignores_unrecorded_stale_glossary(job):
    cfg, settings, _, _, _ = job
    p.run(cfg, settings)
    (cfg.work_dir / "glossary.merged.yaml").write_text("[invalid stale data")
    cfg.resume_from = "translate"
    p.run(cfg, settings)
    assert p._verify_cache(cfg.work_dir, "glossary") == {}


@pytest.fixture
def dub_job(job, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats

    cfg, settings, calls, _, _ = job
    cfg.target_lang, cfg.subtitle_mode, cfg.tts_provider = "zh", "single:zh", "edge"
    cfg.burn, cfg.output_video = True, cfg.output_srt.with_suffix(".mp4")
    def translate(cues, **kwargs):
        for cue in cues:
            cue.en = "这是目标语言的配音。"
        return cues, TranslateStats(), []
    def dub(cues, *, video, output, **kwargs):
        output.write_bytes(video.read_bytes() + b" dubbed")
        return output
    monkeypatch.setattr(p, "translate_cues", translate)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *a, **kw: object())
    monkeypatch.setattr(p, "burn_subtitles", lambda src, ass, out, **kw: out.write_bytes(b"burned"))
    monkeypatch.setattr(p, "dub_cues", dub)
    return cfg, settings, calls


@pytest.mark.parametrize("missing", [False, True])
def test_dub_resume_rejects_bad_burn_before_starting_provider(dub_job, monkeypatch, missing):
    cfg, settings, _ = dub_job
    p.run(cfg, settings)
    old_movie = cfg.output_video.read_bytes()
    burned = cfg.work_dir / "burned.mp4"
    if missing:
        burned.unlink()
    else:
        burned.write_bytes(b"another burned video")
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts",
                        lambda *a, **kw: pytest.fail("do not start synthesis with bad burn cache"))
    cfg.resume_from = "dub"
    with pytest.raises(RuntimeError, match="burn 阶段缓存"):
        p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == old_movie


def test_reexport_rejects_changed_dub_and_rebuilds(dub_job):
    cfg, settings, calls = dub_job
    settings.video.work_dir, cfg.work_dir = str(cfg.work_dir), Path("auto")
    result = p.run(cfg, settings)
    (result.report_path.parent / "dubbed.mp4").write_bytes(b"unrelated dubbed video")
    result = p.run(cfg, settings)
    assert not result.reused and calls["asr"] == 2
    assert cfg.output_video.read_bytes() == b"burned dubbed"


@pytest.mark.parametrize("burn", [False, True])
def test_done_resume_restores_dub_at_new_destination_without_synthesis(dub_job, monkeypatch, burn):
    cfg, settings, calls = dub_job
    cfg.burn = burn
    first = p.run(cfg, settings)
    expected = (first.output_mp4 or first.output_dub).read_bytes()
    cfg.output_video = cfg.output_video.with_name("relocated.mp4")
    cfg.output_srt = cfg.output_srt.with_name("relocated.srt")
    cfg.resume_from = "done"
    monkeypatch.setattr(p, "dub_cues", lambda *a, **kw: pytest.fail("reuse verified dubbed video"))
    second = p.run(cfg, settings)
    destination = second.output_mp4 or second.output_dub
    assert destination.read_bytes() == expected and destination != (first.output_mp4 or first.output_dub)
    assert calls["asr"] == 1
    report = json.loads(second.report_path.read_text())
    assert report["output_mp4" if burn else "output_dub"] == str(destination)


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_done_resume_rejects_bad_dubbed_movie(dub_job, damage):
    cfg, settings, _ = dub_job
    first = p.run(cfg, settings)
    before = first.output_mp4.read_bytes()
    cached = cfg.work_dir / "dubbed.mp4"
    if damage == "missing":
        cached.unlink()
    else:
        cached.write_bytes(b"other video")
    cfg.resume_from = "done"
    with pytest.raises(ValueError, match="dub 阶段缓存"):
        p.run(cfg, settings)
    assert first.output_mp4.read_bytes() == before
    assert json.loads((cfg.work_dir / "job_state.json").read_text())["stage"] != "done"


@pytest.mark.parametrize("burn", [False, True])
def test_dubbed_export_checks_bytes_copied_after_cache_validation(dub_job, monkeypatch, burn):
    cfg, settings, _ = dub_job
    cfg.burn = burn
    first = p.run(cfg, settings)
    destination = first.output_mp4 or first.output_dub
    before = destination.read_bytes()
    original_copy = p.copy_file
    def replace_after_validation(source, dest, **kwargs):
        if source == cfg.work_dir / "dubbed.mp4" and dest == destination:
            stamp = source.stat()
            source.write_bytes(b"x" * stamp.st_size)
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return original_copy(source, dest, **kwargs)
    monkeypatch.setattr(p, "copy_file", replace_after_validation)
    cfg.resume_from = "done"
    with pytest.raises(ValueError, match="内容"):
        p.run(cfg, settings)
    assert destination.read_bytes() == before


def test_original_audio_export_checks_bytes_copied_after_validation(job, monkeypatch):
    cfg, settings, _, _, _ = job
    cfg.burn, cfg.output_video = True, cfg.output_srt.with_suffix(".mp4")
    monkeypatch.setattr(p, "burn_subtitles", lambda src, ass, out, **kw: out.write_bytes(b"original voice"))
    p.run(cfg, settings)
    before = cfg.output_video.read_bytes()
    original_copy = p.copy_file
    def replace_after_validation(source, dest, **kwargs):
        if source == cfg.work_dir / "burned.mp4":
            stamp = source.stat()
            source.write_bytes(b"x" * stamp.st_size)
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        return original_copy(source, dest, **kwargs)
    monkeypatch.setattr(p, "copy_file", replace_after_validation)
    cfg.resume_from = "done"
    with pytest.raises(ValueError, match="内容"):
        p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == before


@pytest.mark.parametrize("stage", ["dub", "done"])
def test_no_dub_resume_restores_missing_movie_without_burn(job, monkeypatch, stage):
    cfg, settings, calls, _, _ = job
    cfg.burn, cfg.output_video = True, cfg.output_srt.with_suffix(".mp4")
    monkeypatch.setattr(p, "burn_subtitles", lambda src, ass, out, **kw: out.write_bytes(b"original voice movie"))
    first = p.run(cfg, settings)
    first.output_mp4.unlink()
    cfg.resume_from = stage
    monkeypatch.setattr(p, "burn_subtitles", lambda *a, **kw: pytest.fail("reuse internal burned movie"))
    result = p.run(cfg, settings)
    assert result.output_mp4.read_bytes() == b"original voice movie" and calls["asr"] == 1


def test_done_resume_does_not_certify_replaced_external_movie(job, monkeypatch):
    cfg, settings, _, _, _ = job
    cfg.burn, cfg.output_video = True, cfg.output_srt.with_suffix(".mp4")
    monkeypatch.setattr(p, "burn_subtitles", lambda src, ass, out, **kw: out.write_bytes(b"original movie"))
    p.run(cfg, settings)
    cfg.output_video.write_bytes(b"unrelated movie")
    cfg.resume_from = "done"
    p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == b"original movie"


@pytest.mark.parametrize("change,stage", [("subtitle_en_color", "render"), ("tts_prompt_text", "dub")])
def test_done_resume_rejects_media_from_different_settings(dub_job, change, stage):
    cfg, settings, _ = dub_job
    p.run(cfg, settings)
    before = cfg.output_video.read_bytes()
    setattr(cfg, change, "#ABCDEF" if change == "subtitle_en_color" else "different reference text")
    cfg.resume_from = "done"
    with pytest.raises(ValueError, match=f"{stage} 阶段"):
        p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == before


def test_dub_resume_allows_new_voice_but_requires_matching_burn(dub_job, monkeypatch):
    cfg, settings, _ = dub_job
    p.run(cfg, settings)
    cfg.tts_prompt_text = "new voice reference"
    cfg.resume_from = "dub"
    p.run(cfg, settings)
    settings.burn.cq += 1
    with pytest.raises(RuntimeError, match="burn 阶段"):
        p.run(cfg, settings)


@pytest.mark.parametrize("revision", ["b" * 32, None])
def test_done_cannot_export_old_model_but_dub_can_regenerate(dub_job, monkeypatch, revision):
    cfg, settings, calls = dub_job
    first = p.run(cfg, settings)
    assert json.loads(first.report_path.read_text())["tts_model_revision"] == "a" * 32
    original = cfg.output_video.read_bytes()
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision", lambda _: revision)
    cfg.resume_from = "done"
    with pytest.raises(ValueError, match="dub 阶段|配音模型"):
        p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == original
    cfg.resume_from = "dub"
    result = p.run(cfg, settings)
    assert json.loads(result.report_path.read_text())["tts_model_revision"] == revision
    assert calls["asr"] == 1


@pytest.mark.parametrize("target", ["zh-Hans", "zh-Hant"])
def test_chinese_original_audio_does_not_query_model_identity(job, monkeypatch, target):
    cfg, settings, _, _, _ = job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "zh", target, "single:zh"
    def asr(wav, **kwargs):
        seg = Segment(0.2, 1.6, "大家好，这是中文视频")
        kwargs["out_json"].write_text(json.dumps({"language": "zh", "segments": [seg.__dict__]}))
        return [seg]
    monkeypatch.setattr(p, "transcribe", asr)
    monkeypatch.setattr("bilingual_sub.adapters.tts.model_identity.fetch_model_revision",
                        lambda _: pytest.fail("same-language task must not depend on the TTS server"))
    result = p.run(cfg, settings)
    report = json.loads(result.report_path.read_text())
    assert report["dubbed"] is False and report["tts_model_revision"] is None


def test_failed_export_after_burn_can_resume_without_encoding_again(job, monkeypatch):
    cfg, settings, calls, _, _ = job
    cfg.burn, cfg.output_video = True, cfg.output_srt.with_suffix(".mp4")
    cfg.output_video.write_bytes(b"old public movie")
    burns = []
    def burn(src, ass, out, **kwargs):
        burns.append(out)
        out.write_bytes(b"new movie")
    monkeypatch.setattr(p, "burn_subtitles", burn)
    original_copy = p.copy_file
    def fail(source, destination, **kwargs):
        if destination == cfg.output_video:
            raise OSError("export failed")
        return original_copy(source, destination, **kwargs)
    monkeypatch.setattr(p, "copy_file", fail)
    with pytest.raises(OSError, match="export failed"):
        p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == b"old public movie"
    assert json.loads((cfg.work_dir / "job_state.json").read_text())["stage"] == "burn"
    monkeypatch.setattr(p, "copy_file", original_copy)
    cfg.resume_from = "dub"
    p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == b"new movie"
    assert len(burns) == 1 and calls["asr"] == 1


def test_done_resume_preserves_translation_statistics_and_missing_lines(job, monkeypatch):
    from bilingual_sub.core.translate import TranslateStats
    cfg, settings, _, _, _ = job
    cfg.subtitle_mode = "bilingual"
    def translate(cues, **kwargs):
        for cue in cues:
            cue.en = "固定译文"
        return cues, TranslateStats(cache_hits=3, api_calls=2), ["needs review"]
    monkeypatch.setattr(p, "translate_cues", translate)
    first = p.run(cfg, settings)
    before = json.loads(first.report_path.read_text())
    assert before["missing_en_count"] == 1 and before["translate_api_calls"] == 2
    cfg.resume_from = "done"
    second = p.run(cfg, settings)
    after = json.loads(second.report_path.read_text())
    for key in ("missing_en_count", "missing_en_samples", "translate_cache_hits", "translate_api_calls"):
        assert after[key] == before[key]


def test_reference_changed_after_mix_cannot_relabel_or_export_old_voice(dub_job, monkeypatch):
    cfg, settings, _ = dub_job
    reference = cfg.output_srt.with_name("ref.wav")
    reference.write_bytes(b"speaker one")
    cfg.tts_ref_audio = str(reference)
    p.run(cfg, settings)
    before = cfg.output_video.read_bytes()
    def changed(cues, *, output, **kwargs):
        output.write_bytes(b"new mixed video")
        reference.write_bytes(b"speaker two")
        return output
    monkeypatch.setattr(p, "dub_cues", changed)
    cfg.resume_from = "dub"
    with pytest.raises(RuntimeError, match="配音期间"):
        p.run(cfg, settings)
    assert cfg.output_video.read_bytes() == before


@pytest.mark.parametrize("burn", [False, True])
def test_completed_dub_with_failed_export_resumes_without_synthesis(dub_job, monkeypatch, burn):
    from bilingual_sub.gui.output_path import resolve_dub_sidecar
    cfg, settings, _ = dub_job
    cfg.burn = burn
    destination = cfg.output_video if burn else resolve_dub_sidecar(cfg.output_video, cfg.output_srt)
    destination.write_bytes(b"old exported movie")
    original = p.copy_file
    def fail(source, dest, **kwargs):
        if dest == destination:
            raise OSError("destination busy")
        return original(source, dest, **kwargs)
    monkeypatch.setattr(p, "copy_file", fail)
    with pytest.raises(RuntimeError, match="配音已完成.*done"):
        p.run(cfg, settings)
    assert destination.read_bytes() == b"old exported movie"
    assert json.loads((cfg.work_dir / "job_state.json").read_text())["completed_stage"] == "dub"
    monkeypatch.setattr(p, "copy_file", original)
    monkeypatch.setattr(p, "dub_cues", lambda *a, **kw: pytest.fail("do not synthesize again"))
    cfg.resume_from = "done"
    result = p.run(cfg, settings)
    assert (result.output_mp4 or result.output_dub) == destination
    assert destination.read_bytes() == (cfg.work_dir / "dubbed.mp4").read_bytes()


def test_silence_detection_surfaces_actual_ffmpeg_failure(tmp_path):
    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not an audio file")
    with pytest.raises(FfmpegError):
        detect_silences(broken)


@pytest.mark.parametrize("missing", ["srt", "ass", "work_ass"])
def test_resume_after_render_recreates_missing_subtitle_exports(job, missing):
    cfg, settings, calls, _, _ = job
    first = p.run(cfg, settings)
    path = {"srt": first.output_srt, "ass": first.output_ass,
            "work_ass": cfg.work_dir / "subs.ass"}[missing]
    expected = path.read_bytes()
    path.unlink()
    cfg.resume_from = "burn"
    second = p.run(cfg, settings)
    assert calls["asr"] == 1
    assert second.output_ass.is_file() and second.output_srt.is_file()
    assert path.read_bytes() == expected


@pytest.mark.parametrize("stage", ["burn", "dub", "done"])
@pytest.mark.parametrize("relocate", [False, True])
def test_resume_rebuilds_existing_external_subtitles_from_verified_cues(job, stage, relocate):
    cfg, settings, calls, _, _ = job
    first = p.run(cfg, settings)
    expected = (first.output_srt.read_bytes(), first.output_ass.read_bytes())
    if relocate:
        cfg.output_srt = cfg.output_srt.with_name("other.srt")
    cfg.output_srt.write_bytes(b"unrelated SRT")
    cfg.output_srt.with_suffix(".ass").write_bytes(b"unrelated ASS")
    cfg.resume_from = stage
    result = p.run(cfg, settings)
    assert (result.output_srt.read_bytes(), result.output_ass.read_bytes()) == expected
    assert calls["asr"] == 1


def test_subtitle_export_replace_failure_restores_existing_pair(job, monkeypatch):
    cfg, settings, _, _, _ = job
    first = p.run(cfg, settings)
    originals = {path: path.read_bytes() for path in
                 (first.output_srt, first.output_ass, cfg.work_dir / "subs.ass")}
    replace = Path.replace
    def fail_srt(path, destination):
        if destination == cfg.output_srt:
            raise PermissionError("SRT is busy")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail_srt)
    cfg.resume_from = "render"
    with pytest.raises(PermissionError, match="SRT is busy"):
        p.run(cfg, settings)
    assert all(path.read_bytes() == data for path, data in originals.items())


@pytest.mark.parametrize("resume", ["render", None])
def test_work_subtitle_commit_failure_restores_external_pair(job, monkeypatch, resume):
    cfg, settings, _, _, _ = job
    settings.video.work_dir, cfg.work_dir = str(cfg.work_dir), Path("auto")
    first = p.run(cfg, settings)
    work_ass = first.report_path.parent / "subs.ass"
    originals = {path: path.read_bytes() for path in (first.output_srt, first.output_ass, work_ass)}
    cfg.subtitle_en_color = "#ABCDEF"
    cfg.resume_from = resume
    replace = Path.replace
    def fail_work_ass(path, destination):
        if destination == work_ass:
            raise PermissionError("cache ASS is busy")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail_work_ass)
    with pytest.raises(PermissionError, match="cache ASS is busy"):
        p.run(cfg, settings)
    assert all(path.read_bytes() == data for path, data in originals.items())


@pytest.mark.parametrize("missing", ["srt", "ass", "work_ass"])
def test_missing_subtitle_does_not_allow_resume_with_different_style(job, missing):
    cfg, settings, _, _, _ = job
    first = p.run(cfg, settings)
    path = {"srt": first.output_srt, "ass": first.output_ass,
            "work_ass": cfg.work_dir / "subs.ass"}[missing]
    path.unlink()
    cfg.subtitle_en_color = "#ABCDEF"
    cfg.resume_from = "burn"
    with pytest.raises(ValueError, match="render"):
        p.run(cfg, settings)
    assert not path.exists()


@pytest.mark.parametrize("fail_report", [False, True])
def test_reexport_emits_done_only_after_report_is_saved(job, monkeypatch, fail_report):
    cfg, settings, _, _, _ = job
    settings.video.work_dir, cfg.work_dir = str(cfg.work_dir), Path("auto")
    first = p.run(cfg, settings)
    previous = first.report_path.read_bytes()
    cfg.output_srt = cfg.output_srt.with_name("new.srt")
    replace = Path.replace
    def write_report(path, destination):
        if fail_report and destination == first.report_path:
            raise OSError("report disk error")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", write_report)
    progress = []
    saved_at_done = []
    def observe(stage, pct):
        progress.append((stage, pct))
        if stage == "done":
            saved_at_done.append(json.loads(first.report_path.read_text(encoding="utf-8"))["output_srt"])
    if fail_report:
        with pytest.raises(OSError, match="report disk error"):
            p.run(cfg, settings, on_progress=observe)
        assert ("done", 1.0) not in progress
        assert first.report_path.read_bytes() == previous
    else:
        assert p.run(cfg, settings, on_progress=observe).reused
        assert saved_at_done == [str(cfg.output_srt)]
        assert progress[-1] == ("done", 1.0)


@pytest.mark.parametrize("reuse", [False, True])
def test_final_state_write_failure_restores_previous_report(job, monkeypatch, reuse):
    cfg, settings, calls, _, _ = job
    if reuse:
        settings.video.work_dir, cfg.work_dir = str(cfg.work_dir), Path("auto")
    first = p.run(cfg, settings)
    previous_report = first.report_path.read_bytes()
    state_path = first.report_path.with_name("job_state.json")
    cfg.output_srt = cfg.output_srt.with_name("new.srt")
    replace = Path.replace
    previous_state = []
    def fail_state(path, destination):
        if (destination == state_path and json.loads(path.read_text(encoding="utf-8"))["stage"] == "done"
                and json.loads(first.report_path.read_text(encoding="utf-8"))["output_srt"] == str(cfg.output_srt)):
            previous_state.append(state_path.read_bytes())
            raise PermissionError("final state disk error")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail_state)
    with pytest.raises(PermissionError, match="final state disk error"):
        p.run(cfg, settings)
    assert first.report_path.read_bytes() == previous_report
    assert previous_state and state_path.read_bytes() == previous_state[-1]
    asr_before = calls["asr"]
    monkeypatch.setattr(Path, "replace", replace)
    cfg.resume_from = "done" if reuse else "burn"
    result = p.run(cfg, settings)
    assert calls["asr"] == asr_before
    assert json.loads(result.report_path.read_text(encoding="utf-8"))["output_srt"] == str(cfg.output_srt)


@pytest.mark.parametrize("reuse", [False, True])
def test_stop_after_last_output_hash_does_not_save_completion(job, monkeypatch, reuse):
    cfg, settings, _, _, _ = job
    if reuse:
        settings.video.work_dir, cfg.work_dir = str(cfg.work_dir), Path("auto")
    first = p.run(cfg, settings)
    previous_report = first.report_path.read_bytes()
    cfg.output_srt = cfg.output_srt.with_name("new.srt")
    control = JobControl()
    digest = p.file_digest
    def stop_after_hash(path, **kwargs):
        result = digest(path, **kwargs)
        if path == cfg.output_srt.with_suffix(".ass"):
            control.stop()
        return result
    monkeypatch.setattr(p, "file_digest", stop_after_hash)
    progress = []
    with pytest.raises(JobStopped):
        p.run(cfg, settings, control=control, on_progress=lambda s, pct: progress.append((s, pct)))
    assert first.report_path.read_bytes() == previous_report
    assert ("done", 1.0) not in progress
    state = json.loads(first.report_path.with_name("job_state.json").read_text(encoding="utf-8"))
    assert state["stage"] == "stopped" and state["stopped"]


def test_first_completion_failure_does_not_leave_a_success_report(job, monkeypatch):
    cfg, settings, _, _, _ = job
    state_path = cfg.work_dir / "job_state.json"
    replace = Path.replace
    def fail_state(path, destination):
        if destination == state_path and json.loads(path.read_text(encoding="utf-8"))["stage"] == "done":
            raise PermissionError("first completion failed")
        return replace(path, destination)
    monkeypatch.setattr(Path, "replace", fail_state)
    with pytest.raises(PermissionError, match="first completion failed"):
        p.run(cfg, settings)
    assert not (cfg.work_dir / "report.json").exists()
    assert json.loads(state_path.read_text(encoding="utf-8"))["completed_stage"] == "render"
    assert not list(cfg.work_dir.glob(".subflow-*.tmp"))


def test_stop_once_completion_replace_starts_finishes_consistent_pair(job, monkeypatch):
    cfg, settings, _, _, _ = job
    control = JobControl()
    replace = Path.replace
    def stop_at_commit(path, destination):
        result = replace(path, destination)
        if destination == cfg.work_dir / "report.json":
            control.stop()
        return result
    monkeypatch.setattr(Path, "replace", stop_at_commit)
    result = p.run(cfg, settings, control=control)
    state = json.loads(result.report_path.with_name("job_state.json").read_text(encoding="utf-8"))
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert control.is_stopped()
    assert state["stage"] == report["last_stage"] == "done"
    assert state["job_id"] == report["job_id"] == result.job_id
    assert not state["stopped"] and not report["stopped"] and not state["paused"]


def test_cached_movie_export_cancels_before_replacing_existing_movie(tmp_path, monkeypatch):
    from bilingual_sub.core.control import JobControl

    previous, destination = tmp_path / "previous.mp4", tmp_path / "new.mp4"
    previous.write_bytes(b"video" * 1024 * 1024)
    destination.write_bytes(b"complete old movie")
    cfg = JobConfig(tmp_path / "input.mp4", destination, tmp_path / "out.srt", tmp_path,
                    source_lang="zh", target_lang="zh", burn=True)
    monkeypatch.setattr(p, "_style_same", lambda *a: True)
    class CancelDuringCopy(JobControl):
        calls = 0
        def wait_if_paused(self):
            self.calls += 1
            if self.calls == 3:
                self.stop()
            super().wait_if_paused()
    with pytest.raises(JobStopped):
        p._copy_or_burn(cfg, tmp_path, AppSettings(), {"output_mp4": str(previous),
                        "output_video_sha256": p.file_digest(previous)},
                        control=CancelDuringCopy())
    assert destination.read_bytes() == b"complete old movie"
    assert not list(tmp_path.glob(".subflow-output-*.tmp"))
