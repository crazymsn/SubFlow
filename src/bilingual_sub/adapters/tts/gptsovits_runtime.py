"""Locate / probe / start the vendored GPT-SoVITS api_v2.py server.

Source lives in third_party/GPT-SoVITS. Portable releases place its Python
runtime and checkpoints beside SubFlow.exe, isolated from Qt.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path
from urllib.parse import urlparse

import httpx

from bilingual_sub.adapters.procwin import hidden_run_kwargs, terminate_process_tree
from bilingual_sub.adapters.tts.base import TtsUnavailable
from bilingual_sub.adapters.tts.gptsovits import DEFAULT_ENDPOINT
from bilingual_sub.core.control import JobControl, JobStopped

logger = logging.getLogger(__name__)

REPO_URL = "https://github.com/RVC-Boss/GPT-SoVITS.git"
_SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", ".pytest_cache", "runtime", "nltk_data", ".cache"}
_IMPORT_PROBE = "import fastapi, uvicorn, torch, torchaudio, soundfile, numpy, librosa, yaml, onnxruntime"
_TTS_PROBE = (
    "import sys;"
    "sys.path.insert(0, '.');"
    "sys.path.insert(0, 'GPT_SoVITS');"
    "from GPT_SoVITS.TTS_infer_pack.TTS import TTS"
)
_WEIGHT_SETS = (
    (
        "v2",
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
        "GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth",
    ),
    (
        "v1",
        "GPT_SoVITS/pretrained_models/s1bert25hz-2kh-longer-epoch=68e-step=50232.ckpt",
        "GPT_SoVITS/pretrained_models/s2G488k.pth",
    ),
    (
        "v4",
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/gsv-v4-pretrained/s2Gv4.pth",
    ),
    (
        "v3",
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/s2Gv3.pth",
    ),
    (
        "v2Pro",
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2Pro.pth",
    ),
    (
        "v2ProPlus",
        "GPT_SoVITS/pretrained_models/s1v3.ckpt",
        "GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth",
    ),
)
_BERT_DIR = "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large"
_HUBERT_DIR = "GPT_SoVITS/pretrained_models/chinese-hubert-base"
_G2PW_DIR = "GPT_SoVITS/text/G2PWModel"

_spawn_lock = threading.Lock()
_children: dict[str, subprocess.Popen] = {}
_shutdown = threading.Event()
_last_import_error = ""


def should_autostart() -> bool:
    if os.environ.get("SUBFLOW_SKIP_SOVITS_BOOT") == "1":
        return False
    if os.environ.get("SUBFLOW_SOVITS_AUTOSTART") == "0":
        return False
    return True


def default_home() -> Path:
    env = (os.environ.get("SUBFLOW_GPTSOVITS_HOME") or "").strip()
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return root / "SubFlow" / "GPT-SoVITS"
    return Path.home() / ".local" / "share" / "subflow" / "GPT-SoVITS"


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "third_party" / "GPT-SoVITS" / "api_v2.py").is_file():
            return parent
    return here.parents[4]


def _frozen_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        roots.extend((exe / "GPT-SoVITS", exe / "_internal" / "GPT-SoVITS"))
        if sys.platform == "darwin":
            roots.append(exe.parent / "Resources" / "GPT-SoVITS")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(Path(meipass) / "GPT-SoVITS")
    return roots


def bundled_src() -> Path | None:
    for path in _frozen_roots():
        if (path / "api_v2.py").is_file():
            return path
    repo = _repo_root() / "third_party" / "GPT-SoVITS"
    if (repo / "api_v2.py").is_file():
        return repo
    return None


def extra_home_candidates() -> list[Path]:
    names = ("GPT-SoVITS", "GPT-SoVITS-v2", "GPT-SoVITS-v4", "GPT_SoVITS")
    roots = [
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "OneDrive" / "桌面",
        Path.home() / "OneDrive" / "Desktop",
        Path("C:/"),
        Path("D:/"),
        Path("E:/"),
        _repo_root(),
        _repo_root().parent,
    ]
    out: list[Path] = []
    for root in roots:
        for name in names:
            out.append(root / name)
    return out


def _has_api(path: Path) -> bool:
    return (path / "api_v2.py").is_file()


def _home_score(path: Path) -> tuple[int, int]:
    return (
        0 if missing_pretrained(path) else 1,
        1 if find_sovits_python(path) is not None else 0,
    )


def discover_home() -> Path | None:
    env = (os.environ.get("SUBFLOW_GPTSOVITS_HOME") or "").strip()
    if env:
        forced = Path(env).expanduser()
        return forced.resolve() if _has_api(forced) else None
    ranked: list[tuple[tuple[int, int], Path]] = []
    seen: set[str] = set()
    for path in (*_frozen_roots(), bundled_src(), default_home(), *extra_home_candidates()):
        if path is None:
            continue
        key = os.path.normcase(str(path))
        if key in seen or not _has_api(path):
            continue
        seen.add(key)
        ranked.append((_home_score(path), path))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def ensure_source() -> Path:
    found = discover_home()
    if found is not None:
        return found
    raise FileNotFoundError(
        "未找到内置 GPT-SoVITS。请运行 scripts/setup-gptsovits.ps1，"
        "或检查 SUBFLOW_GPTSOVITS_HOME 中的 api_v2.py"
    )


def ensure_home() -> Path:
    return ensure_source()


def _weight_file_ok(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 1024


def _model_dir_ok(path: Path) -> bool:
    return (path / "config.json").is_file() and any(
        _weight_file_ok(path / name) for name in ("pytorch_model.bin", "model.safetensors")
    )


def missing_pretrained(home: Path | None = None) -> list[str]:
    root = home or discover_home()
    if root is None:
        return ["api_v2.py"]
    missing: list[str] = []
    if not _model_dir_ok(root / _BERT_DIR):
        missing.append(_BERT_DIR)
    if not any((root / _BERT_DIR / name).is_file() for name in ("tokenizer.json", "vocab.txt")):
        missing.append(f"{_BERT_DIR}/tokenizer.json")
    if not _model_dir_ok(root / _HUBERT_DIR):
        missing.append(_HUBERT_DIR)
    g2pw = root / _G2PW_DIR
    has_onnx = _weight_file_ok(g2pw / "g2pW.onnx") or _weight_file_ok(g2pw / "g2pw.onnx") or any(
        _weight_file_ok(path) for path in g2pw.rglob("*.onnx")
    )
    if not (has_onnx and (g2pw / "POLYPHONIC_CHARS.txt").is_file() and (g2pw / "config.py").is_file()):
        missing.append(_G2PW_DIR)
    try:
        runtime_config(root)
    except TtsUnavailable as exc:
        missing.append(str(exc))
    return missing


def _any_custom_weight_pair(root: Path) -> bool:
    models = root / "GPT_SoVITS" / "pretrained_models"
    if not models.is_dir():
        return False
    has_gpt = False
    has_sovits = False
    for path in models.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".ckpt" and path.stat().st_size > 1024:
            has_gpt = True
        elif suffix == ".pth" and path.stat().st_size > 1024:
            has_sovits = True
        if has_gpt and has_sovits:
            return True
    return False


def find_sovits_python(home: Path | None = None) -> Path | None:
    env = (os.environ.get("SUBFLOW_GPTSOVITS_PYTHON") or "").strip()
    if env:
        cand = Path(env).expanduser()
        return cand.resolve() if cand.is_file() else None
    root = home or discover_home()
    if root is None:
        return None
    for rel in (
        "venv/Scripts/python.exe",
        "venv/bin/python3",
        "venv/bin/python",
        ".venv/Scripts/python.exe",
        ".venv/bin/python",
        "runtime/python.exe",
    ):
        cand = root / rel
        if cand.is_file():
            return cand
    parent_runtime = root.parent / "runtime" / "python.exe"
    if parent_runtime.is_file():
        return parent_runtime
    from bilingual_sub.adapters.runtime_bootstrap import managed_python

    managed = managed_python("gptsovits")
    if managed.is_file():
        return managed
    return None


def _host_python() -> list[str] | None:
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher:
            return [launcher, "-3"]
    host = shutil.which("python") or shutil.which("python3")
    if host:
        resolved = Path(host).resolve()
        if getattr(sys, "frozen", False) and resolved == Path(sys.executable).resolve():
            return None
        return [host]
    return None


def python_has_sovits_deps(
    cmd: list[str],
    timeout: float = 90.0,
    *,
    cwd: Path | str | None = None,
) -> bool:
    if not cmd:
        return False
    global _last_import_error
    work = str(cwd) if cwd else None
    from bilingual_sub.adapters.runtime_bootstrap import install_env

    env = install_env()
    if work:
        env["NLTK_DATA"] = str(Path(work) / "nltk_data")
    try:
        result = subprocess.run(
            [*cmd, "-c", _IMPORT_PROBE],
            capture_output=True,
            timeout=timeout,
            check=False,
            cwd=work,
            env=env,
            **hidden_run_kwargs(),
        )
        if result.returncode != 0:
            _last_import_error = (result.stderr or result.stdout or b"").decode("utf-8", "replace")[-400:]
            return False
        if work and (Path(work) / "api_v2.py").is_file():
            result = subprocess.run(
                [*cmd, "-c", _TTS_PROBE],
                capture_output=True,
                timeout=timeout,
                check=False,
                cwd=work,
                env=env,
                **hidden_run_kwargs(),
            )
            if result.returncode != 0:
                _last_import_error = (result.stderr or result.stdout or b"").decode("utf-8", "replace")[-400:]
                return False
            return True
    except Exception as exc:
        _last_import_error = str(exc)
        return False
    return True


def _python_candidates(home: Path | None = None) -> list[list[str]]:
    out: list[list[str]] = []
    seen: set[str] = set()

    def add(cmd: list[str] | None) -> None:
        if not cmd:
            return
        key = os.path.normcase(" ".join(cmd))
        if key in seen:
            return
        seen.add(key)
        out.append(cmd)

    dedicated = find_sovits_python(home)
    if dedicated is not None:
        add([str(dedicated)])
    if os.environ.get("SUBFLOW_GPTSOVITS_PYTHON", "").strip():
        return out
    if not getattr(sys, "frozen", False):
        add([sys.executable])
    add(_host_python())
    return out


def launch_python(home: Path | None = None) -> list[str]:
    checked: list[str] = []
    for cmd in _python_candidates(home):
        checked.append(" ".join(cmd))
        if python_has_sovits_deps(cmd, cwd=home):
            return cmd
    hint = "、".join(checked) if checked else "无"
    raise FileNotFoundError(
        "未找到能 import FastAPI/Torch/soundfile/onnxruntime 并加载 GPT-SoVITS TTS 的 Python"
        f"（已试：{hint}）。请在 third_party/GPT-SoVITS 运行官方 install.ps1，"
        "或设置 SUBFLOW_GPTSOVITS_PYTHON 指向整合包里的 python.exe"
    )


def diagnose_runtime(home: Path | None = None) -> str | None:
    try:
        root = home or discover_home()
    except Exception as exc:
        return str(exc)
    if root is None or not _has_api(root):
        return "未找到内置 GPT-SoVITS 源码。请确认 third_party/GPT-SoVITS/api_v2.py 存在，或设置 SUBFLOW_GPTSOVITS_HOME"
    problems: list[str] = []
    try:
        launch_python(root)
    except FileNotFoundError as exc:
        problems.append(str(exc))
        if _last_import_error:
            problems.append(_last_import_error.strip())
    missing = missing_pretrained(root)
    if missing:
        problems.append(
            "缺少预训练权重："
            + "；".join(missing)
            + "。运行 scripts/download-gptsovits-weights.ps1，或按官方 install.ps1 下载到该目录"
        )
    return " ".join(problems) if problems else None


def probe_endpoint(endpoint: str | None = None, timeout: float = 2.0) -> bool:
    base = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
    if not base:
        return False
    try:
        resp = httpx.get(base + "/openapi.json", timeout=timeout, trust_env=False)
        if resp.status_code != 200:
            return False
        schema = resp.json()
        paths = schema.get("paths", {})
        fields = schema.get("components", {}).get("schemas", {}).get("TTS_Request", {}).get("properties", {})
        return "post" in paths.get("/tts", {}) and {"text", "text_lang", "ref_audio_path", "prompt_lang"} <= fields.keys()
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return False


def _bind_from_endpoint(endpoint: str) -> tuple[str, int]:
    try:
        parsed = urlparse(endpoint)
        port = parsed.port or 80
    except ValueError as exc:
        raise TtsUnavailable(f"GPT-SoVITS 服务地址无效：{endpoint}") from exc
    host = parsed.hostname
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username:
        raise TtsUnavailable("只能自动启动本机 HTTP 服务；远程或 HTTPS 服务请先在服务端启动")
    return host, port


def runtime_config(root: Path) -> dict:
    """Choose a complete, matching model pair; never infer a pair from arbitrary files."""
    import yaml

    override = os.environ.get("SUBFLOW_GPTSOVITS_CONFIG", "").strip()
    if override:
        path = Path(override).expanduser().resolve()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise TtsUnavailable(f"无法读取 GPT-SoVITS 模型配置：{path}：{exc}") from exc
        if not isinstance(data, dict):
            raise TtsUnavailable(f"模型配置必须是 YAML 映射：{path}")
        config = data.get("custom", data.get("v2", data))
        if not isinstance(config, dict):
            raise TtsUnavailable(f"模型配置 custom 必须是 YAML 映射：{path}")
        config = dict(config)
        required = ("t2s_weights_path", "vits_weights_path", "bert_base_path", "cnhuhbert_base_path")
        for key in required:
            raw = config.get(key)
            if not isinstance(raw, str) or not raw.strip():
                raise TtsUnavailable(f"模型配置缺少路径：{key}")
            value = Path(raw).expanduser()
            value = value if value.is_absolute() else root / value
            valid = _weight_file_ok(value) if key.endswith("weights_path") else _model_dir_ok(value)
            if not valid:
                raise TtsUnavailable(f"模型配置缺少文件：{key}={value}")
            config[key] = str(value.resolve())
        return config
    for version, gpt, sovits in _WEIGHT_SETS:
        if _weight_file_ok(root / gpt) and _weight_file_ok(root / sovits):
            return {
                "version": version,
                "device": os.environ.get("SUBFLOW_GPTSOVITS_DEVICE", "cpu"),
                "is_half": os.environ.get("SUBFLOW_GPTSOVITS_DEVICE", "cpu") != "cpu",
                "t2s_weights_path": str((root / gpt).resolve()),
                "vits_weights_path": str((root / sovits).resolve()),
                "bert_base_path": str((root / _BERT_DIR).resolve()),
                "cnhuhbert_base_path": str((root / _HUBERT_DIR).resolve()),
            }
    raise TtsUnavailable("缺少完整配对的 GPT/SoVITS 权重；运行 scripts/download-gptsovits-weights.ps1")


def _log_path() -> Path:
    from bilingual_sub.config import user_config_dir

    path = user_config_dir() / "gptsovits.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _log_tail(limit: int = 30) -> str:
    path = _log_path()
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


def start_server(
    endpoint: str | None = None,
    *,
    home: Path | None = None,
    visible: bool = False,
) -> subprocess.Popen:
    root = (home or ensure_home()).resolve()
    if not (root / "api_v2.py").is_file():
        raise FileNotFoundError(f"api_v2.py missing: {root}")
    launch = launch_python(root)
    host, port = _bind_from_endpoint(endpoint or DEFAULT_ENDPOINT)
    import yaml

    config = _log_path().with_name(f"gptsovits-{port}.yaml")
    config.write_text(yaml.safe_dump({"custom": runtime_config(root)}), encoding="utf-8")
    args = [*launch, "-u", "api_v2.py", "-a", host, "-p", str(port), "-c", str(config)]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["NLTK_DATA"] = str(root / "nltk_data") + os.pathsep + env.get("NLTK_DATA", "")
    from bilingual_sub.adapters.ffmpeg import find_ffmpeg

    env["PATH"] = str(Path(find_ffmpeg()).parent) + os.pathsep + env.get("PATH", "")
    log = _log_path().open("wb")
    kwargs: dict = {
        "cwd": str(root),
        "stdin": subprocess.DEVNULL,
        "stdout": log,
        "stderr": log,
        "env": env,
    }
    if os.name == "nt":
        if visible:
            kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
            kwargs.pop("stdout", None)
            kwargs.pop("stderr", None)
        else:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            kwargs["startupinfo"] = subprocess.STARTUPINFO()
            kwargs["startupinfo"].dwFlags |= subprocess.STARTF_USESHOWWINDOW
    logger.info("starting GPT-SoVITS: %s (cwd=%s)", args, root)
    try:
        return subprocess.Popen(args, **kwargs)
    finally:
        log.close()


def reset_boot_state() -> None:
    stop_servers()
    _shutdown.clear()


def request_shutdown() -> None:
    """Cancel startup without waiting on the process lock from the GUI thread."""
    _shutdown.set()


def stop_servers() -> None:
    """Stop only children owned by this SubFlow process, never an external API."""
    _shutdown.set()
    with _spawn_lock:
        children = list(_children.values())
        _children.clear()
    for proc in children:
        if proc.poll() is None and hasattr(proc, "terminate"):
            try:
                terminate_process_tree(proc)
                if hasattr(proc, "wait"):
                    proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if hasattr(proc, "kill"):
                    proc.kill()
                    proc.wait(timeout=3)
            except (OSError, AttributeError):
                logger.exception("failed to stop GPT-SoVITS")


atexit.register(stop_servers)


def _boot_error(prefix: str) -> TtsUnavailable:
    tail = _log_tail()
    if tail:
        return TtsUnavailable(f"{prefix}\n{tail[-800:]}")
    return TtsUnavailable(prefix)


def ensure_running(endpoint: str | None = None, *, wait_sec: float = 180.0, control: JobControl | None = None, progress=None) -> str:
    from bilingual_sub.adapters.tts.gptsovits import default_endpoint

    base = (endpoint or default_endpoint()).strip().rstrip("/")
    def check() -> None:
        if _shutdown.is_set():
            raise JobStopped()
        if control:
            control.wait_if_paused()

    check()
    if probe_endpoint(base):
        return "ready"
    _bind_from_endpoint(base)
    with _spawn_lock:
        check()
        if probe_endpoint(base):
            return "ready"
        proc = _children.get(base)
        if proc is None or proc.poll() is not None:
            from bilingual_sub.adapters.runtime_bootstrap import (
                auto_install_enabled,
                ensure_sovits_runtime,
            )

            root = discover_home()
            if root is None or missing_pretrained(root) or find_sovits_python(root) is None:
                if auto_install_enabled():
                    root = ensure_sovits_runtime(control=control, progress=progress)
                else:
                    root = ensure_home()
            missing = missing_pretrained(root)
            if missing:
                raise TtsUnavailable("缺少预训练权重：" + "；".join(missing))
            check()
            try:
                proc = start_server(base, home=root, visible=False)
            except FileNotFoundError:
                if not auto_install_enabled():
                    raise
                root = ensure_sovits_runtime(control=control, progress=progress)
                proc = start_server(base, home=root, visible=False)
            _children[base] = proc
    deadline = time.monotonic() + max(0.0, wait_sec)
    while time.monotonic() < deadline:
        check()
        if probe_endpoint(base, timeout=1.5):
            return "started"
        if proc is not None and proc.poll() is not None:
            raise _boot_error(
                f"GPT-SoVITS 进程已退出（code={proc.returncode}）。"
                f"日志：{_log_path()}"
            )
        _shutdown.wait(0.2)
    raise _boot_error(
        f"GPT-SoVITS 在 {int(wait_sec)} 秒内没有监听 {base}。"
        f"模型加载可能仍在进行，日志：{_log_path()}"
    )


def extract_ref_audio(
    video: Path,
    dest: Path,
    *,
    start: float = 0.4,
    duration: float = 5.0,
    control=None,
) -> Path:
    from bilingual_sub.adapters.ffmpeg import find_ffmpeg, run_cmd

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    span = max(3.0, min(8.0, float(duration)))
    run_cmd(
        [
            find_ffmpeg(),
            "-y",
            "-ss",
            f"{max(0.0, float(start)):.3f}",
            "-t",
            f"{span:.3f}",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "32000",
            str(dest),
        ],
        control=control,
    )
    if not dest.is_file() or dest.stat().st_size < 64:
        raise FileNotFoundError(f"failed to extract GPT-SoVITS reference from {video}")
    with wave.open(str(dest), "rb") as wav:
        seconds = wav.getnframes() / wav.getframerate()
    if not 3.0 <= seconds <= 10.0:
        dest.unlink(missing_ok=True)
        raise TtsUnavailable("参考音频必须包含 3–10 秒人声；当前视频可提取的音频过短，请另选参考音频")
    return dest


def ensure_ref_audio(video: Path, dest: Path, cues=None, *, control=None) -> Path:
    dest = Path(dest)
    from bilingual_sub.adapters.ffmpeg import is_pcm_wav

    if is_pcm_wav(dest):
        with wave.open(str(dest), "rb") as wav:
            if 3.0 <= wav.getnframes() / wav.getframerate() <= 10.0:
                return dest
    start = 0.4
    duration = 5.0
    if cues:
        for cue in cues:
            text = f"{getattr(cue, 'zh', '')}{getattr(cue, 'en', '')}".strip()
            span = float(getattr(cue, "end", 0) or 0) - float(getattr(cue, "start", 0) or 0)
            if text and span >= 2.0:
                start = max(0.0, float(cue.start))
                duration = min(8.0, max(3.0, span))
                break
    return extract_ref_audio(video, dest, start=start, duration=duration, control=control)


def copy_runtime_tree(src: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in _SKIP_DIRS:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(*_SKIP_DIRS, "*.pth", "*.ckpt", "*.bin", "*.safetensors", "*.onnx", "*.pt"),
            )
        else:
            shutil.copy2(item, target)
    return dest
