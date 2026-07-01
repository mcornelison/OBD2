# Finding — Pi 3.5" display blank on V0.29.4: deploy-contract gaps (F-103 splash + F-092 carousel never rendered on hardware)

**By:** Atlas (Architect) · **Date:** 2026-07-01 · **Trigger:** CIO rebooted the Pi (V0.29.4), 3.5" display blank.
**Verdict:** NOT an upcoming sprint. The splash (Sprint 48/V0.29.2) + carousel/DTC (Sprint 49/V0.29.3) are shipped and on the Pi, but **the chromium kiosk that renders them was never deployed**, plus a binary-name bug. This is exactly the failure the still-pending **Sprint 48/49 "bench validation"** was meant to catch — this reboot was the first real on-hardware display test.

## Evidence (live Pi, 2026-07-01)
- `.deploy-version` = V0.29.4 (`554bf39`), deployed 11:10Z. Backend healthy: `eclipse-boot-state.service` + `eclipse-states-http.service` running, serving the splash HTML on `127.0.0.1:9899`; `/run/eclipse-obd/states/` provisioned (C-5 works).
- **No chromium process; no `splash-boot.service` / `eclipse-dashboard.service` on the Pi.** pygame is disabled (`statusDisplay.enabled=false`, US-402 sunset) → no fallback → fully blank.

## Root causes

### BUG 1 (deploy-contract, PRIMARY) — `deploy-pi.sh` never installs the kiosk units
`deploy-pi.sh` installs the splash/dashboard **assets** (`/opt/splash`, `/opt/dashboard`) + the **backend** units (states-http, boot-state emitter, states tmpfiles), but it **never runs the kit installers** `specs/UI/dist/splash-pi/install.sh` / `dashboard-pi/install.sh` — the step that installs+enables the chromium kiosk systemd units. `deploy-pi.sh`'s own comments flag the seam ("the chromium kiosk UNIT … is installed by the kit's [install script]") but it was never wired in. So every real deploy leaves the backend serving the splash to localhost with nothing drawing it.
**Fix:** `deploy-pi.sh` runs both kit installers (idempotent, sync-if-changed), passing the detected user + session type. In-sprint architecture.md deploy section.

### BUG 2 (BLOCKER) — kiosk units call a binary that doesn't exist on this OS
The unit templates (`splash-boot.service.{x11,wayland}`, `dashboard.service.*`, `splash-grace.service.*`) hardcode `ExecStart=/usr/bin/chromium-browser`. This Pi (Raspberry Pi OS Trixie) ships **`/usr/bin/chromium`** — `chromium-browser` is absent → `status=203/EXEC`, unit dies instantly.
**Fix:** unit templates use `/usr/bin/chromium` (or the install-check detects the binary and substitutes it, like it substitutes User=).

### BUG 3 (FUNCTIONAL — needs QA/Iris + the car; NOT yet root-caused) — carousel has no live data
The card emitters (`system_status_emitter.py`, `battery_health_emitter.py`, `dtc_emitter.py`) run **in-process in eclipse-obd** (`orchestrator/lifecycle.py`), not as units. `/run/eclipse-obd/states/` has only `boot-state` — no `system-status`/`battery-health`/`dtc`. eclipse-obd shows `starting`/degraded (wall power, no OBD/car). Previewing the carousel (screenshot) showed the frontend renders but a **"CHECK ENGINE" takeover mis-fires on empty state** with a jumbled layout. **Open question:** should the status emitters run regardless of OBD connection (they exist to show "not connected" — the I-033 fix), or are they gated on a healthy eclipse-obd? Verify with the car connected — this is the pending bench validation. Empty-state takeover-mis-fire is an Iris/QA UI item.

## On-Pi mitigations applied (OUT OF BAND — must be codified)
To give the CIO a display now: (a) ran `splash-pi/install.sh` (SPLASH_FORCE_SESSION=x11, verified via Xorg/loginctl) → splash renders live (screenshot confirms: wordmark + honest degraded state + V0.29.4 chip); (b) `ln -s /usr/bin/chromium /usr/bin/chromium-browser`; (c) ran `dashboard-pi/install.sh`. **These live on the Pi only — a future `deploy-pi.sh` will re-blank the screen** (Bugs 1+2 unfixed in the repo). Same "persist to repo or lose it" pattern as the guard/IP deploys.

## Disposition
- **Bugs 1 + 2 = deploy-contract defects, my lane** → routed to Marcus for issue-intake; they land in `deploy-pi.sh` + the unit templates so a clean deploy works.
- **Bug 3 = QA/Iris** → verify carousel data-cards with the car connected (the pending bench validation) + the empty-state takeover.
- **Sprint 48/49 must NOT be marked bench-validated** until the display renders end-to-end from a clean `deploy-pi.sh` (this reboot proved it doesn't).
- Lane note: my Sprint 48/49 Rule-13 was *code-honors-contract* (which held); *deploy/hardware validation* is a separate gate — and it just failed here. Honest separation.

— Atlas
