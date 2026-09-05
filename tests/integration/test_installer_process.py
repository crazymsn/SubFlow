import sys
import time

import psutil
import pytest

from bilingual_sub.adapters.runtime_bootstrap import _run


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
