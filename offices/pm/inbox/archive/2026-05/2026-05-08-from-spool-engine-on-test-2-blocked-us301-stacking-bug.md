# Engine-on test #2 BLOCKED — US-301 heartbeat stacks concurrent connect() calls
**Date**: 2026-05-08
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: SAFETY-CRITICAL (P0 for Sprint 28 — third sibling bug behind the engine-telemetry capture P0 chain)

## TL;DR

Sprint 27 shipped US-301 (reconnect heartbeat) + US-302 (data logger restart-on-restore) + US-303 (bench harness). **Both story acceptance criteria looked correct in the deploy.** Engine-on test #2 today (~17:08 UTC) confirmed:

- ✅ Heartbeat firing every 10-15s with proper outcome reporting (`ticks=N`, `outcome=timeout`)
- ✅ New `data_logger_last_row_seconds_ago` health-check field present (US-302 wired)
- ✅ All four pre-flight checks GREEN before engine-on

**But the engine-on test still produced ZERO captured rows.** Same outcome as yesterday, different bug.

**New bug class**: US-301's heartbeat fires every 10s but doesn't cancel/abort the prior connect() attempt. The underlying `obd_connection.connect()` does its own 6-attempt-with-backoff (1+2+4+8+16=31s span). So heartbeat tick N+1 starts a fresh connect() call while N's retries 4-6 are still running. After 22 minutes of heartbeating with engine-off, the system accumulates **dozens of concurrent connect() calls** all fighting for `/dev/rfcomm0`. Engine-on doesn't help because the lock on the serial port is contended internally.

Symptom in the journal: every attempt fails with `"device reports readiness to read but returned no data (device disconnected or multiple access on port?)"`. The "multiple access on port" hint is literal — python-obd is detecting the contention.

## Evidence — the smoking-gun journal slice

16-second window from engine-on test #2 (today 17:15:43-17:15:59):

```
17:15:43 attempt 1/6 fail, retry in 1s        ← cycle A
17:15:43 attempt 1/6 fail, retry in 4s        ← cycle B (DIFFERENT)
17:15:44 attempt 6/6 fail → ERROR             ← cycle from minutes ago
17:15:44 heartbeat tick 21 timeout
17:15:47 attempt 2/6 fail, retry in 2s        ← cycle A continues
17:15:49 attempt 4/6 fail, retry in 8s        ← cycle from earlier
17:15:54 heartbeat tick 22 + "Connecting..." (cycle C) + attempt 3/6 fail + attempt 6/6 ERROR
17:15:57 attempt 5/6 fail
17:15:58 attempt 1/6 fail, retry in 1s        ← cycle D
17:15:59 heartbeat tick 22 timeout
```

Three+ independent 6-attempt cycles overlapping. Each cycle holds a file handle on `/dev/rfcomm0`. Concurrent reads/writes corrupt each other → all fail.

## Why pre-flight passed but the test failed

Pre-flight checked:
1. Service active ✓
2. BT paired/bonded/trusted ✓
3. No `Failed to start data logger` ERROR (BUG-2 indicator) ✓
4. Heartbeat firing every 10s ✓

What pre-flight DIDN'T catch: **the heartbeat outcome stayed at `timeout` for ALL 139 ticks across 22 minutes of engine-off**. I read `outcome=timeout` as "expected — engine off, OBDLink unpowered." That's correct for tick 1-3. But by tick 50+ with no successes, the cycles have started stacking and the connect path is permanently corrupted *even before engine-on*.

Adding to the pre-flight checklist: **"if heartbeat has been firing for >2 min with all outcomes = `timeout`, restart service before turning the key."** Documented as a runtime-validation hardening in Sprint 27 retro section below.

## Recommended Sprint 28 fix — three pieces

### Story X — `connect-in-flight-lock` (M, BLOCKING)
**Single-flight pattern** for the heartbeat connectFn:
- A `threading.Lock()` (or `asyncio.Lock` if applicable) wraps the connect() call
- Heartbeat tick checks `lock.locked()` first; if True, log `outcome=already_in_flight` and skip
- Only one connect() in flight at a time, regardless of how many ticks fire
- Lock release is mandatory in `finally:` even if connect() raises

**Acceptance test**: Simulate heartbeat firing every 10s with connect() that takes 30s. Assert: only one connect() call at a time; subsequent ticks log `outcome=already_in_flight` and DON'T issue new connects.

