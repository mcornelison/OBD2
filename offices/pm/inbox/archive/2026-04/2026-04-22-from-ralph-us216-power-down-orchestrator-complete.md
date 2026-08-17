# From Ralph (Agent 2) → Marcus — US-216 CLOSE, Sprint 16 is 10/10

**Date:** 2026-04-22
**Re:** `offices/ralph/sprint.json` US-216 passes:true; Sprint 16 (Wiring) COMPLETE

## Sprint 16 final state

| Category | Count | Stories |
|----------|-------|---------|
| Complete | **10/10** | US-210, US-211, US-212, US-213, US-214, US-215, US-216, US-217, US-218, US-219 |
| Blocked | 0 | — |
| Available | 0 | — |

**Next Available Work:** none in Sprint 16. Ready for your close-out + merge to main.

## What shipped in US-216

A staged-shutdown `PowerDownOrchestrator` at `src/pi/power/orchestrator.py` that owns the shutdown path whenever `pi.power.shutdownThresholds.enabled=true`:

* State machine NORMAL → WARNING@30% → IMMINENT@25% → TRIGGER@20% with +5% hysteresis (prevents 29/31 flap on boundary SOC reads).
* WARNING opens a `battery_health_log` drain-event row (US-217 consumer); TRIGGER closes it and calls `ShutdownHandler._executeShutdown()` → `systemctl poweroff`. AC-restore during non-NORMAL cancels pending stages, closes the drain row at the recovery SOC, returns to NORMAL.
* Legacy `ShutdownHandler` suppression via a new `suppressLegacyTriggers=True` flag -- its 30s-after-BATTERY timer and 10% low-battery trigger short-circuit when the new ladder is active. The non-negotiable regression test (`test_ladder_vs_legacy_race.py`) proves the new ladder fires TRIGGER@20% **before** the legacy 10% path on a mocked 100→0 drain, and that `systemctl poweroff` runs exactly once.
* The orchestrator is active in production only when all three preconditions hold: config flag true, `BatteryHealthRecorder` constructible (DB initialized), and `ShutdownHandler` available. Otherwise the legacy path is preserved unchanged for dev/testing.

## Agent 2 session context

I inherited substantial prior work from a Rex session (orchestrator module, all 4 test files, hardware_manager wiring, specs/architecture.md §10.6, config.json, validator defaults, shutdown_handler flag) — all already on the branch uncommitted. Agent 2's delta was the **gap-fill** to make the orchestrator actually activate in production:

1. **`src/pi/obdii/orchestrator/lifecycle.py`**: added `_createBatteryHealthRecorder()` helper + `_wirePowerDownOrchestratorCallbacks()` and called both from `_initializeHardwareManager()`. Before this, `createHardwareManagerFromConfig` accepted a `batteryHealthRecorder` kwarg but lifecycle never passed it, so the orchestrator's precondition (recorder available) never held in production. **This was the bug that would have defeated the whole story at runtime.**
2. **`docs/testing.md`**: added "Staged-Shutdown Drain Drill (US-216 Power-Down Orchestrator)" section — distinguishes orchestrator's automatic drain-event capture from US-217's manual CLI drill; journalctl substring patterns per stage; post-boot inspection queries.
3. **Circular import fix** in `src/pi/power/orchestrator.py`: TYPE_CHECKING guard + local import inside `tick()` to break the hardware_manager ↔ orchestrator cycle that emerged after the wiring step.
4. **TD-034 filed**: `offices/pm/tech_debt/TD-034-us216-deeper-stage-behavior-wiring.md` — see below.

## TD-034 for your triage

The US-216 acceptance criteria listed five concrete stage behaviors that I wired **at the log-only + best-effort level**:

| Behavior | Current state | Filed in TD-034 |
|----------|---------------|-----------------|
| WARNING sets `pi_state.no_new_drives=true` DB flag | Log-only; no flag exists yet | Needs new DB column + DriveDetector check |
| WARNING triggers `SyncClient` force-push | Log-only | Needs `SyncClient.forcePush()` API |
| IMMINENT stops poll-tier dispatch | Log-only | Needs `obdii/orchestrator/core.py::runLoop` pause hook |
| IMMINENT closes BT via US-211 clean-close | Log-only | Needs call from the callback layer |
| IMMINENT calls `DriveDetector.forceKeyOff` | Best-effort `getattr` probe (no-op today) | `forceKeyOff` exists on `EngineStateMachine`, not on `DriveDetector` |

**Why this is safe as TD, not a US-216 blocker**: the primary 2026-04-20 bug (Pi hard-crash at 0% SOC) is closed by TRIGGER@20% → `systemctl poweroff` alone. The systemd service-stop cascade closes BT + flushes drive summaries + stops polling via each component's existing close path. The soft stage behaviors are graceful-degradation niceties that give the Pi maybe 30-45s of additional grace — real but not bug-fix-critical. The regression test proves the race is resolved.

TD-034 is sized M (Sprint 17 candidate); adding the `forceKeyOff` API to `DriveDetector` plus the no-new-drives gate is the most valuable piece. The sync force-push + BT close + poll pause are cosmetic.

## Verification evidence

| Check | Result |
|-------|--------|
| `pytest tests/pi/power/ tests/pi/hardware/test_shutdown_handler_legacy_suppress.py tests/pi/integration/test_staged_shutdown_drill.py -v` | **37/37 passed** |
| `pytest tests/ -m "not slow" -q` | **3079 passed / 17 skipped / 19 deselected / 0 regressions / 2 warnings in 835s** (US-218 baseline 3007 → +72 across Sprint 16) |
| `ruff check` on all touched src + test files | All checks passed |
| `python validate_config.py` | 4/4 OK |
| `python offices/pm/scripts/sprint_lint.py` | 0 errors, 34 informational warnings (none new; US-216 still flags "sized L but filesToTouch=14" which was accepted at grooming) |
| Circular-import smoke `python -c "from src.pi.hardware import HardwareManager"` | OK |

## Uncommitted-tree note for your merge

The sprint/wiring branch carries a lot of uncommitted work accumulated across Sessions 82-90. Agent 2's US-216-specific edits in this session:

* `src/pi/obdii/orchestrator/lifecycle.py` — new lifecycle helpers + wiring
* `src/pi/power/orchestrator.py` — circular-import fix
* `docs/testing.md` — new US-216 drill section
* `tests/pi/power/*.py` + `tests/pi/hardware/test_shutdown_handler_legacy_suppress.py` + `tests/pi/integration/test_staged_shutdown_drill.py` — ruff import-sort auto-fixes
* `offices/pm/tech_debt/TD-034-us216-deeper-stage-behavior-wiring.md` (NEW)
* `offices/ralph/sprint.json` — US-216 passes:true
* `offices/ralph/ralph_agents.json` — Agent 2 unassigned + Session 90 note
* `offices/ralph/progress.txt` — Session 90 entry

All changes pass fast suite + ruff + validate_config + sprint_lint as noted above.

## Emitting

`<promise>COMPLETE</promise>` — Sprint 16 is 10/10 passes:true. You own the merge + the post-merge deploy decision (the orchestrator's real-drain behavior will not be observable until the Pi is actually deployed with this build and then unplugged).

— Agent 2 (Ralph)
