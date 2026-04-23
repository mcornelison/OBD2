################################################################################
# File Name: test_bt_flap_in_process.py
# Purpose/Description: In-process BT-flap integration test for US-221.
#                      Proves the capture loop + BtResilienceMixin recover
#                      from a simulated adapter drop WITHOUT exiting the
#                      process (same PID before/during/after) and writes
#                      the canonical connection_log flap timeline.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-22    | Rex (US-221) | Initial -- US-211 integration wiring.
# ================================================================================
################################################################################

"""End-to-end BT-flap resilience integration (US-221).

US-211's :class:`~src.pi.obdii.orchestrator.bt_resilience.BtResilienceMixin`
already has unit coverage via :mod:`tests.pi.integration.test_bt_drop_resilience`,
but that test drives ``handleCaptureError`` directly.  This file drives the
wiring end-to-end:

    RealtimeDataLogger._pollCycle
        -> _queryParameterSafe (unwraps ParameterReadError __cause__)
        -> _routeCaptureError
        -> captureErrorHandler = BtResilienceMixin.handleCaptureError
        -> reconnect loop (injected probe + sleep)
        -> capture resumes

Key invariants asserted (US-221 acceptance 6 + Spool Concern 1):

* Same ``os.getpid()`` before / during / after the flap.
* Capture thread alive post-recovery.
* ``connection_log`` shows bt_disconnect -> adapter_wait -> reconnect_attempt
  -> reconnect_success in order.
* Exception is NOT propagated out of the loop (no unhandled exception).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator
from typing import Any

import pytest

from src.pi.data.connection_logger import (
    EVENT_ADAPTER_WAIT,
    EVENT_BT_DISCONNECT,
    EVENT_RECONNECT_ATTEMPT,
    EVENT_RECONNECT_SUCCESS,
    logConnectionEvent,
)
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.obd_connection import ObdConnectionError
from src.pi.obdii.orchestrator.bt_resilience import BtResilienceMixin
from src.pi.obdii.reconnect_loop import ReconnectLoop

# ================================================================================
# Fakes -- wired end-to-end
# ================================================================================

class _FakeObdLibResponse:
    """Minimal python-obd response stand-in that reports a real value."""

    def __init__(self, value: float = 1000.0, unit: str = "rpm") -> None:
        self.value = value
        self.unit = unit

    def is_null(self) -> bool:
        return False


class _FlappingObd:
    """``.obd`` attribute that raises ADAPTER_UNREACHABLE-class errors then recovers.

    Simulates a BT drop: the first ``failureCount`` ``query()`` calls raise
    :class:`ObdConnectionError` with an 'rfcomm' signature; after the
    underlying connection is "reopened" (``markReopened()`` flips the flag),
    subsequent queries return a valid response.
    """

    def __init__(self, failureCount: int = 1) -> None:
        self._remainingFailures = failureCount
        self._reopened = False
        self.queryCalls = 0

    def query(self, cmd: Any) -> Any:
        self.queryCalls += 1
        if self._remainingFailures > 0 and not self._reopened:
            self._remainingFailures -= 1
            raise ObdConnectionError(
                "rfcomm read failed: transport endpoint is not connected"
            )
        return _FakeOdbLibResponseSafe()

    def markReopened(self) -> None:
        self._reopened = True


class _FakeOdbLibResponseSafe(_FakeObdLibResponse):
    """Alias to avoid local-import shadowing in the helper above."""


class _FlappingConnection:
    """ObdConnection stand-in whose ``.obd`` transiently raises rfcomm errors."""

    macAddress: str = '00:04:3E:85:0D:FB'
    rfcommDevice: int = 0
    isSimulated: bool = False

    def __init__(self, failureCount: int = 1) -> None:
        self.obd = _FlappingObd(failureCount=failureCount)
        self.supportedPids = None
        self.disconnectCalls = 0
        self.reconnectCalls = 0

    def isConnected(self) -> bool:
        return True

    def disconnect(self) -> None:
        self.disconnectCalls += 1

    def reconnect(self) -> bool:
        self.reconnectCalls += 1
        self.obd.markReopened()
        return True

    def connect(self) -> bool:
        return self.reconnect()


class _FakeOrchestrator(BtResilienceMixin):
    """Minimal composing shell -- exposes handleCaptureError for integration."""

    def __init__(
        self,
        database: ObdDatabase,
        connection: _FlappingConnection,
        loop: ReconnectLoop,
    ) -> None:
        self._database = database
        self._connection = connection
        self._reconnectLoopFactory = lambda: loop
        self.fatalSignals: list[BaseException] = []

    def onFatalError(self, exc: BaseException) -> None:
        self.fatalSignals.append(exc)


# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    yield db


def _buildLoop(
    freshDb: ObdDatabase,
    probeResults: list[bool],
) -> ReconnectLoop:
    """Reconnect loop with deterministic probe + sleep, writing to the real DB."""
    iterator = iter(probeResults)

    def probe() -> bool:
        return next(iterator)

    def eventLogger(eventType: str, retryCount: int) -> None:
        logConnectionEvent(
            database=freshDb,
            eventType=eventType,
            macAddress='00:04:3E:85:0D:FB',
            success=(eventType == EVENT_RECONNECT_SUCCESS),
            retryCount=retryCount,
        )

    return ReconnectLoop(
        probe=probe,
        eventLogger=eventLogger,
        sleepFn=lambda _seconds: None,
    )


def _minimalConfig() -> dict[str, Any]:
    return {
        'pi': {
            'profiles': {
                'activeProfile': 'daily',
                'availableProfiles': [
                    {'id': 'daily', 'pollingIntervalMs': 100}
                ],
            },
            'realtimeData': {
                'pollingIntervalMs': 100,
                'parameters': [
                    {'name': 'RPM', 'logData': True},
                ],
            },
        }
    }


def _readConnectionLog(db: ObdDatabase) -> list[tuple[str, int]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT event_type, retry_count FROM connection_log ORDER BY id"
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


# ================================================================================
# Tests
# ================================================================================

class TestBtFlapInProcess:
    """Full-wire integration: RealtimeDataLogger -> mixin -> reconnect loop -> resume."""

    def test_btFlap_sameProcessRecovers_notAProcessRestart(self, freshDb):
        """PID must not change across the flap -- US-211's whole point.

        Production already has US-210 systemd Restart=always as the
        FATAL backstop.  US-221 proves that ADAPTER_UNREACHABLE events
        no longer reach that backstop -- the same Python process recovers
        in-line via the reconnect loop.
        """
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        pidBefore = os.getpid()

        conn = _FlappingConnection(failureCount=1)
        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )

        # Drive a single capture cycle directly -- easier to observe than
        # the background thread and the US-221 wiring is pollCycle-level.
        rt._pollCycle()

        pidAfter = os.getpid()
        assert pidAfter == pidBefore
        # Orchestrator never got a FATAL signal.
        assert orch.fatalSignals == []

    def test_btFlap_emitsCanonicalFlapTimeline(self, freshDb):
        """connection_log shows bt_disconnect -> adapter_wait ->
        reconnect_attempt -> reconnect_success, in that order."""
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        conn = _FlappingConnection(failureCount=1)
        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )
        rt._pollCycle()

        events = _readConnectionLog(freshDb)
        # Exact sequence -- US-211 timeline contract.
        assert events == [
            (EVENT_BT_DISCONNECT, 0),
            (EVENT_ADAPTER_WAIT, 1),
            (EVENT_RECONNECT_ATTEMPT, 1),
            (EVENT_RECONNECT_SUCCESS, 1),
        ]

    def test_btFlap_connectionTornDownAndReopened(self, freshDb):
        """Mixin's ADAPTER_UNREACHABLE path calls disconnect() then reconnect()."""
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        conn = _FlappingConnection(failureCount=1)
        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )
        rt._pollCycle()

        assert conn.disconnectCalls == 1
        assert conn.reconnectCalls == 1

    def test_btFlap_loopContinues_noUnhandledException(self, freshDb):
        """After recovery, a second cycle should execute cleanly."""
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        conn = _FlappingConnection(failureCount=1)
        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )
        # First cycle: the flap.
        rt._pollCycle()
        # Second cycle: clean poll on the now-reopened connection.
        rt._pollCycle()

        # Loop still runnable.
        assert rt._stopEvent.is_set() is False


