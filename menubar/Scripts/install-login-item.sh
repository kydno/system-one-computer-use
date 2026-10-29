#!/bin/bash
# Starts SystemOne.app at every login, from where it was built, via a LaunchAgent.
#
# The agent runs `open` on the bundle rather than exec'ing its binary:
# Menu-Bar-Chat found that a login item exec'd directly may not be the process
# macOS attached Screen Recording to, and the runs need it. Re-run this if you
# move the checkout. Scripts/uninstall-login-item.sh undoes it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.kydno.SystemOne"
APP="$ROOT/SystemOne.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ -d "$APP" ] || { echo "!! no built app at $APP; run ./Scripts/build.sh first" >&2; exit 1; }

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>/usr/bin/open</string>
		<string>$APP</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
</dict>
</plist>
PL

# Replace any previous registration cleanly. Loading it also runs it once,
# which launches the app now.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

echo "==> installed login item"
echo "    plist : $PLIST"
echo "    app   : $APP"
