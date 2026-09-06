import json

import pytest

from bilingual_sub import pipeline as p
from bilingual_sub.config import AppSettings
from bilingual_sub.core.langs import spoken_line
from bilingual_sub.core.translate import TranslateStats
from bilingual_sub.models import Cue, JobConfig, Segment


@pytest.mark.parametrize("target", ["zh", "zh-Hant", "en"])
def test_long_sentence_reaches_subtitles_dubbing_and_resume(
    tmp_path, monkeypatch, mock_sovits_runtime, target,
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original video")
    sentence = "这是一句需要从头到尾完整显示而不能只显示前八秒的中文台词"
    calls, translated, spoken = [], [], []

    def recognize(wav, **kwargs):
        calls.append("asr")
        segment = Segment(0, 20, sentence)
        kwargs["out_json"].write_text(json.dumps({"language": "zh", "segments": [segment.__dict__]},
                                               ensure_ascii=False), encoding="utf-8")
        return [segment]

    def translate(cues, **kwargs):
        assert target == "en" and kwargs["source_lang"] == "zh"
        calls.append("translate")
        translated.extend(c.zh for c in cues)
        return [Cue(c.start, c.end, c.zh, f"Translated part {i}.") for i, c in enumerate(cues)], TranslateStats(api_calls=1), []

    def dub(cues, *, lang, output, **kwargs):
        assert target == "en"
        calls.append("dub")
        spoken.extend((c.start, c.end, spoken_line(c, lang)) for c in cues)
        output.write_bytes(b"synthesized fixture")
        return output

    def select(*a, **k):
        assert target == "en", "Chinese variants must preserve the original audio"
        return object()

    monkeypatch.setattr(p, "probe_video", lambda path: {"duration": 20, "has_audio": True, "width": 640, "height": 360})
    monkeypatch.setattr(p, "extract_wav", lambda src, dest, **kwargs: dest.write_bytes(b"audio fixture"))
    monkeypatch.setattr(p, "detect_silences", lambda *a, **k: [])
    monkeypatch.setattr(p, "transcribe", recognize)
    monkeypatch.setattr(p, "translate_cues", translate)
    monkeypatch.setattr(p, "dub_cues", dub)
    monkeypatch.setattr("bilingual_sub.adapters.tts.select_tts", select)
    cfg = JobConfig(source, tmp_path / "result.mp4", tmp_path / "result.srt", tmp_path / "work",
                    burn=False, source_lang="zh", target_lang=target, subtitle_mode="single:" + target,
                    enable_dub=True, tts_provider="gptsovits")
    result = p.run(cfg, AppSettings())
    original = p.load_cues_json(cfg.work_dir / "cues.source.json")
    assert "".join(c.zh for c in original) == sentence
    assert original[0].start == 0 and original[-1].end == 20
    assert all(0 < c.end - c.start <= 8 for c in original)
    text = result.output_srt.read_text(encoding="utf-8")
    assert "00:00:20,000" in text
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    if target == "en":
        assert "".join(translated) == sentence
        assert spoken == [(c.start, c.end, f"Translated part {i}.") for i, c in enumerate(original)]
        assert calls == ["asr", "translate", "dub"] and report["dubbed"]
    else:
        assert calls == ["asr"] and not report["dubbed"] and result.output_dub is None
    previous_calls = list(calls)
    cfg.resume_from = "done"
    cfg.output_srt = tmp_path / "resumed.srt"
    resumed = p.run(cfg, AppSettings())
    assert resumed.output_srt.read_text(encoding="utf-8") == text
    assert calls == previous_calls and source.read_bytes() == b"original video"
