#!/bin/bash
# Full-stack installer: builds the OpenRazer fork's razerkraken kernel module
# (with BlackShark V3 / V3 Pro support), wires up udev, and installs this GUI.
#
# Use this if you don't already have the openrazer fork installed. If you only
# want the GUI and have a working driver, use ./install.sh instead.
#
# Tested on Arch / CachyOS. For Debian/Fedora swap pacman commands and adjust
# kernel-headers package name.

set -euo pipefail

KERNEL="$(uname -r)"
FORK_REPO="${FORK_REPO:-https://github.com/mehmetbayoglu/openrazer.git}"
FORK_BRANCH="${FORK_BRANCH:-blackshark-v3-pro}"
FORK_DIR="${FORK_DIR:-$HOME/openrazer-blackshark}"
GUI_REPO="${GUI_REPO:-https://github.com/mehmetbayoglu/blackshark-control.git}"

# Detect whether we were piped from curl ($0 = bash) vs invoked from a checkout.
# When piped, clone fresh to $HOME/blackshark-control. When invoked from a
# checkout, install from that checkout directly.
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
if [ -f "$SCRIPT_PATH" ] && [ -f "$(dirname "$SCRIPT_PATH")/pyproject.toml" ]; then
    GUI_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
else
    GUI_DIR="${GUI_DIR:-$HOME/blackshark-control}"
fi

