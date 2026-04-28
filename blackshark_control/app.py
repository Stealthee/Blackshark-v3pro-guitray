#!/usr/bin/env python3
"""BlackShark V3 control panel — real-time testing GUI for the razerkraken driver fork."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk, Pango
import glob, os, subprocess, json

SYSFS_DIR = '/sys/bus/hid/drivers/razerkraken'
PIDS = ('057A', '0579')   # wireless dongle, wired

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

CONFIG_FILE = os.path.expanduser('~/.config/blackshark-control.json')

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
.preset-btn { background: #2a2a2a; color: #aaa; border: 1px solid #333; border-radius: 4px; padding: 6px 10px; font-size: 11px; }
.preset-btn:hover { background: #333; color: #eee; }
.preset-btn.active { background: #003a12; color: #00ff41; border-color: #00ff41; }
.toggle-on { background: #003a12; color: #00ff41; border-radius: 4px; padding: 4px 12px; border: 1px solid #00ff41; }
.toggle-off { background: #2a2a2a; color: #666; border-radius: 4px; padding: 4px 12px; border: 1px solid #444; }
.apply-btn { background: #00ff41; color: #000; border-radius: 4px; padding: 8px 20px; font-weight: bold; font-size: 12px; border: none; }
.apply-btn:hover { background: #00cc33; }
.status-ok { color: #00ff41; font-size: 10px; }
.status-err { color: #ff4444; font-size: 10px; }
.pwr-btn { background: #2a2a2a; color: #888; border: 1px solid #333; border-radius: 4px; padding: 6px 14px; }
.pwr-btn.active { background: #003a12; color: #00ff41; border-color: #00ff41; }
.hex-view { background: #0d0d0d; color: #00ff41; font-family: monospace; font-size: 10px; padding: 8px; border-radius: 4px; }
"""

def sysfs_path():
    for pid in PIDS:
        paths = glob.glob(f'{SYSFS_DIR}/0003:1532:{pid}.*')
        if paths:
            return paths[0], pid
    return None, None

def sysfs_read(attr):
    path, _ = sysfs_path()
    if not path:
        return None
    try:
        with open(f'{path}/{attr}') as f:
            return f.read().strip()
    except Exception:
        return None

def sysfs_write(attr, value):
    path, _ = sysfs_path()
    if not path:
        return False, 'device not found'
    try:
        with open(f'{path}/{attr}', 'w') as f:
            f.write(str(value))
        return True, None
    except Exception as e:
        return False, str(e)


