#!/bin/bash
# Update blackshark-control: pulls the latest source from this clone's
# git remote and reinstalls.
#
# Usage: from inside your cloned Blackshark-v3pro-guitray directory:
#   ./bsupdate.sh           — same install mode as install.sh (sudo, /usr/local)
#   ./bsupdate.sh --user    — reinstall to ~/.local
#
# Any extra arguments are passed through to install.sh. If
# blackshark-control is currently running, it's restarted afterward so the
# update takes effect immediately.

set -e
cd "$(dirname "$0")"

echo "Pulling latest changes..."
git pull

echo ""
./install.sh "$@"

if pgrep -f '/bin/blackshark-control$' >/dev/null; then
    echo ""
    echo "Restarting blackshark-control..."
    pkill -f '/bin/blackshark-control$'
    sleep 1
    nohup blackshark-control >/dev/null 2>&1 &
    disown
fi

echo ""
echo "Update complete."
