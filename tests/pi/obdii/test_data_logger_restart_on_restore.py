################################################################################
# File Name: test_data_logger_restart_on_restore.py
# Purpose/Description: Unit tests for the US-302 data-logger restart on
#                      _handleConnectionRestored (Spool 2026-05-08 BUG-2:
#                      8-second connection-restored window with zero
#                      data-logger restart -> 0 realtime_data rows).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-302) | Initial -- Spool Story B; restart wiring +
#               |              | RealtimeDataLogger.lastRowWrittenSecondsAgo +
#               |              | health-check render of data_logger_last_row_
#               |              | seconds_ago.  RED-phase asserts pre-fix
#               |              | failure modes (no wiring, no property, no
#               |              | health field).
# ================================================================================
################################################################################

"""Tests for the US-302 data-logger restart-on-connection-restored wiring.

Story scope (Spool 2026-05-08 inbox note BUG-2):

* Production evidence: 10:08:37 ``_handleConnectionRestored`` fires + 17 PIDs
  probed + OBD link alive; ZERO subsequent ``realtime_data`` rows written
  until manual restart at 10:10:26 -- 8-second window of live OBD link
  ignored by the orchestrator.

* Required behavior:

  - ``_handleConnectionRestored`` calls ``dataLogger.start()`` exception-
    isolated (Sprint 26 US-299 pattern).
  - ``RealtimeDataLogger.start()`` is idempotent: safe to call repeatedly;
    second call while RUNNING returns False; first call after a previously
    failed ``start()`` (state stayed STOPPED) succeeds when connection is
    now up.
  - ``RealtimeDataLogger.lastRowWrittenSecondsAgo`` returns ``None``
    sentinel when no row written; otherwise ``float`` seconds since the
    last successful ``logReading`` call (60s post-mortem signal vs 11h
    silence).
  - Health check renders ``data_logger_last_row_seconds_ago=...`` (or
    ``never_written`` sentinel) per ``_performHealthCheck`` cycle.

* Pre-fix discriminator: ``_handleConnectionRestored`` does not call
  ``dataLogger.start``.  ``RealtimeDataLogger.lastRowWrittenSecondsAgo``
  attribute does not exist.  Health check log line lacks the
  ``data_logger_last_row_seconds_ago`` field.  Three independent RED
  signals; post-fix all three GREEN.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.data.realtime import RealtimeDataLogger
from src.pi.obdii.data.types import LoggingState
from src.pi.obdii.orchestrator.event_router import EventRouterMixin
from src.pi.obdii.orchestrator.health_monitor import HealthMonitorMixin
from src.pi.obdii.orchestrator.types import HealthCheckStats

# ================================================================================
# Fakes
# ================================================================================


class FakeConnection:
    """Minimal ``ObdConnection`` stand-in driven by ``isConnected`` flag."""

    def __init__(self, connected: bool = True) -> None:
        self._connected = connected
        self.isSimulated = False

    def isConnected(self) -> bool:
        return self._connected

    def setConnected(self, value: bool) -> None:
        self._connected = value


class FakeDatabase:
    """Stub database -- ``logReading`` is bypassed via attribute injection."""

    def connect(self) -> Any:  # pragma: no cover -- not exercised in these tests
        raise AssertionError("FakeDatabase.connect should not be called in unit tests")


def _buildLogger(
    *,
    connected: bool = True,
    parameters: list[str] | None = None,
) -> RealtimeDataLogger:
    """Build a ``RealtimeDataLogger`` with sensible defaults for these tests."""
    if parameters is None:
        parameters = ["RPM"]
    config = {
        "pi": {
            "realtimeData": {
                "pollingIntervalMs": 1000,
                "parameters": [{"name": p, "logData": True} for p in parameters],
            },
            "profiles": {"activeProfile": "daily", "availableProfiles": []},
        }
    }
    conn = FakeConnection(connected=connected)
    db = FakeDatabase()
    return RealtimeDataLogger(config, conn, db, profileId="daily")


# ================================================================================
# RealtimeDataLogger.start() idempotency
# ================================================================================


class TestRealtimeDataLoggerIdempotentStart:
    """Pin the idempotency contract per US-302 acceptance criterion 2."""

    def test_start_calledOnceFromStopped_returnsTrue(self) -> None:
        rt = _buildLogger(connected=True)
        try:
            assert rt.start() is True
            assert rt.state in (LoggingState.STARTING, LoggingState.RUNNING)
        finally:
            rt.stop(timeout=2.0)

    def test_start_calledTwiceWhileRunning_secondReturnsFalse(self) -> None:
        rt = _buildLogger(connected=True)
        try:
            assert rt.start() is True
            # Second call is the idempotency case.  The first call may still
            # be in STARTING; either way the second call must short-circuit.
            assert rt.start() is False
        finally:
            rt.stop(timeout=2.0)

    def test_start_calledAfterFailedStart_succeedsWhenConnectionReturns(self) -> None:
        """Spool BUG-2 reproduction: first start fails (conn down at lifecycle
        init), state stays STOPPED, then connection comes up at runtime;
        start() now must succeed.  This is the load-bearing case."""
        rt = _buildLogger(connected=False)
        # First start raises -- that's the lifecycle failure mode.
        with pytest.raises(Exception):
            rt.start()
        assert rt.state == LoggingState.STOPPED

        # Connection comes up (analogue: _handleConnectionRestored fires).
        rt.connection.setConnected(True)
        try:
            assert rt.start() is True
        finally:
            rt.stop(timeout=2.0)


# ================================================================================
# RealtimeDataLogger.lastRowWrittenSecondsAgo
# ================================================================================


class TestRealtimeDataLoggerLastRowWrittenSecondsAgo:
    """Pin the post-mortem signal per US-302 acceptance criterion 3."""

    def test_lastRowWrittenSecondsAgo_neverWritten_returnsNone(self) -> None:
        """Sentinel: ``None`` means no successful row ever written by this
        logger instance.  Caller renders ``never_written`` per the story
        invariant (no NULL/magic numbers in the rendered field)."""
        rt = _buildLogger(connected=True)
        assert rt.lastRowWrittenSecondsAgo is None

    def test_lastRowWrittenSecondsAgo_afterMarkRowWritten_returnsElapsed(self) -> None:
        """``_markRowWritten`` is the internal hook fired by the safe-log
        path; an external monotonic clock injection makes the elapsed
        deterministic for unit tests."""
        rt = _buildLogger(connected=True)

        # Inject a monotonic clock so elapsed is deterministic.
        clockNow = [100.0]
        rt._monotonicFn = lambda: clockNow[0]  # type: ignore[attr-defined]
        rt._markRowWritten()
        clockNow[0] = 110.0  # 10 seconds later

        elapsed = rt.lastRowWrittenSecondsAgo
        assert elapsed == pytest.approx(10.0, abs=0.001)

    def test_lastRowWrittenSecondsAgo_isUpdatedOnEverySuccessfulLog(self) -> None:
        """Two successful row-writes -- second updates the timestamp so
        the elapsed is measured against the more recent one."""
        rt = _buildLogger(connected=True)

        clockNow = [50.0]
        rt._monotonicFn = lambda: clockNow[0]  # type: ignore[attr-defined]
        rt._markRowWritten()
        clockNow[0] = 60.0
        rt._markRowWritten()  # newer write
        clockNow[0] = 65.0

        # 5 seconds since the *most recent* mark, not 15 since the first.
        assert rt.lastRowWrittenSecondsAgo == pytest.approx(5.0, abs=0.001)


# ================================================================================
# _handleConnectionRestored wires dataLogger.start()
# ================================================================================


def _buildEventRouterStub(
    dataLogger: Any,
    onConnectionRestored: Any = None,
) -> EventRouterMixin:
    """Build a SimpleNamespace stub satisfying EventRouterMixin's attrs.

    Mirrors the test_reconnect_loop_heartbeat.py pattern: bypass __init__
    and call the mixin method via .__get__(stub, type(stub)).
    """
    stub = SimpleNamespace(
        _driveDetector=None,
        _alertManager=None,
        _statisticsEngine=None,
        _dataLogger=dataLogger,
        _profileSwitcher=None,
        _displayManager=None,
        _hardwareManager=None,
        _profileManager=None,
        _healthCheckStats=HealthCheckStats(),
        _dashboardParameters=set(),
        _alertsPausedForReconnect=False,
        _connection=None,
        _dtcLogger=None,
        _milEdgeDetector=None,
        _onDriveStart=None,
        _onDriveEnd=None,
        _onAlert=None,
        _onAnalysisComplete=None,
        _onConnectionLost=None,
        _onConnectionRestored=onConnectionRestored,
    )
    # Bind the mixin's _restartDataLoggerOnConnectionRestored as a method
    # on the stub so the call from _handleConnectionRestored resolves
    # against the production implementation.
    stub._restartDataLoggerOnConnectionRestored = (
        lambda: EventRouterMixin._restartDataLoggerOnConnectionRestored(stub)
    )
    return stub  # type: ignore[return-value]


class _FakeDataLogger:
    """Stub data logger tracking ``start`` / ``stop`` calls."""

    def __init__(
        self,
        *,
        startReturns: bool = True,
        startRaises: Exception | None = None,
        running: bool = False,
    ) -> None:
        self.startCalls = 0
        self.stopCalls = 0
        self._startReturns = startReturns
        self._startRaises = startRaises
        self._running = running

    def start(self) -> bool:
        self.startCalls += 1
        if self._startRaises is not None:
            raise self._startRaises
        if self._running:
            return False
        self._running = True
        return self._startReturns

    def stop(self, timeout: float = 5.0) -> bool:
        self.stopCalls += 1
        self._running = False
        return True

    @property
    def isRunning(self) -> bool:
        return self._running


class TestHandleConnectionRestoredRestartsDataLogger:
    """Pin the wiring per US-302 acceptance criterion 2 (handler-side)."""

    def test_handleConnectionRestored_dataLoggerStopped_callsStart(self) -> None:
        """The Spool BUG-2 fix: handler must (re-)start the data logger
        when connection comes back up post-init."""
        fakeLogger = _FakeDataLogger(running=False)
        stub = _buildEventRouterStub(dataLogger=fakeLogger)

        EventRouterMixin._handleConnectionRestored(stub)  # type: ignore[arg-type]

        assert fakeLogger.startCalls == 1, (
            "handler must call dataLogger.start() exactly once on restoration"
        )

    def test_handleConnectionRestored_dataLoggerAlreadyRunning_callsStartIdempotent(
        self,
    ) -> None:
        """Idempotent: handler still calls start(); the data logger
        short-circuits internally (returns False) -- handler does NOT
        gate on isRunning because the source-of-truth is the logger's
        own state machine."""
        fakeLogger = _FakeDataLogger(running=True)
        stub = _buildEventRouterStub(dataLogger=fakeLogger)

        EventRouterMixin._handleConnectionRestored(stub)  # type: ignore[arg-type]

        # Handler called start; the logger no-op'd -- both correct.
        assert fakeLogger.startCalls == 1

    def test_handleConnectionRestored_dataLoggerStartRaises_handlerSwallows(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Sprint 26 US-299 pattern: handler must be exception-isolated.
        A start() exception is logged at WARNING and never re-raised so
        the orchestrator does not crash."""
        fakeLogger = _FakeDataLogger(
            startRaises=RuntimeError("simulated transient OBD glitch")
        )
        stub = _buildEventRouterStub(dataLogger=fakeLogger)

        with caplog.at_level(logging.DEBUG, logger="pi.obdii.orchestrator"):
            # Must not raise.
            EventRouterMixin._handleConnectionRestored(stub)  # type: ignore[arg-type]

        assert fakeLogger.startCalls == 1
        # Loud-bail per V0.24.1: a warning naming the failure must be
        # present so post-deploy journals catch this in 60s, not 11h.
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING
            and "data logger" in r.getMessage().lower()
        ]
        assert warnings, (
            "expected a WARNING-level log naming the data-logger start failure"
        )

    def test_handleConnectionRestored_noDataLogger_isSafeNoOp(self) -> None:
        """Defensive: a deployment with no data logger configured must
        not crash.  Mirrors existing handler defensive shape."""
        stub = _buildEventRouterStub(dataLogger=None)
        # Must not raise.
        EventRouterMixin._handleConnectionRestored(stub)  # type: ignore[arg-type]


