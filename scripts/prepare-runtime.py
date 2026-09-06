"""Prepare automatic runtimes from source or in a container."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["asr", "gptsovits", "whisperx", "qwentts"])
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument("--backend", choices=["cpu", "cuda", "mps"],
                        help="Override the installation backend for this invocation")
    args = parser.parse_args(argv)
    if args.skip_models and args.kind != "gptsovits":
        parser.error("--skip-models requires gptsovits")
    from bilingual_sub.adapters.runtime_bootstrap import ensure_python_env, ensure_sovits_runtime

    previous = os.environ.get("SUBFLOW_TORCH_BACKEND")
    try:
        if args.backend:
            os.environ["SUBFLOW_TORCH_BACKEND"] = args.backend
        if args.kind == "gptsovits":
            print(ensure_sovits_runtime(models=not args.skip_models, progress=lambda s: print(s, flush=True)))
        else:
            print(ensure_python_env(args.kind, progress=lambda s: print(s, flush=True)))
    finally:
        if args.backend:
            if previous is None:
                os.environ.pop("SUBFLOW_TORCH_BACKEND", None)
            else:
                os.environ["SUBFLOW_TORCH_BACKEND"] = previous


if __name__ == "__main__":
    main()
