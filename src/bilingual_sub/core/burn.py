from __future__ import annotations

import logging
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import escape_subtitles_path, find_ffmpeg, has_nvenc, run_cmd
from bilingual_sub.config import bundled_fonts_dir

logger = logging.getLogger(__name__)


def burn_subtitles(
    video: Path,
    ass_path: Path,
    output: Path,
    *,
    encoder: str = "auto",
    cq: int = 18,
    preset: str = "p4",
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fonts_dir = bundled_fonts_dir()
    if not fonts_dir.is_dir() or not any(fonts_dir.iterdir()):
        logger.warning("fonts directory empty at %s — subtitles may not render CJK", fonts_dir)

    ass_esc = escape_subtitles_path(ass_path)
    fonts_esc = escape_subtitles_path(fonts_dir)
    vf = f"subtitles='{ass_esc}':charenc=UTF-8:fontsdir='{fonts_esc}'"

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
        "-c:a",
        "copy",
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
        run_cmd(args)
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
            "-c:a",
            "copy",
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
        run_cmd(retry)
    logger.info("burned subtitles -> %s", output)
