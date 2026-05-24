################################################################################
# File Name: test_cleanup_orphan_realtime_data.py
# Purpose/Description: TDD tests for scripts/cleanup_orphan_realtime_data.py
#                      (US-322 / B-072).  Covers the pure scanOrphans / runCleanup
#                      API + CLI --dry-run / --execute / --age-hours flags +
#                      idempotency + the WHERE clause's discrimination between
#                      NULL-drive_id-old (delete) and the three preservation
#                      classes (NULL-recent, tagged-old, tagged-recent).
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex (US-322) | Initial -- TDD coverage for the orphan cleanup
#                               script (B-072).
# ================================================================================
################################################################################

"""TDD tests for the US-322 / B-072 orphan-realtime-data cleanup script.

The realtime_data column is ``timestamp DATETIME`` (canonical ISO-8601 UTC
strings emitted via ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`` -- see
src/pi/obdii/database_schema.py).  The story spec said ``timestamp_ms`` but
no such column exists; tests pin the actual column to keep the script honest
against the live schema.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'cleanup_orphan_realtime_data.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'cleanup_orphan_realtime_data', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['cleanup_orphan_realtime_data'] = mod
    spec.loader.exec_module(mod)
    return mod


coc = _loadScript()


# ================================================================================
# Fixtures: synthetic realtime_data DB
# ================================================================================

# Anchor "now" so cutoff math is deterministic.
_NOW = _dt.datetime(2026, 5, 11, 12, 0, 0, tzinfo=_dt.UTC)


def _iso(ts: _dt.datetime) -> str:
    """Mirror schema's strftime('%Y-%m-%dT%H:%M:%SZ', 'now') format."""
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


def _frozenNow() -> _dt.datetime:
    return _NOW