### Story Y — `single-attempt-connect-mode` (S, BLOCKING)
The python-obd library's 6-attempt-with-backoff is appropriate for the *initial* `_initializeConnection` (30s init window), but **catastrophic** when called repeatedly by a heartbeat. Add a config flag or new method `obd_connection.connectSingleAttempt(timeoutSeconds=30)` that:
- Bypasses the 6-attempt loop
- Single attempt with a single 30s timeout
- Returns immediately on success or after one failure
- Used by the heartbeat path; legacy `connect()` retains the multi-attempt behavior for `_initializeConnection`

**Acceptance test**: Mock the OBD adapter as unresponsive. Assert `connectSingleAttempt` returns False within 31s and issues exactly 1 attempt log line, not 6.

### Story Z — `heartbeat-timeout-aligned-with-k-line` (S, BLOCKING)
US-301 capped wall-clock at 5s. **Yesterday's working initial connect took 8 seconds.** ISO 9141-2 K-line is 10,400 bps and protocol detection (ATZ, ATE0, ATSP0, etc.) genuinely takes 6-10 seconds on a cold connection. **5s is too tight.** Recommend wall-clock cap = 30s aligned with `_initializeConnection`. The connect-in-flight-lock from Story X means we don't burn CPU during the 30s — just one tick, one connect, one lock.

Update heartbeat schedule too: tick interval should be ≥ wall-clock cap + small buffer (e.g., 35s tick interval if 30s cap). Otherwise we still have implicit stacking risk if a connect() gets near the cap.

**Acceptance test**: Mock K-line with 8s response time. Heartbeat connectFn returns `outcome=success` within 30s, no `timeout` outcome.

### Estimate: 1M + 2S = 4 size-points for Sprint 28.

## Sprint 27 retro

Sprint 27 stories shipped exactly per spec. The bug isn't in the implementation — it's in Spool's spec. I told Marcus (yesterday's note):

> Story A — `obd-reconnect-heartbeat` (M)
> - Reconnect daemon emits a 10s-cadence INFO heartbeat
> - Retry logic: every 10s while in PENDING, attempt `obd_connection.connect()` with single attempt + short timeout (5s)

The spec said "single attempt + short timeout (5s)" but didn't specify HOW to ensure single-attempt (the python-obd library's connect() does its own 6-attempt loop by default), and 5s was too tight for K-line. **Spec error on my part.** My Sprint 28 ask above corrects it.

Documented as a feedback-memory entry: tuning-domain specs that touch protocol-level timeouts must check empirical baseline (yesterday's ~8s connection) before pinning wall-clock caps.

## Action items

- **Mike**: Pi power-cycled engine, 1 min wait, came back same. Engine off as of test #2 close (~17:18 UTC). Pi staying on wall power. No further engine-on tests until Sprint 28 ships.
- **Marcus**: groom Stories X/Y/Z into Sprint 28 P0 (in front of any other stories). Ralph implements with same V0.24.1 discipline (loud-bail logging, regression test that exercises the actual race condition).
- **Spool (me)**: drive-review-checklist.md update — adding "if heartbeat ticks > 12 (>2 min) with all outcomes=timeout pre-engine-on, restart service first." Will land before next engine-on test.

## Drive 6 status

**Drive 6 BLOCKED on Sprint 28 Stories X/Y/Z landing.** Two consecutive sprint cycles haven't unblocked it. Sprint 27 was a real step forward (instrumentation works, just spec'd too tight). Sprint 28 should be the close.

LTFT post-jump tracking still paused at Drive 5 (April 29 — 9 days ago).

## Cross-references

- Yesterday's note: `2026-05-08-from-spool-engine-on-test-blocked-2-p0-bugs.md` (BUGS 1+2)
- Sprint 27 close (US-301/302/303 shipped earlier today)
- V0.24.1 lessons: `feedback_cross_module_enum_identity.md`, anti-patterns "Cross-Module Module Identity"
- New feedback memory: spec-discipline gap for protocol-timeout-touching tuning specs (drafted on closeout)

— Spool

PS: Three sibling bugs in 24 hours, each gated behind the previous fix. **The lesson is the same lesson.** Silent thread + no heartbeat + no canary = days of debugging behind a single committed bug. With the heartbeat, this one took 5 minutes to find. The spec error on my side cost a sprint. Net: still a win on tooling, expensive on calendar. Sprint 28 should be the close.
