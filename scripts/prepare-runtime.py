"""Prepare automatic runtimes from source or in a container."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from bilingual_sub.adapters.runtime_bootstrap import ensure_python_env, ensure_sovits_runtime

    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["asr", "gptsovits", "whisperx"])
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()
    if args.kind == "gptsovits":
        print(ensure_sovits_runtime(models=not args.skip_models, progress=lambda s: print(s, flush=True)))
    else:
        print(ensure_python_env(args.kind, progress=lambda s: print(s, flush=True)))


if __name__ == "__main__":
    main()
