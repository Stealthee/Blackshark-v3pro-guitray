# blackshark-control

GTK4 control panel for the **Razer BlackShark V3** headset on Linux. Controls the openrazer `razerkraken` driver's sysfs attributes — headphone EQ (5 profile slots, 10 bands), mic EQ with 4 presets, sidetone, and the audio function button mode.

Supports both PIDs:
- `1532:0579` (wired USB)
- `1532:057a` (2.4GHz dongle)

## Requirements

- Linux with the openrazer kernel module that supports the BlackShark V3 (PR [openrazer/openrazer#2784](https://github.com/openrazer/openrazer/pull/2784) or later)
- Python 3.9+, GTK 4, PyGObject
- User in the `openrazer` group (added automatically when installing `openrazer-meta`)

## Install

### Universal (any distro)

```sh
git clone https://github.com/mehmetbayoglu/blackshark-control.git
cd blackshark-control
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
sudo dnf install rpm-build python3-devel python3-setuptools python3-pip python3-wheel
rpmbuild -bb --define "_sourcedir $PWD/.." packaging/rpm/blackshark-control.spec
sudo dnf install ~/rpmbuild/RPMS/noarch/blackshark-control-*.rpm
```

### Uninstall

```sh
./install.sh --uninstall    # for the universal installer
# or your distro's package manager
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

## License

GPL-2.0-or-later. See [LICENSE](LICENSE).
