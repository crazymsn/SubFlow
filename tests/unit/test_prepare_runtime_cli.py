import os
import runpy
from pathlib import Path

import pytest

from bilingual_sub.adapters import runtime_bootstrap as rt


@pytest.fixture
def prepare():
    return runpy.run_path(str(Path(__file__).parents[2] / "scripts" / "prepare-runtime.py"))["main"]


@pytest.mark.parametrize("kind,skip", [("asr", False), ("whisperx", False),
                                       ("gptsovits", False), ("gptsovits", True)])
def test_prepare_dispatches_to_client_runtime(prepare, monkeypatch, kind, skip):
    monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", "cpu")
    calls = []
    def python_env(value, **kwargs):
        calls.append((value, kwargs, os.environ.get("SUBFLOW_TORCH_BACKEND")))
        return Path("managed/python")
    def sovits(**kwargs):
        return python_env("gptsovits", **kwargs)
    monkeypatch.setattr(rt, "ensure_python_env", python_env)
    monkeypatch.setattr(rt, "ensure_sovits_runtime", sovits)
    prepare([kind, *(["--skip-models"] if skip else [])])
    assert len(calls) == 1
    assert calls[0][0] == kind
    assert calls[0][2] == "cpu"
    if kind == "gptsovits":
        assert calls[0][1]["models"] == (not skip)


@pytest.mark.parametrize("previous", [None, "cpu"])
@pytest.mark.parametrize("fail", [False, True])
def test_explicit_backend_is_scoped_even_on_failure(prepare, monkeypatch, previous, fail):
    monkeypatch.delenv("SUBFLOW_TORCH_BACKEND", raising=False)
    if previous is not None:
        monkeypatch.setenv("SUBFLOW_TORCH_BACKEND", previous)
    def install(*args, **kwargs):
        assert os.environ["SUBFLOW_TORCH_BACKEND"] == "cuda"
        if fail:
            raise RuntimeError("installation failed")
        return Path("managed/python")
    monkeypatch.setattr(rt, "ensure_python_env", install)
    if fail:
        with pytest.raises(RuntimeError, match="installation failed"):
            prepare(["asr", "--backend", "cuda"])
    else:
        prepare(["asr", "--backend", "cuda"])
    assert os.environ.get("SUBFLOW_TORCH_BACKEND") == previous


@pytest.mark.parametrize("args", [["asr", "--skip-models"], ["asr", "--backend", "invalid"]])
def test_invalid_arguments_do_not_install(prepare, monkeypatch, args):
    monkeypatch.setattr(rt, "ensure_python_env", lambda *a, **kw: pytest.fail("invalid CLI installed runtime"))
    with pytest.raises(SystemExit) as error:
        prepare(args)
    assert error.value.code == 2
