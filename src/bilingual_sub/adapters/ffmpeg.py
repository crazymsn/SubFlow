from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class FfmpegError(RuntimeError):
    pass


def _bundled_exe(name: str) -> str | None:
    names = [name] if sys.platform != "win32" else [f"{name}.exe", name]
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass))
    for root in roots:
        for n in names:
            cand = root / n
            if cand.is_file():
                return str(cand)
    return None


def find_ffmpeg() -> str:
    bundled = _bundled_exe("ffmpeg")
    if bundled:
        return bundled
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FfmpegError("ffmpeg not found in PATH")
    return exe


def find_ffprobe() -> str:
    bundled = _bundled_exe("ffprobe")
    if bundled:
        return bundled
    exe = shutil.which("ffprobe")
    if not exe:
        raise FfmpegError("ffprobe not found in PATH")
    return exe


def run_cmd(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    logger.debug("run: %s", " ".join(args))
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise FfmpegError(proc.stderr.strip() or proc.stdout.strip() or "ffmpeg failed")
    return proc


def ffmpeg_version() -> str:
    proc = run_cmd([find_ffmpeg(), "-version"])
    line = proc.stdout.splitlines()[0] if proc.stdout else ""
    return line


def has_nvenc() -> bool:
    proc = run_cmd([find_ffmpeg(), "-hide_banner", "-encoders"])
    return "h264_nvenc" in proc.stdout


def probe_video(path: Path) -> dict[str, int | float | bool]:
    """Read width/height/duration/has_audio for any container ffmpeg can open."""
    proc = run_cmd(
        [
            find_ffprobe(),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise FfmpegError(f"cannot probe video: {path}") from exc

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise FfmpegError(f"no video stream: {path}")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width <= 0 or height <= 0:
        raise FfmpegError(f"invalid video size: {path}")

    duration = 0.0
    for candidate in (video.get("duration"), (data.get("format") or {}).get("duration")):
        if candidate not in (None, "N/A", ""):
            try:
                duration = float(candidate)
                if duration > 0:
                    break
            except (TypeError, ValueError):
                continue

    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    return {"width": width, "height": height, "duration": duration, "has_audio": has_audio}


def parse_ffmpeg_major(version_line: str) -> int | None:
    import re

    m = re.search(r"ffmpeg version (\d+)", version_line, re.I)
    return int(m.group(1)) if m else None


def escape_subtitles_path(path: Path) -> str:
    """Escape path for ffmpeg subtitles filter on Windows."""
    s = path.resolve().as_posix()
    s = s.replace(":", r"\:")
    return s


def copy_to_ascii_workdir(src: Path, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    dst = work_dir / "source.mp4"
    if dst.resolve() != src.resolve():
        shutil.copy2(src, dst)
    return dst
