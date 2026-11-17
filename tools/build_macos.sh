#!/bin/bash
# Build "OVA Exporter GUI.app" and a drag-to-Applications disk image for Intel Macs.
# Usage (on macOS, from any folder):  PYTHON=python3 tools/build_macos.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
PY="${PYTHON:-python3}"
NAME="OVA Exporter GUI"
VERSION="$("$PY" -c 'import sys; sys.path.insert(0, "src"); from metadata import VERSION; print(VERSION)')"
APP="dist/$NAME.app"
DMG="dist/OVA-Exporter-GUI-$VERSION-macOS-Intel.dmg"

[ "$(uname)" = Darwin ] || { echo "Run this on macOS." >&2; exit 1; }
rm -rf "$APP" "dist/$NAME" build/mac "$DMG" "$DMG.sha256"
mkdir -p build/mac/icon.iconset

# App icon from the project's own artwork.
"$PY" tools/make_icons.py --mac-png build/mac/icon-1024.png
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" build/mac/icon-1024.png --out "build/mac/icon.iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" build/mac/icon-1024.png --out "build/mac/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/mac/icon.iconset -o build/mac/app.icns

"$PY" -m PyInstaller --noconfirm --windowed --onedir --name "$NAME" \
    --osx-bundle-identifier io.github.abdomitov.ova-exporter-gui \
    --target-architecture x86_64 \
    --paths "$ROOT/src" --icon "$ROOT/build/mac/app.icns" \
    --add-data "$ROOT/assets:assets" --hidden-import tools.preview_ui \
    --specpath build/mac --workpath build/mac/work launch.pyw

PLIST="$APP/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace NSHighResolutionCapable -bool true "$PLIST"
plutil -replace LSMinimumSystemVersion -string "10.13" "$PLIST"
plutil -replace NSHumanReadableCopyright -string "MIT License. Not affiliated with Broadcom or VMware." "$PLIST"

"$PY" tools/runtime_licenses.py "$APP/Contents/Resources/licenses"
cp LICENSE THIRD_PARTY_NOTICES.md "$APP/Contents/Resources/"

# Never ship VMware binaries.
if find "$APP" -iname 'ovftool*' -o -iname 'libvmacore*' -o -iname 'libvmomi*' | grep -q .; then
    echo "Proprietary VMware runtime found in the app bundle." >&2; exit 1
fi

# Ad-hoc signature after editing Info.plist (not a Developer ID; Gatekeeper still asks once).
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

STAGE="build/mac/dmg"
rm -rf "$STAGE"; mkdir -p "$STAGE"
ditto "$APP" "$STAGE/$NAME.app"
ln -s /Applications "$STAGE/Applications"
cp packaging/macos-read-me.txt "$STAGE/Read me first.txt"
hdiutil create -volname "$NAME $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
( cd dist && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256" )
echo "Built $DMG"
