import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import psutil
import pytest

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.adapters.tts import gptsovits_runtime as rt
from bilingual_sub.adapters.tts.base import TtsUnavailable
from bilingual_sub.core.control import JobControl, JobStopped


def wait_until(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail("process condition did not arrive")


def stopped(pid):
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def parent_script(tmp_path, *, crash=False):
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "api_v2.py"
    ending = "sys.exit(7)" if crash else "time.sleep(60)"
    script.write_text(f"""import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
pid_file = Path({str(pid_file)!r})
pending = pid_file.with_suffix('.pending')
pending.write_text(str(child.pid), encoding='ascii')
pending.replace(pid_file)
{ending}
""", encoding="utf-8")
    return script, pid_file


@pytest.fixture
def local_runtime(tmp_path, monkeypatch):
    from bilingual_sub.adapters import runtime_bootstrap as bootstrap

    monkeypatch.setattr(rt, "launch_python", lambda *a, **k: [sys.executable])
    monkeypatch.setattr(rt, "_log_path", lambda: tmp_path / "server.log")
    monkeypatch.setattr(rt, "runtime_config", lambda root: {})
    monkeypatch.setattr(rt, "discover_home", lambda: tmp_path)
    monkeypatch.setattr(rt, "missing_pretrained", lambda root: [])
    monkeypatch.setattr(rt, "find_sovits_python", lambda root: Path(sys.executable))
    monkeypatch.setattr(bootstrap, "source_update_needed", lambda root: False)
    monkeypatch.setattr(bootstrap, "assets_update_needed", lambda root: False)
    monkeypatch.setattr(rt, "probe_endpoint", lambda *a, **k: False)
    return tmp_path


@pytest.mark.parametrize("crash", [False, True])
def test_shutdown_cleans_server_descendants_even_after_parent_crash(local_runtime, crash):
    _, pid_file = parent_script(local_runtime, crash=crash)
    proc = rt.start_server("http://127.0.0.1:19880", home=local_runtime)
    wait_until(pid_file.exists)
    child = int(pid_file.read_text())
    if crash:
        proc.wait(timeout=8)
    rt.stop_servers()
    wait_until(lambda: stopped(child))
    assert proc.poll() is not None
    assert not rt._server_owners


def test_failed_boot_reaps_descendants_before_retry(local_runtime):
    _, pid_file = parent_script(local_runtime, crash=True)
    with pytest.raises(TtsUnavailable, match="进程已退出"):
        rt.ensure_running("http://127.0.0.1:19880", wait_sec=8)
    child = int(pid_file.read_text())
    wait_until(lambda: stopped(child))
    assert not rt._children
    assert not rt._server_owners


def test_shutdown_during_spawn_cleans_unregistered_server(local_runtime, monkeypatch):
    _, pid_file = parent_script(local_runtime)
    @contextmanager
    def shutdown_after_spawn(*args, **kwargs):
        with owned_process(*args, **kwargs) as proc:
            wait_until(pid_file.exists)
            rt.request_shutdown()
            yield proc
    monkeypatch.setattr(rt, "owned_process", shutdown_after_spawn)
    with pytest.raises(JobStopped):
        rt.start_server("http://127.0.0.1:19880", home=local_runtime)
    wait_until(lambda: stopped(int(pid_file.read_text())))
    assert not rt._server_owners


@pytest.mark.parametrize("mode", ["crash", "timeout", "cancel"])
def test_dependency_probe_cleans_its_process_tree(tmp_path, mode):
    script, pid_file = parent_script(tmp_path, crash=mode == "crash")
    control = JobControl()
    cancel_thread = None
    if mode == "cancel":
        def cancel():
            deadline = time.monotonic() + 8
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            control.stop()
        cancel_thread = threading.Thread(target=cancel)
        cancel_thread.start()
    try:
        if mode == "cancel":
            with pytest.raises(JobStopped):
                rt.python_has_sovits_deps([sys.executable, str(script)], timeout=8, control=control)
        else:
            assert not rt.python_has_sovits_deps([sys.executable, str(script)], timeout=3)
        wait_until(pid_file.exists)
        wait_until(lambda: stopped(int(pid_file.read_text())))
    finally:
        if cancel_thread:
            cancel_thread.join(timeout=10)


def test_waiting_for_another_startup_can_be_cancelled(monkeypatch):
    probe_entered = threading.Event()
    def probe(*a, **k):
        probe_entered.set()
        return False
    monkeypatch.setattr(rt, "probe_endpoint", probe)
    control = JobControl()
    errors = []
    def waiter():
        try:
            rt.ensure_running("http://127.0.0.1:19880", control=control)
        except Exception as exc:
            errors.append(exc)
    rt._spawn_lock.acquire()
    thread = threading.Thread(target=waiter)
    try:
        thread.start()
        assert probe_entered.wait(timeout=3)
        control.stop()
        thread.join(timeout=3)
        assert not thread.is_alive(), "cancelled caller remained blocked on another startup"
        assert len(errors) == 1 and isinstance(errors[0], JobStopped)
    finally:
        rt._spawn_lock.release()
        thread.join(timeout=10)


def test_external_service_is_not_owned_or_stopped(monkeypatch):
    monkeypatch.setattr(rt, "probe_endpoint", lambda *a, **k: True)
    with owned_process([sys.executable, "-c", "import time; time.sleep(60)"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as external:
        assert rt.ensure_running("http://127.0.0.1:19880") == "ready"
        rt.stop_servers()
        assert external.poll() is None
