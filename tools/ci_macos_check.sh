#!/bin/bash
# CI only: run the frozen app, then install it from the disk image the way a user would
# (mount, drag to a folder, launch) and record each check. Fake data only; no VMware.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "${GITHUB_ACTIONS:-}" = true ] || { echo "This check runs on a disposable CI runner only." >&2; exit 1; }
PY="${PYTHON:-python}"
NAME="OVA Exporter GUI"
VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "src"); from metadata import VERSION; print(VERSION)')"
DMG="$PWD/dist/OVA-Exporter-GUI-$VERSION-macOS-Intel.dmg"
REPORTS="$PWD/artifacts/ci"
mkdir -p "$REPORTS"

passed() { "$PY" - "$1" <<'PY'
import json, sys
report = json.load(open(sys.argv[1]))
sys.exit(0 if report.get('fake_ui_check') == 'passed' else 1)
PY
}

# 1. The freshly built bundle.
"dist/$NAME.app/Contents/MacOS/$NAME" --self-test-report "$REPORTS/macos-frozen.json"
passed "$REPORTS/macos-frozen.json"

# 2. The disk image a user downloads.
MOUNT="$(mktemp -d)"
DEST="$(mktemp -d)"
hdiutil attach -nobrowse -readonly -mountpoint "$MOUNT" "$DMG" >/dev/null
trap 'hdiutil detach "$MOUNT" >/dev/null 2>&1 || true' EXIT
[ -L "$MOUNT/Applications" ] && [ -f "$MOUNT/Read me first.txt" ] && [ -d "$MOUNT/$NAME.app" ]
ditto "$MOUNT/$NAME.app" "$DEST/$NAME.app"
hdiutil detach "$MOUNT" >/dev/null
trap - EXIT
APP="$DEST/$NAME.app"
codesign --verify --deep --strict "$APP"
lipo -archs "$APP/Contents/MacOS/$NAME" | grep -qw x86_64
[ "$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")" = "$VERSION" ]
"$APP/Contents/MacOS/$NAME" --self-test-report "$REPORTS/macos-installed.json"
passed "$REPORTS/macos-installed.json"

cat > "$REPORTS/macos-dmg-check.json" <<JSON
{"version": "$VERSION", "mounted": "passed", "layout": "passed", "signature": "passed",
 "architecture": "passed", "bundle_version": "passed", "installed_self_test": "passed"}
JSON
echo "PASS: macOS app bundle and disk image install checks"
