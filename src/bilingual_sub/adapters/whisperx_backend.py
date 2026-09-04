from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.adapters.asr_protocol import AsrResult
from bilingual_sub.adapters.procwin import gui_python, hidden_run_kwargs
from bilingual_sub.adapters.whisper_backend import (
    _python_candidates,
    _python_has_module,
    load_transcript,
    runtime_home,
)
from bilingual_sub.core.control import JobControl, JobStopped
from bilingual_sub.core.langs import whisper_language

logger = logging.getLogger(__name__)


def worker_script() -> Path:
    here = Path(__file__).with_name("whisperx_worker.py")
    if here.is_file():
        return here
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cand = Path(meipass) / "bilingual_sub" / "adapters" / "whisperx_worker.py"
        if cand.is_file():
            return cand
    raise RuntimeError("whisperx_worker.py missing")


def find_whisperx_python() -> Path | None:
    for cand in _python_candidates():
        if _python_has_module(cand, "whisperx"):
            return cand
    return None


def should_provision_whisperx() -> bool:
    flag = os.environ.get("SUBFLOW_PROVISION_WX", "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    return bool(getattr(sys, "frozen", False))


def _host_python() -> list[str] | None:
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher:
            return [launcher, "-3"]
    host = shutil.which("python") or shutil.which("python3")
    return [host] if host else None


def ensure_whisperx_runtime() -> Path | None:
    found = find_whisperx_python()
    if found:
        return found
    if not should_provision_whisperx():
        return None
    host = _host_python()
    if host is None:
        logger.warning("no host Python to provision WhisperX runtime")
        return None
    dest = runtime_home()
    py = dest / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not py.is_file():
            logger.info("creating WhisperX runtime at %s", dest)
            subprocess.run([*host, "-m", "venv", str(dest)], check=True, timeout=180, **hidden_run_kwargs())
        pip = [str(gui_python(py)), "-m", "pip"]
        subprocess.run([*pip, "install", "-U", "pip"], check=True, timeout=180, **hidden_run_kwargs())
        subprocess.run(
            [*pip, "install", "torch", "openai-whisper", "whisperx"],
            check=True,
            timeout=1800,
            **hidden_run_kwargs(),
        )
    except Exception:
        logger.exception("provision WhisperX runtime failed")
        return None
    return py if _python_has_module(py, "whisperx") else None


def whisperx_available(python: Path | None = None) -> bool:
    if python is None:
        return find_whisperx_python() is not None
    return _python_has_module(python, "whisperx")


class WhisperXBackend:
    name = "whisperx"

    def available(self) -> bool:
        return whisperx_available()

    def transcribe(
        self,
        wav: Path,
        *,
        model_name: str,
        language: str,
        device: str,
        out_json: Path,
        on_progress: Callable[[str, float], None] | None = None,
        control: JobControl | None = None,
    ) -> AsrResult:
        python = find_whisperx_python()
        if python is None:
            raise RuntimeError("WhisperX 不可用")
        script = worker_script()
        log_path = out_json.with_name("whisperx.log")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [
                    str(gui_python(python)),
                    str(script),
                    "--wav",
                    str(wav),
                    "--out",
                    str(out_json),
                    "--model",
                    model_name,
                    "--language",
                    whisper_language(language),
                    "--device",
                    device,
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                **hidden_run_kwargs(),
            )
        if control:
            control.attach_proc(proc)
        started = time.time()
        while proc.poll() is None:
            if control:
                control.wait_if_paused()
            if on_progress:
                elapsed = time.time() - started
                on_progress("transcribe", 0.20 + min(0.24, elapsed / 900.0 * 0.24))
            time.sleep(1.5)
        if control and control.is_stopped():
            raise JobStopped()
        if proc.returncode != 0:
            detail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:] if log_path.is_file() else ""
            raise RuntimeError(f"WhisperX 失败：{detail or proc.returncode}")
        segments = load_transcript(out_json)
        lang = whisper_language(language)
        if out_json.is_file():
            try:
                import json

                meta = json.loads(out_json.read_text(encoding="utf-8"))
                lang = str(meta.get("language") or lang)
            except (OSError, ValueError):
                pass
        return AsrResult(language=lang, segments=segments, detected_language=lang, backend="whisperx")
