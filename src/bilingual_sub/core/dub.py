from __future__ import annotations

import hashlib
import json
import logging
import math
import tempfile
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import FfmpegError, find_ffmpeg, run_cmd
from bilingual_sub.adapters.tts.base import TtsProvider, TtsRequest
from bilingual_sub.adapters.tts.model_identity import ModelSnapshot, retry_model_change
from bilingual_sub.core.audio_cache import cache_digest, pcm_duration, produce_audio
from bilingual_sub.core.control import JobControl
from bilingual_sub.core.dub_progress import DubProgress, Progress
from bilingual_sub.core.dub_timing import plan_speech
from bilingual_sub.core.file_io import file_digest, staged_path
from bilingual_sub.core.output_guard import validate_outputs
from bilingual_sub.models import Cue

logger = logging.getLogger(__name__)
MAX_TEMPO = 1.25


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
    return pcm_duration(path, control)


def fit_clip(src: Path, dest: Path, target_sec: float, control: JobControl | None = None) -> None:
    validate_outputs({"拟合音频": dest}, [src])
    if not math.isfinite(target_sec) or target_sec <= 0:
        raise ValueError("target audio duration must be positive and finite")
    audio_sec = _audio_duration(src, control=control)
    target = target_sec
    rate = max(1.0, audio_sec / target)
    if rate > MAX_TEMPO + 1e-6:
        logger.warning("Narration requires %.2fx tempo after pause allocation (preferred <= %.2fx)", rate, MAX_TEMPO)
    with staged_path(dest, suffix=".wav") as part:
        _fit_clip(src, part, target, rate, control)
        pcm_duration(part, control)
        if control:
            control.wait_if_paused()
        part.replace(dest)


def _fit_clip(src, dest, target, rate, control):
    run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-i",
            str(src),
            "-filter:a",
            atempo_chain(math.ceil(rate * 10000) / 10000),
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
    validate_outputs({"配音视频": output}, [video, *(path for _, path in clips)])
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
        with staged_path(output, suffix=output.suffix or ".mp4") as part:
            _mix_group(video, pending, part, duration, work / "mix.txt", control)
            if not part.is_file() or part.stat().st_size == 0:
                raise FfmpegError("FFmpeg did not produce a dubbed video")
            if control:
                control.wait_if_paused()
            part.replace(output)


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
        # Bound silence by samples and rebuild timestamps after mixed-input EOF.
        # Time-only trimming of unbounded apad can hang or truncate on FFmpeg 8.1.
        samples = max(1, round(duration * 48000))
        mix += f",apad=whole_len={samples},atrim=end_sample={samples},asetpts=N/SR/TB"
    mix += "[aout]"
    filters.append(mix)
    graph.write_text(";".join(filters), encoding="utf-8")
    from bilingual_sub.adapters.ffmpeg import filter_script_option

    args.extend([filter_script_option(args[0]), str(graph)])
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


def _provider_identity(provider: TtsProvider, voice: str) -> str:
    from bilingual_sub.adapters.tts.gptsovits import tts_job_fingerprint

    return tts_job_fingerprint(
        getattr(provider, "name", "") or "unknown", voice=voice,
        **{key: str(getattr(provider, key, "") or "")
           for key in ("endpoint", "ref_audio", "prompt_text", "prompt_lang")},
    )


@retry_model_change
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
    on_progress: Progress = None,
) -> Path:
    with DubProgress(on_progress) as progress:
        return _dub_cues(cues, video=video, work=work, output=output, provider=provider,
                         lang=lang, voice=voice, duration=duration, control=control, progress=progress)


