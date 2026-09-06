#!/usr/bin/env bash
# 构建 SubFlow macOS 客户端（与 Windows 同一套 GUI / spec）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Build the macOS client on a native Mac." >&2
  exit 1
fi
if [[ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" == "1" ]]; then
  echo "Use a native Terminal and arm64 Python on Apple Silicon; Rosetta builds cannot use MPS." >&2
  exit 1
fi
ARCH="$(uname -m)"
if [[ "$(python3 -c 'import platform; print(platform.machine())')" != "$ARCH" ]]; then
  echo "Python architecture must match this Mac ($ARCH)." >&2
  exit 1
fi
# Homebrew Python can be externally managed. Keep build dependencies isolated.
BUILD_ENV="$ROOT/build/macos-build-env"
python3 -m venv "$BUILD_ENV"
PYTHON="$BUILD_ENV/bin/python"
if [[ "$ARCH" == "arm64" ]]; then
  export SUBFLOW_TORCH_BACKEND=mps
elif [[ "$ARCH" == "x86_64" ]]; then
  export SUBFLOW_TORCH_BACKEND=cpu
else
  echo "Unsupported Mac architecture: $ARCH" >&2
  exit 1
fi
if command -v brew >/dev/null && brew --prefix ffmpeg-full >/dev/null 2>&1; then
  export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
fi

VERSION="$("$PYTHON" -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"

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


"$PYTHON" -m pip install -e ".[gui,packaging]"
"$PYTHON" -m PyInstaller --noconfirm --clean "$ROOT/packaging/subflow.spec"
APP="$ROOT/dist/SubFlow.app"
if [[ "${SUBFLOW_SLIM_BUILD:-0}" == "1" ]]; then
  "$PYTHON" scripts/bundle-gptsovits.py third_party/GPT-SoVITS "$APP/Contents/Resources/GPT-SoVITS" --source-only
else
  bundle_args=()
  if [[ "${SUBFLOW_BUNDLE_HARDLINK:-0}" == "1" ]]; then
    bundle_args+=(--hardlink)
  fi
  "$PYTHON" scripts/bundle-offline.py "$APP/Contents/Resources/offline" "${bundle_args[@]}"
  printf '{"schema":1}\n' > "$APP/Contents/Resources/offline-required.json"
  # Newly bundled native interpreters and extensions must be signed before the
  # outer app. Keep binaries in their original package directories for imports.
  "$PYTHON" scripts/sign-offline-macos.py "$APP/Contents/Resources/offline"
fi
# Re-seal the app after adding the complete inference payload.
codesign --force --sign - "$APP"
codesign --verify "$APP"
test -x "$APP/Contents/MacOS/SubFlow"
echo "macOS client: $APP ($VERSION)"
echo "Full build includes all three voice engines, native Python and models (Apple Silicon MPS / Intel CPU)."
