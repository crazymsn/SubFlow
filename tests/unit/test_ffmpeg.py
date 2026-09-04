from pathlib import Path

from bilingual_sub.adapters.ffmpeg import escape_subtitles_path, parse_ffmpeg_major


def test_escape_windows_path():
    p = escape_subtitles_path(Path("C:/Users/test/file.ass"))
    assert r"\:" in p


def test_parse_ffmpeg_major():
    assert parse_ffmpeg_major("ffmpeg version 8.1.1-essentials_build") == 8
    assert parse_ffmpeg_major("ffmpeg version 4.4") == 4
    assert parse_ffmpeg_major("not a version") is None
