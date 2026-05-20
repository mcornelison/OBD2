---
name: Sweep 2a Complete — AlertManager Tiered Rewire
description: B-040 structural reorg Sweep 2a of 6 merged to main 2026-04-13. Sweep 2 split into 2a (rewire) + 2b (delete) after audit found AlertManager was 100% legacy-bound. AlertManager now consumes config['tieredThresholds']. RPM fires at 7000 Spool-authoritative.
type: project
originSessionId: f73c7f38-9bca-4d2f-bee4-e06da0d8b4d0
---
# Sweep 2a — COMPLETE, merged to main 2026-04-13

## State
- **Merge commit**: `418b55b` on main
- **Main fast-suite**: 1503 passed, 3 skipped, 19 deselected (1499 baseline + 7 new Task 3 tests − 3 mark-skipped, exact match)
- **Full suite**: 1521 passed, 4 skipped (pre-merge branch state)
- **Sprint branch `sprint/reorg-sweep2a-rewire`**: retained until Sweep 2b merges (plan rule — branches only deleted 7+ days after merge)
- **Main is now 20+ commits ahead of origin, NOT pushed** — CIO has not requested push
- **Sprint branches still alive**: `sprint/reorg-sweep1-facades` (safe to delete — 2a merged), `sprint/reorg-sweep2a-rewire` (retain for 2b reference), `sprint/reorg-sweep2-thresholds` was renamed to 2a mid-sweep (it no longer exists as a separate branch)

## Why Sweep 2 was split into 2a + 2b

Task 2 audit of the original monolithic Sweep 2 plan uncovered a blocker: `AlertManager.setProfileThresholds()` is the ONLY wiring path feeding threshold values to alert firing, and it reads `profile.alertThresholds` (legacy dict) exclusively. `AlertManager` has zero references to `tieredThresholds`. Deleting the legacy system in one pass would have left alert firing inert (AlertManager would have no thresholds).

**Resolution**: Split.
- **Sweep 2a (this one)** — the logic change: teach AlertManager to consume tiered, rewire callers. No deletions. Medium risk.
- **Sweep 2b (queued)** — the cleanup: pure dead-code deletion of the now-orphaned legacy files. Low risk.

## What Sweep 2a delivered

1. **`src/alert/manager.py`**: Added new public method `setThresholdsFromConfig(config: dict[str, Any]) -> None` that reads `config['tieredThresholds']`, builds `AlertThreshold` objects for RPM (from `rpm.dangerMin`, direction ABOVE) and coolant temp (from `coolantTemp.dangerMin`, direction ABOVE), and populates `_profileThresholds[profileId]` with a fresh per-profile copy. Raises `AlertConfigurationError` on missing tiered section. Legacy `setProfileThresholds()` method **remains alive** for Sweep 2b deletion.
2. **`src/alert/helpers.py`**: `createAlertManagerFromConfig()` now calls `manager.setThresholdsFromConfig(config)` instead of the legacy per-profile loop.
3. **`src/obd/orchestrator.py`**: Profile-switch handler no longer reads `newProfile.alertThresholds` or calls `setProfileThresholds()`. Thresholds are global (tiered) and bound once at AlertManager construction. Profile switching still updates active-profile tracking + polling interval; it just doesn't touch thresholds.
4. **15 test files** updated with a minimal `tieredThresholds: {rpm: {dangerMin: 7000}, coolantTemp: {dangerMin: 220}}` section in their local fixture configs:
   - 13 `test_orchestrator_*.py` files (all of them)
   - `test_simulate_db_validation.py`
   - `test_e2e_simulator.py`
5. **3 tests mark-skipped** in `test_orchestrator_alerts.py` and `test_orchestrator_profiles.py` where their premise (profile-switch rebinds threshold values) is invalidated by the new global-tiered model. Skip reason: `"Sweep 2a: profile switching no longer rebinds thresholds — see sprint/reorg-sweep2a-rewire"`. These tests are preserved (not deleted) for Sweep 2b to review.
6. **7 new unit tests** in new file `tests/test_alert_manager.py` covering the new method (TDD-first).

## Semantic changes (CIO Option A approved)

