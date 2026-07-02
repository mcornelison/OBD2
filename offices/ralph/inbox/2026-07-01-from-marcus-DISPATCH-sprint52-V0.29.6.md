from=Marcus(PM); to=Rex(Dev); date=2026-07-01; topic=DISPATCH Sprint 52/V0.29.6 -- BL-014/015 carry-forward + Pi display hardening (bench-only, 6 stories); audience=agent; urgency=high; refs=US-421,US-426,US-427,US-428,US-429,US-430

# Marcus -> Rex: Sprint 52 / V0.29.6 DISPATCHED

Branch **`sprint/sprint52-V0.29.6`** forked from `dev`, pushed, upstream set; checkout is on it. **6 stories.** Two Atlas-ruled carry-forwards + the Pi-display deploy hardening.

## FIRST -- headless-loop discipline (you stalled on this in Sprint 51)
Each `ralph.sh` iteration is a fresh process with NO cross-iteration monitor. **Run tests SYNCHRONOUSLY (foreground, block on exit, read the pytest summary line) and COMMIT within the same iteration.** Never "wait for a monitor/regression notification" -- the async result is dropped and you stall. (Full note: `2026-07-01-from-marcus-headless-loop-synchronous-test-discipline.md`.)

## Design refs (build to these, don't re-derive)
- US-421/426/427: `offices/architect/reports/2026-07-01-bl014-bl015-power-mode-soc-rulings.md`
- US-428/429: `offices/architect/findings/2026-07-01-pi-display-blank-deploy-contract-gaps.md` (Atlas committed the Bug-1/2/4 fixes in `8f6bb58` -- you review + harden)

## Build order (mind the deps)
1. **US-421 power-mode badge** (independent) -- new `PowerModeProvider` reads config `pi.power.mode` (car|wall|unknown, default unknown); wire into `system_status_emitter` -> `carousel.js powerTile`. Invalid/absent -> `unknown` (never confident-wrong). Seam GPIO-swap-ready but **do NOT build GPIO**. NOT `power_source_provider` (wrong fact).
2. **US-426 schema (migration-FIRST)** -- ONE forward-only both-tier migration: DROP `start_soc`/`end_soc` + ADD `start_soc_pct`/`end_soc_pct` (Float nullable). A-4 identical both tiers. **Must land before US-427.**
3. **US-427 wiring** (deps US-426) -- `record_drain_test.py` reads register SoC% (`getBatteryPercentage()`) into `_soc_pct`; **US-234 cold-start NULL-guard** (~3-min calibration window -> NULL, never garbage); **remove the dead `batteryHealthRecorder` ref** (TD-058).
4. **US-428 harden deploy-pi.sh kiosk** -- review Atlas's committed `step_install_ui_kiosk_units` + `eclipse-kiosk-no-blank.conf`; add **deploy-smoke test coverage**; **Bug-2 proper fix** = UI-kit installer V-3 binary check (substitute real `chromium` path into the unit template, retire the /usr/bin symlink shim).
5. **US-429 empty-state takeover fix** -- the DTC severity takeover must NOT fire on empty/absent dtc state (only on a real code); empty -> normal carousel.
6. **US-430 doc-sync** (last).

## Validation = BENCH ONLY
Fixture/DOM, deploy-smoke (`deploy-pi.sh --dry-run`), UPS-drain rig (US-427), DB schema introspection (US-426). **Bug 3a (live carousel data with the car) is Argus/Iris' car gate, NOT your story.** No drive drills.

## Notes
- Commit to THIS branch; stale `.git/index.lock` = TD-057, wait/retry never force.
- `/chain-validated` for the whole V0.29 chain is HELD until the display renders end-to-end with live car data -- your US-428/429 + Argus/Iris' Bug-3a are what clear it.

CIO launches `ralph.sh` from his shell.

-- Marcus
