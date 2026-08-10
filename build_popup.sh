#!/bin/bash
# Build the Siri-style Aira popup app (needs Xcode Command Line Tools: swiftc).
set -e
cd "$(dirname "$0")"
APP="$HOME/aira/AiraPopup.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

swiftc -O \
  -framework AppKit -framework AVFoundation -framework Carbon -framework CoreGraphics \
  popup/AiraPopup.swift \
  -o "$APP/Contents/MacOS/AiraPopup"

cp popup/Info.plist "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"

echo "Built $APP"
