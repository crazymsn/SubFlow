from pathlib import Path
from unittest.mock import MagicMock, patch

from bilingual_sub.core.audio import detect_silences, extract_wav
from bilingual_sub.core.burn import burn_subtitles
from bilingual_sub.core.cues import long_internal_silence, split_by_punct
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.render import load_cues_json, save_cues_json
from bilingual_sub.models import Cue


def test_detect_silences_parses_stderr():
    mock_proc = MagicMock()
    mock_proc.stderr = (
        "silence_start: 1.5\n"
        "silence_end: 2.0 | silence_duration: 0.5\n"
        "silence_start: 5.0\n"
        "silence_end: 5.8 | silence_duration: 0.8\n"
    )
    with patch("bilingual_sub.core.audio.run_cmd", return_value=mock_proc):
        out = detect_silences(Path("x.wav"))
    assert out == [(1.5, 2.0), (5.0, 5.8)]


def test_extract_wav_calls_ffmpeg(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    wav = tmp_path / "speech.wav"
    with patch("bilingual_sub.core.audio.run_cmd") as m:
        extract_wav(video, wav, preview_sec=30.0)
    args = m.call_args[0][0]
    assert "-t" in args
    assert "30.0" in args
    assert "aresample=async=1:first_pts=0" in args


def test_burn_subtitles_builds_filter(tmp_path):
    video = tmp_path / "v.mp4"
    ass = tmp_path / "s.ass"
    out = tmp_path / "o.mp4"
    video.touch()
    ass.write_text("[Script Info]", encoding="utf-8")
    with (
        patch("bilingual_sub.core.burn.run_cmd", side_effect=lambda args, **kw: Path(args[-1]).write_bytes(b"encoded")) as m,
        patch("bilingual_sub.core.burn.has_nvenc", return_value=False),
    ):
        burn_subtitles(video, ass, out)
    args = m.call_args[0][0]
    vf = args[args.index("-vf") + 1]
    assert "setpts=PTS-STARTPTS" in vf
    assert "subtitles=" in vf
    assert "-c:a" in args and "aac" in args
    assert "libx264" in args
    assert "veryfast" in args


def test_glossary_load_from_yaml(tmp_path):
    p = tmp_path / "g.yaml"
    p.write_text(
        "replacements:\n  - from: foo\n    to: bar\nregex:\n  - pattern: 'a+'\n    replace: 'A'\n",
        encoding="utf-8",
    )
    g = Glossary.load(p)
    assert g.correct("foo aaa") == "bar A"


def test_glossary_load_missing():
    g = Glossary.load(Path("/nonexistent/glossary.yaml"))
    assert g.correct("x") == "x"


def test_split_by_punct_merges_short_parts():
    out = split_by_punct(0.0, 4.0, "短句，另一句也很短")
    assert len(out) >= 1


def test_long_internal_silence():
    silences = [(2.0, 2.8)]
    hits = long_internal_silence(1.0, 4.0, silences, threshold=0.55)
    assert hits == [(2.0, 2.8)]


def test_cues_json_roundtrip(tmp_path):
    cues = [Cue(1.0, 2.0, "测试", "test")]
    p = tmp_path / "cues.json"
    save_cues_json(cues, p)
    loaded = load_cues_json(p)
    assert loaded[0].zh == "测试"
    assert loaded[0].en == "test"
