################################################################################
# File Name: test_drain_event_writer.py
# Purpose/Description: US-526 (F-123) tests for the PRODUCTION drain-event
#                      writer -- the caller that makes battery_health_log grow
#                      again after the US-216 auto-open path was retired
#                      (US-442 / TD-058).  Covers Atlas's Option C ruling
#                      (2026-08-02): open at wall-power loss, close at restore
#                      or on the shutdown path, boot reaper as the crash
#                      backstop with honest-NA (runtime_seconds AND end_vcell_v
#                      stay NULL).  Also pins the two traps that would silently
#                      fabricate data: the late-bound UPS read (US-501/502/503
#                      boot-order trap) and the foreign-row guard that keeps the
#                      writer off the US-442 tombstoned historical orphans.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Rex (US-526) | Initial -- production drain writer catalog.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.power.drain_event_writer` (US-526 / Atlas Option C)."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BATTERY_HEALTH_LOG_TABLE
from src.pi.power.battery_health_verdict import (
    VERDICT_UNKNOWN,
    computeBatteryHealthVerdict,
)
from src.pi.power.drain_event_writer import (
    DRAIN_OPEN_NOTE,
    DrainEventWriter,
    makeDrainEventWriterForPath,
)

_ISO_UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

#: Any uptime past the cold-start window -- the register SoC% is trustworthy.
_SETTLED_UPTIME_S = 9999.0

_ROW_COLUMNS = (
    'start_timestamp, end_timestamp, start_vcell_v, end_vcell_v, '
    'start_soc_pct, end_soc_pct, runtime_seconds, load_class, notes'
)


# ================================================================================
# Doubles
# ================================================================================


class FakeUps:
    """UpsMonitor-shaped double: real numbers, or a raising gauge."""

    def __init__(
        self,
        *,
        vcell: float | None = 3.92,
        socPct: int | None = 84,
        error: Exception | None = None,
    ) -> None:
        self.vcell = vcell
        self.socPct = socPct
        self.error = error
        self.vcellReads = 0

    def getVcell(self) -> float:
        self.vcellReads += 1
        if self.error is not None:
            raise self.error
        assert self.vcell is not None
        return self.vcell

    def getBatteryPercentage(self) -> int:
        if self.error is not None:
            raise self.error
        assert self.socPct is not None
        return self.socPct


class _ForeignPowerSource(Enum):
    """A PowerSource look-alike from a DIFFERENT class object.

    Stands in for the cross-module enum-identity trap: ``pi.power.types`` and
    ``src.pi.power.types`` are distinct module objects, so their ``PowerSource``
    members are NOT ``==``.  The writer must compare on ``.value``.
    """

    UNKNOWN = 'unknown'
    AC_POWER = 'ac_power'
    BATTERY = 'battery'


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / 'test_drain_writer.db'), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def ups() -> FakeUps:
    return FakeUps()


def _makeWriter(
    database: Any,
    ups: Any,
    *,
    uptime: float | None = _SETTLED_UPTIME_S,
) -> DrainEventWriter:
    return DrainEventWriter(
        database=database,
        upsResolver=lambda: ups,
        uptimeReader=lambda: uptime,
    )


def _rows(database: ObdDatabase) -> list[dict[str, Any]]:
    with database.connect() as conn:
        fetched = conn.execute(
            f"SELECT drain_event_id, {_ROW_COLUMNS} "
            f"FROM {BATTERY_HEALTH_LOG_TABLE} ORDER BY drain_event_id"
        ).fetchall()
    keys = ['drain_event_id', *[c.strip() for c in _ROW_COLUMNS.split(',')]]
    return [dict(zip(keys, row, strict=True)) for row in fetched]


def _insertForeignOrphan(database: ObdDatabase, *, notes: str) -> int:
    """Insert a still-open row the writer did NOT open (US-442 residue shape)."""
    with database.connect() as conn:
        cursor = conn.execute(
            f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
            "(start_timestamp, start_vcell_v, load_class, notes, data_source) "
            "VALUES (?, ?, 'production', ?, 'real')",
            ('2026-05-09T04:11:07Z', 4.15, notes),
        )
        return int(cursor.lastrowid or 0)


# ================================================================================
# AC -> BATTERY opens a real row
# ================================================================================


