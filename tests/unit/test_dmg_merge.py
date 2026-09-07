"""Exercise the downloadable merger with actual files and checksums."""
import hashlib
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/merge-macos-dmg.sh"
NAME = "SubFlow-1.3.65-Apple-M-arm64.dmg"


def prepare(root):
    payloads = [b"first DMG block", b"second DMG block"]
    lines = []
    for index, payload in enumerate(payloads, 1):
        name = f"{NAME}.{index:03d}"
        (root / name).write_bytes(payload)
        lines.append(f"{hashlib.sha256(payload).hexdigest()}  {name}\n")
    complete = b"".join(payloads)
    lines.append(f"{hashlib.sha256(complete).hexdigest()}  {NAME}\n")
    (root / "SHA256SUMS").write_text("".join(lines))
    return complete


def run(root):
    return subprocess.run(["bash", str(SCRIPT), "arm64", str(root)],
                          capture_output=True, text=True, timeout=20)


def test_merge_and_repeat_preserve_verified_dmg(tmp_path):
    expected = prepare(tmp_path)
    assert run(tmp_path).returncode == 0
    assert (tmp_path / NAME).read_bytes() == expected
    assert run(tmp_path).returncode == 0


@pytest.mark.parametrize("damage", ["missing", "corrupt", "final_hash", "existing"])
def test_reject_damage_without_overwriting_dmg(tmp_path, damage):
    prepare(tmp_path)
    part = tmp_path / f"{NAME}.002"
    if damage == "missing":
        part.unlink()
    elif damage == "corrupt":
        part.write_bytes(b"corrupted download")
    elif damage == "final_hash":
        sums = tmp_path / "SHA256SUMS"
        lines = sums.read_text().splitlines()
        lines[-1] = f"{'0' * 64}  {NAME}"
        sums.write_text("\n".join(lines) + "\n")
    else:
        (tmp_path / NAME).write_bytes(b"existing user file")
    assert run(tmp_path).returncode != 0
    if damage == "existing":
        assert (tmp_path / NAME).read_bytes() == b"existing user file"
    else:
        assert not (tmp_path / NAME).exists()
    assert not list(tmp_path.glob(f".{NAME}.*"))
