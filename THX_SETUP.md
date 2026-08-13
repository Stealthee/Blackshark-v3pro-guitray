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

## Doing this yourself, without Lynapse (any Linux headset)

None of this is Lynapse-specific — it's stock PipeWire plus a public HRIR
file, so it works for any headset/headphones on any Linux desktop. Here's
the recipe Lynapse itself automates, if you'd rather wire it up by hand or
adapt it for a device Lynapse doesn't support.

**1. Get a HeSuVi-format HRIR/BRIR WAV file.** This is the actual "ears" —
a set of measured (or modeled) head-related impulse responses, one pair
per speaker position, in a standardized 14-channel layout. Sources:
- [IrateGoose's linked collection](https://airtable.com/appayGNkn3nSuXkaz/shruimhjdSakUPg2m/tbloLjoZKWJDnLtTc)
- HeSuVi's own bundle (`HeSuVi/Common/*.wav`, from a Windows/Wine HeSuVi install)

**2. Find your headphone sink's exact PipeWire name:**
```sh
pactl list sinks short
```
Look for your device (usually an `alsa_output.usb-...` or
`alsa_output.pci-...` line) and copy its full name.

**3. Write a filter-chain config** at
`~/.config/pipewire/pipewire.conf.d/60-my-thx.conf` (any filename ending
`.conf` works). This is the minimal 2-channel binaural version — plain
stereo audio in, both ears' direct + crossfeed HRIR response applied, no
upmixing needed:

```
context.modules = [
    { name = libpipewire-module-filter-chain
        flags = [ nofail ]
        args = {
            node.description = "My THX Surround"
            media.name       = "My THX Surround"
            filter.graph = {
                nodes = [
                    { type = builtin label = copy name = copyL }
                    { type = builtin label = copy name = copyR }
                    { type = builtin label = convolver name = convL_L config = { filename = "/path/to/your.wav" channel = 0 } }
                    { type = builtin label = convolver name = convL_R config = { filename = "/path/to/your.wav" channel = 1 } }
                    { type = builtin label = convolver name = convR_R config = { filename = "/path/to/your.wav" channel = 7 } }
                    { type = builtin label = convolver name = convR_L config = { filename = "/path/to/your.wav" channel = 8 } }
                    { type = builtin label = mixer name = mixL control = { "Gain 1" = 3.2 "Gain 2" = 3.2 } }
                    { type = builtin label = mixer name = mixR control = { "Gain 1" = 3.2 "Gain 2" = 3.2 } }
                ]
                links = [
                    { output = "copyL:Out" input = "convL_L:In" }
                    { output = "copyL:Out" input = "convL_R:In" }
                    { output = "copyR:Out" input = "convR_R:In" }
                    { output = "copyR:Out" input = "convR_L:In" }
                    { output = "convL_L:Out" input = "mixL:In 1" }
                    { output = "convR_L:Out" input = "mixL:In 2" }
                    { output = "convL_R:Out" input = "mixR:In 1" }
                    { output = "convR_R:Out" input = "mixR:In 2" }
                ]
                inputs  = [ "copyL:In" "copyR:In" ]
                outputs = [ "mixL:Out" "mixR:Out" ]
            }
            capture.props = {
                node.name      = "effect_input.my-thx"
                media.class    = Audio/Sink
                audio.channels = 2
                audio.position = [ FL FR ]
            }
            playback.props = {
                node.name      = "effect_output.my-thx"
                node.passive   = true
                audio.channels = 2
                audio.position = [ FL FR ]
                target.object  = "your-headphone-sink-name-from-step-2"
            }
        }
    }
]
```

**4. Load it:**
```sh
systemctl --user restart pipewire pipewire-pulse
```
A new sink called `effect_input.my-thx` should appear in `pactl list sinks
short`. Set it as your output (system settings, or `pactl set-default-sink
effect_input.my-thx`), or move a specific app's stream onto it with
`pactl move-sink-input <id> effect_input.my-thx`.

**Gotcha — the makeup-gain math is not what it looks like.** The `mixer`
node's `"Gain N"` control is *not* a plain linear multiplier on an
otherwise-unprocessed signal — each mixer here sums two already-attenuated
convolver paths, and that summed pair measures roughly **half** as loud as
an unprocessed bypass signal at `Gain N = 1.0`. In other words, `Gain N =
G` nets out to about `G/2`x of bypass volume, not `G`x. This bit us twice
while tuning Lynapse's own version — a couple of "obviously enough" gain
values turned out to change nothing audible. If you're tuning this by
ear, don't trust the number alone: A/B it against a bypass sink with
something like
```sh
parecord --device=your-sink.monitor --file-format=wav /tmp/test.wav
```
(once with your player pointed at the effect sink, once at the raw
device) and compare loudness, rather than assuming the config value maps
linearly.

**Full 7.1/8-channel version:** only worth it if your actual source audio
is genuinely multichannel (e.g. a game outputting real 7.1 PCM, or a
custom multichannel test file) — ordinary stereo game/movie/browser audio
never has independent content on the side/rear channels, so an 8-input
graph fed 2-channel source just leaves 6 inputs silent and sounds thinner,
not more spatial. If you do have real multichannel source, the working
reference is
[`sink-virtual-surround-7.1-hesuvi.conf`](https://gitlab.freedesktop.org/pipewire/pipewire/-/blob/master/src/daemon/filter-chain/sink-virtual-surround-7.1-hesuvi.conf)
(ships with PipeWire itself, under `/usr/share/pipewire/filter-chain/` on
most distros) — same idea, one convolver pair per speaker position instead
of two.

Lynapse's own implementation (`lynapse/_thx.py` in this repo) is a working,
tested reference for all of the above if you want a complete example to
copy from, including the game/chat-sink-scoping and stream-move logic.

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
