import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from filelock import FileLock

from bilingual_sub.adapters import ytdlp
from bilingual_sub.adapters.ffmpeg import FfmpegError, remux_to_mp4
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.fixture
def fake_download(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.download_worker.run_download_worker", ytdlp._download_into)
    monkeypatch.setattr(ytdlp, "download_attempts", lambda url: iter([{}]))
    monkeypatch.setattr(ytdlp, "_audio_status", lambda path: True)
    monkeypatch.setattr(ytdlp, "_video_height", lambda path: 1080)
    monkeypatch.setattr(ytdlp, "ydl_options", lambda dest, url, **kw: {
        "outtmpl": str(dest / "source.%(ext)s"),
        "progress_hooks": [kw["hook"]] if kw.get("hook") else [],
    })

    class FakeYDL:
        def __init__(self, opts):
            self.params = opts

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def extract_info(self, url, download=False):
            return {"height": 1080}

        def download(self, urls):
            Path(self.params["outtmpl"] % {"ext": "mp4"}).write_bytes(b"new complete video")

    def install(cls):
        monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=cls))

    return FakeYDL, install


@pytest.mark.parametrize("stage", ["listing", "retry", "download_listing", "progress", "postprocess", "after_download"])
def test_cancel_at_download_boundaries_preserves_existing_files(tmp_path, fake_download, stage):
    base, install = fake_download
    ctl = JobControl()
    calls = []
    original = tmp_path / "source.mp4"
    original.write_bytes(b"original video")
    unrelated = tmp_path / "unrelated.part"
    unrelated.write_bytes(b"another task")

    class Cancelling(base):
        def extract_info(self, url, download=False):
            calls.append("list")
            if stage in {"listing", "retry"} or (stage == "download_listing" and len(calls) == 2):
                ctl.stop()
                if stage == "retry":
                    raise RuntimeError("request failed during stop")
            return super().extract_info(url, download)

        def download(self, urls):
            calls.append("download")
            super().download(urls)
            ctl.stop()
            if stage == "progress":
                self.params["progress_hooks"][0]({"status": "downloading"})
            elif stage == "postprocess":
                self.params["postprocessor_hooks"][0]({"status": "started"})

    install(Cancelling)
    with pytest.raises(JobStopped):
        ytdlp.download("https://example.invalid/video", tmp_path, control=ctl)
    assert original.read_bytes() == b"original video"
    assert unrelated.read_bytes() == b"another task"
    assert not list(tmp_path.glob(".subflow-download-*"))
    if stage in {"listing", "retry"}:
        assert calls == ["list"]
    if stage == "download_listing":
        assert calls == ["list", "list"]


def test_failed_attempt_is_not_reused_as_success(tmp_path, fake_download, monkeypatch):
    base, install = fake_download
    monkeypatch.setattr(ytdlp, "download_attempts", lambda url: iter([{}, {"clients": ("second",)}]))
    calls = []

    class Partial(base):
        def download(self, urls):
            calls.append(1)
            if len(calls) == 1:
                super().download(urls)
                raise RuntimeError("partial failure")
            # A broken downloader reports success but does not write anything.

    install(Partial)
    with pytest.raises(ytdlp.DownloadError):
        ytdlp.download("https://example.invalid/video", tmp_path)
    assert len(calls) == 2
    assert not (tmp_path / "source.mp4").exists()


def test_success_replaces_only_download_target(tmp_path, fake_download):
    base, install = fake_download
    install(base)
    (tmp_path / "source.mp4").write_bytes(b"old")
    (tmp_path / "source.ass").write_bytes(b"keep subtitle")
    (tmp_path / "other.part").write_bytes(b"keep partial")
    result = ytdlp.download("https://example.invalid/video", tmp_path)
    assert result.read_bytes() == b"new complete video"
    assert (tmp_path / "source.ass").read_bytes() == b"keep subtitle"
    assert (tmp_path / "other.part").read_bytes() == b"keep partial"


def test_download_directory_rejects_concurrent_writer(tmp_path, fake_download):
    base, install = fake_download
    install(base)
    with FileLock(str(tmp_path / ".download.lock")):
        with pytest.raises(ytdlp.DownloadError, match="正在下载"):
            ytdlp.download("https://example.invalid/video", tmp_path)
    assert not list(tmp_path.glob(".subflow-download-*"))


