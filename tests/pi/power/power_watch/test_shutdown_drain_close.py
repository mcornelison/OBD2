################################################################################
# File Name: test_shutdown_drain_close.py
# Purpose/Description: US-526 (F-123) -- the PRIMARY drain close runs ON the
#                      shutdown path.  Atlas's Option C ruling makes the
#                      ShutdownSequencer close primary because, under Spool's
#                      depth gate, the run-to-cutoff drain is the ONLY qualifying
#                      drain and it ends exactly there.  These tests pin the
#                      sequencer's prePowerOffFn hook (both poweroff paths, never
#                      on an abort, never able to block poweroff) and the
#                      __main__ factory that wires it -- Atlas DoD 3 asks for the
#                      close exercised on the shutdown path, not just a warm unit
#                      test of the writer.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex (US-526) | Initial -- pre-poweroff drain-close hook.
# ================================================================================
################################################################################

"""The drain close on the real shutdown path (US-526 / Atlas Option C)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BATTERY_HEALTH_LOG_TABLE
from src.pi.power.drain_event_writer import (
    DRAIN_OPEN_NOTE,
    makeDrainEventWriterForPath,
)
from src.pi.power.power_watch.controller import ShutdownSequencer

_SETTLED_UPTIME_S = 9999.0


class FakeUps:
    """UpsMonitor-shaped double."""

    def __init__(self, *, vcell: float = 3.48, socPct: int = 7) -> None:
        self.vcell = vcell
        self.socPct = socPct

    def getVcell(self) -> float:
        return self.vcell

    def getBatteryPercentage(self) -> int:
        return self.socPct


def _sequencer(
    *,
    calls: list[str],
    prePowerOffFn: Any,
    vcell: float = 3.90,
    vcellFloor: float = 3.45,
    onBattery: Any = None,
) -> ShutdownSequencer:
    """A sequencer whose every side effect appends to ``calls`` in order."""

    def _pipeline() -> None:
        calls.append('pipeline')

    def _powerOff() -> None:
        calls.append('poweroff')

    return ShutdownSequencer(
        isOnBattery=onBattery if onBattery is not None else (lambda: True),
        vcell=lambda: vcell,
        runPipelineFn=_pipeline,
        powerOffFn=_powerOff,
        vcellFloor=vcellFloor,
        totalCapSec=5.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        prePowerOffFn=prePowerOffFn,
    )


# ================================================================================
# The hook fires on BOTH poweroff paths
# ================================================================================


class TestPrePowerOffHookFires:
    """A drain must be closed on every path that actually powers the Pi off."""

    def test_normalPath_hookRunsImmediatelyBeforePoweroff(self) -> None:
        """
        Given: a confirmed sustained power loss above the VCELL floor.
        When:  the bounded pipeline finishes and poweroff is reached.
        Then:  the hook runs LAST before poweroff -- so the close records the
               deepest VCELL the drain actually reached.
        """
        calls: list[str] = []
        sequencer = _sequencer(
            calls=calls, prePowerOffFn=lambda: calls.append('drain-close'),
        )

        sequencer.handleOnBattery()

        assert calls == ['pipeline', 'drain-close', 'poweroff']

    def test_vcellFloorFastPath_hookStillRuns(self) -> None:
        """
        Given: a successful VCELL read at or below the floor after sustained
               loss -- the run-to-cutoff drain.
        When:  the sequencer short-circuits straight to poweroff.
        Then:  the hook STILL runs, even though the pipeline was skipped.

        This is the load-bearing case: under Spool's depth gate
        (end_vcell_v <= 3.50 V) the run-to-cutoff drain is the ONLY qualifying
        drain, and this fast path is exactly how it ends.  A close implemented
        as a pipeline ShutdownTask would be skipped here and the verdict would
        never see a single qualifying row.
        """
        calls: list[str] = []
        sequencer = _sequencer(
            calls=calls,
            prePowerOffFn=lambda: calls.append('drain-close'),
            vcell=3.40,
            vcellFloor=3.45,
        )

        sequencer.handleOnBattery()

        assert 'pipeline' not in calls
        assert calls == ['drain-close', 'poweroff']

    def test_hookRunsExactlyOncePerPoweroff(self) -> None:
        calls: list[str] = []
        sequencer = _sequencer(
            calls=calls, prePowerOffFn=lambda: calls.append('drain-close'),
        )

        sequencer.handleOnBattery()

        assert calls.count('drain-close') == 1


# ================================================================================
# The hook never fires when the Pi is NOT powering off
# ================================================================================


class TestPrePowerOffHookDoesNotFireOnAbort:
    """An aborted shutdown is not a drain end -- the drain is still running."""

    def test_transientBlip_noHookNoPoweroff(self) -> None:
        """
        Given: power returns inside the smoothing window (electrical blip).
        When:  the sequencer aborts.
        Then:  neither poweroff nor the drain close runs.  Closing here would
               end a drain that is still in progress; the collector's
               BATTERY->AC transition is what legitimately closes it.
        """
        calls: list[str] = []
        readings = iter([True, False, False, False])
        sequencer = ShutdownSequencer(
            isOnBattery=lambda: next(readings),
            vcell=lambda: 3.90,
            runPipelineFn=lambda: calls.append('pipeline'),
            powerOffFn=lambda: calls.append('poweroff'),
            vcellFloor=3.45,
            totalCapSec=5.0,
            smoothingSec=1.0,
            smoothingPollSec=0.0,
            sleepFn=lambda _s: None,
            monotonicFn=iter([0.0, 0.0, 0.5, 0.9]).__next__,
            prePowerOffFn=lambda: calls.append('drain-close'),
        )

        sequencer.handleOnBattery()

        assert calls == []

    def test_powerReturnsMidWindow_noHookNoPoweroff(self) -> None:
        """
        Given: sustained loss confirmed, then power returns during the bounded
               window.
        When:  the sequencer aborts after the pipeline.
        Then:  the pipeline ran but the drain close did NOT -- power is back, so
               the restore path owns the close.
        """
        calls: list[str] = []
        # Read 1 = the (collapsed) smoothing check -> lost confirmed.
        # Read 2 = the post-window re-check -> power is back -> abort.
        readings = iter([True, False])
        sequencer = ShutdownSequencer(
            isOnBattery=lambda: next(readings),
            vcell=lambda: 3.90,
            runPipelineFn=lambda: calls.append('pipeline'),
            powerOffFn=lambda: calls.append('poweroff'),
            vcellFloor=3.45,
            totalCapSec=5.0,
            smoothingSec=0.0,
            smoothingPollSec=0.0,
            sleepFn=lambda _s: None,
            prePowerOffFn=lambda: calls.append('drain-close'),
        )

        sequencer.handleOnBattery()

        assert calls == ['pipeline']


# ================================================================================
# The hook can never harm the shutdown
# ================================================================================


class TestPrePowerOffHookIsBestEffort:
    """Poweroff is never blocked by the drain close (Atlas A-2 constraint c)."""

    def test_raisingHookStillPowersOff(self) -> None:
        """
        Given: a drain close that raises (locked DB, missing table).
        When:  the sequencer reaches poweroff.
        Then:  poweroff still happens.  A bookkeeping row is never worth
               leaving the Pi up on a dying battery.
        """
        calls: list[str] = []

        def _boom() -> None:
            calls.append('drain-close')
            raise RuntimeError('database is locked')

        sequencer = _sequencer(calls=calls, prePowerOffFn=_boom)

        sequencer.handleOnBattery()

        assert calls == ['pipeline', 'drain-close', 'poweroff']

    def test_noHookWired_behavesExactlyLikeBefore(self) -> None:
        """
        Given: no prePowerOffFn (the default).
        When:  the sequencer runs.
        Then:  the legacy sequence is byte-identical -- pipeline then poweroff.
        """
        calls: list[str] = []
        sequencer = _sequencer(calls=calls, prePowerOffFn=None)

        sequencer.handleOnBattery()

        assert calls == ['pipeline', 'poweroff']


# ================================================================================
# End-to-end: the shutdown path closes a REAL row in a REAL database
# ================================================================================


class TestShutdownPathClosesARealDrainRow:
    """Atlas DoD 3: exercised ON the shutdown path, not just warm."""

    @pytest.fixture()
    def openDrainDb(self, tmp_path: Path) -> ObdDatabase:
        """A database holding one open production drain row."""
        db = ObdDatabase(str(tmp_path / 'shutdown_drain.db'), walMode=False)
        db.initialize()
        writer = makeDrainEventWriterForPath(
            dbPath=db.dbPath,
            upsResolver=lambda: FakeUps(vcell=4.05, socPct=97),
            uptimeReader=lambda: _SETTLED_UPTIME_S,
            busyTimeoutSec=5.0,
        )
        writer.openDrainEvent()
        return db

    def _row(self, database: ObdDatabase) -> dict[str, Any]:
        with database.connect() as conn:
            row = conn.execute(
                "SELECT end_timestamp, end_vcell_v, end_soc_pct, "
                f"runtime_seconds, notes FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchone()
        return {
            'end_timestamp': row[0],
            'end_vcell_v': row[1],
            'end_soc_pct': row[2],
            'runtime_seconds': row[3],
            'notes': row[4],
        }

    def test_cutoffShutdown_closesTheOpenRowWithRealDepth(
        self, openDrainDb: ObdDatabase,
    ) -> None:
        """
        Given: an open drain row and a real ShutdownSequencer whose VCELL has
               fallen to the floor (the run-to-cutoff drain).
        When:  handleOnBattery drives the real shutdown path to poweroff.
        Then:  the row is closed with a REAL end_vcell_v at drain depth and a
               real runtime_seconds -- the row shape the depth-gate verdict
               needs.
        """
        writer = makeDrainEventWriterForPath(
            dbPath=openDrainDb.dbPath,
            upsResolver=lambda: FakeUps(vcell=3.44, socPct=4),
            uptimeReader=lambda: _SETTLED_UPTIME_S,
            busyTimeoutSec=5.0,
        )
        poweredOff: list[str] = []
        sequencer = ShutdownSequencer(
            isOnBattery=lambda: True,
            vcell=lambda: 3.44,
            runPipelineFn=lambda: None,
            powerOffFn=lambda: poweredOff.append('poweroff'),
            vcellFloor=3.45,
            totalCapSec=5.0,
            smoothingSec=0.0,
            smoothingPollSec=0.0,
            sleepFn=lambda _s: None,
            prePowerOffFn=lambda: writer.closeOpenDrainEvent(
                reason='powering_off',
            ),
        )

        sequencer.handleOnBattery()

        assert poweredOff == ['poweroff']
        row = self._row(openDrainDb)
        assert row['end_timestamp'] is not None
        assert row['end_vcell_v'] == pytest.approx(3.44)
        assert row['end_soc_pct'] == pytest.approx(4.0)
        assert row['runtime_seconds'] is not None
        assert row['notes'] == DRAIN_OPEN_NOTE


# ================================================================================
# __main__ wiring seam
# ================================================================================


class TestMainWiringSeam:
    """The service must actually wire the hook, not just support one."""

    def test_buildDrainCloseHook_returnsACallableThatClosesTheRow(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: a validated-shaped config pointing at a db with an open drain.
        When:  the __main__ factory builds the hook and it is called.
        Then:  the row closes -- the factory really is wired to the writer.
        """
        from src.pi.power.power_watch import __main__ as m

        db = ObdDatabase(str(tmp_path / 'wiring.db'), walMode=False)
        db.initialize()
        makeDrainEventWriterForPath(
            dbPath=db.dbPath,
            upsResolver=lambda: FakeUps(),
            uptimeReader=lambda: _SETTLED_UPTIME_S,
            busyTimeoutSec=5.0,
        ).openDrainEvent()

        hook = m.buildDrainCloseHook(
            config={
                'pi': {
                    'database': {'path': db.dbPath},
                    'powerWatch': {'perTaskTimeoutSec': 5.0},
                    'hardware': {
                        'upsMonitor': {'socColdStartWindowSeconds': 1.0},
                    },
                },
            },
            upsResolver=lambda: FakeUps(vcell=3.47, socPct=5),
            uptimeReader=lambda: _SETTLED_UPTIME_S,
        )
        assert hook is not None
        hook()

        with db.connect() as conn:
            endVcell = conn.execute(
                f"SELECT end_vcell_v FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchone()[0]
        assert endVcell == pytest.approx(3.47)

    def test_buildDrainCloseHook_missingDbPath_returnsNone(self) -> None:
        """
        Given: a config with no pi.database.path.
        When:  the factory runs.
        Then:  it returns None (hook disabled) instead of guessing a path.
        """
        from src.pi.power.power_watch import __main__ as m

        assert m.buildDrainCloseHook(
            config={'pi': {}},
            upsResolver=lambda: None,
        ) is None

    def test_hookNeverRaises_evenWithAnAbsentDatabase(
        self, tmp_path: Path,
    ) -> None:
        """
        Given: a config path whose database does not exist.
        When:  the hook is called on the shutdown path.
        Then:  it returns without raising -- poweroff proceeds.
        """
        from src.pi.power.power_watch import __main__ as m

        hook = m.buildDrainCloseHook(
            config={
                'pi': {
                    'database': {'path': str(tmp_path / 'absent.db')},
                    'powerWatch': {'perTaskTimeoutSec': 1.0},
                },
            },
            upsResolver=lambda: FakeUps(),
            uptimeReader=lambda: _SETTLED_UPTIME_S,
        )
        assert hook is not None
        hook()  # must not raise
