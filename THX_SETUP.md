# THX Spatial Audio setup

The **THX SPATIAL AUDIO** button on the SOUND tab does two things when you
turn it on:

1. Sends the existing on-headset HID toggle (`v3pro_thx_spatial_audio` /
   `thx_spatial_audio`), same as before.
2. Routes your headset's audio through a PipeWire HRTF convolver — a
   binaural virtual-surround effect, which is what actually produces the
   "bigger, more spatial" sound people associate with THX Spatial Audio on
   Windows.

**This is not real Windows THX Spatial Audio.** THX's actual DSP is a
licensed, Windows-only proprietary algorithm that internally upmixes stereo
game audio to virtual 7.1.4 before running its HRTF stage. What Lynapse does
instead is apply the same category of effect — HRTF binaural convolution —
using PipeWire's stock `libpipewire-module-filter-chain` convolver, the same
mechanism third-party tools like [IrateGoose](https://github.com/Barafu/IrateGoose)
use. It gets you a comparable "wider, more real" spatial effect on Linux; it
won't be byte-for-byte identical to Windows.

Since we don't have that internal upmixer, and the headset's game sink is
stereo-only anyway (not true 7.1 hardware), Lynapse deliberately convolves
your stereo signal through a proper 2-channel binaural pair — each ear gets
its own-side response plus crossfeed from the opposite channel — rather than
feeding it into a full 8-channel HeSuVi-style graph with 6 permanently-silent
inputs (which is quieter and thinner, since HeSuVi-format IR files are
level-balanced assuming all 8 channels contribute).

## Why "not installed" shows up

The convolver needs an **impulse-response (IR) file** — a WAV file encoding
measured head-related transfer functions (HRTF), in the 14-channel HeSuVi
format. This file isn't bundled with Lynapse (it's not something we can
freely redistribute), so until one is in place, clicking THX just tells you
it's missing instead of silently doing nothing.

## Setup

1. **Get an IR file.** Any HeSuVi-format WAV works; a Razer-flavored one
   gets you closest to the Windows THX character. Options:
   - [IrateGoose's linked collection](https://airtable.com/appayGNkn3nSuXkaz/shruimhjdSakUPg2m/tbloLjoZKWJDnLtTc)
   - HeSuVi's own bundle (`HeSuVi/Common/*.wav` inside a HeSuVi install, if
     you have one from Windows/Wine)
   - An existing IrateGoose setup on this machine, if you have one — its IR
     files typically live in whatever folder you pointed IrateGoose's
     **Options → WAV Folder** at (check
     `~/.config/pipewire/pipewire.conf.d/*.conf` for the `filename =` path
     it's currently using if you're not sure)

2. **Place it here**, exactly:
   ```
   ~/.local/share/lynapse/thx/razer.wav
   ```
   Create the directory if it doesn't exist. The filename must be
   `razer.wav` — that's the only thing Lynapse checks for.

3. That's it. Click **THX SPATIAL AUDIO** in the SOUND tab.

## What happens when you turn it on

- **It only ever touches game/media audio, never chat.** The headset
  exposes separate "game" and "chat" outputs (that's what the Game/Chat
  balance dial controls); THX is scoped to the game sink specifically, so a
  Discord/voice call on the chat side is never touched or rerouted.
- The first time (or any time the target audio device changes), Lynapse
  writes a PipeWire filter-chain config and restarts `pipewire` +
  `pipewire-pulse` to load it — this causes a brief (~1-2 second) audio
  blip system-wide, not just for the headset. This only happens when
  something actually changed; toggling on/off repeatedly in the same
  session after that is instant.
- Whatever's currently playing on the game sink gets moved onto the virtual
  surround sink immediately; the system default output is never changed.
- Turning THX off moves game audio back to the headset's normal game sink.
  The filter-chain config is left in place (it's idle/no-cost when unused)
  so turning on again later doesn't need another restart.

## Troubleshooting

- **"THX Spatial Audio isn't set up"** — the IR file isn't at
  `~/.local/share/lynapse/thx/razer.wav`, or it's empty. Re-check step 2.
- **"headset audio sink not found"** — PipeWire doesn't see the headset as
  an active output sink right now. Make sure it's connected and selected as
  an output at least once.
- **No audible difference** — some IR files are subtler than others, and
  spatial perception is very personal (this is true on Windows too — THX
  ships several profiles for the same reason). Try a different IR file.
- To inspect what Lynapse generated: `cat ~/.config/pipewire/pipewire.conf.d/60-lynapse-thx.conf`.
- To fully undo: delete that file and run
  `systemctl --user restart pipewire pipewire-pulse`.
