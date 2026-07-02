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

---

## UPDATE 2026-07-01 (cont.) — all FOUR gaps + fixes landed + end-to-end validation (CIO-supervised)

Full four-bug tally (a 4th surfaced once the display rendered):

| # | Gap | Fix | Where | Status |
|---|---|---|---|---|
| **1** | `deploy-pi.sh` never runs the kit installers → kiosk units never installed → blank | new `step_install_ui_kiosk_units()` runs both kit installers, with SSH-safe session detection (loginctl seat0, never guesses) | `deploy/deploy-pi.sh` | **FIXED + validated** |
| **2** | Units call `/usr/bin/chromium-browser`, absent on Trixie (`chromium`) → `203/EXEC` | deploy-side compat symlink `chromium-browser → chromium` | `deploy/deploy-pi.sh` (kiosk step) | **FIXED** (deploy shim; proper fix = kit V-3 binary check — UI kit) |
| **3** | Carousel has no live data (emitters not producing state); CHECK-ENGINE takeover mis-fires on empty state | — | needs the car | **OPEN — QA/Iris** (the pending bench validation) |
| **4** | X11 DPMS/screen-blank not disabled → panel sleeps after 10 min → "no input" | xorg drop-in disabling BlankTime/Standby/Suspend/Off + live `xset` | `deploy/eclipse-kiosk-no-blank.conf` + `deploy/deploy-pi.sh` | **FIXED** |

### End-to-end validation (the proof, not "looks right")
- Wrote Bug 1/2 fix into `deploy-pi.sh`; `bash -n` clean; detection logic verified `x11` live.
- **Tore the kiosk fully back down** (uninstalled both kits + removed the symlink → confirmed BLANK), then ran a **full `deploy-pi.sh`** (default mode). The new step re-detected `x11`, re-created the symlink, and re-installed+enabled splash-boot + splash-grace + eclipse-dashboard from scratch. Deploy OK; eclipse-obd/powerwatch restart-verified; `.deploy-version` stamped (`8c80d49`).
- **CIO power-cycled the Pi → the boot splash rendered automatically.** That is the end-to-end confirmation that the deploy fix works at real boot — the core blank-screen bug is closed.
- Then the panel went "no input" → **Bug 4** (DPMS `Monitor is Off` after 600 s; splash still active underneath). Woke it live + disabled blanking; installed the persistent xorg drop-in for future boots.

### Net
- **Bugs 1, 2, 4 are fixed in the deploy path** (`deploy/deploy-pi.sh` + `deploy/eclipse-kiosk-no-blank.conf`) — a clean deploy now renders the display and it won't sleep. The earlier out-of-band Pi patches are now reproducible by the deploy.
- **Bug 3 (carousel live-data + empty-state takeover) is the remaining QA/Iris item** — verify on a drive with the car connected (eclipse-obd reaches "ready" → splash yields → carousel).
- Still holds: **do not `/chain-validated` the V0.29 chain until the display renders end-to-end including live carousel data on the car.**

— Atlas
