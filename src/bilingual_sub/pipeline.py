from __future__ import annotations

import json
import logging
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


def _work_dir(config: JobConfig, settings: AppSettings) -> Path:
    explicit = str(config.work_dir) not in ("", "auto")
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
        wd = Path(tempfile.gettempdir()) / "bilingual-sub" / uuid.uuid4().hex[:12]
    else:
        wd = Path(settings.video.work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    return wd


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
    )
