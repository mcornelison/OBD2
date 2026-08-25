# Splash Screen — Raspberry Pi installation

A two-second-long version of the brief, then the steps.

## What this is

An animated boot/shutdown splash for a Raspberry Pi 3.5" 480×320
automotive display. Pure CSS animation inside two SVG files, displayed
through Chromium in kiosk mode and wired into systemd so it plays on
boot and on shutdown.

- `splash.svg` — 6.5-second boot animation (emerge → 3× rotation →
  saturation throb → fade)
- `splash-shutdown.svg` — same file with `animation-direction:
  reverse` applied to every animation; plays as a graceful dim-down
- `index.html` / `shutdown.html` — full-bleed black wrappers that
  embed the SVGs at native 480×320 and poll the localhost state server
- `boot-state-poll.js` / `shutdown-state-poll.js` — the status-aware
  state machines (boot health + shutdown phase)
- `splash-boot.service.{wayland,x11}` / `splash-grace.service.{wayland,x11}`
  / `splash-grace.path` — systemd unit templates; `install.sh` picks the
  variant matching the detected session type (Wayland or X11)
- `install.sh` / `uninstall.sh` — installer (with `--dry-run`) / remover
- `preview.html` — open this in any desktop browser to preview both
  animations side-by-side without touching a Pi

> **D-1/D-2/D-3 (US-396):** `shutdown.html` now loads `splash-shutdown.svg`
> (was `splash.svg`); the self-cancelling `splash-shutdown.service` is retired
> in favour of `splash-grace.service` + `splash-grace.path` (fired by the
> shutdown-state file); the boot unit is Wayland/X11-aware and orders **after**
> the display server. Preview the picks first with `sudo ./install.sh --dry-run`.

## Requirements

- Raspberry Pi 3, 4, or 5 running Raspberry Pi OS (Bookworm or
  Bullseye)
- A 480×320 display attached and configured (waveshare, adafruit PiTFT,
  or any HDMI / DSI panel of that resolution)
- `chromium-browser` installed (Pi OS Desktop has it preinstalled;
  Pi OS Lite users: `sudo apt install -y chromium-browser`)
- A graphical session that comes up at boot — i.e. `graphical.target`
  is the default target. Check with `systemctl get-default`. If it
  reports `multi-user.target` (no GUI), either switch to graphical
  (`sudo systemctl set-default graphical.target`) or replace
  Chromium in the unit files with a framebuffer image viewer such as
  `fbi` rendering a pre-rasterised PNG of the SVG — see the
  "Headless / no-X" note at the bottom.

## Install

1. Copy this whole folder to the Pi (USB stick, scp, or
   `git clone` if you put it in a repo). Anywhere is fine — the
   installer reads files relative to itself.

   ```sh
   scp -r splash-pi pi@<pi-host>:~/
   ```

2. SSH in and run the installer as root:

   ```sh
   ssh pi@<pi-host>
   cd ~/splash-pi
   chmod +x install.sh uninstall.sh
   sudo ./install.sh
   ```

3. Reboot:

   ```sh
   sudo reboot
   ```

The boot splash plays once during the early graphical-target startup
and exits after 7 seconds. The shutdown splash plays once during
`systemctl poweroff` / `reboot`.

## Test without rebooting

Once installed you can verify by manually running Chromium against the
installed HTML:

```sh
chromium-browser --kiosk file:///opt/splash/index.html
```

…then close it with Ctrl+W (or wait for the script to kill it on a real
boot).

## Test on your laptop first

You can sanity-check the animation on any computer before touching the
Pi: just open `preview.html` in a normal browser (Chrome / Firefox /
Safari). Both boot and shutdown SVGs play side-by-side at native
480×320 with a Replay button each.

## Tuning

All timing and colors are exposed as CSS custom properties at the top
of `splash.svg` (and copied into `splash-shutdown.svg`):

