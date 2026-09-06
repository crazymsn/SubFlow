"""User-local, cancellable installation; no system Python or administrator required."""
from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from filelock import FileLock, Timeout

from bilingual_sub.adapters import installer as _installer
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


@lru_cache(maxsize=1)
def _cuda_driver_available() -> bool:
    """Detect CUDA without importing the GUI's (possibly CPU-only) PyTorch."""
    try:
        driver = (ctypes.WinDLL("nvcuda.dll", winmode=0x800) if sys.platform == "win32"
                  else ctypes.CDLL("libcuda.so.1"))
        version, count = ctypes.c_int(), ctypes.c_int()
        return (driver.cuInit(0) == 0
                and driver.cuDriverGetVersion(ctypes.byref(version)) == 0
                and version.value >= 12000
                and driver.cuDeviceGetCount(ctypes.byref(count)) == 0
                and count.value > 0)
    except (OSError, AttributeError):
        return False


def torch_backend() -> str:
    apple = sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    backend = os.environ.get("SUBFLOW_TORCH_BACKEND", "auto").strip().lower() or "auto"
    if backend == "auto":
        if apple:
            return "mps"
        cuda_platform = sys.platform in {"win32", "linux"} and platform.machine().lower() in {"amd64", "x86_64"}
        hidden = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip() == "-1" or os.environ.get("CUDA_VISIBLE_DEVICES") == ""
        return "cuda" if cuda_platform and not hidden and _cuda_driver_available() else "cpu"
    if backend not in {"cpu", "cuda", "mps"}:
        raise ValueError("SUBFLOW_TORCH_BACKEND must be auto, cpu, cuda or mps")
    if backend == "mps" and not apple:
        raise ValueError("MPS automatic installation requires a native Apple Silicon macOS client")
    if backend == "cuda" and (sys.platform == "darwin" or platform.machine().lower() not in {"amd64", "x86_64"}):
        raise ValueError("CUDA wheels require Windows/Linux x86_64; use cpu on this platform")
    return backend


def managed_env(kind: str) -> Path:
    if kind not in {"asr", "gptsovits", "whisperx", "qwentts"}:
        raise ValueError(f"Unknown runtime: {kind}")
    return runtime_root() / f"{kind}-{torch_backend()}-py311-v1"


def managed_python(kind: str) -> Path:
    return managed_env(kind) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def find_uv(*, control: JobControl | None = None) -> Path:
    return _installer.find_uv(control=control)


def install_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "UV_TORCH_BACKEND"):
        env.pop(key, None)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", UV_NO_CONFIG="1",
               UV_PYTHON_INSTALL_DIR=str(runtime_root() / "python"),
               UV_CACHE_DIR=str(runtime_root() / "download-cache"))
    env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
               SUBFLOW_GPTSOVITS_CACHE=str(runtime_root() / 'gptsovits-cache'),
               NUMBA_CACHE_DIR=str(runtime_root() / 'numba-cache'),
               MPLCONFIGDIR=str(runtime_root() / 'matplotlib-cache'))
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


def _torch_build(backend: str) -> tuple[str, str, list[str]]:
    x86 = platform.machine().lower() in {"x86_64", "amd64"}
    version = "2.2.2" if sys.platform == "darwin" and x86 else "2.5.1"
    if sys.platform != "darwin" and x86:
        wheel = "cu124" if backend == "cuda" else "cpu"
        return version, f"{version}+{wheel}", ["--torch-backend", wheel]
    return version, version, []


def _runtime_probe(kind: str, version: str, backend: str) -> str:
    modules = {
        "asr": "torch, torchaudio, whisper",
        "gptsovits": (
            "torch, torchaudio, fastapi, uvicorn, soundfile, numpy, librosa, yaml, "
            "onnxruntime, transformers, pyopenjtalk, jieba"
        ),
        "whisperx": "torch, torchaudio, whisperx",
        "qwentts": "torch, torchaudio, qwen_tts, fastapi, uvicorn, soundfile",
    }
    if kind not in modules:
        raise ValueError(f"Unknown runtime: {kind}")
    code = (
        f"import {modules[kind]}\n"
        f"expected = ({version!r}, {version!r})\n"
        "actual = (str(torch.__version__), str(torchaudio.__version__))\n"
        "if actual != expected:\n"
        "    raise RuntimeError(f'PyTorch build mismatch: expected {expected}, got {actual}')\n"
    )
    if backend == "cuda":
        code += (
            "if torch.version.cuda != '12.4':\n"
            "    raise RuntimeError('PyTorch CUDA 12.4 build is required')\n"
        )
    else:
        code += (
            "if torch.version.cuda is not None:\n"
            "    raise RuntimeError('PyTorch CUDA build is not valid for this runtime')\n"
        )
    if backend == "mps":
        code += (
            "import platform\n"
            "if platform.machine().lower() not in {'arm64', 'aarch64'}:\n"
            "    raise RuntimeError('MPS runtime requires native Apple Silicon Python')\n"
            "if not torch.backends.mps.is_built():\n"
            "    raise RuntimeError('PyTorch MPS support was not built')\n"
        )
    return code


