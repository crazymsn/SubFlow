from unittest.mock import patch

from bilingual_sub.core.dub import clamp_rate, dub_cues, mix_timeline
from bilingual_sub.models import Cue


def test_clamp_rate_bounds():
    assert clamp_rate(1.0, 1.0) == 1.0
    assert clamp_rate(2.0, 1.0) == 2.0
    assert clamp_rate(0.5, 1.0) == 0.5
    assert clamp_rate(4.0, 1.0) == 2.0
    assert clamp_rate(0.1, 1.0) == 0.5


def test_atempo_chain_covers_long_lines():
    from bilingual_sub.core.dub import atempo_chain

    assert atempo_chain(1.0) == "atempo=1.0000"
    assert atempo_chain(2.0) == "atempo=2.0000"
    assert "atempo=2.0" in atempo_chain(3.0)
    assert atempo_chain(3.0).count("atempo=") == 2


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
    first = clips[0][1]
    assert first.name.endswith(".fit.wav")
    assert first.name.startswith("0000-")
    leftover = tmp_path / "tts" / "0000.wav"
    leftover.parent.mkdir(exist_ok=True)
    leftover.write_bytes(b"stale")
    with patch("bilingual_sub.core.dub.fit_clip"):
        with patch("bilingual_sub.core.dub.mix_timeline") as mix2:
            with patch("bilingual_sub.core.dub._audio_duration", return_value=1.0):
                dub_cues(
                    [Cue(0.0, 1.0, "你好", "Hello there")],
                    video=video,
                    work=tmp_path,
                    output=tmp_path / "o2-dub.mp4",
                    provider=FakeTts(),
                    lang="en",
                    voice="alloy",
                    duration=2.0,
                )
    second = mix2.call_args[0][1][0][1]
    assert second != first


def test_dub_cues_cache_invalidates_when_ref_audio_changes(tmp_path):
    class FakeTts:
        name = "gptsovits"

        def __init__(self, ref_audio: str):
            self.ref_audio = ref_audio
            self.endpoint = "http://127.0.0.1:9880"
            self.prompt_text = ""
            self.prompt_lang = "zh"

        def available(self):
            return True

        def synth(self, req, *, control=None):
            req.dest.write_bytes(self.ref_audio.encode())
            return req.dest

    def fake_fit(src, dest, target_sec, control=None):
        dest.write_bytes(src.read_bytes())

    cues = [Cue(0.0, 1.0, "你好", "Hello")]
    video = tmp_path / "v.mp4"
    video.write_bytes(b"v")
    with patch("bilingual_sub.core.dub.fit_clip", side_effect=fake_fit):
        with patch("bilingual_sub.core.dub.mix_timeline") as mix1:
            with patch("bilingual_sub.core.dub._audio_duration", return_value=1.0):
                dub_cues(
                    cues,
                    video=video,
                    work=tmp_path,
                    output=tmp_path / "a-dub.mp4",
                    provider=FakeTts("ref-a.wav"),
                    lang="en",
                    voice="",
                    duration=2.0,
                )
        with patch("bilingual_sub.core.dub.mix_timeline") as mix2:
            with patch("bilingual_sub.core.dub._audio_duration", return_value=1.0):
                dub_cues(
                    cues,
                    video=video,
                    work=tmp_path,
                    output=tmp_path / "b-dub.mp4",
                    provider=FakeTts("ref-b.wav"),
                    lang="en",
                    voice="",
                    duration=2.0,
                )
    first = mix1.call_args[0][1][0][1]
    second = mix2.call_args[0][1][0][1]
    assert first != second
    assert first.read_bytes() == b"ref-a.wav"
    assert second.read_bytes() == b"ref-b.wav"


def test_fit_cache_tracks_duration_and_reference_contents(tmp_path):
    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"speaker one")

    class Provider:
        name = "gptsovits"
        ref_audio = str(reference)
        def synth(self, req, **kwargs):
            req.dest.write_bytes(reference.read_bytes())
            return req.dest

    def fitted(src, dest, seconds, **kwargs):
        dest.write_bytes(src.read_bytes() + str(seconds).encode())

    def render(end):
        with patch("bilingual_sub.core.dub.mix_timeline") as mix:
            dub_cues([Cue(0, end, "你好", "Hello")], video=tmp_path / "v.mp4",
                     work=tmp_path, output=tmp_path / "out.mp4", provider=Provider(),
                     lang="en", voice="", duration=5)
            return mix.call_args.args[1][0][1]

    with patch("bilingual_sub.core.dub.fit_clip", side_effect=fitted):
        first = render(1)
        longer = render(2)
        assert first != longer
        assert longer.read_bytes().endswith(b"2")
        reference.write_bytes(b"speaker two")
        changed = render(2)
        assert changed != longer
        assert changed.read_bytes().startswith(b"speaker two")


def test_cancelled_fit_does_not_poison_cache(tmp_path):
    from bilingual_sub.core.control import JobStopped
    from bilingual_sub.core.dub import fit_clip

    dest = tmp_path / "fit.wav"
    def fail(args, **kwargs):
        from pathlib import Path
        Path(args[-1]).write_bytes(b"partial")
        raise JobStopped()
    import pytest
    with patch("bilingual_sub.core.dub._audio_duration", return_value=1):
        with patch("bilingual_sub.core.dub.run_cmd", side_effect=fail):
            with pytest.raises(JobStopped):
                fit_clip(tmp_path / "raw.wav", dest, 1)
    assert not dest.exists()
    assert not list(tmp_path.glob("*.part.wav"))
