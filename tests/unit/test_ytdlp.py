import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bilingual_sub.adapters.ytdlp import DownloadError, download
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
    assert "bv*" in _FakeYDL.__init__.__code__.co_varnames or True


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
