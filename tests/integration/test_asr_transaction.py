import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bilingual_sub.adapters.whisper_backend import load_transcript, run_asr_worker
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.mark.parametrize("route", ["mps", "explicit"])
@pytest.mark.parametrize("cancel", [False, True])
def test_selected_runtime_runs_external_worker_with_transactional_output(tmp_path, monkeypatch, route, cancel):
    from bilingual_sub.adapters import runtime_bootstrap as rt
    from bilingual_sub.adapters import whisper_backend as wb

    for key in ("SUBFLOW_PYTHON", "SUBFLOW_WHISPER_PYTHON"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SUBFLOW_AUTO_INSTALL", "1")
    monkeypatch.setattr(rt, "torch_backend", lambda: "mps")
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace())
    python = Path(sys.executable).resolve()
    prepared = []
    def prepare(kind, **kwargs):
        prepared.append(kind)
        return python
    monkeypatch.setattr(rt, "ensure_python_env", prepare)
    monkeypatch.setattr(wb, "_cache_path", lambda: tmp_path / "cached-python.txt")
    monkeypatch.setattr(wb, "_python_has_whisper", lambda path: path == python)
    if route == "explicit":
        monkeypatch.setenv("SUBFLOW_PYTHON", str(python))
    monkeypatch.setattr(wb, "_transcribe_inprocess", lambda *a, **kw: pytest.fail("host inference used"))
    script = tmp_path / "selected-worker.py"
    script.write_text("""import os, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index('--out') + 1])
out.write_text('{"segments":[{"start":0,"end":1,"text":"fresh"}]}', encoding='utf-8')
print('selected worker PID=' + str(os.getpid()), flush=True)
""", encoding="utf-8")
    monkeypatch.setattr(wb, "worker_script", lambda: script)
    target = tmp_path / "transcript.json"
    old = b'{"segments":[{"start":0,"end":1,"text":"old"}]}'
    target.write_bytes(old)
    control = JobControl()
    def progress(stage, fraction):
        if cancel and fraction == 0.44:
            control.stop()
    def run():
        return wb.transcribe(tmp_path / "audio.wav", out_json=target,
                             on_progress=progress, control=control)
    if cancel:
        with pytest.raises(JobStopped):
            run()
        assert target.read_bytes() == old
    else:
        assert run()[0].text == "fresh"
        assert load_transcript(target)[0].text == "fresh"
    assert prepared == (["asr"] if route == "mps" else [])
    pid = int((tmp_path / "whisper.log").read_text(encoding="utf-8").strip().split("=")[-1])
    assert pid != os.getpid()
    assert not list(tmp_path.glob(".asr-*"))


@pytest.mark.parametrize("mode", ["missing", "partial", "nan", "cancel", "success"])
def test_worker_result_commit_is_fresh_validated_and_cancellable(tmp_path, mode):
    script = tmp_path / "worker.py"
    write = {
        "missing": "pass",
        "partial": "out.write_text('{'); sys.exit(7)",
        "nan": "out.write_text('{\"segments\":[{\"start\":NaN,\"end\":1,\"text\":\"bad\"}]}')",
        "cancel": "out.write_text('{\"segments\":[{\"start\":0,\"end\":1,\"text\":\"fresh\"}]}')",
        "success": "out.write_text('{\"segments\":[{\"start\":0,\"end\":1,\"text\":\"fresh\"}]}')",
    }[mode]
    script.write_text("import sys\nfrom pathlib import Path\nout=Path(sys.argv[sys.argv.index('--out')+1])\n" + write)
    target = tmp_path / "result/transcript.json"
    target.parent.mkdir()
    old = b'{"segments":[{"start":0,"end":1,"text":"old"}]}'
    target.write_bytes(old)
    control = JobControl()
    def progress(stage, pct):
        if mode == "cancel" and pct == 0.44:
            control.stop()
    def run():
        return run_asr_worker(sys.executable, script, tmp_path / "audio.wav", model_name="tiny",
            language="zh", device="cpu", out_json=target, backend="whisper",
            control=control, on_progress=progress)
    if mode == "success":
        run()
        assert load_transcript(target)[0].text == "fresh"
    else:
        with pytest.raises((RuntimeError, ValueError, JobStopped)):
            run()
        assert target.read_bytes() == old
    assert not list(target.parent.glob(".asr-*"))
    assert not list(target.parent.glob(".transcript-*"))
