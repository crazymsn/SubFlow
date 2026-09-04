from pathlib import Path
from unittest.mock import MagicMock, patch

from bilingual_sub.core.dub import clamp_rate, dub_cues, mix_timeline
from bilingual_sub.models import Cue


def test_clamp_rate_bounds():
    assert clamp_rate(1.0, 1.0) == 1.0
    assert 0.90 <= clamp_rate(2.0, 1.0) <= 1.15
    assert 0.90 <= clamp_rate(0.5, 1.0) <= 1.15


def test_mix_timeline_uses_copy_video(tmp_path):
    video = tmp_path / "v.mp4"
    clip = tmp_path / "a.wav"
    out = tmp_path / "dub.mp4"
    video.write_bytes(b"v")
    clip.write_bytes(b"a")
    with patch("bilingual_sub.core.dub.find_ffmpeg", return_value="ffmpeg"):
        with patch("bilingual_sub.core.dub.run_cmd") as run:
            mix_timeline(video, [(0.2, clip)], out, 2.0)
    args = run.call_args[0][0]
    assert "-c:v" in args
    assert "copy" in args
    assert "-c:a" in args
    assert "aac" in args


def test_dub_cues_skips_empty_and_fits(tmp_path):
    class FakeTts:
        name = "fake"

        def available(self):
            return True

        def synth(self, req, *, control=None):
            req.dest.write_bytes(b"wav")
            return req.dest

    cues = [Cue(0.0, 1.0, "你好", "Hello"), Cue(1.0, 2.0, "", "")]
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    with patch("bilingual_sub.core.dub.fit_clip"):
        with patch("bilingual_sub.core.dub.mix_timeline") as mix:
            with patch("bilingual_sub.core.dub._audio_duration", return_value=1.0):
                out = tmp_path / "o-dub.mp4"
                dub_cues(
                    cues,
                    video=video,
                    work=tmp_path,
                    output=out,
                    provider=FakeTts(),
                    lang="en",
                    voice="alloy",
                    duration=2.0,
                )
    assert mix.called
    clips = mix.call_args[0][1]
    assert len(clips) == 1
