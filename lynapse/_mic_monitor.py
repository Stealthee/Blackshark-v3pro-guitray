"""Software mic monitoring (loopback), for actually hearing the mic live —
including on-device mic EQ/preset changes — through your own headphones.

Why this exists instead of just using hardware Sidetone: confirmed
2026-08-17 that Sidetone taps the mic signal *before* the on-device mic EQ
DSP stage on this headset — switching mic EQ presets makes zero audible
difference through Sidetone, even though it's a large, real, measurable
change in what actually reaches the PC (see MEMORY: mic EQ investigation).
This routes through PipeWire instead, from the same digital capture stream
the mic EQ audibly affects (confirmed by direct recording), at the cost of
some added software latency Sidetone doesn't have.

Uses `pactl load-module module-loopback`, NOT the config-file + PipeWire-
restart approach `_thx.py` uses — module-loopback is a live, instant,
individually loadable/unloadable module, so there's no reason to pay for a
daemon restart (which would also glitch any other running audio, e.g. a
Discord call) just to flip this on or off.

Latency: `latency_msec` below is an upper bound PipeWire-pulse honors, not
a floor — actual latency follows PipeWire's own quantum (typically a few
ms). Kept low specifically to stay well under the range where Delayed
Auditory Feedback (hearing your own voice with a lag disrupts speech)
becomes noticeable, generally cited starting around 50-200ms.
"""

import subprocess

# Tags the loopback's sink-input/source-output so it can be found again
# without persisting any module id of our own — survives a Lynapse restart
# (or a crash) cleanly, and never leaves an orphaned module.
TAG = 'lynapse-mic-monitor'


def _pactl(*args, timeout=5):
    try:
        r = subprocess.run(['pactl', *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout, r.stderr
    except Exception as e:
        return False, '', str(e)


def _sources():
    ok, out, _ = _pactl('list', 'sources', 'short')
    if not ok:
        return []
    return [f[1] for f in (l.split('\t') for l in out.splitlines()) if len(f) >= 2]


def find_mic_source():
    """The BlackShark's mic input source — wired or wireless, mono-chat or
    mono-mic, whichever naming this connection mode actually exposes."""
    cands = [s for s in _sources() if 'Razer_Inc_BlackShark' in s and '.monitor' not in s]
    if not cands:
        return None
    for want in ('mono-chat', 'mono-mic', 'mono'):
        for s in cands:
            if want in s:
                return s
    return cands[0]


def _default_sink():
    ok, out, _ = _pactl('get-default-sink')
    return out.strip() if ok else None


def _module_id():
    """Our loopback module's id if currently loaded, else None."""
    ok, out, _ = _pactl('list', 'modules', 'short')
    if not ok:
        return None
    for line in out.splitlines():
        f = line.split('\t')
        if len(f) >= 3 and f[1] == 'module-loopback' and TAG in f[2]:
            return f[0]
    return None


def _sink_input_id_for_module(mid):
    """The sink-input id module-loopback created, by matching Owner Module —
    the short listing doesn't carry properties, so this needs the verbose
    one."""
    ok, out, _ = _pactl('list', 'sink-inputs')
    if not ok:
        return None
    cur_id = None
    for raw in out.splitlines():
        line = raw.strip()
        if line.startswith('Sink Input #'):
            cur_id = line.split('#', 1)[1]
        elif line.startswith('Owner Module:') and cur_id is not None:
            if line.split(':', 1)[1].strip() == str(mid):
                return cur_id
    return None


def is_enabled():
    return _module_id() is not None


def enable(volume_pct=50, latency_ms=10):
    """Start the loopback (or just re-apply volume if it's already
    running). Returns (ok, err)."""
    mid = _module_id()
    if mid is not None:
        return set_volume(volume_pct)

    src = find_mic_source()
    if not src:
        return False, 'BlackShark mic input not found (is it connected?)'
    sink = _default_sink()
    if not sink:
        return False, 'no default output sink found'

    ok, out, err = _pactl(
        'load-module', 'module-loopback',
        f'source={src}', f'sink={sink}',
        f'latency_msec={latency_ms}',
        f'sink_input_properties=media.name={TAG}',
        f'source_output_properties=media.name={TAG}',
    )
    if not ok or not out.strip():
        return False, (err.strip() or 'pactl load-module failed')

    set_volume(volume_pct)
    return True, None


def disable():
    mid = _module_id()
    if mid:
        _pactl('unload-module', mid)
    return True, None


def set_volume(pct):
    """Adjust the loopback stream's volume. No-op-ish (ok=True) if the
    loopback isn't currently enabled — nothing to adjust, not an error."""
    mid = _module_id()
    if mid is None:
        return True, None
    sid = _sink_input_id_for_module(mid)
    if not sid:
        return False, 'loopback stream not found yet'
    pct = max(0, min(150, int(pct)))
    ok, _, err = _pactl('set-sink-input-volume', sid, f'{pct}%')
    return ok, (None if ok else err.strip())
