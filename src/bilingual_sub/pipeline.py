from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.adapters.ffmpeg import FfmpegError, copy_to_ascii_workdir, probe_video
from bilingual_sub.adapters.whisper_backend import load_transcript, transcribe
from bilingual_sub.config import (
    AppSettings,
    default_glossary_path,
    load_settings,
    load_style_preset,
)
from bilingual_sub.core.audio import detect_silences, extract_wav
from bilingual_sub.core.burn import burn_subtitles
from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.render import load_cues_json, save_cues_json, write_subtitles
from bilingual_sub.core.translate import translate_cues
from bilingual_sub.logging_util import setup_logging
from bilingual_sub.models import STAGES, Cue, JobConfig, JobResult
from bilingual_sub.secrets.store import get_api_key

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str, float], None] | None


def last_job_pointer() -> Path:
    p = Path.home() / ".cache" / "bilingual-sub"
    p.mkdir(parents=True, exist_ok=True)
    return p / "last_job.json"


def save_last_job(work_dir: Path, job_id: str) -> None:
    last_job_pointer().write_text(
        json.dumps({"work_dir": str(work_dir), "job_id": job_id}, ensure_ascii=False),
        encoding="utf-8",
    )


def load_last_job() -> Path | None:
    path = last_job_pointer()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        wd = Path(data["work_dir"])
        return wd if wd.is_dir() else None
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _stage_index(name: str) -> int:
    try:
        return STAGES.index(name)
    except ValueError:
        return 0


def _should_run(resume_from: str | None, stage: str) -> bool:
    if not resume_from:
        return True
    return _stage_index(stage) >= _stage_index(resume_from)


def _save_state(work_dir: Path, stage: str, extra: dict | None = None) -> None:
    data = {"stage": stage}
    if extra:
        data.update(extra)
    (work_dir / "job_state.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def video_fingerprint(path: Path) -> dict:
    resolved = path.resolve()
    st = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }


