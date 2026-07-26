#!/bin/bash
# Universal installer for lyanpse. Works on any Linux distro
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
        --autostart)   ACTION="autostart" ;;
        --prefix=*)    PREFIX="${arg#--prefix=}" ;;
        -h|--help)
            echo "Usage: $0 [--user] [--uninstall] [--autostart] [--prefix=PATH]"
            exit 0
            ;;
    esac
done

cd "$(dirname "$0")"

if [ "$ACTION" = "uninstall" ]; then
    $USE_SUDO $(command -v python3) -m pip uninstall -y lyanpse || true
    $USE_SUDO rm -f "$PREFIX/share/applications/lyanpse.desktop"
    $USE_SUDO rm -f "$PREFIX/share/icons/hicolor/scalable/apps/lyanpse.svg"
    echo "Uninstalled."
    exit 0
fi

if [ "$ACTION" = "autostart" ]; then
    mkdir -p "$HOME/.config/autostart"
    cp data/lyanpse-autostart.desktop "$HOME/.config/autostart/lyanpse.desktop"
    echo "Autostart enabled — the tray icon will start on next login."
    echo "To undo: rm ~/.config/autostart/lyanpse.desktop"
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

if ! python3 -c 'import dbus' 2>/dev/null; then
    echo "Missing dbus-python (required for system tray). Install with:"
    need_pkg \
        "python-dbus" \
        "python3-dbus" \
        "python3-dbus" \
        "python3-dbus-python"
    exit 1
fi

if ! python3 -c 'from PIL import Image' 2>/dev/null; then
    echo "Missing Pillow (required for system tray). Install with:"
    need_pkg \
        "python-pillow" \
        "python3-pil" \
        "python3-pillow" \
        "python3-Pillow"
    exit 1
fi

echo "Installing to $PREFIX ..."
# pip install flags. PEP 668 (Arch / Debian 12+ / Fedora 38+) blocks system
# pip writes to /usr or /usr/local without --break-system-packages.
PIP_ARGS=(--prefix="$PREFIX")
if $USE_SUDO $(command -v python3) -m pip install --help 2>/dev/null | grep -q break-system-packages; then
    PIP_ARGS+=(--break-system-packages)
fi
$USE_SUDO $(command -v python3) -m pip install "${PIP_ARGS[@]}" ".[tray]"

# Make sure the launcher in $PREFIX/bin can find the module. On Arch/CachyOS,
# /usr/local/lib/python$X/site-packages isn't on Python's default sys.path,
# so /usr/local installs end up with a working pip but a broken launcher
# (ModuleNotFoundError). Always symlink the installed package into the system
# Python's site-packages — cheap, idempotent, fixes both Joe's and the
# original user's reports.
PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [ "$PREFIX" != "$HOME/.local" ] && [ "$PREFIX" != "/usr" ]; then
    INSTALLED_TO="$PREFIX/lib/python$PY_VER/site-packages/lyanpse"
    SYS_SP="/usr/lib/python$PY_VER/site-packages"
    # Test from /tmp (so the repo dir doesn't shadow the import).
    if [ -d "$INSTALLED_TO" ] && [ -d "$SYS_SP" ] && \
       ! ( cd /tmp && python3 -c "import lyanpse" ) 2>/dev/null; then
        echo "Symlinking $INSTALLED_TO → $SYS_SP/ (system sys.path doesn't include $PREFIX)"
        $USE_SUDO ln -sfn "$INSTALLED_TO" "$SYS_SP/lyanpse"
    fi
    # Same deal for the package's dist-info: without it on sys.path,
    # importlib.metadata.version('lyanpse') raises
    # PackageNotFoundError, which breaks the tray's update-check.
    if [ -d "$SYS_SP" ] && \
       ! ( cd /tmp && python3 -c "from importlib.metadata import version; version('lyanpse')" ) 2>/dev/null; then
        for d in "$PREFIX/lib/python$PY_VER/site-packages"/lyanpse-*.dist-info; do
            [ -d "$d" ] && $USE_SUDO ln -sfn "$d" "$SYS_SP/$(basename "$d")"
        done
    fi
fi
$USE_SUDO install -Dm644 data/lyanpse.desktop "$PREFIX/share/applications/lyanpse.desktop"
$USE_SUDO install -Dm644 data/lyanpse.svg "$PREFIX/share/icons/hicolor/scalable/apps/lyanpse.svg"

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    $USE_SUDO gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    $USE_SUDO update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true
fi

echo ""
echo "Done. Launch from your application menu or run:  lyanpse"
if ! id -nG "$USER" | grep -qw openrazer; then
    echo ""
    echo "WARNING: your user is not in the 'openrazer' group."
    echo "Add it so the GUI can write to the device:"
    echo "    sudo usermod -aG openrazer \$USER && newgrp openrazer"
fi
