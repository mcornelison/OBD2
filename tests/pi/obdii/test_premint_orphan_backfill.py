################################################################################
# File Name: test_premint_orphan_backfill.py
# Purpose/Description: TDD tests for scripts/backfill_premint_orphans.py
#                      (US-233). Synthesizes realtime_data with pre-mint
#                      orphan rows + subsequent drives + pre-US-212
#                      pollution and asserts the matching algorithm + the
#                      idempotent UPDATE behavior. Uses temp SQLite DBs;
#                      no SSH, no real Pi.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-233) | Initial -- TDD coverage for the pre-mint
#                               orphan backfill script.
# ================================================================================
################################################################################

"""TDD tests for the US-233 pre-mint orphan backfill script."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'backfill_premint_orphans.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'backfill_premint_orphans', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['backfill_premint_orphans'] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _loadScript()


# ================================================================================
# SQLite synthesis helpers
# ================================================================================

# Minimal realtime_data shape -- only the columns the backfill script touches.
# Full prod schema is much wider; this minimal subset keeps tests focused.
_REALTIME_DATA_DDL = """
CREATE TABLE realtime_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    value REAL,
    drive_id INTEGER,
    data_source TEXT NOT NULL DEFAULT 'real'
)
"""

# drive_summary -- the script must NOT touch this table per invariant #3.
_DRIVE_SUMMARY_DDL = """
CREATE TABLE drive_summary (
    drive_id INTEGER PRIMARY KEY,
    drive_start_timestamp TEXT,
    ambient_temp_at_start_c REAL,
    starting_battery_v REAL,
    barometric_kpa_at_start REAL,
    data_source TEXT DEFAULT 'real'
)
"""


@pytest.fixture
def freshDb(tmp_path) -> sqlite3.Connection:  # noqa: ANN001 -- pytest fixture
    """Empty SQLite DB with realtime_data + drive_summary schema."""
    dbPath = tmp_path / 'obd.db'
    conn = sqlite3.connect(str(dbPath))
    conn.execute(_REALTIME_DATA_DDL)
    conn.execute(_DRIVE_SUMMARY_DDL)
    conn.commit()
    return conn


def _insertRow(
    conn: sqlite3.Connection,
    *,
    timestamp: str,
    parameterName: str = 'RPM',
    value: float = 0.0,
    driveId: int | None = None,
    dataSource: str = 'real',
) -> int:
    cursor = conn.execute(
        "INSERT INTO realtime_data "
        "(timestamp, parameter_name, value, drive_id, data_source) "
        "VALUES (?, ?, ?, ?, ?)",
        (timestamp, parameterName, value, driveId, dataSource),
    )
    rowId = cursor.lastrowid
    assert rowId is not None
    return int(rowId)


def _insertDrive(
    conn: sqlite3.Connection,
    *,
    driveId: int,
    startTime: datetime,
    durationSeconds: int = 60,
    rowsPerSecond: int = 3,
    dataSource: str = 'real',
) -> list[int]:
    """Insert N rows tagged drive_id with timestamps spanning the duration."""
    rowIds: list[int] = []
    totalRows = durationSeconds * rowsPerSecond
    for i in range(totalRows):
        ts = startTime + timedelta(seconds=i / rowsPerSecond)
        rowIds.append(
            _insertRow(
                conn,
                timestamp=_iso(ts),
                driveId=driveId,
                dataSource=dataSource,
            ),
        )
    conn.commit()
    return rowIds


def _insertOrphans(
    conn: sqlite3.Connection,
    *,
    startTime: datetime,
    count: int,
    intervalSeconds: float = 0.2,
    dataSource: str = 'real',
) -> list[int]:
    """Insert N rows with NULL drive_id, evenly spaced from startTime."""
    rowIds: list[int] = []
    for i in range(count):
        ts = startTime + timedelta(seconds=i * intervalSeconds)
        rowIds.append(
            _insertRow(
                conn,
                timestamp=_iso(ts),
                driveId=None,
                dataSource=dataSource,
            ),
        )
    conn.commit()
    return rowIds


def _iso(ts: datetime) -> str:
    """Canonical ISO-8601 UTC string used in realtime_data.timestamp."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _countNullDriveIdRealRows(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "SELECT COUNT(*) FROM realtime_data "
        "WHERE drive_id IS NULL AND data_source='real'",
    )
    return int(cursor.fetchone()[0])


