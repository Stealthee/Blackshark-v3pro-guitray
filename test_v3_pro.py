#!/usr/bin/env python3
"""
BlackShark V3 Pro driver test tool.

Walks through every sysfs attribute exposed by the razerkraken driver fork
(branch blackshark-v3-pro at github.com/mehmetbayoglu/openrazer) and asks
the tester to confirm whether the headset reacted as expected.

Run as your normal user (the openrazer udev rule should grant group access)
or with sudo if writes return permission denied:

    python3 test_v3_pro.py

Reports a pass/fail summary at the end. Paste the output into the PR thread.
"""

import glob
import os
import sys
import time

PID = '0577'
SYSFS_GLOB = f'/sys/bus/hid/drivers/razerkraken/0003:1532:{PID.upper()}.*'


def find_device():
    matches = glob.glob(SYSFS_GLOB)
    if not matches:
        print(f"ERROR: no V3 Pro device found at {SYSFS_GLOB}")
        print("Check: is the dongle plugged in? Is the headset on?")
        print("       lsusb | grep 1532:0577")
        print("       lsmod | grep razerkraken     (and that it's our fork's build)")
        sys.exit(1)
    if len(matches) > 1:
        print(f"WARNING: multiple matches, using first: {matches[0]}")
    return matches[0]


def read_attr(path, name):
    try:
        with open(os.path.join(path, name)) as f:
            return f.read().strip()
    except Exception as e:
        return f"<read error: {e}>"


def write_attr(path, name, value):
    try:
        with open(os.path.join(path, name), 'w') as f:
            f.write(str(value))
        return True, None
    except Exception as e:
        return False, str(e)


def confirm(prompt):
    """Ask y/n. Returns True/False/None (skip)."""
    while True:
        ans = input(f"  -> {prompt} [y/n/s=skip]: ").strip().lower()
        if ans in ('y', 'yes'):
            return True
        if ans in ('n', 'no'):
            return False
        if ans in ('s', 'skip', ''):
            return None


def section(title):
    print()
    print('=' * 60)
    print(f"  {title}")
    print('=' * 60)


