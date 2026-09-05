"""Real subtitle burn; controlled ASR/translation/TTS inputs expose fitting errors."""

import json
import shutil
from pathlib import Path

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.adapters.ffmpeg import find_ffmpeg, probe_video, run_cmd
from bilingual_sub.config import AppSettings
from bilingual_sub.core.langs import spoken_line
from bilingual_sub.core.render import load_cues_json
from bilingual_sub.core.translate import TranslateStats
from bilingual_sub.models import Cue, JobConfig, Segment, WordSpan


def test_netflix_burn_resume_and_reexport_keep_complete_dub_sentences(tmp_path, monkeypatch):
    video = tmp_path / "input.mp4"
    run_cmd([find_ffmpeg(), "-y", "-f", "lavfi", "-i", "color=size=640x360:rate=25",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-t", "2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)])
    original = video.read_bytes()
    source = "中文原声必须保持完整。"
    target = ("This translated sentence must remain intact for speech synthesis, "
              "even when the subtitle needs several separate frames.")
    words = [WordSpan(0.2, 0.7, source[:5]), WordSpan(0.7, 1.8, source[5:])]

    def transcribe(wav, **kwargs):
        segments = [Segment(0.2, 1.8, source)]
        kwargs["out_json"].write_text(json.dumps({
            "language": "zh", "segments": [s.__dict__ for s in segments]}), encoding="utf-8")
        return segments

    def translate(cues, **kwargs):
        return [Cue(0.2, 1.8, source, target, words=words, spoken=target)], TranslateStats(), []

    speech_calls = []

    def dub(cues, **kwargs):
        speech_calls.append([(c.start, c.end, spoken_line(c, "en")) for c in cues])
        if len(speech_calls) == 1:
            raise RuntimeError("injected synthesis failure")
        shutil.copy2(kwargs["video"], kwargs["output"])
        return kwargs["output"]

    monkeypatch.setattr(p, "transcribe", transcribe)
    monkeypatch.setattr(p, "translate_cues", translate)
    monkeypatch.setattr(p, "dub_cues", dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", lambda *a, **k: object())
    settings = AppSettings()
    settings.video.work_dir = str(tmp_path / "jobs")
    cfg = JobConfig(video, tmp_path / "result.mp4", tmp_path / "out.srt", Path("auto"),
                    burn=True, subtitle_mode="netflix_single", source_lang="zh",
                    target_lang="en", enable_dub=True, tts_provider="edge")
    with pytest.raises(RuntimeError, match="injected synthesis failure"):
        p.run(cfg, settings)
    cfg.resume_from = "dub"
    result = p.run(cfg, settings)
    assert speech_calls == [[(0.2, 1.8, target)], [(0.2, 1.8, target)]]
    fitted = load_cues_json(result.report_path.parent / "cues.fitted.json")
    assert len(fitted) > 2
    assert "".join("".join(c.zh.split()) for c in fitted) == "".join(target.split())
    srt = cfg.output_srt.read_text(encoding="utf-8")
    assert source not in srt
    assert all(c.zh in srt for c in fitted)
    assert probe_video(result.output_mp4)["width"] == 640
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["subtitle_fit_warnings"]
    assert any("characters_per_second" in w["issues"] for w in report["subtitle_fit_warnings"])
    cfg.resume_from = None
    reused = p.run(cfg, settings)
    assert reused.reused and len(speech_calls) == 2
    assert cfg.output_srt.read_text(encoding="utf-8") == srt
    assert json.loads(reused.report_path.read_text(encoding="utf-8"))["subtitle_fit_warnings"] == report["subtitle_fit_warnings"]
    assert video.read_bytes() == original


@pytest.mark.parametrize("target,expected", [("zh", "汉语测试"), ("zh-Hant", "漢語測試")])
def test_chinese_single_line_keeps_original_voice_with_dubbing_enabled(tmp_path, monkeypatch, target, expected):
    video = tmp_path / "chinese.mp4"
    video.write_bytes(b"original video")
    source = "汉语测试，源视频选择简体或繁体中文都必须保留原声。"
    monkeypatch.setattr(p, "probe_video", lambda *a: {
        "duration": 4, "has_audio": True, "width": 640, "height": 360})
    monkeypatch.setattr(p, "extract_wav", lambda source, path, **k: path.write_bytes(b"audio"))
    monkeypatch.setattr(p, "detect_silences", lambda *a, **k: [])

    def transcribe(wav, **kwargs):
        segment = Segment(0.2, 3.8, source)
        kwargs["out_json"].write_text(json.dumps({
            "language": "zh", "segments": [segment.__dict__]}), encoding="utf-8")
        return [segment]

    def forbidden(*args, **kwargs):
        raise AssertionError("Chinese to Chinese must not translate or synthesize speech")

    monkeypatch.setattr(p, "transcribe", transcribe)
    monkeypatch.setattr(p, "translate_cues", forbidden)
    monkeypatch.setattr(p, "dub_cues", forbidden)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", forbidden)
    cfg = JobConfig(video, None, tmp_path / "out.srt", tmp_path / "work", burn=False,
                    subtitle_mode="netflix_single", source_lang="zh", target_lang=target,
                    enable_dub=True, tts_provider="gptsovits")
    result = p.run(cfg, AppSettings())
    srt = result.output_srt.read_text(encoding="utf-8")
    assert expected in srt
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["dubbed"] is False and result.output_dub is None
    assert video.read_bytes() == b"original video"