def _countDriveRows(conn: sqlite3.Connection, driveId: int) -> int:
    cursor = conn.execute(
        "SELECT COUNT(*) FROM realtime_data WHERE drive_id=?",
        (driveId,),
    )
    return int(cursor.fetchone()[0])


# ================================================================================
# scanOrphans -- pure read; finds NULL drive_id real rows
# ================================================================================

class TestScanOrphans:
    def test_emptyDb_returnsEmptyList(self, freshDb: sqlite3.Connection) -> None:
        orphans = bf.scanOrphans(freshDb)
        assert orphans == []

    def test_returnsOnlyNullDriveIdRealRows(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        t0 = datetime(2026, 4, 23, 16, 36, 10, tzinfo=UTC)
        orphanIds = _insertOrphans(freshDb, startTime=t0, count=5)
        # Tagged rows -- must NOT come back as orphans
        _insertDrive(
            freshDb, driveId=3,
            startTime=t0 + timedelta(seconds=40), durationSeconds=10,
        )
        # Sim NULL row -- not 'real', not an orphan
        _insertRow(
            freshDb, timestamp=_iso(t0 + timedelta(seconds=100)),
            dataSource='sim',
        )
        orphans = bf.scanOrphans(freshDb)
        returnedIds = sorted(o.rowId for o in orphans)
        assert returnedIds == sorted(orphanIds)

    def test_excludesSimDataSource(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        t0 = datetime(2026, 4, 23, 16, 0, 0, tzinfo=UTC)
        _insertRow(freshDb, timestamp=_iso(t0), dataSource='sim')
        _insertRow(freshDb, timestamp=_iso(t0), dataSource='test')
        freshDb.commit()
        orphans = bf.scanOrphans(freshDb)
        assert orphans == []

    def test_returnsRowsSortedByTimestampAscending(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        # Insert out-of-order: t=2, t=0, t=1
        t0 = datetime(2026, 4, 23, 16, 0, 0, tzinfo=UTC)
        _insertRow(freshDb, timestamp=_iso(t0 + timedelta(seconds=2)))
        _insertRow(freshDb, timestamp=_iso(t0))
        _insertRow(freshDb, timestamp=_iso(t0 + timedelta(seconds=1)))
        freshDb.commit()
        orphans = bf.scanOrphans(freshDb)
        timestamps = [o.timestamp for o in orphans]
        assert timestamps == sorted(timestamps)


# ================================================================================
# scanDriveStarts -- pure read; minimum timestamp per drive_id
# ================================================================================

class TestScanDriveStarts:
    def test_emptyDb_returnsEmptyList(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        assert bf.scanDriveStarts(freshDb) == []

    def test_returnsMinTimestampPerDriveId(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        t0 = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertDrive(freshDb, driveId=3, startTime=t0, durationSeconds=10)
        t1 = datetime(2026, 4, 23, 17, 0, 0, tzinfo=UTC)
        _insertDrive(freshDb, driveId=4, startTime=t1, durationSeconds=10)
        starts = bf.scanDriveStarts(freshDb)
        startsByDrive = {ds.driveId: ds.driveStartTimestamp for ds in starts}
        assert startsByDrive == {3: _iso(t0), 4: _iso(t1)}

    def test_excludesSimDataSourceWhenScanning(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        # A drive_id present only in sim rows should NOT show up as a real
        # drive start (we only backfill real orphans against real drives).
        t0 = datetime(2026, 4, 23, 16, 0, 0, tzinfo=UTC)
        _insertDrive(
            freshDb, driveId=99, startTime=t0,
            durationSeconds=5, dataSource='sim',
        )
        starts = bf.scanDriveStarts(freshDb)
        assert starts == []


# ================================================================================
# findOrphanBackfillMatches -- the matching algorithm
# ================================================================================

class TestFindOrphanBackfillMatches:
    def test_emptyDb_returnsEmpty(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        assert bf.findOrphanBackfillMatches(freshDb) == []

    def test_orphanWithinWindow_matchedToNearestSubsequentDrive(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        driveStart = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        # Orphan 30s before drive start
        orphanIds = _insertOrphans(
            freshDb,
            startTime=driveStart - timedelta(seconds=30),
            count=1,
        )
        _insertDrive(
            freshDb, driveId=3,
            startTime=driveStart, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        assert len(matches) == 1
        assert matches[0].rowId == orphanIds[0]
        assert matches[0].toDriveId == 3

    def test_orphanOutsideWindow_notMatched(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        driveStart = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        # Orphan 120s before drive start; window=60 should reject
        _insertOrphans(
            freshDb,
            startTime=driveStart - timedelta(seconds=120),
            count=1,
        )
        _insertDrive(
            freshDb, driveId=3,
            startTime=driveStart, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        assert matches == []

    def test_orphanAtOrAfterDriveStart_notMatched(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        driveStart = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        # Orphan AT drive_start AND 5s after -- both must be rejected
        # (a row at or after drive_start is not a "pre-mint orphan")
        _insertOrphans(freshDb, startTime=driveStart, count=2)
        _insertDrive(
            freshDb, driveId=3,
            startTime=driveStart, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        assert matches == []

    def test_orphansBetweenTwoDrives_attachToNearestSubsequent(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 0, 0, tzinfo=UTC)
        d4Start = d3Start + timedelta(seconds=300)
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=120,
        )
        _insertDrive(
            freshDb, driveId=4, startTime=d4Start, durationSeconds=60,
        )
        # Orphan 30s before d4Start -- should match drive 4 (the next one),
        # NOT drive 3 (which started 4.5 min earlier).
        orphanIds = _insertOrphans(
            freshDb, startTime=d4Start - timedelta(seconds=30), count=1,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        assert len(matches) == 1
        assert matches[0].rowId == orphanIds[0]
        assert matches[0].toDriveId == 4

    def test_drive3Scenario_225rowsIn39SecWindowAllMatched(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        # The actual real-world Drive 3 case from the SSH probe:
        # 225 NULL-drive_id rows in 2026-04-23T16:36:10..49Z, then
        # Drive 3 starts at 16:36:50Z. With windowSeconds >= 39, ALL
        # 225 should match Drive 3.
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        windowStart = d3Start - timedelta(seconds=40)
        # 225 rows over 39 seconds -- approx every 0.173s
        intervalS = 39.0 / 225.0
        orphanIds = _insertOrphans(
            freshDb, startTime=windowStart, count=225,
            intervalSeconds=intervalS,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=600,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        assert len(matches) == 225
        assert {m.rowId for m in matches} == set(orphanIds)
        assert {m.toDriveId for m in matches} == {3}

    def test_preUs212PollutionScenario_unmatched(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        # The 2026-04-21 188-row case: NULL-drive_id rows on a day with
        # no subsequent drive within the cap. Must remain unmatched.
        pollutionStart = datetime(2026, 4, 21, 2, 27, 10, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=pollutionStart, count=188,
            intervalSeconds=600.0,  # spread across hours
        )
        # The next "drive" starts 2 days later -- way outside any cap
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=60,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        assert matches == []

    def test_customWindow30s_excludes45sGap(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=45), count=1,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=30.0)
        assert matches == []

    def test_customWindow30s_includes20sGap(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=20), count=1,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=30.0)
        assert len(matches) == 1
        assert matches[0].toDriveId == 3

    def test_invalidWindowSeconds_raisesValueError(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        with pytest.raises(ValueError, match='windowSeconds'):
            bf.findOrphanBackfillMatches(freshDb, windowSeconds=0)
        with pytest.raises(ValueError, match='windowSeconds'):
            bf.findOrphanBackfillMatches(freshDb, windowSeconds=-5)


# ================================================================================
# applyBackfill -- transactional UPDATE; idempotent
# ================================================================================

class TestApplyBackfill:
    def test_emptyMatchesIsNoOp_returnsZero(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        assert bf.applyBackfill(freshDb, []) == 0

    def test_updatesMatchedRowsToDriveId(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        orphanIds = _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=30), count=3,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        updated = bf.applyBackfill(freshDb, matches)
        assert updated == 3
        # Verify each orphan now carries drive_id=3
        for rowId in orphanIds:
            row = freshDb.execute(
                "SELECT drive_id FROM realtime_data WHERE id=?", (rowId,),
            ).fetchone()
            assert row[0] == 3

    def test_idempotentSecondRunReturnsZero(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=30), count=3,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        firstMatches = bf.findOrphanBackfillMatches(freshDb)
        bf.applyBackfill(freshDb, firstMatches)
        # Re-scan after the UPDATE -- should find no orphans
        secondMatches = bf.findOrphanBackfillMatches(freshDb)
        assert secondMatches == []
        assert bf.applyBackfill(freshDb, secondMatches) == 0

    def test_doesNotTouchTaggedRows(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        # Safety invariant: the WHERE-clause guard on applyBackfill must
        # refuse to update a row whose drive_id is already non-NULL,
        # even if a stale BackfillMatch named that row id. We craft a
        # synthetic match pointing at an already-tagged row and verify
        # the UPDATE leaves it alone.
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        existingId = _insertRow(
            freshDb,
            timestamp=_iso(d3Start - timedelta(seconds=20)),
            driveId=99,
        )
        freshDb.commit()
        staleMatch = bf.BackfillMatch(
            rowId=existingId,
            toDriveId=3,
            rowTimestamp=_iso(d3Start - timedelta(seconds=20)),
            driveStartTimestamp=_iso(d3Start),
            gapSeconds=20.0,
        )
        # applyBackfill is told to update id=existingId -> 3, but the
        # WHERE-clause guard refuses (drive_id IS NOT NULL).
        updated = bf.applyBackfill(freshDb, [staleMatch])
        assert updated == 0
        assert freshDb.execute(
            "SELECT drive_id FROM realtime_data WHERE id=?", (existingId,),
        ).fetchone()[0] == 99

    def test_doesNotTouchSimDataSourceOrphans(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        simOrphanId = _insertRow(
            freshDb,
            timestamp=_iso(d3Start - timedelta(seconds=20)),
            driveId=None,
            dataSource='sim',
        )
        freshDb.commit()
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        matches = bf.findOrphanBackfillMatches(freshDb, windowSeconds=60.0)
        bf.applyBackfill(freshDb, matches)
        assert freshDb.execute(
            "SELECT drive_id FROM realtime_data WHERE id=?", (simOrphanId,),
        ).fetchone()[0] is None

    def test_doesNotModifyDriveSummary(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        # Pretend US-228 wrote a populated drive_summary row for drive 3
        freshDb.execute(
            "INSERT INTO drive_summary "
            "(drive_id, drive_start_timestamp, ambient_temp_at_start_c, "
            "starting_battery_v, barometric_kpa_at_start) "
            "VALUES (3, ?, 19.0, 13.4, 100.5)",
            (_iso(d3Start),),
        )
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=30), count=3,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        freshDb.commit()
        matches = bf.findOrphanBackfillMatches(freshDb)
        bf.applyBackfill(freshDb, matches)
        row = freshDb.execute(
            "SELECT drive_start_timestamp, ambient_temp_at_start_c, "
            "starting_battery_v, barometric_kpa_at_start "
            "FROM drive_summary WHERE drive_id=3",
        ).fetchone()
        assert row == (_iso(d3Start), 19.0, 13.4, 100.5)


# ================================================================================
# applyBackfill -- safety: per-drive cap enforced
# ================================================================================

class TestApplyBackfillSafety:
    def test_respectsMaxOrphansPerDriveCap(
        self, freshDb: sqlite3.Connection,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        # 100 orphans within the cap window
        _insertOrphans(
            freshDb,
            startTime=d3Start - timedelta(seconds=50),
            count=100,
            intervalSeconds=0.4,  # ~40s span
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        # cap = 10 -- the function should refuse, not silently truncate
        with pytest.raises(bf.SafetyCapError, match='maxOrphansPerDrive'):
            bf.findOrphanBackfillMatches(
                freshDb, windowSeconds=60.0,
                maxOrphansPerDrive=10,
            )


# ================================================================================
# CLI -- --dry-run and --execute
# ================================================================================

class TestCli:
    def test_dryRun_doesNotMutate(
        self, freshDb: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=30), count=3,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        freshDb.commit()
        beforeOrphans = _countNullDriveIdRealRows(freshDb)
        beforeDrive3 = _countDriveRows(freshDb, 3)
        dbPath = _connectionPath(freshDb)
        rc = bf.main(['--db', dbPath, '--dry-run'])
        assert rc == 0
        # Nothing changed -- dry-run is read-only
        afterOrphans = _countNullDriveIdRealRows(freshDb)
        afterDrive3 = _countDriveRows(freshDb, 3)
        assert (afterOrphans, afterDrive3) == (beforeOrphans, beforeDrive3)

    def test_executeRequiresPriorDryRun_refusesWithoutSentinel(
        self, freshDb: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        # No --dry-run sentinel exists -> --execute must refuse
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=30), count=3,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        freshDb.commit()
        dbPath = _connectionPath(freshDb)
        rc = bf.main([
            '--db', dbPath, '--execute',
            '--sentinel-dir', str(tmp_path / 'no-sentinel-here'),
        ])
        assert rc == 2
        # No mutation
        assert _countNullDriveIdRealRows(freshDb) == 3

    def test_executeAfterDryRun_appliesBackfill(
        self, freshDb: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        d3Start = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        _insertOrphans(
            freshDb, startTime=d3Start - timedelta(seconds=30), count=3,
        )
        _insertDrive(
            freshDb, driveId=3, startTime=d3Start, durationSeconds=10,
        )
        freshDb.commit()
        dbPath = _connectionPath(freshDb)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        # Dry-run first to write the sentinel
        rcDry = bf.main([
            '--db', dbPath, '--dry-run',
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rcDry == 0
        # Now execute
        rcExec = bf.main([
            '--db', dbPath, '--execute',
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rcExec == 0
        # The 3 orphans should now carry drive_id=3
        assert _countNullDriveIdRealRows(freshDb) == 0
        # Drive 3 row count went up by 3 (was 30 from _insertDrive)
        assert _countDriveRows(freshDb, 3) == 30 + 3

    def test_dryRunAndExecuteAreMutuallyExclusive(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(SystemExit):
            bf.main(['--db', str(tmp_path / 'no.db'),
                     '--dry-run', '--execute'])

    def test_noModeFlag_exits(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            bf.main(['--db', str(tmp_path / 'no.db')])

    def test_executeOnAlreadyCleanDb_succeedsAsNoOp(
        self, freshDb: sqlite3.Connection, tmp_path: Path,
    ) -> None:
        # No orphans, no drives -- script should report 0 and exit 0
        dbPath = _connectionPath(freshDb)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        bf.main([
            '--db', dbPath, '--dry-run',
            '--sentinel-dir', str(sentinelDir),
        ])
        rc = bf.main([
            '--db', dbPath, '--execute',
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc == 0


def _connectionPath(conn: sqlite3.Connection) -> str:
    """Return the on-disk path backing a sqlite3.Connection."""
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2]
