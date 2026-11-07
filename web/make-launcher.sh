#!/bin/bash
# macOS only. Creates "Quick Crate (Web).app" in ~/Applications.
#
# Opening the app starts the web version in the background (no Terminal window) and shows it in its
# own compact window (Chrome, Edge or Brave), or in a browser tab otherwise. The launcher itself exits
# immediately, so there is nothing to quit; the server stops by itself ~10 s after you close the window.
# Run this again if you move this folder.
set -e
cd "$(dirname "$0")"
VERSION="$(cat ../VERSION 2>/dev/null || echo 0.0.0)"
DIR="$PWD"
PY="$(command -v python3)" || { echo "python3 not found. Install it with: xcode-select --install"; exit 1; }
NAME="Quick Crate (Web)"
APP="$HOME/Applications/$NAME.app"
mkdir -p "$HOME/Applications"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# The app's executable is a tiny shell script: start server.py detached, then exit.
# (If it's already running, server.py just opens the window and exits.)
cat > "$APP/Contents/MacOS/launch" <<SCRIPT
#!/bin/bash
mkdir -p "\$HOME/Library/Logs"
LOG="\$HOME/Library/Logs/$NAME.log"
cd $(printf %q "$DIR") || exit 1
nohup $(printf %q "$PY") server.py < /dev/null >> "\$LOG" 2>&1 &
exit 0
SCRIPT
chmod +x "$APP/Contents/MacOS/launch"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>$NAME</string>
<key>CFBundleDisplayName</key><string>$NAME</string>
<key>CFBundleIdentifier</key><string>local.quickcrate.web</string>
<key>CFBundleExecutable</key><string>launch</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>$VERSION</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST

# Same icon as the native app, if the Swift compiler is available.
if command -v swiftc >/dev/null && [ -f ../macos/make_icon.swift ]; then
  TMP=$(mktemp -d)
  swiftc ../macos/make_icon.swift -o "$TMP/mkicon" && "$TMP/mkicon" "$TMP/icon.png"
  mkdir "$TMP/AppIcon.iconset"
  for sz in 16 32 128 256 512; do
    sips -z $sz $sz "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${sz}x${sz}.png" >/dev/null
    sips -z $((sz*2)) $((sz*2)) "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${sz}x${sz}@2x.png" >/dev/null
  done
  iconutil -c icns "$TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
  rm -rf "$TMP"
fi
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
touch "$APP"
echo "Created $APP"
echo "Open it from Launchpad or Finder, or drag it to your Dock."
