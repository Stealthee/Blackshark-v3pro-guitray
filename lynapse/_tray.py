"""KDE StatusNotifierItem tray icon — battery level + quick-settings menu."""

import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

from lynapse._update_check import RELEASES_URL

_LOG       = '/tmp/bs-tray.log'
_FONT_PATH = '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'

EQ_PRESETS       = ['Default', 'Game', 'Movie', 'Music', 'Esports']
MIC_PRESETS      = ['Default', 'Esports', 'Broadcast', 'MicBoost']
SIDETONE_LEVELS  = [(i, str(i)) for i in range(16)]
FN_MODES         = ['Game/Chat', 'Mic Sidetone', 'Footsteps']
PWR_TIMEOUTS     = [(0, 'Never'), (15, '15 min'), (30, '30 min'), (45, '45 min'), (60, '60 min')]
# ANC: (id_offset, mode, level, label)
ANC_OPTIONS = [
    (0, 0, 1, 'Off'),
    (1, 1, 1, 'ANC: Low'),
    (2, 1, 2, 'ANC: Med'),
    (3, 1, 3, 'ANC: High'),
    (4, 1, 4, 'ANC: Max'),
    (5, 2, 1, 'Ambient'),
]

def _anc_cur_label(mode, level):
    for _, m, l, label in ANC_OPTIONS:
        if m == mode and (m != 1 or l == level):
            return label
    return '?'

GAME_CHAT_LEVELS       = list(range(0, 21, 2))
SIDETONE_LEVELS_VALUES = [v for v, _ in SIDETONE_LEVELS]

def _gc_label(n):
    if n < 0:
        return f'C {-n}'
    if n > 0:
        return f'G {n}'
    return '0'

def _log(msg):
    try:
        with open(_LOG, 'a') as f:
            import time
            f.write(f'[{time.strftime("%H:%M:%S")}] {msg}\n')
    except Exception:
        pass

def _open_url(url):
    try:
        subprocess.Popen(['xdg-open', url])
    except Exception as e:
        _log(f'open_url failed: {e}')
    return False

try:
    import dbus, dbus.service, dbus.mainloop.glib
    from gi.repository import GLib
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    _DBUS_OK = True
    _log('dbus mainloop registered at import time')
except Exception as _e:
    _DBUS_OK = False
    _log(f'dbus import/setup failed: {_e}')


# ── icon rendering ────────────────────────────────────────────────────────────

