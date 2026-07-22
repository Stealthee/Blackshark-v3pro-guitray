Name:           blackshark-control
Version:        0.1.2
Release:        1%{?dist}
Summary:        GTK4 control panel for the Razer BlackShark V3 headset

License:        GPL-2.0-or-later
URL:            https://github.com/Stealthee/Blackshark-v3pro-guitray
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-setuptools
BuildRequires:  python3-pip
BuildRequires:  python3-wheel

Requires:       python3
Requires:       python3-gobject
Requires:       gtk4
Requires:       openrazer-meta

%description
GTK4 control panel for the Razer BlackShark V3 wired and 2.4GHz wireless
variants. Provides headphone EQ (5 profile slots, 10 bands), mic EQ,
mic EQ presets, sidetone, and audio function button mode controls via
the openrazer razerkraken driver's sysfs interface.

%prep
%autosetup -n Blackshark-v3pro-guitray-%{version}

%build
%pyproject_wheel

%install
%pyproject_install
install -Dm644 data/blackshark-control.desktop %{buildroot}%{_datadir}/applications/blackshark-control.desktop
install -Dm644 data/blackshark-control.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/blackshark-control.svg

%files
%license LICENSE
%doc README.md
%{_bindir}/blackshark-control
%{python3_sitelib}/blackshark_control/
%{python3_sitelib}/blackshark_control-*.dist-info/
%{_datadir}/applications/blackshark-control.desktop
%{_datadir}/icons/hicolor/scalable/apps/blackshark-control.svg

%changelog
* Fri Jun 12 2026 Mehmet Bayoglu - 0.1.2-1
- Fix battery-trend charging override not surviving an app restart

* Thu Jun 11 2026 Mehmet Bayoglu - 0.1.1-1
- Add tray "Update available" notice (checks GitHub for newer releases)
- Add bsupdate.sh helper to pull and reinstall in one step
- Add autostart support and PipeWire game/chat channel setup docs

* Sun Apr 26 2026 Mehmet Bayoglu - 0.1.0-1
- Initial package
