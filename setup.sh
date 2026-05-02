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
pkill -f blackshark-control 2>/dev/null || true

# ── 2. Remove distro / DKMS razerkraken so our local build wins ─────────────
say "Removing distro openrazer-driver-dkms / openrazer-daemon if present"
sudo pacman -Rns --noconfirm openrazer-driver-dkms openrazer-daemon 2>/dev/null || true

say "Removing any DKMS-registered razerkraken"
DKMS_VER="$(dkms status 2>/dev/null | awk -F'[/,]' '/openrazer/ {print $2; exit}' || true)"
if [ -n "$DKMS_VER" ]; then
    sudo dkms remove "openrazer-driver/$DKMS_VER" --all || true
fi
sudo rm -f "/lib/modules/$KERNEL/updates/dkms/razerkraken.ko"*
sudo depmod -a
sudo rmmod razerkraken 2>/dev/null || true

if modinfo -F filename razerkraken >/dev/null 2>&1; then
    warn "razerkraken is STILL on the modpath at: $(modinfo -F filename razerkraken)"
    warn "Delete that file manually before re-running this script — otherwise the"
    warn "kernel will keep loading the wrong .ko on every boot."
    exit 1
fi

# ── 3. Clone or update the openrazer fork ───────────────────────────────────
say "Cloning/updating openrazer fork ($FORK_BRANCH)"
if [ ! -d "$FORK_DIR" ]; then
    git clone -b "$FORK_BRANCH" "$FORK_REPO" "$FORK_DIR"
else
    git -C "$FORK_DIR" fetch origin
    git -C "$FORK_DIR" checkout "$FORK_BRANCH"
    git -C "$FORK_DIR" pull --ff-only
fi

# ── 4. Build the kernel module (LLVM=1 for clang-built kernels) ─────────────
say "Building razerkraken module"
make -C "$FORK_DIR/driver" clean 2>/dev/null || true
make -C "$FORK_DIR" driver LLVM=1

# ── 5. Install module + udev rule + razer_mount helper ──────────────────────
say "Installing module to /lib/modules/$KERNEL/extra/"
sudo install -D -m 644 "$FORK_DIR/driver/razerkraken.ko" \
    "/lib/modules/$KERNEL/extra/razerkraken.ko"
sudo depmod -a
echo razerkraken | sudo tee /etc/modules-load.d/razerkraken.conf >/dev/null

say "Installing udev rule and razer_mount helper"
sudo mkdir -p /usr/share/openrazer
sudo install -m 644 "$FORK_DIR/install_files/udev/99-razer.rules" \
    /etc/udev/rules.d/99-razer.rules
sudo install -m 755 "$FORK_DIR/install_files/udev/razer_mount" \
    /usr/share/openrazer/razer_mount
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

# ── 8. Install the GUI ──────────────────────────────────────────────────────
say "Cloning/updating blackshark-control GUI"
if [ ! -f "$GUI_DIR/pyproject.toml" ]; then
    [ -d "$GUI_DIR" ] && rm -rf "$GUI_DIR"
    git clone "$GUI_REPO" "$GUI_DIR"
else
    git -C "$GUI_DIR" pull --ff-only 2>/dev/null || true
fi

say "Removing any /usr/local shim from a previous install"
sudo rm -f /usr/local/bin/blackshark-control

say "Installing blackshark-control to /usr"
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
echo "   blackshark-control"
