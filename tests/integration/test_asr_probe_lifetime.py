import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from bilingual_sub.adapters import whisper_backend as wb
from bilingual_sub.adapters import whisperx_backend as wx
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.mark.parametrize("fail", [False, True])
def test_import_probe_reaps_descendant_after_parent_exit(tmp_path, monkeypatch, fail):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wb, "worker_script", lambda: tmp_path / "whisper_worker.py")
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess,sys\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
        f"Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        + ("raise RuntimeError('probe import failed')\n" if fail else "")
    )
    (tmp_path / "subflow_probe_fixture.py").write_text(code, encoding="utf-8")
    child = None
    try:
        assert wb._python_has_module(Path(sys.executable), "subflow_probe_fixture") is not fail
        assert pid_file.is_file()
        pid = int(pid_file.read_text())
        try:
            child = psutil.Process(pid)
            child.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
        except psutil.TimeoutExpired:
            pytest.fail("import probe left its descendant running")
    finally:
        if child is not None:
            try:
                child.kill()
                child.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass


def test_import_probe_does_not_accept_host_pythonpath(tmp_path, monkeypatch):
    fake = tmp_path / "foreign"
    fake.mkdir()
    (fake / "subflow_only_on_host.py").write_text("installed = False\n")
    monkeypatch.setenv("PYTHONPATH", str(fake))
    assert not wb._python_has_module(Path(sys.executable), "subflow_only_on_host")


def test_import_probe_does_not_accept_unrelated_working_directory(tmp_path, monkeypatch):
    (tmp_path / "subflow_only_in_cwd.py").write_text("installed = False\n")
    monkeypatch.chdir(tmp_path)
    assert not wb._python_has_module(Path(sys.executable), "subflow_only_in_cwd")


def test_valid_module_probe_still_succeeds():
    assert wb._python_has_module(Path(sys.executable), "json")


def test_missing_module_probe_still_fails():
    assert not wb._python_has_module(Path(sys.executable), "subflow_intentionally_missing_dependency_884")


@pytest.mark.parametrize("mode", ["timeout", "cancel", "success"])
def test_probe_owns_inherited_stream_descendants(tmp_path, mode):
    pid_file = tmp_path / "child.pid"
    code = (
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        f"Path({str(pid_file)!r}).write_text(str(p.pid))\n"
        + ("time.sleep(60)\n" if mode != "success" else "print('finished')\n")
    )
    control = JobControl()
    def cancel():
        limit = time.monotonic() + 4
        while not pid_file.exists() and time.monotonic() < limit:
            time.sleep(.02)
        control.stop()
    stopper = threading.Thread(target=cancel) if mode == "cancel" else None
    if stopper:
        stopper.start()
    try:
        if mode == "success":
            result = wb._run_probe([sys.executable, "-c", code], timeout=3, control=control)
            assert result.returncode == 0 and result.stdout.strip() == "finished"
        else:
            with pytest.raises(JobStopped if mode == "cancel" else subprocess.TimeoutExpired):
                wb._run_probe([sys.executable, "-c", code], timeout=1, control=control)
        assert pid_file.exists()
        try:
            psutil.Process(int(pid_file.read_text())).wait(timeout=3)
        except psutil.NoSuchProcess:
            pass
        assert not control._procs
    finally:
        control.stop()
        if stopper:
            stopper.join(timeout=5)


def test_probe_bounds_results_and_uses_no_input():
    result = wb._run_probe([sys.executable, "-c", "import sys;assert sys.stdin.read()=='';sys.stdout.write('x'*200000);sys.stderr.write('y'*200000)"], timeout=3)
    assert result.returncode == 0
    assert result.stdout == "x" * 65536 and result.stderr == "y" * 65536


def test_probe_pause_does_not_exhaust_wait_budget(tmp_path):
    ready, finish = tmp_path / "ready", tmp_path / "finish"
    code = f"from pathlib import Path\nimport time\nPath({str(ready)!r}).touch()\nwhile not Path({str(finish)!r}).exists(): time.sleep(.02)\n"
    control = JobControl()
    failures = []
    def pause_resume():
        try:
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert ready.exists()
            control.pause()
            time.sleep(1.3)
            finish.touch()
            control.resume()
        except BaseException as exc:
            failures.append(exc)
            control.stop()
    thread = threading.Thread(target=pause_resume)
    thread.start()
    try:
        result = wb._run_probe([sys.executable, "-c", code], timeout=1, control=control)
        assert result.returncode == 0
    finally:
        control.stop()
        thread.join(timeout=5)
    assert not failures


@pytest.mark.parametrize("route", ["whisper", "whisperx", "available", "provision", "transcribe"])
def test_control_reaches_import_probe_without_swallowing_stop(tmp_path, monkeypatch, route):
    from bilingual_sub.adapters import runtime_bootstrap as rt

    control = JobControl()
    monkeypatch.setenv("SUBFLOW_PYTHON", sys.executable)
    monkeypatch.setattr(rt, "managed_python", lambda kind: Path(sys.executable))
    monkeypatch.setattr(wx, "_python_candidates", lambda control=None: [])
    def stop(args, *, control=None, **kwargs):
        assert control is expected
        raise JobStopped()
    expected = control
    monkeypatch.setattr(wb, "_run_probe", stop)
    with pytest.raises(JobStopped):
        if route == "whisper":
            wb.find_whisper_python(control=control)
        elif route == "whisperx":
            wx.find_whisperx_python(control=control)
        elif route == "available":
            wx.WhisperXBackend().available(control=control)
        elif route == "provision":
            wx.ensure_whisperx_runtime(control=control)
        else:
            wx.WhisperXBackend().transcribe(tmp_path / "audio.wav", model_name="tiny", language="zh", device="cpu", out_json=tmp_path / "out.json", control=control)
