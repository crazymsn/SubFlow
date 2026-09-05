from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.adapters.procwin import gui_python, hidden_run_kwargs
from bilingual_sub.adapters.torch_device import (
    load_whisper_on_device,
    mps_available,
    select_device,
    transcribe_with_fallback,
)
from bilingual_sub.adapters.transcript_io import (
    normalize_transcript,
    read_transcript,
    write_transcript,
)
from bilingual_sub.core.control import wait_for_process
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
    return select_device(requested, cuda=cuda_available(), mps=mps_available())


def default_whisper_model() -> str:
    return "medium" if cuda_available() or has_nvidia_gpu() else "small"


def load_whisper_model(model_name: str, device: str):
    import whisper

    dev = resolve_device(device)
    try:
        return load_whisper_on_device(whisper, model_name, dev), dev
    except Exception as exc:
        if dev in {"cuda", "mps"}:
            logger.warning("Whisper %s load failed (%s); using CPU", dev, exc)
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
    from bilingual_sub.adapters.runtime_bootstrap import (
        auto_install_enabled,
        managed_python,
        torch_backend,
    )

    explicit = os.environ.get("SUBFLOW_PYTHON") or os.environ.get("SUBFLOW_WHISPER_PYTHON")
    # An Intel interpreter cached by an older app can run under Rosetta but
    # cannot use Apple GPU. Prepare the native managed environment on upgrade.
    if torch_backend() == "mps" and auto_install_enabled() and not explicit:
        candidates = [managed_python("asr")]
    else:
        candidates = _python_candidates()
    for cand in candidates:
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
    control=None,
) -> list[Segment]:
    model, dev = load_whisper_model(model_name, device)
    logger.info("loading whisper model=%s device=%s", model_name, dev)
    result, dev = transcribe_with_fallback(
        model, dev, str(wav),
        language=_whisper_language(language),
        word_timestamps=False,
        verbose=False,
        condition_on_previous_text=True,
        no_speech_threshold=0.4,
    )
    clean = normalize_transcript(result)
    if control:
        control.check()
    if out_json:
        write_transcript(out_json, clean, before_commit=control.check if control else None)
    segments = _segments_from_payload(clean)
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
    data = run_asr_worker(python, worker_script(), wav, model_name=model_name,
        language=_whisper_language(language) or "auto", device=device, out_json=out_json,
        backend="whisper", on_progress=on_progress, control=control)
    return _segments_from_payload(data)


def run_asr_worker(python: Path, script: Path, wav: Path, *, model_name: str,
                   language: str, device: str, out_json: Path, backend: str,
                   on_progress=None, control=None) -> dict:
    from bilingual_sub.adapters.runtime_bootstrap import inference_env

    if control:
        control.wait_if_paused()
    out_json.parent.mkdir(parents=True, exist_ok=True)
    log_path = out_json.with_name(f"{backend}.log")
    env = inference_env()
    env["TQDM_DISABLE"] = "1"
    started = time.monotonic()
    def tick():
        if on_progress:
            elapsed = time.monotonic() - started
            on_progress("transcribe", 0.20 + min(0.24, elapsed / 900.0 * 0.24))
    # Every invocation requires a fresh result, even when a worker exits zero
    # without producing output. A previous transcript remains untouched.
    with tempfile.TemporaryDirectory(prefix=".asr-", dir=out_json.parent) as scratch:
        pending = Path(scratch) / "transcript.json"
        with log_path.open("wb") as log, owned_process([
            str(gui_python(python)), str(script), "--wav", str(wav), "--out", str(pending),
            "--model", model_name, "--language", language, "--device", device,
        ], stdout=log, stderr=subprocess.STDOUT, env=env) as proc:
            code = wait_for_process(proc, control=control, on_tick=tick)
        if code:
            with log_path.open("rb") as stream:
                stream.seek(max(0, log_path.stat().st_size - 8192))
                detail = stream.read().decode("utf-8", "replace")[-2000:]
            raise RuntimeError(f"{backend} 外部识别失败：{detail or f'exit {code}'}")
        if not pending.is_file():
            raise RuntimeError(f"{backend} 识别进程未生成本次结果")
        data = read_transcript(pending)
        if control:
            control.check()
        if on_progress:
            on_progress("transcribe", 0.44)
        if control:
            control.check()
        write_transcript(out_json, data, before_commit=control.check if control else None)
        return data


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
            control=control,
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


def _segments_from_payload(data: dict) -> list[Segment]:
    return [Segment(start=seg["start"], end=seg["end"], text=seg["text"],
                    words=tuple(WordSpan(**word) for word in seg["words"]))
            for seg in data["segments"]]


def load_transcript(path: Path) -> list[Segment]:
    return _segments_from_payload(read_transcript(path))


def probe_whisper(model_name: str = "tiny", device: str = "auto") -> bool:
    try:
        load_whisper_model(model_name, device)
        return True
    except ImportError:
        return find_whisper_python() is not None
    except Exception as exc:
        logger.warning("whisper probe failed: %s", exc)
        return False