| Variable          | Default      | What it does                          |
|-------------------|--------------|---------------------------------------|
| `--red`           | `#E60012`    | Base diamond fill                     |
| `--red-light`     | `#F61D2D`    | Upper-left facet (gradient stop)      |
| `--red-dark`      | `#BF000F`    | Lower-right facet (gradient stop)     |
| `--bright-low`    | `0.25`       | Brightness at end of emergence (1.5s) |
| `--bright-mid`    | `0.50`       | Brightness after rotation 1           |
| `--bright-hi`     | `0.75`       | Brightness after rotation 2           |
| `--bright-max`    | `1.00`       | Brightness after rotation 3           |
| `--throb-low`     | `0.60`       | Low point of the throb pulses         |
| `--spin-end`      | `-360deg`    | Total spin (negative = CCW)           |

To change the boot animation duration: edit the keyframe percentages in
`splash.svg`. The kiosk no longer exits on a hardcoded `sleep`/`pkill` —
`boot-state-poll.js` closes the window itself once boot reaches
`HEALTHY_YIELD` (≥2.5s healthy) or `DEGRADED`, so there is no service-side
timer to keep in sync.

If the panel's narrow gamut washes out the gradient crease, bump
`--red-light` / `--red-dark` to 10–12% deltas instead of 7%.

## Geometry reference

- Stage: 480×320 viewBox, `preserveAspectRatio="xMidYMid meet"`
- Logo center: (240, 160)
- Each rhombus: 50 px short axis × 100 px long axis
- Inner-vertex offset from center: 10 px (creates the visible gap)
- Three rhombi arranged at 120° steps (top, bottom-left, bottom-right)

## Display orientation

Many 3.5" PiTFT panels ship rotated 90° or 180° from the framebuffer.
If your splash appears sideways:

- HDMI / config.txt: add `display_rotate=1` (or 2 / 3) to
  `/boot/firmware/config.txt` and reboot.
- Wayland (Pi OS Bookworm default): use `wlr-randr --output <name>
  --transform 90`.
- X11: use `xrandr --output <name> --rotate left` in your session
  autostart.

The SVG itself is upright; the rotation must happen at the
display-server level.

## Uninstall

```sh
cd ~/splash-pi
sudo ./uninstall.sh
```

## Headless / no-X (Pi OS Lite, no graphical session)

If the Pi has no X / Wayland session running, Chromium kiosk won't
work. Two fallback options:

1. **Plymouth** with a pre-rendered video. Convert `splash.svg` to an
   MP4 using a desktop tool (Inkscape → PNG sequence → ffmpeg), then
   install Plymouth and use the `plymouth-set-default-theme`
   pipeline with a custom theme. This is more involved; happy to
   generate the conversion script and theme files if you go this
   route.
2. **fbi** + PNG. Render the SVG to a 480×320 PNG at the *final* logo
   state and display via `fbi -T 1 -noverbose -a -d /dev/fb0
   /opt/splash/splash.png`. This loses the animation but gives you a
   static logo while the system boots.

## Troubleshooting

**Black screen on boot.** Check the service logs:
`sudo journalctl -u splash-boot.service -b`. Most common: `DISPLAY`
not set, Chromium can't find a server. Add `Environment=DISPLAY=:0`
or switch to Wayland-friendly args (`--ozone-platform=wayland` on
Bookworm).

**Splash plays but is sideways / clipped.** See "Display orientation"
above.

**Splash plays but is too dim/dark.** Bump `--bright-low` and
`--throb-low` in `splash.svg`. Some panels have very limited dynamic
range and 25% brightness reads as black.

**Shutdown splash doesn't appear.** The shutdown splash is fired by
`splash-grace.path` watching `/run/eclipse-obd/states/shutdown-state`,
which `ShutdownSequencer` writes when it enters the grace period. Check:
`systemctl status splash-grace.path` (should be active/waiting) and
`ls -l /run/eclipse-obd/states/shutdown-state` during a shutdown. If the
state file never appears, the sequencer's phase-emit hook (or
`pi.splash.enabled` in `config.json`) is the place to look — not this kit.
The old `splash-shutdown.service` (retired) self-cancelled via a
`Conflicts=` directive the moment shutdown began; that bug (D-2) is gone.
