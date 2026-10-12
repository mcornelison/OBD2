# Carousel dashboard — Raspberry Pi installation (US-399, F-092)

The post-boot touch dashboard that replaces the pygame `status_display`. A
chromium kiosk that renders a **swipeable carousel** of cards (System Status,
Battery Health) with a **persistent top bar** and **page dots**, on the 3.5"
480×320 panel. It is a **pure consumer** of the state files the emitters write —
it never polls hardware.

## What this is

- `dashboard.html` — the carousel shell (top bar + cards + page dots). Served
  same-origin by `eclipse-states-http` at
  `http://127.0.0.1:9899/dashboard.html` so the auth token is injected (token
  SSOT — same seam as the F-103 splash).
- `dashboard.css` — top bar / carousel / page-dot styles. Tap targets ≥40px.
- `carousel.js` — swipe-nav + page dots + the honest-instrument availability
  poll (a missing/malformed state file renders `unavailable`, never a crash and
  never green-when-broken). The per-card field rendering is US-400 / US-401.
- `dashboard.service.{wayland,x11}` — chromium kiosk unit templates;
  `install.sh` picks the variant matching the detected session type.
- `install.sh` / `uninstall.sh` — installer (with `--dry-run`) / remover.

## How it starts (A-1 hand-off)

The dashboard is **not** enabled to start at boot. The F-103 boot splash
(`splash-boot.service`) carries `OnSuccess=eclipse-dashboard.service`: when the
splash reaches `HEALTHY_YIELD` it calls `window.close()`, the `Type=simple`
splash unit exits 0, and systemd starts the dashboard. A **DEGRADED** boot keeps
the splash up (no `window.close`), so the dashboard never appears on a sick boot.

## Prerequisites

- `eclipse-states-http.service` running with **`/opt/dashboard` on its
  `--assets-dir` search path** (it is, per `deploy/eclipse-states-http.service`,
  which lists `/opt/splash` then `/opt/dashboard`). The server serves both kits
  same-origin and injects the token into either kit's HTML.
- The F-103 splash kit installed (it owns the `OnSuccess=` hand-off).
- `chromium-browser`, a graphical session at boot (`graphical.target`).

## Install

1. Copy this folder to the Pi (scp / USB / git clone).
2. Preview the picks first (unprivileged):

   ```sh
   ./install.sh --dry-run
   ```

3. Install as root:

   ```sh
   sudo ./install.sh
   sudo reboot
   ```

The dashboard appears within a few seconds of the boot splash yielding healthy.

## Test on your laptop first

Open `dashboard.html` directly in a desktop browser. The token placeholder stays
unsubstituted, so the state polls fail closed to `unavailable` — but the
carousel still renders and swipes (drag horizontally, or use ← / → arrows).

## Uninstall

```sh
sudo ./uninstall.sh
```

## Notes

- **Sequencing:** the dashboard and the pygame `status_display` must never run
  at once (A-4). The pygame surface is retired in **US-402** (parity-gated); the
  full sprint deploys US-399…402 together, so the shipped artifact has exactly
  one surface.
- **Display orientation / black-screen troubleshooting:** identical to the
  splash kit — see `src/pi/ui/splash/INSTALL.md`.
