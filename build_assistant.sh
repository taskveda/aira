#!/bin/bash
# Build the Aira.app mic-permission wrapper + install the launchd login item.
#
# Why this exists: the "Hey Aira" wake word reads the microphone from a
# launchd background process. macOS (TCC) only grants microphone access to a
# process that has an NSMicrophoneUsageDescription in an .app bundle — a bare
# `python -m aira.main --assistant` in launchd gets auto-denied, so the wake
# word silently never hears anything. This builds a tiny Aira.app whose
# launcher execs the assistant, and registers that app with launchd so the
# first run shows the macOS mic permission prompt for "Aira".
set -e
cd "$(dirname "$0")"
APP="$HOME/aira/Aira.app"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.taskveda.aira.plist"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/MacOS/raslauncher" << 'EOF'
#!/bin/bash
# Aira — GUI wrapper so macOS can grant the mic permission.
# launchd runs this binary directly; it execs the full Aira assistant
# (text popup + web UI + "Hey Aira" wake-word voice), sharing one brain.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$HOME/aira"
exec "$HOME/aira/venv/bin/python" -u -m aira.main --assistant
EOF
chmod +x "$APP/Contents/MacOS/raslauncher"

cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.taskveda.aira</string>
    <key>CFBundleName</key>
    <string>Aira</string>
    <key>CFBundleDisplayName</key>
    <string>Aira</string>
    <key>CFBundleExecutable</key>
    <string>raslauncher</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>Aira listens for the "Hey Aira" wake word.</string>
    <key>NSSpeechRecognitionUsageDescription</key>
    <string>Aira converts your spoken tasks to text.</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP"

cat > "$LAUNCH_AGENT" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.taskveda.aira</string>
    <key>ProgramArguments</key>
    <array>
        <string>$HOME/aira/Aira.app/Contents/MacOS/raslauncher</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$HOME/aira</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/aira/data/assistant.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/aira/data/assistant.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:/Library/Python/3.14/bin</string>
    </dict>
    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
PLIST

# Replace literal $HOME (the plist must be expanded for launchctl).
perl -pi -e "s#\\\$HOME#$HOME#g" "$LAUNCH_AGENT"

echo "Built $APP and installed $LAUNCH_AGENT"
echo
echo "Next steps:"
echo "  1. launchctl unload ~/Library/LaunchAgents/com.taskveda.aira.plist 2>/dev/null; true"
echo "  2. open $APP   (macOS will ask: 'Aira would like to access the microphone' -> Allow)"
echo "  3. launchctl load ~/Library/LaunchAgents/com.taskveda.aira.plist"
echo "  4. Say \"Hey Aira\" — popup rises with the orb + it greets aloud."