def main():
    print("BlackShark V3 Pro driver test tool")
    print("Make sure the headset is on and you can hear audio through it.")
    print()
    path = find_device()
    print(f"Device: {path}")
    print(f"Attributes available:")
    for f in sorted(os.listdir(path)):
        if f.startswith('v3pro_') or f in ('device_type', 'device_serial', 'firmware_version'):
            print(f"  {f}")

    results = {}

    # ---- read-only checks ----
    section("1. Device identification (read-only)")
    dt = read_attr(path, 'device_type')
    print(f"  device_type:     {dt}")
    ds = read_attr(path, 'device_serial')
    print(f"  device_serial:   {ds}")
    fv = read_attr(path, 'firmware_version')
    print(f"  firmware_version: {fv}")
    results['device_type'] = dt == 'Razer BlackShark V3 Pro'

    # ---- battery ----
    section("2. Battery level (read)")
    lvl = read_attr(path, 'v3pro_battery_level')
    chg = read_attr(path, 'v3pro_charging')
    print(f"  v3pro_battery_level: {lvl}")
    print(f"  v3pro_charging:      {chg}")
    print("  (Compare to what Synapse / Razer status indicator shows on the headset.)")
    r = confirm("Is the battery level reasonable (0-100 and matches actual)?")
    results['battery_level'] = r

    # ---- sidetone ----
    section("3. Sidetone")
    print("  Sidetone = your own mic fed back into your headphones so you can")
    print("  hear yourself talking. Speak into the mic during the test.")
    print()
    print("  Setting sidetone to 0 (off)...")
    ok, err = write_attr(path, 'v3pro_sidetone', 0)
    if not ok:
        print(f"  WRITE FAILED: {err}")
        results['sidetone_off'] = False
    else:
        time.sleep(1)
        r = confirm("Speak into mic — do you NOT hear yourself in the headphones?")
        results['sidetone_off'] = r

    print()
    print("  Setting sidetone to 15 (max)...")
    ok, err = write_attr(path, 'v3pro_sidetone', 15)
    if not ok:
        print(f"  WRITE FAILED: {err}")
        results['sidetone_max'] = False
    else:
        time.sleep(1)
        r = confirm("Speak into mic — do you NOW hear yourself loudly in the headphones?")
        results['sidetone_max'] = r

    # readback
    rb = read_attr(path, 'v3pro_sidetone')
    print(f"  Read-back: v3pro_sidetone = {rb}")
    results['sidetone_readback'] = rb in ('15',)

    write_attr(path, 'v3pro_sidetone', 0)  # restore

    # ---- THX ----
    section("4. THX Spatial Audio")
    print("  Play any stereo audio (music or a YouTube video).")
    print()
    print("  Setting THX OFF (stereo)...")
    write_attr(path, 'v3pro_thx_spatial_audio', 0)
    time.sleep(1)
    print("  Setting THX ON (spatial)...")
    ok, err = write_attr(path, 'v3pro_thx_spatial_audio', 1)
    if not ok:
        print(f"  WRITE FAILED: {err}")
        results['thx'] = False
    else:
        time.sleep(1)
        r = confirm("Did the audio noticeably change (more spacious / virtualized)?")
        results['thx'] = r
        write_attr(path, 'v3pro_thx_spatial_audio', 0)

    # ---- ANC ----
    section("5. Active Noise Cancellation")
    print("  Wear the headset somewhere with some ambient noise (or play noise).")
    print()
    print("  Setting ANC OFF...")
    write_attr(path, 'v3pro_anc', '0 1')
    time.sleep(1)
    print("  Setting ANC ON, level 4 (max)...")
    ok, err = write_attr(path, 'v3pro_anc', '1 4')
    if not ok:
        print(f"  WRITE FAILED: {err}")
        results['anc_on'] = False
    else:
        time.sleep(1)
        r = confirm("Did ambient noise drop noticeably?")
        results['anc_on'] = r

    print()
    print("  Setting ANC ON, level 1 (min)...")
    write_attr(path, 'v3pro_anc', '1 1')
    time.sleep(1)
    r = confirm("Is ANC noticeably weaker now than at level 4?")
    results['anc_level'] = r
    write_attr(path, 'v3pro_anc', '0 1')  # restore

    # ---- Power save ----
    section("6. Power save timeout")
    print("  This sets the auto-shutoff timer. We can't wait 15 min in this test,")
    print("  so we just verify the writes are accepted.")
    for minutes in (0, 15, 30, 45, 60):
        ok, err = write_attr(path, 'v3pro_power_save', minutes)
        status = 'OK' if ok else f'FAIL: {err}'
        print(f"  v3pro_power_save = {minutes:2d} -> {status}")
    r = confirm("Did all writes succeed without error?")
    results['power_save'] = r

    # ---- EQ ----
    section("7. Headphone EQ presets")
    print("  Play some music. Each preset should sound noticeably different.")
    print("  Slot 0 = Flat, slots 1-4 are captured presets, 5-8 are placeholders.")
    print()
    eq_results = {}
    for slot in range(5):
        labels = ['Flat (0)', 'Preset 1', 'Preset 2 (movie?)', 'Preset 3 (music?)', 'Preset 4 (esports?)']
        print(f"  Setting EQ slot {slot} ({labels[slot]})...")
        ok, err = write_attr(path, 'v3pro_headphone_eq', slot)
        if not ok:
            print(f"    WRITE FAILED: {err}")
            eq_results[slot] = False
            continue
        time.sleep(2)
        if slot == 0:
            r = confirm("Audio sounds neutral/flat?")
        else:
            r = confirm(f"Audio sounds different from slot {slot-1}?")
        eq_results[slot] = r
    results['eq_presets'] = all(v is True for v in eq_results.values())
    write_attr(path, 'v3pro_headphone_eq', 0)  # restore flat

    # ---- summary ----
    section("Summary")
    pass_ = sum(1 for v in results.values() if v is True)
    fail = sum(1 for v in results.values() if v is False)
    skip = sum(1 for v in results.values() if v is None)
    for k, v in results.items():
        mark = 'PASS' if v is True else ('FAIL' if v is False else 'SKIP')
        print(f"  [{mark}] {k}")
    print()
    print(f"  {pass_} passed, {fail} failed, {skip} skipped")
    print()
    print("Paste the output above into the PR thread to help validate the driver.")
    print("Branch: https://github.com/mehmetbayoglu/openrazer/tree/blackshark-v3-pro")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
