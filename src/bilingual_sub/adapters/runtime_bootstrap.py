"""User-local, cancellable installation; no system Python or administrator required."""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.config import user_config_dir
from bilingual_sub.core.control import JobControl, JobStopped, wait_for_process

logger = logging.getLogger(__name__)
Progress = Callable[[str], None] | None


def auto_install_enabled() -> bool:
    return os.environ.get("SUBFLOW_AUTO_INSTALL", "1") != "0"


def runtime_root() -> Path:
    override = os.environ.get("SUBFLOW_RUNTIME_DIR", "").strip()
    return Path(override).expanduser().resolve() if override else user_config_dir() / "managed"


def bootstrap_assets() -> Path:
    return Path(__file__).resolve().parents[1] / "_data" / "bootstrap"


def torch_backend() -> str:
    apple = sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    backend = os.environ.get("SUBFLOW_TORCH_BACKEND", "mps" if apple else "cpu").strip().lower()
    if backend not in {"cpu", "cuda", "mps"}:
        raise ValueError("SUBFLOW_TORCH_BACKEND must be cpu, cuda or mps")
    if backend == "mps" and not apple:
        raise ValueError("MPS automatic installation requires a native Apple Silicon macOS client")
    if backend == "cuda" and (sys.platform == "darwin" or platform.machine().lower() not in {"amd64", "x86_64"}):
        raise ValueError("CUDA wheels require Windows/Linux x86_64; use cpu on this platform")
    return backend


def managed_env(kind: str) -> Path:
    if kind not in {"asr", "gptsovits", "whisperx"}:
        raise ValueError(f"Unknown runtime: {kind}")
    return runtime_root() / f"{kind}-{torch_backend()}-py311-v1"


def managed_python(kind: str) -> Path:
    return managed_env(kind) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def find_uv() -> Path:
    name = "uv.exe" if os.name == "nt" else "uv"
    if getattr(sys, "frozen", False):
        for root in (Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent):
            path = root / name
            if path.is_file():
                return path
    found = shutil.which("uv")
    if found:
        return Path(found)
    raise RuntimeError("缺少内置 uv 安装器，请重新下载完整客户端；源码安装请执行 pip install -e .")


def install_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", UV_NO_CONFIG="1",
               UV_PYTHON_INSTALL_DIR=str(runtime_root() / "python"),
               UV_CACHE_DIR=str(runtime_root() / "download-cache"))
    env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    # Frozen Qt search paths must never shadow an external interpreter's DLLs.
    if getattr(sys, "frozen", False):
        frozen = str(Path(getattr(sys, "_MEIPASS", "")).resolve()).lower()
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep)
                                     if not p.lower().startswith(frozen))
    return env


def inference_env() -> dict[str, str]:
    from bilingual_sub.adapters.ffmpeg import find_ffmpeg

    env = install_env()
    env["PATH"] = str(Path(find_ffmpeg()).parent) + os.pathsep + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _run(args: list[str], log: Path, control: JobControl | None, *, env=None, cwd=None,
         timeout: float | None = None) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    if control:
        control.wait_if_paused()
    with log.open("ab") as stream:
        deadline = time.monotonic() + timeout if timeout is not None else None
        def check_timeout():
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError(f"环境检查超时；可重试。日志：{log}")
        with owned_process(args, stdout=stream, stderr=subprocess.STDOUT,
                           env=env if env is not None else install_env(), cwd=cwd) as proc:
            code = wait_for_process(proc, control=control, on_tick=check_timeout)
            if code:
                with log.open("rb") as reader:
                    reader.seek(max(0, log.stat().st_size - 6400))
                    tail = reader.read().decode("utf-8", errors="replace")[-1600:]
                raise RuntimeError(f"自动安装失败；可重试。日志：{log}\n{tail}")


def _progress(callback: Progress, message: str) -> None:
    logger.info(message)
    if callback:
        callback(message)


@contextmanager
def _locked(path: Path, control: JobControl | None):
    lock = FileLock(str(path))
    while True:
        if control:
            control.wait_if_paused()
        try:
            lock.acquire(timeout=0.2)
            break
        except Timeout:
            continue
    try:
        yield
    finally:
        lock.release()


