################################################################################
# File Name: test_bt_drop_resilience.py
# Purpose/Description: Integration test for US-211 BT-resilient collector.
#                      Drives the full handleCaptureError -> reconnect loop ->
#                      resume path with a FakeObdConnection and captures the
#                      connection_log flap timeline for inspection.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- Spool Session 6 amended Story 2.
# ================================================================================
################################################################################

"""BT drop resilience end-to-end integration test (US-211).

Covers the full flap path from Spool Session 6 acceptance criterion 8:

    Integration test: fake BT drop (mock rfcomm path missing) -> collector
    does NOT exit (ps assertion via FakeProcess wrapper or similar);
    probe returns success -> reconnect -> capture resumes.

We build a ``BtResilienceMixin``-composing object with:

* A :class:`FakeObdConnection` that tracks disconnect/reconnect calls
  and can be toggled into/out of a raising state.
* A :class:`ObdDatabase` populated from the real Pi schema so
  connection_log rows are visible end-to-end.
* A :class:`ReconnectLoop` wired with injected probe + sleep so the
  loop runs in ~0 wall-clock.

The test drives ``handleCaptureError`` with three canned exceptions:
ADAPTER_UNREACHABLE -> ECU_SILENT -> FATAL, asserting:

* Process does NOT exit on ADAPTER or ECU paths (function returns).
* FATAL re-raises so systemd restarts the process.
* ``connection_log`` holds the full flap timeline with canonical
  event_types in the correct order.
* ``_safeReopen`` is invoked exactly once after a successful probe.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from src.pi.data.connection_logger import (
    EVENT_ADAPTER_WAIT,
    EVENT_BT_DISCONNECT,
    EVENT_ECU_SILENT_WAIT,
    EVENT_RECONNECT_ATTEMPT,
    EVENT_RECONNECT_SUCCESS,
)
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.error_classification import CaptureErrorClass
from src.pi.obdii.obd_connection import ObdConnectionError
from src.pi.obdii.orchestrator.bt_resilience import BtResilienceMixin
from src.pi.obdii.reconnect_loop import ReconnectLoop

# ================================================================================
# Fakes
# ================================================================================

class FakeObdConnection:
    """Duck-typed stand-in for :class:`ObdConnection`.

    Tracks calls to disconnect()/reconnect() so the integration test can
    assert the mixin correctly tore down + reopened on the adapter path.
    """

    macAddress: str = '00:04:3E:85:0D:FB'
    rfcommDevice: int = 0

    def __init__(self) -> None:
        self.disconnectCalls: int = 0
        self.reconnectCalls: int = 0
        self.connectCalls: int = 0

    def disconnect(self) -> None:
        self.disconnectCalls += 1

    def reconnect(self) -> bool:
        self.reconnectCalls += 1
        return True

    def connect(self) -> bool:
        self.connectCalls += 1
        return True

    def isConnected(self) -> bool:
        return True


class FakeOrchestrator(BtResilienceMixin):
    """Minimal composing class -- exposes handleCaptureError for the test."""

    def __init__(self, database: ObdDatabase, connection: Any, loop: ReconnectLoop) -> None:
        self._database = database
        self._connection = connection
        # Override the default factory with a test-controlled one.
        self._reconnectLoopFactory = lambda: loop


# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    """Real Pi schema on disk so connection_log INSERTs actually land."""
    dbPath = tmp_path / "obd.db"
    db = ObdDatabase(str(dbPath), walMode=False)
    db.initialize()
    yield db


def _readConnectionLogEvents(db: ObdDatabase) -> list[tuple[str, int]]:
    """Return (event_type, retry_count) rows in insertion order."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT event_type, retry_count FROM connection_log ORDER BY id"
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


# ================================================================================
# Full-flap integration
# ================================================================================

