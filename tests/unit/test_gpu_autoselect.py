import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bilingual_sub.adapters import runtime_bootstrap as bootstrap
from bilingual_sub.adapters import torch_device
from bilingual_sub.adapters.tts import gptsovits_runtime as sovits


@pytest.mark.parametrize("system,arch,driver,expected", [
    ("win32", "AMD64", True, "cuda"), ("win32", "AMD64", False, "cpu"),
    ("linux", "x86_64", True, "cuda"), ("linux", "aarch64", True, "cpu"),
    ("darwin", "arm64", False, "mps"), ("darwin", "x86_64", True, "cpu"),
])
@pytest.mark.parametrize("setting", [None, "auto", ""])
def test_default_backend_uses_driver_not_host_torch(monkeypatch, system, arch, driver, expected, setting):
    monkeypatch.delenv("SUBFLOW_TORCH_BACKEND", raising=False)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    if setting is not None:
        monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", setting)
    monkeypatch.setattr(bootstrap.sys, "platform", system)
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: arch)
    monkeypatch.setattr(bootstrap, "_cuda_driver_available", lambda: driver)
    monkeypatch.setitem(sys.modules, "torch", None)
    assert bootstrap.torch_backend() == expected


@pytest.mark.parametrize("visible", ["", "-1"])
def test_hidden_cuda_devices_use_cpu(monkeypatch, visible):
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", "auto")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(bootstrap, "_cuda_driver_available", lambda: True)
    assert bootstrap.torch_backend() == "cpu"


def test_explicit_cpu_stays_cpu_on_nvidia(monkeypatch):
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", "cpu")
    monkeypatch.setattr(bootstrap, "_cuda_driver_available", lambda: True)
    assert bootstrap.torch_backend() == "cpu"


@pytest.mark.parametrize('system,arch,gpu,backend', [
    ('win32', 'AMD64', True, 'cuda'), ('win32', 'AMD64', False, 'cpu'),
    ('darwin', 'arm64', False, 'mps'),
])
def test_qwen_environment_tracks_available_accelerator(tmp_path, monkeypatch, system, arch, gpu, backend):
    monkeypatch.setenv('SUBFLOW_TORCH_BACKEND', 'auto')
    monkeypatch.delenv('CUDA_VISIBLE_DEVICES', raising=False)
    monkeypatch.setattr(bootstrap.sys, 'platform', system)
    monkeypatch.setattr(bootstrap.platform, 'machine', lambda: arch)
    monkeypatch.setattr(bootstrap, '_cuda_driver_available', lambda: gpu)
    monkeypatch.setattr(bootstrap, 'runtime_root', lambda: tmp_path)
    assert bootstrap.managed_env('qwentts').name == f'qwentts-{backend}-py311-v1'


@pytest.mark.parametrize("exists", [False, True])
def test_cuda_uses_managed_python_instead_of_bundled_cpu(tmp_path, monkeypatch, exists):
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    monkeypatch.delenv("SUBFLOW_GPTSOVITS_HOME", raising=False)
    monkeypatch.delenv("SUBFLOW_GPTSOVITS_PYTHON", raising=False)
    monkeypatch.setattr(bootstrap, "torch_backend", lambda: "cuda")
    managed = tmp_path / "gpu-python"
    if exists:
        managed.touch()
    monkeypatch.setattr(bootstrap, "managed_python", lambda kind: managed)
    portable = tmp_path / "runtime/python.exe"
    portable.parent.mkdir()
    portable.touch()
    assert sovits.find_sovits_python(tmp_path) == (managed if exists else None)
    assert sovits._python_candidates(tmp_path) == ([[str(managed)]] if exists else [])


def test_cuda_boot_provisions_dependencies_without_copying_models(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    monkeypatch.setattr(sovits, "_automatic_cuda_runtime", lambda: True)
    monkeypatch.setattr(sovits, "_automatic_mps_runtime", lambda: False)
    monkeypatch.setattr(sovits, "discover_home", lambda: tmp_path)
    monkeypatch.setattr(sovits, "missing_pretrained", lambda home: [])
    monkeypatch.setattr(sovits, "find_sovits_python", lambda home: tmp_path / "gpu-python")
    monkeypatch.setattr(bootstrap, "source_update_needed", lambda home: False)
    monkeypatch.setattr(bootstrap, "assets_update_needed", lambda home: False)
    events = []
    monkeypatch.setattr(sovits, "probe_endpoint", lambda *a, **kw: "start" in events)
    monkeypatch.setattr(bootstrap, "ensure_python_env", lambda kind, **kw: events.append(kind))
    monkeypatch.setattr(bootstrap, "ensure_sovits_runtime", Mock(side_effect=AssertionError("must reuse bundled models")))
    def start(*args, **kwargs):
        assert kwargs["home"] == tmp_path and events == ["gptsovits"]
        events.append("start")
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(sovits, "start_server", start)
    endpoint = "http://127.0.0.1:19884"
    try:
        assert sovits.ensure_running(endpoint, wait_sec=1) == "started"
        assert events == ["gptsovits", "start"]
    finally:
        sovits._children.pop(endpoint, None)


def test_whisper_cuda_failure_retries_on_cpu(monkeypatch):
    clear = Mock()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(empty_cache=clear)))
    model = Mock()
    model.transcribe.side_effect = [RuntimeError("CUDA out of memory"), {"segments": [1]}]
    result, device = torch_device.transcribe_with_fallback(model, "cuda", "audio.wav")
    assert result == {"segments": [1]} and device == "cpu"
    model.to.assert_called_once_with("cpu")
    clear.assert_called_once()
    assert model.transcribe.call_args.kwargs["fp16"] is False


@pytest.mark.parametrize("gpu_ready", [False, True])
def test_whisperx_cpu_cache_cannot_shadow_cuda(tmp_path, monkeypatch, gpu_ready):
    from bilingual_sub.adapters import whisperx_backend as wx

    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    for key in ("SUBFLOW_PYTHON", "SUBFLOW_WHISPER_PYTHON"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(bootstrap, "torch_backend", lambda: "cuda")
    gpu, cpu = tmp_path / "gpu-python", tmp_path / "cpu-python"
    cpu.touch()
    if gpu_ready:
        gpu.touch()
    monkeypatch.setattr(bootstrap, "managed_python", lambda kind: gpu)
    monkeypatch.setattr(wx, "_python_candidates", lambda **kw: [cpu])
    checked = []
    monkeypatch.setattr(wx, "_python_has_module", lambda path, *a, **kw: checked.append(path) or True)
    assert wx.find_whisperx_python() == (gpu if gpu_ready else None)
    assert cpu not in checked
