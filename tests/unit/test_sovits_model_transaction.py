import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def transaction():
    source = Path(__file__).resolve().parents[2] / "third_party/GPT-SoVITS/tools/subflow_model_transaction.py"
    spec = importlib.util.spec_from_file_location("sovits_model_transaction_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def model(transaction, tmp_path):
    saved = []
    class DerivedTensor:
        def __deepcopy__(self, memo):
            pytest.fail("model/config cloning must not deepcopy tensors")
    class Config:
        def __init__(self):
            self.path = tmp_path / "config.json"
            self.weights = "original"
            self.defaults = {"nested": [1]}
            self.derived = DerivedTensor()
        def save_configs(self):
            if getattr(self, "_defer_save", False):
                return
            transaction.atomic_config_write(self.path, json.dumps({"weights": self.weights}))
            saved.append(self.weights)
    class Model:
        def __init__(self):
            self.configs = Config()
            self.network = object()
            self.prompt_cache = {"refer_spec": ["original"]}
            self.vocoder_configs = {"rates": [1]}
        @transaction.model_update
        def update(self, weights, failure=False, *, save=True):
            self.configs.weights = weights
            self.configs.defaults["nested"].append(2)
            self.configs.save_configs()
            self.network = object()
            self.prompt_cache["refer_spec"][0] = "new"
            self.vocoder_configs["rates"].append(2)
            if failure:
                raise ValueError("model failed late")
        @transaction.model_update
        def reset(self, failure=False):
            self.update("replacement")
            if failure:
                raise ValueError("later component failed")
    instance = Model()
    instance.configs.save_configs()
    return instance, saved


def test_model_failure_preserves_all_serving_state_and_file(model):
    instance, saved = model
    original = instance.__dict__
    config_text = instance.configs.path.read_bytes()
    with pytest.raises(ValueError):
        instance.update("broken", True)
    assert instance.__dict__ is original
    assert instance.configs.weights == "original"
    assert instance.configs.defaults == {"nested": [1]}
    assert instance.prompt_cache == {"refer_spec": ["original"]}
    assert instance.vocoder_configs == {"rates": [1]}
    assert instance.configs.path.read_bytes() == config_text
    assert saved == ["original"]


def test_publication_failure_keeps_model_and_config(model, monkeypatch):
    instance, saved = model
    original = instance.__dict__
    replace = Path.replace
    def fail(path, target):
        if target == instance.configs.path:
            raise PermissionError("config busy")
        return replace(path, target)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(PermissionError):
        instance.update("replacement")
    assert instance.__dict__ is original
    assert json.loads(instance.configs.path.read_text()) == {"weights": "original"}
    assert saved == ["original"]
    assert not list(instance.configs.path.parent.glob(".subflow-config-*.tmp"))


@pytest.mark.parametrize("failure", [False, True])
def test_nested_model_loads_publish_once_or_roll_back_together(model, failure):
    instance, saved = model
    original = instance.__dict__
    if failure:
        with pytest.raises(ValueError):
            instance.reset(True)
        assert instance.__dict__ is original
        assert saved == ["original"]
    else:
        instance.reset()
        assert instance.__dict__ is not original
        assert instance.network is not original["network"]
        assert instance.configs.derived is original["configs"].derived
        assert saved == ["original", "replacement"]
        assert not hasattr(instance, "_model_update_in_progress")


def test_save_false_updates_memory_without_persisting(model):
    instance, saved = model
    instance.update("temporary", save=False)
    assert instance.configs.weights == "temporary"
    assert json.loads(instance.configs.path.read_text()) == {"weights": "original"}
    assert saved == ["original"]


def test_config_write_failure_before_replace_preserves_previous_file(transaction, tmp_path, monkeypatch):
    path = tmp_path / "模型.yaml"
    path.write_text("old", encoding="utf-8")
    def fail(fd):
        raise OSError("disk full")
    monkeypatch.setattr(transaction.os, "fsync", fail)
    with pytest.raises(OSError, match="disk full"):
        transaction.atomic_config_write(path, "new")
    assert path.read_text() == "old"
    assert not list(tmp_path.glob(".subflow-config-*.tmp"))