say()  { printf '\n\033[1;32m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }

# ── 1. Stop daemon and any old GUI that might lock the device ───────────────
say "Stopping any running openrazer daemon and old GUI processes"
systemctl --user stop openrazer-daemon 2>/dev/null || true
pkill -f openrazer-daemon 2>/dev/null || true
pkill -f lynapse 2>/dev/null || true

# ── 2. Remove distro / DKMS razerkraken so our local build wins ─────────────
say "Removing distro openrazer-driver-dkms / openrazer-daemon if present"
sudo pacman -Rns --noconfirm openrazer-driver-dkms openrazer-daemon 2>/dev/null || true

say "Removing every prior openrazer-driver DKMS install"
while read -r entry; do
    [ -n "$entry" ] || continue
    sudo dkms remove "$entry" --all 2>/dev/null || true
done < <(dkms status 2>/dev/null | awk -F', ' '/^openrazer-driver/ {print $1}')
sudo rm -rf /usr/src/openrazer-driver-*
# Wipe leftover .ko files DKMS or earlier non-DKMS installs may have left.
# A kernel-tree copy at /lib/modules/$VER/kernel/.../razerkraken.ko is fine to
# keep: modprobe priority puts /updates/dkms/ above /kernel/, so our build wins.
sudo rm -f "/lib/modules/$KERNEL/updates/dkms/razerkraken.ko"* \
           "/lib/modules/$KERNEL/extra/razerkraken.ko"*
sudo depmod -a
sudo rmmod razerkraken 2>/dev/null || true

CURRENT_MOD="$(modinfo -F filename razerkraken 2>/dev/null || true)"
case "$CURRENT_MOD" in
    "" )
        ;; # nothing on modpath, perfect
    /lib/modules/*/kernel/* )
        say "Kernel-tree razerkraken at $CURRENT_MOD — leaving alone (our DKMS install will override)"
        ;;
    * )
        warn "razerkraken is STILL on the modpath at: $CURRENT_MOD"
        warn "Unexpected location — delete it manually before re-running this script."
        exit 1
        ;;
esac

# ── 3. Clone or update the openrazer fork ───────────────────────────────────
say "Cloning/updating openrazer fork ($FORK_BRANCH)"
if [ ! -d "$FORK_DIR" ]; then
    git clone -b "$FORK_BRANCH" "$FORK_REPO" "$FORK_DIR"
else
    git -C "$FORK_DIR" fetch origin
    git -C "$FORK_DIR" checkout "$FORK_BRANCH"
    git -C "$FORK_DIR" pull --ff-only
fi

# ── 4. Install via DKMS so kernel updates auto-rebuild ──────────────────────
DKMS_PACKAGE="openrazer-driver"
DKMS_VERSION="3.12.99-blackshark-fork"

if ! command -v dkms >/dev/null 2>&1; then
    say "Installing dkms"
    sudo pacman -S --noconfirm --needed dkms 2>/dev/null \
        || sudo apt install -y dkms 2>/dev/null \
        || sudo dnf install -y dkms 2>/dev/null \
        || { warn "Couldn't auto-install dkms — install it for your distro and rerun."; exit 1; }
fi

say "Removing any prior $DKMS_PACKAGE/$DKMS_VERSION DKMS install"
sudo dkms remove "$DKMS_PACKAGE/$DKMS_VERSION" --all 2>/dev/null || true
sudo rm -rf "/usr/src/$DKMS_PACKAGE-$DKMS_VERSION"

say "Registering source tree at /usr/src/$DKMS_PACKAGE-$DKMS_VERSION"
sudo cp -r "$FORK_DIR" "/usr/src/$DKMS_PACKAGE-$DKMS_VERSION"
sudo cp "$FORK_DIR/install_files/dkms/dkms.conf" "/usr/src/$DKMS_PACKAGE-$DKMS_VERSION/dkms.conf"
# Override PACKAGE_VERSION to our fork-specific tag so we never collide with
# whatever upstream openrazer-driver version the distro might ship.
sudo sed -i "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\"$DKMS_VERSION\"/" \
    "/usr/src/$DKMS_PACKAGE-$DKMS_VERSION/dkms.conf"

say "Building + installing via dkms (auto-rebuilds on every kernel update)"
sudo dkms add -m "$DKMS_PACKAGE" -v "$DKMS_VERSION"
sudo dkms install -m "$DKMS_PACKAGE" -v "$DKMS_VERSION" --force

# ── 5. Install udev rule + razer_mount helper ───────────────────────────────
say "Installing udev rule and razer_mount helper"
sudo mkdir -p /usr/share/openrazer
sudo install -m 644 "$FORK_DIR/install_files/udev/99-razer.rules" \
    /etc/udev/rules.d/99-razer.rules
sudo install -m 755 "$FORK_DIR/install_files/udev/razer_mount" \
    /usr/share/openrazer/razer_mount
# PipeWire upstream doesn't tag V3 Pro PIDs with the gaming-headset
# profile-set yet; this rule does so we get separate Game / Chat sinks.
if [ -f "$FORK_DIR/install_files/udev/91-pipewire-blackshark-v3pro.rules" ]; then
    sudo install -m 644 "$FORK_DIR/install_files/udev/91-pipewire-blackshark-v3pro.rules" \
        /etc/udev/rules.d/91-pipewire-blackshark-v3pro.rules
fi
sudo udevadm control --reload-rules

# ── 6. Make the user a member of plugdev ────────────────────────────────────
NEED_LOGOUT=0
if ! groups | grep -q '\bplugdev\b'; then
    say "Adding $USER to plugdev"
    sudo gpasswd -a "$USER" plugdev
    NEED_LOGOUT=1
fi

# ── 7. Load the module ──────────────────────────────────────────────────────
say "Loading razerkraken module"
sudo modprobe razerkraken

# ── 7b. Manually fix sysfs perms for any already-bound device ───────────────
# The udev rule fires on physical plug events, not on driver-bind via modprobe,
# so the attrs come up root:root 0640 if the device was already plugged in.
# chgrp + chmod here so the GUI works immediately, without forcing a replug.
say "Setting sysfs perms on bound devices (matches udev rule)"
shopt -s nullglob
for dev_dir in /sys/bus/hid/drivers/razerkraken/0003:1532:*; do
    [ -d "$dev_dir" ] || continue
    sudo chgrp plugdev "$dev_dir"/* 2>/dev/null || true
    sudo chmod g+rw  "$dev_dir"/* 2>/dev/null || true
done
shopt -u nullglob

# ── 8. Install the GUI ──────────────────────────────────────────────────────
say "Cloning/updating Lynapse GUI"
if [ ! -f "$GUI_DIR/pyproject.toml" ]; then
    [ -d "$GUI_DIR" ] && rm -rf "$GUI_DIR"
    git clone "$GUI_REPO" "$GUI_DIR"
else
    git -C "$GUI_DIR" pull --ff-only 2>/dev/null || true
fi

say "Removing any /usr/local shim from a previous install"
sudo rm -f /usr/local/bin/lynapse

say "Installing Lynapse to /usr"
sudo pip install --break-system-packages --prefix=/usr --force-reinstall --no-deps "$GUI_DIR"
hash -r

# ── 9. Summary ──────────────────────────────────────────────────────────────
echo
echo "─────────────────────────────────────────────────────────────"
echo " Install complete."
echo "─────────────────────────────────────────────────────────────"
if [ "$NEED_LOGOUT" = 1 ]; then
    echo " ⚠  You were just added to the 'plugdev' group."
    echo "    Log out and back in (or reboot) so the group sticks."
fi
echo
echo " Now UNPLUG the V3 / V3 Pro dongle or cable and PLUG IT BACK IN."
echo " That fires the udev rule which sets sysfs perms to plugdev rw."
echo
echo " Then verify and launch:"
echo "   ls /sys/bus/hid/drivers/razerkraken/"
echo "     # should list 0003:1532:0577.* (V3 Pro 2.4 GHz),"
echo "     # 0003:1532:0576.* (V3 Pro wired), 057A.* (V3 2.4 GHz),"
echo "     # or 0579.* (V3 wired)"
echo "   lynapse"
