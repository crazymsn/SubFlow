from pathlib import Path

import pytest

from bilingual_sub.adapters import runtime_bootstrap as rt
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFLOW_RUNTIME_DIR", str(tmp_path / "managed"))
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", "cpu")
    monkeypatch.setattr(rt, "find_uv", lambda **kw: Path("uv"))
    calls = []
    def run(args, *a, **kw):
        calls.append(args)
        if args[1] == "venv":
            python = rt.managed_python("asr")
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"interpreter")
    monkeypatch.setattr(rt, "_run", run)
    python = rt.ensure_python_env("asr")
    calls.clear()
    return python, calls, run


def test_ready_marker_does_not_hide_broken_imports(environment, monkeypatch):
    python, calls, run = environment
    broken = True
    def fail_once(args, *a, **kw):
        nonlocal broken
        if args[1] == "-c" and broken:
            broken = False
            raise RuntimeError("missing package")
        run(args, *a, **kw)
    monkeypatch.setattr(rt, "_run", fail_once)
    assert rt.ensure_python_env("asr") == python
    assert sum("--reinstall" in call for call in calls) == 2
    assert any("--allow-existing" in call for call in calls)
    assert (python.parent.parent / ".subflow-ready").is_file()


def test_cancelled_environment_probe_does_not_reinstall(environment, monkeypatch):
    python, calls, _ = environment
    def cancel(*a, **kw):
        raise JobStopped()
    monkeypatch.setattr(rt, "_run", cancel)
    with pytest.raises(JobStopped):
        rt.ensure_python_env("asr", control=JobControl())
    assert calls == []
    assert (python.parent.parent / ".subflow-ready").is_file()


def test_disabled_auto_install_reports_corrupt_environment(environment, monkeypatch):
    _, calls, _ = environment
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    def fail(*a, **kw):
        raise RuntimeError("broken dependency")
    monkeypatch.setattr(rt, "_run", fail)
    with pytest.raises(RuntimeError, match="已损坏.*SUBFLOW_AUTO_INSTALL=0"):
        rt.ensure_python_env("asr")
    assert calls == []


def test_failed_repair_removes_ready_marker_and_next_attempt_reinstalls(environment, monkeypatch):
    python, calls, run = environment
    marker = python.parent.parent / ".subflow-ready"
    marker.write_text("old stamp")
    def fail(*a, **kw):
        raise RuntimeError("installation interrupted")
    monkeypatch.setattr(rt, "_run", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        rt.ensure_python_env("asr")
    assert not marker.exists()
    monkeypatch.setattr(rt, "_run", run)
    rt.ensure_python_env("asr")
    assert marker.exists()
    assert sum("--reinstall" in call for call in calls) == 2
    assert not marker.with_name(marker.name + ".pending").exists()


def test_disabled_auto_install_does_not_copy_missing_sovits_source(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFLOW_RUNTIME_DIR", str(tmp_path / "managed"))
    monkeypatch.setenv("SUBFLOW_GPTSOVITS_HOME", str(tmp_path / "sovits"))
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    monkeypatch.setattr("bilingual_sub.adapters.tts.gptsovits_runtime.copy_runtime_tree",
                        lambda *a: pytest.fail("disabled installer copied source"))
    with pytest.raises(RuntimeError, match="SUBFLOW_AUTO_INSTALL=0"):
        rt.ensure_sovits_runtime()


def test_disabled_auto_install_does_not_download_missing_assets(tmp_path, monkeypatch):
    home = tmp_path / "sovits"
    home.mkdir()
    (home / "api_v2.py").write_text("# existing source")
    monkeypatch.setenv("SUBFLOW_RUNTIME_DIR", str(tmp_path / "managed"))
    monkeypatch.setenv("SUBFLOW_GPTSOVITS_HOME", str(home))
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    monkeypatch.setattr(rt, "ensure_python_env", lambda *a, **kw: Path("python"))
    monkeypatch.setattr(rt, "_run", lambda *a, **kw: pytest.fail("disabled installer downloaded assets"))
    with pytest.raises(RuntimeError, match="配音资源需要修复"):
        rt.ensure_sovits_runtime()


def test_relative_runtime_override_resolves_before_changing_worker_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUBFLOW_RUNTIME_DIR", "my-runtime")
    assert rt.runtime_root() == tmp_path / "my-runtime"
