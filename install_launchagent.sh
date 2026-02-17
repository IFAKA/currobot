#!/usr/bin/env bash
# Install the macOS Launch Agent so FastAPI starts automatically on login.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.jobbot.backend.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.jobbot.backend.plist"

# Replace JOBBOT_DIR placeholder with actual path
sed "s|JOBBOT_DIR|$SCRIPT_DIR|g" "$PLIST_SRC" > "$PLIST_DEST"

# Load it
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "✓ Launch Agent installed and loaded."
echo "  The JobBot backend will now start automatically on login."
echo "  To uninstall: launchctl unload $PLIST_DEST && rm $PLIST_DEST"