def ensure_python_env(kind: str, *, control: JobControl | None = None, progress: Progress = None) -> Path:
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    assets = bootstrap_assets()
    requirements = assets / f"{kind}.txt"
    version = "2.2.2" if sys.platform == "darwin" and platform.machine() == "x86_64" else "2.5.1"
    stamp = hashlib.sha256(requirements.read_bytes() + f"{version}|{torch_backend()}|v1".encode()).hexdigest()
    python = managed_python(kind)
    marker = managed_env(kind) / ".subflow-ready"
    log = root / f"install-{kind}.log"
    module = {
        "asr": "torch, torchaudio, whisper",
        "gptsovits": (
            "torch, torchaudio, fastapi, uvicorn, soundfile, numpy, librosa, yaml, "
            "onnxruntime, transformers, pyopenjtalk, jieba"
        ),
        "whisperx": "torch, whisperx",
    }[kind]
    check = [str(python), "-c", f"import {module}"]
    with _locked(root / f"{kind}.lock", control):
        repair = python.is_file()
        if python.is_file() and marker.is_file() and marker.read_text(errors="replace") == stamp:
            try:
                _run(check, log, control, timeout=90)
                return python
            except JobStopped:
                raise
            except (OSError, RuntimeError) as exc:
                if not auto_install_enabled():
                    raise RuntimeError("运行环境已损坏，自动安装已关闭（SUBFLOW_AUTO_INSTALL=0）") from exc
                _progress(progress, "运行环境检查失败，正在修复依赖…")
                repair = True
        if not auto_install_enabled():
            raise RuntimeError("自动安装已关闭（SUBFLOW_AUTO_INSTALL=0）且运行环境尚未准备")
        uv = str(find_uv())
        marker.unlink(missing_ok=True)
        _progress(progress, "首次运行：正在自动准备 Python 3.11（后续使用缓存）…")
        if not python.is_file() or repair:
            _run([uv, "python", "install", "3.11", "--no-bin", "--no-registry"], log, control)
            _run([uv, "venv", "--allow-existing", "--managed-python", "--python", "3.11", "--seed", str(python.parent.parent)], log, control)
        _progress(progress, f"正在安装 {kind} 依赖（{torch_backend().upper()}），首次下载可能需要数分钟…")
        torch_args = [uv, "pip", "install", "--python", str(python), f"torch=={version}", f"torchaudio=={version}"]
        if repair:
            torch_args.append("--reinstall")
        if sys.platform != "darwin" and platform.machine().lower() in {"x86_64", "amd64"}:
            torch_args.extend(["--index-url", "https://download.pytorch.org/whl/" + ("cu124" if torch_backend() == "cuda" else "cpu")])
        _run(torch_args, log, control)
        constraints = root / f"torch-{version}.txt"
        constraints.write_text(f"torch=={version}\ntorchaudio=={version}\n", encoding="utf-8")
        args = [uv, "pip", "install", "--python", str(python), "-r", str(requirements)]
        if repair:
            args.append("--reinstall")
        args += ["-c", str(constraints)]
        _run(args, log, control)
        _run(check, log, control, timeout=90)
        pending_marker = marker.with_name(marker.name + ".pending")
        try:
            pending_marker.write_text(stamp, encoding="utf-8")
            pending_marker.replace(marker)
        finally:
            pending_marker.unlink(missing_ok=True)
    return python


def ensure_sovits_runtime(*, control: JobControl | None = None, progress: Progress = None,
                          models: bool = True) -> Path:
    from bilingual_sub.adapters.tts.gptsovits_runtime import (
        bundled_src,
        copy_runtime_tree,
        default_home,
        missing_pretrained,
    )

    home = default_home()
    runtime_root().mkdir(parents=True, exist_ok=True)
    with _locked(runtime_root() / "gptsovits-home.lock", control):
        source = bundled_src()
        if not (home / "api_v2.py").is_file() or source_update_needed(home):
            if not auto_install_enabled():
                raise RuntimeError("自动安装已关闭（SUBFLOW_AUTO_INSTALL=0），配音源码尚未准备")
            if source is None:
                raise RuntimeError("客户端缺少 GPT-SoVITS 源码，请重新下载完整客户端")
            copy_runtime_tree(source, home)
            from bilingual_sub.__version__ import __version__

            (home / ".subflow-source-version").write_text(__version__, encoding="utf-8")
        python = ensure_python_env("gptsovits", control=control, progress=progress)
        from bilingual_sub._data.bootstrap.download_assets import assets_ready

        if models and (missing_pretrained(home) or not assets_ready(home)):
            if not auto_install_enabled():
                raise RuntimeError("自动安装已关闭（SUBFLOW_AUTO_INSTALL=0），配音资源需要修复")
            _progress(progress, "正在下载并校验配音模型与语言数据，下载完成后会自动启动…")
            env = install_env()
            env["NLTK_DATA"] = str(home / "nltk_data")
            _run([str(python), str(bootstrap_assets() / "download_assets.py"), str(home)],
                 runtime_root() / "install-models.log", control, env=env)
            missing = missing_pretrained(home)
            if missing or not assets_ready(home):
                raise RuntimeError("模型下载不完整：" + "; ".join(missing))
    return home


def assets_update_needed(home: Path) -> bool:
    from bilingual_sub._data.bootstrap.download_assets import assets_ready
    from bilingual_sub.adapters.tts.gptsovits_runtime import default_home

    if os.environ.get("SUBFLOW_GPTSOVITS_HOME", "").strip() or home != default_home():
        return False
    return not assets_ready(home)


def source_update_needed(home: Path) -> bool:
    """Update SubFlow-managed cached source while preserving user-selected installations."""
    from bilingual_sub.__version__ import __version__
    from bilingual_sub.adapters.tts.gptsovits_runtime import bundled_src, default_home

    if os.environ.get("SUBFLOW_GPTSOVITS_HOME", "").strip() or home != default_home():
        return False
    if bundled_src() is None:
        return False
    marker = home / ".subflow-source-version"
    return not marker.is_file() or marker.read_text(encoding="utf-8") != __version__
