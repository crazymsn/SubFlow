import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def validation():
    path = Path(__file__).resolve().parents[2] / "third_party/GPT-SoVITS/tools/subflow_validation.py"
    spec = importlib.util.spec_from_file_location("subflow_validation_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mps_audio_uses_relocatable_shared_bootstrap(validation, tmp_path, monkeypatch):
    from types import SimpleNamespace

    (tmp_path / 'qwen_mps.py').write_text('def install_convolutions(model):\n    model.installed = True\n')
    monkeypatch.setenv('SUBFLOW_BOOTSTRAP_DIR', str(tmp_path))
    model = SimpleNamespace(installed=False)
    validation.configure_mps_audio(model, 'cpu')
    assert not model.installed
    validation.configure_mps_audio(model, 'mps')
    assert model.installed


@pytest.mark.parametrize("value", [None, "1", True, float("inf"), float("-inf"), 10**400, [], {}])
def test_library_rejects_non_finite_or_invalid_numeric_types(validation, value):
    with pytest.raises(ValueError, match="speed_factor"):
        validation.validate_request({"text": "hello", "speed_factor": value})


@pytest.mark.parametrize("value", [None, "", -1, 0, 2**32 - 1])
def test_seed_compatibility_and_boundaries(validation, value):
    validation.validate_request({"text": "hello", "seed": value})


@pytest.mark.parametrize("value", [True, 1.5, "1", None])
def test_fractional_or_untyped_batch_is_rejected(validation, value):
    with pytest.raises(ValueError, match="batch_size"):
        validation.validate_request({"text": "hello", "batch_size": value})


def test_no_segments_is_a_distinct_error(validation):
    with pytest.raises(validation.NoSpeechError):
        validation.require_speech_segments([])
    validation.require_speech_segments([{"phones": [1]}])
