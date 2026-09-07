#!/bin/bash
# Reassemble the binary DMG parts published with a SubFlow Mac release.
set -euo pipefail
export LC_ALL=C

ARCH="${1:-$(uname -m)}"
DIR="${2:-$(cd "$(dirname "$0")" && pwd)}"
VERSION="${3:-1.3.65}"
case "$ARCH" in
  arm64) FLAVOR="Apple-M-arm64" ;;
  x86_64) FLAVOR="Intel-x86_64" ;;
  *) echo 'Usage: bash Merge-SubFlow-DMG.command [arm64|x86_64] [download-directory] [version]' >&2; exit 1 ;;
esac
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 1
cd "$DIR"
OUTPUT="SubFlow-${VERSION}-${FLAVOR}.dmg"
MANIFEST="SHA256SUMS"
[[ -f "$MANIFEST" ]] || { echo 'Missing SHA256SUMS.' >&2; exit 1; }
expected() { awk -v name="$1" '$2 == name {print $1}' "$MANIFEST"; }
verify() {
  local checksum
  checksum="$(expected "$1")"
  [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] &&
    [[ -f "$1" ]] && [[ "$(shasum -a 256 "$1" | awk '{print $1}')" == "$checksum" ]]
}
if [[ -e "$OUTPUT" ]]; then
  verify "$OUTPUT" || { echo "Existing DMG differs; preserving it: $OUTPUT" >&2; exit 1; }
  echo "DMG already verified: $PWD/$OUTPUT"
  exit 0
fi
PARTS=()
while IFS= read -r part; do
  [[ "$part" == "$OUTPUT".[0-9][0-9][0-9] ]] || { echo 'Invalid part name.' >&2; exit 1; }
  NEXT="$(printf '%s.%03d' "$OUTPUT" "$(( ${#PARTS[@]} + 1 ))")"
  [[ "$part" == "$NEXT" ]] || { echo "Missing or duplicated part: $NEXT" >&2; exit 1; }
  verify "$part" || { echo "Missing or damaged part: $part" >&2; exit 1; }
  PARTS+=("$part")
  echo "Verified: $part"
done < <(awk -v prefix="$OUTPUT." 'index($2, prefix) == 1 {print $2}' "$MANIFEST" | sort)
[[ ${#PARTS[@]} -gt 0 ]] || { echo 'No parts listed in SHA256SUMS.' >&2; exit 1; }
FINAL_HASH="$(expected "$OUTPUT")"
[[ "$FINAL_HASH" =~ ^[0-9a-f]{64}$ ]] || { echo 'Missing final DMG checksum.' >&2; exit 1; }
TEMP="$(mktemp "./.${OUTPUT}.XXXXXX")"
trap 'rm -f "$TEMP"' EXIT
echo 'Merging DMG; this may take several minutes...'
cat "${PARTS[@]}" > "$TEMP"
[[ "$(shasum -a 256 "$TEMP" | awk '{print $1}')" == "$FINAL_HASH" ]] || {
  echo 'Final checksum failed; no DMG was installed.' >&2; exit 1;
}
# A hard link creates the final name atomically and refuses to overwrite a file.
ln "$TEMP" "$OUTPUT"
echo "DMG verified: $PWD/$OUTPUT"
echo 'Open the DMG and drag SubFlow.app into Applications.'
