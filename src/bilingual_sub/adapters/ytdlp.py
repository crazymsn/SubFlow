from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path

from bilingual_sub.core.control import JobControl, JobStopped

logger = logging.getLogger(__name__)

# Highest resolution video + a real audio track. Prefer MP4/AAC so ffmpeg can merge.
BEST_AV_FORMAT = (
    "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo+bestaudio/"
    "best[ext=mp4]/"
    "best"
)
FALLBACK_AV_FORMAT = "bestaudio+bestvideo/best"
BROWSERS = ("firefox", "edge", "safari", "chrome", "brave", "chromium")
_BROWSER_PATHS = {
    "firefox": (
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "/Applications/Firefox.app",
        "/usr/bin/firefox",
    ),
    "edge": (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Microsoft Edge.app",
    ),
    "safari": ("/Applications/Safari.app",),
    "chrome": (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app",
        "/usr/bin/google-chrome",
    ),
    "brave": (
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        "/Applications/Brave Browser.app",
    ),
    "chromium": (
        r"C:\Program Files\Chromium\Application\chrome.exe",
        "/Applications/Chromium.app",
        "/usr/bin/chromium",
    ),
}
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class DownloadError(RuntimeError):
    pass


def is_bilibili_url(url: str) -> bool:
    text = (url or "").lower()
    return any(part in text for part in ("bilibili.com", "b23.tv", "bili2233.cn", "bilibili.tv"))


def is_youtube_url(url: str) -> bool:
    text = (url or "").lower()
    return any(part in text for part in ("youtube.com", "youtu.be", "youtube-nocookie.com", "music.youtube.com"))


def canonicalize_url(url: str) -> str:
    text = (url or "").strip()
    return (
        text.replace("://m.bilibili.com/", "://www.bilibili.com/")
        .replace("://www.bilibili.tv/", "://www.bilibili.com/")
        .replace("://bilibili.tv/", "://www.bilibili.com/")
    )


def _referer(url: str) -> str:
    if is_bilibili_url(url):
        return "https://www.bilibili.com/"
    if is_youtube_url(url):
        return "https://www.youtube.com/"
    return "https://www.youtube.com/"


def _bilibili_guest_cookies(dest_dir: Path) -> Path:
    import uuid

    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "buvid.cookies.txt"
    buvid = str(uuid.uuid4()).upper()
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        f".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid3\t{buvid}\n"
        f".bilibili.com\tTRUE\t/\tFALSE\t0\tbuvid4\t{buvid}\n"
        ".bilibili.com\tTRUE\t/\tFALSE\t0\tCURRENT_FNVAL\t4048\n",
        encoding="utf-8",
    )
    return path


def available_browsers() -> tuple[str, ...]:
    """Browsers that look installed. Cookie fallback only opens these jars."""
    found: list[str] = []
    for name in BROWSERS:
        for raw in _BROWSER_PATHS.get(name, ()):
            try:
                if Path(raw).exists():
                    found.append(name)
                    break
            except OSError:
                continue
    return tuple(found)


def cookie_file() -> Path | None:
    env = (os.environ.get("SUBFLOW_COOKIES") or os.environ.get("YTDLP_COOKIES") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    try:
        from bilingual_sub.config import user_config_dir

        root = user_config_dir()
        candidates.extend((root / "cookies.txt", root / "youtube-cookies.txt", root / "bilibili-cookies.txt"))
    except Exception:
        pass
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 32:
                return path
        except OSError:
            continue
    return None


def _impersonate():
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except Exception:
        return None
    for spec in ("chrome-131", "chrome-124", "chrome-120", "chrome-110", "chrome"):
        try:
            return ImpersonateTarget.from_str(spec)
        except Exception:
            continue
    return None


def ydl_options(
    dest_dir: Path,
    url: str,
    *,
    hook: Callable[[dict], None] | None = None,
    fmt: str = BEST_AV_FORMAT,
    clients: tuple[str, ...] | None = None,
    cookiefile: Path | None = None,
    cookiesfrombrowser: tuple | None = None,
    impersonate: bool = True,
) -> dict:
    url = canonicalize_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "Referer": _referer(url),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if is_bilibili_url(url):
        headers["Origin"] = "https://www.bilibili.com"
        headers["Referer"] = "https://www.bilibili.com/"
        if cookiefile is None and not cookiesfrombrowser:
            cookiefile = _bilibili_guest_cookies(dest_dir)
    target = _impersonate() if impersonate else None
    if target is None:
        headers["User-Agent"] = CHROME_UA
    opts: dict = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "format": fmt,
        "format_sort": ["res", "fps:60", "codec:h264:av01:vp9", "size"],
        "quiet": True,
        "noplaylist": True,
        "retries": 8,
        "fragment_retries": 8,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 3,
        "socket_timeout": 30,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "http_headers": headers,
    }
    if is_youtube_url(url):
        opts["extractor_args"] = {
            "youtube": {
                "player_client": list(clients or ("android", "ios")),
            }
        }
    if target is not None:
        opts["impersonate"] = target
    if cookiefile is not None:
        opts["cookiefile"] = str(cookiefile)
    if cookiesfrombrowser:
        opts["cookiesfrombrowser"] = cookiesfrombrowser
    if hook:
        opts["progress_hooks"] = [hook]
    return opts