def _dub_cues(cues: list[Cue], *, video: Path, work: Path, output: Path, provider: TtsProvider,
              lang: str, voice: str, duration: float, control: JobControl | None, progress: DubProgress) -> Path:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("video duration must be positive and finite")
    if getattr(provider, 'supports_phrase_context', False):
        from bilingual_sub.core.speech import speech_phrases

        cues = speech_phrases(cues, lang)
    reference = str(getattr(provider, "ref_audio", "") or "")
    validate_outputs({"配音视频": output}, [video, *([Path(reference).expanduser()] if reference else [])])
    tts_dir = work / "tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    identity = _provider_identity(provider, voice)
    model = ModelSnapshot(getattr(provider, "name", ""), getattr(provider, "endpoint", ""))
    clips: list[tuple[float, Path]] = []
    clip_keys: list[tuple[Path, str]] = []
    synthesized = []
    from bilingual_sub.core.langs import spoken_line

    total = sum(bool(spoken_line(cue, lang)) for cue in cues)
    for i, cue in enumerate(cues):
        if control:
            control.wait_if_paused()
        text = spoken_line(cue, lang)
        if not text:
            continue
        progress.set("synth", len(synthesized) + 1, total, 0.75 * len(synthesized) / max(1, total))
        if not all(math.isfinite(t) for t in (cue.start, cue.end)) or cue.start < 0 or cue.end <= cue.start:
            raise ValueError("dub cue must have finite, nonnegative start and positive duration")
        request_key = hashlib.sha256(
            json.dumps(
                (
                    text,
                    identity,
                    model.cache_id,
                    lang,
                    voice,
                    str(getattr(provider, "name", "") or ""),
                    str(getattr(provider, "endpoint", "") or ""),
                    str(getattr(provider, "ref_audio", "") or ""),
                    str(getattr(provider, "prompt_text", "") or ""),
                    str(getattr(provider, "prompt_lang", "") or ""),
                ), ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        digest = request_key[:16]
        raw = tts_dir / f"{i:04d}-{digest}.wav"
        raw_digest = cache_digest(raw, request_key, control)
        if raw_digest is None:
            def synth_raw(pending):
                model.check()
                provider.synth(TtsRequest(text=text, lang=lang, voice=voice, dest=pending,
                                          model_revision=model.revision or ""), control=control)
                model.check()
                if _provider_identity(provider, voice) != identity:
                    raise RuntimeError("合成期间参考音频或配音设置发生变化，请重试")
            raw_digest = produce_audio(raw, request_key, synth_raw, control)
        synthesized.append((i, cue, raw, request_key, raw_digest, _audio_duration(raw, control)))
    plan = plan_speech([(cue.start, cue.end, seconds) for _, cue, _, _, _, seconds in synthesized], duration)
    for (i, cue, raw, request_key, raw_digest, _seconds), (start, target) in zip(synthesized, plan):
        if control:
            control.wait_if_paused()
        progress.set("align", len(clips) + 1, total, 0.75 + 0.15 * len(clips) / max(1, total))
        fit_key = hashlib.sha256(json.dumps(["natural-fit-v4", request_key, raw_digest,
                                            cue.start, cue.end, start, target]).encode()).hexdigest()
        fitted = tts_dir / f"{i:04d}-{fit_key[:16]}.fit.wav"
        if cache_digest(fitted, fit_key, control) is None:
            def produce_fit(pending):
                fit_clip(raw, pending, target, control=control)
                if file_digest(raw, checkpoint=control.wait_if_paused if control else None) != raw_digest:
                    raise RuntimeError("拟合期间原始配音音频发生变化，请重试")
            produce_audio(fitted, fit_key, produce_fit, control)
        clips.append((start, fitted))
        clip_keys.append((fitted, fit_key))
    progress.set("verify", len(clips), total, 0.9)
    for path, key in clip_keys:
        if cache_digest(path, key, control) is None:
            raise RuntimeError("混音前配音音频发生变化，请重试")
    if _provider_identity(provider, voice) != identity:
        raise RuntimeError("混音前参考音频或配音设置发生变化，请重试")
    output.parent.mkdir(parents=True, exist_ok=True)
    model.check()
    validate_outputs({"配音视频": output}, [video, *(path for _, path in clips)])
    with staged_path(output, suffix=output.suffix or ".mp4") as pending:
        progress.set("mix", len(clips), total, 0.95)
        mix_timeline(video, clips, pending, duration, control=control)
        model.check()
        pending.replace(output)
    progress.set("complete", len(clips), total, 1.0)
    if model.enabled:
        setattr(provider, "cache_model_revision", model.revision)
    return output
