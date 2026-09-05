#!/usr/bin/env bash
# 构建 SubFlow macOS 客户端（与 Windows 同一套 GUI / spec）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"

python3 -m pip install -e ".[gui,packaging]"
python3 -m PyInstaller --noconfirm --clean "$ROOT/packaging/subflow.spec"

APP="$ROOT/dist/SubFlow.app"
BUNDLE="$ROOT/dist/SubFlow"
python3 scripts/bundle-gptsovits.py third_party/GPT-SoVITS "$BUNDLE/GPT-SoVITS" --source-only
if [[ ! -d "$BUNDLE" ]]; then
  echo "PyInstaller onedir missing: $BUNDLE" >&2
  exit 1
fi
if [[ ! -x "$BUNDLE/SubFlow" && ! -f "$BUNDLE/SubFlow" ]]; then
  echo "PyInstaller binary missing: $BUNDLE/SubFlow" >&2
  exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R "$BUNDLE/"* "$APP/Contents/MacOS/"
chmod +x "$APP/Contents/MacOS/SubFlow" || true

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
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/SubFlow.icns"
fi

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>SubFlow</string>
  <key>CFBundleDisplayName</key><string>SubFlow</string>
  <key>CFBundleIdentifier</key><string>tech.deepcloud.subflow</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>SubFlow</string>
  <key>CFBundleIconFile</key><string>SubFlow</string>
  <key>LSMinimumSystemVersion</key><string>$(sw_vers -productVersion | cut -d. -f1).0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Copyright © 深度云创科技</string>
</dict>
</plist>
EOF

# FFmpeg/ffprobe and their dylibs are collected and relocated by subflow.spec.

# --deep fails on .dist-info folders inside _internal. Sign the launcher only.
if command -v codesign >/dev/null; then
  codesign --force --sign - "$APP/Contents/MacOS/SubFlow" || true
fi

if [[ ! -f "$APP/Contents/MacOS/SubFlow" ]]; then
  echo "macOS bundle missing executable" >&2
  exit 1
fi

echo "macOS client: $APP ($VERSION)"
echo "First use automatically installs Python, CPU inference dependencies and models."
