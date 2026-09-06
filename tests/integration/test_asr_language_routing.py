import json

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.config import AppSettings
from bilingual_sub.core.langs import job_translation_langs, token_required_for_job
from bilingual_sub.core.translate import TranslateStats
from bilingual_sub.models import Cue, JobConfig, Segment

SAMPLES = {
    "zh": "欢迎使用字幕工具。",
    "en": "Welcome to the subtitle application.",
    "es": "Hola, bienvenidos a esta prueba de subtítulos.",
    "fr": "Bonjour, bienvenue dans cette application.",
    "de": "Guten Tag, willkommen zu unserem Test.",
    "ru": "Добро пожаловать, проверяем API приложения.",
    "ja": "これは日本語の字幕です。",
}


@pytest.fixture
def pipeline_job(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original input video")
    cfg = JobConfig(source, tmp_path / "out.mp4", tmp_path / "out.srt", tmp_path / "work",
                    burn=False, enable_dub=True, tts_provider="gptsovits")
    monkeypatch.setattr(p, "probe_video", lambda path: {
        "duration": 2, "has_audio": True, "width": 640, "height": 360})
    monkeypatch.setattr(p, "extract_wav", lambda source, dest, **kwargs: dest.write_bytes(b"audio"))
    monkeypatch.setattr(p, "detect_silences", lambda *a, **k: [])
    def forbidden(*args, **kwargs):
        pytest.fail("same-language job must not translate or synthesize")
    monkeypatch.setattr(p, "translate_cues", forbidden)
    monkeypatch.setattr(p, "dub_cues", forbidden)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", forbidden)
    return cfg


@pytest.mark.parametrize("language", list(SAMPLES))
@pytest.mark.parametrize("declared", ["auto", "explicit"])
def test_same_language_uses_asr_metadata_and_preserves_original(pipeline_job, monkeypatch, language, declared):
    cfg = pipeline_job
    cfg.source_lang = language if declared == "explicit" else "auto"
    cfg.target_lang = language
    cfg.subtitle_mode = "single:" + language
    calls = []
    def recognize(wav, **kwargs):
        calls.append(kwargs["language"])
        segment = Segment(0.1, 1.8, SAMPLES[language])
        kwargs["out_json"].write_text(json.dumps({"language": language,
            "segments": [segment.__dict__]}, ensure_ascii=False), encoding="utf-8")
        return [segment]
    monkeypatch.setattr(p, "transcribe", recognize)
    first = p.run(cfg, AppSettings())
    report = json.loads(first.report_path.read_text(encoding="utf-8"))
    assert report["detected_spoken"] == language
    assert not report["dubbed"] and report["tts_provider"] == "none"
    assert not first.translated and report["translated"] is False
    assert first.output_dub is None and cfg.input_video.read_bytes() == b"original input video"
    cfg.resume_from = "done"
    cfg.output_srt = cfg.output_srt.with_name("resumed.srt")
    resumed = p.run(cfg, AppSettings())
    assert len(calls) == 1 and not resumed.translated
    assert json.loads(resumed.report_path.read_text(encoding="utf-8"))["translated"] is False


@pytest.mark.parametrize("language", ["en", "es", "fr", "de", "ru", "ja", "zh-Hant"])
def test_auto_same_screen_and_voice_defers_token_check(language):
    assert not token_required_for_job("auto", language, "single:" + language)


def test_different_screen_and_voice_still_requires_translation_token():
    assert token_required_for_job("auto", "en", "single:zh")
    assert token_required_for_job("auto", "zh", "single:en")
    assert token_required_for_job("auto", "en", "bilingual")


def test_detected_source_drives_subtitle_translation_even_without_dubbing():
    assert job_translation_langs("auto", "en", "single:zh", detected_spoken="en",
                                 cues=[Cue(0, 1, "Hello everyone")]) == ["zh"]


@pytest.mark.parametrize("language", ["es", "fr", "de", "ru"])
def test_non_english_source_pair_translates_both_languages(pipeline_job, monkeypatch, language):
    cfg = pipeline_job
    cfg.source_lang = "auto"
    cfg.target_lang = language
    cfg.subtitle_mode = "bilingual"
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, SAMPLES[language])
        kwargs["out_json"].write_text(json.dumps({"language": language,
            "segments": [segment.__dict__]}, ensure_ascii=False), encoding="utf-8")
        return [segment]
    calls = []
    def translate(cues, *, source_lang, target_lang, **kwargs):
        calls.append((source_lang, target_lang, [c.zh for c in cues]))
        output = "欢迎使用字幕工具。" if target_lang == "zh" else "Welcome to the subtitle application."
        return [Cue(c.start, c.end, c.zh, output) for c in cues], TranslateStats(api_calls=1), []
    monkeypatch.setattr(p, "transcribe", recognize)
    monkeypatch.setattr(p, "translate_cues", translate)
    result = p.run(cfg, AppSettings())
    assert sorted((src, dest) for src, dest, _texts in calls) == [(language, "en"), (language, "zh")]
    assert calls[0][2] == calls[1][2]
    # Cue construction normalizes punctuation before translation.
    assert SAMPLES[language].split(",")[0] in " ".join(calls[0][2])
    text = result.output_srt.read_text(encoding="utf-8")
    assert "欢迎" in text and "Welcome" in text
    assert SAMPLES[language] not in text
    assert not json.loads(result.report_path.read_text(encoding="utf-8"))["dubbed"]


