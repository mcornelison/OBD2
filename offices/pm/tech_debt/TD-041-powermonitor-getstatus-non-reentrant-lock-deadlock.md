# TD-041 — PowerMonitor.getStatus() deadlocks on non-reentrant `_lock`

| Field         | Value                                                            |
|---------------|------------------------------------------------------------------|
| Severity      | Medium                                                           |
| Status        | **Resolved 2026-05-01 (US-254, Sprint 21)**                      |
| Filed By      | Rex (Ralph Agent), Session 115 (US-243 work)                     |
| Filed Date    | 2026-04-30                                                       |
| Resolved By   | Rex (Ralph Agent), Session 126 (US-254)                          |
| Surfaced In   | `src/pi/power/power.py:762-783` (PowerMonitor.getStatus)         |
| Blocking      | Any future caller of PowerMonitor.getStatus(); blocks status     |
|               | display + diagnostic exports for the now-active power_log path.  |
| Related       | US-243 (B-050 PowerMonitor activation; this surfaced the bug)    |

## Problem

`PowerMonitor.getStatus()` (src/pi/power/power.py:762) acquires `self._lock`
and then calls `self.getStats()` (src/pi/power/power.py:596), which **also**
acquires `self._lock`. `self._lock` is constructed as `threading.Lock()`
(line 180), which is **not** reentrant — a thread that already holds the
lock will block forever waiting for itself.

```python
# Line 180 -- non-reentrant lock
self._lock = threading.Lock()

# Line 769 -- getStatus acquires the lock...
def getStatus(self) -> dict[str, Any]:
    with self._lock:                     # ACQUIRE
        return {
            ...
            'stats': self.getStats().toDict(),  # NESTED CALL

# Line 603 -- ...then getStats tries to acquire it again
def getStats(self) -> PowerStats:
    with self._lock:                     # DEADLOCK -- already held
        ...
```

**Empirical reproduction (US-243 Session 115):**
A unit test constructed PowerMonitor and called `getStatus()`. The test
hung indefinitely. Stack inspection showed both `with self._lock` sites
on the same thread; pytest never recovered without SIGTERM.

## Why this stayed latent

PowerMonitor was never instantiated in production until US-243 (Sprint 20),
so `getStatus()` had zero live callers. Every existing test that uses
PowerMonitor calls the lower-level `getStats()` directly, which works
fine on its own — only the **composition** in `getStatus()` deadlocks.

## Expected behavior

`getStatus()` returns a dict snapshot of the monitor's state without
deadlocking. Two acceptable fixes:

### Option (a) — Switch to `threading.RLock`

```python
self._lock = threading.RLock()
```

Reentrant locks allow the same thread to re-acquire. Zero call-site
changes. Lowest-risk fix; the only downside is RLock is slightly slower
than Lock and disguises the lock-aliasing the existing code is doing.

### Option (b) — Refactor `getStatus()` to avoid the nested acquisition

```python
def getStatus(self) -> dict[str, Any]:
    stats = self.getStats()  # acquires + releases lock
    with self._lock:
        return {
            ...
            'stats': stats.toDict(),
        }
```

Captures the stats snapshot *outside* the outer `with`, so only one
acquisition happens at a time. Matches the existing single-acquisition
pattern in `checkPowerStatus`. **Recommended** -- preserves Lock's
discipline, no perf change.

## Acceptance for fix

- [ ] `getStatus()` returns a dict without deadlocking on the same thread
- [ ] New unit test `test_getStatus_doesNotDeadlock` constructs a
      PowerMonitor and asserts `getStatus()` returns within 2 seconds
- [ ] No regression in existing PowerMonitor tests
- [ ] Audit: no other PowerMonitor methods compose `with self._lock`
      around an inner call that also takes `self._lock`

## Why this is filed (CIO Q1 rule)

