from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.adapters.asr_protocol import AsrResult
from bilingual_sub.adapters.procwin import gui_python, hidden_run_kwargs
from bilingual_sub.adapters.whisper_backend import find_whisper_python, load_transcript
from bilingual_sub.core.control import JobControl
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


def whisperx_available(python: Path | None = None) -> bool:
    runner = python or find_whisper_python()
    if runner is None:
        return False
    try:
        proc = subprocess.run(
            [str(gui_python(runner)), "-c", "import whisperx"],
            capture_output=True,
            text=True,
            timeout=12,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


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
        python = find_whisper_python()
        if python is None or not whisperx_available(python):
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
                control.check()
            if on_progress:
                elapsed = time.time() - started
                on_progress("transcribe", 0.20 + min(0.24, elapsed / 900.0 * 0.24))
            time.sleep(1.5)
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
