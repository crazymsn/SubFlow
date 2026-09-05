"""Use the same config selection, health check and lifecycle as the client."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    from bilingual_sub.adapters.tts.gptsovits import default_endpoint
    from bilingual_sub.adapters.tts.gptsovits_runtime import (
        diagnose_runtime,
        ensure_home,
        ensure_running,
        missing_pretrained,
        probe_endpoint,
        stop_servers,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "weights", "serve"))
    parser.add_argument("--endpoint", default=default_endpoint())
    args = parser.parse_args()
    if args.command == "weights":
        missing = missing_pretrained(ensure_home())
        if missing:
            raise SystemExit("Missing: " + "; ".join(missing))
        print("Weights ready")
    elif args.command == "check":
        error = diagnose_runtime()
        if error:
            raise SystemExit(error)
        print("GPT-SoVITS runtime ready")
    else:
        try:
            print(ensure_running(args.endpoint, wait_sec=300), args.endpoint, flush=True)
            while True:
                time.sleep(2)
                if not probe_endpoint(args.endpoint):
                    raise SystemExit("GPT-SoVITS stopped; see gptsovits.log")
        except KeyboardInterrupt:
            pass
        finally:
            stop_servers()


if __name__ == "__main__":
    main()
