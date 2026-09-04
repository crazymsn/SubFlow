from __future__ import annotations

import logging
from collections.abc import Callable
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


class DownloadError(RuntimeError):
    pass


def is_bilibili_url(url: str) -> bool:
    text = (url or "").lower()
    return any(part in text for part in ("bilibili.com", "b23.tv", "bili2233.cn", "bilibili.tv"))


def is_youtube_url(url: str) -> bool:
    text = (url or "").lower()
    return any(part in text for part in ("youtube.com", "youtu.be", "youtube-nocookie.com", "music.youtube.com"))


def _referer(url: str) -> str:
    if is_bilibili_url(url):
        return "https://www.bilibili.com/"
    if is_youtube_url(url):
        return "https://www.youtube.com/"
    return "https://www.youtube.com/"


def ydl_options(
    dest_dir: Path,
    url: str,
    *,
    hook: Callable[[dict], None] | None = None,
    fmt: str = BEST_AV_FORMAT,
) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts: dict = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "format": fmt,
        "format_sort": ["res", "fps:60", "codec:h264:av01:vp9", "size"],
        "quiet": True,
        "noplaylist": True,
        "retries": 8,
        "fragment_retries": 8,
        "concurrent_fragment_downloads": 3,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
            "Referer": _referer(url),
        },
    }
    if hook:
        opts["progress_hooks"] = [hook]
    return opts


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
    for fmt in (BEST_AV_FORMAT, FALLBACK_AV_FORMAT):
        if control:
            control.wait_if_paused()
        try:
            with YoutubeDL(ydl_options(dest_dir, url, hook=hook, fmt=fmt)) as ydl:
                ydl.download([url])
        except JobStopped:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning("yt-dlp format %s failed: %s", fmt, exc)
            continue
        picked = _picked_file(dest_dir)
        if not picked:
            last_error = DownloadError("下载完成但没有找到视频文件")
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

    if last_error:
        log_path.write_text(str(last_error), encoding="utf-8")
        raise DownloadError(f"下载失败：{last_error}") from last_error
    raise DownloadError("下载失败：未能取得带声音的最高清视频")
