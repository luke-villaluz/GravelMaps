#!/usr/bin/env bash
# Builds dist/GravelMaps.app, and with --dmg also dist/GravelMaps-<arch>.dmg.
# Run from a venv that has requirements.txt and requirements-build.txt installed.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

rm -rf build/GravelMaps dist/GravelMaps dist/GravelMaps.app
"$PY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/GravelMaps.spec
rm -rf dist/GravelMaps  # the bare folder; the .app holds the same files

# Ad-hoc signature (no Apple Developer account): Apple Silicon needs every app signed, and
# Gatekeeper shows its one-time "Open Anyway" step for it in System Settings.
codesign --force --deep --sign - dist/GravelMaps.app
codesign --verify --deep --strict dist/GravelMaps.app
echo "Built dist/GravelMaps.app"

if [ "${1:-}" = "--dmg" ]; then
  ARCH="$(uname -m)"
  DMG="dist/GravelMaps-${ARCH}.dmg"
  STAGE="$(mktemp -d)"
  cp -R dist/GravelMaps.app "$STAGE/"
  cp "packaging/dmg/First time opening.txt" "$STAGE/"
  rm -f "$DMG"
  # create-dmg (brew install create-dmg) lays the window out: the app, an arrow's worth of space,
  # and the Applications folder to drag it onto. Without it, a plain DMG with the same contents.
  if command -v create-dmg >/dev/null && create-dmg --volname "GravelMaps" --volicon packaging/icon.icns \
      --window-size 600 400 --icon-size 128 --text-size 13 \
      --icon "GravelMaps.app" 150 170 --app-drop-link 450 170 --icon "First time opening.txt" 300 320 \
      --hide-extension "GravelMaps.app" --no-internet-enable "$DMG" "$STAGE"; then
    :
  else
    rm -f "$DMG"
    ln -s /Applications "$STAGE/Applications"
    hdiutil create -volname "GravelMaps" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
  fi
  rm -rf "$STAGE"
  echo "Built $DMG"
fi
