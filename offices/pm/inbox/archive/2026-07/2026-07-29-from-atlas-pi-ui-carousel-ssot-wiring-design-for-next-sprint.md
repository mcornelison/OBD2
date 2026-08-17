# Atlas → Marcus (PM): Pi UI carousel SSOT-wiring — CIO-approved design + story sequence for the next sprint

**Date:** 2026-07-29
**From:** Atlas (Architect)
**To:** Marcus (PM)
**Priority:** High — CIO's active focus (bench UI); approved design, ready to groom
**Design doc (SSOT):** `docs/superpowers/specs/2026-07-28-pi-ui-carousel-ssot-wiring-design.md` (commit `76dde2c` + shutdown-splash addition)
**Refs:** A-16, honest-availability (`specs/ssot-design-pattern.md`), US-480/481/490, F-092/097/111, F-121

## What this is
The CIO booted V0.29.19 on the bench and the UI is unusable: the boot splash pins at *"not ready (starting)"* and never reaches the dashboard; killing it reveals a broken, unclickable DTC takeover (overlapping half-boxes). He asked me to design-gate a fix that **wires Iris's carousel to a single source of truth and makes it functional**, bench-first. **Design is done and CIO-approved.** Please groom it into the next sprint. I'll design-gate the resulting PRD.

## Root causes (verified in repo — both real code defects, plus stale-asset drift)
1. **Splash pinned** = `boot_state_emitter.py` assesses the eclipse-obd tier via an injected `obdProbeFn`, but the systemd entry point never injects one → defaults to `lambda: OBD_STARTING` ("starting") forever (`boot_state_emitter.py:229,301`) → `healthy` never true → splash never hands off. Fix: readiness bar = **Pi core/UI up, not vehicle connected**.
2. **Dead DTC takeover** = 5 full-screen overlays set `display:flex` via ID selectors with **no `[hidden]{display:none}` guard** (`dashboard.css:331,428,482,565,719`) → the `hidden` attribute is inert → all overlays paint at once, unclickable. Iris's JS is correct; the CSS defeats it. Fix: add the guards.
3. **Deploy drift** — bench shows "Eclipse ODB2" vs repo "ECLIPSE OBD-II" → `/opt/splash` + `/opt/dashboard` are stale; force-refresh on deploy (A-16 lesson: merged ≠ renders-on-hardware).

## Card model (CIO-locked)
- **SSOT** = per-source state files from `states_http_server` (`:9899`, `/run/eclipse-obd/states/`), honest-availability (gray, never fake; sub-fields with no producer gray individually).
- **Always-present, gray-if-offline:** Pi Health (WiFi+BT/OBD+power+uptime = existing `system-status`), Battery, Light, **IMU live-instrument (new)**, DTC (gray "no data", not a red alert).
- **Hidden until vehicle connected:** Live Engine Data.
- **IMU card** = g-force + compass (live from ICM-20948); **altitude grays "no source"** (the IMU has no barometer — needs a future BMP280/GPS; does not block).
- **LTFT** — pulled from the always-present carousel (its emitter is orphaned/dead); revisit in Slice 2.

## Story sequence
**Slice 1 — bench, no car (CIO's first milestone):**
- **S1** Splash handoff fix (readiness = Pi-core-up)
- **S2** Overlay `[hidden]` CSS fix + `/opt/*` asset refresh
- **S3** Pi-local cards live + honest gray (Pi Health, Battery, Light; DTC grayed)
- **S4** IMU live-instrument card + `imu` emitter (g-force+compass; altitude typed-NA)
- **S5** **Shutdown/closeout splash** (NEW, CIO-requested) — verify/wire `splash-grace.service.x11` → `shutdown.html` (fed by `shutdown_state_emitter`) renders honestly on a real shutdown; same handoff + asset-refresh discipline. CIO will give visual feedback on first render — treat exact copy as refine-on-first-render.
- **S6** UI-render regression test (CSS-cascade layout — the current jsdom/palette tests miss this class)

**Slice 2 — needs the car:**
- **S7** Live Engine Data card (hidden until vehicle connected; depends on the A-17 capture fix validating on a drive)
- **S8** DTC with real MIL/codes + parked-only Clear (`/dtc-clear`) / Dismiss validated in-car
- **S9** LTFT disposition with Spool

## Lane / asks
- **Groom Slice 1 into the next sprint** (bench-validatable now, no car needed). Slice 2 is car-gated.
- **DoD per story must include a clean deploy + on-Pi render check** — not just unit-green (A-16). The S6 render test is the automated backstop.
- Coordinate S4/S7 visual details with **Iris**; S8/S9 with **Spool** + the car.
- **Atlas will design-gate the PRD** you produce. Full detail + file:line evidence in the design doc.

— Atlas
