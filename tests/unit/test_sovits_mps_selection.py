from types import SimpleNamespace

import pytest

from bilingual_sub.adapters import runtime_bootstrap as bootstrap
from bilingual_sub.adapters.tts import gptsovits_runtime as rt


@pytest.fixture
def locations(tmp_path, monkeypatch):
    monkeypatch.delenv("SUBFLOW_GPTSOVITS_HOME", raising=False)
    monkeypatch.delenv("SUBFLOW_GPTSOVITS_PYTHON", raising=False)
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    monkeypatch.setattr(bootstrap, "torch_backend", lambda: "mps")
    cache, bundle, foreign = (tmp_path / name for name in ("cache", "bundle", "foreign"))
    for path in (cache, bundle, foreign):
        path.mkdir()
        (path / "api_v2.py").write_text("# source fixture", encoding="utf-8")
    managed = tmp_path / "managed" / "bin" / "python"
    managed.parent.mkdir(parents=True)
    legacy = cache / "venv" / "bin" / "python3"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"old interpreter")
    monkeypatch.setattr(bootstrap, "managed_python", lambda kind: managed)
    monkeypatch.setattr(rt, "default_home", lambda: cache)
    monkeypatch.setattr(rt, "bundled_src", lambda: bundle)
    monkeypatch.setattr(rt, "_frozen_roots", lambda: [bundle])
    monkeypatch.setattr(rt, "extra_home_candidates", lambda: [foreign])
    monkeypatch.setattr(rt, "missing_pretrained", lambda path: [] if path == foreign else ["missing model"])
    monkeypatch.setattr(rt, "_host_python", lambda: ["unrelated-host-python"])
    return cache, bundle, foreign, managed, legacy


def test_mps_uses_managed_interpreter_before_cached_legacy_venv(locations):
    cache, _, _, managed, _ = locations
    managed.write_bytes(b"native managed interpreter")
    assert rt.find_sovits_python(cache) == managed


def test_mps_missing_managed_interpreter_requests_preparation(locations):
    cache, _, _, _, _ = locations
    assert rt.find_sovits_python(cache) is None
    assert rt._python_candidates(cache) == []


def test_mps_has_no_host_fallback_when_managed_interpreter_fails(locations, monkeypatch):
    cache, _, _, managed, _ = locations
    managed.write_bytes(b"broken managed interpreter")
    checked = []
    def probe(cmd, **kwargs):
        checked.append(cmd)
        return False
    monkeypatch.setattr(rt, "python_has_sovits_deps", probe)
    with pytest.raises(FileNotFoundError):
        rt.launch_python(cache)
    assert checked == [[str(managed)]]


def test_mps_prefers_project_cache_to_complete_unrelated_installation(locations):
    cache, _, _, _, _ = locations
    assert rt.discover_home() == cache


def test_mps_without_cache_uses_project_source(locations):
    cache, bundle, _, _, _ = locations
    (cache / "api_v2.py").unlink()
    assert rt.discover_home() == bundle


def test_mps_missing_project_source_does_not_run_unrelated_source(locations):
    cache, bundle, _, _, _ = locations
    (cache / "api_v2.py").unlink()
    (bundle / "api_v2.py").unlink()
    assert rt.discover_home() is None


def test_explicit_interpreter_is_preserved(locations, monkeypatch):
    cache, _, _, _, legacy = locations
    monkeypatch.setenv("SUBFLOW_GPTSOVITS_PYTHON", str(legacy))
    assert rt.find_sovits_python(cache) == legacy.resolve()
    assert rt._python_candidates(cache) == [[str(legacy.resolve())]]


def test_explicit_home_is_preserved(locations, monkeypatch):
    cache, _, _, _, legacy = locations
    monkeypatch.setenv("SUBFLOW_GPTSOVITS_HOME", str(cache))
    assert rt.discover_home() == cache.resolve()
    assert rt.find_sovits_python(cache) == legacy


@pytest.mark.parametrize("override", ["cpu", "disabled"])
def test_nonautomatic_mps_selection_retains_manual_compatibility(locations, monkeypatch, override):
    cache, _, _, _, legacy = locations
    if override == "cpu":
        monkeypatch.setattr(bootstrap, "torch_backend", lambda: "cpu")
    else:
        monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    assert rt.find_sovits_python(cache) == legacy


@pytest.mark.parametrize("failed", [False, True])
def test_mps_validates_cached_environment_before_starting_server(locations, monkeypatch, failed):
    cache, _, _, managed, _ = locations
    managed.write_bytes(b"existing interpreter")
    monkeypatch.setattr(rt, "missing_pretrained", lambda root: [])
    monkeypatch.setattr(bootstrap, "source_update_needed", lambda root: False)
    monkeypatch.setattr(bootstrap, "assets_update_needed", lambda root: False)
    events = []
    monkeypatch.setattr(rt, "probe_endpoint", lambda *a, **kw: "start" in events)
    def prepare(**kwargs):
        events.append("validate")
        if failed:
            raise RuntimeError("native runtime cannot be repaired")
        return cache
    def start(*args, **kwargs):
        assert events == ["validate"]
        assert kwargs["home"] == cache
        assert rt._python_candidates(cache) == [[str(managed)]]
        events.append("start")
        return SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(bootstrap, "ensure_sovits_runtime", prepare)
    monkeypatch.setattr(rt, "start_server", start)
    endpoint = "http://127.0.0.1:19883"
    try:
        if failed:
            with pytest.raises(RuntimeError, match="cannot be repaired"):
                rt.ensure_running(endpoint, wait_sec=1)
            assert events == ["validate"]
        else:
            assert rt.ensure_running(endpoint, wait_sec=1) == "started"
            assert events == ["validate", "start"]
    finally:
        rt._children.pop(endpoint, None)
