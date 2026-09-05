import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bilingual_sub.adapters import runtime_bootstrap as rt
from bilingual_sub.adapters import torch_device as td


@pytest.mark.parametrize("requested,cuda,mps,expected", [
    ("auto", False, True, "mps"), ("mps", False, True, "mps"),
    ("auto", True, True, "cuda"), ("cpu", True, True, "cpu"),
    ("mps", True, False, "cpu"), ("cuda", False, True, "cpu"),
])
def test_device_selection(monkeypatch, requested, cuda, mps, expected):
    monkeypatch.delenv("SUBFLOW_TORCH_BACKEND", raising=False)
    assert td.select_device(requested, cuda=cuda, mps=mps) == expected


def test_cpu_override_is_respected(monkeypatch):
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", "cpu")
    assert td.select_device("auto", cuda=True, mps=True) == "cpu"


@pytest.mark.parametrize("machine,expected", [("arm64", "mps"), ("x86_64", "cpu")])
def test_native_mac_installer_profile(monkeypatch, machine, expected):
    monkeypatch.delenv("SUBFLOW_TORCH_BACKEND", raising=False)
    monkeypatch.setattr(rt.sys, "platform", "darwin")
    monkeypatch.setattr(rt.platform, "machine", lambda: machine)
    assert rt.torch_backend() == expected
    assert rt.install_env()["PYTORCH_ENABLE_MPS_FALLBACK"] == "1"


def test_mps_profile_rejects_linux_container(monkeypatch):
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", "mps")
    monkeypatch.setattr(rt.sys, "platform", "linux")
    with pytest.raises(ValueError, match="native Apple Silicon"):
        rt.torch_backend()


@pytest.mark.parametrize("fail", [False, True])
def test_whisper_sparse_buffer_stays_on_cpu(fail):
    sparse = Mock()
    dense = sparse.to_dense.return_value
    model = SimpleNamespace(alignment_heads=sparse)

    def move(device):
        assert device == "mps"
        assert model.alignment_heads is dense
        if fail:
            raise RuntimeError("MPS out of memory")
    model.to = move
    whisper = SimpleNamespace(load_model=Mock(return_value=model))
    if fail:
        with pytest.raises(RuntimeError):
            td.load_whisper_on_device(whisper, "tiny", "mps")
    else:
        assert td.load_whisper_on_device(whisper, "tiny", "mps") is model
    whisper.load_model.assert_called_once_with("tiny", device="cpu")
    assert model.alignment_heads is sparse


def test_mps_inference_retries_once_on_cpu(monkeypatch):
    clear = Mock()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(mps=SimpleNamespace(empty_cache=clear)))
    model = Mock()
    model.transcribe.side_effect = [NotImplementedError("MPS op"), {"segments": [1]}]
    result, device = td.transcribe_with_fallback(model, "mps", "audio.wav", word_timestamps=False)
    assert result == {"segments": [1]} and device == "cpu"
    model.to.assert_called_once_with("cpu")
    assert model.transcribe.call_count == 2
    assert model.transcribe.call_args.kwargs["fp16"] is False


def test_mps_cpu_retry_failure_surfaces(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(mps=SimpleNamespace(empty_cache=Mock())))
    model = Mock()
    model.transcribe.side_effect = [RuntimeError("MPS op"), RuntimeError("CPU also failed")]
    with pytest.raises(RuntimeError, match="CPU also failed"):
        td.transcribe_with_fallback(model, "mps", "audio.wav")
    assert model.transcribe.call_count == 2


def test_cli_passes_mps_to_pipeline(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    from bilingual_sub.cli.main import app

    seen = []
    result = SimpleNamespace(cue_count=0, elapsed_sec=0, output_srt=None,
                             output_mp4=None, report_path=tmp_path / "report.json", missing_en=[])
    monkeypatch.setattr("bilingual_sub.cli.main.get_api_key", lambda: "test-key")
    monkeypatch.setattr("bilingual_sub.cli.main.run", lambda config, **kw: seen.append(config.device) or result)
    outcome = CliRunner().invoke(app, ["run", "--url", "https://youtu.be/test", "--device", "mps", "--no-burn"])
    assert outcome.exit_code == 0, outcome.output
    assert seen == ["mps"]


def test_cached_source_upgrade_preserves_custom_install(monkeypatch, tmp_path):
    from bilingual_sub.__version__ import __version__
    from bilingual_sub.adapters.tts import gptsovits_runtime as gr

    monkeypatch.delenv("SUBFLOW_GPTSOVITS_HOME", raising=False)
    monkeypatch.setattr(gr, "default_home", lambda: tmp_path)
    monkeypatch.setattr(gr, "bundled_src", lambda: tmp_path / "bundled")
    assert rt.source_update_needed(tmp_path)
    (tmp_path / ".subflow-source-version").write_text(__version__, encoding="utf-8")
    assert not rt.source_update_needed(tmp_path)
    (tmp_path / ".subflow-source-version").write_text("old", encoding="utf-8")
    monkeypatch.setenv("SUBFLOW_GPTSOVITS_HOME", str(tmp_path))
    assert not rt.source_update_needed(tmp_path)


@pytest.mark.parametrize("override", [False, True])
def test_apple_upgrade_ignores_legacy_python_unless_explicit(monkeypatch, tmp_path, override):
    from bilingual_sub.adapters import whisper_backend as wb

    legacy = tmp_path / "intel-python"
    monkeypatch.delenv("SUBFLOW_PYTHON", raising=False)
    monkeypatch.delenv("SUBFLOW_WHISPER_PYTHON", raising=False)
    if override:
        monkeypatch.setenv("SUBFLOW_PYTHON", str(legacy))
    monkeypatch.setattr(rt, "torch_backend", lambda: "mps")
    monkeypatch.setattr(rt, "auto_install_enabled", lambda: True)
    monkeypatch.setattr(rt, "managed_python", lambda kind: tmp_path / "native-python")
    monkeypatch.setattr(wb, "_python_candidates", lambda control=None: [legacy])
    monkeypatch.setattr(wb, "_python_has_whisper", lambda p, control=None: p == legacy)
    monkeypatch.setattr(wb, "_cache_path", lambda: tmp_path / "cache")
    assert wb.find_whisper_python() == (legacy if override else None)


def test_diagnostic_probe_handles_whisper_sparse_mps_buffer(monkeypatch):
    from bilingual_sub.adapters import whisper_backend as wb

    sparse = Mock()
    model = SimpleNamespace(alignment_heads=sparse)

    def move(device):
        assert device == "mps"
        if model.alignment_heads is sparse:
            raise RuntimeError("SparseMPS is not supported")

    model.to = move
    whisper = SimpleNamespace(load_model=Mock(return_value=model))
    monkeypatch.setitem(sys.modules, "whisper", whisper)
    monkeypatch.setattr(wb, "resolve_device", lambda req: "mps")
    assert wb.probe_whisper(device="mps")
    whisper.load_model.assert_called_once_with("tiny", device="cpu")