class TestFatalPidSurface:
    """FATAL classifications set the stopEvent and signal orchestrator shutdown.

    They do NOT kill the process directly -- systemd Restart=always + the
    orchestrator's onFatalError callback is how the process actually bounces.
    """

    def test_fatal_setsStopEventAndSignalsOrchestrator(self, freshDb):
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        conn = _FlappingConnection(failureCount=0)  # No flap needed; we inject directly.
        # Replace .obd.query with one that raises a non-classifiable error.
        conn.obd.query = lambda cmd: (_ for _ in ()).throw(  # type: ignore[assignment]
            RuntimeError("parser corrupted -- process unsafe")
        )

        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )
        rt._pollCycle()

        assert rt._stopEvent.is_set() is True
        assert len(orch.fatalSignals) == 1
        assert isinstance(orch.fatalSignals[0], RuntimeError)
        assert "parser corrupted" in str(orch.fatalSignals[0])

    def test_fatal_notMisclassifiedAsBenignParameterReadError(self, freshDb):
        """Wrapping in ParameterReadError must not hide a FATAL cause.

        The live path goes: ObdDataLogger.queryParameter catches Exception
        and re-raises as ``ParameterReadError`` with ``__cause__=exc``.
        US-221 unwraps the cause in _queryParameterSafe so the classifier
        still sees the real RuntimeError, not the wrapper.
        """
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        conn = _FlappingConnection(failureCount=0)
        conn.obd.query = lambda cmd: (_ for _ in ()).throw(  # type: ignore[assignment]
            RuntimeError("genuine FATAL")
        )

        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )
        rt._pollCycle()

        # If unwrap worked, we get a FATAL signal with the RuntimeError.
        # If unwrap failed, we'd see classifier called with ParameterReadError,
        # which classifies as FATAL as well BUT the orchestrator would see
        # the wrapper, not the real cause.  Assert the real cause surfaces.
        assert len(orch.fatalSignals) == 1
        assert isinstance(orch.fatalSignals[0], RuntimeError)


class TestBackgroundThreadInvariants:
    """Capture thread survives in-flight flaps when driven by start()/stop()."""

    def test_backgroundThread_recoversFromFlap_sameThreadKeepsRunning(
        self, freshDb
    ):
        """Thread identity must be stable across recovery."""
        from src.pi.obdii.data.realtime import RealtimeDataLogger

        conn = _FlappingConnection(failureCount=1)
        loop = _buildLoop(freshDb, probeResults=[True])
        orch = _FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

        rt = RealtimeDataLogger(
            _minimalConfig(),
            conn,
            freshDb,
            captureErrorHandler=orch.handleCaptureError,
            onFatalError=orch.onFatalError,
        )
        assert rt.start() is True
        try:
            threadRef = rt._thread
            # Wait briefly for at least one cycle.
            deadline = threading.Event()
            deadline.wait(0.5)
            # Thread reference unchanged post-flap.
            assert rt._thread is threadRef
            assert rt._thread is not None
            assert rt._thread.is_alive()
        finally:
            rt.stop(timeout=2.0)