def artifact_key(config: JobConfig) -> str:
    fp = video_fingerprint(config.input_video)
    preview = config.preview_minutes or 0
    raw = (
        f"{fp['path']}|{fp['size']}|{fp['mtime_ns']}|"
        f"{config.whisper_model}|{config.translate_model}|{preview}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _same_fingerprint(saved: dict | None, config: JobConfig) -> bool:
    if not saved:
        return False
    cur = video_fingerprint(config.input_video)
    return (
        os.path.normcase(str(saved.get("path") or "")) == os.path.normcase(cur["path"])
        and int(saved.get("size") or -1) == cur["size"]
        and int(saved.get("mtime_ns") or -1) == cur["mtime_ns"]
    )


def _auto_work_dir(config: JobConfig) -> bool:
    return str(config.work_dir) in ("", "auto")


def _work_dir(config: JobConfig, settings: AppSettings) -> Path:
    explicit = not _auto_work_dir(config)
    if explicit:
        wd = config.work_dir
    elif config.resume_from:
        last = load_last_job()
        if last is None:
            raise FileNotFoundError(
                "resume requested but no last job found; pass --work-dir to the previous work folder"
            )
        wd = last
    elif settings.video.work_dir == "auto":
        wd = Path(tempfile.gettempdir()) / "bilingual-sub" / artifact_key(config)
    else:
        wd = Path(settings.video.work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _can_reexport(config: JobConfig, work: Path) -> bool:
    if config.resume_from or not _auto_work_dir(config):
        return False
    cues_path = work / "cues.bilingual.json"
    if not cues_path.is_file():
        return False
    state = _load_json(work / "job_state.json")
    if state.get("stage") not in {"render", "burn", "done"}:
        return False
    report = _load_json(work / "report.json")
    if not _same_fingerprint(report.get("input_fingerprint"), config):
        return False
    if str(report.get("whisper_model") or config.whisper_model) != config.whisper_model:
        return False
    if str(report.get("translate_model") or config.translate_model) != config.translate_model:
        return False
    return True


def _export_subs(
    config: JobConfig,
    work: Path,
    cues: list[Cue],
    play_res: tuple[int, int],
) -> Path:
    preset = load_style_preset(config.style_preset)
    ass_path = work / "subs.ass"
    srt_out = config.output_srt
    srt_out.parent.mkdir(parents=True, exist_ok=True)
    ass_out = srt_out.with_suffix(".ass") if srt_out.suffix else Path(str(srt_out) + ".ass")
    write_subtitles(cues, preset, ass_path, srt_out, play_res=play_res)
    if ass_out != ass_path:
        shutil.copy2(ass_path, ass_out)
    return ass_out


def _copy_or_burn(
    config: JobConfig,
    work: Path,
    settings: AppSettings,
    report: dict,
) -> Path | None:
    if not config.burn:
        return None
    dest = config.output_video or config.output_srt.with_suffix(".mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    prev = Path(str(report["output_mp4"])) if report.get("output_mp4") else None
    style_same = str(report.get("style_preset") or config.style_preset) == config.style_preset
    if prev and prev.is_file() and style_same:
        if prev.resolve() != dest.resolve():
            shutil.copy2(prev, dest)
        return dest
    ass_path = work / "subs.ass"
    source = work / "source.mp4"
    if not source.is_file():
        source = config.input_video
    if not ass_path.is_file():
        raise FileNotFoundError("previous subtitles missing; cannot export without re-running")
    burn_subtitles(
        source,
        ass_path,
        dest,
        encoder=settings.burn.encoder,
        cq=settings.burn.cq,
        preset=settings.burn.preset,
    )
    return dest


def _result_from_work(
    *,
    job_id: str,
    config: JobConfig,
    work: Path,
    output_mp4: Path | None,
    ass_out: Path,
    cues: list[Cue],
    report: dict,
    stages: dict[str, float],
    elapsed: float,
    reused: bool,
) -> JobResult:
    missing = list(report.get("missing_en_samples") or [])
    payload = {
        "job_id": job_id,
        "input": str(config.input_video),
        "duration_sec": report.get("duration_sec") or 0,
        "cue_count": len(cues),
        "missing_en_count": int(report.get("missing_en_count") or len(missing)),
        "missing_en_samples": missing[:20],
        "translate_cache_hits": int(report.get("translate_cache_hits") or 0),
        "translate_api_calls": int(report.get("translate_api_calls") or 0),
        "elapsed_sec": round(elapsed, 2),
        "stages": stages,
        "work_dir": str(work),
        "play_res": report.get("play_res") or [2560, 1600],
        "output_mp4": str(output_mp4) if output_mp4 else None,
        "output_srt": str(config.output_srt),
        "input_fingerprint": video_fingerprint(config.input_video),
        "whisper_model": config.whisper_model,
        "translate_model": config.translate_model,
        "style_preset": config.style_preset,
        "reused": reused,
    }
    report_path = work / "report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_state(work, "done", {"job_id": job_id})
    save_last_job(work, job_id)
    return JobResult(
        job_id=job_id,
        output_mp4=output_mp4,
        output_srt=config.output_srt,
        output_ass=ass_out,
        cue_count=len(cues),
        missing_en=missing,
        duration_sec=float(payload["duration_sec"] or 0),
        report_path=report_path,
        elapsed_sec=elapsed,
        translate_cache_hits=int(payload["translate_cache_hits"]),
        translate_api_calls=int(payload["translate_api_calls"]),
        stages=stages,
        reused=reused,
    )


def _reexport_if_possible(
    config: JobConfig,
    settings: AppSettings,
    work: Path,
    on_progress: ProgressCb,
    t0: float,
) -> JobResult | None:
    if not _can_reexport(config, work):
        return None
    report = _load_json(work / "report.json")
    state = _load_json(work / "job_state.json")
    job_id = str(state.get("job_id") or uuid.uuid4().hex[:12])
    cues = load_cues_json(work / "cues.bilingual.json")
    play = report.get("play_res") or [2560, 1600]
    play_res = (int(play[0]), int(play[1]))

    def prog(stage: str, pct: float) -> None:
        if on_progress:
            on_progress(stage, pct)

    logger.info("reexport job %s work_dir=%s", job_id, work)
    prog("export", 0.85)
    ts = time.time()
    ass_out = _export_subs(config, work, cues, play_res)
    output_mp4 = _copy_or_burn(config, work, settings, report)
    stages = {"export_sec": time.time() - ts}
    prog("done", 1.0)
    return _result_from_work(
        job_id=job_id,
        config=config,
        work=work,
        output_mp4=output_mp4,
        ass_out=ass_out,
        cues=cues,
        report=report,
        stages=stages,
        elapsed=time.time() - t0,
        reused=True,
    )


def run(
    config: JobConfig,
    settings: AppSettings | None = None,
    *,
    on_progress: ProgressCb = None,
) -> JobResult:
    setup_logging(api_key=get_api_key())
    settings = settings or load_settings()
    t0 = time.time()
    stages: dict[str, float] = {}

    work = _work_dir(config, settings)
    reused = _reexport_if_possible(config, settings, work, on_progress, t0)
    if reused:
        return reused
    state_path = work / "job_state.json"
    job_id = uuid.uuid4().hex[:12]
    if state_path.is_file():
        try:
            job_id = str(json.loads(state_path.read_text(encoding="utf-8")).get("job_id") or job_id)
        except json.JSONDecodeError:
            pass
    save_last_job(work, job_id)
    logger.info("job %s work_dir=%s", job_id, work)

    def prog(stage: str, pct: float) -> None:
        if on_progress:
            on_progress(stage, pct)

    input_video = config.input_video
    if settings.video.copy_to_ascii_path:
        source = copy_to_ascii_workdir(input_video, work)
    else:
        source = input_video
        shutil.copy2(input_video, work / "source.mp4")

    meta = probe_video(source)
    duration = float(meta.get("duration") or 0)
    play_res = (int(meta["width"]), int(meta["height"]))
    if not meta.get("has_audio"):
        raise FfmpegError(f"no audio stream in {input_video}")

    speech = work / "speech.wav"
    silences_path = work / "silences.json"
    transcript_path = work / "transcript.json"
    cues_zh_path = work / "cues.zh.json"
    cues_bi_path = work / "cues.bilingual.json"
    ass_path = work / "subs.ass"
    srt_out = config.output_srt
    srt_out.parent.mkdir(parents=True, exist_ok=True)
    ass_out = srt_out.with_suffix(".ass") if srt_out.suffix else Path(str(srt_out) + ".ass")

    glossary = Glossary.load(config.glossary_path or default_glossary_path())
    preset = load_style_preset(config.style_preset)

    cache_hits = 0
    api_calls = 0
    missing: list[str] = []
    cues: list[Cue] = []

    preview_sec = config.preview_minutes * 60 if config.preview_minutes else None

    if _should_run(config.resume_from, "extract"):
        prog("extract", 0.05)
        ts = time.time()
        extract_wav(source, speech, preview_sec=preview_sec)
        stages["extract_sec"] = time.time() - ts
        _save_state(work, "extract", {"job_id": job_id})

    if _should_run(config.resume_from, "silence"):
        prog("silence", 0.12)
        ts = time.time()
        if silences_path.is_file() and config.resume_from:
            silences = [tuple(x) for x in json.loads(silences_path.read_text(encoding="utf-8"))]
        else:
            silences = detect_silences(
                speech,
                noise_db=settings.silence.noise_db,
                min_duration=settings.silence.min_duration,
            )
            silences_path.write_text(json.dumps(silences), encoding="utf-8")
        stages["silence_sec"] = time.time() - ts
        _save_state(work, "silence", {"job_id": job_id})
    else:
        silences = [tuple(x) for x in json.loads(silences_path.read_text(encoding="utf-8"))]

    if _should_run(config.resume_from, "transcribe"):
        prog("transcribe", 0.2)
        ts = time.time()
        segments = transcribe(
            speech,
            model_name=config.whisper_model or settings.asr.model,
            language=settings.asr.language,
            device=config.device or settings.asr.device,  # type: ignore[arg-type]
            out_json=transcript_path,
            on_progress=prog,
        )
        stages["transcribe_sec"] = time.time() - ts
        _save_state(work, "transcribe", {"job_id": job_id})
    else:
        segments = load_transcript(transcript_path)

    if _should_run(config.resume_from, "build_cues"):
        prog("build_cues", 0.45)
        ts = time.time()
        cues = build_cues(
            segments,
            silences,
            glossary,
            snap_tolerance=settings.cues.snap_tolerance,
            min_duration=settings.cues.min_duration,
            max_duration=settings.cues.max_duration,
            silence_split_threshold=settings.cues.silence_split_threshold,
        )
        save_cues_json(cues, cues_zh_path)
        stages["build_cues_sec"] = time.time() - ts
        _save_state(work, "build_cues", {"job_id": job_id, "cue_count": len(cues)})
    else:
        cues = load_cues_json(cues_zh_path if cues_zh_path.is_file() else cues_bi_path)

    if _should_run(config.resume_from, "translate"):
        prog("translate", 0.6)
        ts = time.time()
        if cues:
            cues, tstats, missing = translate_cues(
                cues,
                model=config.translate_model or settings.translate.model,
                batch_size=config.translate_batch_size or settings.translate.batch_size,
                max_en_chars=settings.translate.max_en_chars,
                cache_enabled=settings.translate.cache_enabled,
            )
            cache_hits = tstats.cache_hits
            api_calls = tstats.api_calls
        save_cues_json(cues, cues_bi_path)
        stages["translate_sec"] = time.time() - ts
        _save_state(work, "translate", {"job_id": job_id, "missing_en": len(missing)})
    else:
        cues = load_cues_json(cues_bi_path)

    if _should_run(config.resume_from, "render"):
        prog("render", 0.8)
        ts = time.time()
        write_subtitles(cues, preset, ass_path, srt_out, play_res=play_res)
        if ass_out != ass_path:
            shutil.copy2(ass_path, ass_out)
        stages["render_sec"] = time.time() - ts
        _save_state(work, "render", {"job_id": job_id})
    elif ass_path.is_file() and not srt_out.is_file():
        shutil.copy2(ass_path, ass_out)

    output_mp4: Path | None = None
    if config.burn and _should_run(config.resume_from, "burn"):
        prog("burn", 0.9)
        ts = time.time()
        out = config.output_video or srt_out.with_suffix(".mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        burn_subtitles(
            source,
            ass_path,
            out,
            encoder=settings.burn.encoder,
            cq=settings.burn.cq,
            preset=settings.burn.preset,
        )
        output_mp4 = out
        stages["burn_sec"] = time.time() - ts
        _save_state(work, "burn", {"job_id": job_id})

    elapsed = time.time() - t0
    report = {
        "job_id": job_id,
        "input": str(config.input_video),
        "duration_sec": duration,
        "cue_count": len(cues),
        "missing_en_count": len(missing),
        "missing_en_samples": missing[:20],
        "translate_cache_hits": cache_hits,
        "translate_api_calls": api_calls,
        "elapsed_sec": round(elapsed, 2),
        "stages": stages,
        "work_dir": str(work),
        "play_res": list(play_res),
        "output_mp4": str(output_mp4) if output_mp4 else None,
        "output_srt": str(srt_out),
        "input_fingerprint": video_fingerprint(config.input_video),
        "whisper_model": config.whisper_model,
        "translate_model": config.translate_model,
        "style_preset": config.style_preset,
        "reused": False,
    }
    report_path = work / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _save_state(work, "done", {"job_id": job_id})

    prog("done", 1.0)
    return JobResult(
        job_id=job_id,
        output_mp4=output_mp4,
        output_srt=srt_out,
        output_ass=ass_out,
        cue_count=len(cues),
        missing_en=missing,
        duration_sec=duration,
        report_path=report_path,
        elapsed_sec=elapsed,
        translate_cache_hits=cache_hits,
        translate_api_calls=api_calls,
        stages=stages,
        reused=False,
    )
