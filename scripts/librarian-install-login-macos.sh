#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.ollama-librarian.startup.plist"
LABEL="com.ollama-librarian.startup"

mkdir -p "$PLIST_DIR"

cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/bash</string>
      <string>$REPO_DIR/scripts/librarian-start-macos.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>OLLAMA_WEB_HOST</key>
      <string>127.0.0.1</string>
      <key>OLLAMA_WEB_ALLOW_INSECURE_BIND</key>
      <string>0</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
  </dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"

echo "Installed login startup agent: $PLIST_PATH"
