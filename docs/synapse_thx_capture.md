# Synapse THX Spatial Audio — USB capture findings (2026-08-13)

Investigated whether Windows Synapse sends the BlackShark V3 Pro any HID
command when THX Spatial Audio is toggled that Lynapse might be missing.
Short version: **no evidence of one** — beyond what `openrazer`'s
`razerkraken` driver already implements via `v3pro_thx_spatial_audio` — and
independent evidence strongly suggests THX on Windows is implemented as a
software audio service, not a device-driven effect.

## Setup

- Headset: BlackShark V3 Pro, 2.4GHz dongle mode, confirmed as
  `VID_1532&PID_0577` in Device Manager (composite device with a HID
  vendor-defined control interface on `MI_05`, plus separate Chat/Game USB
  audio interfaces on `MI_00`/`MI_03`).
- Capture tooling: Wireshark + USBPcap, both already installed on the test
  machine. Captured via `tshark -i \\.\USBPcap1` / `\\.\USBPcap2` (only two
  root hubs present on this machine) run elevated.
- Method: a keypress-gated PowerShell script started both hub captures,
  then waited for an explicit Enter press immediately after each real
  Synapse action, so click timing is tied to a logged wall-clock timestamp
  rather than a fixed timer. (An earlier fixed-timer attempt was discarded
  — the user's actual clicks didn't line up with the timer, so it isn't
  used as evidence below.)
- Device identification within the capture: address 10 on USBPcap1 is the
  BlackShark composite device — confirmed by its enumeration descriptor
  burst at capture start (18-byte then 405-byte `GET_DESCRIPTOR` responses,
  matching a multi-interface composite device) and, when audio was
  playing, a steady 2880-byte isochronous OUT transfer every 10ms (the
  outbound PCM stream itself).

## Clean capture timeline

| Event | t (relative to capture start) |
|---|---|
| Capture started | 0s |
| Baseline idle confirmed | 16.5s |
| **THX toggled ON** (keypress logged) | 28.8s |
| Post-ON hold confirmed | 38.1s |
| **THX toggled OFF** (keypress logged) | 46.2s |
| Capture stopped | 50.7s |

## Result

- **At the ON toggle (±3s window):** zero traffic of any kind — control,
  interrupt, or isochronous — on any endpoint of the BlackShark device.
  Complete silence.
- **At the OFF toggle:** a ~1-second burst of paired 72-byte control +
  64-byte interrupt exchanges at a steady ~45ms cadence, starting about
  1.7s before the logged OFF keypress.
- **However**, an identical burst also appears at t≈21.4s — roughly 23
  seconds before the one near the OFF toggle (21.4 + 23.1 ≈ 44.5), and
  nowhere near either logged toggle action. That spacing is consistent
  with a fixed-interval background status/telemetry poll Synapse (or
  `RazerAppEngine`) runs regardless of THX state, not something the toggle
  triggered. Its proximity to the OFF click looks like coincidence, not
  causation — if it were toggle-triggered, the identical pattern should
  also have appeared at the ON click, and it didn't.

Net conclusion from the packet capture alone: **no HID/USB traffic
distinguishable from routine background polling correlates with either
edge of the THX toggle.**

## Corroborating evidence: THX is a software service, not firmware

Independent of the capture, the installed THX driver package settles this
more directly. Its `.inf`
(`thx_razer_blacksharkv3pro_pc_svc.inf`, under
`C:\WINDOWS\System32\DriverStore\FileRepository\thx_razer_blacksharkv3pro_pc_svc.inf_amd64_99889b998fd02a46\`)
installs as:

```
Class = SoftwareComponent
...
[SvcComponents_Install.Services]
AddService = , 2          ; no function driver
AddService = thx_razer_blacksharkv3pro_pc_service, ..., THX_Service_Inst

[THX_Service_Inst]
DisplayName   = "THX Spatial Audio Service"
ServiceType   = 0x00000010   ; SERVICE_WIN32_OWN_PROCESS
ServiceBinary = %13%\thx_razer_blacksharkv3pro_pc_svc.exe
```

That's Microsoft's own INF vocabulary for "this is not a kernel driver" —
`; no function driver`, `SoftwareComponent` class, and a plain Win32
service binary (`thx_razer_blacksharkv3pro_pc_svc.exe`, ~14MB), shipped
alongside `thx_razer_blacksharkv3pro_pc_surround_714_patch.exe` (name
consistent with a stereo→7.1.4 software upmix stage — the same category of
approach Lynapse's own PipeWire convolver takes, just proprietary/licensed
on the Windows side). At time of testing, `THX Spatial Audio Service` was
running as an ordinary Windows service, not tied to any USB/HID driver
stack.

I didn't check the Settings → Sound → Spatial Sound panel directly (that's
a GUI-only check with no scriptable equivalent I had available) — worth a
5-second manual glance to see if "THX Spatial Audio" is listed as an
assignable spatial format there, which would further confirm the
software-APO angle, but the service/driver-package evidence above already
points the same direction on its own.

## Cross-reference to the existing openrazer attribute

`openrazer`'s `razerkraken` driver (what Lynapse sits on top of) already
exposes `v3pro_thx_spatial_audio`, which `_thx.py`/`app.py` already write
to (`self._write_sync('thx', ...)`) before layering the PipeWire HRTF
convolver on top. `test_v3_pro.py` treats that attribute as expected to
produce *some* audible change on its own, which suggests it does trigger a
minor on-device effect — just evidently not the full upmix+HRTF stage,
since Lynapse's own docs (`THX_SETUP.md`) already concluded a software
convolver was needed to get a comparable result. Nothing in this capture
contradicts that split, or suggests there's a second, undiscovered
device-side command Synapse sends that the existing attribute doesn't
already cover.

## Bottom line for `_thx.py`

No changes indicated. The current approach — send the existing
`v3pro_thx_spatial_audio` HID toggle, then do the real spatialization work
in a PipeWire HRTF convolver — appears to already match what Synapse
itself does on Windows (existing device toggle + a separate software DSP
stage), rather than being a compromise standing in for a fuller
device-side protocol we haven't found yet.

## Raw capture files

Not committed here (largest is ~8.7MB and not particularly useful without
the full session context). Left on the Windows machine at:

```
C:\Users\Joes\AppData\Local\Temp\claude\C--Users-Joes\4510ce25-3747-4036-a3b2-1b66ff2f5565\scratchpad\usb_captures\
  usbpcap1_20260813_160341.pcapng   (clean, keypress-gated run — the one referenced above)
  usbpcap2_20260813_160341.pcapng   (idle throughout, included for completeness)
  timeline_20260813_160341.log      (wall-clock log of each keypress)
```

That's a Temp directory tied to this Claude Code session, so treat it as
short-lived — ask if you want these pulled out to somewhere durable before
the session's scratch space gets cleaned up.
