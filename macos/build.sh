#!/bin/zsh
# Builds "Quick Crate.app" into ~/Applications.
# Needs the Xcode Command Line Tools (xcode-select --install). yt-dlp and ffmpeg are NOT bundled;
# install them separately (brew install yt-dlp ffmpeg).
# Override the bundle ID if you like:  BUNDLE_ID=io.github.yourname.quickcrate ./build.sh
set -e
cd "$(dirname "$0")"
VERSION="$(cat ../VERSION 2>/dev/null || echo 0.0.0)"
command -v swiftc >/dev/null || { echo "swiftc not found. Run: xcode-select --install"; exit 1; }
BUNDLE_ID="${BUNDLE_ID:-local.quickcrate}"
APP="$HOME/Applications/Quick Crate.app"
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
swiftc -O -parse-as-library -swift-version 5 QuickCrate.swift -o "$APP/Contents/MacOS/QuickCrate"
# App icon: draw 1024px PNG, then build the .icns
TMP=$(mktemp -d)
swiftc make_icon.swift -o "$TMP/mkicon"
"$TMP/mkicon" "$TMP/icon.png"
mkdir "$TMP/AppIcon.iconset"
for sz in 16 32 128 256 512; do
  sips -z $sz $sz "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${sz}x${sz}.png" >/dev/null
  sips -z $((sz*2)) $((sz*2)) "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns "$TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$TMP"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Quick Crate</string>
<key>CFBundleDisplayName</key><string>Quick Crate</string>
<key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundleExecutable</key><string>QuickCrate</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>$VERSION</string>
<key>CFBundleShortVersionString</key><string>$VERSION</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PL
codesign --force --sign - "$APP"
echo "Built $APP"
