# Blackshark-v3pro-guitray

GTK4 control panel + system tray for the **Razer BlackShark V3 / V3 Pro** headsets on
Linux. Controls the openrazer `razerkraken` driver's sysfs attributes — headphone EQ
(5 profile slots, 10 bands), mic EQ with 4 presets, sidetone, THX Spatial Audio, ANC /
Ambient mode, Ultra-Low-Latency mode, game/chat balance, in-call mix, audio prompts,
power-save timeout, and the audio function button mode.

Supports all four PIDs:
- `1532:0579` (BlackShark V3, wired)
- `1532:057a` (BlackShark V3, 2.4GHz dongle)
- `1532:0576` (BlackShark V3 Pro, wired)
- `1532:0577` (BlackShark V3 Pro, 2.4GHz dongle)

## Requirements

- Linux with an openrazer `razerkraken` driver that supports these devices. V3 Pro
  support isn't upstream yet — use
  [mehmetbayoglu/openrazer, branch `blackshark-v3-pro`](https://github.com/mehmetbayoglu/openrazer/tree/blackshark-v3-pro)
  until the upstream PR lands.
- Python 3.9+, GTK 4, PyGObject
- User in the `openrazer` group (added automatically when installing `openrazer-meta`)

## Install

### Universal (any distro)

```sh
git clone https://github.com/Stealthee/Blackshark-v3pro-guitray.git
cd Blackshark-v3pro-guitray
./install.sh           # system-wide (uses sudo)
./install.sh --user    # ~/.local install, no sudo
```

The script detects missing GTK4/PyGObject and prints the install command for your distro.

### Arch / CachyOS / Manjaro

```sh
cd packaging/arch
makepkg -si
```

### Debian / Ubuntu

```sh
sudo apt install devscripts debhelper dh-python python3-all python3-setuptools
ln -s packaging/debian debian
debuild -us -uc -b
sudo dpkg -i ../blackshark-control_*.deb
```

### Fedora / RHEL

```sh
sudo dnf install rpm-build python3-devel pyproject-rpm-macros python3-setuptools python3-pip python3-wheel
git archive --format=tar.gz --prefix=Blackshark-v3pro-guitray-0.1.2/ -o ../v0.1.2.tar.gz HEAD
rpmbuild -bb --define "_sourcedir $PWD/.." packaging/rpm/blackshark-control.spec
sudo dnf install ~/rpmbuild/RPMS/noarch/blackshark-control-*.rpm
```

### Uninstall

```sh
./install.sh --uninstall    # for the universal installer
# or your distro's package manager
```

## Updating

The tray icon checks GitHub on startup and shows an **"Update available: vX.Y.Z"**
item at the top of its menu when a newer release exists. Clicking it opens this repo
in your browser.

To actually install the update, from inside your cloned directory:

```sh
./bsupdate.sh           # same install mode as install.sh (sudo, /usr/local)
./bsupdate.sh --user    # if you installed with --user
```

This pulls the latest source, reinstalls, and restarts blackshark-control if it's
currently running.

## Autostart (tray icon on login)

The app starts hidden — it never pops up a window on launch — so adding it to your
session's autostart gives you a persistent battery + quick-settings tray icon with
nothing visible until you click it.

```sh
./install.sh --autostart
```

This installs `data/blackshark-control-autostart.desktop` to
`~/.config/autostart/blackshark-control.desktop`. To remove it again:

```sh
rm ~/.config/autostart/blackshark-control.desktop
```

## Usage

Launch from your application menu (entry: **BlackShark V3 Control**) or run:

```sh
blackshark-control
```

The status bar shows the detected device PID. If it says "Device not found", the driver isn't loaded or the device isn't bound — see the openrazer fork's setup notes.

### Tabs

- **Sound** — THX toggle, 5-slot headphone EQ (Default / Game / Movie / Music / Esports), 10-band sliders with auto-apply, "Reset to Default Values" button
- **Enhancement** — Ultra-Low Latency toggle (currently uses an unverified command byte)
- **Mic** — Sidetone slider (0–15), Mic EQ presets, 10-band Mic EQ sliders with reset, audio function button mode (Sidetone Save / Footsteps Scaling)
- **Power** — Wireless power save + timeout (currently uses an unverified command byte)

Mic volume is **not** controlled here — it's standard USB Audio Class 2, use `pavucontrol` / your normal audio mixer.

Per-slot custom EQ values persist in `~/.config/blackshark-control.json`.

## PipeWire: separate Game / Chat audio channels

The headset's hardware **Game/Chat balance** control (Sound tab / tray menu) mixes
two separate audio streams that the V3 Pro presents over USB — "Game" and "Chat".
By default, PipeWire's ALSA Card Profile (ACP) module doesn't know to split these
into separate sinks for the V3 Pro's USB IDs, so you get one combined sink and the
balance slider has nothing useful to mix.

A udev rule fixes this by pointing ACP at the `usb-gaming-headset.conf` profile-set
(already shipped by `alsa-card-profile`, used for other gaming headsets):

```sh
sudo cp udev/91-pipewire-blackshark-v3pro.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and replug the headset/dongle (or reboot). You should then see two sinks plus
a chat mic input:

```sh
wpctl status | grep -i blackshark
# or
pactl list sinks short | grep -i blackshark
```

- **BlackShark V3 Pro Game** — set this as the output for games / desktop audio
- **BlackShark V3 Pro Chat** — set this as the output for Discord / voice chat
- **BlackShark V3 Pro Chat** (input) — the headset mic

Set each app's output device in `pavucontrol` (Playback tab) or your DE's volume
mixer. The headset then mixes the two streams according to the **Game/Chat balance**
slider — fully toward "Game" mutes chat, fully toward "Chat" mutes game, center is
50/50.

### Recommended: disable USB autosuspend on the dongle

If the wireless dongle drops out after sitting idle, USB autosuspend is usually why:

```sh
sudo cp udev/50-razer-blackshark-power.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Releasing (maintainer note)

The tray's "Update available" notice (see [Updating](#updating)) works by comparing
the locally installed version against the `version` field in this repo's
`pyproject.toml` on the `main` branch. **Bump `version` in `pyproject.toml` on every
change you want users to be notified about** — without a bump, the notice won't
appear (or won't go away) correctly.

`pyproject.toml`'s `version` is the single source of truth. When you bump it, also
update the matching version strings in:

- `packaging/arch/PKGBUILD` (`pkgver=`)
- `packaging/rpm/blackshark-control.spec` (`Version:` + add a `%changelog` entry)
- `packaging/debian/changelog` (new entry at the top)

## Credits

This project started as a fork of
[mehmetbayoglu/blackshark-control](https://github.com/mehmetbayoglu/blackshark-control) —
thanks for the original groundwork that made this possible.

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
