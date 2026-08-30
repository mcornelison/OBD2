################################################################################
# File Name: test_drain_checkpoint.py
# Purpose/Description: US-605 (F-138) tests for the 30 s OPEN-drain checkpoint --
#                      Spool's US-504a "Consequence 2" ruling (commit 429a3ed),
#                      the part he was explicit he most wanted built.  US-526
#                      shipped open-at-loss / close-at-restore-or-shutdown / boot
#                      reaper but NO periodic checkpoint, so a single lost
#                      shutdown write discarded a CORRECT measurement entirely.
#
#                      The checkpoint converts "must not lose the shutdown write"
#                      from a HARD requirement into a SOFT one (AC-2): the boot
#                      reaper now closes an interrupted drain onto REAL
#                      checkpointed depth + runtime instead of honest-NA NULLs.
#
#                      The load-bearing rule under test is AC-5: a checkpoint
#                      must NEVER write a value it has not read.  A gauge that
#                      dies mid-drain must leave the last good reading standing,
#                      because NULLing it would destroy exactly the correct
#                      measurement this story exists to preserve.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-605) | Initial -- 30 s open-drain checkpoint catalog.
# ================================================================================
################################################################################

"""Tests for the US-605 open-drain checkpoint in :mod:`src.pi.power.drain_event_writer`."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.common.time.helper import CANONICAL_ISO_FORMAT, utcIsoNow
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BATTERY_HEALTH_LOG_TABLE
from src.pi.power.battery_health_verdict import (
    VERDICT_UNKNOWN,
    computeBatteryHealthVerdict,
)
from src.pi.power.drain_event_writer import (
    DRAIN_CHECKPOINT_INTERVAL_SECONDS,
    DRAIN_OPEN_NOTE,
    REAP_CHECKPOINTED_NOTE_SUFFIX,
    DrainEventWriter,
)

_ISO_UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')

#: Any uptime past the cold-start window -- the register SoC%% is trustworthy.
_SETTLED_UPTIME_S = 9999.0


# ================================================================================
# Doubles
# ================================================================================


class FakeUps:
    """UpsMonitor-shaped double whose gauge can be made to die mid-drain."""

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


class FakeClock:
    """An injectable ``time.monotonic`` the test drives by hand."""

    def __init__(self, *, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _CloseRacingDatabase:
    """``DatabaseLike`` that closes the open row between the SELECT and the UPDATE.

    Reproduces the REAL two-process race this story creates: the collector's
    checkpoint reads the open row's id, and before its UPDATE lands the
    ``eclipse-powerwatch`` process closes that same row on the shutdown path.
    Without an ``end_timestamp IS NULL`` guard on the checkpoint UPDATE, an
    older checkpoint reading would overwrite the close's FINAL depth -- the
    exact "a correct measurement is silently lost" defect, inverted.
    """

    def __init__(self, inner: ObdDatabase, *, raceAfterConnects: int) -> None:
        self._inner = inner
        self._raceAfterConnects = raceAfterConnects
        self.connects = 0
        self.raced = False

    def connect(self) -> Any:
        self.connects += 1
        shouldRace = self.connects == self._raceAfterConnects
        outer = self

        class _Ctx:
            def __enter__(self) -> Any:
                self._cm = outer._inner.connect()
                return self._cm.__enter__()

            def __exit__(self, *exc: Any) -> Any:
                result = self._cm.__exit__(*exc)
                if shouldRace and not outer.raced:
                    outer.raced = True
                    outer._closeTheRowBehindTheCheckpointsBack()
                return result

        return _Ctx()

    def _closeTheRowBehindTheCheckpointsBack(self) -> None:
        with self._inner.connect() as conn:
            conn.execute(
                f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET "
                "end_timestamp = '2026-08-29T12:00:00Z', "
                "end_vcell_v = 3.41, runtime_seconds = 900 "
                "WHERE end_timestamp IS NULL"
            )


class _CountingDatabase:
    """``DatabaseLike`` passthrough that counts how often connect() is used."""

    def __init__(self, inner: ObdDatabase) -> None:
        self._inner = inner
        self.connects = 0

    def connect(self) -> Any:
        self.connects += 1
        return self._inner.connect()


class _ExplodingDatabase:
    """Every connect() raises -- the writer must still never raise out."""

    def connect(self) -> Any:
        raise RuntimeError('database is locked')


# ================================================================================
# Fixtures / helpers
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / 'test_drain_checkpoint.db'), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def ups() -> FakeUps:
    return FakeUps()


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


def _makeWriter(
    database: Any,
    ups: Any,
    *,
    clock: FakeClock | None = None,
    uptime: float | None = _SETTLED_UPTIME_S,
) -> DrainEventWriter:
    return DrainEventWriter(
        database=database,
        upsResolver=lambda: ups,
        uptimeReader=lambda: uptime,
        monotonicFn=clock,
    )


def _row(database: ObdDatabase, drainEventId: int | None = None) -> dict[str, Any]:
    with database.connect() as conn:
        fetched = conn.execute(
            "SELECT drain_event_id, start_timestamp, end_timestamp, "
            "       start_vcell_v, end_vcell_v, start_soc_pct, end_soc_pct, "
            "       runtime_seconds, load_class, notes "
            f"FROM {BATTERY_HEALTH_LOG_TABLE} "
            + ("WHERE drain_event_id = ? " if drainEventId else "")
            + "ORDER BY drain_event_id DESC",
            (drainEventId,) if drainEventId else (),
        ).fetchone()
    keys = (
        'drain_event_id', 'start_timestamp', 'end_timestamp', 'start_vcell_v',
        'end_vcell_v', 'start_soc_pct', 'end_soc_pct', 'runtime_seconds',
        'load_class', 'notes',
    )
    return dict(zip(keys, fetched, strict=True))


def _verdictOver(database: ObdDatabase) -> Any:
    """Run the REAL verdict over the REAL table, at the real now.

    ``computeBatteryHealthVerdict`` is pure (rows + nowIso), so this is what
    connects the writer's rows to the gate that decides whether a drain votes.
    """
    with database.connect() as conn:
        fetched = conn.execute(
            "SELECT start_timestamp, end_timestamp, runtime_seconds, "
            f"load_class, end_vcell_v FROM {BATTERY_HEALTH_LOG_TABLE}"
        ).fetchall()
    keys = (
        'start_timestamp', 'end_timestamp', 'runtime_seconds', 'load_class',
        'end_vcell_v',
    )
    rows = [dict(zip(keys, row, strict=True)) for row in fetched]
    return computeBatteryHealthVerdict(rows=rows, nowIso=utcIsoNow())


def _backdateStart(database: ObdDatabase, drainEventId: int, seconds: int) -> str:
    """Move a row's start_timestamp N seconds into the past; return the new value.

    runtime_seconds is a WALL-CLOCK delta computed by the shared
    ``_computeRuntimeSeconds`` helper, so a measurable runtime needs a
    measurable start.  This is the only honest way to get one in a unit test
    without freezing the canonical clock helper the whole project stamps with.
    """
    newStart = (
        datetime.utcnow() - timedelta(seconds=seconds)
    ).strftime(CANONICAL_ISO_FORMAT)
    with database.connect() as conn:
        conn.execute(
            f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET start_timestamp = ? "
            "WHERE drain_event_id = ?",
            (newStart, drainEventId),
        )
    return newStart


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
# The interval is Spool's, and it is EXACT
# ================================================================================


class TestTheIntervalIsGrounded:
    """AC-3: 'Implement the 30 s checkpoint at Spool EXACT: 30.'"""

    def test_intervalIsExactlyThirtySeconds(self) -> None:
        """
        Given: Spool's US-504a ruling specifies [EXACT: 30] seconds.
        When:  the module constant is read.
        Then:  it is 30 -- re-tuning it is Spool's call, not this story's.
        """
        assert DRAIN_CHECKPOINT_INTERVAL_SECONDS == 30

    def test_theIntervalIsNotAConfigKey(self) -> None:
        """
        Given: AC-3 says do NOT re-tune the interval.
        When:  the writer is built with no config at all.
        Then:  the cadence still holds -- a config key would be an invitation
               to re-tune a value Spool pinned, and Rule 2 forbids inventing
               tunables the story did not ground.
        """
        writer = DrainEventWriter(
            database=_ExplodingDatabase(), upsResolver=lambda: None,
        )
        assert writer.checkpointIntervalSeconds == 30


# ================================================================================
# The cadence gate
# ================================================================================


class TestCheckpointCadence:
    """Every 30 s while draining -- no sooner, and driven by a MONOTONIC clock."""

    def test_firstCheckpointIsNotDueUntilOneIntervalAfterTheOpen(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a drain opened at t=0.
        When:  the loop ticks at t=29.
        Then:  nothing is written -- the cadence anchors on the OPEN, so the
               first checkpoint lands one full interval into the drain.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        writer.openDrainEvent()

        clock.advance(29.0)
        assert writer.checkpointOpenDrainEvent() is None
        assert _row(freshDb)['runtime_seconds'] is None

    def test_checkpointFiresAtExactlyTheInterval(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a drain opened at t=0.
        When:  the loop ticks at exactly t=30.
        Then:  the checkpoint fires -- the boundary is inclusive, matching the
               >= comparison the drive-end silence close already uses.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()

        clock.advance(DRAIN_CHECKPOINT_INTERVAL_SECONDS)
        assert writer.checkpointOpenDrainEvent() == drainEventId

    def test_aStarvedLoopCheckpointsLate_neverTwiceForOneInterval(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: the orchestrator loop is starved for 5 minutes (US-625 measured
               exactly this shape letting a stale drive claim rows).
        When:  it finally ticks, then ticks again immediately.
        Then:  ONE checkpoint lands, and the next is not due for another 30 s.
               A late checkpoint is degraded, never duplicated or backfilled --
               a backfilled instant would be a value nobody read.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        writer.openDrainEvent()

        clock.advance(300.0)
        assert writer.checkpointOpenDrainEvent() is not None
        assert writer.checkpointOpenDrainEvent() is None

        clock.advance(29.0)
        assert writer.checkpointOpenDrainEvent() is None
        clock.advance(1.0)
        assert writer.checkpointOpenDrainEvent() is not None

    def test_theGateRunsOnTheInjectedMonotonicClock_notTheWallClock(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: US-620 MEASURED this Pi booting at 1970 and stepping hours
               forward the instant NTP lands, and US-625 had to rebuild an
               idle bound on time.monotonic() for exactly that reason.
        When:  real wall time passes but the injected monotonic clock does NOT.
        Then:  no checkpoint fires.  A wall-clock gate would read the NTP step
               as elapsed drain time and fire a burst of checkpoints, or -- on a
               backward step -- stop checkpointing for hours.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        writer.openDrainEvent()

        for _ in range(50):
            assert writer.checkpointOpenDrainEvent() is None

    def test_noOpenRow_isANoOpAndCostsOneQueryPerIntervalAtMost(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: no drain is open (the overwhelmingly common case -- the Pi is on
               wall power).
        When:  the loop ticks thousands of times.
        Then:  nothing is written, nothing raises, the gauge is NEVER read, and
               the ownership SELECT runs at most once per interval.

               Two separate costs, both real.  Reading the gauge with no row to
               write it to would put I2C traffic on the bus for no record at
               all.  And the cadence anchor must advance on every ATTEMPT, not
               only on a successful write -- anchoring on success alone would
               re-run the SELECT on EVERY loop pass for the entire time the Pi
               sits on wall power, which is nearly all of its uptime.
        """
        counting = _CountingDatabase(freshDb)
        writer = _makeWriter(counting, ups, clock=clock)

        for _ in range(1000):
            assert writer.checkpointOpenDrainEvent() is None
            clock.advance(1.0)

        assert ups.vcellReads == 0
        # 1000 s of ticking at a 30 s interval: ~34 attempts, not 1000.
        assert counting.connects <= (1000 // DRAIN_CHECKPOINT_INTERVAL_SECONDS) + 2


# ================================================================================
# What a checkpoint actually writes
# ================================================================================


class TestCheckpointWritesLiveValues:
    """VC-1: the open row carries live end_* values, updated on the interval."""

    def test_checkpointWritesDepthSocAndRuntimeOntoTheStillOpenRow(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a drain open for 45 s with a healthy gauge.
        When:  the checkpoint fires.
        Then:  end_vcell_v / end_soc_pct / runtime_seconds all carry live
               values AND end_timestamp is STILL NULL -- the row must remain
               OPEN, because end_timestamp is what every other reader uses to
               mean "closed" (the finder, the close-once guard, the reaper and
               the verdict all key on it).
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 45)

        clock.advance(30.0)
        assert writer.checkpointOpenDrainEvent() == drainEventId

        row = _row(freshDb)
        assert row['end_timestamp'] is None, 'a checkpoint must NOT close the row'
        assert row['end_vcell_v'] == pytest.approx(3.92)
        assert row['end_soc_pct'] == pytest.approx(84)
        assert row['runtime_seconds'] >= 45

    def test_successiveCheckpointsAdvanceTheRuntimeAndTrackTheFallingPack(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a drain whose pack voltage falls as it drains.
        When:  two checkpoints fire 30 s apart.
        Then:  the row carries the LATER depth and the LONGER runtime -- the
               checkpoint is a running best-known, not a one-shot.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()

        _backdateStart(freshDb, drainEventId, 30)
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        first = _row(freshDb)

        ups.vcell = 3.61
        _backdateStart(freshDb, drainEventId, 60)
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        second = _row(freshDb)

        assert first['end_vcell_v'] == pytest.approx(3.92)
        assert second['end_vcell_v'] == pytest.approx(3.61)
        assert second['runtime_seconds'] > first['runtime_seconds']

    def test_theRuntimeUsesTheSAMEHelperTheCloseUses(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a drain backdated a known 120 s.
        When:  a checkpoint fires and the drain is then closed normally.
        Then:  both runtimes agree to within a second.  ONE predicate for the
               checkpoint and the close, so "how long has this drain run" can
               never be answered two different ways (the US-621 _deltaPredicate
               / US-625 isDriveIdStale discipline).
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 120)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        checkpointed = _row(freshDb)['runtime_seconds']

        result = writer.closeOpenDrainEvent()

        assert checkpointed == pytest.approx(120, abs=2)
        assert result is not None
        assert result.runtimeSeconds == pytest.approx(checkpointed, abs=2)


# ================================================================================
# AC-5 -- a checkpoint must NEVER write a value it has not read
# ================================================================================


class TestNeverWritesAValueItHasNotRead:
    """AC-5, and it is the load-bearing rule of this story."""

    def test_gaugeDyingMidDrain_leavesTheLastGoodDepthStanding(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: a checkpoint recorded a REAL 3.71 V, and the MAX17048 then dies.
        When:  the next checkpoint fires with an unreadable gauge.
        Then:  end_vcell_v is STILL 3.71 and runtime_seconds has ADVANCED.

        This is the whole story in one test.  Writing NULL here would destroy
        precisely the correct measurement US-605 exists to preserve -- the
        checkpoint would become the thing that loses the drain.  Duration is
        still readable (it comes from the clock, not the gauge), so it is
        still written: each column is decided on its OWN reading.
        """
        gauge = FakeUps(vcell=3.71)
        writer = _makeWriter(freshDb, gauge, clock=clock)
        drainEventId = writer.openDrainEvent()

        _backdateStart(freshDb, drainEventId, 40)
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        assert _row(freshDb)['end_vcell_v'] == pytest.approx(3.71)

        gauge.error = OSError('i2c bus error')
        _backdateStart(freshDb, drainEventId, 200)
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        row = _row(freshDb)
        assert row['end_vcell_v'] == pytest.approx(3.71), (
            'a failed read must never NULL a value that WAS read'
        )
        # The SAME rule, asserted on the SAME pass for the OTHER gauge column.
        # It needs its own assertion because "wrote NULL" and "wrote nothing"
        # are indistinguishable on a column that was never populated -- only a
        # PRIOR value can tell them apart (mutation M3).
        assert row['end_soc_pct'] == pytest.approx(84)
        assert row['runtime_seconds'] >= 200

    def test_aRuntimeThatBecomesUNDERIVABLE_keepsTheOneAlreadyMeasured(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a checkpoint has already measured a real runtime, and the row's
               start anchor then becomes unparseable so no runtime can be
               derived on the next pass.
        When:  the next checkpoint fires.
        Then:  the runtime already measured SURVIVES.

        The sibling test above proves an unparseable anchor writes NO runtime
        on a fresh row.  That is not the same claim: a column that was never
        populated reads NULL whether it was skipped or explicitly overwritten
        with NULL, so only a PRIOR value distinguishes the two.  This is the
        assertion mutation M4 needed -- the story's own AC-5 property applied
        to the clock-derived column, not just the gauge-derived ones.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 300)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        measured = _row(freshDb)['runtime_seconds']
        assert measured >= 300, 'premise: a real runtime was measured first'

        with freshDb.connect() as conn:
            conn.execute(
                f"UPDATE {BATTERY_HEALTH_LOG_TABLE} "
                "SET start_timestamp = 'not-a-timestamp' "
                "WHERE drain_event_id = ?",
                (drainEventId,),
            )
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        assert _row(freshDb)['runtime_seconds'] == measured

    def test_upsDisappearingEntirely_stillCheckpointsTheDuration(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: no UpsMonitor at all (the gauge was never wired, or died).
        When:  the checkpoint fires.
        Then:  runtime_seconds is written and both gauge columns stay NULL.
               A duration that WAS measured is not discarded because a depth
               was not; and a depth that was never read is not invented.
        """
        writer = DrainEventWriter(
            database=freshDb,
            upsResolver=lambda: None,
            uptimeReader=lambda: _SETTLED_UPTIME_S,
            monotonicFn=clock,
        )
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 90)

        clock.advance(30.0)
        assert writer.checkpointOpenDrainEvent() == drainEventId

        row = _row(freshDb)
        assert row['runtime_seconds'] >= 90
        assert row['end_vcell_v'] is None
        assert row['end_soc_pct'] is None

    def test_coldStartWindow_suppressesSocPctButKeepsDepthAndRuntime(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: the Pi is inside the MAX17048 cold-start calibration window, so
               the register SoC%% mis-reads by 30-40 points.
        When:  a checkpoint fires.
        Then:  end_soc_pct stays NULL while end_vcell_v is written.  Cell
               VOLTAGE is trustworthy immediately; the SoC register is not.
               An untrusted read is not a read.
        """
        writer = _makeWriter(freshDb, ups, clock=clock, uptime=5.0)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 60)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        row = _row(freshDb)
        assert row['end_soc_pct'] is None
        assert row['end_vcell_v'] == pytest.approx(3.92)

    def test_anUnparseableStartTimestamp_writesNoRuntimeRatherThanAWrongOne(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a row whose start_timestamp is corrupt (pre-US-202 shape, or a
               manual edit) so no runtime can be derived.
        When:  a checkpoint fires.
        Then:  runtime_seconds stays NULL while the gauge columns are still
               written.  The same honest-NA posture endDrainEvent already takes
               on that input -- no fabricated duration.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()
        with freshDb.connect() as conn:
            conn.execute(
                f"UPDATE {BATTERY_HEALTH_LOG_TABLE} "
                "SET start_timestamp = 'not-a-timestamp' "
                "WHERE drain_event_id = ?",
                (drainEventId,),
            )

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        row = _row(freshDb)
        assert row['runtime_seconds'] is None
        assert row['end_vcell_v'] == pytest.approx(3.92)


# ================================================================================
# Custody: whose rows may a checkpoint touch?
# ================================================================================


class TestCheckpointCustody:
    """Only this writer's OWN, still-OPEN row -- never a foreign or closed one."""

    def test_checkpointNeverTouchesAForeignOpenRow(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: one of the four US-442 tombstoned historical orphans, whose NULL
               end_timestamp is DELIBERATE.
        When:  a checkpoint fires with no row of this writer's own open.
        Then:  the orphan is untouched.  Stamping a live runtime onto it would
               mint a months-old row that looks QUALIFYING to the verdict --
               strictly worse than the reaper trap US-526 already fenced.
        """
        orphanId = _insertForeignOrphan(freshDb, notes='US-442 historical orphan')
        writer = _makeWriter(freshDb, ups, clock=clock)

        clock.advance(30.0)
        assert writer.checkpointOpenDrainEvent() is None

        row = _row(freshDb, orphanId)
        assert row['runtime_seconds'] is None
        assert row['end_vcell_v'] is None
        assert row['end_timestamp'] is None

    def test_aCloseRacingTheCheckpoint_cannotOverwriteTheFinalDepth(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: the collector has read the open row's id and is about to write a
               checkpoint, and in that window the eclipse-powerwatch process
               closes the SAME row on the shutdown path with the real cutoff
               depth (3.41 V).  Two processes, one row -- this race is real.
        When:  the checkpoint's UPDATE lands.
        Then:  the closed row is untouched.  The UPDATE re-asserts
               `end_timestamp IS NULL`, so a checkpoint can only ever write to
               a row that is still open AT WRITE TIME.  Without that clause an
               older checkpoint reading would overwrite the FINAL depth Spool's
               gate qualifies on -- this story's own defect, inverted.
        """
        racing = _CloseRacingDatabase(freshDb, raceAfterConnects=1)
        writer = _makeWriter(racing, FakeUps(vcell=3.95), clock=clock)

        with freshDb.connect() as conn:
            conn.execute(
                f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                "(start_timestamp, start_vcell_v, load_class, notes, "
                " data_source) VALUES (?, ?, 'production', ?, 'real')",
                ('2026-08-29T11:45:00Z', 4.05, DRAIN_OPEN_NOTE),
            )

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        assert racing.raced, 'the race fixture never fired -- test is vacuous'
        row = _row(freshDb)
        assert row['end_vcell_v'] == pytest.approx(3.41)
        assert row['runtime_seconds'] == 900

    def test_checkpointNeverRaisesIntoTheCaller(self, clock: FakeClock) -> None:
        """
        Given: an unusable database.
        When:  a checkpoint fires from the orchestrator run loop.
        Then:  it returns None instead of raising.  This runs on the loop that
               also drives OBD capture; battery bookkeeping must never cost a
               drive.
        """
        writer = _makeWriter(_ExplodingDatabase(), FakeUps(), clock=clock)
        clock.advance(30.0)
        assert writer.checkpointOpenDrainEvent() is None


# ================================================================================
# VC-3 -- a normal close is unchanged
# ================================================================================


class TestNormalCloseIsUnregressed:
    """VC-3: 'the closing write still produces the same final values as before'."""

    def test_checkpointedRowClosesWithTheCloseTimeValues_notTheCheckpointed(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: a drain checkpointed at 3.80 V whose pack then falls to 3.44 V.
        When:  power is restored and the drain closes normally.
        Then:  the row carries the CLOSE-time depth.  The close is the final
               word and overwrites every checkpoint -- a checkpoint is a
               fallback for a close that never happens, never a competitor to
               one that does.
        """
        gauge = FakeUps(vcell=3.80)
        writer = _makeWriter(freshDb, gauge, clock=clock)
        writer.openDrainEvent()

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        assert _row(freshDb)['end_vcell_v'] == pytest.approx(3.80)

        gauge.vcell = 3.44
        result = writer.closeOpenDrainEvent()

        row = _row(freshDb)
        assert result is not None and result.closed is True
        assert row['end_vcell_v'] == pytest.approx(3.44)
        assert row['end_timestamp'] is not None
        assert _ISO_UTC.match(row['end_timestamp'])

    def test_aCheckpointedRowIsStillFoundByTheCloseP(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a checkpointed open row.
        When:  the shutdown-path close looks for a row of its own to close.
        Then:  it finds it.  The checkpoint deliberately writes NEITHER
               end_timestamp NOR notes, which are the two columns the
               ownership finder keys on -- so checkpointing can never make a
               drain unclosable.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        row = _row(freshDb)
        assert row['notes'] == DRAIN_OPEN_NOTE
        assert writer.closeOpenDrainEvent() is not None
        assert _row(freshDb, drainEventId)['end_timestamp'] is not None


# ================================================================================
# AC-2 -- the shutdown write goes from HARD to SOFT
# ================================================================================


class TestReaperClosesOntoTheCheckpoint:
    """VC-2: kill the process mid-drain; the last checkpoint survives and is usable."""

    def test_killedMidDrain_theReaperKeepsTheCheckpointedDepthAndRuntime(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: a drain checkpointed at 3.42 V / 1800 s, then a hard cutoff --
               the shutdown write never happens.
        When:  the next boot's reaper runs.
        Then:  the row closes carrying the CHECKPOINTED depth and runtime.
               Before US-605 both were NULL and the whole measurement was lost.
        """
        gauge = FakeUps(vcell=3.42)
        writer = _makeWriter(freshDb, gauge, clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 1800)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        # --- hard cutoff: no close runs at all --- next boot: ---
        assert writer.reapOpenDrainEvents() == [drainEventId]

        row = _row(freshDb, drainEventId)
        assert row['end_timestamp'] is not None
        assert row['end_vcell_v'] == pytest.approx(3.42)
        assert row['runtime_seconds'] >= 1800

    def test_aSingleReapedCheckpointedRowNowQUALIFIESWhereItCouldNotBefore(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: one interrupted-but-checkpointed drain, at a depth under Spool's
               3.50 V gate and past the 60 s runtime floor.
        When:  the qualifying gate is applied.
        Then:  the row VOTES -- qualifyingCount goes 0 -> 1.

        This is AC-2 at the row level.  US-526's reaper left runtime_seconds
        AND end_vcell_v NULL precisely so a reaped row could NOT vote, because
        nothing had measured them.  Now something has, so the honest answer
        changed.  One row is not yet a VERDICT (see the next test) -- the two
        facts are separate and worth separating.
        """
        gauge = FakeUps(vcell=3.44)
        writer = _makeWriter(freshDb, gauge, clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 3600)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        writer.reapOpenDrainEvents()

        assert _verdictOver(freshDb).qualifyingCount == 1

    def test_interruptedDrainsAloneCanNowProduceARealVerdict(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: THREE drains, every one of them killed mid-drain so no shutdown
               write ever landed -- the exact history that produced `unknown`
               through ten boots.
        When:  the battery-health verdict is computed.
        Then:  it is no longer `unknown` and carries a real median runtime.

        This is the end-to-end payoff, and it needs three rows because the
        verdict deliberately refuses to colour itself on fewer than
        MEDIAN_SAMPLE_COUNT samples.  Before US-605 this history yielded
        NOTHING: three correct measurements, all discarded for want of a
        shutdown write.
        """
        writer = _makeWriter(freshDb, FakeUps(vcell=3.46), clock=clock)

        for _ in range(3):
            drainEventId = writer.openDrainEvent()
            _backdateStart(freshDb, drainEventId, 3600)
            clock.advance(30.0)
            assert writer.checkpointOpenDrainEvent() == drainEventId
            assert writer.reapOpenDrainEvents() == [drainEventId]

        verdict = _verdictOver(freshDb)
        assert verdict.qualifyingCount == 3
        assert verdict.verdict != VERDICT_UNKNOWN
        assert verdict.medianRuntimeS is not None and verdict.medianRuntimeS >= 3600

    def test_theReapedEndTimestampIsTheLastCheckpointInstant_notTheReapInstant(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: a drain checkpointed at 600 s of runtime, reaped at the NEXT
               boot -- hours later.
        When:  the reaped row is read.
        Then:  end_timestamp == start_timestamp + runtime_seconds.

        AC-5 says no wrong number may be produced.  Stamping the REAP instant
        beside a 600 s runtime would put two contradictory durations on one
        row -- end_timestamp saying hours, runtime_seconds saying ten minutes.
        The last checkpoint is the last instant anything actually observed the
        Pi alive and draining, so it is the only honest end_timestamp
        available.  An un-checkpointed row has no such instant and keeps the
        reap-time stamp (see the no-regression test below).
        """
        gauge = FakeUps(vcell=3.48)
        writer = _makeWriter(freshDb, gauge, clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 600)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        writer.reapOpenDrainEvents()

        row = _row(freshDb, drainEventId)
        start = datetime.strptime(row['start_timestamp'], CANONICAL_ISO_FORMAT)
        expected = start + timedelta(seconds=int(row['runtime_seconds']))
        assert row['end_timestamp'] == expected.strftime(CANONICAL_ISO_FORMAT)

    def test_theReapedCheckpointedRowIsStillIdentifiableAsInterrupted(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: a checkpointed row closed by the reaper.
        When:  an analyst reads it back.
        Then:  notes SAY it was closed from a checkpoint.

        US-526 made an interrupted drain identifiable by its SIGNATURE --
        end_timestamp present with runtime_seconds and end_vcell_v NULL.  The
        checkpoint destroys that signature: the row now looks exactly like a
        cleanly-closed one.  So the fact has to become a POSITIVE statement
        instead of an inferred absence (the US-626 observer_session_start
        lesson).  It matters because a checkpointed close UNDERSTATES both
        depth and duration by up to one interval, and a reader is entitled to
        know the number is a floor rather than the final value.
        """
        writer = _makeWriter(freshDb, FakeUps(vcell=3.45), clock=clock)
        drainEventId = writer.openDrainEvent()
        _backdateStart(freshDb, drainEventId, 900)

        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()
        writer.reapOpenDrainEvents()

        notes = _row(freshDb, drainEventId)['notes']
        assert DRAIN_OPEN_NOTE in notes, 'provenance must survive'
        assert REAP_CHECKPOINTED_NOTE_SUFFIX in notes

    def test_anUnCheckpointedRowReapsEXACTLYAsBefore(
        self, freshDb: ObdDatabase, ups: FakeUps, clock: FakeClock,
    ) -> None:
        """
        Given: a drain that died before its first checkpoint (under 30 s).
        When:  the boot reaper runs.
        Then:  US-526's honest-NA behaviour is UNCHANGED -- runtime_seconds and
               end_vcell_v stay NULL, notes are untouched, and the row cannot
               vote.  Nothing measured it, so nothing may be claimed about it.
               The reaper's new branch must be reachable ONLY via a checkpoint.
        """
        writer = _makeWriter(freshDb, ups, clock=clock)
        drainEventId = writer.openDrainEvent()

        assert writer.reapOpenDrainEvents() == [drainEventId]

        row = _row(freshDb, drainEventId)
        assert row['end_timestamp'] is not None
        assert row['runtime_seconds'] is None
        assert row['end_vcell_v'] is None
        assert row['notes'] == DRAIN_OPEN_NOTE

        verdict = _verdictOver(freshDb)
        assert verdict.qualifyingCount == 0
        assert verdict.verdict == VERDICT_UNKNOWN

    def test_theReaperStillNeverReadsTheGauge(
        self, freshDb: ObdDatabase, clock: FakeClock,
    ) -> None:
        """
        Given: a checkpointed row awaiting reap at the next boot.
        When:  the reaper runs.
        Then:  the gauge is not read.  Today's resting voltage is not the
               interrupted drain's depth, and a reap-time read at or under
               3.50 V would falsely QUALIFY the row.  The checkpoint supplies
               the depth or nothing does.
        """
        gauge = FakeUps(vcell=3.47)
        writer = _makeWriter(freshDb, gauge, clock=clock)
        writer.openDrainEvent()
        clock.advance(30.0)
        writer.checkpointOpenDrainEvent()

        readsBefore = gauge.vcellReads
        writer.reapOpenDrainEvents()
        assert gauge.vcellReads == readsBefore
