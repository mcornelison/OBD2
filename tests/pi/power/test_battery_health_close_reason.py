################################################################################
# File Name: test_battery_health_close_reason.py
# Purpose/Description: US-683 (F-138) -- battery_health_log carries a TYPED
#                      close_reason so a checkpointed reap's understatement is
#                      discoverable from a column, not from English in `notes`.
#                      Covers the column CHECK, the replay-safe boot step (run
#                      twice against a POPULATED database, asserted on the
#                      statements executed), the conservative backfill, the
#                      pairing invariant on every close path, the verdict's
#                      typed exclusion, and the re-sync of backfilled rows.
# Author: Rex (US-683)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-683) | Initial.
# ================================================================================
################################################################################

"""A checkpointed reap is typed, not described (US-683)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.pi.data.sync_log import SYNC_MODIFIED_AT_COLUMN, ensureSyncModifiedAtSchema
from src.pi.obdii.database import ObdDatabase
from src.pi.power import battery_health_verdict as verdictModule
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    CLOSE_REASON_CLEAN,
    CLOSE_REASON_REAPED_CHECKPOINTED,
    CLOSE_REASON_REAPED_UNCHECKPOINTED,
    CLOSE_REASON_VALUES,
    REAP_CHECKPOINTED_NOTE_SUFFIX,
    SCHEMA_BATTERY_HEALTH_LOG,
    BatteryHealthRecorder,
    ensureBatteryHealthLogCloseReasonColumn,
)
from src.pi.power.battery_health_verdict import (
    QUALIFYING_LOAD_CLASS,
    computeBatteryHealthVerdict,
    readBatteryHealthVerdict,
)
from src.pi.power.drain_event_writer import (
    DRAIN_OPEN_NOTE,
    DrainEventWriter,
)
from src.pi.power.drain_event_writer import (
    REAP_CHECKPOINTED_NOTE_SUFFIX as WRITER_SUFFIX,
)

#: The four US-442 historical orphans. end_timestamp IS NULL on purpose.
ORPHAN_IDS = (1, 9, 18, 21)

#: battery_health_log exactly as it stands on the car before US-683: the
#: post-US-426 column set. Created under a temp name and RENAMED, because the
#: car's table was rebuilt by US-426 and so carries a QUOTED name in its stored
#: DDL (specs/design-patterns.md section 10).
PRE_US683_DDL = """
CREATE TABLE battery_health_log__seed (
    drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_timestamp TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    end_timestamp TEXT,
    start_vcell_v REAL,
    end_vcell_v REAL,
    start_soc_pct REAL,
    end_soc_pct REAL,
    runtime_seconds INTEGER,
    ambient_temp_c REAL,
    load_class TEXT NOT NULL DEFAULT 'production'
        CHECK (load_class IN ('production','test','sim')),
    notes TEXT,
    data_source TEXT NOT NULL DEFAULT 'real'
        CHECK (data_source IN ('real','replay','physics_sim','fixture','foreign'))
);
ALTER TABLE battery_health_log__seed RENAME TO battery_health_log;
"""

_OPEN_OWN_ID = 30
_CLEAN_IDS = (2, 3)
_CLEAN_GAUGE_DEAD_ID = 4
_REAPED_UNCHECKPOINTED_ID = 5
_REAPED_CHECKPOINTED_ID = 6

#: (drain_event_id, end_timestamp, end_vcell_v, runtime_seconds, notes)
_SEED_ROWS: tuple[tuple[int, str | None, float | None, int | None, str | None], ...] = (
    (1, None, None, None, 'US-442 tombstone: orphan, no timing truth'),
    (_CLEAN_IDS[0], '2026-05-09T12:12:07Z', 3.41, 727, 'drill'),
    (_CLEAN_IDS[1], '2026-05-10T12:10:17Z', 3.45, 617, None),
    (_CLEAN_GAUGE_DEAD_ID, '2026-08-05T12:01:40Z', None, 100, DRAIN_OPEN_NOTE),
    (_REAPED_UNCHECKPOINTED_ID, '2026-08-06T12:00:00Z', None, None, DRAIN_OPEN_NOTE),
    (
        _REAPED_CHECKPOINTED_ID, '2026-09-01T12:10:00Z', 3.48, 600,
        DRAIN_OPEN_NOTE + REAP_CHECKPOINTED_NOTE_SUFFIX,
    ),
    (9, None, None, None, 'US-442 tombstone: orphan, no timing truth'),
    (18, None, None, None, 'US-442 tombstone: orphan, no timing truth'),
    (21, None, None, None, None),
    (_OPEN_OWN_ID, None, 3.90, 60, DRAIN_OPEN_NOTE),
)

_EXPECTED_BACKFILL: dict[int, str | None] = {
    1: None, 9: None, 18: None, 21: None, _OPEN_OWN_ID: None,
    _CLEAN_IDS[0]: CLOSE_REASON_CLEAN,
    _CLEAN_IDS[1]: CLOSE_REASON_CLEAN,
    _CLEAN_GAUGE_DEAD_ID: CLOSE_REASON_CLEAN,
    _REAPED_UNCHECKPOINTED_ID: CLOSE_REASON_REAPED_UNCHECKPOINTED,
    _REAPED_CHECKPOINTED_ID: CLOSE_REASON_REAPED_CHECKPOINTED,
}


# ================================================================================
# Helpers
# ================================================================================


def _seedPreUs683(conn: sqlite3.Connection) -> None:
    conn.executescript(PRE_US683_DDL)
    conn.executemany(
        "INSERT INTO battery_health_log (drain_event_id, start_timestamp, "
        "end_timestamp, start_vcell_v, end_vcell_v, runtime_seconds, notes) "
        "VALUES (?, '2026-05-09T12:00:00Z', ?, 4.10, ?, ?, ?)",
        _SEED_ROWS,
    )
    conn.commit()


def _snapshot(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT * FROM battery_health_log ORDER BY drain_event_id"
    ).fetchall()


def _closeReasons(conn: sqlite3.Connection) -> dict[int, str | None]:
    return dict(conn.execute(
        "SELECT drain_event_id, close_reason FROM battery_health_log"
    ).fetchall())


def _traced(conn: sqlite3.Connection, fn: Any) -> list[str]:
    executed: list[str] = []
    conn.set_trace_callback(executed.append)
    try:
        fn()
    finally:
        conn.set_trace_callback(None)
    return executed


def _writes(executed: list[str]) -> list[str]:
    """Every statement that could change schema or rows, by its leading verb."""
    return [
        sql for sql in executed
        if re.match(r"\s*(ALTER|UPDATE|INSERT|DELETE|DROP|CREATE)\b", sql, re.IGNORECASE)
    ]


def _assertPairing(conn: sqlite3.Connection) -> None:
    """A row has end_timestamp exactly when it has close_reason."""
    unpaired = conn.execute(
        "SELECT drain_event_id, end_timestamp, close_reason "
        "FROM battery_health_log "
        "WHERE (end_timestamp IS NULL) != (close_reason IS NULL)"
    ).fetchall()
    assert unpaired == [], f"pairing invariant broken: {unpaired}"


class FakeUps:
    """UpsMonitor-shaped double."""

    def __init__(self, vcell: float = 3.47, socPct: int = 12) -> None:
        self.vcell = vcell
        self.socPct = socPct

    def getVcell(self) -> float:
        return self.vcell

    def getBatteryPercentage(self) -> int:
        return self.socPct


def _writer(db: Any, *, clock: list[float] | None = None) -> DrainEventWriter:
    ticks = clock if clock is not None else [0.0]
    return DrainEventWriter(
        database=db,
        upsResolver=lambda: FakeUps(),
        uptimeReader=lambda: 9999.0,
        monotonicFn=lambda: ticks[0],
        checkpointIntervalSeconds=30.0,
    )


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / 'close_reason.db'), walMode=False)
    db.initialize()
    return db


# ================================================================================
# Acceptance 1: typed column, column-level CHECK, no rebuild
# ================================================================================


class TestTheColumn:
    def test_vocabularyIsExactlyTheThreeStates_noOpenValue(self) -> None:
        """end_timestamp IS NULL stays the open marker -- no 'open' enum value."""
        assert CLOSE_REASON_VALUES == (
            'clean', 'reaped_uncheckpointed', 'reaped_checkpointed',
        )

    def test_freshTable_carriesCloseReason(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        columns = [row[1] for row in conn.execute('PRAGMA table_info(battery_health_log)')]
        assert 'close_reason' in columns

    @pytest.mark.parametrize('makeTable', ['fresh', 'upgraded'])
    def test_checkRejectsAValueOutsideTheVocabulary(self, makeTable: str) -> None:
        conn = sqlite3.connect(':memory:')
        if makeTable == 'fresh':
            conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
        else:
            _seedPreUs683(conn)
            ensureBatteryHealthLogCloseReasonColumn(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO battery_health_log (end_timestamp, close_reason) "
                "VALUES ('2026-09-24T00:00:00Z', 'interrupted')"
            )
        for value in CLOSE_REASON_VALUES:
            conn.execute(
                "INSERT INTO battery_health_log (end_timestamp, close_reason) "
                "VALUES ('2026-09-24T00:00:00Z', ?)", (value,),
            )
        conn.execute("INSERT INTO battery_health_log (close_reason) VALUES (NULL)")


# ================================================================================
# Acceptance 4 + 5: backfill, replay-safe step (section 10)
# ================================================================================


class TestSchemaStepOnAPopulatedDatabase:
    def test_firstRun_addsTheColumnWithoutARebuild_andBackfills(self) -> None:
        """
        Given: the car's populated pre-US-683 table (quoted, previously rebuilt)
        When:  the step runs once
        Then:  exactly one ADD COLUMN and one UPDATE -- no CREATE, DROP or RENAME
        """
        conn = sqlite3.connect(':memory:')
        _seedPreUs683(conn)

        executed = _traced(conn, lambda: ensureBatteryHealthLogCloseReasonColumn(conn))

        writes = _writes(executed)
        assert len(writes) == 2, writes
        assert re.search(r'ADD\s+COLUMN\s+close_reason', writes[0], re.IGNORECASE)
        assert writes[1].lstrip().upper().startswith('UPDATE')
        assert not any(re.search(r'\b(CREATE|DROP|RENAME)\b', s, re.I) for s in writes)

    def test_backfill_classifiesEveryRowConservatively(self) -> None:
        """Every closed row gets exactly one value; every open row stays NULL."""
        conn = sqlite3.connect(':memory:')
        _seedPreUs683(conn)

        ensureBatteryHealthLogCloseReasonColumn(conn)

        assert _closeReasons(conn) == _EXPECTED_BACKFILL
        grouped = dict(conn.execute(
            "SELECT close_reason, COUNT(*) FROM battery_health_log GROUP BY close_reason"
        ).fetchall())
        assert grouped == {
            None: 5,
            CLOSE_REASON_CLEAN: 3,
            CLOSE_REASON_REAPED_UNCHECKPOINTED: 1,
            CLOSE_REASON_REAPED_CHECKPOINTED: 1,
        }
        _assertPairing(conn)

    def test_theFourHistoricalOrphans_areUntouched(self) -> None:
        conn = sqlite3.connect(':memory:')
        _seedPreUs683(conn)
        before = {row[0]: row for row in _snapshot(conn) if row[0] in ORPHAN_IDS}

        ensureBatteryHealthLogCloseReasonColumn(conn)

        after = {row[0]: row for row in _snapshot(conn) if row[0] in ORPHAN_IDS}
        assert set(after) == set(ORPHAN_IDS)
        for drainEventId in ORPHAN_IDS:
            # Every pre-existing value identical; the one new column NULL.
            assert after[drainEventId][:-1] == before[drainEventId]
            assert after[drainEventId][-1] is None

    def test_backfill_changesNothingButCloseReason(self) -> None:
        conn = sqlite3.connect(':memory:')
        _seedPreUs683(conn)
        before = _snapshot(conn)

        ensureBatteryHealthLogCloseReasonColumn(conn)

        after = _snapshot(conn)
        assert [row[:-1] for row in after] == before

    def test_secondRun_issuesNoWriteAtAll_andEveryValueIsUnchanged(self) -> None:
        """
        Given: a populated table the step has already upgraded
        When:  the step runs a second time (second boot)
        Then:  no ADD COLUMN, no UPDATE; row count and every value unchanged
        """
        conn = sqlite3.connect(':memory:')
        _seedPreUs683(conn)
        assert ensureBatteryHealthLogCloseReasonColumn(conn) is True
        afterFirst = _snapshot(conn)

        executed = _traced(conn, lambda: ensureBatteryHealthLogCloseReasonColumn(conn))

        assert _writes(executed) == []
        assert _snapshot(conn) == afterFirst
        assert ensureBatteryHealthLogCloseReasonColumn(conn) is False

    def test_freshTable_isANoOp(self) -> None:
        conn = sqlite3.connect(':memory:')
        conn.execute(SCHEMA_BATTERY_HEALTH_LOG)

        executed = _traced(conn, lambda: ensureBatteryHealthLogCloseReasonColumn(conn))

        assert _writes(executed) == []

    def test_aMissingTable_failsLoud_ratherThanReportingNothingToDo(self) -> None:
        conn = sqlite3.connect(':memory:')
        with pytest.raises(sqlite3.OperationalError, match='no such table'):
            ensureBatteryHealthLogCloseReasonColumn(conn)

    def test_backfilledRows_areStampedForReSync(self) -> None:
        """
        The server's notes never carry the reap suffix (sync.py preserves notes
        on update), so the Pi's typed value must reach it by re-sync. The
        backfill UPDATE fires the US-315 modified_at trigger.
        """
        conn = sqlite3.connect(':memory:')
        _seedPreUs683(conn)
        ensureSyncModifiedAtSchema(conn)

        ensureBatteryHealthLogCloseReasonColumn(conn)

        stamped = dict(conn.execute(
            f"SELECT drain_event_id, {SYNC_MODIFIED_AT_COLUMN} IS NOT NULL "
            "FROM battery_health_log"
        ).fetchall())
        for drainEventId, expected in _EXPECTED_BACKFILL.items():
            assert bool(stamped[drainEventId]) is (expected is not None), drainEventId


class TestTheBootPathRunsTheStep:
    """The step is CALLED at boot -- the V0.29.66 shape was a step nothing ran."""

    def _tracedInitialize(
        self, db: ObdDatabase, monkeypatch: pytest.MonkeyPatch,
    ) -> list[str]:
        executed: list[str] = []
        original = db._getConnection  # noqa: SLF001 -- wrap the real connection

        def traced() -> sqlite3.Connection:
            conn = original()
            conn.set_trace_callback(executed.append)
            return conn

        monkeypatch.setattr(db, '_getConnection', traced)
        db.initialize()
        monkeypatch.undo()
        return executed

    def test_initializeTwice_onAPopulatedPreUs683Database(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = str(tmp_path / 'obd.db')
        seed = sqlite3.connect(path)
        _seedPreUs683(seed)
        seed.close()
        db = ObdDatabase(path, walMode=False)

        first = self._tracedInitialize(db, monkeypatch)
        added = [s for s in first if re.search(r'ADD\s+COLUMN\s+close_reason', s, re.I)]
        assert len(added) == 1, added

        check = sqlite3.connect(path)
        try:
            afterFirst = _snapshot(check)
        finally:
            check.close()

        second = self._tracedInitialize(db, monkeypatch)
        # Match the statement's leading verb: the no-op CREATE ... IF NOT EXISTS
        # DDL carries comments that mention "drop".
        touched = [
            s for s in second
            if BATTERY_HEALTH_LOG_TABLE in s
            and (
                re.match(r'\s*(ALTER|UPDATE|DROP|INSERT|DELETE)\b', s, re.IGNORECASE)
                or re.search(r'RENAME\s+TO', s, re.IGNORECASE)
            )
        ]
        assert touched == [], f'second boot changed battery_health_log: {touched}'

        check = sqlite3.connect(path)
        try:
            assert _snapshot(check) == afterFirst
            assert len(afterFirst) == len(_SEED_ROWS)
            assert _closeReasons(check) == _EXPECTED_BACKFILL
        finally:
            check.close()


# ================================================================================
# Acceptance 2: the pairing invariant, enforced in CODE, on every close path
# ================================================================================


class TestEveryClosePathWritesItsReason:
    def test_recorderClose_isClean_andAReCloseKeepsIt(self, freshDb: ObdDatabase) -> None:
        recorder = BatteryHealthRecorder(database=freshDb)
        drainEventId = recorder.startDrainEvent(startSoc=4.1)
        with freshDb.connect() as conn:
            _assertPairing(conn)
            assert _closeReasons(conn)[drainEventId] is None

        recorder.endDrainEvent(drainEventId=drainEventId, endSoc=3.45)
        recorder.endDrainEvent(drainEventId=drainEventId, endSoc=3.99)

        with freshDb.connect() as conn:
            assert _closeReasons(conn)[drainEventId] == CLOSE_REASON_CLEAN
            _assertPairing(conn)

    def test_writerClose_isClean(self, freshDb: ObdDatabase) -> None:
        writer = _writer(freshDb)
        drainEventId = writer.openDrainEvent()
        assert drainEventId is not None

        writer.closeOpenDrainEvent()

        with freshDb.connect() as conn:
            assert _closeReasons(conn)[drainEventId] == CLOSE_REASON_CLEAN
            _assertPairing(conn)

    def test_checkpointLeavesTheRowOpen_withNoReason(self, freshDb: ObdDatabase) -> None:
        clock = [0.0]
        writer = _writer(freshDb, clock=clock)
        drainEventId = writer.openDrainEvent()
        clock[0] = 31.0

        assert writer.checkpointOpenDrainEvent() == drainEventId

        with freshDb.connect() as conn:
            assert _closeReasons(conn)[drainEventId] is None
            _assertPairing(conn)

    def test_reapBeforeAnyCheckpoint_isReapedUncheckpointed(
        self, freshDb: ObdDatabase,
    ) -> None:
        drainEventId = _writer(freshDb).openDrainEvent()

        assert _writer(freshDb).reapOpenDrainEvents() == [drainEventId]

        with freshDb.connect() as conn:
            row = conn.execute(
                "SELECT close_reason, runtime_seconds, end_vcell_v, notes "
                "FROM battery_health_log WHERE drain_event_id = ?", (drainEventId,),
            ).fetchone()
            _assertPairing(conn)
        assert tuple(row) == (
            CLOSE_REASON_REAPED_UNCHECKPOINTED, None, None, DRAIN_OPEN_NOTE,
        )

    def test_reapAfterACheckpoint_isReapedCheckpointed_andKeepsTheProse(
        self, freshDb: ObdDatabase,
    ) -> None:
        clock = [0.0]
        writer = _writer(freshDb, clock=clock)
        drainEventId = writer.openDrainEvent()
        clock[0] = 31.0
        writer.checkpointOpenDrainEvent()

        assert _writer(freshDb).reapOpenDrainEvents() == [drainEventId]

        with freshDb.connect() as conn:
            closeReason, notes = conn.execute(
                "SELECT close_reason, notes FROM battery_health_log "
                "WHERE drain_event_id = ?", (drainEventId,),
            ).fetchone()
            _assertPairing(conn)
        assert closeReason == CLOSE_REASON_REAPED_CHECKPOINTED
        # The prose stays as human context; it just stops being load-bearing.
        assert notes == DRAIN_OPEN_NOTE + REAP_CHECKPOINTED_NOTE_SUFFIX

    def test_theWriterStillExportsTheSameSuffix(self) -> None:
        assert WRITER_SUFFIX is REAP_CHECKPOINTED_NOTE_SUFFIX


# ================================================================================
# Acceptance 3: the verdict keys on the typed column, never on English
# ================================================================================


def _qualifyingRow(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        'start_timestamp': '2026-09-01T12:00:00Z',
        'end_timestamp': '2026-09-01T12:12:00Z',
        'runtime_seconds': 720,
        'load_class': QUALIFYING_LOAD_CLASS,
        'end_vcell_v': 3.45,
    }
    row.update(overrides)
    return row


class TestTheVerdictKeysOnCloseReason:
    def test_qualifyingQuery_readsNoProse(self) -> None:
        sql = verdictModule._QUALIFYING_ROW_SQL  # noqa: SLF001 -- the query itself
        assert 'close_reason' in sql
        assert 'notes' not in sql
        assert 'LIKE' not in sql.upper()

    def test_anUncheckpointedReap_isExcludedByType(self) -> None:
        """Even a row whose values would pass the depth gate cannot vote."""
        rows = [_qualifyingRow(close_reason=CLOSE_REASON_REAPED_UNCHECKPOINTED)]
        result = computeBatteryHealthVerdict(rows=rows, nowIso='2026-09-24T00:00:00Z')
        assert result.qualifyingCount == 0

    @pytest.mark.parametrize(
        'closeReason', [CLOSE_REASON_CLEAN, CLOSE_REASON_REAPED_CHECKPOINTED, None],
    )
    def test_otherRowsStillVoteAsBefore(self, closeReason: str | None) -> None:
        """Excluding checkpointed reaps is Atlas's call, not this story's."""
        rows = [_qualifyingRow(close_reason=closeReason)]
        result = computeBatteryHealthVerdict(rows=rows, nowIso='2026-09-24T00:00:00Z')
        assert result.qualifyingCount == 1

    def test_sqlGate_excludesAnUncheckpointedReapWithValues(
        self, freshDb: ObdDatabase,
    ) -> None:
        with freshDb.connect() as conn:
            for closeReason in CLOSE_REASON_VALUES:
                conn.execute(
                    "INSERT INTO battery_health_log (start_timestamp, end_timestamp, "
                    "end_vcell_v, runtime_seconds, load_class, close_reason) "
                    "VALUES ('2026-09-01T12:00:00Z', '2026-09-01T12:12:00Z', 3.45, "
                    "720, 'production', ?)", (closeReason,),
                )

        result = readBatteryHealthVerdict(database=freshDb, nowIso='2026-09-24T00:00:00Z')

        assert result.qualifyingCount == 2
