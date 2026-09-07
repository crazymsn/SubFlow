import sys
from pathlib import Path

import pytest

from bilingual_sub.adapters import ytdlp


@pytest.mark.parametrize("folder", ["MacOS", "Frameworks"])
def test_frozen_runtime_works_without_shell_path(tmp_path, monkeypatch, folder):
    executable = tmp_path / "MacOS" / "SubFlow"
    binary = tmp_path / folder / ("node.exe" if sys.platform == "win32" else "node")
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"bundled runtime")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "Frameworks"), raising=False)
    # Even an old Node on the user's PATH must not replace the bundled version.
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: "/old/node")
    assert ytdlp.js_runtime_map()["node"]["path"] == str(binary)


def test_merger_receives_bundled_ffmpeg_without_path(tmp_path, monkeypatch):
    root = tmp_path / "Frameworks"
    root.mkdir()
    binary = root / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    binary.write_bytes(b"bundled ffmpeg")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MacOS" / "SubFlow"))
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    monkeypatch.setattr(ytdlp.shutil, "which", lambda name: None)
    opts = ytdlp.ydl_options(tmp_path / "download", "https://youtu.be/test", impersonate=False)
    assert Path(opts["ffmpeg_location"]) == binary
    from yt_dlp import YoutubeDL
    from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

    with YoutubeDL(opts) as downloader:
        assert FFmpegPostProcessor(downloader)._paths["ffmpeg"] == str(binary)


def test_mac_login_error_explains_plain_text_and_mac_path(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    message = ytdlp.explain_download_error(RuntimeError("Sign in to confirm you're not a bot"))
    assert "~/.config/subflow/Cookies/" in message
    assert ".rtf" in message
    assert "%APPDATA%" not in message


@pytest.mark.parametrize("error", ["ffmpeg is not installed", "n challenge solving failed"])
def test_component_errors_do_not_blame_cookie_expiry(error):
    message = ytdlp.explain_download_error(RuntimeError(error))
    assert "组件" in message
    assert "重新导出" not in message
