from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bilingual_sub.adapters.procwin import gui_python, hidden_run_kwargs
from bilingual_sub.core.control import JobStopped
from bilingual_sub.models import Segment, WordSpan

logger = logging.getLogger(__name__)


def _whisper_language(language: str | None) -> str | None:
    raw = (language or "").strip().lower()
    if raw in {"", "auto"}:
        return None
    return language

MISSING_WHISPER_MSG = (
    "未找到可用的 Whisper 识别环境。客户端不内置 Torch。\n"
    "请任选其一：\n"
    "1. 在本机 Python 安装：pip install openai-whisper torch\n"
    "2. 设置环境变量 SUBFLOW_PYTHON，指向已安装 Whisper 的 python.exe"
)


def cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available() and torch.cuda.device_count() > 0)
    except Exception:
        return False


def has_nvidia_gpu() -> bool:
    smi = shutil.which("nvidia-smi")
    if not smi:
        return False
    try:
        proc = subprocess.run(
            [smi, "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0 and "GPU" in out


def resolve_device(requested: str) -> str:
    req = (requested or "auto").strip().lower()
    if req == "cpu":
        return "cpu"
    if cuda_available() and req in {"auto", "cuda"}:
        return "cuda"
    if req == "cuda":
        logger.warning("CUDA unavailable; falling back to CPU")
    return "cpu"


def default_whisper_model() -> str:
    return "medium" if cuda_available() or has_nvidia_gpu() else "small"


def load_whisper_model(model_name: str, device: str):
    import whisper

    dev = resolve_device(device)
    try:
        return whisper.load_model(model_name, device=dev), dev
    except Exception as exc:
        if dev == "cuda":
            logger.warning("Whisper CUDA load failed (%s); using CPU", exc)
            return whisper.load_model(model_name, device="cpu"), "cpu"
        raise


def worker_script() -> Path:
    here = Path(__file__).with_name("whisper_worker.py")
    if here.is_file():
        return here
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        roots.append(Path(sys.executable).resolve().parent / "_internal")
    for root in roots:
        for rel in (
            Path("bilingual_sub") / "adapters" / "whisper_worker.py",
            Path("whisper_worker.py"),
        ):
            cand = root / rel
            if cand.is_file():
                return cand
    raise RuntimeError("whisper_worker.py missing from the client bundle")


def runtime_home() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "SubFlow" / "runtime"
    return Path.home() / ".local" / "share" / "subflow" / "runtime"


def _runtime_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        roots.extend((exe / "runtime", exe / "_internal" / "runtime"))
    else:
        roots.append(Path(__file__).resolve().parents[3] / "runtime")
    roots.append(runtime_home())
    return roots


def _cache_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home())) / "SubFlow"
    else:
        root = Path.home() / ".config" / "subflow"
    return root / "whisper-python.txt"


