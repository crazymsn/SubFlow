#!/usr/bin/env python3
"""One-time import from legacy Temp workspace (sub-1)."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Import legacy sub-1 artifacts into work dir")
    p.add_argument("legacy_dir", type=Path, help="e.g. C:/Users/.../AppData/Local/Temp/sub-1")
    p.add_argument("work_dir", type=Path, help="Target bilingual-sub work directory")
    args = p.parse_args()
    src: Path = args.legacy_dir
    dst: Path = args.work_dir
    dst.mkdir(parents=True, exist_ok=True)
    mapping = {
        "transcript.json": "transcript.json",
        "bilingual.srt": "subs.srt",
        "bilingual.ass": "subs.ass",
    }
    for a, b in mapping.items():
        sp = src / a
        if sp.is_file():
            shutil.copy2(sp, dst / b)
            print(f"copied {a} -> {b}")
    # rebuild.py cues if present
    for name in ("cues.zh.json", "cues.bilingual.json"):
        sp = src / name
        if sp.is_file():
            shutil.copy2(sp, dst / name)
    state = {"stage": "migrate", "source": str(src)}
    (dst / "job_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"Done -> {dst}")


if __name__ == "__main__":
    main()
