from pathlib import Path

from bilingual_sub.core import audio


def test_invalid_silence_records_do_not_corrupt_valid_spans(monkeypatch):
    lines = [
        "silence_start:", "silence_start: nan", "silence_start: -1", "silence_end: 1",
        "silence_start: 2", "silence_end: inf", "silence_end: broken", "silence_end: 1",
        "silence_end: 3 | silence_duration: 1", "silence_end: 4", "silence_start: 8",
        "silence_start: 10", "silence_end: 11", "silence_start: 20",
    ]
    def emit(args, stderr_callback, **kwargs):
        for line in lines:
            stderr_callback(line)
    monkeypatch.setattr(audio, "run_cmd", emit)
    monkeypatch.setattr(audio, "find_ffmpeg", lambda: "ffmpeg")
    assert audio.detect_silences(Path("audio.wav")) == [(2, 3), (10, 11)]
