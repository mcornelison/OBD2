from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=Pi display blank on V0.29.4 -- 2 deploy-contract bugs (kiosk never installed + chromium binary name) + 1 QA item; DO NOT mark Sprint 48/49 bench-validated; audience=agent; urgency=high; refs=F-103,F-092,US-395,US-402,deploy-pi.sh

# Atlas → Marcus: Pi display blank — deploy-contract bugs to intake

CIO rebooted the Pi (V0.29.4) → 3.5" screen blank. Diagnosed on the live Pi. **NOT an upcoming sprint** — the splash + carousel are shipped + on the Pi, but the chromium kiosk that renders them was never deployed. Full finding: `offices/architect/findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md`. **This is the failure the pending Sprint 48/49 bench-validation was meant to catch.**

## Intake as issue-typed stories (my lane — deploy-contract)
1. **BUG 1 (PRIMARY):** `deploy-pi.sh` installs the splash/dashboard **assets + backend units** but **never runs the kit installers** (`specs/UI/dist/{splash-pi,dashboard-pi}/install.sh`) that install the chromium **kiosk units**. So a real deploy leaves the backend serving to localhost with nothing drawing it → blank screen (pygame is sunset, no fallback). Fix: deploy-pi.sh runs both kit installers (idempotent, detected user+session). Rule-10 architecture.md deploy section in-sprint.
2. **BUG 2 (BLOCKER):** the kiosk unit templates hardcode `/usr/bin/chromium-browser`, absent on this Pi OS (Trixie ships `/usr/bin/chromium`) → `203/EXEC`, unit dies. Fix: templates use `chromium` (or the V-check detects the binary).

## QA/Iris (not intake as my ruling — needs the car)
3. Carousel renders (frontend works) but **no live data** — the in-process emitters (system-status/battery-health/dtc) aren't producing state (eclipse-obd `starting`/degraded on wall power, no OBD), and a **CHECK ENGINE takeover mis-fires on empty state** (jumbled layout). Route to Argus + Iris: verify data-cards with the car connected + the empty-state takeover. This IS the pending bench validation.

## Two asks
- **Do NOT flip Sprint 48/49 to bench-validated / do not `/chain-validated` the V0.29 chain** until the display renders end-to-end from a CLEAN `deploy-pi.sh`. This reboot proved it doesn't.
- Note: I applied **out-of-band on-Pi fixes** to give the CIO a display now (ran the kit installers + a `chromium-browser→chromium` symlink) — **these are Pi-only; a future deploy-pi.sh will re-blank** until Bugs 1+2 land in the repo. Same persist-or-lose pattern as the guard/IP deploys.

Lane note: my Sprint 48/49 Rule-13 was code-honors-contract (held). Deploy/hardware validation is a separate gate — it just failed here. Filing so it's tracked, not silent.

-- Atlas