def test_whisperx_detected_language_survives_alignment_metadata(pipeline_job, monkeypatch):
    from bilingual_sub.adapters.asr_protocol import AsrResult

    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "auto", "fr", "single:fr"
    cfg.asr_backend = "whisperx"
    class Backend:
        def available(self, **kwargs):
            return True
        def transcribe(self, wav, **kwargs):
            segment = Segment(0.1, 1.8, SAMPLES["fr"])
            kwargs["out_json"].write_text(json.dumps({"language": "en", "detected_language": "fr",
                "segments": [segment.__dict__]}), encoding="utf-8")
            return AsrResult("fr", [segment], detected_language="fr", backend="whisperx")
    monkeypatch.setattr(p, "WhisperXBackend", Backend)
    result = p.run(cfg, AppSettings())
    assert json.loads(result.report_path.read_text(encoding="utf-8"))["detected_spoken"] == "fr"
    assert not result.translated and result.output_dub is None


def test_auto_english_voice_with_chinese_subtitles_translates_screen_only(pipeline_job, monkeypatch):
    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "auto", "en", "single:zh"
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, SAMPLES["en"])
        kwargs["out_json"].write_text(json.dumps({"language": "en", "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]
    calls = []
    def translate(cues, **kwargs):
        calls.append((kwargs["source_lang"], kwargs["target_lang"]))
        return [Cue(c.start, c.end, c.zh, "欢迎使用字幕工具。") for c in cues], TranslateStats(api_calls=1), []
    monkeypatch.setattr(p, "transcribe", recognize)
    monkeypatch.setattr(p, "translate_cues", translate)
    result = p.run(cfg, AppSettings())
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert calls == [("en", "zh")]
    assert result.translated and report["translated"] and not report["dubbed"]
    assert "欢迎" in result.output_srt.read_text(encoding="utf-8")


@pytest.mark.parametrize("metadata", [None, "", "  ", "auto", 123])
def test_empty_detected_language_falls_back_to_asr_language(pipeline_job, monkeypatch, metadata):
    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "auto", "fr", "single:fr"
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, SAMPLES["fr"])
        kwargs["out_json"].write_text(json.dumps({"language": "fr", "detected_language": metadata,
            "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]
    monkeypatch.setattr(p, "transcribe", recognize)
    result = p.run(cfg, AppSettings())
    assert json.loads(result.report_path.read_text(encoding="utf-8"))["detected_spoken"] == "fr"


@pytest.mark.parametrize("target", ["zh", "zh-Hant"])
def test_chinese_text_keeps_original_despite_stale_english_metadata(pipeline_job, monkeypatch, target):
    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "en", target, "single:" + target
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, SAMPLES["zh"])
        kwargs["out_json"].write_text(json.dumps({"language": "en", "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]
    monkeypatch.setattr(p, "transcribe", recognize)
    result = p.run(cfg, AppSettings())
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["detected_spoken"] == "zh" and not report["dubbed"] and not result.translated


def test_pair_with_third_voice_translates_original_audio_text(pipeline_job, monkeypatch, mock_sovits_runtime):
    from bilingual_sub.core.langs import spoken_line

    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "auto", "ko", "bilingual"
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, SAMPLES["ja"])
        kwargs["out_json"].write_text(json.dumps({"language": "ja", "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]
    calls, spoken = [], []
    def translate(cues, *, source_lang, target_lang, **kwargs):
        calls.append((source_lang, target_lang, [c.zh for c in cues]))
        output = {"zh": SAMPLES["zh"], "en": SAMPLES["en"], "ko": "안녕하세요"}[target_lang]
        return [Cue(c.start, c.end, c.zh, output) for c in cues], TranslateStats(api_calls=1), []
    def dub(cues, *, lang, output, **kwargs):
        spoken.extend(spoken_line(cue, lang) for cue in cues)
        output.write_bytes(b"synthesized fixture")
        return output
    monkeypatch.setattr(p, "transcribe", recognize)
    monkeypatch.setattr(p, "translate_cues", translate)
    monkeypatch.setattr(p, "dub_cues", dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *a, **k: object())
    result = p.run(cfg, AppSettings())
    assert {dest for _src, dest, _text in calls} == {"zh", "en", "ko"}
    assert all(src == "ja" and texts == [SAMPLES["ja"]] for src, _dest, texts in calls)
    assert spoken == ["안녕하세요"]
    assert "Welcome" in result.output_srt.read_text(encoding="utf-8")


@pytest.mark.parametrize("screen", ["fr", "de", "es"])
def test_pipeline_keeps_screen_translation_separate_from_japanese_voice(
    pipeline_job, monkeypatch, mock_sovits_runtime, screen,
):
    from bilingual_sub.core.langs import spoken_line

    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = "auto", "ja", "single:" + screen
    translations = {"fr": "Bonjour à tous", "de": "Hallo zusammen", "es": "Hola a todos", "ja": "こんにちは"}
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, SAMPLES["zh"])
        kwargs["out_json"].write_text(json.dumps({"language": "zh", "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]
    spoken = []
    def translate(cues, *, source_lang, target_lang, **kwargs):
        assert source_lang == "zh"
        return [Cue(c.start, c.end, c.zh, translations[target_lang]) for c in cues], TranslateStats(api_calls=1), []
    def dub(cues, *, lang, output, **kwargs):
        spoken.extend(spoken_line(cue, lang) for cue in cues)
        output.write_bytes(b"synthesized fixture")
        return output
    monkeypatch.setattr(p, "transcribe", recognize)
    monkeypatch.setattr(p, "translate_cues", translate)
    monkeypatch.setattr(p, "dub_cues", dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *a, **k: object())
    result = p.run(cfg, AppSettings())
    assert spoken == [translations["ja"]]
    assert translations[screen] in result.output_srt.read_text(encoding="utf-8")
    assert translations["ja"] not in result.output_srt.read_text(encoding="utf-8")
    cfg.resume_from = "done"
    cfg.output_srt = cfg.output_srt.with_name("resumed.srt")
    resumed = p.run(cfg, AppSettings())
    assert spoken == [translations["ja"]]
    assert translations[screen] in resumed.output_srt.read_text(encoding="utf-8")


@pytest.mark.parametrize("source", ["auto", "ja"])
def test_japanese_kanji_only_transcript_preserves_japanese_voice(pipeline_job, monkeypatch, source):
    cfg = pipeline_job
    cfg.source_lang, cfg.target_lang, cfg.subtitle_mode = source, "ja", "single:ja"
    original = "東京都交通局"
    def recognize(wav, **kwargs):
        segment = Segment(0.1, 1.8, original)
        kwargs["out_json"].write_text(json.dumps({"language": "ja", "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]
    monkeypatch.setattr(p, "transcribe", recognize)
    result = p.run(cfg, AppSettings())
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["detected_spoken"] == "ja" and not report["dubbed"] and not result.translated
    assert original in result.output_srt.read_text(encoding="utf-8")
