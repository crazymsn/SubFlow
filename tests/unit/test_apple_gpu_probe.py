"""Keep hosted-runner hardware failures distinct from GPU test failures."""
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def test_advertised_but_unusable_mps_does_not_pass(monkeypatch):
    probe = runpy.run_path(str(Path(__file__).parents[2] / "scripts/check-apple-gpu.py"))
    torch = SimpleNamespace(
        __version__="test", backends=SimpleNamespace(mps=SimpleNamespace(
            is_built=lambda: True, is_available=lambda: True)),
        ones=Mock(side_effect=RuntimeError("MPS backend out of memory")),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    result = probe["worker"]("asr")
    assert result["mps_built"] and result["mps_available"]
    assert not result["gpu_usable"] and not result["gpu_checks"]
    assert "out of memory" in result["gpu_unavailable_reason"]


def test_gpu_execution_failure_is_not_treated_as_unavailable(monkeypatch):
    probe = runpy.run_path(str(Path(__file__).parents[2] / "scripts/check-apple-gpu.py"))

    class BrokenTensor:
        def __matmul__(self, other):
            raise RuntimeError("GPU computation failed")

    torch = SimpleNamespace(
        __version__="test", backends=SimpleNamespace(mps=SimpleNamespace(
            is_built=lambda: True, is_available=lambda: True)),
        ones=lambda *a, **kw: BrokenTensor(), mps=SimpleNamespace(synchronize=lambda: None),
        allclose=Mock(),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    with pytest.raises(RuntimeError, match="GPU computation failed"):
        probe["worker"]("asr")


@pytest.mark.parametrize("require_gpu", [False, True])
def test_unusable_gpu_report_and_strict_acceptance(monkeypatch, tmp_path, require_gpu):
    from bilingual_sub.adapters import runtime_bootstrap as rt

    probe = runpy.run_path(str(Path(__file__).parents[2] / "scripts/check-apple-gpu.py"))
    report = tmp_path / "report.json"
    argv = ["check-apple-gpu.py", "--report", str(report)]
    if require_gpu:
        argv.append("--require-gpu")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(rt, "ensure_python_env", lambda kind: Path(sys.executable))
    monkeypatch.setattr(rt, "inference_env", lambda: {})
    output = SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
        "mps_built": True, "mps_available": True, "gpu_usable": False, "gpu_checks": [],
    }))
    monkeypatch.setattr(probe["subprocess"], "run", lambda *a, **kw: output)
    if require_gpu:
        with pytest.raises(SystemExit, match="GPU acceptance was not performed"):
            probe["main"]()
    else:
        probe["main"]()
    assert json.loads(report.read_text(encoding="utf-8"))["gpu_verified"] is False
