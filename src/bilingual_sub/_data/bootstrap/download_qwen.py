"""Pinned Qwen3-TTS assets, verified before publishing the ready manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SPEC = json.loads(Path(__file__).with_name("qwen-model.json").read_text(encoding="utf-8"))
MARKER = ".subflow-qwen-ready.json"


def digest(path: Path, expected: str) -> str:
    h = hashlib.sha1() if len(expected) == 40 else hashlib.sha256()
    if len(expected) == 40:
        h.update(f"blob {path.stat().st_size}\0".encode())
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ready(home: Path, spec=None) -> bool:
    spec = spec or SPEC
    try:
        saved = json.loads((home / MARKER).read_text(encoding="utf-8"))
        if saved.get("revision") != spec["revision"]:
            return False
        for name, item in spec["files"].items():
            st = (home / name).stat()
            if st.st_size != item["size"] or saved["files"][name] != st.st_mtime_ns:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def prepare(home: Path, spec=None) -> None:
    from huggingface_hub import hf_hub_download

    spec = spec or SPEC
    home.mkdir(parents=True, exist_ok=True)
    verified = {}
    for name, item in spec["files"].items():
        path = home / name
        print(f"Checking {name}", flush=True)
        for attempt in range(2):
            if path.is_file() and path.stat().st_size == item["size"] and digest(path, item["sha"]) == item["sha"]:
                verified[name] = path.stat().st_mtime_ns
                break
            hf_hub_download(spec["repo"], name, revision=spec["revision"], local_dir=home,
                            force_download=bool(attempt))
        else:
            raise RuntimeError(f"Qwen model checksum mismatch: {name}")
    pending = home / (MARKER + ".pending")
    pending.write_text(json.dumps({"revision": spec["revision"], "files": verified}), encoding="utf-8")
    pending.replace(home / MARKER)
    print("Qwen3-TTS assets verified", flush=True)


if __name__ == "__main__":
    import sys

    spec = json.loads(Path(__file__).with_name('qwen-native-model.json').read_text(encoding='utf-8')) if '--native' in sys.argv else SPEC
    prepare(Path(sys.argv[1]), spec)
