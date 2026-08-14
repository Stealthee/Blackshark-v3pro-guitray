Name:           lynapse
Version:        0.1.17
Release:        1%{?dist}
Summary:        Lynapse — GTK4 control panel for the Razer BlackShark V3 headset

License:        GPL-2.0-or-later
URL:            https://github.com/Stealthee/Blackshark-v3pro-guitray
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
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
%autosetup -n %{name}-%{version}

%build
%py3_build

%install
%py3_install
install -Dm644 data/lynapse.desktop %{buildroot}%{_datadir}/applications/lynapse.desktop
install -Dm644 data/lynapse.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/lynapse.svg

%files
%license LICENSE
%doc README.md
%{_bindir}/lynapse
%{python3_sitelib}/lynapse/
%{python3_sitelib}/lynapse-*.egg-info/
%{_datadir}/applications/lynapse.desktop
%{_datadir}/icons/hicolor/scalable/apps/lynapse.svg

%changelog
* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.17-1
- Redesign tray quick popup as "Lynapse Reorder Quick Menu": lists all
  11 right-click menu items (not just 3) as plain read-only labels
  (matching the real menu's own text) instead of interactive controls
  -- this popup is purely for reordering the right-click menu, which
  it now does live via BatteryTray.set_order(). About and Quit are
  pinned, always last, not reorderable. Uses the Lynapse app icon
  instead of the generic window icon.

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.16-1
- Fix tray icon left-click doing nothing (showed the same right-click
  context menu instead of the quick-settings popup): the SNI
  ItemIsMenu property was advertised as true, which tells Plasma's
  systray to never call Activate() at all and always show the menu
  for every click. Set to false so left-click reaches the popup while
  right-click still opens the context menu as before.

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.15-1
- Fix tray quick-popup reordering: the drag handle was a tiny, easy-
  to-miss glyph with no real hitbox, so clicks meant for it landed on
  the section's own buttons instead; added big ▲/▼ move buttons as a
  guaranteed-to-work alternative to dragging. Also fixed a real bug in
  Gtk.ListBox row moves -- remove()/insert() called back-to-back
  operated on stale row-index state without a main-loop turn in
  between, silently no-opping the reorder.

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.14-1
- Add THX Spatial Audio toggle to the tray right-click menu and the
  quick-settings popup, same setup gate as the main window (fires a
  desktop notification pointing at THX_SETUP.md when not configured)
- Wire up the tray icon's left-click to actually show the quick-
  settings popup (was fully built but never connected -- left-click
  opened the full window instead)
- Add drag-to-reorder + a lock/unlock row to the quick-settings popup,
  order and lock state persisted across restarts

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.13-1
- THX Spatial Audio: push makeup gain to the midpoint between the
  previous +4.3dB and Windows Synapse's measured +10.9dB (~+7.6dB net,
  Gain 3.17 -> 4.8). Known to clip on sustained loud/broadband
  passages (confirmed on a pink-noise test tone) -- listen for
  harshness on real content before trusting this value long-term.

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.12-1
- THX Spatial Audio: fix makeup-gain calibration -- the mixer's "Gain N"
  control isn't a linear multiplier the way it was assumed to be; the
  previous two gain bumps (1.4, then 1.96) both landed within ~0.2dB of
  an unprocessed bypass signal, i.e. audibly unchanged, confirmed via
  live A/B measurement. Recalibrated to a measured +4.3dB net.

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.11-1
- THX Spatial Audio: fix streams that start/reconnect to the game sink
  after the toggle-time sweep window never getting the effect applied
  (sounded identical to THX off no matter how many times you flipped it)

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.10-1
- THX Spatial Audio: stack a second gain bump on the convolver graph
  (~+3dB more, same size step as the previous bump)

* Thu Aug 13 2026 Mehmet Bayoglu - 0.1.9-1
- THX Spatial Audio: tune the PipeWire convolver graph with a modest
  output gain stage and a ~2.5dB high-shelf cut above 2.5kHz, informed by
  a Windows Synapse THX audio A/B capture

* Fri Jun 12 2026 Mehmet Bayoglu - 0.1.2-1
- Fix battery-trend charging override not surviving an app restart

* Thu Jun 11 2026 Mehmet Bayoglu - 0.1.1-1
- Add tray "Update available" notice (checks GitHub for newer releases)
- Add bsupdate.sh helper to pull and reinstall in one step
- Add autostart support and PipeWire game/chat channel setup docs

* Sun Apr 26 2026 Mehmet Bayoglu - 0.1.0-1
- Initial package
