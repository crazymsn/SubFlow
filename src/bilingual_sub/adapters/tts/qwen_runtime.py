"""Install and own the local multilingual voice-cloning service."""
from __future__ import annotations

import atexit
import json
import subprocess
import threading
import time
from contextlib import ExitStack
from urllib.parse import urlparse

import httpx

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.adapters.runtime_bootstrap import (
    _locked,
    _run,
    auto_install_enabled,
    bootstrap_assets,
    ensure_python_env,
    inference_env,
    runtime_root,
)
from bilingual_sub.adapters.tts.base import TtsUnavailable
from bilingual_sub.adapters.tts.routing import provider_endpoint
from bilingual_sub.core.control import JobStopped

_guard = threading.RLock()
_owners: dict[str, tuple[ExitStack, subprocess.Popen]] = {}
_shutdown = threading.Event()


def request_shutdown():
    _shutdown.set()


def stop_servers():
    request_shutdown()
    with _guard:
        for owner, _proc in _owners.values():
            owner.close()
        _owners.clear()


def reset_boot_state():
    _shutdown.clear()


def release_idle_servers(keep_engine=None):
    with _guard:
        for endpoint, (owner, _proc) in list(_owners.items()):
            try:
                with httpx.Client(trust_env=False, timeout=2) as client:
                    data = client.get(endpoint + "/subflow/runtime").json()
                if data.get("busy") is not False or data.get('engine') == keep_engine:
                    continue
            except (httpx.HTTPError, ValueError, AttributeError):
                continue
            _owners.pop(endpoint)
            owner.close()


def probe_endpoint(endpoint: str, *, native=False) -> bool:
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(endpoint.rstrip("/") + "/subflow/runtime")
        data = response.json()
        return response.is_success and data.get("engine") == ('qwen3-native' if native else "qwen3") and bool(data.get("model_revision"))
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def runtime_device(endpoint: str) -> str:
    """Report the running model's device, not just the host's GPU capability."""
    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(endpoint.rstrip('/') + '/subflow/runtime')
        response.raise_for_status()
        data = response.json()
        device = data.get('device', '')
        if data.get('engine') in {'qwen3', 'qwen3-native'} and isinstance(device, str):
            if device in {'cpu', 'mps', 'cuda'} or (device.startswith('cuda:') and device[5:].isdigit()):
                return device
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return ''


def ensure_running(endpoint=None, *, wait_sec=300, control=None, progress=None, native=False):
    endpoint = (endpoint or provider_endpoint('qwen3-native' if native else "qwen3")).rstrip("/")
    def check():
        if _shutdown.is_set():
            raise JobStopped()
        if control:
            control.wait_if_paused()
    check()
    if probe_endpoint(endpoint, native=native):
        return "ready"
    url = urlparse(endpoint)
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1"} or url.username or url.path not in {"", "/"} or url.query or url.fragment:
        raise TtsUnavailable(f"请先启动远程 Qwen3-TTS 服务：{endpoint}")
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    # Serialize installation and startup across threads and client processes.
    with _locked(root / "qwen-service.lock", control):
        check()
        if probe_endpoint(endpoint, native=native):
            return "ready"
        python = ensure_python_env("qwentts", control=control, progress=progress)
        from bilingual_sub._data.bootstrap.download_qwen import ready

        home = root / ('qwen3-native-0.6b' if native else "qwen3-tts-0.6b")
        from bilingual_sub.adapters.offline_bundle import model_home

        bundled = model_home('qwen-native' if native else 'qwen-clone', verify=True,
                             progress=progress, control=control)
        if bundled:
            home = bundled
        spec = json.loads((bootstrap_assets() / 'qwen-native-model.json').read_text(encoding='utf-8')) if native else None
        env = inference_env()
        if not bundled and not ready(home, spec):
            if not auto_install_enabled():
                raise TtsUnavailable("Qwen3-TTS 模型尚未安装；自动安装已关闭")
            if progress:
                progress("首次多语种配音：正在下载并校验 Qwen3-TTS 模型（约 2.5 GB，可续传）…")
            _run([str(python), str(bootstrap_assets() / "download_qwen.py"), str(home), *(['--native'] if native else [])],
                 root / "install-qwen-model.log", control, env=env)
        check()
        if not bundled and not ready(home, spec):
            raise TtsUnavailable("Qwen3-TTS 模型校验失败，请重试")
        clone_args = []
        if native:
            clone = model_home('qwen-clone', verify=True, progress=progress, control=control)
            if clone is None:
                clone = root / 'qwen3-tts-0.6b'
                if not ready(clone):
                    if not auto_install_enabled():
                        raise TtsUnavailable('设计音色所需的 Qwen Base 模型尚未安装；自动安装已关闭')
                    if progress:
                        progress('正在准备多语种设计音色所需的 Qwen Base 模型…')
                    _run([str(python), str(bootstrap_assets() / 'download_qwen.py'), str(clone)],
                         root / 'install-qwen-model.log', control, env=env)
                if not ready(clone):
                    raise TtsUnavailable('Qwen Base 模型校验失败，请重试')
            clone_args = ['--clone-model', str(clone)]
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONNOUSERSITE='1',
                   PYTHONDONTWRITEBYTECODE='1')
        if progress:
            progress("正在加载 Qwen3-TTS，优先使用 GPU；无可用 GPU 时使用 CPU…")
        owner = ExitStack()
        try:
            log = owner.enter_context((root / "qwen-tts.log").open("ab"))
            proc = owner.enter_context(owned_process([str(python), str(bootstrap_assets() / "qwen_server.py"),
                "--model", str(home), "--port", str(url.port or 80), *(['--native'] if native else []),
                *clone_args], stdout=log, stderr=subprocess.STDOUT, env=env))
            deadline = time.monotonic() + wait_sec
            while time.monotonic() < deadline:
                check()
                if proc.poll() is not None:
                    raise TtsUnavailable(f"Qwen3-TTS 启动失败，日志：{root / 'qwen-tts.log'}")
                if probe_endpoint(endpoint, native=native):
                    with _guard:
                        check()
                        previous = _owners.pop(endpoint, None)
                        if previous:
                            previous[0].close()
                        _owners[endpoint] = (owner.pop_all(), proc)
                    return "started"
                _shutdown.wait(0.2)
            raise TtsUnavailable(f"Qwen3-TTS 模型加载超时，日志：{root / 'qwen-tts.log'}")
        finally:
            owner.close()


atexit.register(stop_servers)
