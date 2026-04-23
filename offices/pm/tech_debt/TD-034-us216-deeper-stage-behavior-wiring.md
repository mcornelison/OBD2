# TD-034: US-216 deeper stage-behavior wiring (no_new_drives flag, sync push, poll-tier stop, BT close, DriveDetector.forceKeyOff)

**Status:** Open
**Filed:** 2026-04-22 (Agent 2 / US-216 session)
**Priority:** Medium — cosmetic / graceful-degradation scope. The US-216 primary bug fix (Pi hard-crashing at 0% SOC) is already closed by the state machine + `systemctl poweroff` at TRIGGER@20% + legacy suppression.
**Related:** US-216 (shipped 2026-04-22), Spool audit `offices/pm/inbox/2026-04-21-from-spool-power-audit.md`
**Filed by:** Agent 2 (Ralph)

## What

US-216's acceptance criteria mention concrete stage behaviors beyond the state machine + battery_health_log + poweroff:

* **WARNING@30%**: set DB flag `pi_state.no_new_drives=true`; trigger SyncClient force-push if network up.
* **IMMINENT@25%**: stop poll-tier dispatch (no new Mode 01 queries); close BT via US-211 clean-close API; call `DriveDetector.forceKeyOff(reason='power_imminent')`.
* **AC-restore**: clear `no_new_drives`, resume polling.

These were wired as **lightweight log-only callbacks** in `src/pi/obdii/orchestrator/lifecycle.py::_wirePowerDownOrchestratorCallbacks` during US-216 close-out because the integrations require API additions on multiple runtime components. The IMMINENT callback includes a best-effort `getattr(self._driveDetector, 'forceKeyOff', None)` probe that is a no-op today because `DriveDetector` doesn't expose `forceKeyOff` yet (the API lives on `EngineStateMachine`).

## Why this is safe as TD (not a US-216 blocker)

1. **Primary bug fix stands alone**: the 2026-04-20 hard-crash was caused by the Pi reaching 0% SOC without any shutdown fire. TRIGGER@20% → `ShutdownHandler._executeShutdown()` → `systemctl poweroff` closes that bug without the soft behaviors.
2. **Systemd stop cascade**: `systemctl poweroff` runs the service stop hooks, which in turn close BT, stop polling, and flush drive summaries via each component's existing destructor/close path. The 30–45s graceful-shutdown window is sufficient.
3. **Regression test passes**: `tests/pi/power/test_ladder_vs_legacy_race.py` proves the new ladder fires before the legacy 10% trigger — the race TD-D identified in Spool's audit is resolved.

## What the deeper wiring would add

| Behavior | Component touched | Net win |
|----------|-------------------|---------|
| `pi_state.no_new_drives` DB flag | `src/pi/data/database.py` (new flag) + `src/pi/obdii/drive/detector.py` (check before minting drive_id) | Prevents drive-count drift if the car is turned over briefly during a drain (edge case). |
| SyncClient force-push on WARNING | `src/pi/sync/client.py` (add `forcePush()` API) + `lifecycle.py` callback | Captures in-flight data before poweroff. Today the next boot handles it. |
| Poll-tier stop on IMMINENT | `src/pi/obdii/orchestrator/core.py::runLoop` (add `pauseAllTiers()`) | Stops ECU traffic ~10s earlier. Cosmetic. |
| BT clean-close on IMMINENT | `src/pi/obdii/bluetooth_helper.py` US-211 API call | Cleaner disconnect. Systemd kills it anyway. |
| `DriveDetector.forceKeyOff(reason=...)` | New method on DriveDetector that delegates to its `EngineStateMachine` | Closes the active drive + runs drive-end analytics pre-poweroff. |

## Suggested shape for the follow-up story

* **Size**: M (one sprint). Touches 4-5 runtime components; each integration is small but they are scattered.
* **Testing**: new orchestrator tests with **concrete** callbacks (not mocks) hitting an in-memory DB + mocked subprocess. Verify `no_new_drives` gate on `drive_id` minting. Verify `forceKeyOff` fires on active drive during IMMINENT.
* **Non-scope**: do NOT revive PowerMonitor / BatteryMonitor / power_log (Spool audit per-file dispositions stay).

## Verification that current close is safe

* `pytest tests/pi/power/ tests/pi/hardware/test_shutdown_handler_legacy_suppress.py tests/pi/integration/test_staged_shutdown_drill.py` — 37/37 passing.
* Orchestrator is confirmed active in production when (a) `pi.power.shutdownThresholds.enabled=true`, (b) DB initializes (BatteryHealthRecorder constructs), (c) ShutdownHandler available. Lifecycle-level log line: `PowerDownOrchestrator stage-behavior callbacks wired`.
* Docs pointer: `docs/testing.md` "Staged-Shutdown Drain Drill (US-216 Power-Down Orchestrator)" covers the CIO-facing drain observation protocol.

## Why **not** to take this into Sprint 16 cleanup

Sprint 16 (Wiring) is already at 10/10 once US-216 lands. TD-034 is neither urgent nor risky; leaving it for a fresh sprint grooming lets Marcus scope it against the actual Sprint 17 theme rather than bolting it on at the end of Wiring.
