# Engine-on test BLOCKED — 2 P0 bugs sitting behind Sprint 25 fix
**Date**: 2026-05-08
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: SAFETY-CRITICAL (P0 for Sprint 26 — primary mission still broken)

## TL;DR

Sprint 25 fixed the 27-hour `_initializeConnection` hang exactly as scoped. **But two sibling bugs are sitting behind it that prevent ANY engine telemetry capture in the production-realistic flow.** CIO turned the engine on at ~10:00 UTC today; orchestrator stayed disconnected for 11+ hours leading up to it (BUG-1) and after manual service restarts brought the connection up, the data logger stayed dead (BUG-2). **Total `realtime_data` rows captured during ~15 min of engine-on test: ZERO.**

**Drive 6 cannot happen until both bugs are fixed.** Recommend folding into Sprint 26 as P0, in front of US-204 (DTC retrieval) which I requested in yesterday's note.

---

## BUG-1 — US-211 reconnect daemon doesn't actually reconnect

**Observed**: After Sprint 25 deploy yesterday evening (May 7 22:52 CDT), `_initializeConnection` hit its 30s timeout cleanly because OBDLink LX was unpowered (engine off). Orchestrator dropped to PENDING with the documented log line:

> `Initial connect timed out after 30.0s, runLoop starting in PENDING (connect daemon thread continues; US-211 reconnect path will transition to CONNECTED if/when adapter+ECU become responsive)`

**For the next ~11 hours, the connect daemon thread logged ZERO reconnect attempts.** No `connect | Connecting...`, no retries, no errors, nothing. Health check fired every 60s reporting `connection=disconnected`. The thread is supposed to keep trying — it didn't.

**When CIO turned engine on at ~10:00 UTC today**, OBDLink LX powered up, BT became reachable — and **the daemon still didn't reconnect**. We sat in `connection=disconnected` for the entire engine-on window.

Manual `systemctl restart eclipse-obd.service` succeeded in bringing BT and OBD up — but only via the fresh `_initializeConnection` path, not the US-211 reconnect path.

**Diagnosis**: Either the reconnect daemon thread silently died, has an unreasonable retry interval (hours-long), or its retry logic exits early. Same anti-pattern as V0.24.1 — silent thread, no heartbeat, no canary. The only way I detected this was by manual journal inspection.

**CIO's recommended fix** (his exact words):
> "I do think it should have a heartbeat of every 10 seconds listening and looking to see if the OBD Bluetooth is alive or shut off and was restarted"

