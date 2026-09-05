"""Commit one JSON record without truncating the previous valid file."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def write_json(path: Path, data) -> None:
    encoded = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".subflow-json-", suffix=".tmp", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)
