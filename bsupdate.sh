#!/bin/bash
# Update lynapse: pulls the latest source from this clone's
# git remote and reinstalls.
#
# Usage: from inside your cloned Blackshark-v3pro-guitray directory:
#   ./bsupdate.sh           — same install mode as install.sh (sudo, /usr/local)
#   ./bsupdate.sh --user    — reinstall to ~/.local
#
# Any extra arguments are passed through to install.sh. If
# lynapse is currently running, it's restarted afterward so the
# update takes effect immediately.

set -e
cd "$(dirname "$0")"

echo "Pulling latest changes..."
git pull

echo ""
./install.sh "$@"

if pgrep -f '/bin/lynapse$' >/dev/null; then
    echo ""
    echo "Restarting lynapse..."
    pkill -f '/bin/lynapse$'
    sleep 1
    nohup lynapse >/dev/null 2>&1 &
    disown
fi

echo ""
echo "Update complete."
