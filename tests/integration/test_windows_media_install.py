import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install-windows-ffmpeg.ps1"


def run_installer(tmp_path, installer, *, tools_ready=False, probe_exit=0):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell, "Windows verification requires PowerShell"
    bin_dir = tmp_path / "tools"
    bin_dir.mkdir()
    (bin_dir / "choco.cmd").write_text(installer, encoding="ascii")
    if tools_ready:
        (bin_dir / "ffmpeg.cmd").write_text("@exit /b 0\n", encoding="ascii")
        (bin_dir / "ffprobe.cmd").write_text(f"@exit /b {probe_exit}\n", encoding="ascii")
    env = dict(os.environ, PATH=str(bin_dir))
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                             "-Attempts", "2", "-RetryDelaySeconds", "0"],
                            env=env, capture_output=True, timeout=30)
    attempts = bin_dir / "attempts"
    count = len(attempts.read_text().splitlines()) if attempts.exists() else 0
    return result, count


NO_INSTALL = '@echo attempt>> "%~dp0attempts"\n@exit /b 0\n'


def test_ready_executables_skip_installation(tmp_path):
    result, count = run_installer(tmp_path, NO_INSTALL, tools_ready=True)
    assert result.returncode == 0 and count == 0


def test_zero_exit_without_media_tools_fails_after_bounded_retries(tmp_path):
    result, count = run_installer(tmp_path, NO_INSTALL)
    assert result.returncode != 0 and count == 2
    assert b"unavailable after 2" in result.stderr


def test_existing_but_broken_probe_is_not_accepted(tmp_path):
    result, count = run_installer(tmp_path, NO_INSTALL, tools_ready=True, probe_exit=1)
    assert result.returncode != 0 and count == 2


def test_transient_empty_install_retries_and_verifies_both_tools(tmp_path):
    installer = ('@echo off\n'
                 'echo attempt>> "%~dp0attempts"\n'
                 'if exist "%~dp0first" (\n'
                 '  echo @exit /b 0 > "%~dp0ffmpeg.cmd"\n'
                 '  echo @exit /b 0 > "%~dp0ffprobe.cmd"\n'
                 ')\n'
                 'echo first> "%~dp0first"\n'
                 'exit /b 0\n')
    result, count = run_installer(tmp_path, installer)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert count == 2


def test_packaging_rejects_missing_probe_before_running_pyinstaller(tmp_path):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell
    (tmp_path / "ffmpeg.cmd").write_text("@exit /b 0\n", encoding="ascii")
    (tmp_path / "python.cmd").write_text('@echo called> "%~dp0packager-called"\n@exit /b 0\n', encoding="ascii")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File",
                             str(SCRIPT.with_name("build-windows.ps1")), "-SkipInstall",
                             "-DistPath", str(tmp_path / "dist")],
                            env=dict(os.environ, PATH=str(tmp_path)), capture_output=True, timeout=30)
    assert result.returncode != 0
    assert b"required to build" in result.stderr
    assert not (tmp_path / "packager-called").exists()
    assert not (tmp_path / "dist").exists()
