#!/bin/bash
# Universal installer for blackshark-control. Works on any Linux distro
# with Python 3.9+, GTK4, and PyGObject available.
#
# Usage:
#   ./install.sh           — install to /usr/local (requires sudo)
#   ./install.sh --user    — install to ~/.local
#   ./install.sh --uninstall

set -e

PREFIX="/usr/local"
USE_SUDO="sudo"
ACTION="install"

for arg in "$@"; do
    case "$arg" in
        --user)        PREFIX="$HOME/.local"; USE_SUDO="" ;;
        --uninstall)   ACTION="uninstall" ;;
        --prefix=*)    PREFIX="${arg#--prefix=}" ;;
        -h|--help)
            echo "Usage: $0 [--user] [--uninstall] [--prefix=PATH]"
            exit 0
            ;;
    esac
done

cd "$(dirname "$0")"

if [ "$ACTION" = "uninstall" ]; then
    $USE_SUDO $(command -v python3) -m pip uninstall -y blackshark-control || true
    $USE_SUDO rm -f "$PREFIX/share/applications/blackshark-control.desktop"
    $USE_SUDO rm -f "$PREFIX/share/icons/hicolor/scalable/apps/blackshark-control.svg"
    echo "Uninstalled."
    exit 0
fi

# Detect missing dependencies and suggest install command
need_pkg() {
    case "$(. /etc/os-release && echo $ID)" in
        arch|cachyos|manjaro|endeavouros) echo "sudo pacman -S $1" ;;
        ubuntu|debian|pop|linuxmint)      echo "sudo apt install $2" ;;
        fedora|rhel|centos)                echo "sudo dnf install $3" ;;
        opensuse*|suse)                    echo "sudo zypper install $4" ;;
        *)                                 echo "Install Python 3, GTK4, and PyGObject for your distro" ;;
    esac
}

if ! python3 -c 'import gi; gi.require_version("Gtk","4.0"); from gi.repository import Gtk' 2>/dev/null; then
    echo "Missing GTK4 / PyGObject. Install with:"
    need_pkg \
        "python python-gobject gtk4" \
        "python3 python3-gi gir1.2-gtk-4.0" \
        "python3 python3-gobject gtk4" \
        "python3 python3-gobject gtk4"
    exit 1
fi

echo "Installing to $PREFIX ..."
$USE_SUDO $(command -v python3) -m pip install --prefix="$PREFIX" .
$USE_SUDO install -Dm644 data/blackshark-control.desktop "$PREFIX/share/applications/blackshark-control.desktop"
$USE_SUDO install -Dm644 data/blackshark-control.svg "$PREFIX/share/icons/hicolor/scalable/apps/blackshark-control.svg"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    $USE_SUDO gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    $USE_SUDO update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true
fi

echo ""
echo "Done. Launch from your application menu or run:  blackshark-control"
if ! id -nG "$USER" | grep -qw openrazer; then
    echo ""
    echo "WARNING: your user is not in the 'openrazer' group."
    echo "Add it so the GUI can write to the device:"
    echo "    sudo usermod -aG openrazer \$USER && newgrp openrazer"
fi
