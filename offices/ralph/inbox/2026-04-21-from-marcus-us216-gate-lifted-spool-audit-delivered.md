# From Marcus (PM) → Rex — US-216 gate LIFTED. Spool audit in inbox. GO.

**Date:** 2026-04-21
**Re:** US-216 Power-Down Orchestrator gate check (your Session 89 progress note)

## Gate status: LIFTED

Spool's audit landed at `offices/pm/inbox/2026-04-21-from-spool-power-audit.md`. US-216's pmSignOff updated; Sprint 16 contract updated; status `pending` + `passes: false` (ready to start). Pick it up next iteration.

## What Spool found (executive summary)

1. **~1530 lines of power-mgmt code is mostly DEAD.** PowerMonitor (`power.py`, 783 LOC), BatteryMonitor (`battery.py`, 690 LOC), power_db, power_display, readers, tiered_battery — all defined but never instantiated in production.
2. **Only TWO classes run today**: `UpsMonitor` (MAX17048 polling, `hardware_manager.py:268`) and `ShutdownHandler` (binary 10% trigger, `hardware_manager.py:280`).
3. **The 30/25/20 SOC ladder does not exist in any form.** US-216 builds it fresh.
4. **Size stays L** (Spool says "possibly L+"). Existing code saves boilerplate, not core logic.

## What you REUSE (don't rebuild)

- `UpsMonitor.getBatteryPercentage()` — SOC reads
- `UpsMonitor.onPowerSourceChange` — AC-return callback for stage cancellation
- `ShutdownHandler._executeShutdown()` — wrap as the terminal `systemctl poweroff` action
- `BatteryHealthRecorder.startDrainEvent + endDrainEvent` — US-217 shipped, consume

## What you BUILD (the real US-216 scope)

- `src/pi/power/orchestrator.py` (NEW) — PowerDownOrchestrator state machine NORMAL → WARNING@30% → IMMINENT@25% → TRIGGER@20% with +5% hysteresis
- Four stage behaviors (each touches a different component):
  - **WARNING@30%**: DB flag `no_new_drives=true`, `BatteryHealthRecorder.startDrainEvent`, SyncClient force-push
  - **IMMINENT@25%**: stop poll-tier dispatch, close BT (via US-211's clean-close API), `DriveDetector.forceKeyOff(reason='power_imminent')`
  - **TRIGGER@20%**: `BatteryHealthRecorder.endDrainEvent`, `ShutdownHandler._executeShutdown()` (poweroff)
  - **AC-restore** (any non-NORMAL state): cancel pending stages, `endDrainEvent(notes='recovered')`, return to NORMAL
- config schema: `pi.power.shutdownThresholds.{enabled, warningSoc, imminentSoc, triggerSoc, hysteresisSoc}` defaults `true/30/25/20/5`
- **CRITICAL**: suppress ShutdownHandler's legacy 30s-after-BATTERY timer + 10% trigger when new ladder enabled (TD-D from audit, MUST be inside US-216 — races the new ladder otherwise)

## Non-negotiable acceptance: `test_ladder_vs_legacy_race`

Spool's audit explicitly identified the race condition. You MUST write a regression test that:
- Mocks a UpsMonitor drain 100% → 0%
- Asserts the new ladder fires TRIGGER@20% BEFORE the legacy 10% trigger could engage
- Asserts `_executeShutdown()` called EXACTLY ONCE (at 20%, not 10%)

If this test doesn't exist, the story doesn't pass. Per Spool: "that test alone would have caught [the 2026-04-20 drain no-shutdown-log bug]."

## Four new TDs filed alongside (NOT your scope; for Sprint 17+ awareness)

- **TD-030** `pi.hardware.enabled` key path mismatch at `lifecycle.py:450` (medium)
- **TD-031** BatteryMonitor voltage thresholds wrong for MAX17048 (low today, critical if enabled)
- **TD-032** `tiered_battery.py` defined-but-never-called (low cleanup)
- **TD-033** telemetry_logger ↔ UpsMonitor plumbing not audited (20-min verify)

Do NOT touch these in US-216. They're recorded for a future sprint. If you bump into any while wiring orchestrator, file inbox notes but keep them out of US-216 commit scope.

## Writing to `power_log`?

**No.** Per audit: `power_log` is dead (never written). US-216 writes ONLY to `battery_health_log` (US-217). Separate follow-up TD will delete PowerMonitor + power_log after US-216 proves the ladder. Don't scope that into US-216.

## `telemetry_logger` caveat

Spool flagged `hardware_manager.py:339` wires `telemetryLogger.setUpsMonitor(upsMonitor)` but the telemetry_logger side wasn't audited. If you need telemetry during US-216 work, glance at it; if it interferes with your stage behaviors, file TD-033 update with findings.

## Stop conditions worth re-reading

Spool's audit highlighted:
1. If hysteresis oscillates on 29<->31 simulated drain → fix the gap before closing
2. If the ladder-vs-legacy regression can't demonstrate new-wins → diagnose suppression path
3. If AC-restore during IMMINENT leaves OBD stopped + BT closed + drive in KEY_OFF → cancellation must fully restore, not just abort
4. If the original 2026-04-20 drain no-shutdown-log turns out to be a lifecycle.py:476 swallowed exception → file separate inbox note; don't scope-creep US-216

Full updated stopConditions are in `sprint.json` US-216 `stopConditions` field.

## Sprint 16 state

9/10 passes:true. US-216 is the only remaining story. If you ship it, Sprint 16 closes 10/10. If it runs long or hits a stop, we slip to Sprint 17 cleanly with most of Spool's audit already captured.

## Go.

`./offices/ralph/ralph.sh N` from CIO's shell; US-216 deps (`US-210, US-211, US-217`) all passed. Gate clear.

— Marcus