class TestOpenAtWallPowerLoss:
    """AC->BATTERY opens a drain row carrying REAL gauge values."""

    def test_acToBattery_opensRowWithRealVcellAndSocPct(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a writer wired to a readable MAX17048.
        When:  a real AC->BATTERY transition fires.
        Then:  one open production row carries the REAL start_vcell_v +
               start_soc_pct and the writer's own provenance note.
        """
        writer = _makeWriter(freshDb, ups)

        writer.handlePowerTransition('ac_power', 'battery')

        rows = _rows(freshDb)
        assert len(rows) == 1
        row = rows[0]
        assert row['start_vcell_v'] == pytest.approx(3.92)
        assert row['start_soc_pct'] == pytest.approx(84.0)
        assert row['load_class'] == 'production'
        assert row['notes'] == DRAIN_OPEN_NOTE
        assert row['end_timestamp'] is None
        assert _ISO_UTC.match(row['start_timestamp']) is not None

    def test_gaugeUnreadable_writesNullNeverAGuessedNumber(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: a MAX17048 that raises on every read.
        When:  a wall-power loss opens the drain.
        Then:  the row still opens (the drain DID happen) but both gauge
               columns are NULL -- honest-instrument, never a guessed number.
        """
        writer = _makeWriter(freshDb, FakeUps(error=OSError('i2c bus error')))

        writer.handlePowerTransition('ac_power', 'battery')

        row = _rows(freshDb)[0]
        assert row['start_vcell_v'] is None
        assert row['start_soc_pct'] is None

    def test_upsAbsentAtConstruction_isResolvedLateAtTransitionTime(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: the UPS does not exist yet when the writer is constructed
               (HardwareManager.start() runs later -- the US-501/502/503
               boot-order trap).
        When:  the UPS appears and only THEN a transition fires.
        Then:  the row carries real values, proving the resolver is called at
               transition time and not captured at construction.
        """
        holder: dict[str, Any] = {'ups': None}
        writer = DrainEventWriter(
            database=freshDb,
            upsResolver=lambda: holder['ups'],
            uptimeReader=lambda: _SETTLED_UPTIME_S,
        )

        holder['ups'] = ups
        writer.handlePowerTransition('ac_power', 'battery')

        assert _rows(freshDb)[0]['start_vcell_v'] == pytest.approx(3.92)

    def test_upsStillAbsentAtTransition_opensRowWithNulls(
        self, freshDb: ObdDatabase,
    ) -> None:
        """
        Given: no UPS at all (bench box, hardware absent).
        When:  a transition fires.
        Then:  the drain is still recorded, with NULL gauge columns.
        """
        writer = DrainEventWriter(
            database=freshDb,
            upsResolver=lambda: None,
            uptimeReader=lambda: _SETTLED_UPTIME_S,
        )

        writer.handlePowerTransition('ac_power', 'battery')

        row = _rows(freshDb)[0]
        assert row['start_vcell_v'] is None
        assert row['start_soc_pct'] is None

    def test_coldStartWindow_suppressesSocPctButKeepsVcell(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: the gauge is inside its ~3-min ModelGauge calibration window.
        When:  a drain opens.
        Then:  start_soc_pct is NULL (register uncalibrated) but start_vcell_v
               is kept -- VCELL is trustworthy at cold start, SoC%% is not
               (US-234, the reason the ladder moved off SoC onto VCELL).
        """
        writer = _makeWriter(freshDb, ups, uptime=5.0)

        writer.handlePowerTransition('ac_power', 'battery')

        row = _rows(freshDb)[0]
        assert row['start_vcell_v'] == pytest.approx(3.92)
        assert row['start_soc_pct'] is None

    def test_unknownUptime_suppressesSocPct(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: uptime is unknowable (off-Linux -- /proc/uptime absent).
        When:  a drain opens.
        Then:  start_soc_pct is NULL: an uptime we cannot read cannot prove the
               gauge settled, and uncertain must never render as a number.
        """
        writer = _makeWriter(freshDb, ups, uptime=None)

        writer.handlePowerTransition('ac_power', 'battery')

        assert _rows(freshDb)[0]['start_soc_pct'] is None

    def test_transitionComparisonIsValueBased_notEnumIdentity(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: PowerSource members from a DIFFERENT class object (the
               pi.* vs src.pi.* dual-import identity trap that cost the
               9-drain saga).
        When:  a transition fires with those members.
        Then:  the drain still opens -- the writer compares on .value, so a
               dual-imported enum cannot silently make the writer inert.
        """
        writer = _makeWriter(freshDb, ups)

        writer.handlePowerTransition(
            _ForeignPowerSource.AC_POWER, _ForeignPowerSource.BATTERY,
        )

        assert len(_rows(freshDb)) == 1

    @pytest.mark.parametrize(
        ('fromValue', 'toValue'),
        [
            ('unknown', 'battery'),
            ('unknown', 'ac_power'),
            ('ac_power', 'ac_power'),
            ('battery', 'battery'),
        ],
    )
    def test_nonLossTransitions_openNothing(
        self, freshDb: ObdDatabase, ups: FakeUps,
        fromValue: str, toValue: str,
    ) -> None:
        """
        Given: a transition that is not a real AC->BATTERY loss.
        When:  it fires.
        Then:  no row opens.  UNKNOWN->BATTERY especially: a Pi that boots
               already on battery has NO knowable loss instant, and a row
               stamped at boot time would misreport the drain's start (and so
               its runtime).  Absent beats wrong.
        """
        writer = _makeWriter(freshDb, ups)

        writer.handlePowerTransition(fromValue, toValue)

        assert _rows(freshDb) == []


# ================================================================================
# BATTERY -> AC closes the row
# ================================================================================


class TestCloseAtPowerRestore:
    """BATTERY->AC closes the open row with real end values + real runtime."""

    def test_batteryToAc_closesRowWithRealEndVcellAndRuntime(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: an open drain row.
        When:  wall power is restored.
        Then:  the row closes with a real end_vcell_v / end_soc_pct and a
               non-NULL runtime_seconds computed from the timestamp delta.
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')

        ups.vcell = 3.61
        ups.socPct = 41
        writer.handlePowerTransition('battery', 'ac_power')

        row = _rows(freshDb)[0]
        assert row['end_timestamp'] is not None
        assert row['end_vcell_v'] == pytest.approx(3.61)
        assert row['end_soc_pct'] == pytest.approx(41.0)
        assert row['runtime_seconds'] is not None
        assert row['start_vcell_v'] == pytest.approx(3.92)

    def test_noOpenRow_closeIsANoOp(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: no open drain row (no loss was ever seen).
        When:  a BATTERY->AC transition fires anyway.
        Then:  nothing is written and nothing raises.
        """
        writer = _makeWriter(freshDb, ups)

        assert writer.handlePowerTransition('battery', 'ac_power') is None
        assert _rows(freshDb) == []

    def test_closeNeverTouchesAForeignOpenRow(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a US-442 tombstoned historical orphan whose end_timestamp is
               DELIBERATELY NULL (no timing-truth source exists for it).
        When:  a power-restore close runs with no row of the writer's own.
        Then:  the foreign row is left untouched.

        This is the load-bearing guard.  ``endDrainEvent`` derives
        runtime_seconds from the start/end delta, so closing a months-old
        orphan would manufacture a multi-month runtime AND attach a real
        end_vcell_v to it -- a row that then looks QUALIFYING to the verdict.
        That is strictly worse than the reaper trap Atlas flagged.
        """
        foreignId = _insertForeignOrphan(
            freshDb, notes='HISTORICAL ORPHAN (US-442 residue)',
        )
        writer = _makeWriter(freshDb, ups)

        assert writer.closeOpenDrainEvent(reason='power_restored') is None

        row = _rows(freshDb)[0]
        assert row['drain_event_id'] == foreignId
        assert row['end_timestamp'] is None
        assert row['runtime_seconds'] is None

    def test_gaugeUnreadableAtClose_writesNullEndVcell(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: the gauge dies between open and close.
        When:  the row closes.
        Then:  end_vcell_v / end_soc_pct are NULL but the row IS closed with a
               real runtime -- duration is known, depth is not.
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')

        ups.error = OSError('i2c bus error')
        writer.handlePowerTransition('battery', 'ac_power')

        row = _rows(freshDb)[0]
        assert row['end_timestamp'] is not None
        assert row['end_vcell_v'] is None
        assert row['end_soc_pct'] is None
        assert row['runtime_seconds'] is not None

    def test_secondCloseIsFirstCloseWins(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a row already closed at restore.
        When:  a second close arrives (e.g. the shutdown path also fires).
        Then:  the stored close is preserved -- the writer stops finding the
               row at all, so the original end values cannot be overwritten.
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')
        ups.vcell = 3.61
        writer.handlePowerTransition('battery', 'ac_power')
        firstEnd = _rows(freshDb)[0]['end_timestamp']

        ups.vcell = 4.10
        assert writer.closeOpenDrainEvent(reason='shutdown') is None

        row = _rows(freshDb)[0]
        assert row['end_timestamp'] == firstEnd
        assert row['end_vcell_v'] == pytest.approx(3.61)


# ================================================================================
# Boot reaper (Atlas DoD -- honest-NA, never a manufactured runtime)
# ================================================================================


class TestBootReaper:
    """The crash backstop: stamp end_timestamp ONLY, both value columns NULL."""

    def test_reapStampsOnlyEndTimestamp_runtimeAndEndVcellStayNull(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a drain row left open by a hard crash (previous boot).
        When:  the boot reaper runs.
        Then:  end_timestamp is stamped, and runtime_seconds AND end_vcell_v
               (and end_soc_pct) stay NULL.  Across a reboot endDrainEvent
               would manufacture a multi-hour runtime from the timestamp
               delta, and a fabricated end_vcell_v <= 3.50 would falsely pass
               Spool's depth gate -- so the reaper must never call it.
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')

        reaped = writer.reapOpenDrainEvents()

        row = _rows(freshDb)[0]
        assert reaped == [row['drain_event_id']]
        assert _ISO_UTC.match(row['end_timestamp']) is not None
        assert row['runtime_seconds'] is None
        assert row['end_vcell_v'] is None
        assert row['end_soc_pct'] is None
        # The open-side facts are authoritative and untouched.
        assert row['start_vcell_v'] == pytest.approx(3.92)

    def test_reapNeverReadsTheGauge(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a readable gauge at reap time.
        When:  the reaper runs.
        Then:  it does not read VCELL at all.  A reap-time voltage is TODAY's
               resting voltage, not the interrupted drain's depth; writing it
               would be the fabrication the NULL exists to prevent.
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')
        readsAfterOpen = ups.vcellReads

        writer.reapOpenDrainEvents()

        assert ups.vcellReads == readsAfterOpen

    def test_reapIgnoresClosedRows(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a row already closed by the ShutdownSequencer (the PRIMARY
               close) with a real runtime.
        When:  the reaper runs on the next boot.
        Then:  it targets only still-open rows, so the legitimate close is
               never clobbered (first-close-wins respected).
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')
        writer.handlePowerTransition('battery', 'ac_power')
        before = _rows(freshDb)[0]

        assert writer.reapOpenDrainEvents() == []

        assert _rows(freshDb)[0] == before

    def test_reapIgnoresForeignOpenRows(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: the US-442 tombstoned historical orphans, whose NULL
               end_timestamp is deliberate and is what makes
               annotate_orphan_production_drain_events.py idempotent.
        When:  the reaper runs.
        Then:  they are left NULL.  The reaper narrows Atlas's
               ``WHERE end_timestamp IS NULL`` to rows THIS writer opened --
               a narrowing can only make the backstop more conservative.
        """
        foreignId = _insertForeignOrphan(
            freshDb, notes='HISTORICAL ORPHAN (US-442 residue)',
        )
        writer = _makeWriter(freshDb, ups)

        assert writer.reapOpenDrainEvents() == []

        row = _rows(freshDb)[0]
        assert row['drain_event_id'] == foreignId
        assert row['end_timestamp'] is None

    def test_reapedOrphanIsExcludedByTheDepthGateVerdict(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: three reaped orphans (enough to satisfy the 3-sample minimum
               if they counted).
        When:  the verdict is computed over the table.
        Then:  the verdict is unknown -- a reaped orphan does not vote.

        Double-safe by construction: runtime_seconds NULL fails today's
        runtime gate AND end_vcell_v NULL fails Spool's depth gate, so this
        holds before and after the US-527 band remap.
        """
        writer = _makeWriter(freshDb, ups)
        for _ in range(3):
            writer.handlePowerTransition('ac_power', 'battery')
            writer.reapOpenDrainEvents()

        rows = _rows(freshDb)
        assert len(rows) == 3
        for row in rows:
            assert row['runtime_seconds'] is None
            assert row['end_vcell_v'] is None

        verdict = computeBatteryHealthVerdict(
            rows=rows, nowIso='2026-08-03T12:00:00Z',
        )
        assert verdict.verdict == VERDICT_UNKNOWN
        assert verdict.qualifyingCount == 0

    def test_reapThenOpen_closeCannotResurrectThePreviousBootRow(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: the reaper ran at boot (closing a crashed drain), then a new
               drain opened this boot.
        When:  the new drain closes.
        Then:  the NEW row gets the runtime and the reaped row keeps its NULLs.

        This ordering -- reap BEFORE any transition can open -- is what makes
        every runtime the writer computes a same-boot delta, i.e. truthful.
        """
        writer = _makeWriter(freshDb, ups)
        writer.handlePowerTransition('ac_power', 'battery')
        writer.reapOpenDrainEvents()

        writer.handlePowerTransition('ac_power', 'battery')
        writer.handlePowerTransition('battery', 'ac_power')

        crashed, current = _rows(freshDb)
        assert crashed['runtime_seconds'] is None
        assert crashed['end_vcell_v'] is None
        assert current['runtime_seconds'] is not None
        assert current['end_vcell_v'] == pytest.approx(3.92)


# ================================================================================
# The production seam: a REAL PowerMonitor drives the writer
# ================================================================================


class TestRealPowerMonitorSeam:
    """PowerMonitor.onTransition is the registration point (AC [SEAM])."""

    def test_realTransitionsThroughPowerMonitor_writeOneCompleteRow(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: a real PowerMonitor with the writer registered via onTransition.
        When:  checkPowerStatus goes AC -> battery -> AC (the GPIO6 truth the
               US-502 _PowerSourceUiBridge feeds it).
        Then:  exactly one complete production row lands.  This drives the
               REAL callback plumbing, not the writer's method directly.
        """
        from src.pi.power.power import PowerMonitor

        writer = _makeWriter(freshDb, ups)
        monitor = PowerMonitor(database=freshDb, enabled=True)
        monitor.onTransition(writer.handlePowerTransition)

        monitor.checkPowerStatus(True)   # first read: UNKNOWN -> AC, no drain
        monitor.checkPowerStatus(False)  # real loss -> open
        monitor.checkPowerStatus(True)   # restore -> close

        rows = _rows(freshDb)
        assert len(rows) == 1
        assert rows[0]['end_timestamp'] is not None
        assert rows[0]['runtime_seconds'] is not None
        assert rows[0]['load_class'] == 'production'

    def test_bootingOnBatteryThroughPowerMonitor_opensNothing(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: the Pi's first observed power reading is already 'battery'.
        When:  that first reading lands.
        Then:  no drain row opens -- PowerMonitor suppresses the UNKNOWN->X
               transition, and the writer must not add its own path around it.
        """
        from src.pi.power.power import PowerMonitor

        writer = _makeWriter(freshDb, ups)
        monitor = PowerMonitor(database=freshDb, enabled=True)
        monitor.onTransition(writer.handlePowerTransition)

        monitor.checkPowerStatus(False)

        assert _rows(freshDb) == []


# ================================================================================
# Never raises into its caller (power-loss + shutdown paths)
# ================================================================================


class TestNeverRaisesIntoCaller:
    """A writer fault must never break a power transition or block poweroff."""

    class _BrokenDb:
        def connect(self) -> Any:
            raise RuntimeError('database is gone')

    def test_openFailure_isSwallowed(self, ups: FakeUps) -> None:
        writer = _makeWriter(self._BrokenDb(), ups)
        assert writer.handlePowerTransition('ac_power', 'battery') is None

    def test_closeFailure_isSwallowed(self, ups: FakeUps) -> None:
        writer = _makeWriter(self._BrokenDb(), ups)
        assert writer.closeOpenDrainEvent(reason='shutdown') is None

    def test_reapFailure_isSwallowed(self, ups: FakeUps) -> None:
        writer = _makeWriter(self._BrokenDb(), ups)
        assert writer.reapOpenDrainEvents() == []


# ================================================================================
# Path factory (the powerwatch process has no ObdDatabase)
# ================================================================================


class TestMakeDrainEventWriterForPath:
    """The shutdown-critical service builds a writer without pi.obdii."""

    def test_writesThroughAPlainSqlitePath(
        self, freshDb: ObdDatabase, ups: FakeUps,
    ) -> None:
        """
        Given: only the sqlite file path (what powerwatch has in config).
        When:  a drain is opened and closed through the path-built writer.
        Then:  the row lands in the same table the orchestrator writes.
        """
        writer = makeDrainEventWriterForPath(
            dbPath=freshDb.dbPath,
            upsResolver=lambda: ups,
            uptimeReader=lambda: _SETTLED_UPTIME_S,
            busyTimeoutSec=5.0,
        )

        writer.handlePowerTransition('ac_power', 'battery')
        writer.closeOpenDrainEvent(reason='powering_off')

        row = _rows(freshDb)[0]
        assert row['end_timestamp'] is not None
        assert row['runtime_seconds'] is not None

    def test_missingDatabaseFile_doesNotRaise(
        self, tmp_path: Path, ups: FakeUps,
    ) -> None:
        """
        Given: a db path whose table does not exist (fresh Pi, pre-migration).
        When:  the shutdown-path close runs.
        Then:  it returns None instead of raising into the poweroff sequence.
        """
        writer = makeDrainEventWriterForPath(
            dbPath=str(tmp_path / 'nope' / 'absent.db'),
            upsResolver=lambda: ups,
            uptimeReader=lambda: _SETTLED_UPTIME_S,
            busyTimeoutSec=1.0,
        )

        assert writer.closeOpenDrainEvent(reason='powering_off') is None