def _ready_marker(marker: Path, stamp: str, control: JobControl | None) -> None:
    pending = marker.with_name(marker.name + ".pending")
    try:
        if control:
            control.wait_if_paused()
        pending.write_text(stamp, encoding="utf-8")
        if control:
            control.wait_if_paused()
        pending.replace(marker)
    finally:
        pending.unlink(missing_ok=True)


def ensure_python_env(kind: str, *, control: JobControl | None = None, progress: Progress = None) -> Path:
    backend = torch_backend()
    from bilingual_sub.adapters.offline_bundle import runtime

    bundled = runtime(kind, backend)
    if bundled:
        python, wheel, build = bundled
        _progress(progress, '正在检查内置配音环境（无需下载）…')
        _run([str(python), '-c', _runtime_probe(kind, wheel, build)],
             runtime_root() / f'bundled-{kind}.log', control,
             env={**inference_env(), 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}, timeout=180)
        return python
    version, wheel_version, backend_args = _torch_build(backend)
    probe = _runtime_probe(kind, wheel_version, backend)
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    requirements = bootstrap_assets() / f"{kind}.txt"
    content = requirements.read_bytes()
    stamp = hashlib.sha256(content + f"{wheel_version}|{backend}|v2".encode()).hexdigest()
    legacy = hashlib.sha256(content + f"{version}|{backend}|v1".encode()).hexdigest()
    python = managed_python(kind)
    marker = managed_env(kind) / ".subflow-ready"
    log = root / f"install-{kind}.log"
    check = [str(python), "-c", probe]
    with _locked(root / f"{kind}.lock", control):
        repair = python.is_file()
        cached = marker.read_text(encoding="utf-8", errors="replace") if marker.is_file() else None
        if python.is_file() and cached in {stamp, legacy}:
            try:
                _run(check, log, control, timeout=90)
            except JobStopped:
                raise
            except (OSError, RuntimeError) as exc:
                if not auto_install_enabled():
                    raise RuntimeError("运行环境已损坏，自动安装已关闭（SUBFLOW_AUTO_INSTALL=0）") from exc
                _progress(progress, "运行环境检查失败，正在修复依赖…")
                repair = True
            else:
                if cached != stamp:
                    _ready_marker(marker, stamp, control)
                return python
        if not auto_install_enabled():
            raise RuntimeError("自动安装已关闭（SUBFLOW_AUTO_INSTALL=0）且运行环境尚未准备")
        uv = str(find_uv(control=control))
        marker.unlink(missing_ok=True)
        _progress(progress, "首次运行：正在自动准备 Python 3.11（后续使用缓存）…")
        if not python.is_file() or repair:
            _run([uv, "python", "install", "3.11", "--no-bin", "--no-registry"], log, control)
            _run([uv, "venv", "--allow-existing", "--managed-python", "--python", "3.11", "--seed", str(python.parent.parent)], log, control)
        _progress(progress, f"正在安装 {kind} 依赖（{backend.upper()}），首次下载可能需要数分钟…")
        torch_args = [uv, "pip", "install", "--python", str(python),
                      f"torch=={wheel_version}", f"torchaudio=={wheel_version}", *backend_args]
        if repair:
            torch_args.append("--reinstall")
        _run(torch_args, log, control)
        # Each environment owns its constraints under the same installation lock.
        constraints = python.parent.parent / ".subflow-torch-constraints.txt"
        constraints.write_text(f"torch=={wheel_version}\ntorchaudio=={wheel_version}\n", encoding="utf-8")
        args = [uv, "pip", "install", "--python", str(python), "-r", str(requirements), *backend_args]
        if repair:
            args.append("--reinstall")
        args += ["-c", str(constraints)]
        _run(args, log, control)
        _run(check, log, control, timeout=90)
        _ready_marker(marker, stamp, control)
    return python


def ensure_sovits_runtime(*, control: JobControl | None = None, progress: Progress = None,
                          models: bool = True) -> Path:
    from bilingual_sub.adapters.offline_bundle import model_home

    if not os.environ.get('SUBFLOW_GPTSOVITS_HOME', '').strip():
        bundled = model_home('gptsovits', verify=models, progress=progress, control=control)
        if bundled:
            ensure_python_env('gptsovits', control=control, progress=progress)
            return bundled
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
