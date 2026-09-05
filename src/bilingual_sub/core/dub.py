from __future__ import annotations

import hashlib
import logging
import math
import tempfile
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import find_ffmpeg, find_ffprobe, run_cmd
from bilingual_sub.adapters.tts.base import TtsProvider, TtsRequest
from bilingual_sub.core.control import JobControl
from bilingual_sub.models import Cue

logger = logging.getLogger(__name__)


def clamp_rate(audio_sec: float, target_sec: float) -> float:
    """Single-stage atempo factor (ffmpeg allows 0.5–2.0 per filter)."""
    if target_sec <= 0:
        return 1.0
    return max(0.5, min(2.0, audio_sec / target_sec))


def atempo_chain(rate: float) -> str:
    """Build an atempo chain so long TTS lines can fully fit the cue window."""
    rate = float(rate)
    if not math.isfinite(rate):
        raise ValueError("audio rate must be finite")
    if rate <= 0:
        return "atempo=1.0"
    parts: list[str] = []
    while rate > 2.0 + 1e-9:
        parts.append("atempo=2.0")
        rate /= 2.0
    while rate < 0.5 - 1e-9:
        parts.append("atempo=0.5")
        rate /= 0.5
    parts.append(f"atempo={rate:.4f}")
    return ",".join(parts)


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
    rate = (audio_sec / target) if target > 0 else 1.0
    part = dest.with_name(dest.stem + ".part" + dest.suffix)
    try:
        _fit_clip(src, part, target, rate, control)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def _fit_clip(src, dest, target, rate, control):
    run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(src),
            "-filter:a",
            atempo_chain(rate),
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
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be positive and finite")
    if any(not math.isfinite(start) for start, _ in clips):
        raise ValueError("clip start must be finite")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Bound both command length and open file handles. Each intermediate keeps
    # its own start offset, avoiding hours of silence in every temporary WAV.
    with tempfile.TemporaryDirectory(prefix="sf-mix-") as temp:
        work = Path(temp)
        pending = sorted(clips, key=lambda item: item[0])
        level = 0
        while len(pending) > 24:
            reduced = []
            for index in range(0, len(pending), 24):
                group = pending[index:index + 24]
                offset = max(0.0, group[0][0])
                dest = work / f"{level}-{index}.wav"
                _mix_group(None, [(max(0.0, s) - offset, p) for s, p in group],
                           dest, max(0.4, duration - offset), work / "mix.txt", control)
                reduced.append((offset, dest))
            pending = reduced
            level += 1
        _mix_group(video, pending, output, duration, work / "mix.txt", control)


def _mix_group(video, clips, output, duration, graph, control):
    if control:
        control.wait_if_paused()
    args = [find_ffmpeg(), "-y"]
    if video is not None:
        args.extend(["-i", str(video)])
    for _start, clip in clips:
        args.extend(["-i", str(clip)])
    filters = []
    names = []
    for i, (start, _clip) in enumerate(clips, start=int(video is not None)):
        delay = max(0, int(start * 1000))
        label = f"a{i}"
        filters.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={delay}:all=1[{label}]")
        names.append(f"[{label}]")
    mix = "".join(names) + f"amix=inputs={len(clips)}:normalize=0"
    if video is not None:
        mix += f",apad,atrim=duration={duration:.6f}"
    mix += "[aout]"
    filters.append(mix)
    graph.write_text(";".join(filters), encoding="utf-8")
    args.extend(["-filter_complex_script", str(graph)])
    if video is not None:
        args.extend(["-map", "0:v:0", "-c:v", "copy"])
    args.extend(
        [
            "-map",
            "[aout]",
            "-c:a",
            "aac" if video is not None else "pcm_f32le",
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
    from bilingual_sub.adapters.tts.gptsovits import tts_job_fingerprint

    identity = tts_job_fingerprint(
        getattr(provider, "name", "") or "unknown", voice=voice,
        **{key: str(getattr(provider, key, "") or "")
           for key in ("endpoint", "ref_audio", "prompt_text", "prompt_lang")},
    )
    clips: list[tuple[float, Path]] = []
    for i, cue in enumerate(cues):
        if control:
            control.wait_if_paused()
        from bilingual_sub.core.langs import spoken_line

        text = spoken_line(cue, lang)
        if not text:
            continue
        digest = hashlib.sha256(
            "|".join(
                (
                    text,
                    identity,
                    lang,
                    voice,
                    str(getattr(provider, "name", "") or ""),
                    str(getattr(provider, "endpoint", "") or ""),
                    str(getattr(provider, "ref_audio", "") or ""),
                    str(getattr(provider, "prompt_text", "") or ""),
                    str(getattr(provider, "prompt_lang", "") or ""),
                )
            ).encode()
        ).hexdigest()[:12]
        raw = tts_dir / f"{i:04d}-{digest}.wav"
        target = max(0.4, cue.end - cue.start)
        fitted = tts_dir / f"{i:04d}-{digest}-{target:.6f}.fit.wav"
        if not raw.is_file():
            provider.synth(TtsRequest(text=text, lang=lang, voice=voice, dest=raw), control=control)
        if not fitted.is_file():
            fit_clip(raw, fitted, max(0.4, cue.end - cue.start), control=control)
        clips.append((cue.start, fitted))
    output.parent.mkdir(parents=True, exist_ok=True)
    mix_timeline(video, clips, output, duration, control=control)
    return output
