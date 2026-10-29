#!/bin/bash
# Stops SystemOne.app starting at login. Leaves the app itself alone.
set -euo pipefail
LABEL="com.kydno.SystemOne"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
echo "==> removed login item ($PLIST)"
