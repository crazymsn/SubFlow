#!/usr/bin/env bash
# 构建 SubFlow macOS 客户端（与 Windows 同一套 GUI / spec）
set -euo pipefail
# Editable imports must also work from non-ASCII checkout paths under C locale.
export PYTHONUTF8=1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Build the macOS client on a native Mac." >&2
  exit 1
fi
ARCH="${SUBFLOW_TARGET_ARCH:-$(uname -m)}"
if [[ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" == "1" && "${SUBFLOW_TARGET_ARCH:-}" != "x86_64" ]]; then
  echo "Use native arm64 for Apple M, or explicitly set SUBFLOW_TARGET_ARCH=x86_64 for an Intel CPU build under Rosetta." >&2
  exit 1
fi
BUILD_PYTHON="${SUBFLOW_BUILD_PYTHON:-python3}"
"$BUILD_PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Building requires Python 3.11 or newer"'
if [[ "$("$BUILD_PYTHON" -c 'import platform; print(platform.machine())')" != "$ARCH" ]]; then
  echo "Python architecture must match this Mac ($ARCH)." >&2
  exit 1
fi
# Homebrew Python can be externally managed. Keep build dependencies isolated.
BUILD_ENV="${SUBFLOW_BUILD_ENV:-$ROOT/build/macos-build-env}"
"$BUILD_PYTHON" -m venv "$BUILD_ENV"
PYTHON="$BUILD_ENV/bin/python"
if [[ "$ARCH" == "arm64" ]]; then
  export SUBFLOW_TORCH_BACKEND=mps
elif [[ "$ARCH" == "x86_64" ]]; then
  export SUBFLOW_TORCH_BACKEND=cpu
else
  echo "Unsupported Mac architecture: $ARCH" >&2
  exit 1
fi
if [[ -n "${SUBFLOW_FFMPEG_DIR:-}" ]]; then
  export PATH="$SUBFLOW_FFMPEG_DIR:$PATH"
elif command -v brew >/dev/null && brew --prefix ffmpeg-full >/dev/null 2>&1; then
  export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"
fi

VERSION="$("$PYTHON" -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"

"$PYTHON" -m pip install -e ".[gui,packaging]"
"$PYTHON" scripts/make-macos-icons.py
DIST_DIR="${SUBFLOW_DIST_DIR:-$ROOT/dist}"
"$PYTHON" -m PyInstaller --noconfirm --clean --workpath "$ROOT/build/pyinstaller-$ARCH" --distpath "$DIST_DIR" "$ROOT/packaging/subflow.spec"
APP="$DIST_DIR/SubFlow.app"
if [[ "${SUBFLOW_SLIM_BUILD:-0}" == "1" ]]; then
  "$PYTHON" scripts/bundle-gptsovits.py third_party/GPT-SoVITS "$APP/Contents/Resources/GPT-SoVITS" --source-only
else
  bundle_args=()
  if [[ "${SUBFLOW_BUNDLE_HARDLINK:-0}" == "1" ]]; then
    bundle_args+=(--hardlink)
  fi
  if [[ -n "${SUBFLOW_REUSE_OFFLINE:-}" ]]; then
    bundle_args+=(--copy-bundle "$SUBFLOW_REUSE_OFFLINE")
  fi
  "$PYTHON" scripts/bundle-offline.py "$APP/Contents/Resources/offline" "${bundle_args[@]}"
  printf '{"schema":1}\n' > "$APP/Contents/Resources/offline-required.json"
  # Newly bundled native interpreters and extensions must be signed before the
  # outer app. Keep binaries in their original package directories for imports.
  "$PYTHON" scripts/sign-offline-macos.py "$APP/Contents/Resources/offline"
fi
# Re-seal the app after adding the complete inference payload.
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP"
test -x "$APP/Contents/MacOS/SubFlow"
echo "macOS client: $APP ($VERSION)"
if [[ "${SUBFLOW_SLIM_BUILD:-0}" == "1" ]]; then
  echo "Slim staging app: attach and validate the complete offline payload before distribution."
else
  echo "Full build includes all three voice engines, native Python and models (Apple Silicon MPS / Intel CPU)."
fi
