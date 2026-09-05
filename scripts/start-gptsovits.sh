#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${SUBFLOW_GPTSOVITS_HOME:-$ROOT/third_party/GPT-SoVITS}"
API="$HOME_DIR/api_v2.py"
if [[ ! -f "$API" ]]; then
  echo "api_v2.py not found in $HOME_DIR. Run scripts/setup-gptsovits.sh first."
  exit 1
fi
PY="${SUBFLOW_GPTSOVITS_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$HOME_DIR/venv/bin/python3" ]]; then
    PY="$HOME_DIR/venv/bin/python3"
  else
    PY="python3"
  fi
fi
CONFIG="$HOME_DIR/GPT_SoVITS/configs/tts_infer.yaml"
cd "$HOME_DIR"
echo "Starting GPT-SoVITS API at http://127.0.0.1:9880"
if [[ -f "$CONFIG" ]]; then
  exec "$PY" api_v2.py -a 127.0.0.1 -p 9880 -c "$CONFIG"
fi
exec "$PY" api_v2.py -a 127.0.0.1 -p 9880
