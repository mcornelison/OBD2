# TD-047: Orchestrator init needs subprocess isolation for python-obd I/O blocks

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | High                      |
| Status       | Open                      |
| Category     | architecture              |
| Affected     | `src/pi/obdii/orchestrator/lifecycle.py` (`_runInitialConnectWithTimeout`, `_queryWithTimeout`); `src/pi/obdii/obd_connection.py` |
| Introduced   | US-244 (Sprint 20, 2026-04-30) -- daemon-thread + Event.wait pattern works in synthetic tests but Spool's 2026-05-05 production evidence (boot 0: 82-min wait when configured for 30 sec) shows it drifts on Pi 5. |
| Created      | 2026-05-07                |
| Filed by     | Rex (US-284, Sprint 25)   |

## Description

The orchestrator init phase wraps python-obd I/O calls (`_connection.connect()` and now also `_connection.obd.query("VIN")` per US-284) in a daemon-thread + `threading.Event.wait(timeout=N)` pattern.  This is the cleanest in-process timeout enforcement Python offers, but it relies on the C extension releasing the GIL frequently enough for the main-thread wait timer to fire on schedule.

Spool's 2026-05-05 inbox note documented two production drift instances:

* Boot -1: 27-hour gap between `Creating real ObdConnection` and `VinDecoder started successfully` -- the configured 30-sec timeout effectively disarmed.
* Boot 0: 82-min gap between `_initializeConnection` start and `Initial connect timed out after 30.0s` WARNING -- so the WARNING did fire, but at 164x the configured value.

Likely cause: python-obd's `obd.OBD()` constructor probes ELM327 protocol via tight serial reads.  pyserial on Linux/Pi for rfcomm devices uses `serial.Serial.read()` which (on this hardware path) appears to hold the GIL longer than expected.  Main-thread `Event.wait(timeout=30)` becomes scheduler-starved.

US-284 added two mitigations within scope:

1. Wrapped the previously-unprotected `query("VIN")` in `_performFirstConnectionVinDecode` with the same daemon-thread + `Event.wait` pattern (`_queryWithTimeout`).  This narrows the bug class but inherits the same drift risk.
2. Added a `CRITICAL` log in `_runInitialConnectWithTimeout` that names the drift fact when wall-clock elapsed exceeds 1.5x the configured timeout.  Observability only -- cannot prevent the drift.

Neither mitigation closes the root cause.

## Why It Was Accepted

US-284's S/M scope explicitly allowed it (per stop-condition 3: "If python-obd library has no clean timeout-enforcement path -- STOP, document the library limitation + propose subprocess-isolation alternative as Sprint 26 follow-up").  Subprocess-isolation is an architectural change with cross-cutting concerns:

* Process boundary: connect attempt runs in a child process, parent reads result via `multiprocessing.Queue` or pipe.
* Termination: parent SIGKILLs child on timeout (kernel-level escape; no Python-level cooperation needed).
* State plumbing: connection object cannot be returned across the process boundary (`obd.OBD` instance has open file descriptors, threads, etc.); the parent must re-construct after the child reports success.
* Database side-effects: `_logConnectionEvent` writes to SQLite from inside `connect()`; child-process writes need careful handling to avoid double-logging.

This is days of work + risk -- not appropriate to bundle into US-284's "ship the wrap" scope.  The production gap is also bounded NOW by US-284's two mitigations: drift is observable in journals, and the VIN-query path no longer hangs even when the connect timeout drifts.

## Risk If Not Addressed

* **Likelihood**: Medium-high.  Spool's evidence suggests the drift is reproducible on every cold boot when the engine is off (which is most of the Pi's life).  US-284 narrowed the consequence but didn't close the cause.
* **Impact**: High.  When `_runInitialConnectWithTimeout` drifts, `_initializeAllComponents` is blocked at the connect step.  DriveDetector, OBD polling loop, and every downstream init step is delayed.  In Spool's boot -1 evidence, this delay was 27 hours -- the entire engine-on cycle was missed.  Even with US-284's wrap on `query("VIN")`, the connect step itself can still drift.

## Remediation Plan

**Sprint 26 candidate story** (proposed M, P0):

1. Refactor `_runInitialConnectWithTimeout` to dispatch `_connection.connect()` in a child `multiprocessing.Process`.
2. Use `multiprocessing.Queue` for the (success, error) result.
3. On timeout, `process.terminate()` (SIGTERM) then `process.kill()` (SIGKILL) -- guaranteed escape regardless of what the child is doing.
4. After successful child-reported connect, re-construct `ObdConnection` in the parent (the child's `obd.OBD` instance died with the child).
5. Validate via Drain Test 12 (engine-off cold boot timing): boot-to-DriveDetector-ready time consistently <60 sec across 5 cold boots.

**Acceptance gate**: post-deploy, the new `Event.wait drift detected` CRITICAL log (added by US-284) MUST NOT appear in journal for 5 consecutive boots.  If it does appear, subprocess isolation hasn't closed the drift.

**Reference precedent**: US-244 (Sprint 20) shipped the daemon-thread approach as the minimum-risk first cut.  US-284 (Sprint 25) added observability + narrowed the bug class.  Subprocess isolation is the third architectural step -- correct sequencing per the "ratchet" pattern from `specs/methodology.md`.