def _python_candidates() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path | str | None) -> None:
        if not path:
            return
        p = Path(path)
        key = os.path.normcase(str(p))
        if key in seen or not p.is_file():
            return
        seen.add(key)
        found.append(p)

    add(os.environ.get("SUBFLOW_PYTHON") or os.environ.get("SUBFLOW_WHISPER_PYTHON"))
    from bilingual_sub.adapters.runtime_bootstrap import managed_python

    add(managed_python("asr"))
    cached = _cache_path()
    if cached.is_file():
        add(cached.read_text(encoding="utf-8").strip())
    for root in _runtime_roots():
        add(root / "python.exe")
        add(root / "Scripts" / "python.exe")
        add(root / "bin" / "python3")
        add(root / "bin" / "python")
    if not getattr(sys, "frozen", False):
        add(sys.executable)
    for name in ("python", "python3"):
        add(shutil.which(name))
    home = Path.home()
    if os.name == "nt":
        add(home / ".agent-reach-venv" / "Scripts" / "python.exe")
        add(home / ".venv" / "Scripts" / "python.exe")
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python"
        if local.is_dir():
            for child in sorted(local.glob("Python*/python.exe")):
                add(child)
        py = shutil.which("py")
        if py:
            try:
                probe = subprocess.run(
                    [py, "-3", "-c", "import sys; print(sys.executable)"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    **hidden_run_kwargs(),
                )
                if probe.returncode == 0:
                    add(probe.stdout.strip())
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        add(home / ".agent-reach-venv" / "bin" / "python")
        add(home / ".venv" / "bin" / "python")
        add(home / ".local" / "bin" / "python3")
    return found


def _python_has_module(python: Path, module: str) -> bool:
    try:
        proc = subprocess.run(
            [str(gui_python(python)), "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=12,
            **hidden_run_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _python_has_whisper(python: Path) -> bool:
    return _python_has_module(python, "whisper")


def find_whisper_python() -> Path | None:
    for cand in _python_candidates():
        if _python_has_whisper(cand):
            try:
                cache = _cache_path()
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(str(cand), encoding="utf-8")
            except OSError:
                pass
            return cand
    return None


def _transcribe_inprocess(
    wav: Path,
    *,
    model_name: str,
    language: str,
    device: str,
    out_json: Path | None,
) -> list[Segment]:
    model, dev = load_whisper_model(model_name, device)
    logger.info("loading whisper model=%s device=%s", model_name, dev)
    result: dict[str, Any] = model.transcribe(
        str(wav),
        language=_whisper_language(language),
        fp16=dev == "cuda",
        word_timestamps=False,
        verbose=False,
        condition_on_previous_text=True,
        no_speech_threshold=0.4,
    )
    segments: list[Segment] = []
    clean: dict[str, Any] = {"language": result.get("language"), "segments": []}
    for seg in result.get("segments") or []:
        text = (seg.get("text") or "").strip()
        start = float(seg.get("start") or 0)
        end = float(seg.get("end") or 0)
        segments.append(Segment(start=start, end=end, text=text))
        clean["segments"].append(
            {
                "start": start,
                "end": end,
                "text": text,
                "words": seg.get("words") or [],
            }
        )
    if out_json:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("transcribed %d segments", len(segments))
    return segments


def _transcribe_external(
    python: Path,
    wav: Path,
    *,
    model_name: str,
    language: str,
    device: str,
    out_json: Path,
    on_progress: Callable[[str, float], None] | None = None,
    control=None,
) -> list[Segment]:
    script = worker_script()
    runner = gui_python(python)
    log_path = out_json.with_name("whisper.log")
    logger.info("whisper via %s (%s)", runner, script)
    from bilingual_sub.adapters.runtime_bootstrap import inference_env

    env = inference_env()
    env["TQDM_DISABLE"] = "1"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [
                str(runner),
                str(script),
                "--wav",
                str(wav),
                "--out",
                str(out_json),
                "--model",
                model_name,
                "--language",
                _whisper_language(language) or "auto",
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
        elapsed = time.time() - started
        pct = 0.20 + min(0.24, elapsed / 900.0 * 0.24)
        if on_progress:
            on_progress("transcribe", pct)
        time.sleep(1.5)
    if control and control.is_stopped():
        raise JobStopped()
    if proc.returncode != 0:
        detail = ""
        if log_path.is_file():
            detail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-2000:]
        raise RuntimeError(f"Whisper 外部识别失败：{detail or f'exit {proc.returncode}'}")
    if on_progress:
        on_progress("transcribe", 0.44)
    return load_transcript(out_json)


def transcribe(
    wav: Path,
    *,
    model_name: str = "medium",
    language: str = "zh",
    device: str = "auto",
    out_json: Path | None = None,
    on_progress: Callable[[str, float], None] | None = None,
    control=None,
) -> list[Segment]:
    if control:
        control.wait_if_paused()
    try:
        import whisper  # noqa: F401

        if on_progress:
            on_progress("transcribe", 0.22)
        result = _transcribe_inprocess(
            wav,
            model_name=model_name,
            language=language,
            device=device,
            out_json=out_json,
        )
        if control:
            control.check()
        return result
    except ImportError:
        python = find_whisper_python()
        if python is None:
            from bilingual_sub.adapters.runtime_bootstrap import (
                auto_install_enabled,
                ensure_python_env,
            )

            if not auto_install_enabled():
                raise RuntimeError(MISSING_WHISPER_MSG) from None
            python = ensure_python_env("asr", control=control,
                progress=lambda message: on_progress(message, 0.20) if on_progress else None)
        target = out_json or (wav.with_name(wav.stem + ".transcript.json"))
        return _transcribe_external(
            python,
            wav,
            model_name=model_name,
            language=language,
            device=device,
            out_json=target,
            on_progress=on_progress,
            control=control,
        )


def load_transcript(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segs = []
    for seg in data.get("segments") or []:
        words = []
        for raw in seg.get("words") or []:
            try:
                words.append(
                    WordSpan(
                        start=float(raw.get("start") or 0),
                        end=float(raw.get("end") or 0),
                        text=str(raw.get("word") or raw.get("text") or "").strip(),
                        score=float(raw["score"]) if raw.get("score") is not None else None,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        segs.append(
            Segment(
                start=float(seg["start"]),
                end=float(seg["end"]),
                text=str(seg.get("text") or "").strip(),
                words=tuple(w for w in words if w.text),
            )
        )
    return segs


def probe_whisper(model_name: str = "tiny", device: str = "auto") -> bool:
    try:
        import whisper

        dev = resolve_device(device)
        whisper.load_model(model_name, device=dev)
        return True
    except ImportError:
        return find_whisper_python() is not None
    except Exception as exc:
        logger.warning("whisper probe failed: %s", exc)
        return False
