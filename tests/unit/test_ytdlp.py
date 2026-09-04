import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bilingual_sub.adapters.ytdlp import (
    BEST_AV_FORMAT,
    DownloadError,
    available_browsers,
    download,
    download_attempts,
    explain_download_error,
    is_bilibili_url,
    is_youtube_url,
    ydl_options,
)
from bilingual_sub.core.control import JobControl, JobStopped


class _FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        return None


def test_download_writes_source_mp4(tmp_path):
    dest = tmp_path / "source.mp4"
    dest.write_bytes(b"ok")
    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = _FakeYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        out = download("https://youtu.be/demo", tmp_path)
    assert out == dest
    assert "bestaudio" in BEST_AV_FORMAT
    assert "bestvideo" in BEST_AV_FORMAT


def test_download_stop_interrupts(tmp_path):
    ctl = JobControl()

    class StoppingYDL(_FakeYDL):
        def __init__(self, opts):
            super().__init__(opts)
            hook = opts["progress_hooks"][0]
            ctl.stop()
            hook({"status": "downloading", "total_bytes": 100, "downloaded_bytes": 10})

    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = StoppingYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        with pytest.raises(JobStopped):
            download("https://youtu.be/demo", tmp_path, control=ctl)


def test_download_missing_ytdlp(tmp_path, monkeypatch):
    import builtins

    real = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("missing")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(DownloadError):
        download("https://youtu.be/demo", tmp_path)


def test_format_keeps_audio_and_max_res(tmp_path):
    opts = ydl_options(tmp_path, "https://www.bilibili.com/video/BV1xx", fmt=BEST_AV_FORMAT)
    assert "bestaudio" in opts["format"]
    assert opts["merge_output_format"] == "mp4"
    assert opts["http_headers"]["Referer"].endswith("bilibili.com/")
    yt = ydl_options(tmp_path, "https://youtu.be/demo")
    assert yt["http_headers"]["Referer"].endswith("youtube.com/")
    assert yt["extractor_args"]["youtube"]["player_client"][0] == "android"
    assert "ios" in yt["extractor_args"]["youtube"]["player_client"]
    assert opts["http_headers"]["Origin"] == "https://www.bilibili.com"
    assert Path(opts["cookiefile"]).name == "buvid.cookies.txt"
    assert is_bilibili_url("https://b23.tv/abcd")
    assert is_youtube_url("https://www.youtube.com/watch?v=1")
    assert any(item.get("clients") == ("tv", "web_safari") for item in download_attempts("https://youtu.be/x"))
    assert any(item.get("cookiesfrombrowser") for item in download_attempts("https://youtu.be/x"))
    assert isinstance(available_browsers(), tuple)


def test_browser_cookie_fallback_skips_tv(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.available_browsers", lambda: ("firefox",))
    attempts = list(download_attempts("https://youtu.be/x"))
    cookie_ones = [item for item in attempts if item.get("cookiesfrombrowser")]
    assert cookie_ones
    assert all(item["cookiesfrombrowser"] == ("firefox",) for item in cookie_ones)
    assert all("tv" not in (item.get("clients") or ()) for item in cookie_ones)


def test_browser_cookie_fallback_when_none_detected(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.available_browsers", lambda: ())
    names = [
        item["cookiesfrombrowser"][0]
        for item in download_attempts("https://www.bilibili.com/video/BV1")
        if item.get("cookiesfrombrowser")
    ]
    assert names[:3] == ["firefox", "edge", "chrome"]


def test_youtube_bot_error_is_human():
    raw = (
        "ERROR: [youtube] uO0naZNsX8c: Sign in to confirm you're not a bot. "
        "Use --cookies-from-browser or --cookies for the authentication. "
        "See https://github.com/yt-dlp/yt-dlp/wiki/FAQ"
    )
    msg = explain_download_error(RuntimeError(raw))
    assert "YouTube" in msg
    assert "登录" in msg
    assert "cookies-from-browser" not in msg


def test_download_retries_after_bot_check(tmp_path):
    dest = tmp_path / "source.mp4"
    calls = {"n": 0}

    class FlakyYDL(_FakeYDL):
        def download(self, urls):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Sign in to confirm you're not a bot")
            dest.write_bytes(b"ok")

    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = FlakyYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        out = download("https://youtu.be/demo", tmp_path)
    assert out == dest
    assert calls["n"] >= 2
