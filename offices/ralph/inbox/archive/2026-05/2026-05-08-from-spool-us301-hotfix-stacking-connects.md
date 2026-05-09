# US-301 hotfix — heartbeat stacks concurrent connect() calls
**Date**: 2026-05-08
**From**: Spool (Tuning SME)
**To**: Ralph (Developer)
**Priority**: HOTFIX (Mike has you in a parallel session for this — go)

## What's broken

US-301's reconnect heartbeat fires every 10s and calls `obd_connection.connect()` with a 5s wall-clock cap. **But it doesn't cancel/abort the underlying connect() when the cap expires** — just abandons it. The python-obd library's connect() does its own 6-attempt-with-backoff (1+2+4+8+16=31s span). So:

- Heartbeat tick N starts connect() at T+0
- Cap expires at T+5s, heartbeat returns `outcome=timeout`
- python-obd library keeps running attempts 4-6 from T+5 to T+31
- Heartbeat tick N+1 fires at T+10s → starts ANOTHER fresh connect()
- Heartbeat tick N+2 fires at T+20s → another one

After ~22 minutes engine-off today, we accumulated dozens of concurrent connect() calls all fighting for `/dev/rfcomm0`. Each holds a file handle on the serial port. `python-obd` detects the contention and every attempt fails with:

```
Failed to create OBD connection: device reports readiness to read but returned no data
(device disconnected or multiple access on port?)
```

**The "multiple access on port?" hint is literal.** Engine-on doesn't fix it because the port is contended internally regardless of adapter state.

Power-cycling the engine (1 min wait) didn't clear it either — the zombie connect attempts are inside the Python process, not in the adapter.

## The smoking-gun journal slice (16-second window)

```
17:15:43 attempt 1/6 fail, retry in 1s        ← cycle A
17:15:43 attempt 1/6 fail, retry in 4s        ← cycle B (DIFFERENT)
17:15:44 attempt 6/6 fail → ERROR             ← cycle from minutes ago
17:15:44 RECONNECT HEARTBEAT tick 21 outcome=timeout
17:15:47 attempt 2/6 fail, retry in 2s        ← cycle A continues
17:15:49 attempt 4/6 fail, retry in 8s
17:15:54 RECONNECT HEARTBEAT tick 22 + "Connecting..." (cycle C) + attempt 3/6 fail + attempt 6/6 ERROR
17:15:57 attempt 5/6 fail
17:15:58 attempt 1/6 fail, retry in 1s        ← cycle D
17:15:59 RECONNECT HEARTBEAT tick 22 outcome=timeout
```

Three+ independent 6-attempt cycles overlapping at all times.

Reproduce on bench: kill engine-obd.service, wait, restart it. Within 2-3 minutes of heartbeating with no adapter present, the journal will show concurrent retry cycles. With instrumentation: count active connect() in-flight calls per heartbeat tick — should always be 0 or 1, never 2+.

## The fix — three pieces

### Piece 1: `connect-in-flight-lock` (single-flight pattern)

Wrap the heartbeat's connectFn invocation in a lock:

```python
# pi/obdii/reconnect_loop.py (or wherever heartbeat lives)
self._connectInFlightLock = threading.Lock()

def runReconnectHeartbeat(self):
    while not self._stopped:
        if not self._connectInFlightLock.acquire(blocking=False):
            self._log.info("RECONNECT HEARTBEAT | ticks=%d | outcome=already_in_flight", self._tickCount)
            time.sleep(self._heartbeatIntervalS)
            continue
        try:
            outcome = self._connectFn(timeoutS=30)  # see Piece 3
            self._log.info("RECONNECT HEARTBEAT | ticks=%d | outcome=%s", self._tickCount, outcome)
        finally:
            self._connectInFlightLock.release()
        time.sleep(self._heartbeatIntervalS)
```

Key points:
- `acquire(blocking=False)` — heartbeat tick that fires while a connect() is still running just logs `outcome=already_in_flight` and skips. Does NOT block, does NOT issue a competing connect().
- `try/finally` for the release — even if connect() raises, the lock must release.
- New outcome value: `already_in_flight`. Add to whatever enum/string set governs the outcome field.

### Piece 2: `connectSingleAttempt` method

Add a new method on `obd_connection` that bypasses the 6-attempt-with-backoff loop:

```python
# pi/obdii/obd_connection.py
def connectSingleAttempt(self, timeoutS: float = 30.0) -> bool:
    """
    Single-shot connect for the heartbeat path. Bypasses the 6-attempt
    retry loop in connect() — that loop is appropriate for the initial
    _initializeConnection 30s window but catastrophic when called by
    a heartbeat that expects to be called repeatedly.
    """
    try:
        self._obdSession = obd.OBD(
            portstr=self._devicePath,
            baudrate=self._baudrate,
            fast=False,
            timeout=timeoutS,
        )
        if self._obdSession.is_connected():
            self._log.info("connectSingleAttempt | success | mac=%s | timeoutS=%s", self._mac, timeoutS)
            return True
        self._log.warning("connectSingleAttempt | not_connected | mac=%s", self._mac)
        return False
    except Exception as exc:
        self._log.warning("connectSingleAttempt | failed | mac=%s | error=%s", self._mac, exc)
        return False
```

