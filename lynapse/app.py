#!/usr/bin/env python3
"""Lynapse — real-time testing GUI for the Razer BlackShark V3 headset (razerkraken driver fork)."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk, Pango, Gio, GObject
import glob, os, subprocess, json, threading, time, traceback
from importlib.metadata import version as _pkg_version, PackageNotFoundError

_APP_LOG = '/tmp/bs-control.log'

def _log(msg):
    try:
        with open(_APP_LOG, 'a') as _f:
            _f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')
    except Exception:
        pass

def _pump_main_loop():
    """Drain pending GLib main-context work synchronously. Gtk.ListBox
    doesn't update its row-index bookkeeping inside remove()/insert()
    themselves — it needs a main-loop turn — so code that does a
    remove() immediately followed by an insert() (see TrayView._move_row)
    needs this in between, or the insert operates on stale indices."""
    ctx = GLib.MainContext.default()
    while ctx.iteration(False):
        pass

from lynapse._tray import BatteryTray as _BatteryTray, REORDERABLE_ITEMS
from lynapse import _update_check
from lynapse import _thx

SYSFS_DIR = '/sys/bus/hid/drivers/razerkraken'
PIDS = ('0576', '0577', '057A', '0579')   # V3 Pro wired, V3 Pro 2.4GHz, V3 wireless dongle, V3 wired

# Per-PID feature/capability map. Each entry is the sysfs attr name (or None).
# A feature with attr=None is hidden in the GUI for that device.
DEVICE_CAPS = {
    # V3 wireless dongle (full V3 feature set)
    '057A': {
        'name': 'BlackShark V3 (2.4 GHz)',
        'thx': 'thx_spatial_audio',
        'ull': 'ultra_low_latency',
        'sidetone': 'sidetone',
        'eq': 'headphone_eq',         # accepts "<profile> b1..b10"
        'eq_mode': 'bands',           # full per-band control
        'power_save': 'wireless_power_save',
        'battery': 'charge_level',    # 0..255 byte, scale /255*100 for %
        'charging': 'charge_status',
        'anc': None,
        'mic_eq': 'mic_eq',
        'mic_eq_preset': 'mic_eq_preset',
        'audio_fn_button': 'audio_function_button',
        'mic_volume_uac2': True,
        'game_chat': 'game_chat_balance',
        'in_call_mix': 'in_call_audio_mix',
        'audio_prompts': 'audio_prompts',
        'serial': 'device_serial',
    },
    # V3 wired
    '0579': None,   # filled below — same as 057A minus ull/power_save/battery
    # V3 Pro
    '0577': {
        'name': 'BlackShark V3 Pro',
        'thx': 'v3pro_thx_spatial_audio',
        'ull': 'v3pro_ultra_low_latency',
        'sidetone': 'v3pro_sidetone',
        'eq': 'v3pro_headphone_eq',   # accepts single byte = slot index 0..8
        'eq_mode': 'slot-only',       # only switch between firmware slots
        'power_save': 'v3pro_power_save',
        'battery': 'charge_level',          # 0..255 byte, scale /255*100 for %
        'charging': 'charge_status',
        'anc': 'v3pro_anc',
        'mic_eq': 'mic_eq',           # shared with V3 — same 0x97 protocol
        'mic_eq_preset': 'mic_eq_preset',
        'audio_fn_button': 'audio_function_button',  # same wire bytes as V3 (cls=0xea, 1-byte arg)
        'mic_volume_uac2': True,
        'game_chat': 'game_chat_balance',
        'in_call_mix': 'in_call_audio_mix',
        'audio_prompts': 'audio_prompts',
        'serial': 'device_serial',
    },
}
# V3 wired: same as wireless but no power-save / ULL (those need the dongle's
# wireless link). Battery is irrelevant when wired.
DEVICE_CAPS['0579'] = dict(DEVICE_CAPS['057A'])
DEVICE_CAPS['0579'].update({
    'name': 'BlackShark V3 (Wired)',
    'ull': None,
    'power_save': None,
})
# V3 Pro wired: same as V3 Pro wireless minus power_save/ULL (those need the
# wireless link). Battery is still present — the headset is just charging
# whenever it's plugged in via USB-C.
DEVICE_CAPS['0576'] = dict(DEVICE_CAPS['0577'])
DEVICE_CAPS['0576'].update({
    'name': 'BlackShark V3 Pro (Wired)',
    'power_save': None,
    'ull': None,
})

EQ_FREQS = ['31Hz','63Hz','125Hz','250Hz','500Hz','1kHz','2kHz','4kHz','8kHz','16kHz']

EQ_PRESETS = {
    'Default': [ 0,  0,  0,  0,  0,  0,  0,  0,  0,  0],
    'Game':    [ 2,  2, -3, -3,  1, -1,  2,  3,  3,  3],
    'Movie':   [ 3,  3,  4,  0, -4, -4,  2,  3,  3,  3],
    'Music':   [ 6,  3,  4,  3,  0,  0,  0,  1,  3,  4],
    'Esports': [ 1,  1, -1,  0,  2,  0,  4,  4,  4, -3],
}
PRESET_IDX = {'Default': 0, 'Game': 1, 'Movie': 2, 'Music': 3, 'Esports': 4}

MIC_EQ_PRESETS = ['Default', 'Esports', 'Broadcast', 'MicBoost']
# Synthetic factory values (Synapse doesn't send mic EQ band data with preset cmds)
MIC_EQ_PRESET_BANDS = {
    'Default':   [ 0,  0,  0,  0,  0,  0,  0,  0,  0,  0],
    'Esports':   [-3, -3, -1, -1,  0,  0,  3,  4,  2,  1],
    'Broadcast': [-4,  1,  2,  0, -1,  0,  2,  3,  2, -1],
    'MicBoost':  [ 2,  2,  3,  4,  4,  4,  4,  3,  2,  2],
}
MIC_EQ_FACTORY = {i: list(v) for i, (_, v) in enumerate(MIC_EQ_PRESET_BANDS.items())}
# Factory (Razer built-in) values per profile slot
EQ_FACTORY = {PRESET_IDX[n]: list(v) for n, v in EQ_PRESETS.items()}

CONFIG_FILE = os.path.expanduser('~/.config/lynapse.json')

def _read_config():
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}

def _write_config(data):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_eq_config():
    saved = {int(k): v for k, v in _read_config().get('eq_custom', {}).items()}
    for idx in range(5):
        if idx not in saved:
            saved[idx] = list(EQ_FACTORY[idx])
    return saved

def save_eq_config(eq_custom):
    data = _read_config()
    data['eq_custom'] = {str(k): v for k, v in eq_custom.items()}
    _write_config(data)

def load_mic_eq_config():
    saved = {int(k): v for k, v in _read_config().get('mic_eq_custom', {}).items()}
    for idx in range(4):
        if idx not in saved:
            saved[idx] = list(MIC_EQ_FACTORY[idx])
    return saved

def save_mic_eq_config(mic_eq_custom):
    data = _read_config()
    data['mic_eq_custom'] = {str(k): v for k, v in mic_eq_custom.items()}
    _write_config(data)

def load_profiles():
    """Named full-settings snapshots (EQ + mic EQ + ANC + everything else),
    used so multiple people (or one person with multiple setups) can save
    and restore a complete headset configuration."""
    return _read_config().get('profiles', {})

def save_profiles(profiles):
    data = _read_config()
    data['profiles'] = profiles
    _write_config(data)

def load_default_profile():
    """Name of the profile to auto-apply on every Lynapse startup, or None
    if no default is set."""
    return _read_config().get('default_profile')

def save_default_profile(name):
    data = _read_config()
    if name:
        data['default_profile'] = name
    else:
        data.pop('default_profile', None)
    _write_config(data)

TRAY_SECTIONS = REORDERABLE_ITEMS  # every item the tray's right-click menu can show, reorder-popup default order

def load_tray_order():
    """(order, locked) for the tray quick-popup's reorderable rows. order
    is always a permutation of TRAY_SECTIONS — any saved id that's no
    longer valid (e.g. a future rename) is dropped, and any missing one is
    appended, so a corrupt/outdated save can't hide a row entirely."""
    data = _read_config().get('tray_order', {})
    saved = data.get('order', [])
    order = [s for s in saved if s in TRAY_SECTIONS]
    order += [s for s in TRAY_SECTIONS if s not in order]
    return order, bool(data.get('locked', False))

def save_tray_order(order, locked):
    data = _read_config()
    data['tray_order'] = {'order': list(order), 'locked': bool(locked)}
    _write_config(data)

def load_state(pid):
    """Per-device state cache: feature → last-written string value.
    Used as fallback when the driver returns -1 (no SET this session)."""
    return _read_config().get('state', {}).get(pid, {})

def save_state_value(pid, feature, value):
    data = _read_config()
    state = data.setdefault('state', {}).setdefault(pid, {})
    state[feature] = str(value)
    _write_config(data)

CSS = b"""
* { font-family: "Noto Sans", sans-serif; }
window, .main-box { background-color: #111111; color: #eeeeee; }
notebook > header > tabs > tab { background: #1a1a1a; color: #888; padding: 8px 18px; border: none; }
notebook > header > tabs > tab:checked { background: #1a1a1a; color: #00ff41; border-bottom: 2px solid #00ff41; }
notebook > header { background: #1a1a1a; border-bottom: 1px solid #333; }
.section-label { color: #00ff41; font-weight: bold; font-size: 11px; letter-spacing: 1px; }
.card { background: #1e1e1e; border-radius: 6px; padding: 16px; }
scale trough { background: #2a2a2a; min-height: 4px; min-width: 4px; }
scale trough highlight { background: #00ff41; }
scale slider { background: #00ff41; border-radius: 6px; }
scale.vertical trough { min-width: 4px; min-height: 4px; }
.freq-label { color: #888; font-size: 9px; }
.db-label { color: #555; font-size: 9px; }
.value-label { color: #00ff41; font-size: 10px; font-weight: bold; }
.sn-label { color: #ffffff; font-size: 15px; font-weight: bold; }
.preset-btn { background: #2a2a2a; color: #aaa; border: 1px solid #333; border-radius: 4px; padding: 6px 10px; font-size: 11px; }
.preset-btn:hover { background: #333; color: #eee; }
.preset-btn.active { background: #003a12; color: #00ff41; border-color: #00ff41; }
.toggle-on { background: #003a12; color: #00ff41; border-radius: 4px; padding: 4px 12px; border: 1px solid #00ff41; }
.toggle-off { background: #2a2a2a; color: #666; border-radius: 4px; padding: 4px 12px; border: 1px solid #444; }
.thx-btn { padding: 8px 18px; min-width: 150px; }
.status-ok { color: #00ff41; font-size: 10px; }
.status-err { color: #ff4444; font-size: 10px; }
.pwr-btn { background: #2a2a2a; color: #888; border: 1px solid #333; border-radius: 4px; padding: 6px 14px; }
.pwr-btn.active, .pwr-btn:checked { background: #003a12; color: #00ff41; border-color: #00ff41; }
.tv-battery { font-size: 28px; font-weight: bold; }
.tv-btn { background: #2a2a2a; color: #aaa; border: 1px solid #333; border-radius: 4px; padding: 6px 10px; font-size: 11px; }
.tv-btn.active { background: #003a12; color: #00ff41; border-color: #00ff41; }
.tv-step { background: #2a2a2a; color: #eee; border: 1px solid #444; border-radius: 4px; padding: 4px 14px; font-size: 14px; }
.tv-list { background: transparent; }
.tv-row { background: transparent; padding: 4px 0; }
.tv-move-btn { background: transparent; color: #888; border: none; padding: 0 6px; font-size: 9px; min-width: 0; min-height: 0; }
.tv-move-btn:hover { color: #00ff41; }
.tv-move-btn:disabled { color: #333; }
.tv-lock-btn { background: #2a2a2a; color: #aaa; border: 1px solid #333; border-radius: 4px; padding: 4px 10px; font-size: 11px; }
.tv-lock-btn.locked { color: #00ff41; border-color: #00ff41; }
"""

