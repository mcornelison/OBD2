from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=Pi display: deploy fix VALIDATED end-to-end + Bug 4 (screen-sleep) fixed -- all 4 rolled into the finding; audience=agent; refs=deploy-pi.sh,F-103,F-092

# Atlas → Marcus: Pi display fix validated + Bug 4 landed

Follow-up to the display finding (`findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md`, updated with all 4 gaps). CIO-supervised.

## Validated end-to-end
Tore the kiosk fully back down (blank state), ran a **full `deploy-pi.sh`** → the new `step_install_ui_kiosk_units` rebuilt it from scratch (detected x11, re-symlinked chromium, installed+enabled the units). **CIO power-cycled → the boot splash rendered automatically.** The core blank-screen deploy bug is fixed + proven at real boot.

## 4 bugs, final tally
1. Kiosk never installed by deploy — **FIXED** (`deploy-pi.sh` step).
2. `chromium-browser` vs `chromium` (Trixie) — **FIXED** (deploy symlink; proper fix = kit V-3 binary check, UI kit).
3. Carousel no live data + empty-state CHECK-ENGINE takeover — **OPEN, QA/Iris** (verify with the car).
4. **NEW: DPMS screen-sleep** — panel slept after 10 min → "no input" (splash still running underneath). **FIXED**: `deploy/eclipse-kiosk-no-blank.conf` xorg drop-in + live xset in the kiosk step.

## For intake / review
- Bugs 1/2/4 are in the deploy path now (Ralph: review `deploy-pi.sh` `step_install_ui_kiosk_units` + `deploy/eclipse-kiosk-no-blank.conf`; both validated live).
- Bug 3 → Argus + Iris (car-connected drive: eclipse-obd ready → splash yields → carousel live data + the empty-state takeover).
- **Do NOT `/chain-validated` the V0.29 chain** until the display renders end-to-end *including* live carousel data on the car.

-- Atlas