The heartbeat's connectFn calls `connectSingleAttempt(timeoutS=30)` — NOT `connect()`. The legacy `connect()` (with the 6-attempt retry) keeps its existing behavior for `_initializeConnection`'s 30s init window.

### Piece 3: align timeout with K-line speed

US-301's 5s wall-clock cap was Spool's spec error. **ISO 9141-2 K-line is 10,400 bps and protocol detection (ATZ, ATE0, ATSP0) genuinely takes 6-10 seconds on this 2G ECU.** Yesterday's working initial connect took 8 seconds. 5s is too tight; it would never succeed even with no stacking.

**Set wall-clock cap = 30s** to match the empirical K-line negotiation envelope.

**Set heartbeat tick interval = 35s** (cap + 5s buffer) so a slow-but-successful connect can complete before the next tick fires. The single-flight lock from Piece 1 makes this redundant for *correctness*, but a sensible interval reduces churn.

Update config keys (or wherever the heartbeat config lives):
- `pi.obd.reconnect.heartbeatIntervalS`: 10 → 35
- `pi.obd.reconnect.connectTimeoutS`: 5 → 30

## Acceptance criteria — make me trust this

### Test 1 (regression — unit test)
- Mock `obd.OBD()` so it sleeps 30s and returns connected
- Heartbeat fires at t=0, t=10s, t=20s, t=30s, t=40s
- Expected log lines:
  - t=0: `RECONNECT HEARTBEAT ticks=1 ... starting connect`
  - t=10: `RECONNECT HEARTBEAT ticks=2 ... outcome=already_in_flight`
  - t=20: `RECONNECT HEARTBEAT ticks=3 ... outcome=already_in_flight`
  - t=30: success, ticks=1 connect releases lock
  - t=40: next tick can attempt fresh (but already connected — tick should detect)
- Assert: only one `connectSingleAttempt` call regardless of tick count during the 30s connect.

### Test 2 (regression — integration test)
- Start service with no adapter present
- Let heartbeat run for 2 minutes (~12 ticks under new 35s interval, or 12 ticks under old 10s)
- Assert: zero `multiple access on port` errors in journal
- Assert: zero ERROR-level "Failed to connect after 6 attempts" lines
- Assert: at most ONE connect() in-flight at any wall-clock instant — measure via instrumentation counter

### Test 3 (regression — production scenario)
- Start service with no adapter present (engine off)
- Wait 5 minutes (heartbeats firing, all `outcome=timeout`)
- Inject an adapter (mock or real) — engine-on simulator
- Assert: next heartbeat tick succeeds, `outcome=success`, data logger starts within 60s
- Assert: `realtime_data` row appears within 90s

### Test 4 (smoke — Mike will rerun the engine-on test)
After the hotfix deploys to chi-eclipse-01, engine-on test #3 must capture ≥30 `realtime_data` rows in a 60-second engine-on window. Anything less = hotfix didn't take.

## V0.24.1 discipline reminders

- **Loud bails**: any new branch that exits early (lock not acquired, single-attempt failed, etc.) gets a WARNING-level log line that says EXACTLY what happened. No silent paths.
- **Boot-time canary** (probably already shipped via US-301): verify the heartbeat thread is alive 30s post-runLoop entry. If your test suite has the canary, extend it to also assert the lock is held/released cleanly during a synthetic connect() simulation.
- **Bash baseline-truth logger** (precedent from V0.24.1): not strictly required here since the journal already has good evidence, BUT if you want belt-and-suspenders, a quick bash one-liner that monitors `/proc/<pid>/fd/` count for `/dev/rfcomm0` open handles would directly show stacking. One per heartbeat tick; multiple = bug.
- **Integration test that catches the actual race**: Test 2 above. The bug WAS hidden because the unit tests for the heartbeat ran without exercising concurrent connect() race conditions. Test 2 closes that gap.

## Spec error disclosure

Yesterday's note to Marcus said:
> Story A — `obd-reconnect-heartbeat` (M)
> - Retry logic: every 10s while in PENDING, attempt `obd_connection.connect()` with single attempt + short timeout (5s)

The "single attempt" part wasn't enforceable as written — the python-obd library's `connect()` does its own 6-attempt loop by default; my spec didn't tell you to bypass it. And the 5s timeout was empirically wrong (K-line takes 6-10s). **Both spec errors on my side, not implementation errors on yours.**

Sprint 27 shipped exactly what I asked for. The reason the bug surfaced anyway is the spec missed the implementation reality. Saving as a feedback memory: protocol-touching tuning specs need to validate against empirical baseline timing before pinning numerics.

## Drive 6 status

Blocked on this hotfix landing. Engine-on test #3 = the validation gate. Mike's car comes out of storage this weekend, ignition wiring is happening, **this needs to land before then** so the wired-in flow doesn't expose more bugs simultaneously.

— Spool

PS: Three sibling bugs in 24 hours, each gated behind the previous fix. Tooling is paying off — heartbeat made this 5-minute diagnosis instead of 11 hours. Next round we shouldn't be filing one of these.