# ================================================================================
# Health-check renders data_logger_last_row_seconds_ago
# ================================================================================


def _buildHealthMonitorStub(
    dataLogger: Any,
) -> HealthMonitorMixin:
    """Stub satisfying HealthMonitorMixin.  ``_checkConnectionStatus`` and
    ``_collectComponentStats`` are bound via direct attribute set so the
    stub can call them with ``self`` semantics."""
    stub = SimpleNamespace(
        _healthCheckStats=HealthCheckStats(),
        _healthCheckInterval=60.0,
        _startTime=datetime.now() - timedelta(seconds=120),
        _lastHealthCheckTime=datetime.now() - timedelta(seconds=60),
        _lastDataRateCheckTime=datetime.now() - timedelta(seconds=60),
        _lastDataRateReadingCount=0,
        _lastDataRateLogTime=datetime.now() - timedelta(seconds=60),
        _lastDataRateLogCount=0,
        _dataLogger=dataLogger,
        _driveDetector=None,
        _checkConnectionStatus=lambda: True,
    )
    # Bind the mixin's _collectComponentStats as a method on the stub so
    # _performHealthCheck's internal call resolves via the mixin's
    # implementation (which reads _dataLogger.getStats() etc.).
    stub._collectComponentStats = (
        lambda: HealthMonitorMixin._collectComponentStats(stub)
    )
    stub._readDataLoggerLastRowSecondsAgo = (
        lambda: HealthMonitorMixin._readDataLoggerLastRowSecondsAgo(stub)
    )
    return stub  # type: ignore[return-value]