class BlackSharkControl(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='BlackShark V3 Control')
        self.set_default_size(900, 620)
        self.set_resizable(False)

        self._eq_sliders = []
        self._eq_values = [0] * 10
        self._eq_target_profile = 0
        self._eq_apply_timer = None
        self._eq_custom = load_eq_config()
        self._mic_eq_custom = load_mic_eq_config()
        self._mic_target_idx = 0
        self._connected_pid = None
        self._mic_vol_slider = None
        self._pwr_timeout = 30
        self._thx_on = False
        self._ull_on = True
        self._pwr_on = True
        self._ignore_slider = False

        # status refresh
        GLib.timeout_add(2000, self._refresh_status)

        nb = Gtk.Notebook()
        nb.set_tab_pos(Gtk.PositionType.TOP)
        self.set_child(nb)

        nb.append_page(self._build_sound_tab(), Gtk.Label(label='SOUND'))
        nb.append_page(self._build_enhancement_tab(), Gtk.Label(label='ENHANCEMENT'))
        nb.append_page(self._build_mic_tab(), Gtk.Label(label='MIC'))
        nb.append_page(self._build_power_tab(), Gtk.Label(label='POWER'))

        self._refresh_status()
        # load Default preset into sliders on startup
        GLib.idle_add(self._load_default_preset)

    def _load_default_preset(self):
        self._on_preset(self._preset_btns['Default'], 'Default')
        return False

    # ── status bar ──────────────────────────────────────────────────────────

    def _status_widget(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._status_label = Gtk.Label(label='Detecting device…')
        self._status_label.add_css_class('status-ok')
        box.append(self._status_label)
        return box

    def _refresh_status(self):
        path, pid = sysfs_path()
        if path:
            mode = '2.4GHz' if pid == '057A' else 'Wired'
            self._status_label.set_text(f'Connected ({mode}) · {pid} · {os.path.basename(path)}')
            self._status_label.remove_css_class('status-err')
            self._status_label.add_css_class('status-ok')
            self._connected_pid = pid
        else:
            self._status_label.set_text('Device not found — plug in headset/dongle')
            self._status_label.remove_css_class('status-ok')
            self._status_label.add_css_class('status-err')
            self._connected_pid = None
        return True   # keep timer running

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
        self._thx_btn = Gtk.Button(label='STEREO')
        self._thx_btn.add_css_class('toggle-off')
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

        # hex preview
        self._hex_label = Gtk.Label(label='hex: (not connected)')
        self._hex_label.add_css_class('hex-view')
        self._hex_label.set_halign(Gtk.Align.START)
        self._hex_label.set_selectable(True)
        eq_card.append(self._hex_label)

        # reset to factory defaults button (bottom middle)
        reset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        reset_row.set_halign(Gtk.Align.CENTER)
        reset_row.set_margin_top(4)
        reset_btn = Gtk.Button(label='Reset to Default Values')
        reset_btn.add_css_class('preset-btn')
        reset_btn.connect('clicked', self._on_reset_to_factory)
        reset_row.append(reset_btn)
        eq_card.append(reset_row)

        # profile target selector
        prof_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        prof_row.set_margin_top(4)
        prof_lbl = Gtk.Label(label='Write to:')
        prof_lbl.add_css_class('db-label')
        prof_row.append(prof_lbl)
        self._profile_sel_btns = {}
        for name, idx in PRESET_IDX.items():
            b = Gtk.Button(label=name)
            b.add_css_class('pwr-btn')
            if idx == 0:
                b.add_css_class('active')
            b.connect('clicked', self._on_profile_sel, idx)
            prof_row.append(b)
            self._profile_sel_btns[idx] = b
        eq_card.append(prof_row)

        apply_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        apply_row.set_halign(Gtk.Align.END)
        apply_row.set_margin_top(4)
        apply_btn = Gtk.Button(label='Apply EQ')
        apply_btn.add_css_class('apply-btn')
        apply_btn.connect('clicked', self._on_eq_apply)
        apply_row.append(apply_btn)
        eq_card.append(apply_row)

        right.append(eq_card)

        return outer

    def _on_thx_toggle(self, btn):
        self._thx_on = not self._thx_on
        if self._thx_on:
            btn.set_label('THX SPATIAL AUDIO')
            btn.remove_css_class('toggle-off')
            btn.add_css_class('toggle-on')
        else:
            btn.set_label('STEREO')
            btn.remove_css_class('toggle-on')
            btn.add_css_class('toggle-off')
        sysfs_write('thx_spatial_audio', '1' if self._thx_on else '0')

    def _on_preset(self, btn, name):
        # Update button highlight first and let GTK paint it before doing
        # anything else — the slider-load + sysfs-write takes long enough
        # that without the deferral the previous preset's green styling
        # appeared to linger for ~1s before the new selection lit up.
        for n, b in self._preset_btns.items():
            b.remove_css_class('active')
        btn.add_css_class('active')
        self._eq_target_profile = PRESET_IDX[name]
        self._update_profile_selector()

        def _finish_preset_change():
            vals = self._eq_custom.get(self._eq_target_profile,
                                       list(EQ_FACTORY[self._eq_target_profile]))
            self._load_sliders(vals)
            if self._eq_apply_timer:
                GLib.source_remove(self._eq_apply_timer)
            self._eq_apply_timer = GLib.timeout_add(50, self._debounced_apply)
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
        self._update_hex_preview()
        if self._eq_apply_timer:
            GLib.source_remove(self._eq_apply_timer)
        self._eq_apply_timer = GLib.timeout_add(300, self._debounced_apply)

    def _debounced_apply(self):
        self._eq_apply_timer = None
        self._apply_eq()
        return False

    def _update_hex_preview(self, status=None):
        buf = bytearray(64)
        buf[0] = 0x02
        buf[2] = 0x60
        buf[6] = 0x0f
        buf[9] = 0x80 if getattr(self, '_connected_pid', None) != '0579' else 0x00
        buf[10] = 0x95
        buf[12] = 0x0b
        buf[13] = self._eq_target_profile
        for i, v in enumerate(self._eq_values):
            buf[14 + i] = (0x80 | (-v)) if v < 0 else v
        crc = 0
        for b in buf[:62]:
            crc ^= b
        buf[62] = crc
        hex_str = ' '.join(f'{b:02x}' for b in buf[:24]) + ' ...'
        sysfs_cmd = f"{self._eq_target_profile} " + ' '.join(str(v) for v in self._eq_values)
        profile_names = ['Default', 'Game', 'Movie', 'Music', 'Esports']
        pname = profile_names[self._eq_target_profile]
        lines = [
            f'0x95 cmd (profile={self._eq_target_profile} {pname}): {hex_str}',
            f'bands[0..9]: {" ".join(str(v) for v in self._eq_values)}',
            f'sysfs: "{sysfs_cmd}"',
        ]
        if status:
            lines.append(status)
        self._hex_label.set_text('\n'.join(lines))

    def _update_profile_selector(self):
        for idx, btn in self._profile_sel_btns.items():
            if idx == self._eq_target_profile:
                btn.add_css_class('active')
            else:
                btn.remove_css_class('active')

    def _on_profile_sel(self, btn, idx):
        # treat exactly like clicking the matching preset button
        name = [n for n, i in PRESET_IDX.items() if i == idx][0]
        self._on_preset(self._preset_btns[name], name)

    def _apply_eq(self, profile_idx=None):
        if profile_idx is None:
            profile_idx = self._eq_target_profile
        val_str = f"{profile_idx} " + ' '.join(str(v) for v in self._eq_values)
        snapshot_vals = list(self._eq_values)
        profile_names = ['Default', 'Game', 'Movie', 'Music', 'Esports']
        pname = profile_names[profile_idx]

        # Run the sysfs write on a worker thread — the driver's 5-step HID
        # sequence blocks the caller for ~750ms (4 inter-write msleep(150)).
        # Doing it on the GTK main thread froze paint, which made the new
        # preset's green styling appear ~1s late.
        def _worker():
            ok, err = sysfs_write('headphone_eq', val_str)
            def _on_done():
                if ok:
                    self._eq_custom[profile_idx] = snapshot_vals
                    save_eq_config(self._eq_custom)
                    status = f'→ Written to slot {profile_idx} ({pname})'
                else:
                    status = f'→ Write failed: {err}'
                self._update_hex_preview(status=status)
                return False
            GLib.idle_add(_on_done)

        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def _on_eq_apply(self, btn):
        self._apply_eq()

    # ── Enhancement tab ─────────────────────────────────────────────────────

    def _build_enhancement_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_top(16); outer.set_margin_bottom(16)
        outer.set_margin_start(20); outer.set_margin_end(20)
        outer.add_css_class('main-box')

        # ULL
        ull_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ull_card.add_css_class('card')
        ull_lbl = Gtk.Label(label='ULTRA-LOW LATENCY')
        ull_lbl.add_css_class('section-label')
        ull_lbl.set_halign(Gtk.Align.START)
        ull_card.append(ull_lbl)

        ull_desc = Gtk.Label(label='High-speed wireless audio via Razer HyperSpeed Gen-2 dongle.\nEnabled: ~10ms latency.  Disabled: extended range & battery life.')
        ull_desc.set_wrap(True)
        ull_desc.set_halign(Gtk.Align.START)
        ull_desc.set_xalign(0)
        ull_card.append(ull_desc)

        self._ull_btn = Gtk.Button(label='ON')
        self._ull_btn.add_css_class('toggle-on')
        self._ull_btn.set_halign(Gtk.Align.START)
        self._ull_btn.connect('clicked', self._on_ull_toggle)
        ull_card.append(self._ull_btn)
        outer.append(ull_card)

        # note about unknown commands
        note_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        note_card.add_css_class('card')
        note_lbl = Gtk.Label(label='AUDIO ENHANCEMENT')
        note_lbl.add_css_class('section-label')
        note_lbl.set_halign(Gtk.Align.START)
        note_card.append(note_lbl)
        note_desc = Gtk.Label(label='Sound Normalization / Bass Boost / Voice Clarity\nnot yet decoded from captures.')
        note_desc.set_halign(Gtk.Align.START)
        note_desc.set_xalign(0)
        note_card.append(note_desc)
        outer.append(note_card)

        return outer

    def _on_ull_toggle(self, btn):
        self._ull_on = not self._ull_on
        if self._ull_on:
            btn.set_label('ON')
            btn.remove_css_class('toggle-off')
            btn.add_css_class('toggle-on')
        else:
            btn.set_label('OFF')
            btn.remove_css_class('toggle-on')
            btn.add_css_class('toggle-off')
        sysfs_write('ultra_low_latency', '1' if self._ull_on else '0')

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
        st_adj = Gtk.Adjustment(value=0, lower=0, upper=15, step_increment=1, page_increment=1)
        self._sidetone_slider = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=st_adj)
        self._sidetone_slider.set_hexpand(True)
        self._sidetone_slider.set_draw_value(True)
        self._sidetone_slider.set_digits(0)
        self._sidetone_slider.connect('value-changed', self._on_sidetone)
        st_lbl15 = Gtk.Label(label='15'); st_lbl15.add_css_class('db-label')
        st_row.append(st_lbl0); st_row.append(self._sidetone_slider); st_row.append(st_lbl15)
        st_card.append(st_row)
        outer.append(st_card)

        # Mic EQ presets
        mp_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        mp_card.add_css_class('card')
        mp_lbl = Gtk.Label(label='MIC EQ PRESET')
        mp_lbl.add_css_class('section-label')
        mp_lbl.set_halign(Gtk.Align.START)
        mp_card.append(mp_lbl)
        mp_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._mic_preset_btns = {}
        for i, name in enumerate(MIC_EQ_PRESETS):
            b = Gtk.Button(label=name)
            b.add_css_class('pwr-btn')
            if i == 0:
                b.add_css_class('active')
            b.connect('clicked', self._on_mic_preset, i)
            mp_row.append(b)
            self._mic_preset_btns[i] = b
        mp_card.append(mp_row)
        outer.append(mp_card)

        # Mic EQ 10-band sliders
        meq_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        meq_card.add_css_class('card')
        meq_lbl = Gtk.Label(label='MIC EQUALIZER  (-6 dB … +6 dB)')
        meq_lbl.add_css_class('section-label')
        meq_lbl.set_halign(Gtk.Align.START)
        meq_card.append(meq_lbl)

        meq_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        meq_row.set_hexpand(True)
        self._mic_eq_sliders = []
        self._mic_eq_val_labels = []
        self._mic_eq_values = [0] * 10
        self._mic_ignore_slider = False
        self._mic_eq_apply_timer = None
        for i, freq in enumerate(EQ_FREQS):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            col.set_hexpand(True)
            val_lbl = Gtk.Label(label='0')
            val_lbl.add_css_class('value-label')
            adj = Gtk.Adjustment(value=0, lower=-6, upper=6, step_increment=1, page_increment=1)
            sl = Gtk.Scale(orientation=Gtk.Orientation.VERTICAL, adjustment=adj)
            sl.set_inverted(True); sl.set_draw_value(False)
            sl.set_size_request(40, 100)
            sl.add_mark(0, Gtk.PositionType.RIGHT, None)
            sl.connect('value-changed', self._on_mic_eq_slider, i)
            freq_lbl = Gtk.Label(label=freq); freq_lbl.add_css_class('freq-label')
            col.append(val_lbl); col.append(sl); col.append(freq_lbl)
            meq_row.append(col)
            self._mic_eq_sliders.append(sl)
            self._mic_eq_val_labels.append(val_lbl)
        meq_card.append(meq_row)

        # Reset to default values for mic EQ (mirrors headphone EQ behavior)
        meq_reset_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        meq_reset_row.set_halign(Gtk.Align.CENTER)
        meq_reset_row.set_margin_top(4)
        meq_reset_btn = Gtk.Button(label='Reset to Default Values')
        meq_reset_btn.add_css_class('preset-btn')
        meq_reset_btn.connect('clicked', self._on_mic_reset_to_factory)
        meq_reset_row.append(meq_reset_btn)
        meq_card.append(meq_reset_row)

        outer.append(meq_card)

        # Audio function button mode (footsteps vs sidetone save)
        fn_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        fn_card.add_css_class('card')
        fn_lbl = Gtk.Label(label='AUDIO FUNCTION BUTTON')
        fn_lbl.add_css_class('section-label')
        fn_lbl.set_halign(Gtk.Align.START)
        fn_card.append(fn_lbl)
        fn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._fn_btns = {}
        for mode_val, mode_name in [(1, 'Sidetone Save'), (2, 'Footsteps Scaling')]:
            b = Gtk.Button(label=mode_name)
            b.add_css_class('pwr-btn')
            b.connect('clicked', self._on_fn_button, mode_val)
            fn_row.append(b)
            self._fn_btns[mode_val] = b
        fn_card.append(fn_row)
        outer.append(fn_card)

        return outer

    def _on_sidetone(self, sl):
        val = int(round(sl.get_value()))
        sysfs_write('sidetone', str(val))

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
        ok, err = sysfs_write('mic_eq', ' '.join(str(v) for v in self._mic_eq_values))
        if ok:
            self._mic_eq_custom[idx] = list(self._mic_eq_values)
            save_mic_eq_config(self._mic_eq_custom)
        sysfs_write('mic_eq_preset', str(idx))

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
        for b in self._fn_btns.values():
            b.remove_css_class('active')
        btn.add_css_class('active')
        sysfs_write('audio_function_button', str(mode))

    # ── Power tab ───────────────────────────────────────────────────────────

    def _build_power_tab(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_margin_top(16); outer.set_margin_bottom(16)
        outer.set_margin_start(20); outer.set_margin_end(20)
        outer.add_css_class('main-box')

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        outer.append(hbox)

        # left: wireless power save
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        hbox.append(left)

        pwr_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        pwr_card.add_css_class('card')
        pwr_card.set_size_request(340, -1)

        pwr_lbl = Gtk.Label(label='WIRELESS POWER SAVING')
        pwr_lbl.add_css_class('section-label')
        pwr_lbl.set_halign(Gtk.Align.START)
        pwr_card.append(pwr_lbl)

        self._pwr_toggle_btn = Gtk.Button(label='ON')
        self._pwr_toggle_btn.add_css_class('toggle-on')
        self._pwr_toggle_btn.set_halign(Gtk.Align.START)
        self._pwr_toggle_btn.connect('clicked', self._on_pwr_toggle)
        pwr_card.append(self._pwr_toggle_btn)

        pwr_desc = Gtk.Label(label='Device will turn off after (mins) of inactivity:')
        pwr_desc.set_halign(Gtk.Align.START)
        pwr_desc.set_xalign(0)
        pwr_card.append(pwr_desc)

        timeout_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._timeout_btns = {}
        for t in (15, 30, 45, 60):
            btn = Gtk.Button(label=str(t))
            btn.add_css_class('pwr-btn')
            if t == 30:
                btn.add_css_class('active')
            btn.connect('clicked', self._on_timeout, t)
            timeout_row.append(btn)
            self._timeout_btns[t] = btn
        pwr_card.append(timeout_row)
        left.append(pwr_card)

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

    def _on_pwr_toggle(self, btn):
        self._pwr_on = not self._pwr_on
        if self._pwr_on:
            btn.set_label('ON')
            btn.remove_css_class('toggle-off')
            btn.add_css_class('toggle-on')
            sysfs_write('wireless_power_save', str(self._pwr_timeout))
        else:
            btn.set_label('OFF')
            btn.remove_css_class('toggle-on')
            btn.add_css_class('toggle-off')
            sysfs_write('wireless_power_save', '0')

    def _on_timeout(self, btn, t):
        for tb in self._timeout_btns.values():
            tb.remove_css_class('active')
        btn.add_css_class('active')
        self._pwr_timeout = t
        if self._pwr_on:
            sysfs_write('wireless_power_save', str(t))


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='com.blackshark.control')

    def do_activate(self):
        win = BlackSharkControl(self)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            win.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        win.present()


def main():
    app = App()
    return app.run()


if __name__ == '__main__':
    raise SystemExit(main())
