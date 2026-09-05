from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from filelock import FileLock, Timeout

from bilingual_sub.adapters.ffmpeg import FfmpegError, copy_to_ascii_workdir, probe_video
from bilingual_sub.adapters.whisper_backend import load_transcript, transcribe
from bilingual_sub.adapters.whisperx_backend import WhisperXBackend, ensure_whisperx_runtime
from bilingual_sub.adapters.ytdlp import download as ytdlp_download
from bilingual_sub.config import (
    AppSettings,
    default_glossary_path,
    load_settings,
    load_style_preset,
)
from bilingual_sub.core.audio import detect_silences, extract_wav
from bilingual_sub.core.burn import burn_subtitles
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.cues import build_cues
from bilingual_sub.core.dub import dub_cues
from bilingual_sub.core.glossary import Glossary
from bilingual_sub.core.glossary_ai import extract_glossary
from bilingual_sub.core.job_profile import processing_profile, render_profile
from bilingual_sub.core.langs import (
    apply_han_to_cues,
    assign_pair_fields,
    drop_target_if_unneeded,
    effective_tts_provider,
    has_distinct_target_line,
    is_pair_mode,
    job_needs_dub,
    job_needs_translation,
    job_translation_langs,
    lang_family,
    normalize_pair_fields,
    pair_cues_polluted,
    screen_han_lang,
    should_dub,
    spoken_family,
    spoken_han_lang,
    spoken_line,
    translation_needed,
    whisper_language,
)
from bilingual_sub.core.netflix import fit_cues, fit_warnings
from bilingual_sub.core.persistence import write_json
from bilingual_sub.core.render import (
    SUBTITLE_PACK,
    apply_subtitle_colors,
    load_cues_json,
    save_cues_json,
    write_subtitles,
)
from bilingual_sub.core.translate import (
    fill_translated_languages,
    translate_cues,
    translate_pair_cues,
)
from bilingual_sub.core.translate_refine import translate_cues_refined
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
    write_json(last_job_pointer(), {"work_dir": str(work_dir), "job_id": job_id})


def load_last_job() -> Path | None:
    path = last_job_pointer()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        wd = Path(data["work_dir"])
        return wd if wd.is_dir() else None
    except (KeyError, OSError, TypeError, ValueError):
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


def _save_state(
    work_dir: Path,
    stage: str,
    extra: dict | None = None,
    *,
    control: JobControl | None = None,
) -> None:
    previous = _load_json(work_dir / "job_state.json")
    completed = stage if stage in STAGES else previous.get("completed_stage", previous.get("stage", "init"))
    data = {"stage": stage, "completed_stage": completed, "paused": False, "stopped": False}
    if control:
        data["paused"] = control.is_paused()
        data["stopped"] = control.is_stopped()
    if extra:
        data.update(extra)
    write_json(work_dir / "job_state.json", data)


def video_fingerprint(path: Path) -> dict:
    resolved = path.resolve()
    if not resolved.is_file():
        return {"path": str(resolved), "size": 0, "mtime_ns": 0}
    st = resolved.stat()
    return {
        "path": str(resolved),
        "size": int(st.st_size),
        "mtime_ns": int(st.st_mtime_ns),
    }


