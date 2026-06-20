################################################################################
# File Name: test_lifecycle_bus_wiring.py
# Purpose/Description: EDR bus slice 1 (US-385) orchestrator wiring tests.
#     Proves _initializeDataLogger builds a SampleBus + starts a
#     PersistenceSubscriber on ['raw.obd.*'] LOSSLESS and injects the bus into
#     the logger ONLY when pi.bus.enabled is true; with the flag off the
#     dataLogger behavior is identical to today (no bus, no subscriber). The
#     end-to-end test pushes one sample through the orchestrator-built bus and
#     asserts the PersistenceSubscriber writes a realtime_data row.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Flag-gated orchestrator wiring for the EDR bus (ships dark, default off)."""

import time
from unittest.mock import MagicMock, patch

from pi.bus.sample import Sample
from pi.obdii.database import ObdDatabase
from pi.obdii.orchestrator.lifecycle import LifecycleMixin
from pi.obdii.orchestrator.types import ShutdownState

_PROFILE_ID = "daily"


def _orch(busEnabled, *, config=None, database=None, connection=None):
    """Build a bare LifecycleMixin with only the attributes _initializeDataLogger
    and _shutdownDataLogger touch (no full orchestrator construction)."""
    orch = LifecycleMixin.__new__(LifecycleMixin)
    orch._config = config or {"pi": {"bus": {"enabled": busEnabled}}}
    orch._connection = connection if connection is not None else MagicMock()
    orch._database = database if database is not None else MagicMock()
    orch.handleCaptureError = MagicMock()
    orch._onCaptureFatalError = MagicMock()
    # Required by _stopComponentWithTimeout on the shutdown path.
    orch._shutdownState = ShutdownState.RUNNING
    orch._shutdownTimeout = 5.0
    return orch


def test_busDisabled_noSubscriberNoBus():
    orch = _orch(busEnabled=False)
    with patch("pi.obdii.data.createRealtimeLoggerFromConfig") as factory:
        factory.return_value = MagicMock()
        orch._initializeDataLogger()
    assert getattr(orch, "_sampleBus", None) is None
    assert getattr(orch, "_persistenceSubscriber", None) is None
    # The factory was called WITHOUT a bus (flag off == today's behavior).
    assert factory.call_args.kwargs.get("bus") is None


def test_busEnabled_buildsBusAndStartsPersistenceSubscriber():
    orch = _orch(busEnabled=True)
    fakeLogger = MagicMock()
    with patch(
        "pi.obdii.data.createRealtimeLoggerFromConfig", return_value=fakeLogger
    ) as factory:
        orch._initializeDataLogger()
    try:
        assert orch._sampleBus is not None
        assert orch._persistenceSubscriber is not None
        assert orch._dataLogger is fakeLogger
        # The bus was injected into the logger factory.
        assert factory.call_args.kwargs.get("bus") is orch._sampleBus
    finally:
        # Stop the daemon drain thread the wiring started.
        orch._persistenceSubscriber.stop()


def test_busEnabled_isStoppedOnShutdown():
    orch = _orch(busEnabled=True)
    with patch(
        "pi.obdii.data.createRealtimeLoggerFromConfig", return_value=MagicMock()
    ):
        orch._initializeDataLogger()
    subscriber = orch._persistenceSubscriber
    subscriber.stop = MagicMock()
    orch._shutdownDataLogger()
    subscriber.stop.assert_called_once()
    assert orch._dataLogger is None


def _seededDb(tmp_path):
    """Initialized SQLite DB with a seeded profile row (realtime_data FK target)."""
    db = ObdDatabase(str(tmp_path / "e2e.db"))
    db.initialize()
    with db.connect() as conn:
        conn.cursor().execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)", (_PROFILE_ID, "Daily")
        )
    return db


def _realtimeRowCount(db):
    with db.connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT parameter_name, value FROM realtime_data")
        return [tuple(r) for r in cur.fetchall()]


def test_busEnabled_endToEnd_pushOneSampleWritesRealtimeRow(tmp_path):
    """VC#3: enable the flag, push one sample through the orchestrator-built bus
    -> a realtime_data row is written by the PersistenceSubscriber."""
    db = _seededDb(tmp_path)
    config = {
        "pi": {
            "bus": {"enabled": True},
            "profiles": {"activeProfile": _PROFILE_ID},
        }
    }
    orch = _orch(busEnabled=True, config=config, database=db, connection=MagicMock())
    # Real factory -> real RealtimeDataLogger -> real inner ObdDataLogger on db.
    orch._initializeDataLogger()
    try:
        assert orch._sampleBus is not None
        orch._sampleBus.publish(
            Sample(
                topic="raw.obd.RPM",
                source="obd",
                value=3500.0,
                unit="rpm",
                tsUtc="2026-06-19T00:00:00Z",
                tsCapture=1.0,
                driveId=None,
                dataSource="real",
                seq=1,
            )
        )
        # The subscriber drains on its own thread; poll the DB up to ~5s.
        deadline = time.monotonic() + 5.0
        rows = []
        while time.monotonic() < deadline:
            rows = _realtimeRowCount(db)
            if rows:
                break
            time.sleep(0.05)
        assert rows == [("RPM", 3500.0)]
    finally:
        orch._persistenceSubscriber.stop()
