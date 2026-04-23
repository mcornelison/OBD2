# US-221 Closure — BT-Resilience Integration Wired

**Date:** 2026-04-22
**From:** Rex (Ralph Agent 1)
**To:** Spool (Tuning SME)
**Re:** Sprint 17 MUST-SHIP Section 3 — closes your US-211 YELLOW concern.

## TL;DR

`handleCaptureError()` is now wired into `RealtimeDataLogger._pollCycle`.
Next real drive's BT flap stays in-process (same PID across the gap).
Only FATAL surfaces to systemd. Your Sprint 16 release-readiness
Concern 1 ("integration gap -- the downstream unblock claims in
Ralph's note are aspirational until the wiring lands") is now met.

## What changed

### Wiring (production code)

`src/pi/obdii/data/realtime.py` — `RealtimeDataLogger` gets two new
`__init__` kwargs:
- `captureErrorHandler: Callable[[BaseException], CaptureErrorClass]`
- `onFatalError: Callable[[BaseException], None]`

Plus a new `ecuSilentMultiplier: int = 5` for cadence reduction.

`_pollCycle` now routes unexpected exceptions through
`_routeCaptureError` (new method):
- **ADAPTER_UNREACHABLE** — handler ran the reconnect loop
  synchronously; loop breaks to start the next cycle on the
  reopened connection.
- **ECU_SILENT** — handler logged `ecu_silent_wait`; loop enters
  silent mode (poll interval x 5 until next successful query
  clears it via `_onSuccessfulQuery`).
- **FATAL** — handler re-raised; loop sets `_stopEvent`, invokes
  `onFatalError(exc)` which signals orchestrator shutdown. systemd
  `Restart=always` (US-210) bounces.

`_queryParameterSafe` unwraps `ParameterReadError.__cause__` when it's
a capture-boundary exception so the classifier sees the real cause
(OSError, TimeoutError, ObdConnectionError) not the wrapper. Null-
response ParameterReadError (no `__cause__`) still short-circuits
as benign.

`src/pi/obdii/data/helpers.py` — `createRealtimeLoggerFromConfig`
threads the two new kwargs through.

`src/pi/obdii/orchestrator/lifecycle.py` — `_initializeDataLogger`
passes `self.handleCaptureError` and `self._onCaptureFatalError`
(new method) when building the RealtimeDataLogger. The fatal hook
flips `_shutdownState=FORCE_EXIT` with `EXIT_CODE_FORCED`.

### Tests (new)

- `tests/pi/obdii/test_capture_loop_integration.py` — 18 unit tests
  covering constructor shape, ADAPTER/ECU/FATAL routing, cadence
  multiplier, restore-on-success, backward compatibility when no
  handler is wired, and the `__cause__` unwrap path.
- `tests/pi/integration/test_bt_flap_in_process.py` — 7 integration
  tests driving the full wiring end-to-end with a `_FlappingObd`
  fake that raises rfcomm errors then recovers. Asserts same PID
  before/after, canonical connection_log event sequence, no
  unhandled exception, and that a FATAL cause survives the
  ParameterReadError wrapping (doesn't get misclassified).

### Existing tests (one update)

`tests/test_orchestrator_data_logging_config.py::test_initializeDataLogger_passesConfig_toFactory`
now asserts the two new kwargs are passed through. Not a behavior
change -- the old assertion literally forbade additional kwargs,
which was the contract the wiring was violating.

### Docs

- `specs/architecture.md` Section 5 "Collector Resilience" — new
  "Capture-loop integration (US-221)" subsection with an example
  timeline for a 2-second BT drop.
- `docs/testing.md` "BT Drop-Resilience Walkthrough" — updated
  header (now references US-211 + US-221), added explicit note that
  PID-unchanged is load-bearing after US-221, and a new "ECU-silent
  cadence (US-221)" subsection explaining the silent-mode journal
  grep.

## Spool-specific invariants respected

Checked against your US-221 story invariants (sprint.json):

- ✓ **Process stays alive on ADAPTER_UNREACHABLE + ECU_SILENT** —
  integration test `test_btFlap_sameProcessRecovers_notAProcessRestart`
  asserts `os.getpid()` unchanged + orchestrator never received a
  FATAL signal.
- ✓ **FATAL bubbles to systemd** — `test_fatal_setsStopEventAndSignalsOrchestrator`
  asserts `_stopEvent.is_set()` + `onFatalError` called with the
  original exception. Orchestrator's `_onCaptureFatalError` sets
  `EXIT_CODE_FORCED` so the process exits non-zero and systemd
  `Restart=always` bounces.
- ✓ **connection_log event types are ADDITIVE** — no new event_types
  added, no existing ones removed. All writes go through the
  existing `logConnectionEvent` + US-211 constants.
- ✓ **Backoff schedule unchanged** — ReconnectLoop untouched; still
  `(1, 5, 10, 30, 60)` capped.
- ✓ **Classifier logic untouched** — did NOT change
  `classifyCaptureError` or `CaptureErrorClass`.

## ECU-silent multiplier decision

The story says "Ralph picks conservative multiplier per Spool's spec."
I picked **5x** as the default (exposed as
`DEFAULT_ECU_SILENT_MULTIPLIER=5` in `realtime.py`, overridable via
`RealtimeDataLogger.__init__` kwarg).

Rationale: at the 100ms daily-profile cadence this slows to 500ms
during engine-off / key-on sessions, which eases pressure on the
silent ECU without sacrificing responsiveness when the engine comes
back (first successful query clears silent mode immediately).

If you'd prefer a different multiplier based on your tuning-domain
knowledge of ECU timeout behavior, I can lift this to config
(`pi.resilience.ecuSilentMultiplier`) in a follow-up -- or change
the default now if you flag it before Sprint 17 closeout.

## Verification

- `pytest tests/pi/obdii/test_capture_loop_integration.py
  tests/pi/integration/test_bt_flap_in_process.py -v`
  → **25 passed** (18 unit + 7 integration).
- `pytest tests/pi/obdii/test_reconnect_loop.py
  tests/pi/obdii/test_error_classification.py
  tests/pi/integration/test_bt_drop_resilience.py
  tests/test_orchestrator_data_logging_*.py -q`
  → **66 passed** (existing US-211 + orchestrator regression; zero
  broken by the wiring).
- Full fast suite: running at close-out; results in final progress.txt.
- `ruff check` on touched files: **clean**.
- `python validate_config.py`: **All validations passed**.
- `sprint_lint.py`: **0 errors** (18 warnings, all pre-existing
  Sprint 17 sizing informationals).

## What I did NOT do

Per Scope Fence (rule #3):

- Did NOT change `BtResilienceMixin.handleCaptureError` or the
  classifier -- just wired them in. Your spec-drift flag on the
  10s backoff step stays as-is (accepted).
- Did NOT touch `ConnectionRecoveryMixin` -- the
  background-threaded state-change path still coexists with the new
  synchronous error-class path. Over time the former can be
  narrowed; that's out of US-221 scope.
- Did NOT change the drive state machine. ECU_SILENT does not
  trigger KEY_OFF; it's purely a poll-cadence modifier as per the
  story invariant.
- Did NOT touch Mode 01 PID polling tiers (US-199 scheduler).
  Silent mode is a cycle-level multiplier, not a tier reshape.

## Next real-drive expectations (Spool Sprint 16 §"Deploy posture")

Before US-221: "expect the systemd-level process-bounce signature in
the journal, not the in-process recovery signature US-211 ultimately
promises."

After US-221 (i.e., starting with the next drill after this
deploys): expect the in-process recovery signature. PID unchanged
across BT flaps. `connection_log` shows the canonical four-event
timeline (`bt_disconnect` → `adapter_wait` → `reconnect_attempt` →
`reconnect_success`). No journalctl `Restart=always` trigger for
ordinary BT drops; only genuinely FATAL exceptions reach the
systemd bounce path.

If the first real drive post-deploy shows a PID change during a BT
flap, treat it as a regression and file an inbox note -- that's the
scenario US-221's wiring is specifically meant to eliminate.

— Rex (Ralph Agent 1, Session 93)
