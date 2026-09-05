from __future__ import annotations

import logging
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import find_ffmpeg, find_ffprobe, run_cmd
from bilingual_sub.adapters.tts.base import TtsProvider, TtsRequest
from bilingual_sub.core.control import JobControl
from bilingual_sub.models import Cue

logger = logging.getLogger(__name__)


def clamp_rate(audio_sec: float, target_sec: float) -> float:
    if target_sec <= 0:
        return 1.0
    return max(0.90, min(1.15, audio_sec / target_sec))


def _audio_duration(path: Path, control: JobControl | None = None) -> float:
    import json

    proc = run_cmd(
        [
            find_ffprobe(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        control=control,
    )
    data = json.loads(proc.stdout or "{}")
    try:
        return float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def fit_clip(src: Path, dest: Path, target_sec: float, control: JobControl | None = None) -> None:
    audio_sec = _audio_duration(src, control=control) or target_sec or 1
    target = max(0.4, target_sec)
    rate = clamp_rate(audio_sec, target)
    run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(src),
            "-filter:a",
            f"atempo={rate:.3f}",
            "-t",
            f"{target:.3f}",
            str(dest),
        ],
        control=control,
    )


def mix_timeline(
    video: Path,
    clips: list[tuple[float, Path]],
    output: Path,
    duration: float,
    control: JobControl | None = None,
) -> None:
    if not clips:
        raise RuntimeError("no dub clips")
    args = [find_ffmpeg(), "-y", "-i", str(video)]
    for _start, clip in clips:
        args.extend(["-i", str(clip)])
    filters = []
    names = []
    for i, (start, _clip) in enumerate(clips, start=1):
        delay = max(0, int(start * 1000))
        label = f"a{i}"
        filters.append(f"[{i}:a]adelay={delay}|{delay}[{label}]")
        names.append(f"[{label}]")
    mix = "".join(names) + f"amix=inputs={len(clips)}:normalize=0[aout]"
    filters.append(mix)
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{max(duration, 0.4):.3f}",
            str(output),
        ]
    )
    run_cmd(args, control=control)


def dub_cues(
    cues: list[Cue],
    *,
    video: Path,
    work: Path,
    output: Path,
    provider: TtsProvider,
    lang: str,
    voice: str,
    duration: float,
    control: JobControl | None = None,
) -> Path:
    tts_dir = work / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    clips: list[tuple[float, Path]] = []
    for i, cue in enumerate(cues):
        if control:
            control.wait_if_paused()
        from bilingual_sub.core.langs import spoken_line

        text = spoken_line(cue, lang)
        if not text:
            continue
        raw = tts_dir / f"{i:04d}.wav"
        fitted = tts_dir / f"{i:04d}.fit.wav"
        if not raw.is_file():
            provider.synth(TtsRequest(text=text, lang=lang, voice=voice, dest=raw), control=control)
        if not fitted.is_file():
            fit_clip(raw, fitted, max(0.4, cue.end - cue.start), control=control)
        clips.append((cue.start, fitted))
    output.parent.mkdir(parents=True, exist_ok=True)
    mix_timeline(video, clips, output, duration, control=control)
    return output
