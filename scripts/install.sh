#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_NAME="com.henry.dictation.plist"
HAMMERSPOON_DIR="$HOME/.hammerspoon"

mkdir -p "$LAUNCH_AGENT_DIR" "$HAMMERSPOON_DIR"

# 1. Symlink the LaunchAgent plist
if [ -L "$LAUNCH_AGENT_DIR/$PLIST_NAME" ] || [ -f "$LAUNCH_AGENT_DIR/$PLIST_NAME" ]; then
    echo "Removing existing $PLIST_NAME"
    launchctl unload "$LAUNCH_AGENT_DIR/$PLIST_NAME" 2>/dev/null || true
    rm -f "$LAUNCH_AGENT_DIR/$PLIST_NAME"
fi
ln -s "$REPO_DIR/launchagent/$PLIST_NAME" "$LAUNCH_AGENT_DIR/$PLIST_NAME"
echo "Linked $LAUNCH_AGENT_DIR/$PLIST_NAME"

# 2. Symlink the Hammerspoon module (dictation.lua) into ~/.hammerspoon/
if [ -L "$HAMMERSPOON_DIR/dictation.lua" ] || [ -f "$HAMMERSPOON_DIR/dictation.lua" ]; then
    rm -f "$HAMMERSPOON_DIR/dictation.lua"
fi
ln -s "$REPO_DIR/hammerspoon/dictation.lua" "$HAMMERSPOON_DIR/dictation.lua"
echo "Linked $HAMMERSPOON_DIR/dictation.lua"

# 3. Make sure ~/.hammerspoon/init.lua loads our module
INIT_LUA="$HAMMERSPOON_DIR/init.lua"
LOAD_LINE='require("dictation")'
if [ ! -f "$INIT_LUA" ] || ! grep -qF "$LOAD_LINE" "$INIT_LUA"; then
    echo "$LOAD_LINE" >> "$INIT_LUA"
    echo "Appended dictation loader to $INIT_LUA"
fi

# 4. Load + kickstart the LaunchAgent.
# `launchctl load` alone often does NOT auto-spawn on recent macOS even with RunAtLoad=true;
# `kickstart` forces the spawn. Idempotent if already running.
launchctl load "$LAUNCH_AGENT_DIR/$PLIST_NAME" 2>/dev/null || true
launchctl kickstart -p "gui/$(id -u)/com.henry.dictation" >/dev/null
echo "LaunchAgent loaded and kickstarted."
echo "  - first run: model downloads ~4GB and loads (several minutes)"
echo "  - subsequent runs: model loads from cache (~1-2s)"
echo "  - daemon logs: ~/Library/Logs/dictation.log (stdout), dictation.err (stderr)"

# 5. Reload Hammerspoon if it's running
if pgrep -x Hammerspoon >/dev/null; then
    osascript -e 'tell application "Hammerspoon" to reload'
    echo "Hammerspoon reloaded."
else
    echo "Hammerspoon is not running. Launch it from /Applications and grant Accessibility permission."
fi
