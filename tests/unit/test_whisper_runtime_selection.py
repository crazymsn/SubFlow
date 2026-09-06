import sys
from types import SimpleNamespace

import pytest

from bilingual_sub.adapters import runtime_bootstrap as rt
from bilingual_sub.adapters import whisper_backend as wb
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    for key in ("SUBFLOW_PYTHON", "SUBFLOW_WHISPER_PYTHON"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(rt, "torch_backend", lambda: "mps")
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace())
    managed = tmp_path / "native-python"
    managed.write_bytes(b"interpreter fixture")
    monkeypatch.setattr(rt, "managed_python", lambda kind: managed)
    monkeypatch.setattr(wb, "_python_has_whisper", lambda path, control=None: path == managed)
    monkeypatch.setattr(wb, "_python_candidates", lambda control=None: [managed])
    monkeypatch.setattr(wb, "_cache_path", lambda: tmp_path / "cached-python.txt")
    events = []
    def prepare(kind, **kwargs):
        events.append(("prepare", kind))
        return managed
    def external(python, *args, **kwargs):
        events.append(("external", python))
        return ["external result"]
    def inprocess(*args, **kwargs):
        events.append(("inprocess", None))
        return ["host result"]
    monkeypatch.setattr(rt, "ensure_python_env", prepare)
    monkeypatch.setattr(wb, "_transcribe_external", external)
    monkeypatch.setattr(wb, "_transcribe_inprocess", inprocess)
    return tmp_path / "audio.wav", managed, events


@pytest.mark.parametrize("host_importable", [False, True])
@pytest.mark.parametrize("backend", ["mps", "cuda"])
def test_automatic_gpu_always_validates_native_runtime(runtime, monkeypatch, host_importable, backend):
    wav, managed, events = runtime
    monkeypatch.setattr(rt, "torch_backend", lambda: backend)
    if not host_importable:
        monkeypatch.setitem(sys.modules, "whisper", None)
    assert wb.transcribe(wav) == ["external result"]
    assert events == [("prepare", "asr"), ("external", managed)]


@pytest.mark.parametrize("error", [RuntimeError("repair failed"), JobStopped()])
def test_native_preparation_failure_never_runs_another_interpreter(runtime, monkeypatch, error):
    wav, _, events = runtime
    def prepare(*args, **kwargs):
        raise error
    monkeypatch.setattr(rt, "ensure_python_env", prepare)
    with pytest.raises(type(error)):
        wb.transcribe(wav)
    assert events == []


@pytest.mark.parametrize("key", ["SUBFLOW_PYTHON", "SUBFLOW_WHISPER_PYTHON"])
def test_explicit_interpreter_wins_over_importable_host(runtime, monkeypatch, key):
    wav, managed, events = runtime
    monkeypatch.setenv(key, str(managed))
    assert wb.transcribe(wav) == ["external result"]
    assert events == [("external", managed)]


def test_invalid_explicit_interpreter_does_not_fall_back(runtime, monkeypatch):
    wav, _, events = runtime
    monkeypatch.setenv("SUBFLOW_PYTHON", str(wav.parent / "missing-python"))
    assert wb.find_whisper_python() is None
    with pytest.raises(RuntimeError, match="指定|SUBFLOW_PYTHON"):
        wb.transcribe(wav)
    assert events == []


def test_secondary_override_works_with_blank_primary(runtime, monkeypatch):
    wav, managed, events = runtime
    monkeypatch.setenv("SUBFLOW_PYTHON", "   ")
    monkeypatch.setenv("SUBFLOW_WHISPER_PYTHON", str(managed))
    assert wb.transcribe(wav) == ["external result"]
    assert events == [("external", managed)]


def test_inference_import_error_is_not_retried_in_another_runtime(runtime, monkeypatch):
    wav, _, events = runtime
    monkeypatch.setattr(rt, "torch_backend", lambda: "cpu")
    def infer(*args, **kwargs):
        events.append(("inference started", None))
        raise ImportError("decoder dependency failed")
    monkeypatch.setattr(wb, "_transcribe_inprocess", infer)
    with pytest.raises(ImportError, match="decoder dependency failed"):
        wb.transcribe(wav)
    assert events == [("inference started", None)]


def test_cpu_source_run_retains_inprocess_support(runtime, monkeypatch):
    wav, _, events = runtime
    monkeypatch.setattr(rt, "torch_backend", lambda: "cpu")
    assert wb.transcribe(wav) == ["host result"]
    assert events == [("inprocess", None)]


def test_cancelled_request_does_not_select_or_prepare_runtime(runtime):
    wav, _, events = runtime
    control = JobControl()
    control.stop()
    with pytest.raises(JobStopped):
        wb.transcribe(wav, control=control)
    assert events == []