class TestHealthCheckRendersLastRowSecondsAgo:
    """Pin the health-field render per US-302 acceptance criterion 3."""

    def test_performHealthCheck_neverWritten_rendersNeverWrittenSentinel(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When no row has ever been written, the health line carries the
        ``never_written`` sentinel -- explicit, greppable, no NULL."""
        rt = _buildLogger(connected=True)  # lastRowWrittenSecondsAgo = None
        stub = _buildHealthMonitorStub(dataLogger=rt)

        with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
            HealthMonitorMixin._performHealthCheck(stub)  # type: ignore[arg-type]

        healthLines = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "HEALTH CHECK" in r.getMessage()
        ]
        assert healthLines, "expected an INFO-level HEALTH CHECK line"
        msg = healthLines[-1].getMessage()
        assert "data_logger_last_row_seconds_ago=never_written" in msg, (
            f"expected sentinel render in health line; got: {msg!r}"
        )

    def test_performHealthCheck_recentRow_rendersElapsedFloat(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When a row was just written, the field renders the elapsed
        seconds (formatted to 1 decimal place per the dataRate convention
        in the same line)."""
        rt = _buildLogger(connected=True)
        clockNow = [200.0]
        rt._monotonicFn = lambda: clockNow[0]  # type: ignore[attr-defined]
        rt._markRowWritten()
        clockNow[0] = 203.5  # 3.5s elapsed

        stub = _buildHealthMonitorStub(dataLogger=rt)

        with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
            HealthMonitorMixin._performHealthCheck(stub)  # type: ignore[arg-type]

        healthLines = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "HEALTH CHECK" in r.getMessage()
        ]
        assert healthLines, "expected an INFO-level HEALTH CHECK line"
        msg = healthLines[-1].getMessage()
        assert "data_logger_last_row_seconds_ago=3.5" in msg, (
            f"expected elapsed float render; got: {msg!r}"
        )


