import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bilingual_sub.adapters.ytdlp import (
    BEST_AV_FORMAT,
    ORIGINAL_AUDIO,
    HD_FLOOR,
    YT_SAFE_CLIENTS,
    DownloadError,
    StreamProgress,
    available_browsers,
    cookie_file,
    cookie_folder_dirs,
    cookie_search_dirs,
    js_runtime_map,
    youtube_cookie_is_guest,
    download,
    download_attempts,
    download_folder,
    download_fraction,
    explain_download_error,
    audio_track_kind,
    format_for_height,
    original_audio_format_id,
    prefer_audio_format,
    selected_audio_is_dubbed,
    is_bilibili_url,
    is_youtube_url,
    max_video_height,
    quality_target,
    selected_height,
    ydl_options,
)
from bilingual_sub.core.control import JobControl, JobStopped


class _FakeYDL:
    def __init__(self, opts):
        self.opts = opts
        self.params = opts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def download(self, urls):
        return None


def test_download_writes_source_mp4(tmp_path, monkeypatch):
    dest = tmp_path / "source.mp4"
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._video_height", lambda path: 1080)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._audio_status", lambda path: True)

    class WriteYDL(_FakeYDL):
        def download(self, urls):
            dest.write_bytes(b"ok")

    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = WriteYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        out = download("https://youtu.be/demo", tmp_path)
    assert out == dest
    assert "bv*" in BEST_AV_FORMAT
    assert "ba[format_note*=original]" in BEST_AV_FORMAT
    assert "protocol^=http" in BEST_AV_FORMAT


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


