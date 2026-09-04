import subprocess
import threading
import time
from unittest.mock import MagicMock

import pytest

from bilingual_sub.core.control import JobControl, JobStopped


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
