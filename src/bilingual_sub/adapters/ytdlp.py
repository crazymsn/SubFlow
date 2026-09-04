from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.core.control import JobControl, JobStopped

logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    pass


def download(
    url: str,
    dest_dir: Path,
    *,
    on_progress: Callable[[str, float], None] | None = None,
    control: JobControl | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / "source.mp4"
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

    opts = {
        "outtmpl": str(dest_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "format": "bv*+ba/b",
        "quiet": True,
        "noplaylist": True,
        "progress_hooks": [hook],
    }
    try:
        with YoutubeDL(opts) as ydl:
            if control:
                control.wait_if_paused()
            ydl.download([url])
    except JobStopped:
        raise
    except Exception as exc:
        log_path.write_text(str(exc), encoding="utf-8")
        raise DownloadError(f"下载失败：{exc}") from exc

    if out.is_file():
        if on_progress:
            on_progress("ingest", 0.15)
        return out
    candidates = sorted(dest_dir.glob("source.*"))
    if not candidates:
        raise DownloadError("下载完成但没有找到视频文件")
    picked = candidates[0]
    if picked.suffix.lower() != ".mp4":
        target = dest_dir / "source.mp4"
        picked.replace(target)
        return target
    return picked