def test_format_keeps_audio_and_max_res(tmp_path, monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_file", lambda url=None: None)
    opts = ydl_options(tmp_path, "https://www.bilibili.com/video/BV1xx", fmt=BEST_AV_FORMAT)
    assert "bv*" in opts["format"]
    assert "ba[format_note*=original]" in opts["format"]
    assert opts["format_sort"][0] == "lang"
    assert "res" in opts["format_sort"]
    assert opts["format_sort_force"] is True
    assert opts["merge_output_format"] == "mp4"
    assert opts["http_headers"]["Referer"].endswith("bilibili.com/")
    yt = ydl_options(tmp_path, "https://youtu.be/demo")
    assert yt["http_headers"]["Referer"].endswith("youtube.com/")
    clients = yt["extractor_args"]["youtube"]["player_client"]
    assert yt["extractor_args"]["youtube"]["lang"][0] == "zh-CN"
    assert clients[0] == "default"
    assert "web_embedded" in clients
    assert "visionos" in clients
    assert "android" not in clients
    assert "tv" not in clients
    assert "-tv" in clients and "-tv_downgraded" in clients
    assert opts["http_headers"]["Origin"] == "https://www.bilibili.com"
    assert "node" in opts["js_runtimes"]
    assert "deno" in opts["js_runtimes"]
    assert "ejs:github" in opts["remote_components"]
    cookie_text = Path(opts["cookiefile"]).read_text(encoding="utf-8")
    assert "bili_locale" in cookie_text
    assert "zh-CN" in cookie_text
    assert is_bilibili_url("https://b23.tv/abcd")
    assert is_youtube_url("https://www.youtube.com/watch?v=1")
    yt_attempts = list(download_attempts("https://youtu.be/x"))
    assert yt_attempts[0].get("clients")[0] in ("default", "visionos")
    assert any("visionos" in (item.get("clients") or ()) for item in yt_attempts)
    for item in yt_attempts:
        used = item.get("clients") or ()
        assert "tv" not in used
        assert "tv_downgraded" not in used
    assert any(item.get("cookiesfrombrowser") for item in yt_attempts)
    assert isinstance(available_browsers(), tuple)


def test_download_fraction_uses_bytes_and_fragments():
    assert download_fraction({"status": "downloading", "total_bytes": 1000, "downloaded_bytes": 250}) == 0.25
    assert download_fraction({"status": "downloading", "fragment_index": 3, "fragment_count": 10}) == 0.2
    assert download_fraction({"status": "downloading", "_percent_str": " 42.0%"}) == 0.42
    assert download_fraction({"status": "finished"}) == 1.0
    assert download_fraction({"status": "downloading"}) is None


def test_cookie_search_prefers_project_cookies_dir():
    dirs = cookie_search_dirs()
    assert any(path.name == "Cookies" for path in dirs)


def test_cookie_folder_walks_parents(tmp_path, monkeypatch):
    repo = tmp_path / "SubFlow"
    dist = repo / "dist" / "SubFlow"
    cookies = repo / "Cookies"
    cookies.mkdir(parents=True)
    dist.mkdir(parents=True)
    (cookies / "bilibili-cookies.txt").write_text("# Netscape\n.bilibili.com\tTRUE\t/\tFALSE\t0\tSESSDATA\tx\n", encoding="utf-8")
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._project_root", lambda: dist)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_search_dirs", lambda: cookie_folder_dirs())
    monkeypatch.delenv("SUBFLOW_COOKIES", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES", raising=False)
    folders = cookie_folder_dirs()
    assert cookies.resolve() in [path.resolve() for path in folders]
    assert cookie_file("https://www.bilibili.com/video/BV1").resolve() == (cookies / "bilibili-cookies.txt").resolve()


def test_youtube_guest_cookie_is_skipped(tmp_path, monkeypatch):
    guest = tmp_path / "youtube-cookies.txt"
    guest.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tVISITOR_INFO1_LIVE\tabc\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tPREF\tf1=1\n",
        encoding="utf-8",
    )
    logged = tmp_path / "other" / "youtube-cookies.txt"
    logged.parent.mkdir()
    logged.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tLOGIN_INFO\tabc\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tSID\tdef\n",
        encoding="utf-8",
    )
    assert youtube_cookie_is_guest(guest) is True
    assert youtube_cookie_is_guest(logged) is False
    login_only = tmp_path / "login-only.txt"
    login_only.write_text(
        "# Netscape HTTP Cookie File\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tLOGIN_INFO\tabc\n"
        ".youtube.com\tTRUE\t/\tFALSE\t0\tVISITOR_INFO1_LIVE\tx\n",
        encoding="utf-8",
    )
    assert youtube_cookie_is_guest(login_only) is True
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_folder_dirs", lambda: [tmp_path])
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_search_dirs", lambda: [tmp_path])
    monkeypatch.delenv("SUBFLOW_COOKIES", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES", raising=False)
    assert cookie_file("https://youtu.be/x") is None
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_folder_dirs", lambda: [tmp_path, logged.parent])
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_search_dirs", lambda: [tmp_path, logged.parent])
    assert cookie_file("https://youtu.be/x") == logged


def test_js_runtime_map_enables_node_and_deno():
    runtimes = js_runtime_map()
    assert "node" in runtimes
    assert "deno" in runtimes


def test_site_cookie_file_prefers_named_jar(tmp_path, monkeypatch):
    monkeypatch.delenv("SUBFLOW_COOKIES", raising=False)
    monkeypatch.delenv("YTDLP_COOKIES", raising=False)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_folder_dirs", lambda: [tmp_path])
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_search_dirs", lambda: [tmp_path])
    (tmp_path / "cookies.txt").write_text("# generic\n" + "x" * 40, encoding="utf-8")
    (tmp_path / "youtube-cookies.txt").write_text("# yt\n" + "y" * 40, encoding="utf-8")
    (tmp_path / "bilibili-cookies.txt").write_text("# bili\n" + "z" * 40, encoding="utf-8")
    assert cookie_file("https://youtu.be/x").name == "youtube-cookies.txt"
    assert cookie_file("https://www.bilibili.com/video/BV1").name == "bilibili-cookies.txt"


def test_download_reports_standalone_percent(tmp_path, monkeypatch):
    dest = tmp_path / "source.mp4"
    seen: list[float] = []
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._video_height", lambda path: 1080)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._audio_status", lambda path: True)

    class ProgYDL(_FakeYDL):
        def download(self, urls):
            hook = self.opts["progress_hooks"][0]
            hook({"status": "downloading", "total_bytes": 1000, "downloaded_bytes": 400})
            dest.write_bytes(b"ok")
            hook({"status": "finished"})

    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = ProgYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        out = download(
            "https://youtu.be/demo",
            tmp_path,
            on_progress=lambda stage, pct: seen.append(pct),
            progress_range=(0.0, 1.0),
        )
    assert out == dest
    assert seen
    assert seen[-1] == 1.0
    for prev, cur in zip(seen, seen[1:]):
        assert cur + 1e-9 >= prev


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