@pytest.fixture
def freshDb() -> sqlite3.Connection:
    """In-memory realtime_data table seeded with 4 row classes.

    Row classes:
      - 100 rows: drive_id=NULL,  timestamp 48h old -> SHOULD be deleted (>24h cutoff)
      -  50 rows: drive_id=NULL,  timestamp  6h old -> PRESERVE (recent NULL)
      -  30 rows: drive_id=7,     timestamp 72h old -> PRESERVE (tagged, even though old)
      -  20 rows: drive_id=7,     timestamp  1h old -> PRESERVE (tagged + recent)
    Total 200; cleanup at 24h cutoff should remove exactly 100, leaving 100.
    """
    conn = sqlite3.connect(':memory:')
    conn.execute(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            profile_id TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        )
        """,
    )

    def _seed(*, count: int, driveId: int | None, ageHours: float) -> None:
        ts = _iso(_NOW - _dt.timedelta(hours=ageHours))
        rows = [
            (ts, 'RPM', 1500.0 + i, 'rpm', 'daily', 'real', driveId)
            for i in range(count)
        ]
        conn.executemany(
            'INSERT INTO realtime_data '
            '(timestamp, parameter_name, value, unit, profile_id, data_source, drive_id) '
            'VALUES (?,?,?,?,?,?,?)',
            rows,
        )

    _seed(count=100, driveId=None, ageHours=48)   # delete
    _seed(count=50, driveId=None, ageHours=6)     # preserve (NULL but recent)
    _seed(count=30, driveId=7, ageHours=72)       # preserve (tagged + old)
    _seed(count=20, driveId=7, ageHours=1)        # preserve (tagged + recent)
    conn.commit()
    return conn


def _countTotal(conn: sqlite3.Connection) -> int:
    return int(conn.execute('SELECT COUNT(*) FROM realtime_data').fetchone()[0])


def _countNullDriveId(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute('SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL').fetchone()[0],
    )


# ================================================================================
# Tests: pure-API contracts (the script's testable seam)
# ================================================================================

class TestComputeCutoff:
    def test_returnsIsoUtcStringForNowMinusAgeHours(self):
        cutoff = coc.computeCutoff(ageHours=24, nowFn=_frozenNow)

        expected = _iso(_NOW - _dt.timedelta(hours=24))
        assert cutoff == expected
        assert cutoff.endswith('Z')

    def test_zeroAgeHoursReturnsNowItself(self):
        # Edge-case sanity: ageHours=0 means cutoff == now (no row "older
        # than now" by strict <).  Useful for operators who want to clear
        # ALL NULL rows immediately.
        cutoff = coc.computeCutoff(ageHours=0, nowFn=_frozenNow)
        assert cutoff == _iso(_NOW)

    def test_negativeAgeHoursRejected(self):
        with pytest.raises(ValueError):
            coc.computeCutoff(ageHours=-1, nowFn=_frozenNow)


class TestRunCleanup:
    def test_dryRun_returnsCountWithoutDeleting(self, freshDb):
        before = _countTotal(freshDb)

        result = coc.runCleanup(
            freshDb, ageHours=24, execute=False, nowFn=_frozenNow,
        )

        assert result.eligibleRowCount == 100
        assert result.rowsDeleted == 0  # dry-run never writes
        assert result.executed is False
        assert _countTotal(freshDb) == before  # DB unchanged

    def test_execute_deletesOnlyNullAndOlderThanCutoff(self, freshDb):
        result = coc.runCleanup(
            freshDb, ageHours=24, execute=True, nowFn=_frozenNow,
        )

        assert result.executed is True
        assert result.rowsDeleted == 100  # only the NULL+old class
        assert _countTotal(freshDb) == 100  # 200 - 100
        assert _countNullDriveId(freshDb) == 50  # the recent NULL rows survive

    def test_execute_preservesAllTaggedRows_evenWhenOld(self, freshDb):
        coc.runCleanup(
            freshDb, ageHours=24, execute=True, nowFn=_frozenNow,
        )

        tagged = freshDb.execute(
            'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NOT NULL',
        ).fetchone()[0]
        # 30 (tagged+old) + 20 (tagged+recent) = 50; both survive.
        assert tagged == 50

    def test_execute_isIdempotent_secondRunIsZero(self, freshDb):
        first = coc.runCleanup(
            freshDb, ageHours=24, execute=True, nowFn=_frozenNow,
        )
        second = coc.runCleanup(
            freshDb, ageHours=24, execute=True, nowFn=_frozenNow,
        )

        assert first.rowsDeleted == 100
        assert second.eligibleRowCount == 0
        assert second.rowsDeleted == 0

    def test_resultCarriesCutoffStringForLogging(self, freshDb):
        result = coc.runCleanup(
            freshDb, ageHours=24, execute=False, nowFn=_frozenNow,
        )

        assert result.cutoffTimestamp == _iso(_NOW - _dt.timedelta(hours=24))

    def test_executeOnlyNullClauseShape_taggedOldRowsPreserved(self, freshDb):
        # Discriminator: would FAIL if the WHERE clause ever dropped the
        # ``drive_id IS NULL`` predicate (e.g. accidentally widened to a
        # generic age-based purge).  Tagged-OLDER-than-cutoff rows MUST stay.
        coc.runCleanup(
            freshDb, ageHours=24, execute=True, nowFn=_frozenNow,
        )
        taggedOld = freshDb.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id = 7 AND timestamp < ?",
            (_iso(_NOW - _dt.timedelta(hours=24)),),
        ).fetchone()[0]
        # The 30 tagged+72h-old rows must survive intact.
        assert taggedOld == 30


# ================================================================================
# Tests: CLI surface (argparse)
# ================================================================================

class TestCli:
    def test_main_dryRunByDefault(self, tmp_path, capsys):
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main(['--db', str(dbPath)])
        captured = capsys.readouterr()

        assert exitCode == 0
        assert 'DRY-RUN' in captured.out or 'dry-run' in captured.out.lower()
        # No write happened: total NULL rows still 150 (100 old + 50 recent).
        assert _countOrphans(dbPath) == 150
        # The eligible-but-not-deleted count is reported.
        assert 'eligible=100' in captured.out

    def test_main_executeDeletes(self, tmp_path, capsys):
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main(['--db', str(dbPath), '--execute'])
        captured = capsys.readouterr()

        assert exitCode == 0
        # US-336: ``main()`` now runs the recent-orphan sweep by default (4h
        # cutoff) AFTER the main 24h-pass.  Main pass deletes 100 (NULL+48h
        # old); sweep deletes 50 (NULL+6h old, > 4h cutoff).  All tagged
        # rows preserved.  Legacy 24h-only behaviour is opt-in via
        # ``--no-recent-orphan-sweep`` (see test_cleanup_orphan_leak.py).
        assert _countOrphans(dbPath) == 0
        # The main-pass line still reports rowsDeleted=100; the sweep line
        # then reports rowsDeleted=50 on a separate ``sweep recent-orphan``
        # line.  This assertion pins the main-pass output unchanged.
        assert 'rowsDeleted=100' in captured.out or 'deleted 100' in captured.out.lower()

    def test_main_missingDb_exitsNonZero(self, tmp_path, capsys):
        bogus = tmp_path / 'nope.db'
        exitCode = coc.main(['--db', str(bogus)])
        captured = capsys.readouterr()

        assert exitCode != 0
        assert 'not found' in (captured.err + captured.out).lower() or \
               'no such' in (captured.err + captured.out).lower()

    def test_main_customAgeHours(self, tmp_path, capsys):
        # With --age-hours 4, both the 48h-old (100) AND the 6h-old (50) NULL
        # rows are now older than the cutoff -> 150 eligible.  Tagged rows
        # still preserved.
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main(['--db', str(dbPath), '--execute', '--age-hours', '4'])
        capsys.readouterr()  # drain captured output (not asserted in this test)

        assert exitCode == 0
        assert _countOrphans(dbPath) == 0  # both NULL classes purged
        # Tagged rows untouched.
        with sqlite3.connect(dbPath) as conn:
            assert conn.execute(
                'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NOT NULL',
            ).fetchone()[0] == 50


# ================================================================================
# Standalone DB seeder for CLI tests (the freshDb fixture is in-memory only)
# ================================================================================

def _writeStandaloneSeededDb(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            profile_id TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        )
        """,
    )
    # Use REAL-time "now" here (not the frozen anchor) because CLI tests
    # exercise the script's own time source.  Cutoff math still works:
    # 48h-old rows are >24h before "now" regardless of when "now" is.
    now = _dt.datetime.now(_dt.UTC)

    def seed(count: int, driveId: int | None, ageHours: float) -> None:
        ts = (now - _dt.timedelta(hours=ageHours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows = [
            (ts, 'RPM', 1500.0 + i, 'rpm', 'daily', 'real', driveId)
            for i in range(count)
        ]
        conn.executemany(
            'INSERT INTO realtime_data '
            '(timestamp, parameter_name, value, unit, profile_id, data_source, drive_id) '
            'VALUES (?,?,?,?,?,?,?)',
            rows,
        )

    seed(100, None, 48)
    seed(50, None, 6)
    seed(30, 7, 72)
    seed(20, 7, 1)
    conn.commit()
    conn.close()


def _countOrphans(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(
            'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL',
        ).fetchone()[0])