def sysfs_path():
    """Return (path, pid) for the first connected BlackShark variant."""
    for pid in PIDS:
        paths = glob.glob(f'{SYSFS_DIR}/0003:1532:{pid}.*')
        if paths:
            return paths[0], pid
    return None, None


class Device:
    """Capability-aware wrapper around the kernel sysfs interface.

    Hides per-device differences (V3 vs V3 Pro use different attribute names
    for the same logical feature). Use `dev.has(feature)` to gate UI, and
    `dev.write(feature, val)` / `dev.read(feature)` to talk to it.
    """
    def __init__(self, path, pid):
        self.path = path
        self.pid = pid
        self.caps = DEVICE_CAPS[pid]
        self.name = self.caps['name']
        self.is_v3_pro = (pid in ('0576', '0577'))
        self.state = load_state(pid)

    @classmethod
    def detect(cls):
        path, pid = sysfs_path()
        return cls(path, pid) if path else None

    def has(self, feature):
        return self.caps.get(feature) is not None

    def attr(self, feature):
        return self.caps.get(feature)

    def write(self, feature, value):
        attr = self.attr(feature)
        if attr is None:
            return False, f'feature {feature!r} unsupported on {self.name}'
        try:
            with open(f'{self.path}/{attr}', 'w') as f:
                f.write(str(value))
            self.state[feature] = str(value)
            save_state_value(self.pid, feature, value)
            return True, None
        except Exception as e:
            _log(f'write {self.pid} {feature}={value!r} → {e}')
            return False, str(e)

    def read(self, feature):
        attr = self.attr(feature)
        if attr is None:
            return None
        try:
            with open(f'{self.path}/{attr}') as f:
                return f.read().strip()
        except Exception:
            return None

    def get_value(self, feature, fallback=None):
        """Driver cache > JSON cache > fallback. Returns the raw string or fallback.
        '-1' from the driver means 'no SET this session' — treated as no value."""
        v = self.read(feature)
        if v is not None and v != '-1' and not v.startswith('-1 '):
            return v
        return self.state.get(feature, fallback)

    def get_value_cached(self, feature, fallback=None):
        """JSON cache > fallback only — never touches sysfs. Use during startup
        to avoid blocking on GETs that take 2s when the firmware response gate
        is tripped (V3 wireless on Linux). The 2s _refresh_status timer will
        sync from sysfs once the window is up."""
        return self.state.get(feature, fallback)


def sysfs_read(attr):
    """Legacy direct-attr read (used by code that already knows the attr name)."""
    path, _ = sysfs_path()
    if not path:
        return None
    try:
        with open(f'{path}/{attr}') as f:
            return f.read().strip()
    except Exception:
        return None

def sysfs_write(attr, value):
    """Legacy direct-attr write."""
    path, _ = sysfs_path()
    if not path:
        return False, 'device not found'
    try:
        with open(f'{path}/{attr}', 'w') as f:
            f.write(str(value))
        return True, None
    except Exception as e:
        return False, str(e)


class TrayView(Gtk.Window):
    """'Lynapse Reorder Quick Menu' — shown via the tray's right-click
    'Reorder Menu Items…' item (left-click on the tray icon just opens
    the full window, same as before this popup existed). Lists every
    reorderable item the tray's right-click menu can show (see
    _tray.REORDERABLE_ITEMS), one plain label per row — this is a
    reorder tool, not a second set of controls, so rows just show the
    item's name/current value the same way the real menu does, with no
    interactive buttons of their own. The ▲/▼ buttons here change the
    order the right-click menu itself uses, live, via
    self._ctrl._tray.set_order(). Show Full Window, Reorder, About, and
    Quit are all fixed and not part of the reorderable list, nor shown
    in this popup at all — see _tray.py's _MenuService._layout()."""

    def __init__(self, ctrl):
        super().__init__(title='Lynapse Reorder Quick Menu')
        self._ctrl    = ctrl
        self._busy    = False
        self.set_resizable(False)
        self.set_deletable(True)
        self.set_icon_name('lynapse')
        self.connect('close-request', lambda w: w.hide() or True)

        saved_order, self._locked = load_tray_order()
        # Only show rows for items this device actually supports right
        # now (item_labels() is already gated on has_anc/has_ull/etc.) —
        # a saved order may reference ids from a differently-equipped
        # device or an older version.
        available = self._ctrl._tray.item_labels()
        self._order = [sid for sid in saved_order if sid in available]
        self._order += [sid for sid in REORDERABLE_ITEMS if sid in available and sid not in self._order]

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.set_margin_top(14); outer.set_margin_bottom(14)
        outer.set_margin_start(16); outer.set_margin_end(16)
        self.set_child(outer)

        # Battery
        self._bat_lbl = Gtk.Label(label='—')
        self._bat_lbl.add_css_class('tv-battery')
        self._bat_lbl.set_halign(Gtk.Align.CENTER)
        outer.append(self._bat_lbl)

        outer.append(Gtk.Separator())

        # Lock/unlock — a fixed row that gates whether the ▲/▼ buttons
        # below do anything, so an accidental click can't reshuffle
        # things once you've got them how you want.
        lock_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        lock_row.set_halign(Gtk.Align.CENTER)
        self._lock_btn = Gtk.Button()
        self._lock_btn.add_css_class('tv-lock-btn')
        self._lock_btn.connect('clicked', self._on_lock_toggle)
        lock_row.append(self._lock_btn)
        outer.append(lock_row)
        self._sync_lock_btn()

        outer.append(Gtk.Separator())

        # Reorderable items
        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class('tv-list')
        for section_id in self._order:
            self._list.append(self._build_row(section_id))
        outer.append(self._list)
        self._sync_reorder_controls()

        outer.append(Gtk.Separator())

        save_close_btn = Gtk.Button(label='Save & Close')
        save_close_btn.connect('clicked', self._on_save_close)
        outer.append(save_close_btn)

    def _on_save_close(self, _btn):
        # The order/lock state are already saved incrementally on every
        # move and every lock toggle — this re-saves (harmless, just a
        # safety net) and closes, rather than opening the full window
        # the way the old footer button did.
        save_tray_order(self._order, self._locked)
        self._ctrl._tray.set_order(self._order)
        self.hide()

    # ── reorderable rows ─────────────────────────────────────────────────

    def _build_row(self, section_id):
        row = Gtk.ListBoxRow()
        row.add_css_class('tv-row')
        row._section_id = section_id  # tag read back on reorder to persist order

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

        # ▲/▼ move buttons — the only reorder mechanism now. An earlier
        # version also had a drag handle, but GTK/Wayland drag-and-drop
        # here was unreliable enough to crash the app, so it's gone —
        # these plain-click buttons are simple and can't do that.
        move_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        move_box.set_valign(Gtk.Align.CENTER)
        row._up_btn = Gtk.Button(label='▲')
        row._up_btn.add_css_class('tv-move-btn')
        row._up_btn.set_tooltip_text('Move up')
        row._up_btn.connect('clicked', self._on_move_click, row, -1)
        row._down_btn = Gtk.Button(label='▼')
        row._down_btn.add_css_class('tv-move-btn')
        row._down_btn.set_tooltip_text('Move down')
        row._down_btn.connect('clicked', self._on_move_click, row, +1)
        move_box.append(row._up_btn)
        move_box.append(row._down_btn)
        box.append(move_box)

        # Just the item's name/current value, same text the right-click
        # menu itself shows — this popup is for reordering, not a second
        # set of controls, so no interactive buttons/sliders here.
        row._label = Gtk.Label(label=self._ctrl._tray.item_labels().get(section_id, section_id))
        row._label.set_halign(Gtk.Align.START)
        row._label.set_hexpand(True)
        box.append(row._label)
        row.set_child(box)

        return row

    def _on_move_click(self, _btn, row, delta):
        if self._locked:
            return
        idx = row.get_index()
        # Unlike _on_drop's target-row index, this is already the desired
        # *final* index (one adjacent step), so _move_row needs no shift
        # adjustment for it — see _move_row's docstring.
        final_idx = idx + delta
        if 0 <= final_idx < self._list.observe_children().get_n_items():
            self._move_row(idx, final_idx)

    def _move_row(self, src_idx, final_idx):
        """Move the row at src_idx so it ends up at final_idx, where
        final_idx is already expressed as the row's index *after*
        removal (i.e. pass the exact target position, not a pre-removal
        index — callers with a pre-removal reference index need to
        adjust before calling, as _on_drop does)."""
        src_row = self._list.get_row_at_index(src_idx)
        self._list.remove(src_row)
        # Gtk.ListBox's row-index bookkeeping doesn't update synchronously
        # inside remove()/insert() — an insert() called immediately after
        # remove() with no main-loop turn in between can operate on a
        # stale pre-removal index list. Pump the loop so insert() (and
        # the _iter_rows() read below) sees fully-settled state.
        _pump_main_loop()
        self._list.insert(src_row, final_idx)
        _pump_main_loop()
        self._order = [r._section_id for r in self._iter_rows()]
        save_tray_order(self._order, self._locked)
        # Live-update the actual right-click menu too, not just what's
        # persisted to disk — see _tray.BatteryTray.set_order().
        self._ctrl._tray.set_order(self._order)
        self._sync_reorder_controls()

    def _iter_rows(self):
        i = 0
        while True:
            row = self._list.get_row_at_index(i)
            if row is None:
                return
            yield row
            i += 1

    def _sync_reorder_controls(self):
        """Disable move-up on the first row / move-down on the last,
        whenever locked. Call after any reorder and after a lock toggle."""
        rows = list(self._iter_rows())
        last = len(rows) - 1
        for i, r in enumerate(rows):
            r._up_btn.set_sensitive(not self._locked and i > 0)
            r._down_btn.set_sensitive(not self._locked and i < last)

    def _on_lock_toggle(self, _btn):
        self._locked = not self._locked
        save_tray_order(self._order, self._locked)
        self._sync_lock_btn()
        self._sync_reorder_controls()

    def _sync_lock_btn(self):
        self._lock_btn.set_label('🔒 Locked' if self._locked else '🔓 Unlocked — ▲▼ to reorder')
        if self._locked:
            self._lock_btn.add_css_class('locked')
        else:
            self._lock_btn.remove_css_class('locked')

    def refresh(self):
        """Battery + every row's label text, from the same item_labels()
        the right-click menu itself uses — call after anything that might
        have changed a setting (this popup has no controls of its own to
        trigger that, but the main window or the right-click menu can)."""
        pct = getattr(self._ctrl, '_last_pct', None)
        ch  = getattr(self._ctrl, '_last_charging', False)
        if pct is not None:
            self._bat_lbl.set_markup(
                f'<span foreground="{"#32c850" if ch else "#1e78ff"}">'
                f'{"⚡ " if ch else ""}{pct}%</span>')
        else:
            self._bat_lbl.set_markup('<span foreground="#888">—</span>')

        labels = self._ctrl._tray.item_labels()
        for row in self._iter_rows():
            row._label.set_text(labels.get(row._section_id, row._section_id))


def _install_app_icon():
    try:
        from lynapse._tray import render_logo
        base = os.path.expanduser('~/.local/share/icons/hicolor')
        for sz in (256, 128, 48):
            d = os.path.join(base, f'{sz}x{sz}', 'apps')
            os.makedirs(d, exist_ok=True)
            render_logo(sz).save(os.path.join(d, 'lynapse.png'))
    except Exception as e:
        _log(f'icon install: {e}')


def _window_title():
    """'Lynapse' with the installed version appended when it's determinable
    (e.g. 'Lynapse v0.1.9') — mainly so a reinstall's effect is visible at a
    glance without opening the About dialog."""
    try:
        return f'Lynapse v{_pkg_version("lynapse")}'
    except PackageNotFoundError:
        return 'Lynapse'

class LynapseWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_window_title())
        self.set_default_size(900, 620)
        self.set_resizable(False)
        self.set_icon_name('lynapse')

        self._device = Device.detect()

        self._eq_sliders = []
        self._eq_values = [0] * 10
        self._eq_apply_timer = None
        self._eq_custom = load_eq_config()
        self._mic_eq_custom = load_mic_eq_config()
        self._profiles = load_profiles()
        self._default_profile = load_default_profile()
        self._profile_switching = False
        self._connected_pid = self._device.pid if self._device else None
        self._mic_vol_slider = None
        self._ignore_slider = False

        # Seed UI state from JSON cache → defaults. Skip sysfs reads at startup
        # because some attrs (thx, ull, battery on V3 wireless) issue blocking
        # GETs that take ~2s each when the firmware response gate is tripped.
        # _refresh_status (2s timer) re-syncs from sysfs in the background.
        def _gv(feature, default):
            v = self._device.get_value_cached(feature, default) if self._device else default
            return v if v is not None else default
        def _int(feature, default):
            try: return int(_gv(feature, str(default)))
            except (ValueError, TypeError): return default

        # 'eq' must come from JSON state (driver's sysfs read returns only the
        # bands, no profile prefix — first token would be band 0, not profile).
        eq_state = (self._device.state.get('eq', '') if self._device else '').split()
        try: self._eq_target_profile = int(eq_state[0]) if eq_state else 0
        except ValueError: self._eq_target_profile = 0
        # Last active-preset value the *device* reported. Live-sync only moves
        # the green highlight when this actually changes (a real on-headset
        # switch), so clicking a profile in the GUI isn't reverted a poll later
        # by the device still reporting the previous active slot.
        self._last_eq_device_preset = -1
        # Power-save timeout in minutes. 0 = "Never sleep" (a valid choice, not
        # disabled state — the toggle was UX bloat that conflated this).
        self._pwr_timeout = _int('power_save', 30)
        self._thx_on = _gv('thx', '0') == '1'
        # Guards _live_sync's enforce() sweep (below) against racing a
        # _set_thx() toggle in flight — see that flag's use there.
        self._thx_toggling = False
        self._ull_on = _gv('ull', '1') == '1'
        anc_raw = _gv('anc', '0 1').split()
        self._anc_mode  = int(anc_raw[0]) if anc_raw and anc_raw[0].isdigit() else 0
        self._anc_level = int(anc_raw[1]) if len(anc_raw) > 1 and anc_raw[1].isdigit() else 1
        self._gc_balance     = _int('game_chat', 10)
        self._in_call_mix    = _int('in_call_mix', 0)
        self._audio_prompts  = _gv('audio_prompts', '1') == '1'
        self._sidetone_level = _int('sidetone', 0)
        self._mic_target_idx = _int('mic_eq_preset', 0)
        self._fn_mode        = _int('audio_fn_button', 1)

        # The effective default profile (explicitly starred, or — with
        # nothing starred — the sole profile if that's all there is; see
        # _effective_default_profile) overrides every value just seeded
        # above, so Lynapse starts up already showing/using it instead of
        # the raw last-used cache. _resync_all_settings (scheduled further
        # down) then pushes these to the device exactly like it already
        # does for the plain cached case — no separate device-write path
        # needed.
        effective_default = self._effective_default_profile()
        if effective_default:
            prof = self._profiles[effective_default]
            self._eq_target_profile = prof.get('eq_target_profile', self._eq_target_profile)
            if 'eq_custom' in prof:
                self._eq_custom = {int(k): v for k, v in prof['eq_custom'].items()}
            self._mic_target_idx = prof.get('mic_target_idx', self._mic_target_idx)
            if 'mic_eq_custom' in prof:
                self._mic_eq_custom = {int(k): v for k, v in prof['mic_eq_custom'].items()}
            self._anc_mode        = prof.get('anc_mode',        self._anc_mode)
            self._anc_level       = prof.get('anc_level',       self._anc_level)
            self._thx_on          = prof.get('thx_on',          self._thx_on)
            self._ull_on          = prof.get('ull_on',          self._ull_on)
            self._gc_balance      = prof.get('gc_balance',      self._gc_balance)
            self._in_call_mix     = prof.get('in_call_mix',     self._in_call_mix)
            self._audio_prompts   = prof.get('audio_prompts',   self._audio_prompts)
            self._sidetone_level  = prof.get('sidetone_level',  self._sidetone_level)
            self._fn_mode         = prof.get('fn_mode',         self._fn_mode)
            self._pwr_timeout     = prof.get('pwr_timeout',     self._pwr_timeout)

        # When True, a widget is being updated programmatically to mirror an
        # on-board (headset button/dial) change — its own change handler must
        # NOT write the value back to the device (that would be a feedback loop).
        self._syncing = False
        self._sync_inflight = False

        # status refresh
        GLib.timeout_add(2000, self._refresh_status)

        nb = Gtk.Notebook()
        nb.set_tab_pos(Gtk.PositionType.TOP)
        self.set_child(nb)

        nb.append_page(self._build_sound_tab(), Gtk.Label(label='SOUND'))
        nb.append_page(self._build_enhancement_tab(), Gtk.Label(label='ENHANCEMENT'))
        nb.append_page(self._build_mic_tab(), Gtk.Label(label='MIC'))
        nb.append_page(self._build_power_tab(), Gtk.Label(label='POWER'))

        # Battery indicator parked at the right end of the tab row (V3 Pro only).
        self._bat_widget = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._bat_widget.set_margin_end(12)
        self._bat_widget.set_valign(Gtk.Align.CENTER)
        self._sn_label = Gtk.Label(label='')
        self._sn_label.add_css_class('sn-label')
        self._sn_label.set_margin_end(16)
        self._bat_widget.append(self._sn_label)
        self._bat_widget.append(self._build_profile_switcher())
        self._bat_label = Gtk.Label(label='')
        self._bat_label.add_css_class('value-label')
        self._bat_widget.append(self._bat_label)
        nb.set_action_widget(self._bat_widget, Gtk.PackType.END)
        self._refresh_battery_widget()

        about_btn = Gtk.Button(label='About')
        about_btn.add_css_class('flat')
        about_btn.set_margin_start(12)
        about_btn.set_valign(Gtk.Align.CENTER)
        about_btn.connect('clicked', self._on_about_clicked)
        nb.set_action_widget(about_btn, Gtk.PackType.START)

        self.set_title(_window_title())
        self.connect('close-request', self._on_close_request)
        self._init_tray()
        self._refresh_status()
        # Load the cached EQ preset into sliders on startup.
        GLib.idle_add(self._load_cached_preset)
        # Push cached mic-EQ band values into the slider widgets too.
        if self._has('mic_eq'):
            GLib.idle_add(lambda: (self._load_mic_sliders(self._mic_eq_values), False)[1])
        # Resend every cached setting to the device so it matches what's
        # shown here. Delayed so it runs after _load_cached_preset has
        # populated self._eq_values and after razer_mount's udev-triggered
        # driver rebind has settled.
        GLib.timeout_add(2000, self._resync_all_settings)
        # live sync: reflect on-board (headset button) changes in the UI.
        # Polls only the driver's cached attrs (no device query → no blocking),
        # so it's safe to run frequently on the wireless link.
        GLib.timeout_add(700, self._live_sync)
        # Check GitHub for a newer release; surfaces as a tray menu item.
        GLib.timeout_add(3000, self._check_for_update)

    def _check_for_update(self):
        def _worker():
            try:
                current = _pkg_version('lynapse')
            except PackageNotFoundError:
                # Can't determine the installed version — skip rather than
                # risk a false "Update available" (a fallback like '0.0.0'
                # would always compare as older than any real release).
                return
            result = _update_check.check_for_update(current)
            if result:
                latest, url = result
                GLib.idle_add(lambda: (self._tray.set_update_available(latest, url), False)[1])
        threading.Thread(target=_worker, daemon=True).start()
        return False

    def _on_about_clicked(self, _btn=None):
        # _btn=None default: also used as the tray's about_cb (id 21 in
        # the right-click menu), called with no arguments — see
        # _init_tray() and _tray.py's Event() handler.
        try:
            ver = _pkg_version('lynapse')
        except PackageNotFoundError:
            ver = 'unknown'
        about = Gtk.AboutDialog()
        about.set_transient_for(self)
        about.set_modal(True)
        about.set_program_name('Lynapse')
        about.set_version(ver)
        about.set_logo_icon_name('lynapse')
        about.set_comments(
            'GTK4 control panel for the Razer BlackShark V3 Pro headset.\n\n'
            'Originally created by Mehm for the V3. I pulled together all the V3 Pro-'
            'specific settings and customized this into a dedicated V3 Pro control '
            'GUI, built on top of Mehm’s original V3 GUI — the V3 and V3 Pro are '
            'similar but not the same, so this build is tailored for V3 Pro and '
            'isn’t guaranteed to work on a plain V3.\n\n'
            'V3 Pro support nearly drove me insane :) — but I did all this because '
            'I love to tinker.\n\n'
            'If you’d like to say thank you for the V3 Pro GUI: Cash App $j71rivera. '
            'If not, that’s okay too!\n\n'
            'The tray icon will let you know up top when a new version is available.')
        about.set_license_type(Gtk.License.GPL_2_0)
        about.set_website(_update_check.RELEASES_URL)
        about.set_website_label('GitHub')
        about.present()

    def _has(self, feature):
        return self._device is not None and self._device.has(feature)

    def _write(self, feature, value):
        if not self._device:
            return False, 'device not found'
        return self._device.write(feature, value)

    # Back-compat alias for callers that explicitly want sync semantics.
    _write_sync = _write

    def _read(self, feature):
        return self._device.read(feature) if self._device else None

    def _load_cached_preset(self):
        # Find the preset name corresponding to the cached profile index.
        name = next((n for n, i in PRESET_IDX.items() if i == self._eq_target_profile),
                    'Default')
        self._on_preset(self._preset_btns[name], name)
        return False

    def _resync_all_settings(self, on_done=None):
        """Resend every cached/current setting to the device. Used on
        GUI/tray startup and by the manual 'Resync' action — covers cases
        where the headset was off or disconnected when the GUI/tray first
        loaded, so nothing got pushed to it then.

        Runs on a worker thread since each HID write can block the caller
        for up to ~750ms (driver's multi-step handshake)."""
        if not self._device:
            if on_done:
                GLib.idle_add(on_done, False, 'device not found')
            return False

        def _worker():
            if self._has('eq'):
                profile_idx = self._eq_target_profile
                val_str = f"{profile_idx} " + ' '.join(str(v) for v in self._eq_values)
                eq_write = (str(profile_idx)
                            if self._device.caps.get('eq_mode') == 'slot-only' else val_str)
                self._write_sync('eq', eq_write)
            if self._has('thx'):
                self._write_sync('thx', '1' if self._thx_on else '0')
            if self._has('ull'):
                self._write_sync('ull', '1' if self._ull_on else '0')
            if self._has('anc'):
                self._write_sync('anc', f'{self._anc_mode} {self._anc_level}')
            if self._has('game_chat'):
                self._write_sync('game_chat', str(self._gc_balance))
            if self._has('in_call_mix'):
                self._write_sync('in_call_mix', str(self._in_call_mix))
            if self._has('audio_prompts'):
                self._write_sync('audio_prompts', '1' if self._audio_prompts else '0')
            if self._has('sidetone'):
                self._write_sync('sidetone', str(self._sidetone_level))
            if self._has('mic_eq'):
                self._write_sync('mic_eq', ' '.join(str(v) for v in self._mic_eq_values))
            if self._has('mic_eq_preset'):
                self._write_sync('mic_eq_preset', str(self._mic_target_idx))
            if self._has('power_save'):
                self._write_sync('power_save', str(self._pwr_timeout))
            if self._has('audio_fn_button'):
                self._write_sync('audio_fn_button', str(self._fn_mode))

            if on_done:
                GLib.idle_add(on_done, True, None)

        threading.Thread(target=_worker, daemon=True).start()
        return False

    def _on_resync_clicked(self, btn=None):
        """Manual 'Resync' trigger from the GUI button or tray menu — pushes
        every cached setting to the device. Use this if the headset was off
        or disconnected when the GUI/tray first loaded."""
        if not self._device:
            self._status_label.set_text('Resync: device not found — plug in headset/dongle')
            return
        self._status_label.set_text('Resyncing settings to headset…')
        self._resync_all_settings(self._on_resync_done)

    def _on_resync_done(self, ok, err):
        if ok:
            self._status_label.set_text('Resync complete — settings resent to headset')
        else:
            self._status_label.set_text(f'Resync failed: {err}')
        return False

    # ── named profiles (full-settings snapshots) ────────────────────────────
    # Lets multiple people — or one person with multiple setups — save the
    # whole headset configuration under a name and restore it in one click.
    # Reuses the _tray_set_* setters (each already does state + device write
    # + widget update in one place) so applying a profile is just "call every
    # setter with the saved value", no new write plumbing needed.

    def _build_profile_switcher(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_margin_end(20)
        box.set_valign(Gtk.Align.CENTER)

        self._profile_combo = Gtk.ComboBoxText()
        self._profile_combo.set_size_request(130, -1)
        self._populate_profile_combo()
        self._profile_combo.connect('changed', self._on_profile_selected)
        box.append(self._profile_combo)

        self._default_toggle_switching = False
        self._default_btn = Gtk.ToggleButton(label='☆')
        self._default_btn.add_css_class('tv-btn')
        self._default_btn.connect('toggled', self._on_toggle_default)
        self._sync_default_btn()
        box.append(self._default_btn)

        save_btn = Gtk.Button(label='Save')
        save_btn.add_css_class('tv-btn')
        save_btn.set_tooltip_text('Save current settings to the selected profile')
        save_btn.connect('clicked', self._on_save_profile)
        box.append(save_btn)

        new_btn = Gtk.Button(label='+')
        new_btn.add_css_class('tv-btn')
        new_btn.set_tooltip_text('Save current settings as a new profile')
        new_btn.connect('clicked', self._on_new_profile)
        box.append(new_btn)

        return box

    def _effective_default_profile(self):
        """Which profile counts as default right now: the explicitly
        starred one (default_profile in lynapse.json) if it's still valid,
        otherwise — only while there's exactly one profile saved — that
        lone profile auto-counts, since there's nothing to disambiguate.
        The moment a second profile exists this stops; from then on
        default is only ever the explicitly-starred one (or None)."""
        if self._default_profile in self._profiles:
            return self._default_profile
        if len(self._profiles) == 1:
            return next(iter(self._profiles))
        return None

    def _populate_profile_combo(self, select=None):
        """(Re)fill the combo's rows, marking the effective default profile
        with a star. `select`: which id to leave active afterward — None
        defaults to the effective default if there is one (the startup
        case), else the blank placeholder."""
        effective_default = self._effective_default_profile()
        if select is None:
            select = effective_default or ''
        self._profile_combo.remove_all()
        self._profile_combo.append('', '— profile —')
        for name in sorted(self._profiles):
            label = f'★ {name}' if name == effective_default else name
            self._profile_combo.append(name, label)
        self._profile_switching = True
        self._profile_combo.set_active_id(select)
        self._profile_switching = False

    def _sync_default_btn(self):
        """Reflect whether the currently-selected profile is the (effective)
        default in the star toggle's pressed state and glyph, without
        re-firing its own handler. Disabled while there's only one profile
        — nothing to choose between yet, it's already the default for
        free (see _effective_default_profile)."""
        name = self._profile_combo.get_active_id()
        solo = len(self._profiles) <= 1
        is_default = bool(name) and name == self._effective_default_profile()
        self._default_toggle_switching = True
        self._default_btn.set_active(is_default)
        self._default_btn.set_label('★' if is_default else '☆')
        self._default_btn.set_sensitive(bool(name) and not solo)
        self._default_btn.set_tooltip_text(
            "Automatically the default while it's your only profile"
            if solo else
            'Set the selected profile as default — auto-applied every time Lynapse starts')
        self._default_toggle_switching = False

    def _on_toggle_default(self, btn):
        if self._default_toggle_switching:
            return
        name = self._profile_combo.get_active_id()
        if not name:
            btn.set_active(False)
            return
        self._default_profile = name if btn.get_active() else None
        save_default_profile(self._default_profile)
        self._populate_profile_combo(select=name)
        self._sync_default_btn()
        self._status_label.set_text(
            f"'{name}' set as default profile — auto-applied on startup" if btn.get_active()
            else f"'{name}' is no longer the default profile")

    def _snapshot_profile(self):
        """Capture every setting this app manages, for saving under a name."""
        return {
            'eq_target_profile': self._eq_target_profile,
            'eq_custom': {str(k): v for k, v in self._eq_custom.items()},
            'mic_target_idx': self._mic_target_idx,
            'mic_eq_custom': {str(k): v for k, v in self._mic_eq_custom.items()},
            'anc_mode': getattr(self, '_anc_mode', 0),
            'anc_level': getattr(self, '_anc_level', 1),
            'thx_on': getattr(self, '_thx_on', False),
            'ull_on': getattr(self, '_ull_on', True),
            'gc_balance': getattr(self, '_gc_balance', 10),
            'in_call_mix': getattr(self, '_in_call_mix', 0),
            'audio_prompts': getattr(self, '_audio_prompts', True),
            'sidetone_level': getattr(self, '_sidetone_level', 0),
            'fn_mode': getattr(self, '_fn_mode', 1),
            'pwr_timeout': getattr(self, '_pwr_timeout', 30),
        }

    def _apply_profile(self, name):
        """Restore a saved snapshot: push every setting it contains to the
        device (via the _tray_set_* setters) and update the GUI to match."""
        prof = self._profiles.get(name)
        if not prof:
            return
        if not self._device:
            self._status_label.set_text(f"Can't apply profile '{name}' — device not found")
            return
        self._status_label.set_text(f"Applying profile '{name}'…")

        if 'eq_custom' in prof:
            self._eq_custom = {int(k): v for k, v in prof['eq_custom'].items()}
            save_eq_config(self._eq_custom)
        if 'mic_eq_custom' in prof:
            self._mic_eq_custom = {int(k): v for k, v in prof['mic_eq_custom'].items()}
            save_mic_eq_config(self._mic_eq_custom)

        if self._has('eq'):
            self._tray_set_eq_preset(prof.get('eq_target_profile', 0))
        if self._has('mic_eq_preset'):
            self._tray_set_mic_preset(prof.get('mic_target_idx', 0))
        if self._has('anc'):
            self._tray_set_anc(prof.get('anc_mode', 0), prof.get('anc_level', 1))
        if self._has('thx'):
            self._tray_set_thx(prof.get('thx_on', False))
        if self._has('ull'):
            self._tray_set_ull(prof.get('ull_on', True))
        if self._has('game_chat'):
            self._tray_set_game_chat(prof.get('gc_balance', 10))
        if self._has('in_call_mix'):
            self._tray_set_in_call_mix(prof.get('in_call_mix', 0))
        if self._has('audio_prompts'):
            self._tray_set_audio_prompts(prof.get('audio_prompts', True))
        if self._has('sidetone'):
            self._tray_set_sidetone(prof.get('sidetone_level', 0))
        if self._has('audio_fn_button'):
            self._tray_set_fn_mode(prof.get('fn_mode', 1))
        if self._has('power_save'):
            self._tray_set_pwr_timeout(prof.get('pwr_timeout', 30))

        self._status_label.set_text(f"Profile '{name}' applied")

    def _on_profile_selected(self, combo):
        if self._profile_switching:
            return
        name = combo.get_active_id()
        self._sync_default_btn()
        if not name:
            return
        self._apply_profile(name)

    def _on_save_profile(self, btn):
        name = self._profile_combo.get_active_id()
        if not name:
            self._on_new_profile(btn)
            return
        self._profiles[name] = self._snapshot_profile()
        save_profiles(self._profiles)
        self._status_label.set_text(f"Saved current settings to profile '{name}'")

    def _on_new_profile(self, btn):
        dialog = Gtk.Window(title='New Profile', transient_for=self, modal=True)
        dialog.set_default_size(300, -1)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(16); box.set_margin_bottom(16)
        box.set_margin_start(16); box.set_margin_end(16)
        dialog.set_child(box)

        lbl = Gtk.Label(label='Profile name:')
        lbl.set_halign(Gtk.Align.START)
        box.append(lbl)

        entry = Gtk.Entry()
        box.append(entry)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_row.set_halign(Gtk.Align.END)
        cancel_btn = Gtk.Button(label='Cancel')
        cancel_btn.connect('clicked', lambda _b: dialog.destroy())
        create_btn = Gtk.Button(label='Create')

        def _create(_w=None):
            name = entry.get_text().strip()
            if not name:
                return
            self._profiles[name] = self._snapshot_profile()
            save_profiles(self._profiles)
            self._populate_profile_combo(select=name)
            self._sync_default_btn()
            self._status_label.set_text(f"Saved current settings to new profile '{name}'")
            dialog.destroy()

        create_btn.connect('clicked', _create)
        entry.connect('activate', _create)
        btn_row.append(cancel_btn); btn_row.append(create_btn)
        box.append(btn_row)

        dialog.present()
        entry.grab_focus()

    # ── live sync (on-board button changes → UI) ─────────────────────────────
    # Only cache-backed attrs are polled here. Reading these returns the value
    # the driver's raw_event cached from the headset's spontaneous pushes — no
    # HID command is sent, so it never disturbs the wireless link. thx/ull/
    # battery are intentionally excluded: reading them issues a blocking GET.
    # sidetone re-added 2026-07-21 now that razer_attr_read_v3pro_sidetone is
    # a pure cache read driver-side (was a blocking active query, same
    # anti-pattern the old charge_status bug had — fixed the same way).
    # anc re-added 2026-07-21 now that the driver caches on-board ANC-button
    # pushes too (verified on hardware: pushes arrive on class 0x12, not the
    # 0x92 SET class).
    _SYNC_FEATURES = ('sidetone', 'game_chat', 'in_call_mix', 'audio_fn_button',
                      'audio_prompts', 'mic_eq_preset', 'eq', 'anc')

    @staticmethod
    def _sync_int(raw):
        """First token of a sysfs value as int, or None if unset ('-1')/garbage."""
        if raw is None:
            return None
        tok = raw.split()
        if not tok:
            return None
        try:
            v = int(tok[0])
        except ValueError:
            return None
        return None if v < 0 else v

    def _live_sync(self):
        if not self._device or self._sync_inflight:
            return True
        self._sync_inflight = True
        dev = self._device
        def _worker():
            vals = {f: dev.read(f) for f in self._SYNC_FEATURES if dev.has(f)}
            # Piggyback THX's stray-stream sweep on this same poll (see
            # _thx.enforce()) — enable()'s own sweep only lasts ~1s at
            # toggle time, so anything that starts playing on the game
            # sink after that (a browser tab resumed later, etc.) would
            # otherwise never get moved onto the effect sink and just
            # sound identical to THX off.
            if self._thx_on and not self._thx_toggling:
                _thx.enforce()
            GLib.idle_add(self._apply_live_sync, dev, vals)
        threading.Thread(target=_worker, daemon=True).start()
        return True   # keep timer running

    def _apply_live_sync(self, dev, vals):
        self._sync_inflight = False
        if self._device is not dev:
            return False
        self._syncing = True
        try:
            v = self._sync_int(vals.get('sidetone'))
            if v is not None and getattr(self, '_sidetone_slider', None) and v != self._sidetone_level:
                self._sidetone_level = v
                self._sidetone_slider.set_value(v)

            v = self._sync_int(vals.get('game_chat'))
            if v is not None and getattr(self, '_gc_slider', None) and v != self._gc_balance:
                self._gc_balance = v
                self._gc_slider.set_value(v)

            v = self._sync_int(vals.get('in_call_mix'))
            if v is not None and v != self._in_call_mix and v in getattr(self, '_ic_btns', {}):
                self._in_call_mix = v
                for b in self._ic_btns.values():
                    b.remove_css_class('active')
                self._ic_btns[v].add_css_class('active')

            v = self._sync_int(vals.get('audio_fn_button'))
            if v is not None and v != self._fn_mode and v in getattr(self, '_fn_btns', {}):
                self._fn_mode = v
                self._fn_btns[v].set_active(True)

            v = self._sync_int(vals.get('audio_prompts'))
            if v is not None and getattr(self, '_ap_btn', None) and (v == 1) != self._audio_prompts:
                self._audio_prompts = (v == 1)
                self._ap_btn.set_label('ON' if self._audio_prompts else 'OFF')
                self._ap_btn.remove_css_class('toggle-off' if self._audio_prompts else 'toggle-on')
                self._ap_btn.add_css_class('toggle-on' if self._audio_prompts else 'toggle-off')

            v = self._sync_int(vals.get('mic_eq_preset'))
            if v is not None and v != self._mic_target_idx and v in getattr(self, '_mic_preset_btns', {}):
                self._sync_mic_preset(v)

            anc_raw = vals.get('anc')
            if anc_raw:
                tok = anc_raw.split()
                if len(tok) >= 2:
                    try:
                        m, lvl = int(tok[0]), int(tok[1])
                    except ValueError:
                        m = lvl = None
                    if m is not None and (m != self._anc_mode or lvl != self._anc_level):
                        self._sync_anc(m, lvl)

            v = self._sync_int(vals.get('eq'))
            if v is not None and v != self._last_eq_device_preset:
                # Only react to a genuine device-side change, not to the device
                # echoing back the slot we just wrote.
                self._last_eq_device_preset = v
                if v != self._eq_target_profile:
                    self._sync_eq_preset(v)
        finally:
            self._syncing = False
        return False   # one-shot (idle_add)

    def _sync_eq_preset(self, idx):
        """Mirror an on-board headphone-EQ preset switch. Highlights the preset
        and loads its bands into the sliders WITHOUT writing back to the device."""
        name = next((n for n, i in PRESET_IDX.items() if i == idx), None)
        if name is None:
            return   # custom slot with no preset button in this fork — nothing to highlight
        for b in self._preset_btns.values():
            b.remove_css_class('active')
        self._preset_btns[name].add_css_class('active')
        self._eq_target_profile = idx
        self._load_sliders(self._eq_custom.get(idx, list(EQ_FACTORY[idx])))
        self._update_tray_state()

    def _sync_anc(self, mode, level):
        """Mirror an on-board ANC button press (highlight only, no write-back —
        _anc_mode_btns/_anc_lvl_btns are plain Gtk.Button with manual CSS
        toggling, not ToggleButtons, so there's no signal to feed back into)."""
        self._anc_mode = mode
        self._anc_level = level
        if hasattr(self, '_anc_mode_btns'):
            for m, b in self._anc_mode_btns.items():
                if m == mode:
                    b.add_css_class('active')
                else:
                    b.remove_css_class('active')
        if hasattr(self, '_anc_lvl_btns'):
            for lvl, b in self._anc_lvl_btns.items():
                b.set_sensitive(mode == 1)
                if lvl == level:
                    b.add_css_class('active')
                else:
                    b.remove_css_class('active')
        self._update_tray_state()

    def _sync_mic_preset(self, idx):
        """Mirror an on-board mic-EQ preset switch (highlight + load bands)."""
        for b in self._mic_preset_btns.values():
            b.remove_css_class('active')
        self._mic_preset_btns[idx].add_css_class('active')
        self._mic_target_idx = idx
        self._load_mic_sliders(self._mic_eq_custom.get(idx, list(MIC_EQ_FACTORY[idx])))

    # ── system tray battery indicator ───────────────────────────────────────

    def _on_close_request(self, win):
        self.hide()
        return True  # suppress destroy; window lives until tray says quit

    def _init_tray(self):
        self._tray      = _BatteryTray()
        self._tray_view = None   # created lazily on first use
        self._tray.set_order(load_tray_order()[0])
        GLib.idle_add(lambda: self._tray.start(
            show_cb     = self.present,
            quit_cb     = self.get_application().quit,
            mic_cb      = self._tray_set_mic_preset,
            sidetone_cb = self._tray_set_sidetone,
            anc_cb      = self._tray_set_anc,
            ull_cb      = self._tray_set_ull,
            activate_cb = self.present,
            fn_cb       = self._tray_set_fn_mode,
            eq_cb       = self._tray_set_eq_preset,
            pwr_cb      = self._tray_set_pwr_timeout,
            gc_cb       = self._tray_set_game_chat,
            resync_cb   = self._on_resync_clicked,
            thx_cb      = self._tray_set_thx,
            reorder_cb  = self._on_reorder_clicked,
            about_cb    = self._on_about_clicked,
        ) or (_log('tray started') or False))

    def _on_reorder_clicked(self):
        """'Reorder Menu Items…' in the right-click menu: toggle the
        compact reorder popup (TrayView), created lazily on first use.
        Left-click on the tray icon goes back to opening the full window
        (activate_cb = self.present, same as before this popup existed)
        — reordering lives only behind this explicit menu item now, since
        having it on left-click read as confusing/unexpected."""
        if self._tray_view is None:
            self._tray_view = TrayView(self)
        self._tray_view.refresh()
        if self._tray_view.get_visible():
            self._tray_view.hide()
        else:
            self._tray_view.present()

    def _tray_set_mic_preset(self, idx):
        self._mic_target_idx = idx
        # Ensure mic EQ state exists even in tray-only mode (built lazily by GUI)
        if not hasattr(self, '_mic_eq_values'):
            self._mic_eq_values = [0] * 10
            self._mic_eq_apply_timer = None
        # Load stored band values for this preset, then write bands + index to device
        vals = self._mic_eq_custom.get(idx, list(MIC_EQ_FACTORY[idx]))
        self._mic_eq_values = list(vals)
        self._apply_mic_eq(idx)
        self._update_tray_state()
        if hasattr(self, '_mic_preset_btns'):
            for i, b in self._mic_preset_btns.items():
                if i == idx: b.add_css_class('active')
                else: b.remove_css_class('active')
            self._load_mic_sliders(vals)

    def _tray_set_sidetone(self, level):
        self._write('sidetone', str(level))
        self._sidetone_level = level
        self._update_tray_state()
        if hasattr(self, '_sidetone_slider'):
            self._sidetone_slider.handler_block_by_func(self._on_sidetone)
            self._sidetone_slider.set_value(level)
            self._sidetone_slider.handler_unblock_by_func(self._on_sidetone)
        if self._tray_view is not None:
            self._tray_view.refresh()

    def _tray_set_game_chat(self, val):
        self._gc_balance = val
        self._write('game_chat', str(val))
        self._update_tray_state()
        if hasattr(self, '_gc_slider'):
            self._gc_slider.handler_block_by_func(self._on_game_chat_balance)
            self._gc_slider.set_value(val)
            self._gc_slider.handler_unblock_by_func(self._on_game_chat_balance)

    def _tray_set_anc(self, mode, level):
        self._anc_mode  = mode
        self._anc_level = level
        self._write('anc', f'{mode} {level}')
        self._update_tray_state()
        if hasattr(self, '_anc_mode_btns'):
            for m, b in self._anc_mode_btns.items():
                if m == mode:
                    b.add_css_class('active')
                else:
                    b.remove_css_class('active')
        if hasattr(self, '_anc_lvl_btns'):
            for lvl, b in self._anc_lvl_btns.items():
                b.set_sensitive(mode == 1)
                if lvl == level:
                    b.add_css_class('active')
                else:
                    b.remove_css_class('active')

    def _tray_set_ull(self, on):
        self._ull_on = on
        self._write('ull', '1' if on else '0')
        self._update_tray_state()
        if hasattr(self, '_ull_btn'):
            if on:
                self._ull_btn.set_label('Turn Off')
                self._ull_btn.remove_css_class('toggle-off')
                self._ull_btn.add_css_class('toggle-on')
            else:
                self._ull_btn.set_label('Turn On')
                self._ull_btn.remove_css_class('toggle-on')
                self._ull_btn.add_css_class('toggle-off')

    def _tray_set_thx(self, on):
        self._set_thx(on)

    def _tray_set_in_call_mix(self, mode):
        self._in_call_mix = mode
        self._write('in_call_mix', str(mode))
        if hasattr(self, '_ic_btns'):
            for m, b in self._ic_btns.items():
                if m == mode: b.add_css_class('active')
                else: b.remove_css_class('active')

    def _tray_set_audio_prompts(self, on):
        self._audio_prompts = on
        self._write('audio_prompts', '1' if on else '0')
        if hasattr(self, '_ap_btn'):
            self._ap_btn.set_label('ON' if on else 'OFF')
            self._ap_btn.remove_css_class('toggle-off' if on else 'toggle-on')
            self._ap_btn.add_css_class('toggle-on' if on else 'toggle-off')

    def _tray_set_fn_mode(self, mode):
        self._fn_mode = mode
        self._write('audio_fn_button', str(mode))
        self._update_tray_state()
        if mode in self._fn_btns:
            self._fn_btns[mode].set_active(True)

    def _tray_set_eq_preset(self, idx):
        self._eq_target_profile = idx
        vals = self._eq_custom.get(idx, list(EQ_FACTORY[idx]))
        self._eq_values = list(vals)
        self._update_tray_state()
        if hasattr(self, '_preset_btns'):
            name = next((n for n, i in PRESET_IDX.items() if i == idx), 'Default')
            for n, b in self._preset_btns.items():
                if n == name: b.add_css_class('active')
                else: b.remove_css_class('active')
            self._load_sliders(vals)
        if self._eq_apply_timer:
            GLib.source_remove(self._eq_apply_timer)
        self._eq_apply_timer = GLib.timeout_add(50, self._debounced_apply)

    def _update_tray_state(self):
        self._tray.set_device_state(
            mic_preset  = self._mic_target_idx,
            sidetone    = self._sidetone_level,
            anc_mode    = getattr(self, '_anc_mode',  0),
            anc_level   = getattr(self, '_anc_level', 1),
            ull_on      = getattr(self, '_ull_on',    False),
            has_anc     = self._has('anc'),
            has_ull     = self._has('ull'),
            fn_mode     = getattr(self, '_fn_mode',   1),
            has_fn      = self._has('audio_fn_button'),
            eq_preset   = getattr(self, '_eq_target_profile', 0),
            pwr_timeout = getattr(self, '_pwr_timeout', 30),
            has_pwr     = self._has('power_save'),
            gc_balance  = getattr(self, '_gc_balance', 10),
            thx_on      = getattr(self, '_thx_on',    False),
            has_thx     = self._has('thx'),
        )

    def _update_tray(self, pct, charging):
        self._last_pct      = pct
        self._last_charging = charging
        self._tray.update(pct, charging)

    # ── status bar ──────────────────────────────────────────────────────────

    def _status_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._status_label = Gtk.Label(label='Detecting device…')
        self._status_label.add_css_class('status-ok')
        self._status_label.set_hexpand(True)
        self._status_label.set_halign(Gtk.Align.START)
        box.append(self._status_label)
        resync_btn = Gtk.Button(label='Resync to Headset')
        resync_btn.set_tooltip_text(
            'Resend all saved settings to the headset — use this if it was '
            'off or disconnected when the GUI/tray loaded.')
        resync_btn.connect('clicked', self._on_resync_clicked)
        box.append(resync_btn)
        return box

    def _refresh_status(self):
        # Re-detect on each tick — handles unplug/replug.
        new_dev = Device.detect()
        if new_dev and (self._device is None or new_dev.pid != self._device.pid
                        or new_dev.path != self._device.path):
            self._device = new_dev
        elif new_dev is None:
            self._device = None

        if self._device:
            # Show device id immediately — battery extras are appended later
            # by the async worker so we don't block the GTK main thread on
            # sysfs reads (each can take up to 500ms in the kernel; sync
            # reads here triggered GTK 'app-not-responding' on connect).
            self._status_label.set_text(
                f'{self._device.name} · {self._device.pid} · '
                f'{os.path.basename(self._device.path)}'
            )
            # Battery sysfs read triggers a 1s kernel timeout on V3 Pro wireless
            # (firmware never replies to the query; value comes via push cache).
            # Read immediately on first connect, then throttle to once per 60s.
            _now = time.monotonic()
            _last = getattr(self, '_bat_last_read', 0)
            _pid_changed = getattr(self, '_bat_last_pid', None) != self._device.pid
            if _pid_changed:
                # Different device than last tick — its serial (if any) needs
                # re-resolving rather than keeping the previous device's SN.
                self._sn_resolved = False
                if hasattr(self, '_sn_label'):
                    self._sn_label.set_text('')
            if self._device.has('battery') and not getattr(self, '_status_bat_inflight', False) and (_pid_changed or (_now - _last) >= 15):
                self._bat_last_read = _now
                self._bat_last_pid = self._device.pid
                self._status_bat_inflight = True
                dev = self._device
                # Serial never changes once resolved, so only keep asking for
                # it (piggybacked on this same throttled worker, not a
                # separate poll) until it's been read successfully once.
                need_serial = dev.has('serial') and not getattr(self, '_sn_resolved', False)
                def _bat_worker():
                    bl = dev.read('battery')
                    ch = dev.read('charging')
                    sn = dev.read('serial') if need_serial else None
                    GLib.idle_add(self._status_apply_battery, dev, bl, ch, sn)
                threading.Thread(target=_bat_worker, daemon=True).start()
            self._status_label.remove_css_class('status-err')
            self._status_label.add_css_class('status-ok')
            self._connected_pid = self._device.pid
        else:
            self._status_label.set_text('Device not found — plug in headset/dongle')
            self._status_label.remove_css_class('status-ok')
            self._status_label.add_css_class('status-err')
            self._connected_pid = None
            self._sn_resolved = False
            if hasattr(self, '_sn_label'):
                self._sn_label.set_text('')
            self._update_tray(None, False)
        self._refresh_battery_widget()
        return True   # keep timer running

    def _status_apply_battery(self, dev, bl, ch, sn=None):
        """Called from the worker thread via GLib.idle_add — runs on main."""
        self._status_bat_inflight = False
        # Bail if device disconnected/replaced while the worker was running.
        if self._device is None or self._device is not dev:
            return False
        if sn and sn != '-1' and hasattr(self, '_sn_label'):
            self._sn_label.set_text(f'Serial:    {sn}')
            self._sn_resolved = True
        # If the read failed (wireless link not up yet after hot-plug), retry
        # in 10s instead of waiting the full 60s throttle window.
        if not bl or bl == '-1':
            self._bat_last_read = time.monotonic() - 50
        extras = ''
        pct = None
        if bl and bl != '-1':
            try:
                pct = round(int(bl) / 255 * 100)
            except ValueError:
                pass

        # The driver's charge_status is updated only when the headset sends a
        # cls=0x2a interrupt, which happens on charger PLUG but not on UNPLUG
        # (headset firmware limitation). Override with battery trend so the icon
        # doesn't stay green forever after unplugging.
        charging = ch == '1'
        if pct is not None:
            prev = getattr(self, '_bat_trend_prev', None)
            prev_pid = getattr(self, '_bat_trend_pid', None)
            if prev is None or prev_pid != dev.pid:
                # No in-session baseline (just started/reconnected) — fall
                # back to the last reading saved before the app closed, so a
                # restart right after a battery change doesn't lose the trend.
                try:
                    prev = int(load_state(dev.pid).get('battery_pct'))
                except (TypeError, ValueError):
                    prev = None
            if prev is not None:
                if pct > prev:
                    charging = True    # battery rising → definitely charging
                elif pct < prev:
                    charging = False   # battery falling → definitely not charging
                # equal: trust driver's charge_status as-is
            self._bat_trend_prev = pct
            self._bat_trend_pid  = dev.pid
            save_state_value(dev.pid, 'battery_pct', pct)

        if pct is not None:
            extras = f' · battery {pct}%'
            if charging:
                extras += ' (charging)'
        self._status_label.set_text(
            f'{dev.name} · {dev.pid} · {os.path.basename(dev.path)}{extras}'
        )
        # Also push to the notebook battery widget so it doesn't need its own read loop.
        if hasattr(self, '_bat_label'):
            if pct is not None:
                suffix = ' · charging' if charging else ''
                self._bat_label.set_text(f'battery {pct}%{suffix}')
            else:
                self._bat_label.set_text('battery —')
        self._update_tray(pct, charging)
        self._update_tray_state()
        return False  # one-shot

    # ── Sound tab ───────────────────────────────────────────────────────────

    def _build_sound_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.set_margin_top(16); outer.set_margin_bottom(16)
        outer.set_margin_start(20); outer.set_margin_end(20)
        outer.add_css_class('main-box')

        # status
        status_box = self._status_widget()
        outer.append(status_box)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        hbox.set_margin_top(12)
        outer.append(hbox)

        # left: THX + presets
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.set_size_request(200, -1)
        hbox.append(left)

        # THX toggle
        thx_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        thx_card.add_css_class('card')
        thx_lbl = Gtk.Label(label='THX SPATIAL AUDIO')
        thx_lbl.add_css_class('section-label')
        thx_lbl.set_halign(Gtk.Align.START)
        thx_card.append(thx_lbl)
        thx_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._thx_btn = Gtk.Button()
        self._thx_btn.add_css_class('toggle-on' if self._thx_on else 'toggle-off')
        self._thx_btn.add_css_class('thx-btn')
        self._thx_btn_lbl = Gtk.Label()
        self._thx_btn_lbl.set_justify(Gtk.Justification.CENTER)
        self._thx_btn.set_child(self._thx_btn_lbl)
        self._set_thx_btn_markup(self._thx_on)
        self._thx_btn.connect('clicked', self._on_thx_toggle)
        thx_row.append(self._thx_btn)
        thx_card.append(thx_row)
        left.append(thx_card)

        # presets
        preset_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preset_card.add_css_class('card')
        preset_lbl = Gtk.Label(label='AUDIO EQUALIZER')
        preset_lbl.add_css_class('section-label')
        preset_lbl.set_halign(Gtk.Align.START)
        preset_card.append(preset_lbl)

        self._preset_btns = {}
        for name in EQ_PRESETS:
            btn = Gtk.Button(label=name)
            btn.add_css_class('preset-btn')
            btn.connect('clicked', self._on_preset, name)
            preset_card.append(btn)
            self._preset_btns[name] = btn
        left.append(preset_card)

        # right: EQ sliders
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_hexpand(True)
        hbox.append(right)

        eq_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        eq_card.add_css_class('card')
        eq_card.set_hexpand(True)

        eq_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        eq_h = Gtk.Label(label='EQUALIZER  (-6 dB … +6 dB)')
        eq_h.add_css_class('section-label')
        eq_h.set_halign(Gtk.Align.START)
        eq_top.append(eq_h)

        # db labels on right side
        db_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        db_col.set_valign(Gtk.Align.CENTER)
        for db in ('+6', '+3', '0', '-3', '-6'):
            l = Gtk.Label(label=db)
            l.add_css_class('db-label')
            l.set_size_request(-1, 28)
            db_col.append(l)

        eq_card.append(eq_top)

        slider_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        slider_row.set_hexpand(True)

        self._eq_sliders = []
        self._eq_val_labels = []
        for i, freq in enumerate(EQ_FREQS):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.set_hexpand(True)

            val_lbl = Gtk.Label(label='0')
            val_lbl.add_css_class('value-label')
            val_lbl.set_size_request(40, -1)

            adj = Gtk.Adjustment(value=0, lower=-6, upper=6, step_increment=1, page_increment=1)
            sl = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, adjustment=adj)
            sl.set_inverted(True)  # top = +6
            sl.set_draw_value(False)
            sl.set_size_request(40, 130)
            sl.add_mark(0, Gtk.PositionType.RIGHT, None)
            sl.connect('value-changed', self._on_eq_slider, i)

            freq_lbl = Gtk.Label(label=freq)
            freq_lbl.add_css_class('freq-label')

            col.append(val_lbl)
            col.append(sl)
            col.append(freq_lbl)
            slider_row.append(col)

            self._eq_sliders.append(sl)
            self._eq_val_labels.append(val_lbl)

        eq_card.append(slider_row)

        # reset to factory defaults button (bottom middle)
        reset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset_row.set_halign(Gtk.Align.CENTER)
        reset_row.set_margin_top(4)
        reset_btn = Gtk.Button(label='Reset to Default Values')
        reset_btn.add_css_class('preset-btn')
        reset_btn.connect('clicked', self._on_reset_to_factory)
        reset_row.append(reset_btn)
        eq_card.append(reset_row)

        right.append(eq_card)

        return outer

    def _on_thx_toggle(self, btn):
        self._set_thx(not self._thx_on)

    def _set_thx_btn_markup(self, on):
        """Two-line THX button label: bold current state on top, a small
        'Click to change' hint underneath — text color tracks whichever of
        toggle-on/toggle-off is on the button (no color set here) so it
        stays in sync with the button's own on/off styling."""
        state = 'THX Active' if on else 'Stereo Active'
        self._thx_btn_lbl.set_markup(f'<b>{state}</b>\n<small>Click to change</small>')

    def _set_thx(self, on):
        """Turn THX-style virtual surround on/off (see lynapse/_thx.py).
        Gates on _thx.components_installed() — if the required HRIR file
        isn't present, shows a status message pointing at THX_SETUP.md and
        leaves _thx_on/the device untouched. Threaded because turning on can
        block ~1-2s (a PipeWire restart) the first time or after a change.
        Shared by the button click handler, _tray_set_thx (tray menu item +
        profile restore), so all three go through the same gate — the tray
        path has no status label to read, so the "not set up" case also
        fires a desktop notification there, not just the label update."""
        if not _thx.components_installed():
            msg = ("THX Spatial Audio isn't set up — see THX_SETUP.md "
                   f"(https://github.com/{_update_check.REPO}/blob/main/THX_SETUP.md) "
                   "to install the required component")
            self._status_label.set_text(msg)
            self._notify_thx_not_setup()
            self._update_tray_state()
            return
        if hasattr(self, '_thx_btn'):
            self._thx_btn.set_sensitive(False)
        self._status_label.set_text(
            'Turning THX Spatial Audio on…' if on else 'Turning THX Spatial Audio off…')

        # Block _live_sync's enforce() sweep for the duration of this
        # toggle — enable()/disable() run their own sink-input sweep over
        # ~1s, and enforce() racing that on the 700ms live-sync timer was
        # moving streams back onto the THX sink mid-disable, making "off"
        # flicker back to sounding on. Cleared in _done() below.
        self._thx_toggling = True

        def _worker():
            ok, err = _thx.enable() if on else _thx.disable()

            def _done():
                self._thx_toggling = False
                if hasattr(self, '_thx_btn'):
                    self._thx_btn.set_sensitive(True)
                if ok:
                    self._thx_on = on
                    if hasattr(self, '_thx_btn'):
                        self._thx_btn.remove_css_class('toggle-off' if on else 'toggle-on')
                        self._thx_btn.add_css_class('toggle-on' if on else 'toggle-off')
                        self._set_thx_btn_markup(on)
                    self._write('thx', '1' if on else '0')
                    self._status_label.set_text(
                        'THX Spatial Audio on' if on else 'THX Spatial Audio off')
                else:
                    self._status_label.set_text(f'THX Spatial Audio: {err}')
                self._update_tray_state()
                return False
            GLib.idle_add(_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _notify_thx_not_setup(self):
        """Desktop notification pointing at THX_SETUP.md — fired from
        _set_thx's gate so the tray-only path (no visible status label)
        still tells the user what's missing and where to fix it."""
        try:
            n = Gio.Notification.new("THX Spatial Audio isn't set up")
            n.set_body(
                "Lynapse needs a one-time extra component for this feature. "
                f"See THX_SETUP.md at https://github.com/{_update_check.REPO} for setup instructions.")
            app = self.get_application()
            if app:
                app.send_notification('thx-not-setup', n)
        except Exception as e:
            _log(f'thx notification failed: {e}')

    def _on_preset(self, btn, name):
        # Update button highlight first and let GTK paint it before doing
        # anything else — the slider-load + sysfs-write takes long enough
        # that without the deferral the previous preset's green styling
        # appeared to linger for ~1s before the new selection lit up.
        for n, b in self._preset_btns.items():
            b.remove_css_class('active')
        btn.add_css_class('active')
        self._eq_target_profile = PRESET_IDX[name]

        def _finish_preset_change():
            vals = self._eq_custom.get(self._eq_target_profile,
                                       list(EQ_FACTORY[self._eq_target_profile]))
            self._load_sliders(vals)
            if self._eq_apply_timer:
                GLib.source_remove(self._eq_apply_timer)
            self._eq_apply_timer = GLib.timeout_add(50, self._debounced_apply)
            self._update_tray_state()
            return False

        GLib.idle_add(_finish_preset_change)

    def _load_sliders(self, vals):
        self._ignore_slider = True
        for i, sl in enumerate(self._eq_sliders):
            sl.set_value(vals[i])
            self._eq_val_labels[i].set_text(f'{vals[i]:+d}' if vals[i] != 0 else '0')
        self._ignore_slider = False
        self._eq_values = list(vals)

    def _on_reset_to_factory(self, btn):
        name = [n for n, i in PRESET_IDX.items() if i == self._eq_target_profile][0]
        self._load_sliders(list(EQ_FACTORY[self._eq_target_profile]))
        if self._eq_apply_timer:
            GLib.source_remove(self._eq_apply_timer)
        self._eq_apply_timer = GLib.timeout_add(50, self._debounced_apply)

    def _on_eq_slider(self, sl, idx):
        if self._ignore_slider:
            return
        v = int(round(sl.get_value()))
        self._eq_values[idx] = v
        self._eq_val_labels[idx].set_text(f'{v:+d}' if v != 0 else '0')
        for b in self._preset_btns.values():
            b.remove_css_class('active')
        if self._eq_apply_timer:
            GLib.source_remove(self._eq_apply_timer)
        self._eq_apply_timer = GLib.timeout_add(300, self._debounced_apply)

    def _debounced_apply(self):
        self._eq_apply_timer = None
        self._apply_eq()
        return False

    def _apply_eq(self, profile_idx=None):
        if profile_idx is None:
            profile_idx = self._eq_target_profile
        val_str = f"{profile_idx} " + ' '.join(str(v) for v in self._eq_values)
        snapshot_vals = list(self._eq_values)

        # Run the sysfs write on a worker thread — the driver's 5-step HID
        # sequence blocks the caller for ~750ms (4 inter-write msleep(150)).
        # Doing it on the GTK main thread froze paint, which made the new
        # preset's green styling appear ~1s late.
        # On V3 Pro the EQ sysfs only takes a slot index — sliders are advisory.
        write_val = (str(profile_idx) if self._device and self._device.caps.get('eq_mode') == 'slot-only'
                     else val_str)
        def _worker():
            ok, _err = self._write_sync('eq', write_val)
            def _on_done():
                if ok:
                    self._eq_custom[profile_idx] = snapshot_vals
                    save_eq_config(self._eq_custom)
                return False
            GLib.idle_add(_on_done)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    # ── Enhancement tab ─────────────────────────────────────────────────────

    def _build_enhancement_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_top(16); outer.set_margin_bottom(16)
        outer.set_margin_start(20); outer.set_margin_end(20)
        outer.add_css_class('main-box')

        # ULL — wireless only
        if self._has('ull'):
            ull_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            ull_card.add_css_class('card')
            ull_lbl = Gtk.Label(label='HYPERSPEED')
            ull_lbl.add_css_class('section-label')
            ull_lbl.set_halign(Gtk.Align.START)
            ull_card.append(ull_lbl)

            ull_desc = Gtk.Label(label='High-speed wireless audio via Razer HyperSpeed Gen-2 dongle.\nTurn On: ~10ms latency.  Turn Off: extended range & battery life.')
            ull_desc.set_wrap(True)
            ull_desc.set_halign(Gtk.Align.START)
            ull_desc.set_xalign(0)
            ull_card.append(ull_desc)

            self._ull_btn = Gtk.Button(label='Turn Off' if self._ull_on else 'Turn On')
            self._ull_btn.add_css_class('toggle-on' if self._ull_on else 'toggle-off')
            self._ull_btn.set_halign(Gtk.Align.START)
            self._ull_btn.connect('clicked', self._on_ull_toggle)
            ull_card.append(self._ull_btn)
            outer.append(ull_card)

        # ANC + Ambient — V3 Pro only
        if self._has('anc'):
            anc_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            anc_card.add_css_class('card')
            anc_lbl = Gtk.Label(label='ACTIVE NOISE CANCELLATION')
            anc_lbl.add_css_class('section-label')
            anc_lbl.set_halign(Gtk.Align.START)
            anc_card.append(anc_lbl)

            anc_mode_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self._anc_mode_btns = {}
            for mode_val, mode_name in [(0, 'Off'), (1, 'ANC'), (2, 'Ambient')]:
                b = Gtk.Button(label=mode_name)
                b.add_css_class('pwr-btn')
                if mode_val == self._anc_mode:
                    b.add_css_class('active')
                b.connect('clicked', self._on_anc_mode, mode_val)
                anc_mode_row.append(b)
                self._anc_mode_btns[mode_val] = b
            anc_card.append(anc_mode_row)

            anc_lvl_lbl = Gtk.Label(label='ANC level (1–4, ANC mode only)')
            anc_lvl_lbl.set_halign(Gtk.Align.START); anc_lvl_lbl.set_xalign(0)
            anc_card.append(anc_lvl_lbl)
            anc_lvl_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self._anc_lvl_btns = {}
            for lvl in (1, 2, 3, 4):
                b = Gtk.Button(label=str(lvl))
                b.add_css_class('pwr-btn')
                if lvl == self._anc_level:
                    b.add_css_class('active')
                b.set_sensitive(self._anc_mode == 1)
                b.connect('clicked', self._on_anc_level, lvl)
                anc_lvl_row.append(b)
                self._anc_lvl_btns[lvl] = b
            anc_card.append(anc_lvl_row)
            outer.append(anc_card)

        # Game/Chat balance
        gc_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        gc_card.add_css_class('card')
        gc_lbl = Gtk.Label(label='GAME / CHAT BALANCE')
        gc_lbl.add_css_class('section-label')
        gc_lbl.set_halign(Gtk.Align.START)
        gc_card.append(gc_lbl)
        gc_desc = Gtk.Label(label='Centered = even mix · drag toward GAME or CHAT to favor that source')
        gc_desc.set_halign(Gtk.Align.START)
        gc_desc.set_xalign(0)
        gc_card.append(gc_desc)
        gc_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        gc_row.set_valign(Gtk.Align.CENTER)
        gc_left_lbl = Gtk.Label(label='CHAT')
        gc_left_lbl.add_css_class('value-label')
        gc_right_lbl = Gtk.Label(label='GAME')
        gc_right_lbl.add_css_class('value-label')
        self._gc_slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 20, 1)
        self._gc_slider.set_value(self._gc_balance)
        self._gc_slider.set_hexpand(True)
        self._gc_slider.set_draw_value(True)
        self._gc_slider.set_format_value_func(lambda sl, val: str(int(round(val)) - 10))
        self._gc_slider.add_mark(10, Gtk.PositionType.BOTTOM, None)
        self._gc_slider.connect('value-changed', self._on_game_chat_balance)
        gc_row.append(gc_left_lbl)
        gc_row.append(self._gc_slider)
        gc_row.append(gc_right_lbl)
        gc_card.append(gc_row)
        outer.append(gc_card)

        # In-call audio mix
        ic_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ic_card.add_css_class('card')
        ic_lbl = Gtk.Label(label='IN-CALL AUDIO MIX')
        ic_lbl.add_css_class('section-label')
        ic_lbl.set_halign(Gtk.Align.START)
        ic_card.append(ic_lbl)
        ic_desc = Gtk.Label(label='What happens to 2.4 GHz game audio when a Bluetooth call comes in.')
        ic_desc.set_halign(Gtk.Align.START)
        ic_desc.set_xalign(0)
        ic_card.append(ic_desc)
        ic_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._ic_btns = {}
        for mode_val, mode_name in [(0, 'Combine 2.4 + BT'), (1, 'Lower 2.4'), (2, 'Mute 2.4')]:
            b = Gtk.Button(label=mode_name)
            b.add_css_class('pwr-btn')
            b.connect('clicked', self._on_in_call_mix, mode_val)
            ic_row.append(b)
            self._ic_btns[mode_val] = b
        self._ic_btns[self._in_call_mix].add_css_class('active')
        ic_card.append(ic_row)
        outer.append(ic_card)

        return outer

    def _on_ull_toggle(self, btn):
        self._ull_on = not self._ull_on
        if self._ull_on:
            btn.set_label('Turn Off')
            btn.remove_css_class('toggle-off')
            btn.add_css_class('toggle-on')
        else:
            btn.set_label('Turn On')
            btn.remove_css_class('toggle-on')
            btn.add_css_class('toggle-off')
        self._write('ull', '1' if self._ull_on else '0')

    def _on_game_chat_balance(self, sl):
        if self._syncing:
            return
        val = int(round(sl.get_value()))
        self._gc_balance = val
        self._write('game_chat', str(val))
        self._update_tray_state()

    def _on_in_call_mix(self, btn, mode):
        if self._syncing:
            return
        for b in self._ic_btns.values():
            b.remove_css_class('active')
        btn.add_css_class('active')
        self._write('in_call_mix', str(mode))

    def _on_anc_mode(self, btn, mode):
        for b in self._anc_mode_btns.values():
            b.remove_css_class('active')
        btn.add_css_class('active')
        self._anc_mode = mode
        # Level only applies to ANC mode — Off and Ambient ignore it.
        for lvl_btn in self._anc_lvl_btns.values():
            lvl_btn.set_sensitive(mode == 1)
        self._write('anc', f'{mode} {self._anc_level}')

    def _on_anc_level(self, btn, lvl):
        for b in self._anc_lvl_btns.values():
            b.remove_css_class('active')
        btn.add_css_class('active')
        self._anc_level = lvl
        # Only re-write if in ANC mode (level is irrelevant otherwise)
        if self._anc_mode == 1:
            self._write('anc', f'1 {lvl}')

    # ── Mic tab ─────────────────────────────────────────────────────────────

    def _build_mic_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        outer.set_margin_top(16); outer.set_margin_bottom(16)
        outer.set_margin_start(20); outer.set_margin_end(20)
        outer.add_css_class('main-box')

        # Mic volume note (UAC2 standard, not Razer-specific)
        vol_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        vol_card.add_css_class('card')
        vol_lbl = Gtk.Label(label='MICROPHONE VOLUME')
        vol_lbl.add_css_class('section-label')
        vol_lbl.set_halign(Gtk.Align.START)
        vol_card.append(vol_lbl)
        vol_note = Gtk.Label(label='Mic volume is standard USB Audio Class — control via PipeWire/pavucontrol\n'
                                    '(it\'s NOT a Razer-specific HID command).')
        vol_note.set_halign(Gtk.Align.START); vol_note.set_xalign(0)
        vol_card.append(vol_note)
        outer.append(vol_card)

        # Sidetone slider (0-15)
        st_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        st_card.add_css_class('card')
        st_lbl = Gtk.Label(label='SIDE TONE  (mic monitoring 0–15)')
        st_lbl.add_css_class('section-label')
        st_lbl.set_halign(Gtk.Align.START)
        st_card.append(st_lbl)
        st_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        st_lbl0 = Gtk.Label(label='0'); st_lbl0.add_css_class('db-label')
        st_adj = Gtk.Adjustment(value=self._sidetone_level, lower=0, upper=15, step_increment=1, page_increment=1)
        self._sidetone_slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=st_adj)
        self._sidetone_slider.set_hexpand(True)
        self._sidetone_slider.set_draw_value(True)
        self._sidetone_slider.set_digits(0)
        self._sidetone_slider.connect('value-changed', self._on_sidetone)
        st_lbl15 = Gtk.Label(label='15'); st_lbl15.add_css_class('db-label')
        st_row.append(st_lbl0); st_row.append(self._sidetone_slider); st_row.append(st_lbl15)
        st_card.append(st_row)
        outer.append(st_card)

        # Mic EQ presets — V3 only (V3 Pro driver doesn't expose mic EQ yet)
        self._mic_preset_btns = {}
        self._mic_eq_sliders = []
        self._mic_eq_val_labels = []
        self._mic_eq_values = [0] * 10
        self._mic_ignore_slider = False
        self._mic_eq_apply_timer = None
        if self._has('mic_eq_preset'):
            mp_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            mp_card.add_css_class('card')
            mp_lbl = Gtk.Label(label='MIC EQ PRESET')
            mp_lbl.add_css_class('section-label')
            mp_lbl.set_halign(Gtk.Align.START)
            mp_card.append(mp_lbl)
            mp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for i, name in enumerate(MIC_EQ_PRESETS):
                b = Gtk.Button(label=name)
                b.add_css_class('pwr-btn')
                if i == self._mic_target_idx:
                    b.add_css_class('active')
                b.connect('clicked', self._on_mic_preset, i)
                mp_row.append(b)
                self._mic_preset_btns[i] = b
            # Restore the cached preset's bands into the sliders.
            self._mic_eq_values = list(self._mic_eq_custom.get(
                self._mic_target_idx, MIC_EQ_FACTORY[self._mic_target_idx]))
            mp_card.append(mp_row)
            outer.append(mp_card)

        # Mic EQ 10-band sliders — V3 only
        if self._has('mic_eq'):
            meq_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            meq_card.add_css_class('card')
            meq_lbl = Gtk.Label(label='MIC EQUALIZER  (-6 dB … +6 dB)')
            meq_lbl.add_css_class('section-label')
            meq_lbl.set_halign(Gtk.Align.START)
            meq_card.append(meq_lbl)

            meq_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            meq_row.set_hexpand(True)
            for i, freq in enumerate(EQ_FREQS):
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                col.set_hexpand(True)
                val_lbl = Gtk.Label(label='0')
                val_lbl.add_css_class('value-label')
                adj = Gtk.Adjustment(value=0, lower=-6, upper=6, step_increment=1, page_increment=1)
                sl = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, adjustment=adj)
                sl.set_inverted(True); sl.set_draw_value(False)
                sl.set_size_request(40, 140)
                sl.add_mark(0, Gtk.PositionType.RIGHT, None)
                sl.connect('value-changed', self._on_mic_eq_slider, i)
                freq_lbl = Gtk.Label(label=freq); freq_lbl.add_css_class('freq-label')
                col.append(val_lbl); col.append(sl); col.append(freq_lbl)
                meq_row.append(col)
                self._mic_eq_sliders.append(sl)
                self._mic_eq_val_labels.append(val_lbl)
            meq_card.append(meq_row)

            reset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            reset_row.set_halign(Gtk.Align.CENTER)
            reset_row.set_margin_top(4)
            meq_reset_btn = Gtk.Button(label='Reset to Default Values')
            meq_reset_btn.add_css_class('preset-btn')
            meq_reset_btn.connect('clicked', self._on_mic_reset_to_factory)
            reset_row.append(meq_reset_btn)
            meq_card.append(reset_row)
            outer.append(meq_card)

        # Audio function button mode — V3 only
        self._fn_btns = {}
        if self._has('audio_fn_button'):
            fn_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            fn_card.add_css_class('card')
            fn_lbl = Gtk.Label(label='AUDIO FUNCTION BUTTON')
            fn_lbl.add_css_class('section-label')
            fn_lbl.set_halign(Gtk.Align.START)
            fn_card.append(fn_lbl)
            fn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            _group_leader = None
            for mode_val, mode_name in [
                (0, 'Game/Chat'),
                (1, 'Mic Sidetone'),
                (2, 'Footsteps'),
                (3, 'Bluetooth Volume'),
            ]:
                b = Gtk.ToggleButton(label=mode_name)
                b.add_css_class('pwr-btn')
                if _group_leader is None:
                    _group_leader = b
                else:
                    b.set_group(_group_leader)
                if mode_val == self._fn_mode:
                    b.set_active(True)
                b.connect('toggled', self._on_fn_button, mode_val)
                fn_row.append(b)
                self._fn_btns[mode_val] = b
            fn_card.append(fn_row)
            outer.append(fn_card)

        # Audio prompts toggle
        ap_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ap_card.add_css_class('card')
        ap_lbl = Gtk.Label(label='AUDIO PROMPTS')
        ap_lbl.add_css_class('section-label')
        ap_lbl.set_halign(Gtk.Align.START)
        ap_card.append(ap_lbl)
        ap_desc = Gtk.Label(label='Voice prompts for mic mute/unmute events.')
        ap_desc.set_halign(Gtk.Align.START)
        ap_desc.set_xalign(0)
        ap_card.append(ap_desc)
        self._ap_btn = Gtk.Button(label='ON' if self._audio_prompts else 'OFF')
        self._ap_btn.add_css_class('toggle-on' if self._audio_prompts else 'toggle-off')
        self._ap_btn.set_halign(Gtk.Align.START)
        self._ap_btn.connect('clicked', self._on_audio_prompts)
        ap_card.append(self._ap_btn)
        outer.append(ap_card)

        return outer

    def _on_audio_prompts(self, btn):
        if self._syncing:
            return
        self._audio_prompts = not self._audio_prompts
        if self._audio_prompts:
            btn.set_label('ON')
            btn.remove_css_class('toggle-off')
            btn.add_css_class('toggle-on')
        else:
            btn.set_label('OFF')
            btn.remove_css_class('toggle-on')
            btn.add_css_class('toggle-off')
        self._write('audio_prompts', '1' if self._audio_prompts else '0')

    def _on_sidetone(self, sl):
        if self._syncing:
            return
        val = int(round(sl.get_value()))
        self._sidetone_level = val
        self._write('sidetone', str(val))
        self._update_tray_state()

    def _load_mic_sliders(self, vals):
        self._mic_ignore_slider = True
        for i, sl in enumerate(self._mic_eq_sliders):
            sl.set_value(vals[i])
            self._mic_eq_val_labels[i].set_text(f'{vals[i]:+d}' if vals[i] != 0 else '0')
        self._mic_ignore_slider = False
        self._mic_eq_values = list(vals)

    def _apply_mic_eq(self, idx=None):
        if idx is None:
            idx = self._mic_target_idx
        ok, _err = self._write('mic_eq', ' '.join(str(v) for v in self._mic_eq_values))
        if ok:
            self._mic_eq_custom[idx] = list(self._mic_eq_values)
            save_mic_eq_config(self._mic_eq_custom)
        self._write('mic_eq_preset', str(idx))

    def _on_mic_preset(self, btn, idx):
        for b in self._mic_preset_btns.values():
            b.remove_css_class('active')
        btn.add_css_class('active')
        self._mic_target_idx = idx
        # load saved custom values for this slot (or factory if first time)
        vals = self._mic_eq_custom.get(idx, list(MIC_EQ_FACTORY[idx]))
        self._load_mic_sliders(vals)
        self._apply_mic_eq(idx)

    def _on_mic_eq_slider(self, sl, idx):
        if self._mic_ignore_slider:
            return
        v = int(round(sl.get_value()))
        self._mic_eq_values[idx] = v
        self._mic_eq_val_labels[idx].set_text(f'{v:+d}' if v != 0 else '0')
        if self._mic_eq_apply_timer:
            GLib.source_remove(self._mic_eq_apply_timer)
        self._mic_eq_apply_timer = GLib.timeout_add(300, self._mic_eq_debounced_apply)

    def _mic_eq_debounced_apply(self):
        self._mic_eq_apply_timer = None
        self._apply_mic_eq()
        return False

    def _on_mic_reset_to_factory(self, btn):
        self._load_mic_sliders(list(MIC_EQ_FACTORY[self._mic_target_idx]))
        self._apply_mic_eq()

    def _on_fn_button(self, btn, mode):
        if not btn.get_active():
            return
        if self._syncing:
            return
        try:
            self._fn_mode = mode
            self._write('audio_fn_button', str(mode))
            self._update_tray_state()
        except Exception:
            _log(f'_on_fn_button mode={mode}\n{traceback.format_exc()}')

    # ── Power tab ───────────────────────────────────────────────────────────

    def _build_power_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_top(16); outer.set_margin_bottom(16)
        outer.set_margin_start(20); outer.set_margin_end(20)
        outer.add_css_class('main-box')

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        outer.append(hbox)

        # left: wireless power save (only on wireless variants)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        hbox.append(left)

        self._timeout_btns = {}
        if self._has('power_save'):
            pwr_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            pwr_card.add_css_class('card')
            pwr_card.set_size_request(340, -1)

            pwr_lbl = Gtk.Label(label='WIRELESS POWER SAVING')
            pwr_lbl.add_css_class('section-label')
            pwr_lbl.set_halign(Gtk.Align.START)
            pwr_card.append(pwr_lbl)

            pwr_desc = Gtk.Label(label='Sleep after this many minutes of inactivity:')
            pwr_desc.set_halign(Gtk.Align.START)
            pwr_desc.set_xalign(0)
            pwr_card.append(pwr_desc)

            timeout_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            for t, label in [(0, 'Never'), (15, '15'), (30, '30'), (45, '45'), (60, '60')]:
                btn = Gtk.Button(label=label)
                btn.add_css_class('pwr-btn')
                if t == self._pwr_timeout:
                    btn.add_css_class('active')
                btn.connect('clicked', self._on_timeout, t)
                timeout_row.append(btn)
                self._timeout_btns[t] = btn
            pwr_card.append(timeout_row)
            left.append(pwr_card)
        else:
            wired_note = Gtk.Label(label='Wireless power saving is only available\nwith the 2.4 GHz dongle or V3 Pro.')
            wired_note.set_halign(Gtk.Align.START); wired_note.set_xalign(0)
            wired_note.add_css_class('card')
            left.append(wired_note)

        # right: LED indicator (informational only)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        hbox.append(right)

        led_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        led_card.add_css_class('card')
        led_card.set_size_request(300, -1)
        led_lbl = Gtk.Label(label='LED INDICATOR')
        led_lbl.add_css_class('section-label')
        led_lbl.set_halign(Gtk.Align.START)
        led_card.append(led_lbl)
        led_note = Gtk.Label(label='LED indicator mode (dongle) and other\npower commands not yet decoded.')
        led_note.set_halign(Gtk.Align.START)
        led_note.set_xalign(0)
        led_card.append(led_note)
        right.append(led_card)

        return outer

    def _refresh_battery_widget(self):
        """Update the battery indicator label in the notebook action area.
        Data is pushed here by _status_apply_battery so no extra sysfs read
        is needed — prevents the widget from hammering the device independently
        of the 60s throttle on the status bar battery worker."""
        if not hasattr(self, '_bat_widget'):
            return
        if not self._device:
            self._bat_label.set_text('battery —')
            return
        if not self._device.has('battery'):
            self._bat_label.set_text('battery N/A')
            return
        # Leave whatever _status_apply_battery last wrote; nothing to do here.


    def _tray_set_pwr_timeout(self, t):
        self._pwr_timeout = t
        self._write('power_save', str(t))
        self._update_tray_state()
        if hasattr(self, '_timeout_btns'):
            for tb in self._timeout_btns.values():
                tb.remove_css_class('active')
            if t in self._timeout_btns:
                self._timeout_btns[t].add_css_class('active')

    def _on_timeout(self, btn, t):
        for tb in self._timeout_btns.values():
            tb.remove_css_class('active')
        btn.add_css_class('active')
        self._pwr_timeout = t
        self._write('power_save', str(t))
        self._update_tray_state()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='com.lynapse.app')

    def do_activate(self):
        _install_app_icon()
        win = LynapseWindow(self)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def main():
    app = App()
    return app.run()


if __name__ == '__main__':
    raise SystemExit(main())