Exactly right. Apply the V0.24.1 lesson:
- 10-second heartbeat from the reconnect daemon (similar to US-265's tickCount-snapshot probe)
- Boot-time canary that verifies the daemon thread is alive (similar to `_verifyOrchestratorCallbackWiring`)
- WARNING-level log line every retry attempt (loud bail anti-pattern)
- Health check should report **time-since-last-reconnect-attempt**, not just `connected/disconnected`

**Why this is not an outlier case** — once Pi is wired to ignition (CIO doing this weekend), this will be the COMMON path:
- Every key-on: Pi cold-boots, OBDLink LX powers up. Pi may boot faster than the OBDLink LX is ready to pair → `_initializeConnection` 30s timeout fires → reconnect path needs to take over within seconds.
- Mid-drive BT flap: momentary BT disconnect (interference, distance, OBDLink power glitch) → reconnect path needs to recover **without losing the current `drive_id`**.
- Post-shutdown sequence: when OBDLink LX cuts power, we need clean disconnect handling.

This bug is in the critical path for **every drive** going forward.

---

## BUG-2 — Data logger fails to restart after `_handleConnectionRestored`

**Observed**: First restart attempt today (10:07:59) — `_initializeConnection` timed out at 30s, runLoop entered with `Failed to start data logger: Cannot start realtime logging - not connected to OBD-II`. **8 seconds later** at 10:08:37, the connect daemon succeeded:

```
10:08:37 pid_probe | probeSupportedPids: discovered 17 Mode 01 PIDs
10:08:37 _handleConnectionRestored | OBD connection restored
10:08:37 obd_connection | Connected to OBD-II dongle | mac=00:04:3E:85:0D:FB | attempts=1
```

**OBD connection alive. ECU responding. 17 PIDs probed. `_handleConnectionRestored` fires.**

**Result**: ZERO new rows in `realtime_data`. The data logger started in failed state at 10:08:29 and **was never re-kicked** when the connection came back at 10:08:37. The orchestrator just kept polling health checks while the OBD link sat there idle and ignored.

**The `_handleConnectionRestored` callback is not wired to restart the data logger.** That's the bug.

**Recommended fix**:
- `_handleConnectionRestored` must (re-)initialize / start the realtime data logger
- If data logger was already running and connection drops, it must pause cleanly (not crash)
- If data logger was never started (PENDING-on-init case), `_handleConnectionRestored` is the trigger to first-start it
- Idempotent: calling start twice in a row should be safe (ignored or restart cleanly)
- Boot-time canary: data logger health-check that reports `last_row_written_seconds_ago` so we catch this in 60s, not 11 hours

This is NOT a US-285 issue — US-285 was the orchestrator init fix and it works correctly. This is a *separate* path: connection lifecycle event handling.

---

## What was confirmed working (don't lose this)

Sprint 25 P0 fix is **REAL and SOLID**:
- `_initializeConnection` returns within exactly 30s as documented (witnessed twice today during restart cycles)
- DriveDetector + SummaryRecorder + AlertManager + DataLogger + DtcLogger all init successfully
- PowerDownOrchestrator wiring self-test PASSED on every restart (V0.24.1 enum identity regression gate firing as designed)
- `startup_log` writer is firing rows on service start (US-287 GREEN)
- `battery_health_log` schema has new `start_vcell_v` / `end_vcell_v` columns (US-289 partial — writer-side untestable until next drain event)

The failure mode is purely in the **post-init connection lifecycle**: reconnect daemon silence + data logger one-shot startup.

---

## Test session evidence (chronological, all UTC)

| Time | Event | Outcome |
|---|---|---|
| 2026-05-07 22:52:38 | Service started (Sprint 25 deploy) | `_initializeConnection` 30s timeout fires clean (engine off, expected) |
| 2026-05-07 22:53:08 | runLoop enters PENDING | "connect daemon thread continues" — but no retries logged |
| 2026-05-08 ~10:00 | CIO turns engine on | **OBDLink LX powers up but reconnect daemon stays silent** |
| 2026-05-08 10:00-10:06 | 6+ min engine-on monitoring | `connection=disconnected` on every health check, NO reconnect attempts |
| 2026-05-08 10:07:59 | Spool runs `systemctl restart` (manual) | `_initializeConnection` 30s timeout fires (BT pairing takes time) |
| 2026-05-08 10:08:29 | runLoop enters with "Failed to start data logger" ERROR | **BUG-2 begins** — data logger in failed state |
| 2026-05-08 10:08:37 | `_handleConnectionRestored` fires, 17 PIDs probed | **OBD link alive but data logger NOT re-kicked** |
| 2026-05-08 10:08-10:10 | OBD connection alive | **Zero `realtime_data` rows written** |
| 2026-05-08 10:10:26 | Spool runs `systemctl restart` (second attempt) | `_initializeConnection` 30s timeout fires AGAIN (rfcomm release+re-acquire forces ELM327 settle window > 30s) |
| 2026-05-08 10:10:56 | runLoop enters with "Failed to start data logger" ERROR (second occurrence) | **BUG-2 reproduces** |
| 2026-05-08 ~10:11 | CIO shuts engine off | Test ended, total captured rows: 0 |

---

## Sprint 26 ask

**Add to Sprint 26 as P0, before US-204:**

### Story A — `obd-reconnect-heartbeat` (M)
- Reconnect daemon emits a 10s-cadence INFO heartbeat: `RECONNECT HEARTBEAT | ticks=N | last_attempt_seconds_ago=X | last_attempt_outcome=Y`
- Boot-time canary verifies thread is alive within 30s of runLoop entry; ERROR-logs if not
- Retry logic: every 10s while in PENDING, attempt `obd_connection.connect()` with single attempt + short timeout (5s)
- Loud-bail rules per V0.24.1 lesson: any silent path becomes a WARNING+ log line
- Regression test: simulate PENDING state, assert reconnect daemon makes ≥3 attempts in 30s with logged heartbeats

### Story B — `data-logger-restart-on-connection-restored` (S)
- `_handleConnectionRestored` triggers `dataLogger.start()` if not running
- `dataLogger.start()` is idempotent (safe to call repeatedly)
- Health check reports `data_logger_last_row_seconds_ago` (NEW field)
- Regression test: simulate init-without-connection → connection-restored → assert data logger starts and writes a row

### Story C — `engine-on-bench-harness` (S, deps Story A + B)
- Extend US-286's bench harness to simulate the production flow: service starts with no OBD adapter present → adapter wakes up later (mock) → assert reconnect path fires AND data logger starts AND row is written
- This is the regression gate that should have caught both bugs pre-deploy

**Total estimate**: 2M + 1S = 5 size-points for Sprint 26.

---

## Drive 6 status

**Drive 6 is gated on Stories A + B landing.** Until then, every engine-on test we run will produce zero data, same failure mode I just witnessed. CIO's car is coming out of storage this weekend and the Pi gets wired to ignition — both events make this MORE urgent, not less.

LTFT post-jump adaptation tracking remains paused. Last data point: Drive 5 (2026-04-29).

---

## Cross-references
- Sprint 25 close (US-284-291) just deployed today
- V0.24.1 lesson applied: `feedback_cross_module_enum_identity.md` + `specs/anti-patterns.md` Cross-Module Module Identity entry
- US-265 tickCount heartbeat pattern is the model for Story A
- `_verifyOrchestratorCallbackWiring` boot canary is the model for Story A canary
- US-211 was the original reconnect-path story (Sprint 14); appears the implementation didn't ship the heartbeat/canary discipline that V0.24.1 later normalized

---

## Engine-on test discipline (procedural ask)

For Sprint 26 + every future engine-on test, recommend the playbook explicitly say: **never spin the engine for capture without first verifying the Pi is showing CONNECTED state.** Quick check:

```bash
ssh chi-eclipse-01 'journalctl -u eclipse-obd.service --since "1 minute ago" | grep -E "(Connected to OBD|Failed to start data logger)" | tail -5'
```

If `Failed to start data logger` is in the output, do NOT proceed with capture — restart service first and re-verify. This is the kind of pre-flight check that should be in `offices/tuner/drive-review-checklist.md` Section A (pipeline integrity) before Section B (engine-on data review).

I'll add it to my checklist on close-out today.

---

— Spool

PS: CIO had the diagnostic instinct on this one. He asked verbatim if the issue was the Pi-on-wall-power-no-cycle scenario, AND independently proposed the 10-second heartbeat solution before I had the chance. Crediting that here so it's on the record. The "outlier case" framing is the only part I'd push back on — it's not outlier; it's the common path.
