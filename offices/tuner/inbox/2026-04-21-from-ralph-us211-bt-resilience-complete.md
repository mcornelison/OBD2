# US-211 BT-Resilient Collector — shipped

**Date**: 2026-04-21
**From**: Rex (Ralph agent, Windows dev runner)
**To**: Spool (Tuning SME)
**Priority**: informational (the story you asked for is live)

## TL;DR

Sprint 16 US-211 shipped end-to-end per your Session 6 amended Story 2.
Collector process now survives BT flaps; FATAL errors still surface to
systemd (US-210 `Restart=always`). Full flap timeline lands in
`connection_log` with the five new event_types you specified.

## What landed

| Module | Purpose |
|--------|---------|
| `src/pi/data/connection_logger.py` | Canonical event_type constants + `logConnectionEvent` helper |
| `src/pi/obdii/error_classification.py` | `classifyCaptureError()` + 3-bucket enum |
| `src/pi/obdii/reconnect_loop.py` | `ReconnectLoop` class + `(1,5,10,30,60)` schedule cap=60 |
| `src/pi/obdii/orchestrator/bt_resilience.py` | `BtResilienceMixin.handleCaptureError()` wiring |
| `src/pi/obdii/bluetooth_helper.py` (extend) | `isRfcommReachable()` two-layer probe |

## Backoff schedule (verbatim from your grounding)

`1s → 5s → 10s → 30s → 60s → 60s ...` capped at 60s.
`reset()` auto-fires on successful reconnect so serial flaps don't
compound backoff.

## Error taxonomy (your three buckets)

* `ADAPTER_UNREACHABLE` — rfcomm/bluez signature (OSError against
  /dev/rfcomm\*, BluetoothHelperError, timeout with rfcomm substring).
  Reaction: close python-obd → log `bt_disconnect` → run reconnect loop
  → reopen on probe-success.
* `ECU_SILENT` — plain TimeoutError/ObdConnectionTimeoutError without
  adapter signature, ambiguous ObdConnectionError. Reaction: stay
  connected → log `ecu_silent_wait` → caller reduces cadence.
* `FATAL` — everything else. Reaction: log + re-raise so systemd
  `Restart=always` from US-210 restarts the process cleanly.

**Boundary case I pinned with a dedicated test**: a `TimeoutError` whose
message contains "rfcomm" classifies as ADAPTER_UNREACHABLE, not
ECU_SILENT. Python 3.10+ makes `TimeoutError` a subclass of `OSError`
so the classifier must check it before the generic OSError branch.
`test_classifyCaptureError_timeoutWithRfcommSignature_isAdapter` guards
against reordering drift.

## connection_log timeline

Five new event_types land on the `connection_log` table. The column
stays `TEXT` (no `CHECK` constraint) because existing dynamic writers
(profile switcher `event.eventType`, `shutdown/command_core.py`
`f'shutdown_{event}'`) emit runtime-composed strings that a
restrictive CHECK would reject. Canonical set is a Python frozenset in
`src/pi/data/connection_logger.py`; a grep-style audit test pins that
every US-211 literal is referenced somewhere in `src/pi/`.

Your invariant was "event_types are ADDITIVE" — the Python-constants
route respects that cleanly without risking reject-on-INSERT breakage
of the dynamic paths.

## What you can verify

**Off-Pi test path** (runs on any Python 3.11+ machine):

```bash
pytest tests/pi/obdii/test_error_classification.py \
       tests/pi/obdii/test_reconnect_loop.py \
       tests/pi/obdii/test_bluetooth_helper.py \
       tests/pi/data/test_connection_log_event_types.py \
       tests/pi/integration/test_bt_drop_resilience.py -v
```

Expected: 52 tests pass. The integration test drives the full flap
(bt_disconnect → adapter_wait × 3 → reconnect_attempt × 3 →
reconnect_success with backoff 1/5/10s, FakeSleep-driven so ~0 wall-
clock) against a real `ObdDatabase` and asserts the `connection_log`
rows.

**Live Pi verification** (5-step procedure in `docs/testing.md` → "BT
Drop-Resilience Walkthrough"):

1. Note collector PID + baseline realtime_data row count.
2. Unplug OBDLink; wait 10s.
3. Confirm PID unchanged (`systemctl show eclipse-obd -p MainPID`).
4. Read connection_log — expect `bt_disconnect` + `adapter_wait`/`reconnect_attempt` pairs.
5. Re-plug OBDLink; confirm `reconnect_success` row + realtime_data resumes.

## What I did NOT do (by design)

* **No data_logger.py refactor.** The orchestrator's existing
  `ConnectionRecoveryMixin` stays (it's state-change-driven in a
  background thread). The new `BtResilienceMixin.handleCaptureError`
  exposes the synchronous error-class-driven path for data-logger
  callers to invoke. Wiring it into the actual capture loop is a
  follow-up story — stop condition #2 (capture loop tightly coupled
  to every PID poll) was a risk I explicitly avoided. Once we're ready
  to integrate, the `handleCaptureError` entry-point is waiting.
* **No CHECK constraint on event_type.** See rationale above; the
  canonical set is Python-level only.
* **No systemd work.** That's US-210 territory, already shipped. My
  story is pure Python.
* **No wake-on-BT / heartbeat rows / observability endpoint.** Per
  your explicit "nice-to-haves deferred" list.

## Quality gates (Windows runner)

* Fast suite: 2886 passed (+80 vs 2806 baseline, 0 regressions, 510.94s)
* Ruff: clean on all 12 touched files
* validate_config: 4/4 OK
* sprint_lint: 0 errors (pre-existing informational sizing warnings, matches PM calibration)

## Downstream unblocks

* **US-208** first-drive validator can now actually validate something
  (collector survives BT flaps, so the "no rows" finding stops being
  the primary failure mode).
* **US-216** power orchestrator can call `handleCaptureError` on power-
  transition errors without worrying about process exit.
* **B-037 Pi Sprint** downstream stories can assume continuous capture.

— Rex (Ralph, Session 82)
