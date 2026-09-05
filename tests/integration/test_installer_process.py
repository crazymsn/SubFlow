import sys
import time
from contextlib import contextmanager

import psutil
import pytest

from bilingual_sub.adapters import installer
from bilingual_sub.adapters.owned_process import owned_process
from bilingual_sub.adapters.runtime_bootstrap import _run
from bilingual_sub.core.control import JobControl, JobStopped


@pytest.mark.parametrize("mode", ["success", "malformed", "crash", "timeout", "cancel"])
def test_installer_version_probe_owns_and_cleans_descendants(tmp_path, monkeypatch, mode):
    pid_file = tmp_path / "probe-child.pid"
    script = tmp_path / "probe.py"
    endings = {
        "success": "print('uv 0.11.8 (test build)', flush=True)",
        "malformed": "print('unexpected output', flush=True)",
        "crash": "sys.exit(7)",
        "timeout": "time.sleep(60)",
        "cancel": "time.sleep(60)",
    }
    script.write_text(f"""import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
pending = Path({str(pid_file.with_suffix('.pending'))!r})
pending.write_text(str(child.pid))
pending.replace({str(pid_file)!r})
{endings[mode]}
""", encoding="utf-8")
    control = JobControl()
    binary = tmp_path / "uv"

    @contextmanager
    def launch_probe(args, **kwargs):
        assert args == [str(binary), "--version"]
        with owned_process([sys.executable, str(script)], **kwargs) as proc:
            if mode == "cancel":
                deadline = time.monotonic() + 10
                while not pid_file.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert pid_file.exists(), "worker did not publish child PID"
                control.stop()
            yield proc

    monkeypatch.setattr(installer, "owned_process", launch_probe)
    if mode == "success":
        assert installer._uv_version(binary, control) == "0.11.8"
    elif mode == "cancel":
        with pytest.raises(JobStopped):
            installer._uv_version(binary, control)
    else:
        expected = {"malformed": "无法识别", "crash": "检查失败", "timeout": "检查超时"}[mode]
        with pytest.raises(RuntimeError, match=expected):
            installer._uv_version(binary, control)
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(0.05)
    pytest.fail("installer version probe left a running child")


@pytest.mark.parametrize("mode", ["crash", "timeout"])
def test_failed_installer_owns_and_cleans_descendants(tmp_path, mode):
    pid_file = tmp_path / "child.pid"
    script = tmp_path / "installer.py"
    ending = "sys.exit(7)" if mode == "crash" else "time.sleep(60)"
    script.write_text(f"""import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path({str(pid_file)!r}).write_text(str(child.pid))
{ending}
""", encoding="utf-8")
    with pytest.raises(RuntimeError, match="自动安装失败|检查超时"):
        _run([sys.executable, str(script)], tmp_path / "install.log", None,
             timeout=3 if mode == "timeout" else 10)
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if psutil.Process(pid).status() == psutil.STATUS_ZOMBIE:
                return
        except psutil.NoSuchProcess:
            return
        time.sleep(0.05)
    pytest.fail("installer left a running child")
