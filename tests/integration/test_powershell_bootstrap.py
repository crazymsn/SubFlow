import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bilingual_sub.adapters.procwin import hidden_run_kwargs

SHELLS = [path for name in ("powershell", "pwsh") if (path := shutil.which(name))]
SCRIPTS = Path(__file__).parents[2] / "scripts"


@pytest.mark.parametrize("shell", SHELLS or [None])
@pytest.mark.parametrize("script,args,expected", [
    ("install-gptsovits-runtime.ps1", ["-Device", "cpu", "-SkipWeights"],
     ["gptsovits", "--backend", "cpu", "--skip-models"]),
    ("bootstrap-whisperx.ps1", [], ["whisperx"]),
    ("setup-gptsovits.ps1", [], ["gptsovits", "--skip-models"]),
    ("download-gptsovits-weights.ps1", [], ["gptsovits"]),
])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_legacy_entry_uses_managed_installer_and_propagates_failure(
        tmp_path, shell, script, args, expected, exit_code):
    if shell is None:
        pytest.skip("PowerShell is unavailable on this host")
    scripts = tmp_path / "中文 scripts with spaces"
    scripts.mkdir()
    for name in (script, "invoke-runtime-preparation.ps1"):
        shutil.copy2(SCRIPTS / name, scripts / name)
    # Replace only the installer boundary: run the actual PowerShell wrappers and
    # argument transport without downloading packages or changing real runtimes.
    (scripts / "prepare-runtime.py").write_text("""import json, os, sys
from pathlib import Path
Path(os.environ['SUBFLOW_TEST_REPORT']).write_text(json.dumps({
    'args': sys.argv[1:], 'cwd': os.getcwd(),
    'backend': os.environ.get('SUBFLOW_TORCH_BACKEND')
}), encoding='utf-8')
sys.exit(int(os.environ['SUBFLOW_TEST_EXIT']))
""", encoding="utf-8")
    report = tmp_path / "report.json"
    env = os.environ.copy()
    env.update(SUBFLOW_TEST_REPORT=str(report), SUBFLOW_TEST_EXIT=str(exit_code),
               SUBFLOW_TORCH_BACKEND="cpu")
    result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-File", str(scripts / script), "-Python", sys.executable, *args],
                            cwd=tmp_path, env=env, capture_output=True, timeout=30,
                            **hidden_run_kwargs())
    assert (result.returncode == 0) == (exit_code == 0), result.stdout + result.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["args"] == expected
    assert Path(data["cwd"]) == tmp_path
    assert data["backend"] == "cpu"
    if exit_code:
        assert b"preparation failed" in result.stdout + result.stderr