def test_adapterUnreachable_completeFlap_resumesWithoutExiting(freshDb):
    """Full BT flap: disconnect -> wait -> probe-success -> reconnect.

    Acceptance criterion 8: collector does NOT exit (function returns),
    probe returns success -> reconnect -> capture resumes.
    """
    # Probe: False twice (two failed probes), then True.
    probeResults = iter([False, False, True])
    sleepDurations: list[float] = []

    loop = ReconnectLoop(
        probe=lambda: next(probeResults),
        eventLogger=None,  # Mixin writes via logConnectionEvent directly.
        sleepFn=lambda seconds: sleepDurations.append(seconds),
    )
    # Route the loop's event emission through the real writer so the DB
    # accumulates the flap timeline. Re-wire the eventLogger here.
    from src.pi.data.connection_logger import logConnectionEvent

    loop._eventLogger = lambda eventType, retryCount: logConnectionEvent(
        database=freshDb,
        eventType=eventType,
        macAddress='00:04:3E:85:0D:FB',
        success=(eventType == EVENT_RECONNECT_SUCCESS),
        retryCount=retryCount,
    )

    conn = FakeObdConnection()
    orch = FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

    # Drive the mixin with a canned adapter-layer exception.
    result = orch.handleCaptureError(
        ObdConnectionError("rfcomm read timed out")
    )

    assert result is CaptureErrorClass.ADAPTER_UNREACHABLE

    # Connection was torn down and reopened.
    assert conn.disconnectCalls == 1
    assert conn.reconnectCalls == 1

    # Flap timeline in connection_log -- bt_disconnect first, then
    # (adapter_wait -> reconnect_attempt) x 3, then reconnect_success.
    events = _readConnectionLogEvents(freshDb)
    assert events == [
        (EVENT_BT_DISCONNECT, 0),
        (EVENT_ADAPTER_WAIT, 1),
        (EVENT_RECONNECT_ATTEMPT, 1),
        (EVENT_ADAPTER_WAIT, 2),
        (EVENT_RECONNECT_ATTEMPT, 2),
        (EVENT_ADAPTER_WAIT, 3),
        (EVENT_RECONNECT_ATTEMPT, 3),
        (EVENT_RECONNECT_SUCCESS, 3),
    ]

    # Backoff schedule respected: 1s -> 5s -> 10s for the three iterations.
    assert sleepDurations == [1.0, 5.0, 10.0]


def test_ecuSilent_staysConnected_noDisconnect(freshDb):
    """ECU_SILENT path logs ecu_silent_wait and leaves the connection open."""
    loop = ReconnectLoop(
        probe=lambda: True,
        eventLogger=None,
        sleepFn=lambda _: None,
    )
    conn = FakeObdConnection()
    orch = FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

    result = orch.handleCaptureError(
        TimeoutError("ECU did not respond to 010D")
    )

    assert result is CaptureErrorClass.ECU_SILENT
    # Critical: connection stays open.
    assert conn.disconnectCalls == 0
    assert conn.reconnectCalls == 0

    events = _readConnectionLogEvents(freshDb)
    assert events == [(EVENT_ECU_SILENT_WAIT, 0)]


def test_fatal_reraises_soSystemdRestarts(freshDb):
    """FATAL class re-raises; systemd Restart=always (US-210) handles the restart."""
    loop = ReconnectLoop(
        probe=lambda: True,
        eventLogger=None,
        sleepFn=lambda _: None,
    )
    conn = FakeObdConnection()
    orch = FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

    with pytest.raises(RuntimeError, match="parser broke"):
        orch.handleCaptureError(RuntimeError("parser broke"))

    # No disconnect happened -- FATAL bypassed the adapter path.
    assert conn.disconnectCalls == 0
    # No connection_log rows written for FATAL (log only; caller handles
    # the raise).
    events = _readConnectionLogEvents(freshDb)
    assert events == []


def test_adapterUnreachable_abortedByShouldExit_doesNotReopen(freshDb):
    """If shutdown signal fires mid-reconnect, the mixin exits cleanly.

    The call returns ADAPTER_UNREACHABLE -- caller's outer loop decides
    whether to shut down. No reopen happens because the probe never
    returned True.
    """
    shutdownFlag = {'stop': False}

    loop = ReconnectLoop(
        probe=lambda: False,
        eventLogger=None,
        sleepFn=lambda _: shutdownFlag.__setitem__('stop', True),
        shouldExitFn=lambda: shutdownFlag['stop'],
    )
    conn = FakeObdConnection()
    orch = FakeOrchestrator(database=freshDb, connection=conn, loop=loop)

    result = orch.handleCaptureError(
        OSError("rfcomm vanished")
    )
    assert result is CaptureErrorClass.ADAPTER_UNREACHABLE

    # Disconnect happened before the loop; no reopen.
    assert conn.disconnectCalls == 1
    assert conn.reconnectCalls == 0