def download_attempts(url: str) -> Iterator[dict]:
    """Guest clients first, then the user's signed-in browser cookies."""
    cookie = cookie_file()
    browsers = available_browsers() or ("firefox", "edge", "chrome")
    if is_youtube_url(url):
        profiles: list[dict] = [
            {"clients": ("android", "ios"), "impersonate": True},
            {"clients": ("tv", "web_safari"), "impersonate": True},
            {"clients": ("web_safari",), "impersonate": True},
        ]
        if cookie:
            profiles.append(
                {"clients": ("web_safari", "android"), "cookiefile": cookie, "impersonate": True}
            )
        for browser in browsers:
            # Cookies + web/android only. Do not pair a logged-in jar with the TV client.
            profiles.append(
                {
                    "clients": ("web_safari", "android"),
                    "cookiesfrombrowser": (browser,),
                    "impersonate": True,
                }
            )
    elif is_bilibili_url(url):
        profiles = [{"impersonate": True}]
        if cookie:
            profiles.append({"cookiefile": cookie, "impersonate": True})
        for browser in browsers:
            profiles.append({"cookiesfrombrowser": (browser,), "impersonate": True})
    else:
        profiles = [{"impersonate": True}]
        if cookie:
            profiles.append({"cookiefile": cookie, "impersonate": True})
        for browser in browsers:
            profiles.append({"cookiesfrombrowser": (browser,), "impersonate": True})

    for profile in profiles:
        yield {**profile, "fmt": BEST_AV_FORMAT}
    for profile in profiles[:2]:
        yield {**profile, "fmt": FALLBACK_AV_FORMAT}


def explain_download_error(exc: BaseException) -> str:
    text = str(exc)
    low = text.lower()
    first = text.split("See https://", 1)[0].split("Also see https://", 1)[0].strip()
    if "412" in low and any(token in low for token in ("bilibili", "b23.tv", "precondition")):
        return (
            "B 站拦截了网页请求。已尝试读取本机浏览器登录 Cookie；"
            "请用已登录的浏览器打开 bilibili.com 后再点下载。"
        )
    if "not a bot" in low or "sign in to confirm" in low:
        return (
            "YouTube 拦截了游客下载。已尝试读取本机浏览器登录 Cookie；"
            "请用 Firefox 或 Edge 打开并登录 youtube.com 后再点下载。"
        )
    if any(token in low for token in ("bilibili", "b23.tv")) and any(
        token in low for token in ("412", "403", "login", "risk", "风控", "登录")
    ):
        return (
            "B 站拒绝了游客下载。请用浏览器登录 bilibili.com 后再试，"
            "或把 cookies.txt 放到本机配置目录。"
        )
    if "unsupported url" in low or "unable to extract" in low:
        return f"无法解析该链接：{first.splitlines()[0] if first else text}"
    if first:
        return f"下载失败：{first.splitlines()[0]}"
    return f"下载失败：{exc}"


def _picked_file(dest_dir: Path) -> Path | None:
    exact = dest_dir / "source.mp4"
    if exact.is_file():
        return exact
    candidates = sorted(p for p in dest_dir.glob("source.*") if p.is_file())
    return candidates[0] if candidates else None


def _ensure_mp4(path: Path, dest_dir: Path) -> Path:
    if path.suffix.lower() == ".mp4":
        return path
    target = dest_dir / "source.mp4"
    if path.resolve() != target.resolve():
        path.replace(target)
    return target


def _audio_status(path: Path) -> bool | None:
    try:
        from bilingual_sub.adapters.ffmpeg import probe_video

        return bool(probe_video(path).get("has_audio"))
    except Exception:
        return None


def download(
    url: str,
    dest_dir: Path,
    *,
    on_progress: Callable[[str, float], None] | None = None,
    control: JobControl | None = None,
) -> Path:
    url = canonicalize_url(url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    log_path = dest_dir / "ytdlp.log"
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise DownloadError("未安装 yt-dlp，请执行 pip install yt-dlp") from exc

    def hook(status: dict) -> None:
        if control:
            control.check()
        if on_progress and status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            frac = min(0.99, done / total) if total else 0.1
            on_progress("ingest", 0.05 + 0.10 * frac)

    last_error: Exception | None = None
    notes: list[str] = []
    for attempt in download_attempts(url):
        if control:
            control.wait_if_paused()
        label = (
            attempt.get("clients")
            or attempt.get("cookiesfrombrowser")
            or attempt.get("cookiefile")
            or "default"
        )
        if attempt.get("cookiesfrombrowser"):
            logger.info("download fallback: browser cookies %s", attempt["cookiesfrombrowser"])
        try:
            opts = ydl_options(
                dest_dir,
                url,
                hook=hook,
                fmt=str(attempt.get("fmt") or BEST_AV_FORMAT),
                clients=attempt.get("clients"),
                cookiefile=attempt.get("cookiefile"),
                cookiesfrombrowser=attempt.get("cookiesfrombrowser"),
                impersonate=bool(attempt.get("impersonate", True)),
            )
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
        except JobStopped:
            raise
        except Exception as exc:
            last_error = exc
            notes.append(f"{label}: {exc}")
            if attempt.get("cookiesfrombrowser"):
                logger.info("browser-cookie fallback %s failed: %s", label, exc)
            else:
                logger.warning("yt-dlp %s failed: %s", label, exc)
            continue
        picked = _picked_file(dest_dir)
        if not picked:
            last_error = DownloadError("下载完成但没有找到视频文件")
            notes.append(f"{label}: missing file")
            continue
        picked = _ensure_mp4(picked, dest_dir)
        audio = _audio_status(picked)
        if audio is False:
            last_error = DownloadError("下载的文件没有音轨，正在改用备用格式")
            logger.warning("downloaded %s has no audio, retrying", picked)
            try:
                picked.unlink(missing_ok=True)
            except OSError:
                pass
            continue
        if on_progress:
            on_progress("ingest", 0.15)
        return picked

    if notes:
        log_path.write_text("\n".join(notes), encoding="utf-8")
    if last_error:
        raise DownloadError(explain_download_error(last_error)) from last_error
    raise DownloadError("下载失败：未能取得带声音的最高清视频")
