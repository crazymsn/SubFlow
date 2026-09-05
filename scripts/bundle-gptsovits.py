"""Build a Windows runtime that works without the developer's Python installation."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def bundle(source: Path, dest: Path, source_only: bool = False) -> None:
    from bilingual_sub.adapters.tts.gptsovits_runtime import (
        copy_runtime_tree,
        launch_python,
        missing_pretrained,
        runtime_config,
    )

    source, dest = source.resolve(), dest.resolve()
    if source == dest or source.is_relative_to(dest) or dest.is_relative_to(source):
        raise ValueError("Source and destination must be separate trees")
    if not (source / "api_v2.py").is_file():
        raise FileNotFoundError(source / "api_v2.py")
    copy_runtime_tree(source, dest)
    if source_only:
        return
    if os.name != "nt":
        raise RuntimeError("Portable Python bundling currently supports Windows; use --source-only elsewhere")
    missing = missing_pretrained(source)
    if missing:
        raise RuntimeError("Missing models: " + "; ".join(missing))
    config = runtime_config(source)
    python = launch_python(source)
    result = subprocess.run(
        [*python, "-c", "import json,sys,sysconfig;print(json.dumps([sys.base_prefix,sysconfig.get_path('purelib')]))"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    base, packages = map(Path, json.loads(result.stdout.strip()))
    runtime = dest / "runtime"
    # The venv's redirector is not portable. Copy the real CPython base + site-packages.
    shutil.copytree(base, runtime, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "site-packages"))
    shutil.copytree(packages, runtime / "Lib" / "site-packages", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for key in ("t2s_weights_path", "vits_weights_path", "bert_base_path", "cnhuhbert_base_path"):
        src = Path(config[key])
        if not src.is_relative_to(source):
            raise RuntimeError(f"Bundled model must be inside source: {src}")
        target = dest / src.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)
    for relative in ("GPT_SoVITS/text/G2PWModel", "GPT_SoVITS/pretrained_models/fast_langdetect", "nltk_data"):
        src = source / relative
        if src.is_dir():
            shutil.copytree(src, dest / relative, dirs_exist_ok=True)
    if config["version"] != "v2":
        raise RuntimeError("Portable release currently requires the validated v2 pair (unset SUBFLOW_GPTSOVITS_CONFIG)")
    check = subprocess.run(
        [str(runtime / "python.exe"), "-c", "import sys;sys.path.insert(0,'GPT_SoVITS');from GPT_SoVITS.TTS_infer_pack.TTS import TTS;print('BUNDLED_IMPORT_OK')"],
        cwd=dest, env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": "", "PYTHONHOME": "",
                       "NLTK_DATA": str(dest / "nltk_data")},
        check=True, capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    print(check.stdout, flush=True)
    print(f"Bundled GPT-SoVITS: {dest}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    bundle(args.source, args.dest, args.source_only)
