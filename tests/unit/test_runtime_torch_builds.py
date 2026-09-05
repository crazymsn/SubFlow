import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bilingual_sub.adapters import runtime_bootstrap as rt


def install(monkeypatch, tmp_path, backend):
    monkeypatch.setenv("SUBFLOW_RUNTIME_DIR", str(tmp_path / "managed"))
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", backend)
    monkeypatch.setattr(rt, "sys", SimpleNamespace(platform="darwin" if backend == "mps" else "win32"))
    monkeypatch.setattr(rt.platform, "machine", lambda: "arm64" if backend == "mps" else "AMD64")
    monkeypatch.setattr(rt, "find_uv", lambda **kw: Path("uv"))
    calls = []
    def run(args, *a, **kw):
        calls.append(args)
        if args[1] == "venv":
            relative = rt.managed_python("asr").relative_to(rt.managed_env("asr"))
            python = Path(args[-1]) / relative
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"test interpreter")
    monkeypatch.setattr(rt, "_run", run)
    python = rt.ensure_python_env("asr")
    return python, calls


@pytest.mark.parametrize("backend,wheel", [("cpu", "cpu"), ("cuda", "cu124")])
def test_both_install_phases_and_repair_pin_the_selected_torch_build(monkeypatch, tmp_path, backend, wheel):
    python, calls = install(monkeypatch, tmp_path, backend)
    (python.parent.parent / ".subflow-ready").write_text("old stamp", encoding="ascii")
    rt.ensure_python_env("asr")
    pip_calls = [args for args in calls if args[1:3] == ["pip", "install"]]
    assert len(pip_calls) == 4
    for args in pip_calls:
        assert args[args.index("--torch-backend") + 1] == wheel
    requirement_calls = [args for args in pip_calls if "-r" in args]
    for args in requirement_calls:
        constraints = Path(args[args.index("-c") + 1])
        assert constraints.parent == python.parent.parent
        assert constraints.read_text(encoding="utf-8") == (
            f"torch==2.5.1+{wheel}\ntorchaudio==2.5.1+{wheel}\n")


@pytest.mark.parametrize("backend", ["cpu", "cuda", "mps"])
def test_import_probe_rejects_wrong_torch_build(monkeypatch, tmp_path, backend):
    _, calls = install(monkeypatch, tmp_path, backend)
    code = [args[2] for args in calls if args[1] == "-c"][-1]
    torch = SimpleNamespace(__version__="2.5.1", version=SimpleNamespace(cuda=None),
                            backends=SimpleNamespace(mps=SimpleNamespace(is_built=lambda: False)))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torchaudio", SimpleNamespace(__version__="2.5.1"))
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace())
    with pytest.raises(RuntimeError, match="PyTorch|MPS"):
        exec(code, {})


def test_valid_legacy_marker_can_migrate_without_reinstall(monkeypatch, tmp_path):
    python, calls = install(monkeypatch, tmp_path, "cpu")
    marker = python.parent.parent / ".subflow-ready"
    old = hashlib.sha256((rt.bootstrap_assets() / "asr.txt").read_bytes() + b"2.5.1|cpu|v1").hexdigest()
    marker.write_text(old, encoding="ascii")
    calls.clear()
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "0")
    assert rt.ensure_python_env("asr") == python
    assert len(calls) == 1 and calls[0][1] == "-c"
    assert marker.read_text(encoding="ascii") != old


@pytest.mark.parametrize("backend,version,cuda", [
    ("cpu", "2.5.1+cpu", None), ("cuda", "2.5.1+cu124", "12.4"), ("mps", "2.5.1", None),
])
def test_probe_accepts_correct_build_without_requiring_available_gpu(monkeypatch, tmp_path, backend, version, cuda):
    _, calls = install(monkeypatch, tmp_path, backend)
    code = [args[2] for args in calls if args[1] == "-c"][-1]
    torch = SimpleNamespace(__version__=version, version=SimpleNamespace(cuda=cuda),
                            backends=SimpleNamespace(mps=SimpleNamespace(is_built=lambda: True)))
    monkeypatch.setitem(sys.modules, "torch", torch)
    audio = SimpleNamespace(__version__=version)
    monkeypatch.setitem(sys.modules, "torchaudio", audio)
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace())
    exec(code, {})
    audio.__version__ = "0.0.0"
    with pytest.raises(RuntimeError, match="PyTorch build mismatch"):
        exec(code, {})


def test_runtime_constraints_are_not_shared_between_installation_locks(monkeypatch, tmp_path):
    _, calls = install(monkeypatch, tmp_path, "cpu")
    rt.ensure_python_env("gptsovits")
    constraints = [Path(args[args.index("-c") + 1]) for args in calls if "-r" in args]
    assert len(constraints) == 2 and constraints[0] != constraints[1]
    assert all(path.read_text(encoding="utf-8") == "torch==2.5.1+cpu\ntorchaudio==2.5.1+cpu\n"
               for path in constraints)


def test_mps_probe_rejects_intel_interpreter_even_with_mps_compiled(monkeypatch):
    monkeypatch.setattr(rt.platform, "machine", lambda: "x86_64")
    torch = SimpleNamespace(__version__="2.5.1", version=SimpleNamespace(cuda=None),
                            backends=SimpleNamespace(mps=SimpleNamespace(is_built=lambda: True)))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torchaudio", SimpleNamespace(__version__="2.5.1"))
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace())
    with pytest.raises(RuntimeError, match="native Apple Silicon"):
        exec(rt._runtime_probe("asr", "2.5.1", "mps"), {})


def test_foreign_uv_backend_does_not_override_application_device(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBFLOW_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("UV_TORCH_BACKEND", "auto")
    assert "UV_TORCH_BACKEND" not in rt.install_env()


@pytest.mark.parametrize("machine,expected", [("arm64", "2.5.1"), ("x86_64", "2.2.2")])
def test_macos_uses_native_wheels_without_cuda_index(monkeypatch, machine, expected):
    monkeypatch.setattr(rt, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(rt.platform, "machine", lambda: machine)
    assert rt._torch_build("cpu") == (expected, expected, [])
