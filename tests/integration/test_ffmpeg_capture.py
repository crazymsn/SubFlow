import sys
import time
import tracemalloc
from pathlib import Path

import psutil
import pytest

from bilingual_sub.adapters.ffmpeg import run_cmd
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.mark.parametrize("controlled", [False, True])
def test_stderr_is_bounded_while_stdout_is_preserved(controlled):
    code = "import sys; sys.stdout.write('result' * 50000); sys.stderr.write('warning\\n' * 200000 + 'last message')"
    result = run_cmd([sys.executable, "-c", code], control=JobControl() if controlled else None)
    assert result.stdout == "result" * 50000
    assert len(result.stderr) <= 65536
    assert result.stderr.endswith("last message")


def stopped(pid):
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


@pytest.mark.parametrize("exit_code", [0, 7])
def test_finished_worker_does_not_leave_descendants(tmp_path, exit_code):
    pid_file = tmp_path / "child.pid"
    code = f"""import subprocess, sys
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
Path({str(pid_file)!r}).write_text(str(child.pid), encoding='ascii')
sys.exit({exit_code})
"""
    try:
        assert run_cmd([sys.executable, "-c", code], check=False).returncode == exit_code
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 3
        while not stopped(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert stopped(pid), "FFmpeg command left its child running"
    finally:
        if pid_file.exists():
            pid = int(pid_file.read_text())
            if not stopped(pid):
                psutil.Process(pid).kill()


@pytest.mark.parametrize("mode", ["cancel", "callback_error"])
def test_stderr_observer_failure_or_cancellation_cleans_process_tree(tmp_path, mode):
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "worker.py"
    script.write_text(f"""import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path({str(pid_file)!r}).write_text(str(child.pid), encoding='ascii')
print('ready', file=sys.stderr, flush=True)
time.sleep(60)
""", encoding="utf-8")
    control = JobControl()
    def observe(line):
        if line == "ready":
            if mode == "cancel":
                control.stop()
            else:
                raise ValueError("observer failed")
    with pytest.raises(JobStopped if mode == "cancel" else ValueError):
        run_cmd([sys.executable, str(script)], control=control, stderr_callback=observe)
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 3
    while not stopped(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert stopped(pid)


def test_stderr_observer_handles_split_utf8_and_unterminated_line():
    lines = []
    code = "import sys, time; data='汉字\\r\\nlast'.encode('utf-8'); [(sys.stderr.buffer.write(bytes([b])), sys.stderr.flush(), time.sleep(.002)) for b in data]"
    run_cmd([sys.executable, "-c", code], stderr_callback=lines.append)
    assert [line for line in lines if line] == ["汉字", "last"]


def test_stderr_observer_rejects_unbounded_line():
    code = "import sys; sys.stderr.write('x' * 1000000)"
    with pytest.raises(RuntimeError, match="line.*long|日志行"):
        run_cmd([sys.executable, "-c", code], stderr_callback=lambda line: None)


def test_silence_detection_keeps_early_events_beyond_diagnostic_tail(tmp_path, monkeypatch):
    from bilingual_sub.core import audio

    script = tmp_path / "silences.py"
    script.write_text("""import sys
for i in range(5000):
    print(f'silence_start: {i * 2}', file=sys.stderr)
    print(f'silence_end: {i * 2 + 1} | silence_duration: 1', file=sys.stderr)
""", encoding="utf-8")
    def fake_ffmpeg(args, **kwargs):
        return run_cmd([sys.executable, str(script)], **kwargs)
    monkeypatch.setattr(audio, "run_cmd", fake_ffmpeg)
    monkeypatch.setattr(audio, "find_ffmpeg", lambda: "unused")
    spans = audio.detect_silences(Path("unused.wav"))
    assert spans == [(float(i * 2), float(i * 2 + 1)) for i in range(5000)]


def test_stderr_capture_memory_does_not_scale_with_log_size():
    code = "import sys; block=b'x'*65536; [sys.stderr.buffer.write(block) for _ in range(256)]"
    tracemalloc.start()
    try:
        result = run_cmd([sys.executable, "-c", code])
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(result.stderr) == 65536
    assert peak < 6 * 1024 * 1024, f"16 MiB log caused {peak} bytes of Python allocation"