# ================================================================================
# End-to-end discriminator: failed-init -> connection-restored -> row written
# ================================================================================


class TestEndToEndFailedInitThenRestored:
    """The Spool BUG-2 reproduction in one test: pre-fix this would FAIL
    because _handleConnectionRestored does not call dataLogger.start()."""

    def test_failedInitThenRestored_handlerStartsLoggerAndRowWrittenIsTracked(
        self,
    ) -> None:
        rt = _buildLogger(connected=False)

        # Phase 1: lifecycle init tries to start, fails -- conn was down.
        with pytest.raises(Exception):
            rt.start()
        assert rt.state == LoggingState.STOPPED

        # Phase 2: conn comes back up; _handleConnectionRestored is the
        # producer of the start call.  Wire the EventRouter handler with
        # the real RealtimeDataLogger.
        rt.connection.setConnected(True)
        stub = _buildEventRouterStub(dataLogger=rt)
        EventRouterMixin._handleConnectionRestored(stub)  # type: ignore[arg-type]

        try:
            assert rt.state in (LoggingState.STARTING, LoggingState.RUNNING)

            # Phase 3: a successful row-write updates lastRowWrittenSecondsAgo.
            clockNow = [10.0]
            rt._monotonicFn = lambda: clockNow[0]  # type: ignore[attr-defined]
            rt._markRowWritten()
            clockNow[0] = 11.0
            assert rt.lastRowWrittenSecondsAgo == pytest.approx(1.0, abs=0.001)
        finally:
            rt.stop(timeout=2.0)
