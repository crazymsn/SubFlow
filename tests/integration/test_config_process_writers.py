import os
import subprocess
import sys
import time
from pathlib import Path

import yaml


def test_two_processes_merge_settings_without_lost_updates(tmp_path):
    script = tmp_path / "writer.py"
    script.write_text('''
import sys
import time
from pathlib import Path
from bilingual_sub import config
root, role = Path(sys.argv[1]), sys.argv[2]
config._user_config_path = lambda: root / "config.yaml"
load = config._load_yaml
def paused_load(path, **kwargs):
    data = load(path, **kwargs)
    if role == "first":
        (root / "first-read").touch()
        deadline = time.monotonic() + 15
        while not (root / "release").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("parent did not release writer")
            time.sleep(.02)
    return data
config._load_yaml = paused_load
(root / (role + "-started")).touch()
config.save_user_overrides({"ui": {"theme": "light"}} if role == "first"
                           else {"translate": {"model": "chosen-model"}})
(root / (role + "-done")).touch()
''', encoding="utf-8")
    destination = tmp_path / "config.yaml"
    destination.write_text("tts:\n  gptsovits:\n    prompt_text: 原有参考文字\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / "src"))
    processes = []

    def wait_for(marker, timeout=10):
        deadline = time.monotonic() + timeout
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        return marker.exists()

    try:
        processes.append(subprocess.Popen([sys.executable, str(script), str(tmp_path), "first"],
                                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        assert wait_for(tmp_path / "first-read")
        processes.append(subprocess.Popen([sys.executable, str(script), str(tmp_path), "second"],
                                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        assert wait_for(tmp_path / "second-started")
        # An unlocked second writer finishes against the stale first snapshot.
        # With the file lock it waits until the first commit releases ownership.
        wait_for(tmp_path / "second-done", timeout=1)
        (tmp_path / "release").touch()
        for process in processes:
            out, err = process.communicate(timeout=15)
            assert process.returncode == 0, (out, err)
        data = yaml.safe_load(destination.read_text(encoding="utf-8"))
        assert data == {"ui": {"theme": "light"}, "translate": {"model": "chosen-model"},
                        "tts": {"gptsovits": {"prompt_text": "原有参考文字"}}}
    finally:
        (tmp_path / "release").touch()
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
