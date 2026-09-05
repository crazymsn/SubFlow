from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from bilingual_sub.adapters.procwin import hidden_run_kwargs

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


def run_cmd(args: list[str], *, check: bool = True, control=None) -> subprocess.CompletedProcess[str]:
    logger.debug("run: %s", " ".join(args))
    if control is None:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **hidden_run_kwargs(),
        )
        if check and proc.returncode != 0:
            raise FfmpegError(proc.stderr.strip() or proc.stdout.strip() or "ffmpeg failed")
        return proc

    control.check()
    popen = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_run_kwargs(),
    )
    out, err = control.run_attached(popen)
    code = 0 if popen.returncode is None else popen.returncode
    if check and code != 0:
        raise FfmpegError((err or "").strip() or (out or "").strip() or "ffmpeg failed")
    return subprocess.CompletedProcess(args, code, out, err)


def ffmpeg_version() -> str:
    proc = run_cmd([find_ffmpeg(), "-version"])
    line = proc.stdout.splitlines()[0] if proc.stdout else ""
    return line


def has_nvenc() -> bool:
    try:
        proc = run_cmd([find_ffmpeg(), "-hide_banner", "-encoders"])
    except Exception:
        return False
    return "h264_nvenc" in (proc.stdout or "")


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
        if candidate is not None and candidate not in ("N/A", ""):
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


def is_pcm_wav(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 44:
        return False
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getnframes() <= 0:
                return False
            remaining = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
            while remaining > 0:
                block = wav.readframes(65536)
                if not block:
                    return False
                remaining -= len(block)
            return remaining == 0
    except (OSError, wave.Error, EOFError):
        return False


def to_pcm_wav(src: Path, dest: Path | None = None, *, control=None) -> Path:
    """Decode any ffmpeg audio into 16-bit PCM WAV for Windows playback."""
    src = Path(src)
    dest = Path(dest) if dest is not None else src.with_name(src.stem + ".pcm.wav")
    if dest.resolve() == src.resolve() and is_pcm_wav(src):
        return src
    dest.parent.mkdir(parents=True, exist_ok=True)
    # FFmpeg cannot decode into its own input. Publish only a complete WAV.
    with tempfile.NamedTemporaryFile(suffix=".wav", prefix=".decode-", dir=dest.parent, delete=False) as tmp:
        part = Path(tmp.name)
    try:
        run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "24000",
            "-c:a",
            "pcm_s16le",
            str(part),
        ]
            , control=control,
        )
        if not is_pcm_wav(part):
            raise FfmpegError(f"cannot decode preview audio: {src}")
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)
    return dest


def remux_to_mp4(src: Path, dest: Path) -> Path:
    """Prefer stream copy into MP4; transcode only if the container rejects the codecs."""
    if src.suffix.lower() == ".mp4" and src.resolve() == dest.resolve():
        return src
    dest.parent.mkdir(parents=True, exist_ok=True)
    copy_args = [
        find_ffmpeg(),
        "-y",
        "-i",
        str(src),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    try:
        run_cmd(copy_args)
        if dest.is_file() and dest.stat().st_size > 32:
            return dest
    except FfmpegError:
        logger.info("stream copy to mp4 failed, transcoding %s", src)
    run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(src),
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    return dest


def copy_to_ascii_workdir(src: Path, work_dir: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    dst = work_dir / "source.mp4"
    if dst.resolve() != src.resolve():
        shutil.copy2(src, dst)
    return dst
