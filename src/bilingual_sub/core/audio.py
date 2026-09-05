from __future__ import annotations

import logging
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import FfmpegError, find_ffmpeg, run_cmd

logger = logging.getLogger(__name__)


def extract_wav(
    video: Path,
    wav_out: Path,
    *,
    preview_sec: float | None = None,
    control=None,
) -> None:
    wav_out.parent.mkdir(parents=True, exist_ok=True)
    args = [
        find_ffmpeg(),
        "-y",
        "-fflags",
        "+genpts",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-af",
        "aresample=async=1:first_pts=0",
    ]
    if preview_sec:
        args[args.index("-i") : args.index("-i")] = ["-t", str(preview_sec)]
    args.append(str(wav_out))
    try:
        run_cmd(args, control=control)
    except FfmpegError as exc:
        msg = str(exc).lower()
        if "does not contain any stream" in msg or "output file #" in msg or "no audio" in msg:
            raise FfmpegError(
                f"no usable audio track in {video}. bilingual-sub needs a speech track."
            ) from exc
        raise
    logger.info("extracted audio -> %s", wav_out)


def detect_silences(
    wav: Path,
    *,
    noise_db: float = -32,
    min_duration: float = 0.35,
    control=None,
) -> list[tuple[float, float]]:
    """Parse ffmpeg silencedetect output into (start, end) silence islands."""
    proc = run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(wav),
            "-af",
            f"silencedetect=noise={noise_db}dB:d={min_duration}",
            "-f",
            "null",
            "-",
        ],
        control=control,
    )
    text = proc.stderr or ""
    starts: list[float] = []
    silences: list[tuple[float, float]] = []
    for line in text.splitlines():
        if "silence_start:" in line:
            m = line.split("silence_start:")[-1].strip().split()[0]
            try:
                starts.append(float(m))
            except ValueError:
                pass
        elif "silence_end:" in line and starts:
            part = line.split("silence_end:")[-1].strip()
            end = float(part.split("|")[0].strip())
            start = starts.pop(0)
            silences.append((round(start, 3), round(end, 3)))
    silences.sort()
    logger.info("detected %d silence islands", len(silences))
    return silences
