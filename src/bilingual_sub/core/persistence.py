"""Stage JSON records and preserve previous records on reported I/O failures."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from bilingual_sub.core.file_io import Checkpoint, write_text_files


def write_json_files(files: list[tuple[Path, object]], *, checkpoint: Checkpoint = None) -> None:
    """Roll back reported I/O errors; this is not atomic across a process crash."""
    encoded = [(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), "utf-8")
               for path, data in files]
    write_text_files(encoded, checkpoint=checkpoint)


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
