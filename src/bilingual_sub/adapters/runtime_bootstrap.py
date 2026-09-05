"""User-local, cancellable installation; no system Python or administrator required."""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from bilingual_sub.adapters.procwin import hidden_run_kwargs, terminate_process_tree
from bilingual_sub.config import user_config_dir
from bilingual_sub.core.control import JobControl

logger = logging.getLogger(__name__)
Progress = Callable[[str], None] | None


def auto_install_enabled() -> bool:
    return os.environ.get("SUBFLOW_AUTO_INSTALL", "1") != "0"


def runtime_root() -> Path:
    override = os.environ.get("SUBFLOW_RUNTIME_DIR", "").strip()
    return Path(override).expanduser() if override else user_config_dir() / "managed"


def bootstrap_assets() -> Path:
    return Path(__file__).resolve().parents[1] / "_data" / "bootstrap"


def torch_backend() -> str:
    backend = os.environ.get("SUBFLOW_TORCH_BACKEND", "cpu").lower()
    if backend not in {"cpu", "cuda"}:
        raise ValueError("SUBFLOW_TORCH_BACKEND must be cpu or cuda")
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


def _run(args: list[str], log: Path, control: JobControl | None, *, env=None, cwd=None) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    if control:
        control.wait_if_paused()
    with log.open("ab") as stream:
        proc = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT,
                                env=env or install_env(), cwd=cwd, **hidden_run_kwargs())
        try:
            if control:
                control.attach_proc(proc)
            while proc.poll() is None:
                if control:
                    control.wait_if_paused()
                try:
                    proc.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            if control:
                control.check()
            if proc.returncode:
                tail = log.read_text(encoding="utf-8", errors="replace")[-1600:]
                raise RuntimeError(f"自动安装失败；可重试。日志：{log}\n{tail}")
        finally:
            if proc.poll() is None:
                terminate_process_tree(proc)
                proc.wait(timeout=10)
            if control:
                control.detach_proc(proc)


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
    with _locked(root / f"{kind}.lock", control):
        if python.is_file() and marker.is_file() and marker.read_text() == stamp:
            return python
        if not auto_install_enabled():
            raise RuntimeError("自动安装已关闭（SUBFLOW_AUTO_INSTALL=0）且运行环境尚未准备")
        uv = str(find_uv())
        log = root / f"install-{kind}.log"
        _progress(progress, "首次运行：正在自动准备 Python 3.11（后续使用缓存）…")
        if not python.is_file():
            _run([uv, "python", "install", "3.11", "--no-bin", "--no-registry"], log, control)
            _run([uv, "venv", "--managed-python", "--python", "3.11", "--seed", str(python.parent.parent)], log, control)
        _progress(progress, f"正在安装 {kind} 依赖（{torch_backend().upper()}），首次下载可能需要数分钟…")
        torch_args = [uv, "pip", "install", "--python", str(python), f"torch=={version}", f"torchaudio=={version}"]
        if sys.platform != "darwin" and platform.machine().lower() in {"x86_64", "amd64"}:
            torch_args.extend(["--index-url", "https://download.pytorch.org/whl/" + ("cu124" if torch_backend() == "cuda" else "cpu")])
        _run(torch_args, log, control)
        constraints = root / f"torch-{version}.txt"
        constraints.write_text(f"torch=={version}\ntorchaudio=={version}\n", encoding="utf-8")
        args = [uv, "pip", "install", "--python", str(python), "-r", str(requirements)]
        args += ["-c", str(constraints)]
        _run(args, log, control)
        module = {"asr": "whisper", "gptsovits": "torch, torchaudio, fastapi, pyopenjtalk, jieba", "whisperx": "whisperx"}[kind]
        _run([str(python), "-c", f"import {module}"], log, control)
        marker.write_text(stamp, encoding="utf-8")
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
        if not (home / "api_v2.py").is_file():
            if source is None:
                raise RuntimeError("客户端缺少 GPT-SoVITS 源码，请重新下载完整客户端")
            copy_runtime_tree(source, home)
        python = ensure_python_env("gptsovits", control=control, progress=progress)
        if models and (missing_pretrained(home) or not (home / ".subflow-assets-v1").is_file()):
            _progress(progress, "正在下载并校验配音模型与语言数据，下载完成后会自动启动…")
            env = install_env()
            env["NLTK_DATA"] = str(home / "nltk_data")
            _run([str(python), str(bootstrap_assets() / "download_assets.py"), str(home)],
                 runtime_root() / "install-models.log", control, env=env)
            missing = missing_pretrained(home)
            if missing:
                raise RuntimeError("模型下载不完整：" + "; ".join(missing))
            (home / ".subflow-assets-v1").write_text("ready", encoding="utf-8")
    return home
