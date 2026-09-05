#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${SUBFLOW_GPTSOVITS_HOME:-$ROOT/third_party/GPT-SoVITS}"
REPO="https://github.com/RVC-Boss/GPT-SoVITS.git"
echo "GPT-SoVITS -> $DEST"
if [[ ! -f "$DEST/api_v2.py" ]]; then
  command -v git >/dev/null || { echo "git not found"; exit 1; }
  mkdir -p "$(dirname "$DEST")"
  TMP="$(dirname "$DEST")/GPT-SoVITS-src"
  rm -rf "$TMP"
  git clone --depth 1 "$REPO" "$TMP" || git clone --depth 1 "https://ghproxy.net/https://github.com/RVC-Boss/GPT-SoVITS.git" "$TMP"
  mkdir -p "$DEST"
  cp -R "$TMP"/. "$DEST"/
  rm -rf "$TMP"
fi
echo "Source ready. Install official deps + weights, then start SubFlow to auto-boot api_v2.py."
