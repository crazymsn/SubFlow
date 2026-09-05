"""Exercise the actual frozen launcher and its bundled external executables."""
import argparse
import json
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("client", type=Path)
args = parser.parse_args()
report = Path("client-smoke.json").resolve()
subprocess.run([str(args.client.resolve()), "--self-test", str(report)], check=True, timeout=120)
print(report.read_text(encoding="utf-8"))
assert json.loads(report.read_text(encoding="utf-8"))["ok"]