def test_paused_download_hook_waits_for_resume(tmp_path, fake_download):
    base, install = fake_download
    ctl = JobControl()
    paused, continued = threading.Event(), threading.Event()
    errors = []

    class Paused(base):
        def download(self, urls):
            ctl.pause()
            paused.set()
            self.params["progress_hooks"][0]({"status": "downloading"})
            continued.set()
            super().download(urls)

    install(Paused)
    def run():
        try:
            ytdlp.download("https://example.invalid/video", tmp_path, control=ctl)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert paused.wait(2)
        assert not continued.wait(0.1)
    finally:
        ctl.resume()
        worker.join(timeout=3)
    assert not worker.is_alive() and continued.is_set() and not errors


@pytest.mark.parametrize("failure,calls", [(FfmpegError("bad codec"), 2), (JobStopped(), 1)])
def test_remux_failure_or_stop_preserves_existing_target(tmp_path, monkeypatch, failure, calls):
    source, target = tmp_path / "video.webm", tmp_path / "source.mp4"
    source.write_bytes(b"source video")
    target.write_bytes(b"previous video")
    seen = []
    ctl = JobControl()
    def fail(args, **kwargs):
        seen.append(kwargs.get("control"))
        Path(args[-1]).write_bytes(b"partial output")
        raise failure
    monkeypatch.setattr("bilingual_sub.adapters.ffmpeg.run_cmd", fail)
    with pytest.raises(type(failure)):
        remux_to_mp4(source, target, control=ctl)
    assert seen == [ctl] * calls
    assert target.read_bytes() == b"previous video"
    assert source.read_bytes() == b"source video"
    assert not list(tmp_path.glob(".subflow-remux-*"))


def test_container_failure_is_reported_instead_of_returning_deleted_path(tmp_path, fake_download, monkeypatch):
    base, install = fake_download
    class Webm(base):
        def download(self, urls):
            Path(self.params["outtmpl"] % {"ext": "webm"}).write_bytes(b"webm")
    install(Webm)
    def fail(*args, **kwargs):
        raise FfmpegError("unsupported codec")
    monkeypatch.setattr("bilingual_sub.adapters.ffmpeg.remux_to_mp4", fail)
    with pytest.raises(ytdlp.DownloadError, match="MP4"):
        ytdlp.download("https://example.invalid/video", tmp_path)
    assert not (tmp_path / "source.mp4").exists()


@pytest.mark.parametrize("identifier", ["../../outside", "..\\outside", "C:\\outside", "CON", "NUL", "x" * 1000, "中文/文件"])
def test_download_folder_cannot_escape_root_or_exceed_component_limit(tmp_path, identifier):
    from urllib.parse import urlencode

    folder = ytdlp.download_folder("https://www.youtube.com/watch?" + urlencode({"v": identifier}), tmp_path)
    assert folder.resolve().parent == tmp_path.resolve()
    assert len(folder.name) <= 80
    folder.mkdir()
    assert folder.is_dir()


@pytest.mark.parametrize("url", [
    "https://notyoutube.com/watch?v=x", "https://youtube.com.evil.invalid/watch",
    "https://evil.invalid/?next=https://youtube.com/watch", "https://youtube.com@evil.invalid/video",
    "https://bilibili.com.evil.invalid/video", "https://evil.invalid/b23.tv/video",
])
def test_service_detection_uses_actual_host(url):
    assert not ytdlp.is_youtube_url(url)
    assert not ytdlp.is_bilibili_url(url)


def test_download_tls_certificates_are_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(ytdlp, "_impersonate", lambda: None)
    opts = ytdlp.ydl_options(tmp_path, "https://www.youtube.com/watch?v=x")
    assert not opts.get("nocheckcertificate", False)


def test_later_remux_failure_preserves_best_successful_attempt(tmp_path, fake_download, monkeypatch):
    base, install = fake_download
    monkeypatch.setattr(ytdlp, "download_attempts", lambda url: iter([{}, {"clients": ("second",)}]))
    calls = []
    class Mixed(base):
        def extract_info(self, url, download=False):
            return {"height": 2160}

        def download(self, urls):
            calls.append(1)
            if len(calls) == 1:
                super().download(urls)
            else:
                Path(self.params["outtmpl"] % {"ext": "webm"}).write_bytes(b"bad codec")
    install(Mixed)
    def fail(*args, **kwargs):
        raise FfmpegError("bad codec")
    monkeypatch.setattr("bilingual_sub.adapters.ffmpeg.remux_to_mp4", fail)
    result = ytdlp.download("https://example.invalid/video", tmp_path)
    assert result.read_bytes() == b"new complete video"
    assert len(calls) == 2


def test_remux_same_path_requires_existing_media(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError):
        remux_to_mp4(path, path)
