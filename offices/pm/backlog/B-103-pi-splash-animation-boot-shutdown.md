# B-103: Pi Splash Animation -- Boot + Shutdown

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low (polish)           |
| Status       | Pending (V0.28+ candidate -- gated behind V0.27 chain merge per CIO 2026-05-21) |
| Category     | display / deployment / UX |
| Size         | S (kit is pre-built; integration work only) |
| Related PRD  | None                   |
| Dependencies | V0.27 chain merge (per CIO directive); soft-dependency on B-052 HDMI canvas decision |
| Filed By     | Marcus (PM) per CIO 2026-05-21 directive |
| Created      | 2026-05-21             |

## Description

CIO has designed a complete boot + shutdown splash animation kit -- already sitting in `specs/UI/dist/splash-pi/`. It is a pure CSS-animated SVG (Mitsubishi-style 3-rhombus emergence -> 3x rotation w/ saturation throb -> fade), displayed via Chromium kiosk through two systemd units (`splash-boot.service`, `splash-shutdown.service`). The shutdown variant is the same animation with `animation-direction: reverse` -- a graceful dim-down.

**This item integrates that kit onto the production Pi (`Chi-Eclips-01`).** No new asset design is required; the SVGs, HTML wrappers, systemd units, install/uninstall scripts, and preview page already exist. Scope = land it on the Pi during a deploy and verify it plays on boot + on `systemctl poweroff`.

Kit specifics (per `specs/UI/INSTALL.md`):
- Boot splash: 6.5 s (emerge 1.5 s -> 3 rotations w/ staged brightness 0.25/0.50/0.75/1.00 -> throb pulses -> fade)
- Shutdown splash: same SVG, `animation-direction: reverse`
- Target: 480x320 viewBox, `preserveAspectRatio="xMidYMid meet"`
- Color + timing exposed as CSS custom properties (tunable at the top of each SVG without touching keyframes)
- Headless / no-X fallback documented (Plymouth pre-rendered video OR `fbi` static PNG)

## Acceptance Criteria

- [ ] `specs/UI/dist/splash-pi/` contents land in `/opt/splash/` on `Chi-Eclips-01` (installer runs cleanly).
- [ ] `splash-boot.service` is enabled + plays the 6.5 s animation during graphical-target bring-up on the production HDMI display.
- [ ] `splash-shutdown.service` plays the reverse animation during `systemctl poweroff` and `systemctl reboot`.
- [ ] Animation visible + correctly oriented from the driver's seat (no sideways / clipped / off-screen rendering on the production HDMI panel).
- [ ] Idempotent on re-deploy: re-running the installer over an existing install does not double-enable units or duplicate files.
- [ ] `uninstall.sh` cleanly removes the splash with no orphaned systemd state.
- [ ] Splash plays do **not** race or block `eclipse-powerwatch.service` / `eclipse-obd.service` startup (services up by the splash exit window; verify via `journalctl` timestamps).

## Open Design Questions (resolve at PRD grooming time)

1. **Canvas size**: SVG is authored at 480x320 (the legacy OSOYOO footprint). Production HDMI per B-052 is 1920x1080 or 1280x720. `preserveAspectRatio="xMidYMid meet"` letterboxes cleanly but will look small on a full HDMI canvas. **Options**: (a) ship as-is, letterboxed, lowest risk; (b) retarget viewBox + keyframes to 1920x1080 before install; (c) make canvas size configurable + auto-detect at install.
2. **Install path**: standalone via `install.sh` (kit's design), or fold into `deploy/deploy-pi.sh` Step N so every Pi deploy reconciles the splash? Trade-off: standalone keeps the kit decoupled but risks drift; folding-in guarantees freshness but couples the kit to the deploy script.
3. **Shutdown-splash race**: shutdown service races against actual shutdown. INSTALL.md flags this -- some Pis poweroff before the 7-second window completes. May need to render a shortened (~2 s throb-only) variant for production. Decide at PRD time after first IRL test.
4. **Display rotation**: if the production HDMI panel reports a rotated orientation, install-time rotation hint may be needed (`display_rotate` in `/boot/firmware/config.txt`, `wlr-randr`, or `xrandr` -- per INSTALL.md "Display orientation" section).
5. **Graphical-target dependency**: kit assumes `graphical.target` is the default. Confirm production Pi is on graphical (`systemctl get-default`). If not, the headless / `fbi` fallback path becomes the install.
6. **Coordination w/ ShutdownSequencer**: V0.27.x sequencer drives `systemctl poweroff` from `__main__.py`. Confirm `splash-shutdown.service` fires in the right ordering (likely fine -- `systemctl poweroff` invokes shutdown.target which the splash unit hooks; sequencer's job is to *trigger* poweroff, not to render UI during it).

## Validation

- **Synthetic**: none feasible (animation is browser-rendered in kiosk mode; no Python test path).
- **IRL gate**: power-cycle the Pi in the car. CIO observes the boot splash plays from screen-on through to dashboard hand-off; key-off triggers the shutdown splash; both animations visible + smooth on the production HDMI panel.
- **Preview path**: open `specs/UI/dist/splash-pi/preview.html` on Windows in any modern browser to sanity-check boot + shutdown animations side-by-side before any Pi work.

## Notes

- This is **polish**, not infrastructure. Filing now so the kit doesn't drift unnoticed against `deploy-pi.sh` evolution. CIO directive 2026-05-21: file as backlog item; integrate after V0.27 chain merge.
- The 6.5 s boot splash window roughly coincides with the existing eclipse-obd / eclipse-powerwatch bring-up window -- a nice visual "system is coming up" cover. No functional blocker to launching them simultaneously.
- Related: B-007 (HDMI tap-to-cycle, dependent on B-052), B-052 (HDMI canvas redesign, RESOLVED Sprint 21). B-103 is a sibling -- it touches the same display but only at boot/shutdown, not during normal dashboard operation.
