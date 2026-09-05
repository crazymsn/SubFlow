"""Exercise the actual frozen launcher and its bundled external executables."""
import argparse
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bilingual_sub.adapters.ytdlp import download
from bilingual_sub.core.control import JobControl, JobStopped


def check_frozen_download_cancel(client: Path) -> None:
    requested, release = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            requested.set()
            release.wait(30)
            self.send_response(200)
            self.end_headers()

        do_HEAD = do_GET

        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    control, errors = JobControl(), []
    with TemporaryDirectory(prefix="subflow-frozen-download-") as scratch:
        target = Path(scratch) / "source.mp4"
        target.write_bytes(b"previous video")
        def run():
            try:
                download(f"http://127.0.0.1:{server.server_port}/blocked.mp4", Path(scratch), control=control)
            except Exception as exc:
                errors.append(exc)
        with patch("bilingual_sub.adapters.download_worker.worker_command",
                   lambda job: [str(client), "--download-worker", str(job)]):
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                assert requested.wait(30), "frozen downloader did not reach local HTTP server"
                started = time.monotonic()
                control.stop()
                worker.join(timeout=10)
                assert time.monotonic() - started < 10 and not worker.is_alive()
                assert len(errors) == 1 and isinstance(errors[0], JobStopped), errors
                assert target.read_bytes() == b"previous video"
                assert not list(Path(scratch).glob(".subflow-download-*"))
            finally:
                control.stop()
                release.set()
                worker.join(timeout=10)
                server.shutdown()
                server.server_close()
                serving.join(timeout=3)

parser = argparse.ArgumentParser()
parser.add_argument("client", type=Path)
args = parser.parse_args()
report = Path("client-smoke.json").resolve()
subprocess.run([str(args.client.resolve()), "--self-test", str(report)], check=True, timeout=120)
data = json.loads(report.read_text(encoding="utf-8"))
assert data["ok"]
for worker_script in data["checks"]["asr_worker_scripts"]:
    # Run the actual packaged scripts under an external interpreter, where
    # sibling helpers must exist as files, not only inside PyInstaller's PYZ.
    result = subprocess.run([sys.executable, worker_script, "--help"], capture_output=True,
                            text=True, timeout=30, check=True)
    assert "--out" in result.stdout
data["checks"]["asr_worker_imports"] = "both packaged workers started with an external Python"
check_frozen_download_cancel(args.client.resolve())
data["checks"]["frozen_download_cancel"] = "blocked HTTP cancelled; previous video preserved"
report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(report.read_text(encoding="utf-8"))
