#!/usr/bin/env bash
# Build a native arm64 application that uses this checkout and its runtime.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
parent="$(cd "$repo/.." && pwd)"
destination="${1:-$parent/output/五线谱转简谱.app}"
mkdir -p "$(dirname "$destination")"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
app="$stage/五线谱转简谱.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
printf '%s\n' "$repo" > "$app/Contents/Resources/repository.txt"

cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>CFBundleExecutable</key><string>MusicTranslator</string>
    <key>CFBundleIdentifier</key><string>org.musictranslator.local</string>
    <key>CFBundleName</key><string>五线谱转简谱</string>
    <key>CFBundleDisplayName</key><string>五线谱转简谱</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

xcrun swiftc -parse-as-library -O -target arm64-apple-macos14.0 \
    "$repo/macos/MusicTranslator.swift" -o "$app/Contents/MacOS/MusicTranslator"
codesign --force --sign - "$app"
ditto "$app" "$destination"
printf '%s\n' "$destination"
