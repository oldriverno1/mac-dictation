#!/usr/bin/env bash
set -euo pipefail

LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.henry.dictation.plist"
HAMMERSPOON_DIR="$HOME/.hammerspoon"

launchctl unload "$LAUNCH_AGENT_DIR/$PLIST_NAME" 2>/dev/null || true
rm -f "$LAUNCH_AGENT_DIR/$PLIST_NAME"
rm -f "$HAMMERSPOON_DIR/dictation.lua"

INIT_LUA="$HAMMERSPOON_DIR/init.lua"
if [ -f "$INIT_LUA" ]; then
    sed -i '' '/require("dictation")/d' "$INIT_LUA"
fi

if pgrep -x Hammerspoon >/dev/null; then
    osascript -e 'tell application "Hammerspoon" to reload'
fi

echo "Uninstalled. Daemon stopped, plist removed, Hammerspoon module unlinked."
