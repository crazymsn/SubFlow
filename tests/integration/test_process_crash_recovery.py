import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from filelock import FileLock

from bilingual_sub import pipeline as p
from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.core.file_io import file_digest
from bilingual_sub.core.resource_claims import registry_dir


def run_worker(root, phase, step):
    script = Path(__file__).parents[1] / "helpers" / "pipeline_crash_worker.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(p.__file__).parents[1]) + os.pathsep + env.get("PYTHONPATH", "")
    with owned_process([sys.executable, str(script), str(root), phase, step],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env) as proc:
        output, _ = proc.communicate(timeout=30)
        return proc.returncode, output.decode("utf-8", errors="replace")


@pytest.mark.parametrize("phase,completed", [
    ("transcribe", "silence"), ("subtitle", "fit_subs"), ("completion", "dub"),
])
def test_real_process_crash_cannot_certify_unfinished_stages(tmp_path, phase, completed):
    rc, output = run_worker(tmp_path, phase, "seed")
    assert rc == 0, output
    work = tmp_path / "work"
    state_path = work / "job_state.json"
    old_ass = (work / "subs.ass").read_bytes()
    rc, output = run_worker(tmp_path, phase, "crash")
    assert rc == 77, output
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["completed_stage"] == completed
    assert list(registry_dir().glob("*.json"))  # Abrupt exit bypassed cleanup.
    with FileLock(str(work / ".job.lock"), timeout=0):
        pass
    if phase == "subtitle":
        assert (tmp_path / "out.ass").read_bytes() != old_ass
        assert (work / "subs.ass").read_bytes() == old_ass
    if phase == "completion":
        partial_report = json.loads((work / "report.json").read_text(encoding="utf-8"))
        assert partial_report["last_stage"] == "done" and state["stage"] != "done"
    else:
        rc, output = run_worker(tmp_path, phase, "reject")
        assert rc != 0 and "ValueError" in output, output
        assert json.loads(state_path.read_text(encoding="utf-8"))["completed_stage"] == completed
    rc, output = run_worker(tmp_path, phase, "recover")
    assert rc == 0, output
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report = json.loads((work / "report.json").read_text(encoding="utf-8"))
    assert state["stage"] == report["last_stage"] == "done"
    assert state["job_id"] == report["job_id"]
    assert not state["stopped"]
    count = int((tmp_path / "asr-count.txt").read_text(encoding="ascii"))
    assert count == (3 if phase == "transcribe" else 1)
    srt = Path(report["output_srt"])
    assert f"version {count}" in srt.read_text(encoding="utf-8")
    assert report["output_hashes"]["srt"] == file_digest(srt)
    assert report["output_hashes"]["ass"] == file_digest(srt.with_suffix(".ass"))
    assert not list(registry_dir().glob("*.json"))