def _glossary_hash(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _resolved_tts_provider(
    config: JobConfig,
    cues=None,
    *,
    detected_spoken: str | None = None,
) -> str:
    return effective_tts_provider(
        config.source_lang,
        config.source_lang if detected_spoken is None else detected_spoken,
        config.target_lang,
        cues=cues,
        enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    )


def _tts_fingerprint(config: JobConfig, *, detected_spoken: str | None = None, cues=None) -> str:
    from bilingual_sub.adapters.tts.gptsovits import tts_job_fingerprint

    return tts_job_fingerprint(
        _resolved_tts_provider(config, cues, detected_spoken=detected_spoken),
        voice=config.tts_voice,
        endpoint=config.tts_endpoint,
        ref_audio=config.tts_ref_audio,
        prompt_text=config.tts_prompt_text,
        prompt_lang=config.tts_prompt_lang,
    )


def artifact_key(config: JobConfig) -> str:
    if config.input_video.is_file():
        fp = video_fingerprint(config.input_video)
    elif config.source_url:
        fp = {"path": f"url|{config.source_url}", "size": 0, "mtime_ns": 0}
    else:
        fp = {"path": f"url|{config.source_url or config.input_video}", "size": 0, "mtime_ns": 0}
    preview = config.preview_minutes or 0
    gloss = _glossary_hash(config.glossary_path)
    raw = (
        f"{fp['path']}|{fp['size']}|{fp['mtime_ns']}|"
        f"{config.whisper_model}|{config.translate_model}|{preview}|"
        f"{config.source_lang}|{config.target_lang}|{config.subtitle_mode}|"
        f"{int(translation_needed(config.source_lang, config.target_lang, config.subtitle_mode))}|"
        f"{int(should_dub(config.source_lang, config.source_lang, config.target_lang))}|"
        f"{int(config.enable_dub)}|{_tts_fingerprint(config)}|"
        f"{config.asr_backend}|{int(config.refine_translate)}|{gloss}|{int(config.glossary_generate)}|"
        f"{int(config.burn)}|{config.source_url or ''}|"
        f"pair-script-v1|original-audio-v2|bounded-mix-v1"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _same_fingerprint(saved: dict | None, config: JobConfig, work: Path | None = None) -> bool:
    if not saved:
        return False
    if config.input_video.is_file():
        cur = video_fingerprint(config.input_video)
        return (
            os.path.normcase(str(saved.get("path") or "")) == os.path.normcase(cur["path"])
            and int(saved.get("size") or -1) == cur["size"]
            and int(saved.get("mtime_ns") or -1) == cur["mtime_ns"]
        )
    if work is None or not config.source_url:
        return False
    src = work / "source.mp4"
    url_txt = work / "source.url.txt"
    if not (src.is_file() and url_txt.is_file()):
        return False
    if url_txt.read_text(encoding="utf-8").strip() != config.source_url:
        return False
    stat = src.stat()
    return (int(saved.get("size") or -1) == stat.st_size and stat.st_size > 0
            and int(saved.get("mtime_ns") or -1) == stat.st_mtime_ns)


def _job_profile_matches(report: dict, config: JobConfig) -> bool:
    if not report:
        return True
    return (
        str(report.get("source_lang") or "zh") == config.source_lang
        and str(report.get("target_lang") or "zh") == config.target_lang
        and str(report.get("subtitle_mode") or "bilingual") == config.subtitle_mode
        and str(report.get("whisper_model") or config.whisper_model) == config.whisper_model
        and str(report.get("translate_model") or config.translate_model) == config.translate_model
        and str(report.get("asr_backend") or "whisper") == config.asr_backend
    )


def _resume_dir_matches(config: JobConfig, work: Path, settings: AppSettings | None = None) -> bool:
    report = _load_json(work / "job_input.json") or _load_json(work / "report.json")
    if report.get("processing_profile") != processing_profile(config, settings or load_settings()):
        return False
    if report and not _job_profile_matches(report, config):
        return False
    if report:
        saved = report.get("input_fingerprint") if isinstance(report.get("input_fingerprint"), dict) else None
        if config.source_url and str(report.get("source_url") or "") != config.source_url:
            return False
        if config.input_video.is_file():
            return _same_fingerprint(saved, config, work)
        saved_url = str(report.get("source_url") or "")
        if config.source_url and saved_url:
            return saved_url == config.source_url and _same_fingerprint(saved, config, work)
    url_txt = work / "source.url.txt"
    if config.source_url and url_txt.is_file() and (work / "source.mp4").is_file():
        return url_txt.read_text(encoding="utf-8").strip() == config.source_url
    return False


def _auto_work_dir(config: JobConfig) -> bool:
    return str(config.work_dir) in ("", "auto")


def _work_dir(config: JobConfig, settings: AppSettings) -> Path:
    explicit = not _auto_work_dir(config)
    if explicit:
        wd = config.work_dir
        if (config.resume_from and _stage_index(config.resume_from) > _stage_index("ingest")
                and not _resume_dir_matches(config, wd, settings)):
            raise FileNotFoundError("工作目录不是这部片子或字幕/识别设置不同；请从 ingest 重新处理")
    elif config.resume_from:
        last = load_last_job()
        if last is None:
            raise FileNotFoundError(
                "resume requested but no last job found; pass --work-dir to the previous work folder"
            )
        if not _resume_dir_matches(config, last, settings):
            raise FileNotFoundError(
                "上次作业不是这部片子或字幕/识别设置不同；请传 --work-dir 指向对应工作目录"
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
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_silences(path: Path) -> list[tuple[float, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("静音缓存必须是时间区间列表；请从 silence 重新处理")
    out: list[tuple[float, float]] = []
    for pair in data:
        if (not isinstance(pair, list) or len(pair) != 2
                or any(not isinstance(v, (int, float)) or isinstance(v, bool)
                       or not math.isfinite(v) or v < 0 for v in pair)
                or pair[1] < pair[0] or (out and pair[0] < out[-1][0])):
            raise ValueError("静音缓存包含无效时间区间；请从 silence 重新处理")
        out.append((float(pair[0]), float(pair[1])))
    return out


def _can_reexport(config: JobConfig, work: Path, settings: AppSettings | None = None) -> bool:
    try:
        return _can_reexport_checked(config, work, settings)
    except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
        logger.warning("Invalid cached job; processing again: %s", exc)
        return False


def _can_reexport_checked(config: JobConfig, work: Path, settings: AppSettings | None = None) -> bool:
    if config.resume_from or not _auto_work_dir(config):
        return False
    cues_path = work / "cues.bilingual.json"
    if not cues_path.is_file():
        return False
    state = _load_json(work / "job_state.json")
    if state.get("stage") not in {"render", "burn", "done"}:
        return False
    if state.get("completed_stage", state["stage"]) != state["stage"]:
        return False
    report = _load_json(work / "report.json")
    if not state.get("job_id") or report.get("job_id") != state["job_id"]:
        return False
    fitted = work / "cues.fitted.json"
    fitted_cues = None
    if config.subtitle_mode == "netflix_single" and fitted.is_file():
        fitted_cues = load_cues_json(fitted)
    play = report.get("play_res")
    if play is not None and (not isinstance(play, list) or len(play) != 2
                            or any(not isinstance(v, int) or isinstance(v, bool)
                                   or not 0 < v < 100000 for v in play)):
        return False
    for key in ("cue_count", "missing_en_count", "translate_cache_hits", "translate_api_calls"):
        value = report.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            return False
    for key in ("duration_sec", "elapsed_sec"):
        value = report.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                  or not math.isfinite(value) or value < 0):
            return False
    for key in ("burn", "dubbed", "refine", "translated"):
        if report.get(key) is not None and not isinstance(report[key], bool):
            return False
    missing = report.get("missing_en_samples", [])
    if not isinstance(missing, list) or any(not isinstance(s, str) for s in missing):
        return False
    settings = settings or load_settings()
    if report.get("processing_profile") != processing_profile(config, settings):
        return False
    if not _same_fingerprint(report.get("input_fingerprint"), config, work):
        return False
    if str(report.get("whisper_model") or config.whisper_model) != config.whisper_model:
        return False
    if str(report.get("translate_model") or config.translate_model) != config.translate_model:
        return False
    if str(report.get("source_lang") or "zh") != config.source_lang:
        return False
    if str(report.get("target_lang") or "zh") != config.target_lang:
        return False
    if str(report.get("subtitle_mode") or "bilingual") != config.subtitle_mode:
        return False
    if str(report.get("asr_backend") or "whisper") != config.asr_backend:
        return False
    if bool(report.get("refine", False)) != bool(config.refine_translate):
        return False
    if "burn" in report and bool(report.get("burn")) != bool(config.burn):
        return False
    heard = str(report.get("detected_spoken") or config.source_lang)
    need_screen = translation_needed(config.source_lang, config.target_lang, config.subtitle_mode)
    need_any = job_needs_translation(
        config.source_lang,
        config.target_lang,
        config.subtitle_mode,
        detected_spoken=heard,
        enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    )
    if report.get("translated") is not None and bool(report.get("translated")) != need_screen:
        return False
    cues = load_cues_json(cues_path)
    if report.get("cue_count") is not None and report["cue_count"] != len(fitted_cues if fitted_cues is not None else cues):
        return False
    if not need_any and has_distinct_target_line(cues):
        return False
    if is_pair_mode(config.subtitle_mode) and pair_cues_polluted(cues):
        return False
    needs_voice = job_needs_dub(
        config.source_lang,
        heard,
        config.target_lang,
        cues=_original_cues(work),
        enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    )
    if "dubbed" in report and bool(report["dubbed"]) != needs_voice:
        return False
    if needs_voice:
        if not (work / "dubbed.mp4").is_file():
            return False
        saved_tts = report.get("tts_fingerprint")
        if saved_tts and saved_tts != _tts_fingerprint(config, detected_spoken=heard, cues=cues):
            return False
        if config.burn and not _style_same(report, config, settings):
            return False
    return True


def _styled_preset(config: JobConfig):
    return apply_subtitle_colors(
        load_style_preset(config.style_preset),
        config.subtitle_zh_color,
        config.subtitle_en_color,
    )


def _style_same(report: dict, config: JobConfig, settings: AppSettings) -> bool:
    return report.get("render_profile") == render_profile(config, settings)


def _export_subs(
    config: JobConfig,
    work: Path,
    cues: list[Cue],
    play_res: tuple[int, int],
) -> Path:
    preset = _styled_preset(config)
    ass_path = work / "subs.ass"
    srt_out = config.output_srt
    srt_out.parent.mkdir(parents=True, exist_ok=True)
    ass_out = srt_out.with_suffix(".ass") if srt_out.suffix else Path(str(srt_out) + ".ass")
    write_subtitles(
        cues,
        preset,
        ass_path,
        srt_out,
        play_res=play_res,
        mode=config.subtitle_mode,
        han_lang=screen_han_lang(config.source_lang, config.target_lang, config.subtitle_mode),
        target_lang=config.target_lang,
        source_lang=config.source_lang,
    )
    if ass_out != ass_path:
        shutil.copy2(ass_path, ass_out)
    return ass_out


def _copy_or_burn(
    config: JobConfig,
    work: Path,
    settings: AppSettings,
    report: dict,
    control: JobControl | None = None,
) -> Path | None:
    heard = str(report.get("detected_spoken") or config.source_lang)
    needs_voice = job_needs_dub(
        config.source_lang,
        heard,
        config.target_lang,
        cues=_original_cues(work),
        enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    )
    if not config.burn:
        if not needs_voice:
            return None
        dubbed = work / "dubbed.mp4"
        if not dubbed.is_file():
            raise FileNotFoundError("previous dub missing; cannot export without re-running")
        from bilingual_sub.gui.output_path import resolve_dub_sidecar

        dest = resolve_dub_sidecar(config.output_video, config.output_srt)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dubbed.resolve() != dest.resolve():
            shutil.copy2(dubbed, dest)
        return dest
    dest = config.output_video or config.output_srt.with_suffix(".mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if needs_voice:
        dubbed = work / "dubbed.mp4"
        if not dubbed.is_file():
            raise FileNotFoundError("previous dub missing; cannot export without re-running")
        if dubbed.resolve() != dest.resolve():
            shutil.copy2(dubbed, dest)
        return dest
    prev = Path(str(report["output_mp4"])) if report.get("output_mp4") else None
    style_same = _style_same(report, config, settings)
    if prev and prev.is_file() and style_same and not report.get("dubbed"):
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
        control=control,
    )
    return dest


def _original_cues(work: Path) -> list[Cue]:
    for name in ("cues.source.json", "cues.zh.json"):
        path = work / name
        if path.is_file():
            return load_cues_json(path)
    return []


def _result_from_work(
    *,
    job_id: str,
    config: JobConfig,
    settings: AppSettings,
    work: Path,
    output_mp4: Path | None,
    output_dub: Path | None,
    ass_out: Path,
    cues: list[Cue],
    report: dict,
    stages: dict[str, float],
    elapsed: float,
    reused: bool,
) -> JobResult:
    missing = list(report.get("missing_en_samples") or [])
    payload: dict = {
        "job_id": job_id,
        "input": str(config.input_video),
        "duration_sec": report.get("duration_sec") or 0,
        "cue_count": len(cues),
        "subtitle_fit_warnings": (fit_warnings(cues, config.target_lang)
                                  if config.subtitle_mode == "netflix_single" else []),
        "missing_en_count": int(report.get("missing_en_count") or len(missing)),
        "missing_en_samples": missing[:20],
        "translate_cache_hits": int(report.get("translate_cache_hits") or 0),
        "translate_api_calls": int(report.get("translate_api_calls") or 0),
        "elapsed_sec": round(elapsed, 2),
        "stages": stages,
        "work_dir": str(work),
        "play_res": report.get("play_res") or [2560, 1600],
        "output_mp4": str(output_mp4) if output_mp4 else None,
        "output_dub": str(output_dub) if output_dub else None,
        "output_srt": str(config.output_srt),
        "input_fingerprint": video_fingerprint(config.input_video),
        "whisper_model": config.whisper_model,
        "translate_model": config.translate_model,
        "style_preset": config.style_preset,
        "subtitle_zh_color": config.subtitle_zh_color,
        "subtitle_en_color": config.subtitle_en_color,
        "subtitle_pack": SUBTITLE_PACK,
        "ui_locale": config.ui_locale,
        "source_lang": config.source_lang,
        "target_lang": config.target_lang,
        "subtitle_mode": config.subtitle_mode,
        "asr_backend": config.asr_backend,
        "refine": config.refine_translate,
        "burn": bool(config.burn),
        "source_url": config.source_url,
        "detected_spoken": report.get("detected_spoken"),
        "dubbed": bool(report.get("dubbed")),
        "tts_provider": report.get("tts_provider")
        or _resolved_tts_provider(
            config,
            detected_spoken=str(report.get("detected_spoken") or "") or None,
        ),
        "tts_fingerprint": report.get("tts_fingerprint")
        or _tts_fingerprint(
            config,
            detected_spoken=str(report.get("detected_spoken") or "") or None,
        ),
        "last_stage": "done",
        "stopped": False,
        "reused": reused,
        "processing_profile": processing_profile(config, settings),
        "render_profile": render_profile(config, settings),
    }
    report_path = work / "report.json"
    write_json(report_path, payload)
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
        output_dub=output_dub,
        translated=translation_needed(config.source_lang, config.target_lang, config.subtitle_mode),
    )


def _reexport_if_possible(
    config: JobConfig,
    settings: AppSettings,
    work: Path,
    on_progress: ProgressCb,
    t0: float,
    control: JobControl | None = None,
) -> JobResult | None:
    if not _can_reexport(config, work, settings):
        return None
    report = _load_json(work / "report.json")
    state = _load_json(work / "job_state.json")
    job_id = str(state.get("job_id") or uuid.uuid4().hex[:12])
    cues_file = work / "cues.bilingual.json"
    fitted = work / "cues.fitted.json"
    if config.subtitle_mode == "netflix_single" and fitted.is_file():
        cues_file = fitted
    cues = load_cues_json(cues_file)
    play = report.get("play_res") or [2560, 1600]
    play_res = (int(play[0]), int(play[1]))

    def prog(stage: str, pct: float) -> None:
        if on_progress:
            on_progress(stage, pct)

    logger.info("reexport job %s work_dir=%s", job_id, work)
    _validate_output_paths(config, work, include_dub=job_needs_dub(
        config.source_lang, str(report.get("detected_spoken") or config.source_lang),
        config.target_lang, cues=_original_cues(work), enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    ))
    prog("export", 0.85)
    ts = time.time()
    ass_out = _export_subs(config, work, cues, play_res)
    output_mp4 = _copy_or_burn(config, work, settings, report, control=control)
    _gate(control)
    stages = {"export_sec": time.time() - ts}
    prog("done", 1.0)
    return _result_from_work(
        job_id=job_id,
        config=config,
        settings=settings,
        work=work,
        output_mp4=output_mp4 if config.burn else None,
        output_dub=output_mp4 if not config.burn else None,
        ass_out=ass_out,
        cues=cues,
        report=report,
        stages=stages,
        elapsed=time.time() - t0,
        reused=True,
    )


def _gate(control: JobControl | None) -> None:
    if control:
        control.wait_if_paused()


def _validate_output_paths(config: JobConfig, work: Path | None = None, *, include_dub=False) -> None:
    from bilingual_sub.core.output_guard import validate_outputs
    from bilingual_sub.gui.output_path import resolve_dub_sidecar

    outputs = {"SRT": config.output_srt, "ASS": config.output_srt.with_suffix(".ass")}
    if config.burn:
        outputs["视频"] = config.output_video or config.output_srt.with_suffix(".mp4")
    elif include_dub:
        outputs["配音"] = resolve_dub_sidecar(config.output_video, config.output_srt)
    protected = [config.input_video]
    if config.glossary_path:
        protected.append(config.glossary_path)
    if config.tts_ref_audio:
        protected.append(Path(config.tts_ref_audio))
    if work is not None:
        protected.extend(work / name for name in (
            "source.mp4", "speech.wav", "transcript.json", "silences.json",
            "cues.zh.json", "cues.source.json", "cues.bilingual.json", "cues.fitted.json",
            "report.json", "job_state.json", "job_input.json", "source.url.txt",
            "source.download.json", "source.download.mp4", "source.download.pending.json",
            ".job.lock",
        ))
    validate_outputs(outputs, protected)


def _download_source(config: JobConfig, work: Path, prog, control: JobControl | None) -> Path:
    """Only associate a URL with the work copy after its download succeeds."""
    url = config.source_url or ""
    source = work / "source.mp4"
    marker = work / "source.url.txt"
    manifest = work / "source.download.json"
    saved = _load_json(manifest)
    if (source.is_file() and source.stat().st_size > 0 and marker.is_file()
            and marker.read_text(encoding="utf-8").strip() == url
            and saved.get("url") == url
            and saved.get("fingerprint") == video_fingerprint(source)):
        return source
    staging = work / "downloads" / hashlib.sha256(url.encode()).hexdigest()[:16]
    staging.mkdir(parents=True, exist_ok=True)
    downloaded = ytdlp_download(url, staging, on_progress=prog, control=control,
                               source_lang=config.source_lang)
    _gate(control)
    pending = work / "source.download.mp4"
    pending_manifest = work / "source.download.pending.json"
    try:
        shutil.copy2(downloaded, pending)
        if pending.stat().st_size == 0:
            raise RuntimeError("下载结果为空，请重试")
        _gate(control)
        # Invalidate the old identity before replacing its media. A failed
        # marker write must never leave another video's URL attached to it.
        marker.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        pending.replace(source)
        marker.write_text(url, encoding="utf-8")
        pending_manifest.write_text(json.dumps({"url": url, "fingerprint": video_fingerprint(source)},
                                               ensure_ascii=False), encoding="utf-8")
        pending_manifest.replace(manifest)
    finally:
        pending.unlink(missing_ok=True)
        pending_manifest.unlink(missing_ok=True)
    return source


def run(
    config: JobConfig,
    settings: AppSettings | None = None,
    *,
    on_progress: ProgressCb = None,
    control: JobControl | None = None,
) -> JobResult:
    if config.resume_from and config.resume_from not in STAGES:
        raise ValueError(f"未知恢复阶段：{config.resume_from}")
    _gate(control)
    _validate_output_paths(config)
    setup_logging(api_key=get_api_key())
    settings = settings or load_settings()
    t0 = time.time()

    work = _work_dir(config, settings)
    _validate_output_paths(config, work)
    lock = FileLock(str(work / ".job.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise RuntimeError(f"工作目录正在被另一任务使用：{work}；请等待该任务结束或选择其他目录") from exc
    try:
        _gate(control)
        return _run_in_work(config, settings, work, on_progress, control, t0)
    finally:
        lock.release()


def _run_in_work(config: JobConfig, settings: AppSettings, work: Path,
                 on_progress: ProgressCb, control: JobControl | None, t0: float) -> JobResult:
    stages: dict[str, float] = {}
    reused = _reexport_if_possible(config, settings, work, on_progress, t0, control=control)
    if reused:
        return reused
    state = _load_json(work / "job_state.json")
    job_id = uuid.uuid4().hex[:12]
    resume_index = _stage_index(config.resume_from) if config.resume_from else 0
    if resume_index > _stage_index("ingest"):
        completed = state.get("completed_stage", state.get("stage"))
        if completed not in STAGES or _stage_index(completed) < resume_index - 1:
            raise ValueError("恢复阶段之前的步骤尚未完成或记录缺失；请从上次完成的阶段或 ingest 重新处理")
        # Rewinding invalidates downstream completion before any new work.
        _save_state(work, STAGES[resume_index - 1], {"job_id": job_id}, control=control)
    else:
        _save_state(work, "init", {"job_id": job_id}, control=control)
    save_last_job(work, job_id)
    logger.info("job %s work_dir=%s", job_id, work)

    floor = 0.0

    def prog(stage: str, pct: float) -> None:
        nonlocal floor
        value = max(floor, float(pct))
        floor = value
        if on_progress:
            on_progress(stage, value)

    try:
        return _run_job(config, settings, on_progress, control, work, job_id, t0, stages, prog)
    except JobStopped:
        _save_state(work, "stopped", {"job_id": job_id, "stopped": True, "note": "stopped"}, control=control)
        raise


def _run_job(
    config: JobConfig,
    settings: AppSettings,
    on_progress: ProgressCb,
    control: JobControl | None,
    work: Path,
    job_id: str,
    t0: float,
    stages: dict[str, float],
    prog,
) -> JobResult:
    if _should_run(config.resume_from, "ingest"):
        _gate(control)
        if config.source_url:
            prog("ingest", 0.03)
            ts = time.time()
            config.input_video = _download_source(config, work, prog, control)
            stages["ingest_sec"] = time.time() - ts
        _save_state(work, "ingest", {"job_id": job_id}, control=control)

    input_video = config.input_video
    if not input_video.is_file():
        fallback = work / "source.mp4"
        if fallback.is_file() and config.resume_from and _resume_dir_matches(config, work, settings):
            input_video = fallback
            config.input_video = fallback
        elif config.source_url:
            prog("ingest", 0.03)
            ts = time.time()
            downloaded = _download_source(config, work, prog, control)
            config.input_video = downloaded
            input_video = downloaded
            stages["ingest_sec"] = time.time() - ts
        else:
            raise FileNotFoundError("请先选择本地视频，或填写可下载的视频链接")
    _validate_output_paths(config, work)
    if settings.video.copy_to_ascii_path:
        source = copy_to_ascii_workdir(input_video, work)
    else:
        source = input_video
        dest = work / "source.mp4"
        if source.resolve() != dest.resolve():
            shutil.copy2(input_video, dest)

    meta = probe_video(source)
    duration = float(meta.get("duration") or 0)
    play_res = (int(meta["width"]), int(meta["height"]))
    if not meta.get("has_audio"):
        raise FfmpegError(f"no audio stream in {input_video}")
    identity = {"input_fingerprint": video_fingerprint(config.input_video),
                "processing_profile": processing_profile(config, settings),
                "source_url": config.source_url,
                "source_lang": config.source_lang, "target_lang": config.target_lang,
                "subtitle_mode": config.subtitle_mode, "whisper_model": config.whisper_model,
                "translate_model": config.translate_model, "asr_backend": config.asr_backend}
    write_json(work / "job_input.json", identity)

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
    preset = _styled_preset(config)

    cache_hits = 0
    api_calls = 0
    missing: list[str] = []
    cues: list[Cue] = []

    preview_sec = config.preview_minutes * 60 if config.preview_minutes else None

    if _should_run(config.resume_from, "extract"):
        _gate(control)
        prog("extract", 0.05)
        ts = time.time()
        extract_wav(source, speech, preview_sec=preview_sec, control=control)
        stages["extract_sec"] = time.time() - ts
        _save_state(work, "extract", {"job_id": job_id}, control=control)

    if _should_run(config.resume_from, "silence"):
        _gate(control)
        prog("silence", 0.12)
        ts = time.time()
        silences = detect_silences(
            speech,
            noise_db=settings.silence.noise_db,
            min_duration=settings.silence.min_duration,
            control=control,
        )
        write_json(silences_path, silences)
        stages["silence_sec"] = time.time() - ts
        _save_state(work, "silence", {"job_id": job_id}, control=control)
    else:
        silences = _load_silences(silences_path)

    asr_lang = whisper_language(config.source_lang)
    if _should_run(config.resume_from, "transcribe"):
        _gate(control)
        prog("transcribe", 0.2)
        ts = time.time()
        used_x = False
        if config.asr_backend == "whisperx":
            backend = WhisperXBackend()
            if not backend.available():
                logger.info("正在准备内置 WhisperX 环境…")
                ensure_whisperx_runtime(control=control)
            if backend.available():
                result = backend.transcribe(
                    speech,
                    model_name=config.whisper_model or settings.asr.model,
                    language=asr_lang,
                    device=config.device or settings.asr.device,
                    out_json=transcript_path,
                    on_progress=prog,
                    control=control,
                )
                segments = result.segments
                used_x = True
            else:
                logger.warning("识别 · 已回退 whisper（未找到 WhisperX 环境）")
        if not used_x:
            segments = transcribe(
                speech,
                model_name=config.whisper_model or settings.asr.model,
                language=asr_lang,
                device=config.device or settings.asr.device,  # type: ignore[arg-type]
                out_json=transcript_path,
                on_progress=prog,
                control=control,
            )
        stages["transcribe_sec"] = time.time() - ts
        _save_state(work, "transcribe", {"job_id": job_id, "asr_backend": "whisperx" if used_x else "whisper"}, control=control)
    else:
        segments = load_transcript(transcript_path)

    if _should_run(config.resume_from, "build_cues"):
        _gate(control)
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
        save_cues_json(cues, work / "cues.source.json")
        stages["build_cues_sec"] = time.time() - ts
        _save_state(work, "build_cues", {"job_id": job_id, "cue_count": len(cues)}, control=control)
    else:
        cues = load_cues_json(cues_zh_path if cues_zh_path.is_file() else cues_bi_path)
    asr_cues = load_cues_json(cues_zh_path) if cues_zh_path.is_file() else cues
    detected_spoken = spoken_family(asr_cues, config.source_lang)
    _validate_output_paths(config, work, include_dub=job_needs_dub(
        config.source_lang, detected_spoken, config.target_lang, cues=asr_cues,
        enable_dub=config.enable_dub, tts_provider=config.tts_provider,
    ))

    if _should_run(config.resume_from, "glossary"):
        _gate(control)
        ts = time.time()
        if config.glossary_generate:
            prog("glossary", 0.52)
            from bilingual_sub.adapters.meding import create_client
            from bilingual_sub.secrets.store import get_api_key

            key = get_api_key()
            if key:
                generated = extract_glossary(
                    cues,
                    model=config.translate_model or settings.translate.model,
                    source_lang=config.source_lang,
                    target_lang=config.target_lang,
                    client=create_client(key, control=control),
                )
                generated.save(work / "glossary.generated.yaml")
                if config.glossary_path:
                    glossary = Glossary.merge(generated, glossary)
                else:
                    glossary = Glossary.merge(glossary, generated)
                glossary.save(work / "glossary.merged.yaml")
        stages["glossary_sec"] = time.time() - ts
        _save_state(work, "glossary", {"job_id": job_id}, control=control)

    if _should_run(config.resume_from, "translate"):
        _gate(control)
        prog("translate", 0.6)
        ts = time.time()
        if cues:
            heard_src = (
                detected_spoken
                if detected_spoken and detected_spoken != "auto"
                else config.source_lang
            )
            dests = job_translation_langs(
                config.source_lang,
                config.target_lang,
                config.subtitle_mode,
                detected_spoken=detected_spoken,
                cues=asr_cues,
                enable_dub=config.enable_dub,
                tts_provider=config.tts_provider,
            )
            if is_pair_mode(config.subtitle_mode):
                if config.refine_translate:
                    from bilingual_sub.adapters.meding import TranslationCache, create_client
                    from bilingual_sub.secrets.store import get_api_key

                    key = get_api_key()
                    if not key:
                        from bilingual_sub.adapters.meding import MedingAuthError

                        raise MedingAuthError("API key not configured")

                    def translator(batch, *, source_lang, target_lang, **_k):
                        return translate_cues_refined(
                            batch,
                            model=config.translate_model or settings.translate.model,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            glossary=glossary,
                            client=create_client(key, control=control),
                            cache=TranslationCache() if settings.translate.cache_enabled else None,
                            batch_size=min(10, config.translate_batch_size or settings.translate.batch_size or 10),
                            control=control,
                        )
                else:
                    def translator(batch, *, source_lang, target_lang, **_k):
                        return translate_cues(
                            batch,
                            model=config.translate_model or settings.translate.model,
                            batch_size=config.translate_batch_size or settings.translate.batch_size,
                            max_en_chars=settings.translate.max_en_chars,
                            cache_enabled=settings.translate.cache_enabled,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            glossary_block=glossary.block(),
                            control=control,
                        )

                cues, tstats, missing = translate_pair_cues(cues, translator=translator)
                extra = [lang for lang in dests if lang_family(lang) not in {"zh", "en"}]
                if extra:
                    cues, extra_stats, extra_miss = fill_translated_languages(
                        cues,
                        extra,
                        translator=translator,
                        source_lang=heard_src,
                    )
                    tstats.cache_hits += extra_stats.cache_hits
                    tstats.api_calls += extra_stats.api_calls
                    missing.extend(extra_miss)
            elif not dests:
                from bilingual_sub.core.translate import TranslateStats

                drop_target_if_unneeded(
                    cues,
                    config.source_lang,
                    config.target_lang,
                    config.subtitle_mode,
                    detected_spoken=detected_spoken,
                    enable_dub=config.enable_dub,
                    tts_provider=config.tts_provider,
                )
                tstats = TranslateStats()
                missing = []
            elif dests:
                if config.refine_translate:
                    from bilingual_sub.adapters.meding import TranslationCache, create_client
                    from bilingual_sub.secrets.store import get_api_key

                    key = get_api_key()
                    if not key:
                        from bilingual_sub.adapters.meding import MedingAuthError

                        raise MedingAuthError("API key not configured")

                    def translator(batch, *, source_lang, target_lang, **_k):
                        return translate_cues_refined(
                            batch,
                            model=config.translate_model or settings.translate.model,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            glossary=glossary,
                            client=create_client(key, control=control),
                            cache=TranslationCache() if settings.translate.cache_enabled else None,
                            batch_size=min(10, config.translate_batch_size or settings.translate.batch_size or 10),
                            control=control,
                        )
                else:
                    def translator(batch, *, source_lang, target_lang, **_k):
                        return translate_cues(
                            batch,
                            model=config.translate_model or settings.translate.model,
                            batch_size=config.translate_batch_size or settings.translate.batch_size,
                            max_en_chars=settings.translate.max_en_chars,
                            cache_enabled=settings.translate.cache_enabled,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            glossary_block=glossary.block(),
                            control=control,
                        )

                cues, tstats, missing = fill_translated_languages(
                    cues,
                    dests,
                    translator=translator,
                    source_lang=heard_src,
                )
            if is_pair_mode(config.subtitle_mode):
                assign_pair_fields(cues, config.source_lang)
                normalize_pair_fields(cues)
            han = spoken_han_lang(config.target_lang)
            if han:
                apply_han_to_cues(cues, han)
            cache_hits = tstats.cache_hits
            api_calls = tstats.api_calls
        save_cues_json(cues, cues_bi_path)
        stages["translate_sec"] = time.time() - ts
        _save_state(work, "translate", {"job_id": job_id, "missing_en": len(missing)}, control=control)
    else:
        cues = load_cues_json(cues_bi_path)

    if _should_run(config.resume_from, "fit_subs"):
        _gate(control)
        ts = time.time()
        if config.subtitle_mode == "netflix_single":
            prog("fit_subs", 0.72)
            cues = fit_cues(cues, config.target_lang, use_target=True)
        save_cues_json(cues, work / "cues.fitted.json")
        stages["fit_subs_sec"] = time.time() - ts
        _save_state(work, "fit_subs", {"job_id": job_id}, control=control)
    else:
        fitted = work / "cues.fitted.json"
        if config.subtitle_mode == "netflix_single" and fitted.is_file():
            cues = load_cues_json(fitted)

    drop_target_if_unneeded(
        cues,
        config.source_lang,
        config.target_lang,
        config.subtitle_mode,
        detected_spoken=detected_spoken,
        enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    )
    if is_pair_mode(config.subtitle_mode):
        normalize_pair_fields(cues)
    han_lang = screen_han_lang(config.source_lang, config.target_lang, config.subtitle_mode)
    spoken_han = spoken_han_lang(config.target_lang)
    if spoken_han:
        apply_han_to_cues(cues, spoken_han)

    if _should_run(config.resume_from, "render"):
        _gate(control)
        prog("render", 0.8)
        ts = time.time()
        write_subtitles(
            cues,
            preset,
            ass_path,
            srt_out,
            play_res=play_res,
            mode=config.subtitle_mode,
            han_lang=han_lang,
            target_lang=config.target_lang,
            source_lang=config.source_lang,
        )
        if ass_out != ass_path:
            shutil.copy2(ass_path, ass_out)
        stages["render_sec"] = time.time() - ts
        _save_state(work, "render", {"job_id": job_id}, control=control)
    elif ass_path.is_file() and not srt_out.is_file():
        shutil.copy2(ass_path, ass_out)

    dest_mp4 = config.output_video or srt_out.with_suffix(".mp4")
    output_mp4: Path | None = None
    output_dub: Path | None = None
    burned_mp4 = work / "burned.mp4"
    need_dub = job_needs_dub(
        config.source_lang,
        detected_spoken,
        config.target_lang,
        cues=asr_cues,
        enable_dub=config.enable_dub,
        tts_provider=config.tts_provider,
    )
    if config.burn and _should_run(config.resume_from, "burn"):
        _gate(control)
        prog("burn", 0.9)
        ts = time.time()
        burn_dest = burned_mp4 if need_dub else dest_mp4
        burn_dest.parent.mkdir(parents=True, exist_ok=True)
        dest_mp4.parent.mkdir(parents=True, exist_ok=True)
        burn_subtitles(
            source,
            ass_path,
            burn_dest,
            encoder=settings.burn.encoder,
            cq=settings.burn.cq,
            preset=settings.burn.preset,
            control=control,
        )
        if not need_dub:
            output_mp4 = dest_mp4
        stages["burn_sec"] = time.time() - ts
        _save_state(work, "burn", {"job_id": job_id}, control=control)
    elif config.burn and not need_dub and dest_mp4.is_file():
        output_mp4 = dest_mp4

    if need_dub and _should_run(config.resume_from, "dub"):
        _gate(control)
        prog("dub", 0.94)
        ts = time.time()
        from bilingual_sub.adapters.tts import select_tts

        tts_name = _resolved_tts_provider(config, asr_cues, detected_spoken=detected_spoken)
        ref_audio = config.tts_ref_audio
        from bilingual_sub.gui.output_path import resolve_dub_sidecar

        sidecar = resolve_dub_sidecar(config.output_video, srt_out)
        dub_tmp = work / "dubbed.mp4"
        try:
            if tts_name == "gptsovits":
                from bilingual_sub.adapters.tts.gptsovits import to_sovits_lang
                from bilingual_sub.adapters.tts.gptsovits_runtime import (
                    ensure_ref_audio,
                    ensure_running,
                )

                to_sovits_lang(config.target_lang)
                ensure_running(config.tts_endpoint or None, wait_sec=300, control=control)
                if not ref_audio:
                    ref_audio = str(
                        ensure_ref_audio(
                            source,
                            work / "sovits_ref.wav",
                            cues=asr_cues,
                            control=control,
                        )
                    )
            provider = select_tts(
                tts_name,
                endpoint=config.tts_endpoint,
                ref_audio=ref_audio,
                prompt_text=config.tts_prompt_text,
                prompt_lang=config.tts_prompt_lang
                or (
                    detected_spoken
                    if detected_spoken and detected_spoken != "auto"
                    else config.source_lang
                ),
            )
            if config.burn and burned_mp4.is_file():
                video_for_dub = burned_mp4
            elif config.burn and dest_mp4.is_file():
                video_for_dub = dest_mp4
            else:
                video_for_dub = source
            # Subtitle fitting changes display timing and stores only the shown
            # language. Synthesize complete translated sentences at their
            # original intervals, including when resuming directly at dub.
            speech_cues = (load_cues_json(cues_bi_path)
                           if config.subtitle_mode == "netflix_single" else cues)
            if not any(spoken_line(cue, config.target_lang) for cue in speech_cues):
                raise RuntimeError("没有目标语种台词，无法配音")
            dubbed = dub_cues(
                speech_cues,
                video=video_for_dub,
                work=work,
                output=dub_tmp,
                provider=provider,
                lang=config.target_lang,
                voice=config.tts_voice,
                duration=duration,
                control=control,
            )
            if dubbed is None or not Path(dubbed).is_file():
                raise RuntimeError("配音失败，没有生成目标语种音轨")
            if config.burn:
                dest_mp4.parent.mkdir(parents=True, exist_ok=True)
                if Path(dubbed).resolve() != dest_mp4.resolve():
                    shutil.copy2(dubbed, dest_mp4)
                output_mp4 = dest_mp4
            else:
                if Path(dubbed).resolve() != sidecar.resolve():
                    sidecar.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dubbed, sidecar)
                output_dub = sidecar
        except JobStopped:
            raise
        except Exception as exc:
            logger.warning("dub failed: %s", exc)
            raise RuntimeError(f"配音失败，成片仍是原声：{exc}") from exc
        stages["dub_sec"] = time.time() - ts
        _save_state(work, "dub", {"job_id": job_id}, control=control)

    elapsed = time.time() - t0
    report = {
        "job_id": job_id,
        "input": str(config.input_video),
        "duration_sec": duration,
        "cue_count": len(cues),
        "subtitle_fit_warnings": (fit_warnings(cues, config.target_lang)
                                  if config.subtitle_mode == "netflix_single" else []),
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
        "subtitle_zh_color": config.subtitle_zh_color,
        "subtitle_en_color": config.subtitle_en_color,
        "subtitle_pack": SUBTITLE_PACK,
        "source_lang": config.source_lang,
        "target_lang": config.target_lang,
        "subtitle_mode": config.subtitle_mode,
        "asr_backend": config.asr_backend,
        "refine": config.refine_translate,
        "burn": bool(config.burn),
        "source_url": config.source_url,
        "ui_locale": config.ui_locale,
        "detected_spoken": detected_spoken,
        "translated": translation_needed(config.source_lang, config.target_lang, config.subtitle_mode),
        "dubbed": bool(need_dub),
        "tts_provider": _resolved_tts_provider(config, asr_cues, detected_spoken=detected_spoken),
        "tts_fingerprint": _tts_fingerprint(
            config, detected_spoken=detected_spoken, cues=asr_cues
        ),
        "last_stage": "done",
        "stopped": False,
        "output_dub": str(output_dub) if output_dub else None,
        "reused": False,
        "processing_profile": processing_profile(config, settings),
        "render_profile": render_profile(config, settings),
    }
    report_path = work / "report.json"
    write_json(report_path, report)
    _save_state(work, "done", {"job_id": job_id}, control=control)

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
        output_dub=output_dub,
        translated=translation_needed(config.source_lang, config.target_lang, config.subtitle_mode),
    )