def test_reload_error_is_human_and_not_doubled():
    raw = "ERROR: [youtube] u00naZNsX8c: The page needs to be reloaded."
    once = explain_download_error(RuntimeError(raw))
    twice = explain_download_error(DownloadError(once))
    assert once == twice
    assert once.count("下载失败") <= 1
    assert "可下载地址" in once
    stale = explain_download_error(RuntimeError("The provided YouTube account cookies are no longer valid."))
    assert "Cookie" in stale
    assert stale == explain_download_error(DownloadError(stale))


def test_download_retries_after_bot_check(tmp_path, monkeypatch):
    dest = tmp_path / "source.mp4"
    calls = {"n": 0}
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._video_height", lambda path: 1080)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._audio_status", lambda path: True)

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


def test_cookie_folder_beats_env_and_legacy(tmp_path, monkeypatch):
    folder = tmp_path / "Cookies"
    legacy = tmp_path / "legacy"
    folder.mkdir()
    legacy.mkdir()
    chosen = folder / "youtube-cookies.txt"
    chosen.write_text("# folder\n" + "a" * 40, encoding="utf-8")
    (legacy / "youtube-cookies.txt").write_text("# legacy\n" + "b" * 40, encoding="utf-8")
    env_jar = tmp_path / "env-cookies.txt"
    env_jar.write_text("# env\n" + "c" * 40, encoding="utf-8")
    monkeypatch.setenv("SUBFLOW_COOKIES", str(env_jar))
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_folder_dirs", lambda: [folder])
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_search_dirs", lambda: [folder, legacy])
    assert cookie_file("https://youtu.be/x") == chosen


def test_youtube_attempts_use_cookie_file_before_guest(tmp_path, monkeypatch):
    jar = tmp_path / "youtube-cookies.txt"
    jar.write_text("# yt\n" + "x" * 40, encoding="utf-8")
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_file", lambda url=None: jar)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.available_browsers", lambda: ("firefox",))
    attempts = list(download_attempts("https://youtu.be/x"))
    kinds = []
    for item in attempts:
        if item.get("cookiefile"):
            kinds.append("file")
        elif item.get("cookiesfrombrowser"):
            kinds.append("browser")
        else:
            kinds.append("guest")
    assert kinds[0] == "file"
    last_file = max(i for i, kind in enumerate(kinds) if kind == "file")
    first_guest = kinds.index("guest")
    assert last_file < first_guest
    for item in attempts:
        if item.get("cookiefile"):
            used = item.get("clients") or ()
            assert "android" not in used
            assert "tv" not in used
            assert used == YT_SAFE_CLIENTS or "visionos" in used


def test_format_pins_listed_max_height():
    assert "bv*" in BEST_AV_FORMAT
    assert format_for_height(2160).count("height>=2160") >= 2
    assert max_video_height(
        {
            "formats": [
                {"vcodec": "vp9", "acodec": "none", "height": 720, "url": "http://a"},
                {"vcodec": "vp9", "acodec": "none", "height": 2160, "url": "http://b"},
                {"vcodec": "vp9", "acodec": "none", "height": 4320},
                {"vcodec": "none", "acodec": "opus", "url": "http://c"},
            ]
        }
    ) == 2160


def test_progress_is_monotonic_across_video_then_audio():
    tracker = StreamProgress(expected=2)
    seen: list[float] = []
    events = (
        {"status": "downloading", "filename": "source.f313.webm", "total_bytes": 1000, "downloaded_bytes": 200},
        {"status": "downloading", "filename": "source.f313.webm", "total_bytes": 1000, "downloaded_bytes": 1000},
        {"status": "finished", "filename": "source.f313.webm"},
        {"status": "downloading", "filename": "source.f251.webm", "total_bytes": 400, "downloaded_bytes": 40},
        {"status": "downloading", "filename": "source.f251.webm", "total_bytes": 400, "downloaded_bytes": 400},
        {"status": "finished", "filename": "source.f251.webm"},
    )
    for event in events:
        value = tracker.feed(event)
        if value is not None:
            seen.append(value)
    assert seen
    for prev, cur in zip(seen, seen[1:]):
        assert cur + 1e-9 >= prev
    assert seen[0] < 0.3
    assert seen[-1] >= 0.99


