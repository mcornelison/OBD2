################################################################################
# File Name: test_initialize_connection_timeout.py
# Purpose/Description: US-284 -- bound the orchestrator init phase against
#                      unprotected python-obd I/O blockers (Spool engine-
#                      telemetry-regression P0; 27-hour boot-1 / 82-min boot-0
#                      production hangs root-caused to two adjacent classes:
#                      (a) Event.wait drift in _runInitialConnectWithTimeout
#                      (Pi-5 GIL contention from python-obd protocol probing,
#                      requires subprocess isolation -- Sprint 26 follow-up
#                      TD), and (b) unprotected obd.query() call in
#                      _performFirstConnectionVinDecode line 502 -- code-
#                      readable bug in the same I/O class, fixed here).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-07    | Rex (US-284) | Initial: pin _performFirstConnectionVinDecode
#               |              | wall-clock bound + _runInitialConnectWithTimeout
#               |              | drift-detection log.  3 classes:
#               |              | TestStaticQueryTimeoutWrapper (3 tests),
#               |              | TestPerformFirstConnectionVinDecodeBoundedReturn
#               |              | (2 tests), TestRunInitialConnectDriftDetection
#               |              | (1 test).
# ================================================================================
################################################################################

"""US-284 / Sprint 25 P0: bound init-phase python-obd I/O against indefinite hangs.

Spool's 2026-05-05 engine-telemetry-regression-p0 inbox note documents the Pi's
primary mission silently broken since Drive 5 (April 29).  Production journal
evidence: ``ApplicationOrchestrator._initializeConnection`` blocks the
orchestrator init thread for 27 hours (boot -1) / 82 minutes (boot 0) instead
of the documented 30-sec timeout.  Investigation findings (Rex, code-only,
no Pi access):

* US-244's daemon-thread spawn IS in place (``lifecycle.py:458-462``).
* Config default IS 30 sec (``config.json:203`` + ``validator.py:178``).
* python-obd library blocking — Spool's hypothesis 2 — is the most plausible
  production root cause.  Two distinct unprotected sites in the same class:

  1. ``_runInitialConnectWithTimeout`` uses ``connectDoneEvent.wait(timeout=
     timeoutSec)``.  Synthetic-env tests show this is correct (existing
     ``test_lifecycle_initial_connect_timeout.py`` is GREEN).  Production
     evidence shows it drifts on Pi 5 — likely GIL contention from
     python-obd's serial I/O during protocol probing starves the main-thread
     wait.  Fix requires subprocess isolation (kernel-level SIGKILL escape)
     beyond US-284's S/M scope; tracked as Sprint 26 follow-up TD.  THIS file
     adds a wall-clock drift-detection log so post-deploy journals will name
     the drift fact (instead of silently waiting on a timer that's broken).

  2. ``_performFirstConnectionVinDecode`` line 502 calls
     ``self._connection.obd.query("VIN")`` with NO timeout-wrapper.  python-
     obd's per-command timeout is set on the ``obd.OBD(timeout=...)`` ctor,
     but production evidence on the same I/O subsystem shows the timeout is
     not honored when the underlying serial / bluetooth subsystem hangs.  This
     IS the same bug class as Spool's hypothesis 2 (broadened from
     ``obd.OBD()`` ctor only to any python-obd call in the init chain).  THIS
     file adds the daemon-thread+Event.wait wrapper around the VIN query that
     mirrors US-244's pattern, bounding the call regardless of library
     behavior.

Tests pin three contracts:

1. ``TestStaticQueryTimeoutWrapper`` -- new ``_queryWithTimeout`` helper
   bounds an arbitrary ``self._connection.obd.query(command)`` call.  Daemon-
   thread + Event.wait pattern; success / timeout / error tuple identical to
   ``_runInitialConnectWithTimeout`` shape.
2. ``TestPerformFirstConnectionVinDecodeBoundedReturn`` -- the VIN-query
   site honors the wrapper.  Pre-fix this test FAILS (``query("VIN")`` blocks
   indefinitely; the worker-thread-with-pytest-timeout idiom catches the hang
   in 2 sec instead of the production 27-hour hang).  Post-fix it PASSES.
3. ``TestRunInitialConnectDriftDetection`` -- the drift-log fires whenever
   ``Event.wait(timeout=N)`` actually returned at >1.5x N wall-clock elapsed.
   Observability-only; the underlying drift cannot be PREVENTED without
   subprocess isolation (Sprint 26 follow-up).

Mocks are at the ``self._connection.obd`` boundary so the lifecycle wiring
under test is the real ApplicationOrchestrator code path.  Wall-clock budget
per acceptance: <5 sec test runtime.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.orchestrator.core import ApplicationOrchestrator

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig(
    *,
    initialConnectTimeoutSec: float = 0.5,
) -> dict[str, Any]:
    """Tier-aware config for the live (simulate=False) connect path.

    Mirrors ``test_lifecycle_initial_connect_timeout.py`` shape so the
    fixtures stay parallel and a future regression on the orchestrator
    construction surface surfaces in BOTH files.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "bluetooth": {
                "macAddress": "00:04:3E:85:0D:FB",
                "retryDelays": [0],
                "maxRetries": 0,
            },
            "obdii": {
                "orchestrator": {
                    "initialConnectTimeoutSec": initialConnectTimeoutSec,
                },
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    return ApplicationOrchestrator(config=config, simulate=False)


def _runWithWatchdog(fn: Any, timeoutSec: float) -> tuple[bool, float]:
    """Run ``fn`` in a daemon thread; return (completed, elapsedSec).

    Idiom: pre-fix the function-under-test blocks indefinitely on the
    unprotected python-obd call.  We CANNOT join() a non-returning daemon
    thread, so we use Event.wait(timeout=timeoutSec) as the watchdog.  The
    daemon thread is left running (it'll be reaped at process exit) -- the
    test's pass/fail signal is whether ``fn`` returned within ``timeoutSec``.

    ``completed`` is True iff fn returned (or raised) within the cap.
    ``elapsedSec`` is wall-clock time to either return or watchdog wake.
    """
    doneEvent = threading.Event()

    def _runner() -> None:
        try:
            fn()
        finally:
            doneEvent.set()

    started = time.perf_counter()
    threading.Thread(
        target=_runner, daemon=True, name="us284-watchdog-fn"
    ).start()
    completed = doneEvent.wait(timeout=timeoutSec)
    elapsed = time.perf_counter() - started
    return completed, elapsed


# ================================================================================
# 1. _queryWithTimeout helper bounds an arbitrary obd.query(command)
# ================================================================================


class TestStaticQueryTimeoutWrapper:
    """The new helper bounds a python-obd query against a wall-clock cap.

    Mirrors ``_runInitialConnectWithTimeout`` semantics so both wrappers are
    a single conceptual pattern -- daemon thread, Event-with-timeout wait,
    (completed, value, error) result tuple.
    """

    def test_queryReturnsQuickly_completedTrueValueReturned(self) -> None:
        """
        Given: connection.obd.query returns a value within the cap
        When:  _queryWithTimeout is called
        Then:  completed=True, value is the query response, error is None.
               The happy path that the cap MUST NOT regress.
        """
        orch = _makeOrch(_baseConfig())

        fakeOBD = MagicMock()
        fakeOBD.query.return_value = "MOCK-VIN-RESPONSE"

        fakeConnection = MagicMock()
        fakeConnection.obd = fakeOBD
        orch._connection = fakeConnection

        completed, value, error = orch._queryWithTimeout("VIN", timeoutSec=1.0)

        assert completed is True
        assert value == "MOCK-VIN-RESPONSE"
        assert error is None
        fakeOBD.query.assert_called_once_with("VIN")

    def test_queryBlocksLongerThanTimeout_completedFalseValueNone(self) -> None:
        """
        Given: connection.obd.query blocks until a Stop event is set
        When:  _queryWithTimeout is called with a 0.5s cap
        Then:  completed=False, value=None, returns within ~1.0s.

        This is the production failure mode: query("VIN") never returns
        because the python-obd serial read is wedged on a non-responsive
        ECU.  Without the wrapper, _performFirstConnectionVinDecode hangs
        forever on the unprotected call (lifecycle.py:502).
        """
        orch = _makeOrch(_baseConfig())

        stopEvent = threading.Event()
        fakeOBD = MagicMock()
        fakeOBD.query.side_effect = lambda cmd: stopEvent.wait(timeout=10.0)

        fakeConnection = MagicMock()
        fakeConnection.obd = fakeOBD
        orch._connection = fakeConnection

        started = time.perf_counter()
        completed, value, error = orch._queryWithTimeout("VIN", timeoutSec=0.5)
        elapsed = time.perf_counter() - started

        # Cleanup: release the blocking thread
        stopEvent.set()

        assert completed is False
        assert value is None
        assert error is None
        # Wall-clock cap honored: 0.5s timeout + small overhead.
        assert elapsed < 2.0, (
            f"_queryWithTimeout blocked {elapsed:.2f}s -- wall-clock cap "
            "did not fire (expected <2.0s with 0.5s timeout)"
        )

    def test_queryRaisesException_completedTrueErrorPropagated(self) -> None:
        """
        Given: connection.obd.query raises an exception
        When:  _queryWithTimeout is called
        Then:  completed=True (thread finished), value=None, error is the
               exception.  Exception is surfaced to caller, not swallowed.
        """
        orch = _makeOrch(_baseConfig())

        boom = RuntimeError("simulated python-obd internal error")
        fakeOBD = MagicMock()
        fakeOBD.query.side_effect = boom

        fakeConnection = MagicMock()
        fakeConnection.obd = fakeOBD
        orch._connection = fakeConnection

        completed, value, error = orch._queryWithTimeout("VIN", timeoutSec=1.0)

        assert completed is True
        assert value is None
        assert error is boom


# ================================================================================
# 2. _performFirstConnectionVinDecode honors the timeout wrapper
# ================================================================================


class TestPerformFirstConnectionVinDecodeBoundedReturn:
    """The VIN-decode call site cannot block indefinitely on python-obd I/O.

    This is the FAILS-pre-fix gate per US-284 acceptance criterion 3.  Pre-
    fix, ``_performFirstConnectionVinDecode`` calls
    ``self._connection.obd.query("VIN")`` directly with NO timeout wrapper.
    A wedged serial read inside python-obd has been observed to block for
    HOURS in production.  Synthetic reproduction: mock query() to wait on
    a never-set Event; assert the function returns within bounded time.
    """

    def test_blockingVinQuery_returnsWithinBoundedTime(self) -> None:
        """
        Given: connection.obd.query("VIN") blocks indefinitely
        When:  _performFirstConnectionVinDecode is called
        Then:  the method returns within bounded time (initialConnectTimeoutSec
               re-used as the static-query cap; default 0.5s in fixture).

        FAILS pre-fix: the unprotected query() call never returns; the
        watchdog assert fires at 2.0s.

        PASSES post-fix: the wrapper bounds the query; the function returns
        and logs the timeout; the watchdog assert succeeds well under 2.0s.
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=0.5))

        # Set up a connection whose obd.query blocks forever.
        stopEvent = threading.Event()
        fakeOBD = MagicMock()
        fakeOBD.query.side_effect = lambda cmd: stopEvent.wait(timeout=30.0)

        fakeConnection = MagicMock()
        fakeConnection.obd = fakeOBD
        orch._connection = fakeConnection

        # _performFirstConnectionVinDecode also requires _vinDecoder non-None
        # to proceed to the query() call (line 492-494 short-circuits otherwise).
        orch._vinDecoder = MagicMock()

        try:
            completed, elapsed = _runWithWatchdog(
                orch._performFirstConnectionVinDecode,
                timeoutSec=2.0,
            )
        finally:
            stopEvent.set()

        assert completed, (
            "_performFirstConnectionVinDecode did not return within 2.0s -- "
            "the unprotected query('VIN') at lifecycle.py:502 is blocking "
            "indefinitely.  Post-fix should wrap query with the daemon-"
            "thread + Event.wait pattern matching US-244."
        )
        # Wall-clock budget: the function should return in roughly the static-
        # query timeout (0.5s here), well under the 2.0s watchdog ceiling.
        assert elapsed < 2.0

    def test_blockingVinQuery_logsTimeoutWarning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: connection.obd.query("VIN") blocks past the static-query cap
        When:  _performFirstConnectionVinDecode runs
        Then:  the post-fix wrapper logs a WARNING naming "VIN" + "timed out"
               so post-deploy journal walks can name the failure mode.

        This is ANALYTICS for the Pi -- lets us tell apart "VIN query was
        clean but vehicle returned null" from "VIN query timed out".  Both
        end the same way (no decoded vehicle info), but the diagnostic
        signal matters for engine-telemetry health.
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=0.5))

        stopEvent = threading.Event()
        fakeOBD = MagicMock()
        fakeOBD.query.side_effect = lambda cmd: stopEvent.wait(timeout=30.0)

        fakeConnection = MagicMock()
        fakeConnection.obd = fakeOBD
        orch._connection = fakeConnection
        orch._vinDecoder = MagicMock()

        try:
            with caplog.at_level(
                logging.WARNING, logger="pi.obdii.orchestrator"
            ):
                completed, _ = _runWithWatchdog(
                    orch._performFirstConnectionVinDecode,
                    timeoutSec=2.0,
                )
        finally:
            stopEvent.set()

        assert completed
        assert any(
            "vin" in r.getMessage().lower()
            and ("timed out" in r.getMessage().lower()
                 or "timeout" in r.getMessage().lower())
            for r in caplog.records
        ), (
            "Expected a WARN log naming 'VIN' + 'timed out' after the static-"
            f"query cap fires; got: {[r.getMessage() for r in caplog.records]}"
        )


# ================================================================================
# 3. _runInitialConnectWithTimeout drift-detection log
# ================================================================================


class TestRunInitialConnectDriftDetection:
    """Wall-clock drift on Event.wait fires a CRITICAL diagnostic log.

    Spool's 2026-05-05 production evidence: ``connectDoneEvent.wait(timeout=
    30)`` returned at T+82min on boot 0 (and presumably ~27h on boot -1).
    The wait timer drifts on Pi 5 -- likely python-obd's GIL contention
    during ELM327 protocol probing.  US-284 cannot PREVENT this drift
    without subprocess isolation (Sprint 26 follow-up TD), but can detect
    and LOG it so post-deploy journal walks are not silent on the failure
    mode.

    The log fires whenever wait elapsed > 1.5x timeoutSec.  This is the
    observability gate Spool's note explicitly asked for:
        "Per the documented behavior the timeout should fire at 30 sec;
        reality is 82 min."
    """

    def test_eventWaitDrifts_logsCriticalDriftWarning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """
        Given: connectDoneEvent.wait simulates production drift (returns
               False after a wall-clock interval much larger than its
               timeout argument)
        When:  _runInitialConnectWithTimeout completes
        Then:  a CRITICAL log line names the drift: configured timeout vs
               actual elapsed wall-clock.

        Synthetic reproduction monkey-patches threading.Event.wait via
        the orchestrator's ``_eventWaitForTesting`` seam (added by the
        US-284 fix) so the production drift is deterministic in <5 sec
        without simulating GIL contention.
        """
        orch = _makeOrch(_baseConfig(initialConnectTimeoutSec=0.2))

        # The fix introduces a seam ``_eventWaitForTesting`` that defaults to
        # ``Event.wait`` itself; tests can override it to simulate drift.
        # We make the wait sleep 0.6s (>1.5x of 0.2 timeoutSec = 0.3) and
        # return False as if it timed out at the configured value.
        def _driftingWait(event: threading.Event, timeout: float) -> bool:
            time.sleep(0.6)
            return False

        fakeConnection = MagicMock()
        # connect() blocks; daemon thread will be left running -- harmless
        # because daemon=True and the test process exits afterwards.
        fakeConnection.connect.side_effect = lambda: time.sleep(5.0)
        orch._connection = fakeConnection
        orch._eventWaitForTesting = _driftingWait

        with caplog.at_level(logging.CRITICAL, logger="pi.obdii.orchestrator"):
            completed, success, error = orch._runInitialConnectWithTimeout(0.2)

        # Drift-detection means: wait took 3x the configured timeout (0.6s
        # actual vs 0.2s configured), and the diagnostic CRITICAL log fired.
        assert completed is False
        assert success is False
        assert any(
            "drift" in r.getMessage().lower()
            and r.levelno >= logging.CRITICAL
            for r in caplog.records
        ), (
            "Expected a CRITICAL drift-detection log; got: "
            f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
        )
