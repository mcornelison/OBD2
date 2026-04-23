# From Marcus (PM) → Rex — Sprint 17 loaded. GO when CIO gives shell-side go.

**Date:** 2026-04-22
**Branch:** `sprint/tuning-safety` (from main@ea6e71e)
**Baseline:** fastSuite=3079, ruffErrors=0

## Theme: Tuning-Safety + Resilience Integration

Close aged safety debt from Spool Session 3, finish Sprint 16's US-211 integration, trim dead code Spool's power audit surfaced. Three of Spool's top-priority tuning-domain asks land this sprint.

## 6 stories (1M + 5S ≈ 12 points)

**P0 — safety + resilience**:
1. **US-220** (M) Legacy threshold hotfix bundle — US-140/141/142/143/144 in one go
2. **US-221** (S) US-211 integration wiring — `handleCaptureError()` into `data_logger.py` capture loop

**P1 — audit cleanup**:
3. **US-222** (S) TD-030 `pi.hardware.enabled` key path fix (one-liner)
4. **US-223** (S) TD-031 delete dead BatteryMonitor + `battery.py` + `battery_log` (~700 LOC)
5. **US-224** (S) `record_drain_test.py` CLI default flip `production` → `test`
6. **US-225** (M) TD-034 US-216 deeper stage wiring — `forceKeyOff` + `no_new_drives` flag + `forcePush` + poll-pause

**All stories are independent** (no cross-deps). Pick any order; P0 first is a suggestion, not a constraint.

## US-220 values are NON-NEGOTIABLE

| Fix | From | To |
|---|---|---|
| US-140 coolantTempCritical | 110 (nonsense) | 220 with explicit Fahrenheit unit |
| US-141 rpmRedline (legacy profile) | 7200 | 7000 |
| US-142 boostPressureMax | 18 psi | 15 psi |
| US-143 BOOST_CAUTION / BOOST_DANGER | 18.0 / 22.0 | 14.0 / 15.0 |
| US-144 INJECTOR_CAUTION | 80.0% | 75.0% (DANGER 85.0 stays) |

Values come straight from Spool's Session 3 variance report (`offices/pm/inbox/2026-04-12-from-spool-code-audit-variances.md`). **Do NOT re-derive.** If a value looks off during implementation, file inbox to Marcus before changing.

## US-221 preserves US-211 exactly as shipped

Don't re-tune US-211's backoff schedule `(1, 5, 10, 30, 60)` — Spool flagged the 10s intermediate as minor spec-drift in her Sprint 16 review but accepted it. Same for the 3-bucket classifier — scope is wiring into `data_logger.py`, not redesign.

## US-223 is DELETE only — leave these ALONE

- `src/pi/power/orchestrator.py` (US-216 — the replacement)
- `src/pi/power/battery_health.py` (US-217 — separate from BatteryMonitor)
- `src/pi/hardware/ups_monitor.py` (LIVE)
- `src/pi/hardware/shutdown_handler.py` (LIVE)

Spool's audit explicitly marked BatteryMonitor + `battery.py` + `battery_log` as dead. The server-side `battery_log` table gets a DROP via idempotent migration (use the US-213 gate path; do not fork).

## US-225 is the graceful-degradation layer on US-216

TD-034 closes the 4 stage behaviors Agent 2 left log-only at US-216 ship:

| Stage | New API |
|---|---|
| WARNING | `pi_state.no_new_drives` DB flag + `SyncClient.forcePush()` |
| IMMINENT | `runLoop.pausePolling()` + `DriveDetector.forceKeyOff(reason)` + US-211 clean BT-close |
| AC-restore | clear all of the above, resume polling |

All stage effects MUST fully unwind on AC-restore — test verifies. `forceKeyOff` wraps the existing `EngineStateMachine.forceKeyOff` (already present); DriveDetector delegates.

## Spool parallel deliverables (NOT your stories)

Tracked in sprint.json `sprintNotes` so they don't get lost:
- **First real-drive review ritual** — Spool runs US-219 against a real drive_id post-drill, grades Ollama output against DESIGN_NOTE.md's 6 quality gates
- **DSM DTC interpretation cheat sheet** — Spool docs work, post-drill
- **TD-033 `telemetry_logger` ↔ UpsMonitor audit** — 20-min Spool audit

If any of Spool's deliverables land in inbox during the sprint, note them but don't pick up as stories — they're her lane.

## Story counter

nextId = **US-226** (US-220 through US-225 consumed).

## No L stories this sprint

Sprint 17 is mostly small-cap cleanup. No Spool-audit-gates, no regressive changes. Good sprint for steady throughput.

## Go when CIO says go

`./offices/ralph/ralph.sh N` from CIO's shell.

— Marcus