def test_first_stream_finish_is_not_overall_100():
    tracker = StreamProgress(expected=2)
    mid = tracker.feed({"status": "finished", "filename": "source.f313.webm"})
    assert mid is not None
    assert mid <= 0.55


def test_download_keeps_going_until_listed_max(tmp_path, monkeypatch):
    dest = tmp_path / "source.mp4"
    heights = [720, 2160]

    class ListingYDL(_FakeYDL):
        def extract_info(self, url, download=False):
            return {
                "formats": [
                    {"vcodec": "vp9", "acodec": "none", "height": 2160, "url": "http://v"},
                    {"vcodec": "none", "acodec": "opus", "url": "http://a"},
                ],
                "requested_formats": [{}, {}],
            }

        def download(self, urls):
            dest.write_bytes(b"ok")

    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_file", lambda url=None: None)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._video_height", lambda path: heights.pop(0) if heights else 2160)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._audio_status", lambda path: True)
    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = ListingYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        out = download("https://youtu.be/demo", tmp_path)
    assert out == dest
    assert heights == []


def test_format_prefers_original_audio_over_dub():
    assert "format_note*=original" in ORIGINAL_AUDIO
    assert "language^=zh" in ORIGINAL_AUDIO
    assert "format_note*=original" in BEST_AV_FORMAT
    assert "format_note*=original" in format_for_height(2160)
    assert "ba[format_note!*=dub]" in ORIGINAL_AUDIO
    assert audio_track_kind({"format_note": "English (US) original", "acodec": "opus"}) == "original"
    assert audio_track_kind({"language_preference": 10, "acodec": "opus"}) == "original"
    assert audio_track_kind({"format_note": "English (US) (default), dubbed", "acodec": "opus"}) == "dubbed"
    info = {
        "requested_formats": [
            {"vcodec": "vp9", "acodec": "none", "height": 2160},
            {"vcodec": "none", "acodec": "opus", "format_note": "English (US) (default), dubbed", "format_id": "251-1"},
        ],
        "formats": [
            {"vcodec": "none", "acodec": "opus", "format_note": "中文 (中国) original", "format_id": "251-0", "abr": 160},
            {"vcodec": "none", "acodec": "opus", "format_note": "English (US) (default), dubbed", "format_id": "251-1", "abr": 160},
        ],
    }
    assert selected_audio_is_dubbed(info) is True
    assert original_audio_format_id(info) == "251-0"
    pinned = prefer_audio_format(info, 2160)
    assert "+251-0/" in pinned or pinned.startswith("bv*") and "251-0" in pinned
    clean = {
        "requested_formats": [
            {"vcodec": "none", "acodec": "opus", "format_note": "中文 (中国) original", "format_id": "251-0"},
        ]
    }
    assert selected_audio_is_dubbed(clean) is False
    assert prefer_audio_format(clean, 1080) == format_for_height(1080)


def test_download_replaces_dubbed_audio(tmp_path, monkeypatch):
    dest = tmp_path / "source.mp4"
    seen: dict[str, str] = {}

    class DubYDL(_FakeYDL):
        def extract_info(self, url, download=False):
            return {
                "formats": [
                    {"vcodec": "vp9", "acodec": "none", "height": 1080, "url": "http://v"},
                    {
                        "vcodec": "none",
                        "acodec": "opus",
                        "format_note": "中文 (中国) original",
                        "format_id": "251-0",
                        "abr": 160,
                        "url": "http://a0",
                    },
                    {
                        "vcodec": "none",
                        "acodec": "opus",
                        "format_note": "English (US) (default), dubbed",
                        "format_id": "251-1",
                        "abr": 160,
                        "url": "http://a1",
                    },
                ],
                "requested_formats": [
                    {"vcodec": "vp9", "acodec": "none", "height": 1080},
                    {
                        "vcodec": "none",
                        "acodec": "opus",
                        "format_note": "English (US) (default), dubbed",
                        "format_id": "251-1",
                    },
                ],
                "height": 1080,
            }

        def download(self, urls):
            seen["format"] = str(self.params.get("format") or "")
            dest.write_bytes(b"ok")

    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_file", lambda url=None: None)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._video_height", lambda path: 1080)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._audio_status", lambda path: True)
    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = DubYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        out = download("https://youtu.be/demo", tmp_path)
    assert out == dest
    assert "251-0" in seen["format"]


