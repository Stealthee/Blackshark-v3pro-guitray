#!/bin/bash
# Bootstrap installer: pulls the openrazer-blackshark driver fork +
# blackshark-control GUI in one go, builds the kernel module via DKMS,
# applies the per-attribute sysfs udev rule, and starts everything.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/mehmetbayoglu/blackshark-control/main/bootstrap.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/mehmetbayoglu/blackshark-control/main/bootstrap.sh | bash -s -- --branch v3
#
# Flags:
#   --branch v3      install the V3-only driver branch (default: blackshark-v3-pro)
#   --src DIR        clone/update repos here (default: $HOME)
#   --no-driver      skip the kernel module step (GUI only)
#   --no-gui         skip the GUI step (driver only)
#   --uninstall      remove driver + GUI

set -euo pipefail

BRANCH="blackshark-v3-pro"
SRC_DIR="$HOME"
DO_DRIVER=1
DO_GUI=1
ACTION="install"

while [ $# -gt 0 ]; do
    case "$1" in
        --branch)     BRANCH="$2"; shift 2 ;;
        --branch=*)   BRANCH="${1#--branch=}"; shift ;;
        --src)        SRC_DIR="$2"; shift 2 ;;
        --src=*)      SRC_DIR="${1#--src=}"; shift ;;
        --no-driver)  DO_DRIVER=0; shift ;;
        --no-gui)     DO_GUI=0; shift ;;
        --uninstall)  ACTION="uninstall"; shift ;;
        -h|--help)
            sed -n '4,18p' "$0"; exit 0 ;;
        *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
done

case "$BRANCH" in
    blackshark-v3-pro|v3-pro|pro) BRANCH="blackshark-v3-pro" ;;
    add-blackshark-v3-support|v3) BRANCH="add-blackshark-v3-support" ;;
esac

OPENRAZER_REPO="https://github.com/mehmetbayoglu/openrazer.git"
GUI_REPO="https://github.com/mehmetbayoglu/blackshark-control.git"
OPENRAZER_DIR="$SRC_DIR/openrazer-blackshark"
GUI_DIR="$SRC_DIR/blackshark-control"

DKMS_NAME="openrazer-driver"
DKMS_VER="3.12.99-blackshark-fork"
DKMS_SRC="/usr/src/${DKMS_NAME}-${DKMS_VER}"

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*" >&2; }
step()   { printf "\n\033[36m::\033[0m \033[1m%s\033[0m\n" "$*"; }

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || { red "missing required tool: $1"; exit 1; }
}

# Ensure deps.
need_cmd git
[ "$DO_DRIVER" = 1 ] && { need_cmd make; need_cmd dkms; }
[ "$DO_GUI" = 1 ] && need_cmd python3

# Avoid running the whole thing as root — sudo is invoked per-step instead.
if [ "$(id -u)" = 0 ] && [ -z "${ALLOW_ROOT:-}" ]; then
    red "don't run me as root — sudo is invoked per-step. (Set ALLOW_ROOT=1 to override.)"
    exit 1
fi

uninstall() {
    step "Uninstalling"
    if [ -d "$GUI_DIR" ]; then
        ( cd "$GUI_DIR" && [ -x install.sh ] && ./install.sh --uninstall || true )
    fi
    sudo dkms remove "${DKMS_NAME}/${DKMS_VER}" --all 2>/dev/null || true
    sudo rm -rf "$DKMS_SRC"
    sudo rm -f /usr/lib/udev/rules.d/99-razerkraken-sysfs.rules \
               /lib/udev/rules.d/99-razerkraken-sysfs.rules
    sudo udevadm control --reload || true
    green "uninstalled (source dirs at $OPENRAZER_DIR and $GUI_DIR left in place)"
    exit 0
}

[ "$ACTION" = "uninstall" ] && uninstall

clone_or_update() {
    local repo="$1" dir="$2" branch="$3"
    if [ -d "$dir/.git" ]; then
        step "updating $(basename "$dir") (branch: $branch)"
        git -C "$dir" fetch origin
        git -C "$dir" checkout "$branch"
        git -C "$dir" pull --ff-only
    else
        step "cloning $(basename "$dir") (branch: $branch)"
        git clone -b "$branch" "$repo" "$dir"
    fi
}

if [ "$DO_DRIVER" = 1 ]; then
    clone_or_update "$OPENRAZER_REPO" "$OPENRAZER_DIR" "$BRANCH"

    step "syncing source into DKMS tree"
    sudo mkdir -p "$DKMS_SRC"
    sudo rsync -a --delete --exclude='.git' "$OPENRAZER_DIR/" "$DKMS_SRC/"

    step "rebuilding kernel module via DKMS"
    sudo dkms remove "${DKMS_NAME}/${DKMS_VER}" --all 2>/dev/null || true
    sudo dkms add    "$DKMS_SRC"
    sudo dkms install "${DKMS_NAME}/${DKMS_VER}" --force

    step "installing udev rules"
    ( cd "$OPENRAZER_DIR" && sudo make udev_install )
    sudo udevadm control --reload

    step "reloading razerkraken module"
    sudo rmmod razerkraken 2>/dev/null || true
    sudo modprobe razerkraken
    sleep 1
    sudo modprobe -v razerkraken >/dev/null 2>&1 || true
    if lsmod | grep -q '^razerkraken'; then
        green "razerkraken loaded (srcversion: $(cat /sys/module/razerkraken/srcversion 2>/dev/null))"
    else
        yellow "razerkraken not loaded — check 'sudo dmesg | tail -20'"
    fi
fi

if [ "$DO_GUI" = 1 ]; then
    clone_or_update "$GUI_REPO" "$GUI_DIR" "main"
    step "installing blackshark-control"
    ( cd "$GUI_DIR" && ./install.sh )
fi

step "Done"
cat <<EOF

  Now unplug + replug the V3 / V3 Pro dongle so udev fires the per-bind
  chgrp rule on a fresh device. Then launch:

    blackshark-control

  Verify perms (after replug):

    ls -l /sys/bus/hid/drivers/razerkraken/0003:1532:*/charge_level
    # should show owner: root  group: plugdev  mode: 0660

  Membership: ensure your user is in the plugdev group:

    groups | grep -q plugdev || (sudo usermod -aG plugdev "\$USER" && echo \\
      "added to plugdev — log out + back in for it to take effect")

EOF
