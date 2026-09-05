"""Real FFmpeg acceptance for long timelines, overlaps and trailing silence."""
import array
import math
import wave
from pathlib import Path

import pytest

from bilingual_sub.adapters.ffmpeg import find_ffmpeg, probe_video, run_cmd
from bilingual_sub.core.dub import mix_timeline


def test_many_clips_preserve_offsets_overlap_and_full_duration(tmp_path):
    ffmpeg = find_ffmpeg()
    video = tmp_path / "中文源视频.mp4"
    run_cmd([ffmpeg, "-y", "-f", "lavfi", "-i", "color=s=160x90:r=25:d=5",
             "-c:v", "libx264", str(video)])
    clip = tmp_path / "配音.wav"
    samples = array.array("h", [int(2000 * math.sin(i * 2 * math.pi * 440 / 48000))
                               for i in range(4800)])
    with wave.open(str(clip), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(samples.tobytes())
    # 25 simultaneous clips cross a batch boundary; all start at 1 second.
    clips = [(1.0, clip)] * 25 + [(2.0, clip)] * 24 + [(3.0, clip)] * 24
    out = tmp_path / "配音成片.mp4"
    mix_timeline(video, clips, out, 5)
    assert float(probe_video(out)["duration"]) == pytest.approx(5, abs=0.05)
    decoded = tmp_path / "decoded.wav"
    run_cmd([ffmpeg, "-y", "-i", str(out), "-vn", "-ac", "1", "-ar", "48000", str(decoded)])
    with wave.open(str(decoded), "rb") as wav:
        audio = array.array("h", wav.readframes(wav.getnframes()))
        assert wav.getnframes() / wav.getframerate() == pytest.approx(5, abs=0.05)
    def rms(start, end):
        chunk = audio[int(start * 48000):int(end * 48000)]
        return math.sqrt(sum(float(v) ** 2 for v in chunk) / len(chunk))
    for start in (1, 2, 3):
        assert rms(start + 0.02, start + 0.08) > 10000
    for start in (0.3, 1.5, 2.5, 3.5, 4.5):
        assert rms(start, start + 0.1) < 30


def test_thousand_long_paths_never_form_one_windows_command(tmp_path, monkeypatch):
    import subprocess

    commands = []
    graphs = []
    def capture(args, **kwargs):
        commands.append(args)
        graphs.append(Path(args[next(i for i, arg in enumerate(args) if arg in {"-filter_complex_script", "-/filter_complex"}) + 1]).read_text())
        Path(args[-1]).write_bytes(b"mixed")
    monkeypatch.setattr("bilingual_sub.core.dub.run_cmd", capture)
    clips = [(i * 0.1, tmp_path / ("a" * 150) / f"{i}.wav") for i in range(1200)]
    mix_timeline(tmp_path / "video.mp4", clips, tmp_path / "out.mp4", 125)
    assert len(commands) > 50
    assert all(args.count("-i") <= 25 for args in commands)
    assert all(len(subprocess.list2cmdline(args).encode("utf-16-le")) // 2 < 30000 for args in commands)
    assert "apad" in graphs[-1]


def test_mix_cancel_cleans_temporary_graph(tmp_path, monkeypatch):
    from bilingual_sub.core.control import JobStopped
    graphs = []
    def fail(args, **kwargs):
        graphs.append(Path(args[next(i for i, arg in enumerate(args) if arg in {"-filter_complex_script", "-/filter_complex"}) + 1]))
        raise JobStopped()
    monkeypatch.setattr("bilingual_sub.core.dub.run_cmd", fail)
    with pytest.raises(JobStopped):
        mix_timeline(tmp_path / "v.mp4", [(0, tmp_path / "a.wav")] * 25, tmp_path / "out.mp4", 5)
    assert graphs and not graphs[0].parent.exists()


@pytest.mark.parametrize("failure", ["cancel", "error", "empty", "stop_after_write"])
def test_failed_final_mix_preserves_previous_movie(tmp_path, monkeypatch, failure):
    from bilingual_sub.core.control import JobControl, JobStopped

    output = tmp_path / "complete.mp4"
    output.write_bytes(b"previous movie")
    control = JobControl()
    def fail(args, **kwargs):
        if failure != "empty":
            Path(args[-1]).write_bytes(b"partial movie")
        if failure == "cancel":
            raise JobStopped()
        if failure == "error":
            raise RuntimeError("encoder failed")
        if failure == "stop_after_write":
            control.stop()
    monkeypatch.setattr("bilingual_sub.core.dub.run_cmd", fail)
    with pytest.raises(RuntimeError):
        mix_timeline(tmp_path / "video.mp4", [(0, tmp_path / "clip.wav")], output, 2, control=control)
    assert output.read_bytes() == b"previous movie"
    assert not list(tmp_path.glob(".subflow-output-*"))


@pytest.mark.parametrize("protect", ["video", "clip"])
def test_mix_cannot_overwrite_its_inputs(tmp_path, monkeypatch, protect):
    video, clip = tmp_path / "video.mp4", tmp_path / "clip.wav"
    video.write_bytes(b"video")
    clip.write_bytes(b"audio")
    monkeypatch.setattr("bilingual_sub.core.dub.run_cmd", lambda *a, **kw: pytest.fail("must reject before FFmpeg"))
    with pytest.raises(ValueError, match="覆盖输入"):
        mix_timeline(video, [(0, clip)], video if protect == "video" else clip, 2)
    assert video.read_bytes() == b"video" and clip.read_bytes() == b"audio"