def test_format_pins_https_at_listed_height():
    text = format_for_height(2160)
    assert "height>=2160" in text
    assert "protocol^=http" in text
    assert text.endswith("b[height>=2160]")
    assert not text.endswith("/b")
    assert "protocol^=http" in BEST_AV_FORMAT
    assert quality_target(0) == HD_FLOOR
    assert quality_target(2160) == 2160
    assert "height>=1080" in format_for_height(0)
    assert selected_height({"requested_formats": [{"vcodec": "vp9", "height": 360}], "height": 360}) == 360


def test_low_res_selection_is_skipped_and_not_saved(tmp_path, monkeypatch):
    dest = tmp_path / "source.mp4"

    class LowYDL(_FakeYDL):
        def extract_info(self, url, download=False):
            return {
                "formats": [
                    {"vcodec": "vp9", "acodec": "none", "height": 2160, "url": "http://v"},
                    {"vcodec": "avc1", "acodec": "none", "height": 360, "url": "http://l"},
                ],
                "requested_formats": [{"vcodec": "avc1", "height": 360, "url": "http://l"}],
                "height": 360,
            }

        def download(self, urls):
            dest.write_bytes(b"360p")

    monkeypatch.setattr("bilingual_sub.adapters.ytdlp.cookie_file", lambda url=None: None)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._video_height", lambda path: 360)
    monkeypatch.setattr("bilingual_sub.adapters.ytdlp._audio_status", lambda path: True)
    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = LowYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        with pytest.raises(DownloadError, match="最高清|低清晰度|已跳过"):
            download("https://youtu.be/demo", tmp_path)
    assert not dest.exists()


def test_download_folder_uses_video_id():
    root = Path("/tmp/subflow-dl")
    assert download_folder("https://www.youtube.com/watch?v=u00naZNsX8c", root).name == "u00naZNsX8c"
    assert download_folder("https://youtu.be/dQw4w9wgWcQ", root).name == "dQw4w9wgWcQ"


def test_stale_source_is_not_treated_as_success(tmp_path):
    stale = tmp_path / "source.mp4"
    stale.write_bytes(b"old-360p")
    fake = type(sys)("yt_dlp")
    fake.YoutubeDL = _FakeYDL
    with patch.dict(sys.modules, {"yt_dlp": fake}):
        with pytest.raises(DownloadError):
            download("https://youtu.be/demo", tmp_path)


def test_hls_fragments_do_not_spike_the_bar():
    tracker = StreamProgress(expected=1)
    seen: list[float] = []
    for index in range(1, 21):
        value = tracker.feed(
            {
                "status": "downloading",
                "filename": f"source.mp4.part-Frag{index}",
                "fragment_index": index,
                "fragment_count": 20,
                "info_dict": {"format_id": "625"},
            }
        )
        if value is not None:
            seen.append(value)
    assert seen
    assert seen[0] <= 0.15
    assert 0.85 <= seen[-1] <= 0.999
    for prev, cur in zip(seen, seen[1:]):
        assert cur + 1e-9 >= prev
    early = StreamProgress(expected=2)
    last = 0.0
    for index in range(1, 4):
        last = early.feed(
            {
                "status": "downloading",
                "filename": f"source.f625.mp4.part-Frag{index}",
                "fragment_index": index,
                "fragment_count": 80,
                "info_dict": {"format_id": "625"},
            }
        ) or last
    assert last < 0.2
