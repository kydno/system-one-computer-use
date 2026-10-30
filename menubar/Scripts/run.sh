#!/bin/bash
# Build, replace any running copy, launch. Launching puts the app in the menu
# bar and nothing else: no run starts until you give it a goal.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="SystemOne"

"$ROOT/Scripts/build.sh"

# An LSUIElement app has no Dock tile to quit from, so stop the old one by name.
if pgrep -x "$NAME" >/dev/null 2>&1; then
    echo "==> stopping running $NAME"
    pkill -x "$NAME" || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        pgrep -x "$NAME" >/dev/null 2>&1 || break
        sleep 0.2
    done
fi

echo "==> launching"
# `open` hands the app this shell's environment, and runs inherit it: an
# ANTHROPIC_BASE_URL from the shell would take the writer away from OpenRouter.
# Launch clean, as from Finder or the login item, so only `.env` decides.
env -i HOME="$HOME" USER="$USER" LOGNAME="${LOGNAME:-$USER}" TMPDIR="${TMPDIR:-/tmp}" \
    LANG="${LANG:-en_US.UTF-8}" PATH="/usr/bin:/bin:/usr/sbin:/sbin" \
    open "$ROOT/$NAME.app"
echo "==> look for the icon in the menu bar"
