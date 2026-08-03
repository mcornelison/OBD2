################################################################################
# File Name: test_lifecycle_drain_writer_wiring.py
# Purpose/Description: US-526 (F-123) orchestrator wiring for the production
#     drain-event writer.  Proves _initializeDrainEventWriter registers the
#     writer on PowerMonitor.onTransition (the AC [SEAM]), runs the boot reaper
#     BEFORE any transition can open a new row, and resolves the UpsMonitor
#     LATE (HardwareManager.start() runs after this wiring -- the
#     US-501/502/503 boot-order trap).  Also pins the soft-fail posture: no
#     PowerMonitor / no database / a construction fault must never break boot.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex (US-526) | Initial -- drain-writer orchestrator wiring.
# ================================================================================
################################################################################

"""Orchestrator wiring of the production drain-event writer (US-526)."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.database import ObdDatabase
from pi.obdii.orchestrator.lifecycle import LifecycleMixin
from pi.power.battery_health import BATTERY_HEALTH_LOG_TABLE
from pi.power.drain_event_writer import DRAIN_OPEN_NOTE
from pi.power.power import PowerMonitor

_CONFIG: dict[str, Any] = {
    'pi': {
        'power': {'power_monitor': {'enabled': True}},
        'hardware': {'upsMonitor': {'socColdStartWindowSeconds': 1.0}},
    },
}


class FakeUps:
    def __init__(self, *, vcell: float = 3.88, socPct: int = 79) -> None:
        self.vcell = vcell
        self.socPct = socPct

    def getVcell(self) -> float:
        return self.vcell

    def getBatteryPercentage(self) -> int:
        return self.socPct


def _orch(
    *,
    database: Any,
    powerMonitor: Any,
    hardwareManager: Any = None,
    config: dict[str, Any] | None = None,
) -> LifecycleMixin:
    """A bare LifecycleMixin carrying only what the wiring touches."""
    orch = LifecycleMixin.__new__(LifecycleMixin)
    orch._config = config if config is not None else _CONFIG
    orch._database = database
    orch._powerMonitor = powerMonitor
    orch._hardwareManager = hardwareManager
    return orch


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / 'lifecycle_drain.db'), walMode=False)
    db.initialize()
    return db


def _rows(database: ObdDatabase) -> list[tuple[Any, ...]]:
    with database.connect() as conn:
        return conn.execute(
            "SELECT drain_event_id, end_timestamp, start_vcell_v, "
            f"end_vcell_v, runtime_seconds FROM {BATTERY_HEALTH_LOG_TABLE} "
            "ORDER BY drain_event_id"
        ).fetchall()


# ================================================================================
# The seam
# ================================================================================


class TestDrainWriterIsWiredToPowerMonitor:
    """PowerMonitor.onTransition is the registration point (AC [SEAM])."""

    def test_transitionsThroughTheRealPowerMonitorWriteARealRow(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: the orchestrator wiring with a live PowerMonitor + UpsMonitor.
        When:  GPIO6 truth drives AC -> battery -> AC through PowerMonitor.
        Then:  one complete production row lands, with real gauge values.
        """
        monitor = PowerMonitor(database=freshDb, enabled=True)
        hardware = MagicMock()
        hardware.upsMonitor = FakeUps()
        orch = _orch(
            database=freshDb, powerMonitor=monitor, hardwareManager=hardware,
        )

        orch._initializeDrainEventWriter()

        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)
        monitor.checkPowerStatus(True)

        rows = _rows(freshDb)
        assert len(rows) == 1
        _, endTs, startVcell, endVcell, runtime = rows[0]
        assert endTs is not None
        assert startVcell == pytest.approx(3.88)
        assert endVcell == pytest.approx(3.88)
        assert runtime is not None

    def test_upsIsResolvedLate_notCapturedAtWiringTime(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: HardwareManager has no UpsMonitor yet when the writer is wired
               (HardwareManager.start() builds it later).
        When:  the UpsMonitor appears and only THEN power is lost.
        Then:  the row carries real values.  A resolver captured at wiring time
               would have pinned None and written NULL forever -- the
               US-501/502/503 boot-order trap, now six sightings.
        """
        monitor = PowerMonitor(database=freshDb, enabled=True)
        hardware = MagicMock()
        hardware.upsMonitor = None
        orch = _orch(
            database=freshDb, powerMonitor=monitor, hardwareManager=hardware,
        )

        orch._initializeDrainEventWriter()
        hardware.upsMonitor = FakeUps(vcell=3.71)

        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)

        assert _rows(freshDb)[0][2] == pytest.approx(3.71)

    def test_hardwareManagerAbsentEntirely_recordsNullNotACrash(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: no HardwareManager at all (bench, hardware init failed).
        When:  power is lost.
        Then:  the drain is still recorded with a NULL gauge column.
        """
        monitor = PowerMonitor(database=freshDb, enabled=True)
        orch = _orch(
            database=freshDb, powerMonitor=monitor, hardwareManager=None,
        )

        orch._initializeDrainEventWriter()
        monitor.checkPowerStatus(True)
        monitor.checkPowerStatus(False)

        assert _rows(freshDb)[0][2] is None


# ================================================================================
# The boot reaper runs at wiring time, before anything can open
# ================================================================================


class TestBootReaperRunsAtWiring:
    """Reap-before-register is what keeps every computed runtime same-boot."""

    def test_crashedDrainIsReapedWhenTheWriterIsWired(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: a drain row left open by a previous boot's hard crash.
        When:  the orchestrator wires the drain writer at boot.
        Then:  the orphan is stamped closed with runtime_seconds AND end_vcell_v
               NULL -- honest-NA, never a cross-reboot runtime.
        """
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                "(start_timestamp, start_vcell_v, load_class, notes, "
                " data_source) VALUES (?, ?, 'production', ?, 'real')",
                ('2026-08-02T22:14:03Z', 3.95, DRAIN_OPEN_NOTE),
            )
        monitor = PowerMonitor(database=freshDb, enabled=True)
        orch = _orch(database=freshDb, powerMonitor=monitor)

        orch._initializeDrainEventWriter()

        _, endTs, startVcell, endVcell, runtime = _rows(freshDb)[0]
        assert endTs is not None
        assert runtime is None
        assert endVcell is None
        assert startVcell == pytest.approx(3.95)

    def test_reapHappensBeforeTheTransitionCallbackIsRegistered(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: a crashed drain row, and a PowerMonitor that inspects the table
               at the instant onTransition is called.
        When:  the writer is wired.
        Then:  the orphan is ALREADY stamped by then -- the reap ran first.

        Ordering is the invariant, not an implementation detail: if a
        transition could open a row before the reap, the reaper would stamp
        THIS boot's live drain as interrupted and that drain would be lost.
        Asserted behaviourally rather than by reading the source -- the
        docstring mentions both names, so a text-order check proves nothing.
        """
        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                "(start_timestamp, start_vcell_v, load_class, notes, "
                " data_source) VALUES (?, ?, 'production', ?, 'real')",
                ('2026-08-02T22:14:03Z', 3.95, DRAIN_OPEN_NOTE),
            )

        observed: dict[str, Any] = {}

        def _inspectAtRegistration(_callback: Any) -> None:
            observed['endTimestampAtRegistration'] = _rows(freshDb)[0][1]

        monitor = MagicMock()
        monitor.onTransition.side_effect = _inspectAtRegistration
        orch = _orch(database=freshDb, powerMonitor=monitor)

        orch._initializeDrainEventWriter()

        assert monitor.onTransition.called
        assert observed['endTimestampAtRegistration'] is not None


# ================================================================================
# Soft-fail posture -- the drain log must never break boot
# ================================================================================


class TestSoftFailPosture:
    """A bookkeeping writer is never boot-critical."""

    def test_noPowerMonitor_isASkip(self, freshDb: ObdDatabase) -> None:
        orch = _orch(database=freshDb, powerMonitor=None)

        orch._initializeDrainEventWriter()

        assert getattr(orch, '_drainEventWriter', None) is None

    def test_noDatabase_isASkip(self) -> None:
        orch = _orch(database=None, powerMonitor=MagicMock())

        orch._initializeDrainEventWriter()

        assert getattr(orch, '_drainEventWriter', None) is None

    def test_powerMonitorDisabled_isASkip(self, freshDb: ObdDatabase) -> None:
        """The writer follows PowerMonitor's own gate -- no second flag."""
        orch = _orch(
            database=freshDb,
            powerMonitor=None,
            config={
                'pi': {'power': {'power_monitor': {'enabled': False}}},
            },
        )

        orch._initializeDrainEventWriter()

        assert getattr(orch, '_drainEventWriter', None) is None

    def test_registrationFault_isSwallowed(self, freshDb: ObdDatabase) -> None:
        """
        Given: a PowerMonitor whose onTransition raises.
        When:  the writer is wired.
        Then:  boot continues -- battery_health_log is bookkeeping, and losing
               it must never cost the drive capture it sits beside.
        """
        monitor = MagicMock()
        monitor.onTransition.side_effect = RuntimeError('registration broke')
        orch = _orch(database=freshDb, powerMonitor=monitor)

        orch._initializeDrainEventWriter()

        assert getattr(orch, '_drainEventWriter', None) is None

    def test_isCalledFromTheComponentInitChain(self) -> None:
        """
        Given: the orchestrator's component-init chain.
        When:  read.
        Then:  it calls _initializeDrainEventWriter AFTER
               _initializePowerMonitor (the writer needs the monitor to exist).

        Without this the whole feature is a well-tested module nobody calls --
        exactly the US-442 gap this story exists to close.
        """
        source = inspect.getsource(LifecycleMixin._initializeAllComponents)
        assert '_initializeDrainEventWriter()' in source
        assert (
            source.index('_initializePowerMonitor()')
            < source.index('_initializeDrainEventWriter()')
        )
