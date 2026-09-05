#!/usr/bin/env bash
# 构建 SubFlow macOS 客户端（与 Windows 同一套 GUI / spec）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if command -v brew >/dev/null && brew --prefix ffmpeg-full >/dev/null 2>&1; then
  export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
fi

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"

ICON_SRC="$ROOT/assets/brand/subflow.png"
if [[ -f "$ICON_SRC" ]] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
  ICONSET="$ROOT/build/SubFlow.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    dbl=$((size * 2))
    sips -z "$dbl" "$dbl" "$ICON_SRC" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$ROOT/build/SubFlow.icns"
fi


python3 -m pip install -e ".[gui,packaging]"
python3 -m PyInstaller --noconfirm --clean "$ROOT/packaging/subflow.spec"
APP="$ROOT/dist/SubFlow.app"
python3 scripts/bundle-gptsovits.py third_party/GPT-SoVITS "$APP/Contents/Resources/GPT-SoVITS" --source-only
# PyInstaller signs nested binaries; re-seal the app after adding vendored source.
codesign --force --sign - "$APP"
codesign --verify "$APP"
test -x "$APP/Contents/MacOS/SubFlow"
echo "macOS client: $APP ($VERSION)"
echo "First use automatically installs Python, CPU inference dependencies and models."
