# TD-064 — event_router still pushes OBD status + alert counts to the (retired) status-display API

**Filed by:** Rex (Ralph) — Sprint 61 / V0.29.15, 2026-07-22
**Origin:** US-485 (pygame `status_display` sunset)
**Severity:** low (cosmetic / dead-path drift — no functional impact)
**Type:** tech-debt

## What

US-485 fully retired the pygame `status_display` overlay. `HardwareManager.updateObdStatus`
and `HardwareManager.updateErrorCount` were kept as **documented no-op stubs** so the
orchestrator's best-effort status push in `event_router.py` stays valid without an
`AttributeError`:

- `src/pi/obdii/orchestrator/event_router.py:336` — `_handleAlert` → `updateErrorCount(errors=...)`
- `src/pi/obdii/orchestrator/event_router.py:544` — `_handleConnectionLost` → `updateObdStatus('reconnecting')`
- `src/pi/obdii/orchestrator/event_router.py:574` — `_handleConnectionRestored` → `updateObdStatus('connected')`

These three call sites now push data into a no-op sink. The information they carried
(OBD connection status + alert counts) reaches the HTML dashboard through the US-480
state-file emitters instead, so the pushes are pure dead-path residue.

## Why not fixed in US-485

Scope fence (Refusal Rule 3): US-485's scope was "retire `status_display.py` + its
orchestrator **launch path** + config flag." The `event_router` calls are a *runtime
status-push* into `HardwareManager`'s abstraction, not the launch path, and
`event_router` is a drive-path core module. Removing them also requires updating
`tests/test_orchestrator_alerts_registration.py`
(`test_handleAlert_updatesHardwareManager_withAlertCount` asserts the call). That is
behavioral change beyond the sunset story, so it was tracked here rather than smuggled
into an "S" story.

## Proposed fix (a future housekeeping story)

Remove the three `event_router` "Update hardware manager display (Pi status display)"
blocks and then delete the `updateObdStatus` / `updateErrorCount` no-op stubs from
`HardwareManager`. Update `tests/test_orchestrator_alerts_registration.py` accordingly
(drop or repurpose the two tests asserting `updateErrorCount` is called). Net result: no
no-op API, no void pushes.

## Files

- `src/pi/obdii/orchestrator/event_router.py` (3 call sites)
- `src/pi/hardware/hardware_manager.py` (the 2 no-op stubs)
- `tests/test_orchestrator_alerts_registration.py` (2 tests)
