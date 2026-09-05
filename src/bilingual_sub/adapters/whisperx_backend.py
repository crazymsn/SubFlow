from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.adapters.asr_protocol import AsrResult
from bilingual_sub.adapters.whisper_backend import (
    _python_candidates,
    _python_has_module,
    _segments_from_payload,
    run_asr_worker,
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
    from bilingual_sub.adapters.runtime_bootstrap import managed_python

    for cand in [managed_python("whisperx"), *_python_candidates()]:
        if not cand.is_file():
            continue
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


def ensure_whisperx_runtime(control: JobControl | None = None) -> Path | None:
    found = find_whisperx_python()
    if found:
        return found
    if not should_provision_whisperx():
        return None
    from bilingual_sub.adapters.runtime_bootstrap import auto_install_enabled, ensure_python_env

    if not auto_install_enabled():
        return None
    try:
        py = ensure_python_env("whisperx", control=control)
    except JobStopped:
        raise
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
        data = run_asr_worker(python, worker_script(), wav, model_name=model_name,
            language=whisper_language(language), device=device, out_json=out_json,
            backend="whisperx", on_progress=on_progress, control=control)
        lang = data.get("language") or whisper_language(language)
        return AsrResult(language=lang, segments=_segments_from_payload(data), detected_language=lang, backend="whisperx")
