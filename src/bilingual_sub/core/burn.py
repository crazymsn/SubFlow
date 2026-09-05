from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import FfmpegError, find_ffmpeg, has_nvenc, run_cmd
from bilingual_sub.config import bundled_fonts_dir
from bilingual_sub.core.control import JobStopped
from bilingual_sub.core.output_guard import validate_outputs

logger = logging.getLogger(__name__)


def burn_subtitles(
    video: Path,
    ass_path: Path,
    output: Path,
    *,
    encoder: str = "auto",
    cq: int = 18,
    preset: str = "p4",
    control=None,
) -> None:
    validate_outputs({"视频": output}, [video, ass_path])
    if control:
        control.wait_if_paused()
    output.parent.mkdir(parents=True, exist_ok=True)
    fonts_dir = bundled_fonts_dir()
    if not fonts_dir.is_dir() or not any(fonts_dir.iterdir()):
        logger.warning("fonts directory empty at %s — subtitles may not render CJK", fonts_dir)
    fd, name = tempfile.mkstemp(prefix=".subflow-", suffix=output.suffix or ".mp4", dir=output.parent)
    os.close(fd)
    part = Path(name)
    try:
        # Only fixed relative names enter the filter grammar. Arbitrary user
        # paths (quotes, brackets, commas, Unicode) stay in OS path arguments.
        with tempfile.TemporaryDirectory(prefix="subflow-burn-") as scratch:
            cwd = Path(scratch)
            shutil.copy2(ass_path, cwd / "subs.ass")
            if fonts_dir.is_dir():
                shutil.copytree(fonts_dir, cwd / "fonts")
            else:
                (cwd / "fonts").mkdir()
            _burn_in_directory(video.resolve(), part.resolve(), encoder=encoder, cq=cq,
                               preset=preset, control=control, cwd=cwd)
        if not part.is_file() or part.stat().st_size == 0:
            raise FfmpegError("FFmpeg did not produce a video")
        if control:
            control.wait_if_paused()
        part.replace(output)
    finally:
        part.unlink(missing_ok=True)
    logger.info("burned subtitles -> %s", output)


def _burn_in_directory(video: Path, output: Path, *, encoder: str, cq: int,
                       preset: str, control, cwd: Path) -> None:
    vf = "setpts=PTS-STARTPTS,subtitles=subs.ass:charenc=UTF-8:fontsdir=fonts"
    audio = ["-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-b:a", "192k"]

    enc = encoder
    if enc == "auto":
        enc = "h264_nvenc" if has_nvenc() else "libx264"

    args = [
        find_ffmpeg(),
        "-y",
        "-i",
        str(video),
        "-vf",
        vf,
        *audio,
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
    ]

    if enc == "h264_nvenc":
        args.extend(
            [
                "-c:v",
                "h264_nvenc",
                "-preset",
                preset,
                "-rc",
                "vbr",
                "-cq",
                str(cq),
                "-b:v",
                "0",
            ]
        )
    else:
        args.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", str(max(18, cq))])

    args.append(str(output))
    try:
        run_cmd(args, control=control, cwd=cwd)
    except JobStopped:
        raise
    except Exception as exc:
        if enc != "h264_nvenc":
            raise
        logger.warning("NVENC failed (%s); retrying with libx264", exc)
        retry = [
            find_ffmpeg(),
            "-y",
            "-i",
            str(video),
            "-vf",
            vf,
            *audio,
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(max(18, cq)),
            str(output),
        ]
        run_cmd(retry, control=control, cwd=cwd)
