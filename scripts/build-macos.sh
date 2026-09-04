#!/usr/bin/env bash
# 构建 SubFlow macOS 客户端（与 Windows 同一套 GUI / spec）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m pip install -e ".[gui,packaging]"
python3 -m PyInstaller --noconfirm --clean "$ROOT/packaging/subflow.spec"

APP="$ROOT/dist/SubFlow.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R "$ROOT/dist/SubFlow/"* "$APP/Contents/MacOS/"

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
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>SubFlow</string>
  <key>CFBundleIconFile</key><string>SubFlow</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Copyright © 深度云创科技</string>
</dict>
</plist>
EOF

if command -v ffmpeg >/dev/null; then
  cp "$(command -v ffmpeg)" "$APP/Contents/MacOS/ffmpeg"
  if command -v ffprobe >/dev/null; then
    cp "$(command -v ffprobe)" "$APP/Contents/MacOS/ffprobe"
  fi
fi

echo "macOS client: $APP"
echo "ASR 需本机 Whisper，或使用 docker compose。"
