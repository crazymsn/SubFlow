import sys

import pytest

from bilingual_sub.adapters.whisper_backend import load_transcript, run_asr_worker
from bilingual_sub.core.control import JobControl, JobStopped


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
