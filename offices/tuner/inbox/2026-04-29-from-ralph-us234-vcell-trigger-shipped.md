# US-234 — VCELL trigger shipped (Sprint 19, Session 106 / Ralph Agent 1)

**To**: Spool, Marcus
**From**: Rex (Ralph Agent 1)
**Date**: 2026-04-29
**Story**: US-234 — Fix US-216 trigger source: switch SOC% → VCELL thresholds (3.70/3.55/3.45V)
**Sprint**: 19 — Runtime Fixes + Server Reconciliation
**Status**: passes:true (synthetic-test gate cleared; live drain test 5 is post-sprint action item per CIO no-human-tasks rule)

## What changed

- **Trigger source**: `PowerDownOrchestrator` now reads VCELL volts via `UpsMonitor.getVcell()` (new alias for `getBatteryVoltage()`). Old `tick(currentSoc=int)` is now `tick(currentVcell=float)`.
- **Thresholds**: warningVcell=3.70V, imminentVcell=3.55V, triggerVcell=3.45V, hysteresisVcell=0.05V (your 4-drain recommendation, no tuning needed to make tests pass).
- **State machine shape unchanged**: NORMAL → WARNING → IMMINENT → TRIGGER + AC-restore + hysteresis + callback isolation. All US-225/TD-034 stage-behavior wiring (DB no_new_drives flag, SyncClient force-push, OBD poll pause, force key-off, AC-restore unwind) preserved bit-for-bit.
- **battery_health_log schema**: unchanged per US-234 doNotTouch list. The `start_soc` and `end_soc` columns now hold VCELL volts post-US-234. **Pre-US-234 rows are SOC %; post-US-234 rows are volts.** Future analytics consumers must filter on drain-event start time, or we add a `unit` discriminator column / rename in Sprint 20+.
- **Production tick wiring**: `hardware_manager._displayUpdateLoop` now passes `telemetry['voltage']` instead of `int(telemetry['percentage'])` into `orchestrator.tick`. Same poll cadence (5s).

## Synthetic test fidelity (the runtime-validation-required gate)

`tests/pi/power/test_orchestrator_vcell_thresholds.py` mocks at the **`I2cClient.readWord` level** (the real MAX17048 chip-read entry point). The mock's discriminator design:

- VCELL register stair-steps 4.20V → 3.40V across 5 ticks (real I2C path: little-endian word → byte-swap → 78.125 µV/LSB → volts).
- **SOC register stays pinned at 60%** throughout — the production mis-calibration failure mode.
- CRATE register returns 0xFFFF (in-the-wild disabled state).

If this test ran against the pre-US-234 SOC%-based orchestrator code, every tick would see SOC=60 > warningSoc=30 and skip every stage. No battery_health_log row, no shutdownAction. The test passing here proves the new VCELL path catches the actual bug class.

The systemctl poweroff assertion routes through a real `ShutdownHandler._executeShutdown` so the chain orchestrator → handler → `subprocess.run(['systemctl', 'poweroff'])` is exercised end-to-end exactly as production runs it.

## Files touched (filesActuallyTouched)

Production:
- `config.json` — pi.power.shutdownThresholds: SOC keys → VCELL keys
- `src/common/config/validator.py` — DEFAULTS for new VCELL keys (SOC keys removed)
- `src/pi/hardware/ups_monitor.py` — added `getVcell()` alias + `getVcellHistory(seconds)` (the latter for US-235 BATTERY-detection follow-up)
- `src/pi/power/orchestrator.py` — `ShutdownThresholds` fields + `tick()` signature + `_evaluateThresholds` rewrite, `_highestBatterySoc` → `_highestBatteryVcell`
- `src/pi/hardware/hardware_manager.py` — display-loop tick wiring + factory ShutdownThresholds construction
- `specs/architecture.md` — Section 10.6 rewrite (state-machine diagram, threshold table, schema-reuse note, mod-history entry)

Tests (the pre-flight audit found 4 existing files using the old API; updated all to VCELL):
- `tests/pi/power/test_power_down_orchestrator.py` — UPDATE
- `tests/pi/power/test_orchestrator_stage_behavior_wiring.py` — UPDATE (named in scope.filesToTouch)
- `tests/pi/power/test_ladder_vs_legacy_race.py` — UPDATE (parallel-rail walk: VCELL 4.20→3.30 + SOC 100→0; legacy still consumes SOC)
- `tests/pi/integration/test_staged_shutdown_drill.py` — UPDATE
- `tests/pi/power/test_orchestrator_vcell_thresholds.py` — NEW (the discriminator gate)
- `tests/pi/power/test_orchestrator_vcell_hysteresis.py` — NEW

## Known schema-misalignment (Sprint 20+ candidate)

The doNotTouch list said "battery_health_log schema (US-217 stays; orchestrator just uses existing columns differently)" — so I wrote VCELL volts into `start_soc` / `end_soc` columns. The story's acceptance text mentioned a `start_vcell` column populated; that's not in the schema and would have been a doNotTouch violation. Ran with the doNotTouch interpretation. Future Sprint 20+ work could:

1. Rename columns to `start_vcell` / `end_vcell` (requires Pi schema migration).
2. Or add a `trigger_unit` column with values `'soc_pct'` (legacy) or `'vcell_v'` (post-US-234) so analytics can filter.
3. Or accept that all rows from this point forward are volts; drop pre-US-234 rows in a one-shot script (analytics value of legacy SOC% rows is near-zero after US-234 since the SOC% values were misleading).

Not in US-234 scope. Flagging for sprint-close grooming.

## Verification

```
$ python -m pytest tests/pi/power/test_orchestrator_vcell_thresholds.py \
                   tests/pi/power/test_orchestrator_vcell_hysteresis.py \
                   tests/pi/power/test_orchestrator_stage_behavior_wiring.py \
                   tests/pi/power/test_power_down_orchestrator.py \
                   tests/pi/power/test_ladder_vs_legacy_race.py \
                   tests/pi/integration/test_staged_shutdown_drill.py -v
... 43 passed in 114.67s

$ python -m ruff check src/pi/power/orchestrator.py src/pi/hardware/ups_monitor.py \
                       src/pi/hardware/hardware_manager.py src/common/config/validator.py \
                       tests/pi/power/ tests/pi/integration/test_staged_shutdown_drill.py
All checks passed!

$ python validate_config.py
All validations passed! Ready to run.

$ python offices/pm/scripts/sprint_lint.py
Summary: 0 error(s), 22 warning(s) across 8 stories
(All 22 warnings are pre-existing on Sprint 19 stories at sprint-load time;
US-234 introduced none.)
```

Test count delta: +9 net new tests (3 in vcell_thresholds, 3 in vcell_hysteresis, plus the 4 existing files renamed/restructured at parity).

## Post-sprint action items relevant to this story

Per the no-human-tasks-in-sprint rule, the following live verification belongs to CIO/Spool, not US-234:

- **Drain test 5** (full battery → trigger): with US-234 deployed (and US-235 deployed for BATTERY-detection), the next drain should fire WARNING / IMMINENT / TRIGGER stage transitions live AND populate `battery_health_log` with all three rows' worth of evidence. If TRIGGER fires but stages don't precede it, that's a US-235 BATTERY-detection issue (US-235 is the parallel sister story).
- **Schema-misalignment grooming**: surface for Sprint 20+ — rename columns OR add `trigger_unit` discriminator OR drop legacy rows.

— Rex (Ralph Agent 1)
