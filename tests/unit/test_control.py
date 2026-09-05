import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock

import pytest

from bilingual_sub.core.control import JobControl, JobStopped


def test_logged_worker_normal_exit_detaches():
    from bilingual_sub.adapters.procwin import hidden_run_kwargs
    from bilingual_sub.core.control import wait_for_process

    control = JobControl()
    proc = subprocess.Popen([sys.executable, "-c", "pass"], **hidden_run_kwargs())
    assert wait_for_process(proc, control=control) == 0
    assert control._procs == []


def test_callback_failure_stops_real_worker_and_its_child(tmp_path):
    from bilingual_sub.adapters.procwin import hidden_run_kwargs, terminate_process_tree
    from bilingual_sub.core.control import wait_for_process

    marker = tmp_path / "heartbeat"
    child = (
        "import time; from pathlib import Path; "
        f"p=Path({str(marker)!r});\n"
        "while True:\n p.write_text(str(time.time_ns())); time.sleep(0.02)"
    )
    parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", parent], **hidden_run_kwargs())
    control = JobControl()
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), "child did not start"

        def fail():
            raise ValueError("progress callback failed")

        with pytest.raises(ValueError, match="progress callback failed"):
            wait_for_process(proc, control=control, on_tick=fail)
        assert proc.poll() is not None and control._procs == []
        before = marker.stat().st_mtime_ns
        time.sleep(0.15)
        assert marker.stat().st_mtime_ns == before
    finally:
        if proc.poll() is None:
            terminate_process_tree(proc)
            proc.wait(timeout=5)


def test_stop_raises():
    ctl = JobControl()
    ctl.stop()
    with pytest.raises(JobStopped):
        ctl.check()
    with pytest.raises(JobStopped):
        ctl.wait_if_paused()


def test_pause_blocks_then_resume():
    ctl = JobControl()
    hit = []

    def worker():
        ctl.wait_if_paused()
        hit.append(1)

    ctl.pause()
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    assert hit == []
    ctl.resume()
    t.join(timeout=1)
    assert hit == [1]


def test_stop_unblocks_paused_and_raises():
    ctl = JobControl()
    err = []

    def worker():
        try:
            ctl.wait_if_paused()
        except JobStopped as exc:
            err.append(exc)

    ctl.pause()
    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    ctl.stop()
    t.join(timeout=1)
    assert err


def test_kill_attached_fake_popen():
    ctl = JobControl()
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    ctl.attach_proc(proc)
    ctl.kill_attached()
    assert proc.terminate.called or proc.kill.called


def test_pause_suspends_attached_proc(monkeypatch):
    hits: list[str] = []
    monkeypatch.setattr("bilingual_sub.core.control._suspend_proc", lambda _proc: hits.append("suspend"))
    monkeypatch.setattr("bilingual_sub.core.control._resume_proc", lambda _proc: hits.append("resume"))
    ctl = JobControl()
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    ctl.attach_proc(proc)
    ctl.pause()
    assert "suspend" in hits
    ctl.resume()
    assert "resume" in hits
    ctl.stop()
    assert proc.terminate.called or proc.kill.called


def test_concurrent_resume_cannot_overtake_suspend(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    order = []

    def suspend(proc):
        entered.set()
        assert release.wait(timeout=3)
        order.append("suspend")

    monkeypatch.setattr("bilingual_sub.core.control._suspend_proc", suspend)
    monkeypatch.setattr("bilingual_sub.core.control._resume_proc", lambda proc: order.append("resume"))
    ctl = JobControl()
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    ctl.attach_proc(proc)
    pausing = threading.Thread(target=ctl.pause)
    resuming = threading.Thread(target=ctl.resume)
    pausing.start()
    assert entered.wait(timeout=1)
    resuming.start()
    time.sleep(0.05)
    release.set()
    pausing.join(timeout=2)
    resuming.join(timeout=2)
    assert not pausing.is_alive() and not resuming.is_alive()
    assert order == ["suspend", "resume"]
    assert not ctl.is_paused()


def test_pipe_read_failure_is_not_reported_as_success():
    ctl = JobControl()
    proc = MagicMock(spec=subprocess.Popen)
    proc.poll.return_value = None
    proc.communicate.side_effect = OSError("pipe was closed")
    with pytest.raises(RuntimeError, match="读取子进程输出失败") as err:
        ctl.run_attached(proc)
    assert isinstance(err.value.__cause__, OSError)
    assert proc.terminate.called or proc.kill.called
    assert ctl._procs == []


def test_stop_interrupts_network_backoff():
    ctl = JobControl()
    started = threading.Event()
    stopped = threading.Event()

    def backoff():
        started.set()
        try:
            ctl.wait_seconds(60)
        except JobStopped:
            stopped.set()

    worker = threading.Thread(target=backoff, daemon=True)
    worker.start()
    assert started.wait(1)
    ctl.stop()
    worker.join(timeout=2)
    assert stopped.is_set() and not worker.is_alive()