def _render(pct, charging):
    SIZE = 256
    lw   = 16

    if pct is None:
        color, text = (127, 140, 141, 255), '?'
    elif charging:
        color, text = (39, 174, 96, 255),   str(pct)
    elif pct < 20:
        color, text = (231, 76, 60, 255),   str(pct)
    elif pct < 40:
        color, text = (243, 156, 18, 255),  str(pct)
    else:
        color, text = (61, 174, 233, 255),  str(pct)

    img  = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── headset geometry ──────────────────────────────────────────────────
    ax0, ax1 = 30, 226                          # left / right x of arms
    arc_bbox = [ax0, 6, ax1, 118]
    arc_cy   = (arc_bbox[1] + arc_bbox[3]) // 2  # 62 — arm/arc join point
    arm_bot  = 162                              # bottom of arm stems
    ear_r    = 22                               # ear-cup radius
    ear_cy   = arm_bot + ear_r                  # 184

    # headband arc — top half of ellipse
    draw.arc(arc_bbox, 180, 360, fill=color, width=lw)
    # arm stems
    draw.line([(ax0, arc_cy), (ax0, arm_bot)], fill=color, width=lw)
    draw.line([(ax1, arc_cy), (ax1, arm_bot)], fill=color, width=lw)
    # ear cups
    draw.ellipse([ax0-ear_r, ear_cy-ear_r, ax0+ear_r, ear_cy+ear_r],
                 outline=color, width=lw)
    draw.ellipse([ax1-ear_r, ear_cy-ear_r, ax1+ear_r, ear_cy+ear_r],
                 outline=color, width=lw)

    # ── L-shaped gaming boom mic from left ear cup ────────────────────────
    bm_lw    = lw
    bm_vert_x = ax0                       # 30
    bm_vert_y0 = ear_cy + ear_r - 2       # 204 — bottom of left ear cup
    bm_vert_y1 = SIZE - 42                # 214 — elbow of L
    bm_horiz_x1 = SIZE // 2 + 10         # 138 — tip of boom
    # vertical drop
    draw.line([(bm_vert_x, bm_vert_y0), (bm_vert_x, bm_vert_y1)],
              fill=color, width=bm_lw)
    # horizontal sweep toward mouth
    draw.line([(bm_vert_x, bm_vert_y1), (bm_horiz_x1, bm_vert_y1)],
              fill=color, width=bm_lw)
    # smooth elbow corner
    elbow_r = bm_lw // 2
    draw.ellipse([bm_vert_x - elbow_r, bm_vert_y1 - elbow_r,
                  bm_vert_x + elbow_r, bm_vert_y1 + elbow_r], fill=color)
    # mic capsule at tip
    cap_r = 16
    draw.ellipse([bm_horiz_x1 - cap_r, bm_vert_y1 - cap_r,
                  bm_horiz_x1 + cap_r, bm_vert_y1 + cap_r], fill=color)

    # ── auto-size text to fit between the arm stems ───────────────────────
    inner_w = ax1 - ax0 - lw * 2   # ~172 px
    inner_h = arm_bot - arc_cy - lw  # ~88 px

    font, bb_f, fs_f = ImageFont.load_default(), (0, 0, 8, 12), 12
    for fs in range(120, 14, -2):
        try:
            f = ImageFont.truetype(_FONT_PATH, fs)
        except Exception:
            break
        bb = draw.textbbox((0, 0), text, font=f)
        if bb[2]-bb[0] <= inner_w and bb[3]-bb[1] <= inner_h:
            font, bb_f, fs_f = f, bb, fs
            break

    tw, th = bb_f[2]-bb_f[0], bb_f[3]-bb_f[1]
    tx = (SIZE - tw) // 2 - bb_f[0]
    ty = arc_cy + lw // 2 + (inner_h - th) // 2 - bb_f[1]
    draw.text((tx, ty), text, fill=color, font=font,
              stroke_width=max(1, fs_f // 50), stroke_fill=color)
    return img

def render_logo(size=256):
    """Dark rounded-square app icon with gaming-headset silhouette."""
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── background: dark rounded square ──────────────────────────────────
    r = size // 5
    draw.rounded_rectangle([0, 0, size-1, size-1], radius=r,
                            fill=(18, 18, 30, 255))

    # Subtle inner glow ring
    glow = (40, 120, 200, 60)
    draw.rounded_rectangle([2, 2, size-3, size-3], radius=r-1,
                            outline=glow, width=3)

    # ── headset: scaled into padded sub-region ────────────────────────────
    pad = int(size * 0.09)
    eff = size - pad * 2
    s   = eff / 256
    lw  = max(4, int(14 * s))
    color = (90, 200, 250, 255)   # bright cyan-blue on dark bg

    def X(v): return pad + int(v * s)
    def Y(v): return pad + int(v * s)

    ax0, ax1   = X(30), X(226)
    ab_t, ab_b = Y(6),  Y(118)
    arc_cy     = (ab_t + ab_b) // 2
    arm_bot    = Y(162)
    ear_r      = max(4, int(22 * s))
    ear_cy     = arm_bot + ear_r

    draw.arc([ax0, ab_t, ax1, ab_b], 180, 360, fill=color, width=lw)
    draw.line([(ax0, arc_cy), (ax0, arm_bot)], fill=color, width=lw)
    draw.line([(ax1, arc_cy), (ax1, arm_bot)], fill=color, width=lw)
    draw.ellipse([ax0-ear_r, ear_cy-ear_r, ax0+ear_r, ear_cy+ear_r],
                 outline=color, width=lw)
    draw.ellipse([ax1-ear_r, ear_cy-ear_r, ax1+ear_r, ear_cy+ear_r],
                 outline=color, width=lw)

    bv_y0 = ear_cy + ear_r - 2
    bv_y1 = Y(214)
    bh_x1 = X(138)
    draw.line([(ax0, bv_y0), (ax0, bv_y1)],   fill=color, width=lw)
    draw.line([(ax0, bv_y1), (bh_x1, bv_y1)], fill=color, width=lw)
    er = lw // 2
    draw.ellipse([ax0-er, bv_y1-er, ax0+er, bv_y1+er], fill=color)
    cap = max(4, int(16 * s))
    draw.ellipse([bh_x1-cap, bv_y1-cap, bh_x1+cap, bv_y1+cap], fill=color)

    return img

def _to_argb_bytes(img):
    data = []
    for r, g, b, a in img.getdata():
        data += [dbus.Byte(a), dbus.Byte(r), dbus.Byte(g), dbus.Byte(b)]
    return dbus.Array(data, signature='y')


# ── dbusmenu ──────────────────────────────────────────────────────────────────

class _MenuService(dbus.service.Object):
    IFACE = 'com.canonical.dbusmenu'

    def __init__(self, conn, path, tray):
        super().__init__(conn, path)
        self._tray = tray
        self._rev  = 1

    # ── helpers ──────────────────────────────────────────────────────────────

    def _item(self, id_, label, enabled=True):
        return dbus.Struct((
            dbus.Int32(id_),
            dbus.Dictionary({'label': dbus.String(label),
                             'enabled': dbus.Boolean(enabled),
                             'visible': dbus.Boolean(True)}, signature='sv'),
            dbus.Array([], signature='v'),
        ), signature=None)

    def _sep(self, id_):
        return dbus.Struct((
            dbus.Int32(id_),
            dbus.Dictionary({'type': dbus.String('separator')}, signature='sv'),
            dbus.Array([], signature='v'),
        ), signature=None)

    def _submenu(self, id_, label, children):
        return dbus.Struct((
            dbus.Int32(id_),
            dbus.Dictionary({'label': dbus.String(label),
                             'children-display': dbus.String('submenu'),
                             'enabled': dbus.Boolean(True),
                             'visible': dbus.Boolean(True)}, signature='sv'),
            dbus.Array(children, signature='v'),
        ), signature=None)

    # ── layout ────────────────────────────────────────────────────────────────

    def _layout(self):
        t = self._tray

        def _sel(label, active):
            return f'● {label}' if active else label

        # Sound EQ submenu — bullet on current preset
        eq_items = [self._item(110+i, _sel(name, i == t._eq_preset))
                    for i, name in enumerate(EQ_PRESETS)]
        cur_eq = EQ_PRESETS[t._eq_preset] if 0 <= t._eq_preset < len(EQ_PRESETS) else '?'
        eq_menu = self._submenu(104, f'Sound EQ: {cur_eq}', eq_items)

        # Mic EQ submenu — bullet on current preset
        mic_items = [self._item(30+i, _sel(name, i == t._mic_preset))
                     for i, name in enumerate(MIC_PRESETS)]
        cur_mic = MIC_PRESETS[t._mic_preset] if 0 <= t._mic_preset < len(MIC_PRESETS) else '?'
        mic_menu = self._submenu(100, f'Mic EQ: {cur_mic}', mic_items)

        # Sidetone submenu — bullet on current level (0–15)
        st_items = [self._item(40+i, _sel(str(val), val == t._sidetone))
                    for i, (val, _) in enumerate(SIDETONE_LEVELS)]
        st_menu = self._submenu(101, f'Sidetone: {t._sidetone}', st_items)

        extra = []

        # ANC submenu — only when device supports it
        if t._has_anc:
            anc_items = [
                self._item(60+off, _sel(label, t._anc_mode == m and (m != 1 or t._anc_level == lvl)))
                for off, m, lvl, label in ANC_OPTIONS
            ]
            cur_anc = _anc_cur_label(t._anc_mode, t._anc_level)
            extra.append(self._submenu(102, f'ANC: {cur_anc}', anc_items))

        # HyperSpeed — plain item; label shows the action clicking will perform
        if t._has_ull:
            extra.append(self._item(70, f'Turn {"Off" if t._ull_on else "On"} HyperSpeed'))

        # Audio function button — only when device supports it
        if t._has_fn:
            fn_items = [self._item(80+i, _sel(name, i == t._fn_mode))
                        for i, name in enumerate(FN_MODES)]
            cur_fn = FN_MODES[t._fn_mode] if 0 <= t._fn_mode < len(FN_MODES) else '?'
            extra.append(self._submenu(103, f'Fn: {cur_fn}', fn_items))

        # Scroll-wheel submenu — reflects whatever the Fn mode currently
        # routes the headset's scroll wheel to.
        if t._has_fn and t._fn_mode == 1:
            sc_items = [self._item(141+i, _sel(str(val), val == t._sidetone))
                        for i, val in enumerate(SIDETONE_LEVELS_VALUES)]
            extra.append(self._submenu(106, f'Sidetone Scroll: {t._sidetone}', sc_items))
        else:
            gc_items = [self._item(130+i, _sel(_gc_label(val - 10), val == t._gc_balance))
                        for i, val in enumerate(GAME_CHAT_LEVELS)]
            extra.append(self._submenu(106, f'Game-Chat Scroll: {_gc_label(t._gc_balance - 10)}', gc_items))

        # Wireless power saving — only when device supports it
        if t._has_pwr:
            pwr_items = [self._item(120+i, _sel(label, t._pwr_timeout == val))
                         for i, (val, label) in enumerate(PWR_TIMEOUTS)]
            cur_pwr = next((label for val, label in PWR_TIMEOUTS if val == t._pwr_timeout), '?')
            extra.append(self._submenu(105, f'Sleep: {cur_pwr}', pwr_items))

        if extra:
            extra = [self._sep(16)] + extra

        update = []
        if t._update_version:
            update = [self._item(19, f'Update available: v{t._update_version}'), self._sep(12)]

        children = dbus.Array(update + [
            self._item(10, 'Show Full Window'),
            self._sep(11),
            eq_menu,
            mic_menu,
            st_menu,
        ] + extra + [
            self._sep(15),
            self._item(17, 'Resync Settings to Headset'),
            self._sep(18),
            self._item(21, 'About'),
            self._item(20, 'Quit'),
        ], signature='v')

        root = dbus.Struct((
            dbus.Int32(0),
            dbus.Dictionary({'children-display': dbus.String('submenu')}, signature='sv'),
            children,
        ), signature=None)
        return (dbus.UInt32(self._rev), root)

    # ── dbusmenu interface ────────────────────────────────────────────────────

    @dbus.service.method(IFACE, in_signature='iias', out_signature='u(ia{sv}av)')
    def GetLayout(self, parentId, recursionDepth, propertyNames):
        rev, root = self._layout()
        node = self._find_node(root, int(parentId)) if int(parentId) != 0 else root
        return (rev, node if node is not None else root)

    def _find_node(self, node, target_id):
        if int(node[0]) == target_id:
            return node
        for child in node[2]:
            r = self._find_node(child, target_id)
            if r is not None:
                return r
        return None

    @dbus.service.method(IFACE, in_signature='aias', out_signature='a(ia{sv})')
    def GetGroupProperties(self, ids, propertyNames):
        return dbus.Array([], signature='(ia{sv})')

    @dbus.service.method(IFACE, in_signature='is', out_signature='v')
    def GetProperty(self, id, name):
        return dbus.String('')

    @dbus.service.method(IFACE, in_signature='isvu', out_signature='')
    def Event(self, id, eventId, data, timestamp):
        if eventId != 'clicked':
            return
        t = self._tray
        if   id == 10 and t._show_cb:
            GLib.idle_add(t._show_cb)
        elif id == 20 and t._quit_cb:
            GLib.idle_add(t._quit_cb)
        elif 30 <= id <= 33 and t._mic_cb:
            t._mic_preset = id - 30
            self._bump()
            GLib.idle_add(t._mic_cb, id - 30)
        elif 40 <= id <= 55 and t._sidetone_cb:
            t._sidetone = id - 40
            self._bump()
            GLib.idle_add(t._sidetone_cb, t._sidetone)
        elif 130 <= id <= 140 and t._gc_cb:
            val = GAME_CHAT_LEVELS[id - 130]
            t._gc_balance = val
            self._bump()
            GLib.idle_add(t._gc_cb, val)
        elif 141 <= id <= 156 and t._sidetone_cb:
            t._sidetone = SIDETONE_LEVELS_VALUES[id - 141]
            self._bump()
            GLib.idle_add(t._sidetone_cb, t._sidetone)
        elif 60 <= id <= 65 and t._anc_cb:
            _, m, lvl, _ = ANC_OPTIONS[id - 60]
            t._anc_mode, t._anc_level = m, lvl
            self._bump()
            GLib.idle_add(t._anc_cb, m, lvl)
        elif id == 70 and t._ull_cb:
            t._ull_on = not t._ull_on
            self._bump()
            GLib.idle_add(t._ull_cb, t._ull_on)
        elif 80 <= id <= 82 and t._fn_cb:
            t._fn_mode = int(id) - 80
            self._bump()
            GLib.idle_add(t._fn_cb, int(id) - 80)
        elif 110 <= id <= 114 and t._eq_cb:
            t._eq_preset = id - 110
            self._bump()
            GLib.idle_add(t._eq_cb, id - 110)
        elif 120 <= id <= 124 and t._pwr_cb:
            val, _ = PWR_TIMEOUTS[id - 120]
            t._pwr_timeout = val
            self._bump()
            GLib.idle_add(t._pwr_cb, val)
        elif id == 17 and t._resync_cb:
            GLib.idle_add(t._resync_cb)
        elif id == 19 and t._update_url:
            GLib.idle_add(_open_url, t._update_url)
        elif id == 21:
            GLib.idle_add(_open_url, RELEASES_URL)

    @dbus.service.method(IFACE, in_signature='a(isvu)', out_signature='ai')
    def EventGroup(self, events):
        for id_, eventId, data, ts in events:
            self.Event(id_, eventId, data, ts)
        return dbus.Array([], signature='i')

    @dbus.service.method(IFACE, in_signature='i', out_signature='b')
    def AboutToShow(self, id):
        # Return True so KDE always re-fetches the submenu layout before showing it.
        # This prevents stale selection state from being displayed.
        return dbus.Boolean(True)

    @dbus.service.method(IFACE, in_signature='ai', out_signature='aiai')
    def AboutToShowGroup(self, ids):
        return dbus.Array([], signature='i'), dbus.Array([], signature='i')

    @dbus.service.signal(IFACE, signature='uu')
    def LayoutUpdated(self, revision, parent): pass

    @dbus.service.signal(IFACE, signature='iu')
    def ItemActivationRequested(self, id, timestamp): pass

    def _bump(self):
        self._rev += 1
        self.LayoutUpdated(self._rev, 0)


# ── StatusNotifierItem ────────────────────────────────────────────────────────

class _SNIService(dbus.service.Object):

    def __init__(self, conn, path, tray):
        super().__init__(conn, path)
        self._tray     = tray
        self._pct      = None
        self._charging = False

    @dbus.service.method('org.freedesktop.DBus.Properties',
                         in_signature='ss', out_signature='v')
    def Get(self, iface, prop):
        return self._props().get(prop, dbus.String(''))

    @dbus.service.method('org.freedesktop.DBus.Properties',
                         in_signature='s', out_signature='a{sv}')
    def GetAll(self, iface):
        return self._props()

    def _props(self):
        if self._pct is not None:
            suffix = ' (charging)' if self._charging else ''
            tip = f'BlackShark: {self._pct}%{suffix}'
        else:
            tip = 'BlackShark: no device'
        img    = _render(self._pct, self._charging)
        W, H   = img.size
        argb   = _to_argb_bytes(img)
        pixmap = dbus.Array(
            [dbus.Struct((dbus.Int32(W), dbus.Int32(H), argb), signature=None)],
            signature='(iiay)')
        return {
            'Category':            dbus.String('Hardware'),
            'Id':                  dbus.String('blackshark-battery'),
            'Title':               dbus.String(tip),
            'Status':              dbus.String('Active'),
            'IconName':            dbus.String(''),
            'IconPixmap':          pixmap,
            'OverlayIconName':     dbus.String(''),
            'OverlayIconPixmap':   dbus.Array([], signature='(iiay)'),
            'AttentionIconName':   dbus.String(''),
            'AttentionIconPixmap': dbus.Array([], signature='(iiay)'),
            'ToolTip': dbus.Struct(
                ('', dbus.Array([], signature='(iiay)'), tip, ''), signature=None),
            'ItemIsMenu': dbus.Boolean(True),
            'Menu':       dbus.ObjectPath('/StatusNotifierMenu'),
        }

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewIcon(self): pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewTitle(self): pass

    @dbus.service.signal('org.kde.StatusNotifierItem')
    def NewToolTip(self): pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii')
    def Activate(self, x, y):
        t = self._tray
        if t._activate_cb:
            GLib.idle_add(t._activate_cb)

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii')
    def SecondaryActivate(self, x, y): pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='ii')
    def ContextMenu(self, x, y): pass

    @dbus.service.method('org.kde.StatusNotifierItem', in_signature='is')
    def Scroll(self, delta, orientation): pass

    def update(self, pct, charging):
        changed = (pct != self._pct or charging != self._charging)
        self._pct, self._charging = pct, charging
        if changed:
            self.NewIcon(); self.NewTitle(); self.NewToolTip()


# ── public handle ─────────────────────────────────────────────────────────────

class BatteryTray:

    def __init__(self):
        self._sni            = None
        self._menu           = None
        self._show_cb        = None
        self._quit_cb        = None
        self._mic_cb         = None
        self._sidetone_cb    = None
        self._anc_cb         = None
        self._ull_cb         = None
        self._activate_cb    = None
        self._mic_preset     = 0
        self._sidetone       = 0
        self._anc_mode       = 0
        self._anc_level      = 1
        self._ull_on         = False
        self._has_anc        = False
        self._has_ull        = False
        self._fn_cb          = None
        self._fn_mode        = 1
        self._has_fn         = False
        self._eq_cb          = None
        self._eq_preset      = 0
        self._pwr_cb         = None
        self._pwr_timeout    = 30
        self._has_pwr        = False
        self._gc_cb          = None
        self._gc_balance     = 10
        self._resync_cb      = None
        self._tray_view_mode = False
        self._update_version = None
        self._update_url     = None

    def start(self, show_cb=None, quit_cb=None, mic_cb=None,
              sidetone_cb=None, anc_cb=None, ull_cb=None, activate_cb=None, fn_cb=None,
              eq_cb=None, pwr_cb=None, gc_cb=None, resync_cb=None):
        self._show_cb     = show_cb
        self._quit_cb     = quit_cb
        self._mic_cb      = mic_cb
        self._sidetone_cb = sidetone_cb
        self._anc_cb      = anc_cb
        self._ull_cb      = ull_cb
        self._activate_cb = activate_cb
        self._fn_cb       = fn_cb
        self._eq_cb       = eq_cb
        self._pwr_cb      = pwr_cb
        self._gc_cb       = gc_cb
        self._resync_cb   = resync_cb
        if not _DBUS_OK:
            return False
        try:
            self._bus      = dbus.SessionBus()
            self._bus_name = dbus.service.BusName('org.kde.StatusNotifierItem-lynapse', self._bus)
            self._sni      = _SNIService(self._bus, '/StatusNotifierItem', self)
            self._menu     = _MenuService(self._bus, '/StatusNotifierMenu', self)
            watcher = self._bus.get_object(
                'org.kde.StatusNotifierWatcher', '/StatusNotifierWatcher')
            watcher.RegisterStatusNotifierItem(
                self._bus_name.get_name(),
                dbus_interface='org.kde.StatusNotifierWatcher')
            _log('tray started')
        except Exception as e:
            _log(f'start failed: {type(e).__name__}: {e}')
            self._sni = None
        return False

    def set_device_state(self, mic_preset, sidetone, anc_mode=0, anc_level=1,
                         ull_on=False, has_anc=False, has_ull=False, fn_mode=1, has_fn=False,
                         eq_preset=0, pwr_timeout=30, has_pwr=False, gc_balance=10):
        changed = (mic_preset != self._mic_preset or sidetone != self._sidetone
                   or anc_mode != self._anc_mode or anc_level != self._anc_level
                   or ull_on != self._ull_on or has_anc != self._has_anc
                   or has_ull != self._has_ull or fn_mode != self._fn_mode
                   or has_fn != self._has_fn or eq_preset != self._eq_preset
                   or pwr_timeout != self._pwr_timeout or has_pwr != self._has_pwr
                   or gc_balance != self._gc_balance)
        self._mic_preset  = mic_preset
        self._sidetone    = sidetone
        self._anc_mode    = anc_mode
        self._anc_level   = anc_level
        self._ull_on      = ull_on
        self._has_anc     = has_anc
        self._has_ull     = has_ull
        self._fn_mode     = fn_mode
        self._has_fn      = has_fn
        self._eq_preset   = eq_preset
        self._pwr_timeout = pwr_timeout
        self._has_pwr     = has_pwr
        self._gc_balance  = gc_balance
        if changed and self._menu:
            self._menu._bump()

    def set_update_available(self, version, url):
        changed = (version != self._update_version)
        self._update_version = version
        self._update_url     = url
        if changed and self._menu:
            self._menu._bump()

    def update(self, pct, charging):
        if self._sni:
            try:
                self._sni.update(pct, charging)
            except Exception as e:
                _log(f'update failed: {e}')