- **RPM redline**: was 6500 (daily) / 6000 (performance) via legacy `profile.alertThresholds.rpmRedline`; now **7000** from `tieredThresholds.rpm.dangerMin`. 7000 is the Spool-authoritative value from US-139 hotfix (97-99 2G factory redline, softer cam than 95-96 2G).
- **Coolant temp critical**: unchanged at 220°F.
- **Boost pressure alerts**: SILENT. Legacy had `boostPressureMax`; tiered has no `boostPressure` section. Spool hasn't specced it. **Follow-on backlog**: Spool adds tiered boost, Ralph wires it.
- **Oil pressure alerts**: SILENT. Same reason. Follow-on backlog.
- **STFT / battery / IAT / timing alerts**: pre-existing coverage gap. Task 2 investigation confirmed these were NEVER wired to any consumer — the tiered evaluation modules (`tiered_thresholds.py`, `iat_thresholds.py`, `timing_thresholds.py`) exist with stateful trackers but nothing outside tests instantiates them. **`fuel_detail.py` has its own inline `_evaluateFuelTrim()` with hardcoded thresholds** that bypasses the tiered evaluator entirely. Tech debt note: `offices/pm/tech_debt/TD-alert-coverage-stft-battery-iat-timing.md`.

## What's still alive (Sweep 2b removes it)

- `src/alert/thresholds.py` (170 lines — `convertThresholds`, `checkThresholdValue`, `getDefaultThresholds`, `validateThresholds`)
- `Profile.alertThresholds` field + `DEFAULT_ALERT_THRESHOLDS` constant + `getAlertConfigJson()` method in `src/profile/types.py`
- `alert_config_json` column in `profiles` table (`src/obd/database.py:122`) — Sweep 2b needs a schema migration to drop it
- `profiles.availableProfiles[*].alertThresholds` + `profiles.thresholdUnits` in `src/obd_config.json`
- `AlertManager.setProfileThresholds()` legacy method in `src/alert/manager.py`
- `_validateAlertThresholds()` function + default-profile injection in `src/obd/config/loader.py`
- `getAlertThresholdsForProfile()` in `src/alert/helpers.py`
- `THRESHOLD_KEY_TO_PARAMETER` constant in `src/alert/types.py`

All are orphaned (no production callers) but physically present. Sweep 2b is a pure dead-code delete.

## Preservation verified at two layers

1. **Config file layer**: `diff /tmp/tiered-before.json /tmp/tiered-after.json` → empty. The `tieredThresholds` section of `obd_config.json` is byte-identical to pre-sweep state.
2. **Runtime layer**: `createAlertManagerFromConfig(realConfig)._profileThresholds['daily']` contains `AlertThreshold(parameterName='RPM', threshold=7000.0, direction=ABOVE)` and `AlertThreshold(parameterName='COOLANT_TEMP', threshold=220.0, direction=ABOVE)`. Same for `performance` profile.

## Documents filed

- **PM inbox** (backlog candidates): `offices/pm/inbox/2026-04-13-from-ralph-sweep2a-scope-and-backlog.md` — covers: tiered boost spec request, tiered oil-pressure spec request, STFT/battery/IAT/timing investigation, alert_config_json column drop (2b scope).
- **Tech debt**: `offices/pm/tech_debt/TD-alert-coverage-stft-battery-iat-timing.md`
- **Sweep 2a plan**: `docs/superpowers/plans/2026-04-13-reorg-sweep2a-rewire.md` (748 lines) — source of truth for how 2a was executed.
- **Audit notes**: `docs/superpowers/plans/sweep2-audit-notes.md` — per-file line numbers, classifications, migration plans. Still useful for 2b execution; do not delete until 2b merges.
- **Original Sweep 2 plan**: `docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md` — obsolete for 2a, parts still inform 2b.
- **Design doc session log row** appended at `docs/superpowers/specs/2026-04-12-reorg-design.md` section 12.

## Commits on the sprint branch (9 total)

1. `4f781a7` sweep 2 audit notes (pre-split)
2. `802da47` 2a plan + PM inbox scope note
3. `9b1eea6` Task 2 non-AlertManager path trace (Verdict B)
4. `5f527fb` Task 3 implementation (setThresholdsFromConfig)
5. `c3238aa` Task 3 code review fixes (mod history, context manager, pathlib)
6. `a930819` Task 4 rewire (helpers.py, orchestrator.py)
7. `549f05f` Task 5 (13 orchestrator fixture updates)
8. `19ff044` Task 5 stragglers (simulate_db_validation, e2e_simulator)
9. `6a794f2` Task 8 design doc log row

Merge commit on main: `418b55b`.

## Next (Sweep 2b)

Sweep 2b is a **pure dead-code delete** — every file listed in "What's still alive" above. Low risk, maybe 2-4 hours of work. No cooling period needed between 2a and 2b. A new plan file should be written: `docs/superpowers/plans/2026-04-14-reorg-sweep2b-delete.md` (or similar). It should include:
- SQLite schema migration to drop `alert_config_json` column (requires version bump)
- Test for the 3 mark-skipped tests in 2a: read them, decide delete-or-rewrite-or-keep-skipped
- Final ruff/mypy/full suite pass, CIO approval, merge

The original Sweep 2 plan at `docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md` has reusable Tasks 3-8 material for 2b; don't start from zero.
