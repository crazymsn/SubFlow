import os
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psutil

from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.adapters.ytdlp import download
from bilingual_sub.core.control import JobControl, JobStopped


def alive(pid):
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def eventually(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    assert predicate()


def test_stop_interrupts_real_blocked_http_request(tmp_path):
    requested, release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            requested.set()
            release.wait(20)
            self.send_response(200)
            self.end_headers()

        do_HEAD = do_GET

        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    ctl = JobControl()
    errors = []
    old = tmp_path / "source.mp4"
    old.write_bytes(b"old video")
    def run():
        try:
            download(f"http://127.0.0.1:{server.server_port}/blocked.mp4", tmp_path, control=ctl)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert requested.wait(15), "download worker did not reach HTTP server"
        with ctl._lock:
            pids = [p.pid for proc in ctl._procs for p in
                    [psutil.Process(proc.pid), *psutil.Process(proc.pid).children(recursive=True)]]
        started = time.monotonic()
        ctl.stop()
        worker.join(timeout=10)
        assert time.monotonic() - started < 10
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], JobStopped), "".join(
            traceback.format_exception(errors[0])) if errors else "worker returned without cancellation"
        eventually(lambda: all(not alive(pid) for pid in pids))
        assert old.read_bytes() == b"old video"
        assert not list(tmp_path.glob(".subflow-download-*"))
    finally:
        ctl.stop()
        release.set()
        worker.join(timeout=10)
        server.shutdown()
        server.server_close()
        serving.join(timeout=3)


def test_pause_resume_and_stop_include_worker_descendants(tmp_path, monkeypatch):
    child_ticks, parent_ticks = tmp_path / "child.txt", tmp_path / "parent.txt"
    pid_file = tmp_path / "child.pid"
    child_code = f"""import time
from pathlib import Path
p = Path({str(child_ticks)!r})
while True:
    p.write_text(str(time.monotonic()))
    time.sleep(0.05)
"""
    script = tmp_path / "blocking_worker.py"
    script.write_text(f"""import json, subprocess, sys, time
from pathlib import Path
job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
child = subprocess.Popen([sys.executable, '-c', {child_code!r}])
Path({str(pid_file)!r}).write_text(str(child.pid))
progress = Path(job['dest']) / 'download-progress.jsonl'
progress.write_text(json.dumps({{'stage':'ingest','progress':0.1}}) + '\\n')
while True:
    Path({str(parent_ticks)!r}).write_text(str(time.monotonic()))
    time.sleep(0.05)
""", encoding="utf-8")
    monkeypatch.setattr("bilingual_sub.adapters.download_worker.worker_command",
                        lambda job: [sys.executable, str(script), str(job)])
    ctl = JobControl()
    errors = []
    def run():
        try:
            download("https://example.invalid/video", tmp_path / "download", control=ctl)
        except Exception as exc:
            errors.append(exc)
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        eventually(lambda: child_ticks.exists() and parent_ticks.exists())
        ctl.pause()
        before = (child_ticks.read_bytes(), parent_ticks.read_bytes())
        time.sleep(0.3)
        assert (child_ticks.read_bytes(), parent_ticks.read_bytes()) == before
        ctl.resume()
        eventually(lambda: child_ticks.read_bytes() != before[0] and parent_ticks.read_bytes() != before[1])
        ctl.pause()
        ctl.stop()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], JobStopped), "".join(
            traceback.format_exception(errors[0])) if errors else "worker returned without cancellation"
        eventually(lambda: not alive(int(pid_file.read_text())))
        assert not list((tmp_path / "download").glob(".subflow-download-*"))
    finally:
        ctl.stop()
        worker.join(timeout=10)


def test_worker_exit_does_not_leave_orphan_descendant(tmp_path):
    pid_file = tmp_path / "orphan.pid"
    script = tmp_path / "crash.py"
    script.write_text(f"""import subprocess, sys, os
from pathlib import Path
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path({str(pid_file)!r}).write_text(str(p.pid))
os._exit(7)
""", encoding="utf-8")
    with owned_process([sys.executable, str(script)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=dict(os.environ)) as proc:
        assert proc.wait(timeout=10) == 7
        child = int(pid_file.read_text())
    eventually(lambda: not alive(child))
