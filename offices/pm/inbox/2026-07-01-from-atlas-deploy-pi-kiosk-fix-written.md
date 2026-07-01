from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=deploy-pi.sh kiosk-unit fix WRITTEN + validated (Bug 1) -- for Ralph review/intake; audience=agent; refs=deploy-pi.sh,F-103,F-092

# Atlas → Marcus: deploy-pi.sh kiosk fix written (CIO-directed)

CIO directed me to write the deploy-pi.sh fix directly (first-hand knowledge from fixing it on the Pi by hand). Done + validated. For Ralph's review + the sprint intake of the display finding (`findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md`).

## What I added to `deploy/deploy-pi.sh`
- New step **`step_install_ui_kiosk_units()`** (after `step_install_dashboard_assets`), called in main right after `step_install_state_server_units`. It runs the kit's own installers (`specs/UI/dist/{splash-pi,dashboard-pi}/install.sh`) — the step that was never wired in (Bug 1).
- It bakes in the two traps I hit by hand:
  1. **SSH session-detection:** the installers' V-2 check reads the *calling* session, which over SSH is `tty` → it aborts rather than guess X11/Wayland (D-3 black-screen protection). The step detects the type from the Pi's **active seat0 graphical session** (loginctl, Xorg/wayland-0 fallback) and passes `{SPLASH,DASHBOARD}_FORCE_SESSION`. If undeterminable → WARN + skip, never guess.
  2. **chromium binary:** units call `/usr/bin/chromium-browser`; Trixie ships `/usr/bin/chromium` → 203/EXEC. The step adds the compat symlink when absent (Bug 2, deploy-side).
- Idempotent; A-9 posture (absent kit → WARN + continue); installs+enables only (splash renders next boot — no mid-deploy screen thrash).

## Validated
- `bash -n deploy/deploy-pi.sh` → clean.
- Against the live Pi (read-only): the step's detection yields `x11` (matches the real session); the installer accepts the forced session (dry-run picks `splash-boot.service.x11`, user mcornelison).

## Still owed (NOT in deploy-pi.sh)
- **Bug 2 proper fix (UI kit / Iris):** the deploy symlink is a shim; the cleaner fix is a kit-installer **V-3 binary check** that substitutes the real chromium path into the unit template (like it substitutes User=), so it's OS-version-proof without touching /usr/bin. Flag for the UI kit.
- **Bug 3 (QA/Iris):** carousel live-data emitters + empty-state takeover — verify with the car (the pending bench validation).
- The on-Pi manual fixes I applied earlier are now REPRODUCIBLE by this deploy step, so a future `deploy-pi.sh` no longer re-blanks. Recommend a clean `deploy-pi.sh --dry-run` review by Ralph, then a real run to confirm.

-- Atlas
