# US-229 close -- drive_end ECU-silence signal shipped

**From**: Rex (Ralph / Agent 1) — Sprint 18 Session 100
**Date**: 2026-04-23
**Story**: US-229 — Fix drive_end not firing — ELM_VOLTAGE heartbeat keeps drive open past engine-off
**Status**: `passes: true`

## What shipped

Drive 3 (2026-04-23, engine-off 16:46:21 UTC) remained open in `connection_log` for 6+ minutes because the `DriveDetector` relied on RPM=0 readings continuing to arrive for its debounce — when the ECU went silent post-engine-off, python-obd returned null for RPM, `event_router` skipped the `processValue` call, and the below-threshold timer never started. Meanwhile `BATTERY_V` via `ELM_VOLTAGE` (adapter-level ATRV, not a Mode 01 PID) kept ticking every ~10 cycles, keeping `processValue` alive but giving no ECU liveness signal.

Fix: **ECU-silence drive_end** as a second path that runs alongside the existing RPM-debounce path.

- `decoders.py`: added `isEcuDependent: bool` to every `ParameterDecoderEntry` (6/7 `True`; `BATTERY_V` is the lone `False`).
- `decoders.py`: added `LEGACY_ECU_PARAMETERS` frozenset enumerating the legacy Mode 01 PIDs polled via the `getattr` fallback (RPM, SPEED, COOLANT_TEMP, ENGINE_LOAD, THROTTLE_POS, TIMING_ADVANCE, SHORT_FUEL_TRIM_1, LONG_FUEL_TRIM_1, INTAKE_TEMP, O2_B1S1, CONTROL_MODULE_VOLTAGE, INTAKE_PRESSURE) + a drift-guard test in `test_decoder_metadata.py::TestLegacyEcuParametersFrozenset::test_legacyEcuParameters_coversCollectorPollTiers` that fails CI if a new config.json tier adds a Mode 01 PID without updating the frozenset.
- `decoders.py`: added `isEcuDependentParameter(name: str) -> bool` helper with three-way resolution (registry explicit → legacy frozenset → default False for unknowns).
- `drive/detector.py`: new `_lastEcuReadingTime` attribute; stamped in `processValue` on every ECU-sourced tick, seeded in `_startDrive`, cleared in `_endDrive`. New `_checkEcuSilenceDriveEnd` method runs after `_processRpmValue`: if `_currentSession` open + state ∈ {RUNNING, STOPPING} + `now - _lastEcuReadingTime ≥ driveEndDurationSeconds`, calls `_endDrive()`.
- `specs/architecture.md` Section 5 Drive Lifecycle: added a **Drive-end detection (US-229)** subsection with the two-path table + distinguishing-rule explainer.

## Decisions worth surfacing

**No new config knob** — reused `driveEndDurationSeconds` (60s default) as the silence timeout. The story's invariant said "pick a value ≥ 30s aligned with US-200 30s KEY_OFF debounce." 60s satisfies that and avoids config-surface bloat; the two paths share the same debounce window, so whichever signal crosses first fires drive_end. Idempotent `_endDrive` makes a rare same-tick race harmless.

**Safe default for unknown parameters is `False`** — per invariant "Missing metadata defaults to False (safe for unknown adapter-level commands)." The three-way resolution in `isEcuDependentParameter` ensures unknown params don't silently extend drive_end, while still explicitly accounting for every ECU PID actually polled by the collector.

**Scope-fence honorarium (refusal rule #3)** — story's `filesToTouch` listed `tests/pi/obdii/test_decoder_metadata.py` + `tests/pi/obdii/test_drive_end_detection.py` (new files) and I created exactly those two. No orchestrator or event_router changes were needed: those files already route every parameter reading to `DriveDetector.processValue`, which is where the new logic hooks.

**Did NOT touch `src/pi/obdii/engine_state.py`** — story listed it in filesToTouch ("if engine_state transition logic consumes 'rows arriving': filter similarly") but the existing `EngineStateMachine.observeReading` already has the right shape: it refuses to advance state on a `None` RPM reading (`if rpm is None: return None`). The ELM_VOLTAGE heartbeat never reaches `observeReading` because event_router only feeds RPM/SPEED to the state machine. So no change is structurally required there; noting here for visibility.

**Did NOT touch `dtc_client.py`** — story asked to "confirm these are ECU-sourced" in filesToRead. Confirmed: Mode 03/07 DTC queries are ECU-sourced. But DTCs flow through a separate event-driven path (MIL rising-edge in `event_router._handleNewReading`), not the periodic `processValue` tier; they aren't a regular heartbeat signal, so tagging them is not load-bearing for US-229. If/when DTC retrieval becomes part of the silence heartbeat we'd tag it then.

## Verification

- 49 new tests pass (32 unit in `test_decoder_metadata.py` + 17 unit+integration in `test_drive_end_detection.py`).
- Full fast suite regression check: running as I write this closure note; baseline post-US-228 was 3212 passed / 17 skipped / 0 regressions. Expected delta: +49 = 3261 passed. Will flag in progress.txt if the delta diverges.
- `ruff check` clean on all 4 touched files.
- `sprint_lint.py`: 0 errors, 23 pre-existing sizing warnings (identical baseline to US-228 close).

## Real-world verification (deferred — for CIO next cold-start drive)

On a normal engine-off with BT staying connected:
1. Expect `connection_log` to carry a `drive_end` row with `timestamp` within ~60s of engine-off (silence debounce fires, no `error_message` reason code since this is debounce-driven not force-key-off).
2. `sqlite3 ~/Projects/Eclipse-01/data/obd.db "SELECT MAX(timestamp) FROM connection_log WHERE event_type = 'drive_end'"` should show a value not older than the drive's engine-off time + ~60s.
3. Drive 3's already-open row stays open (this is a forward-fix; Drive 3's `drive_end` row is gone forever unless hand-inserted, and even then the 6-min-plus drive-duration stamp would be wrong). Reopen a fresh drive to verify fix.

If the first post-deploy cold-start drive still leaves `drive_end` unfired:
- Check journalctl for `"drive_end via ECU silence | elapsed="` log lines. If absent, `_checkEcuSilenceDriveEnd` isn't being called — indicates `processValue` isn't being invoked at all post-engine-off (e.g., OBDLink BT dropped). If present but no drive_end row persists, the DB write in `_logDriveEvent` is failing (check for `"Failed to log drive event:"` right after the silence log).
- Fallback: bump `pi.analysis.driveEndDurationSeconds` to 30s in `config.json` if 60s is too loose; drop to 90s if the two-path races cause duplicate close attempts (still safe per idempotency but noisier in the log).

## Follow-ups NOT in scope

- **DTC retrieval heartbeat**: Mode 03/07 is event-driven not periodic, so it's not feeding the silence timer. If a future story wants DTC-retrieval-aware drive-end detection we'd add `isEcuDependentParameter` coverage there too.
- **Orchestrator-level silence**: the detector is the right place for this since it's the drive state machine. But if the collector's main loop hangs (different bug class), `processValue` won't get called at all and the silence check never runs. That's a different failure mode — likely US-232 SIGTERM responsiveness or a future watchdog story.
- **Engine state machine adoption**: US-206's _lastEngineState tracking is still a minimal shadow of `EngineStateMachine`. Full adoption remains out of scope per the existing carve-out in Section 5.

-- Rex (Agent 1 / Ralph) 2026-04-23
