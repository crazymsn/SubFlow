from pathlib import Path

from bilingual_sub.adapters.whisper_backend import (
    MISSING_WHISPER_MSG,
    _cache_path,
    _python_candidates,
    default_whisper_model,
    resolve_device,
    worker_script,
)


def test_missing_message_is_actionable():
    assert "SUBFLOW_PYTHON" in MISSING_WHISPER_MSG
    assert "openai-whisper" in MISSING_WHISPER_MSG


def test_worker_script_exists():
    assert worker_script().is_file()
    assert worker_script().name == "whisper_worker.py"


def test_candidates_include_env_and_home_venv(monkeypatch, tmp_path):
    fake = tmp_path / "python.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("SUBFLOW_PYTHON", str(fake))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    home_venv = tmp_path / ".agent-reach-venv" / "Scripts" / "python.exe"
    home_venv.parent.mkdir(parents=True)
    home_venv.write_text("", encoding="utf-8")
    found = [str(p) for p in _python_candidates()]
    assert str(fake) in found
    assert str(home_venv) in found
    runtime = tmp_path / "roaming" / "SubFlow" / "runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text("", encoding="utf-8")
    found = [str(p) for p in _python_candidates()]
    assert str(runtime) in found


def test_cache_path_under_subflow(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = _cache_path()
    assert path.name == "whisper-python.txt"
    assert "SubFlow" in path.parts


def test_resolve_device_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.whisper_backend.cuda_available", lambda: False)
    assert resolve_device("auto") == "cpu"
    assert resolve_device("cpu") == "cpu"
    assert resolve_device("cuda") == "cpu"


def test_resolve_device_uses_cuda_when_present(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.whisper_backend.cuda_available", lambda: True)
    assert resolve_device("auto") == "cuda"
    assert resolve_device("cuda") == "cuda"
    assert resolve_device("cpu") == "cpu"


def test_default_whisper_model_is_small_without_gpu(monkeypatch):
    monkeypatch.setattr("bilingual_sub.adapters.whisper_backend.cuda_available", lambda: False)
    monkeypatch.setattr("bilingual_sub.adapters.whisper_backend.has_nvidia_gpu", lambda: False)
    assert default_whisper_model() == "small"