Spotted during US-243 implementation, but US-243's `doNotTouch:
PowerMonitor's internal state machine logic` and `invariants:
PowerMonitor's internal state machine logic preserved verbatim --
only instantiation + subscription added` explicitly forbid touching
PowerMonitor internals. Per the drift-observation rule, filing
the TD now so Marcus can wrap into a future sprint story; the
US-243 lifecycle test was rewritten to use a different (deadlock-safe)
PowerMonitor read API as a workaround.

## Related

- **US-243 / B-050** — PowerMonitor activation; surfaced this bug because
  it's the first sprint that constructs PowerMonitor in production.
- **TD-032** — sister "code exists, never instantiated" pattern in the
  power-mgmt area; future cleanup of the broader power-mgmt surface
  (B-050 + TD-032 + TD-033) could consume TD-041 in the same sprint.

## Resolution (2026-05-01, US-254)

**Chosen fix: Option (a) — `threading.Lock` → `threading.RLock`.**

Initial attempt used Option (b) (capture `self.getStats()` snapshot
outside the outer `with self._lock` block).  That fixed the *direct-call*
shape -- `getStatus()` invoked from a thread that does not yet hold
`_lock` -- but did NOT fix the broader scenario the US-254 acceptance
calls out: a callback fires from inside `checkPowerStatus()`'s locked
section and itself calls `getStatus()`.  In that path, the producer
thread already holds `_lock`; even with Option (b)'s reordering, the
inner `getStats()` call still tries to re-acquire the same non-reentrant
Lock and deadlocks.

`RLock` is the only fix that addresses both shapes: the same thread can
re-acquire freely.  The TD-041 author's note that RLock "disguises the
lock-aliasing the existing code is doing" is acknowledged but accepted
-- the lock-aliasing is what callbacks-from-locked-sections require to
work at all, and is documented in the docstrings of `getStatus()` and
the `_lock` attribute.

### Files touched

- `src/pi/power/power.py` -- `_lock` constructor switched to
  `threading.RLock()`; `getStatus()` docstring documents the
  reentrant contract; modification history entry appended.
- `tests/pi/power/test_power_monitor_db_write.py` -- new
  `TestGetStatusNoDeadlock` class with two tests:
  1. `test_getStatus_doesNotDeadlock_returnsWithinTimeout` -- direct
     call from a fresh thread (the original empirical reproduction).
  2. `test_getStatus_calledFromInsideCallback_doesNotDeadlock` -- the
     canonical scenario the story scope calls out: a reading callback
     registered on `PowerMonitor.onReading` fires from inside
     `checkPowerStatus()`'s locked section and calls `getStatus()` from
     within that callback.  Pre-fix this hung indefinitely; post-fix
     returns within 2s.

  Both tests use a `threading.Thread` with 2s `join(timeout=...)` so a
  deadlock surfaces as a hard timeout rather than hanging the pytest
  run -- the daemon thread is abandoned cleanly.

### Audit of all `with self._lock` sites

`rg "with self._lock" src/pi/power/power.py` returned 6 sites:
| Line | Method            | Composes nested lock acquire? |
|------|-------------------|-------------------------------|
| 286  | `start`           | No (leaf acquirer)            |
| 309  | `stop`            | No (calls only non-locked private helpers) |
| 416  | `checkPowerStatus`| No (calls non-locked private helpers + callbacks) |
| 603  | `getStats`        | No (leaf acquirer)            |
| 623  | `resetStats`      | No (leaf acquirer)            |
| 769  | `getStatus`       | **Yes** (calls `self.getStats()`) |

Only `getStatus` had the nested-acquire bug.  RLock makes the
nested-acquire safe; the other 5 sites are unaffected.

### Verification

- `pytest tests/pi/power/test_power_monitor_db_write.py -v` -- 9/9 PASS
  (7 existing + 2 new TD-041 close tests).
- `pytest tests/pi/power/ tests/pi/hardware/ tests/pi/integration/
  -m "not slow"` -- 200 passed / 11 skipped / 0 regressions.
- `ruff check src/pi/power/power.py
  tests/pi/power/test_power_monitor_db_write.py` -- All checks passed.
- `python validate_config.py` -- All validations passed.
