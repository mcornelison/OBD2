################################################################################
# File Name: test_cleanup_orphan_leak.py
# Purpose/Description: TDD regression tests for US-336 (Spool 2026-05-12
#                      Story F) -- the recent-orphan-sweep pass added to
#                      scripts/cleanup_orphan_realtime_data.py.  After
#                      V0.27.6 US-322's nightly cleanup landed, ~199 orphan
#                      NULL-drive_id realtime_data rows still accumulated on
#                      the Pi over the 24h window between firings (8/hour
#                      steady-state).  drive_id is set at INSERT-time and
#                      never updated, so a NULL-drive_id row older than the
#                      maximum DriveDetector engage lag is permanently
#                      orphaned -- the new runRecentOrphanSweep() pass
#                      deletes such rows on each firing (default cutoff 4h,
#                      controllable via --recent-orphan-age-hours /
#                      --no-recent-orphan-sweep).
# Author: Agent2 (Ralph agent)
# Creation Date: 2026-05-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author          | Description
# ================================================================================
# 2026-05-13    | Agent2 (US-336) | Initial -- regression coverage for the
#                                   199-orphan-leak pattern (Spool Story F).
# ================================================================================
################################################################################

"""TDD regression tests for the US-336 recent-orphan-sweep cleanup pass.

Pre-fix, ``scripts/cleanup_orphan_realtime_data.py`` deleted NULL-drive_id rows
older than 24h only.  Rows aged 0-24h survived every firing -- giving Spool
a steady-state ~199-row leak on the Pi (down from 61,293 pre-US-322, but
still above the post-Drive-12 ``<= 50`` target in
``offices/ralph/sprint.json`` US-336).

Post-fix, ``main()`` runs an additional sweep via the new
``runRecentOrphanSweep`` function (default cutoff 4h).  ``drive_id`` is set
at INSERT-time and never updated, so a NULL-drive_id row older than the
maximum DriveDetector engage lag is permanently orphaned -- 4h is
conservative.

The regression-test ``test_execute_deletesNullRowsOlderThanSweepCutoff``
fails pre-fix (``runRecentOrphanSweep`` does not exist -> AttributeError)
and passes post-fix once the function is added.
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
        'cleanup_orphan_realtime_data_us336', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['cleanup_orphan_realtime_data_us336'] = mod
    spec.loader.exec_module(mod)
    return mod


coc = _loadScript()


# ================================================================================
# Fixtures: synthetic realtime_data DB mirroring the leak-pattern row classes
# ================================================================================

# Anchor "now" so cutoff math is deterministic.
_NOW = _dt.datetime(2026, 5, 13, 4, 0, 0, tzinfo=_dt.UTC)


def _iso(ts: _dt.datetime) -> str:
    """Mirror the schema's strftime('%Y-%m-%dT%H:%M:%SZ', 'now') format."""
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


def _frozenNow() -> _dt.datetime:
    return _NOW


def _createTable(conn: sqlite3.Connection) -> None:
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


def _seedRows(
    conn: sqlite3.Connection,
    *,
    count: int,
    driveId: int | None,
    ageHours: float,
    nowDt: _dt.datetime = _NOW,
) -> None:
    ts = _iso(nowDt - _dt.timedelta(hours=ageHours))
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


@pytest.fixture
def leakFixtureDb() -> sqlite3.Connection:
    """In-memory DB seeded to mirror the steady-state orphan accumulation.

    Row classes (timestamp anchor: ``_NOW = 2026-05-13T04:00:00Z``):
      - 50 rows: drive_id=NULL,    6h old -> LEAK CLASS (> 4h sweep cutoff)
      - 25 rows: drive_id=NULL,    2h old -> preserve at 4h cutoff (< 4h)
      - 10 rows: drive_id=NULL, 30min old -> preserve at 4h cutoff (< 4h)
      - 20 rows: drive_id=42,      6h old -> preserve (tagged, ignored by sweep)
      - 15 rows: drive_id=42,   30min old -> preserve (tagged + recent)

    Total 120.  Sweep at 4h cutoff deletes exactly 50; 70 survive.
    Sweep at 1h cutoff deletes 50 + 25 = 75; 45 survive.
    """
    conn = sqlite3.connect(':memory:')
    _createTable(conn)
    _seedRows(conn, count=50, driveId=None, ageHours=6.0)
    _seedRows(conn, count=25, driveId=None, ageHours=2.0)
    _seedRows(conn, count=10, driveId=None, ageHours=0.5)
    _seedRows(conn, count=20, driveId=42, ageHours=6.0)
    _seedRows(conn, count=15, driveId=42, ageHours=0.5)
    conn.commit()
    return conn


def _countTotal(conn: sqlite3.Connection) -> int:
    return int(conn.execute('SELECT COUNT(*) FROM realtime_data').fetchone()[0])


def _countNull(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL',
        ).fetchone()[0],
    )


def _countTagged(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute(
            'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NOT NULL',
        ).fetchone()[0],
    )


def _writeStandaloneSeededDb(path: Path, *, nowDt: _dt.datetime | None = None) -> None:
    """Write the same 5-class fixture to an on-disk DB for CLI tests.

    CLI tests cannot pin the script's clock via ``nowFn``; they use real
    ``datetime.now()``.  Seeding the fixture at deterministic ages relative
    to ``datetime.now(UTC)`` (the default) keeps the cutoff math correct
    regardless of when the test happens to run.
    """
    if nowDt is None:
        nowDt = _dt.datetime.now(_dt.UTC)
    conn = sqlite3.connect(path)
    _createTable(conn)
    _seedRows(conn, count=50, driveId=None, ageHours=6.0, nowDt=nowDt)
    _seedRows(conn, count=25, driveId=None, ageHours=2.0, nowDt=nowDt)
    _seedRows(conn, count=10, driveId=None, ageHours=0.5, nowDt=nowDt)
    _seedRows(conn, count=20, driveId=42, ageHours=6.0, nowDt=nowDt)
    _seedRows(conn, count=15, driveId=42, ageHours=0.5, nowDt=nowDt)
    conn.commit()
    conn.close()


def _countOrphansOnDisk(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(
            'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NULL',
        ).fetchone()[0])


def _countTaggedOnDisk(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return int(conn.execute(
            'SELECT COUNT(*) FROM realtime_data WHERE drive_id IS NOT NULL',
        ).fetchone()[0])


# ================================================================================
# Tests: runRecentOrphanSweep pure-API contract -- the new function
# ================================================================================

class TestRunRecentOrphanSweep:
    """Pure-API tests for the new sweep function.

    Pre-fix the function does not exist -> every test here errors with
    ``AttributeError`` on the ``coc.runRecentOrphanSweep`` call site.
    """

    def test_dryRun_doesNotMutateDatabase(self, leakFixtureDb):
        before = _countTotal(leakFixtureDb)

        result = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=False,
            nowFn=_frozenNow,
        )

        assert result.executed is False
        assert result.rowsDeleted == 0
        assert _countTotal(leakFixtureDb) == before

    def test_dryRun_reportsEligibleCountForOrphansOlderThanCutoff(self, leakFixtureDb):
        # Eligible (NULL AND age > 4h): the 50 rows aged 6h.  The 2h-old +
        # 30min-old NULL rows are recent enough to stay (could be in-flight
        # pre-engage windows).
        result = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=False,
            nowFn=_frozenNow,
        )

        assert result.eligibleRowCount == 50

    def test_execute_deletesNullRowsOlderThanSweepCutoff(self, leakFixtureDb):
        """REGRESSION TEST for the 199-orphan-leak pattern (Spool Story F).

        Pre-fix: no sweep exists; NULL rows aged 0-24h survive every cleanup
        firing.  Post-fix: this sweep deletes NULL rows older than the 4h
        cutoff, catching the dominant leak class (rows written during
        pre-engage / reconnect-noise windows that are by definition
        permanently orphaned -- drive_id is set at INSERT, never updated).
        """
        result = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=True,
            nowFn=_frozenNow,
        )

        assert result.executed is True
        assert result.rowsDeleted == 50  # the 50 6h-old NULL rows
        # Survivors: 25 + 10 + 20 + 15 = 70
        assert _countTotal(leakFixtureDb) == 70
        # Remaining NULL: 25 (2h-old) + 10 (30min-old) = 35; well under any
        # reasonable in-flight DriveDetector engage window.
        assert _countNull(leakFixtureDb) == 35

    def test_execute_preservesAllTaggedRows_evenWhenOld(self, leakFixtureDb):
        """The 20 tagged 6h-old rows must survive: only NULL-drive_id rows
        are in scope.  This pins the WHERE-clause discrimination -- if a
        future refactor ever widens to a generic age-based purge, this
        breaks loudly."""
        coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=True,
            nowFn=_frozenNow,
        )

        # 20 tagged 6h + 15 tagged 30min = 35.
        assert _countTagged(leakFixtureDb) == 35

    def test_execute_preservesRecentNullRowsWithinSweepWindow(self, leakFixtureDb):
        """The 25 (2h) + 10 (30min) NULL rows must survive the 4h sweep.

        Rationale: although ``drive_id`` is set at INSERT time and these
        rows COULD be permanently orphaned already, a generous sweep
        window leaves headroom for diagnostic queries against recent
        NULL-drive_id activity (eg. debugging DriveDetector engage lag).
        """
        coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=True,
            nowFn=_frozenNow,
        )

        # 25 (2h-old) + 10 (30min-old) = 35 NULL rows survive.
        assert _countNull(leakFixtureDb) == 35

    def test_execute_isIdempotent_secondRunIsZero(self, leakFixtureDb):
        first = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=True,
            nowFn=_frozenNow,
        )
        second = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=True,
            nowFn=_frozenNow,
        )

        assert first.rowsDeleted == 50
        assert second.eligibleRowCount == 0
        assert second.rowsDeleted == 0

    def test_customSweepCutoff_oneHour_deletesMoreOrphans(self, leakFixtureDb):
        """At 1h cutoff the 2h-old NULL rows (25) ALSO become eligible.

        Cutoff = NOW - 1h; rows with ``timestamp < cutoff`` are deleted.
        50 (6h-old NULL) + 25 (2h-old NULL) = 75 rows match.  The
        30min-old NULL rows still survive (< 1h cutoff).
        """
        result = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=1.0,
            execute=True,
            nowFn=_frozenNow,
        )

        assert result.rowsDeleted == 75
        assert _countNull(leakFixtureDb) == 10  # only the 30min-old NULL survive

    def test_resultCarriesCutoffStringForLogging(self, leakFixtureDb):
        result = coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=False,
            nowFn=_frozenNow,
        )

        assert result.cutoffTimestamp == _iso(_NOW - _dt.timedelta(hours=4))
        assert result.nowTimestamp == _iso(_NOW)

    def test_negativeAgeHoursRejected(self, leakFixtureDb):
        with pytest.raises(ValueError):
            coc.runRecentOrphanSweep(
                leakFixtureDb,
                recentOrphanAgeHours=-1.0,
                execute=False,
                nowFn=_frozenNow,
            )

    def test_defaultRecentOrphanAgeHoursPinnedAtFourHours(self):
        """Constant pin: the default sweep cutoff is 4.0 hours.

        Rationale: drive_id is set at INSERT, never updated; a NULL row
        older than the DriveDetector engage lag (~30s typically) is
        permanently orphaned.  4h gives diagnostic headroom while still
        cutting daily steady-state count well below the 50-orphan target.
        """
        assert coc.DEFAULT_RECENT_ORPHAN_AGE_HOURS == 4.0


# ================================================================================
# Tests: CLI surface -- both passes run by default; --no-recent-orphan-sweep opt-out
# ================================================================================

class TestSweepCli:
    """End-to-end CLI tests proving the recent-orphan sweep is wired into
    ``main()`` by default (so the existing ``.service`` ExecStart picks it
    up automatically, without US-334 territory)."""

    def test_main_executeRunsBothPassesByDefault(self, tmp_path, capsys):
        """``main --execute`` (no sweep flag) deletes BOTH the >24h NULL rows
        (main pass) AND the >4h NULL rows (sweep pass).

        Pre-fix: only the main pass runs -> the 6h-old NULL rows survive
        and ``_countOrphansOnDisk`` returns 50 + 25 + 10 = 85.
        Post-fix: sweep runs by default -> the 6h-old NULL rows are
        ALSO deleted -> ``_countOrphansOnDisk`` returns 25 + 10 = 35.

        The fixture has no >24h-old rows, so the main pass deletes 0;
        the entire 50-row delete comes from the sweep.
        """
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main(['--db', str(dbPath), '--execute'])
        captured = capsys.readouterr()

        assert exitCode == 0
        # Tagged rows preserved.
        assert _countTaggedOnDisk(dbPath) == 35
        # NULL rows: 50 (6h-old) deleted by sweep; 25 (2h-old) + 10 (30min) survive.
        assert _countOrphansOnDisk(dbPath) == 35
        # Sweep line should be present in the CLI output.
        out = captured.out.lower()
        assert 'sweep' in out or 'recent-orphan' in out

    def test_main_noRecentOrphanSweep_skipsSweepPass(self, tmp_path, capsys):
        """``--no-recent-orphan-sweep`` opts out -- the LEGACY 24h-only
        behaviour is preserved for operators who want to keep recent NULL
        rows for diagnostic windows.

        With sweep disabled, only the main pass runs.  The fixture has no
        >24h rows, so 0 deletions, ``_countOrphansOnDisk`` stays at 85.
        """
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main([
            '--db', str(dbPath),
            '--execute',
            '--no-recent-orphan-sweep',
        ])
        capsys.readouterr()

        assert exitCode == 0
        # 50 + 25 + 10 = 85 NULL rows all survive (none > 24h old).
        assert _countOrphansOnDisk(dbPath) == 85
        # Tagged rows preserved.
        assert _countTaggedOnDisk(dbPath) == 35

    def test_main_customRecentOrphanAgeHours(self, tmp_path, capsys):
        """``--recent-orphan-age-hours 1`` tightens the sweep cutoff.

        At 1h, the 2h-old NULL rows (25) ALSO become eligible.  Combined
        with the 6h-old NULL rows (50), that's 75 deletions; only the
        30min-old NULL (10) survive among NULL rows.
        """
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main([
            '--db', str(dbPath),
            '--execute',
            '--recent-orphan-age-hours', '1',
        ])
        capsys.readouterr()

        assert exitCode == 0
        # Only the 30min-old NULL survive.
        assert _countOrphansOnDisk(dbPath) == 10
        assert _countTaggedOnDisk(dbPath) == 35

    def test_main_dryRunReportsSweepEligibleWithoutDeleting(self, tmp_path, capsys):
        """The dry-run reports the sweep's eligible count but mutates nothing."""
        dbPath = tmp_path / 'obd.db'
        _writeStandaloneSeededDb(dbPath)

        exitCode = coc.main(['--db', str(dbPath)])  # no --execute -> dry-run
        captured = capsys.readouterr()

        assert exitCode == 0
        # Nothing deleted: all 50 + 25 + 10 = 85 NULL rows still present.
        assert _countOrphansOnDisk(dbPath) == 85
        # All 20 + 15 = 35 tagged rows still present.
        assert _countTaggedOnDisk(dbPath) == 35
        # CLI reports the sweep's eligible count somewhere in output.
        out = captured.out.lower()
        assert 'sweep' in out or 'recent-orphan' in out


# ================================================================================
# Tests: end-to-end leak-pattern regression
# ================================================================================

class TestLeakPatternRegression:
    """Pin the specific Spool Story F symptom: a steady-state accumulation
    of NULL-drive_id rows aged > 4h (the dominant leak class identified
    via code archaeology) is reduced to zero by the new sweep."""

    def test_steadyStateLeakClass_reducedToZero_byDefaultSweep(self, leakFixtureDb):
        """50 rows representing a day's worth of >4h-old NULL accumulation
        all get cleared on a single sweep firing with default args."""
        priorOrphansAgedOver4h = leakFixtureDb.execute(
            'SELECT COUNT(*) FROM realtime_data '
            'WHERE drive_id IS NULL AND timestamp < ?',
            (_iso(_NOW - _dt.timedelta(hours=4)),),
        ).fetchone()[0]
        assert priorOrphansAgedOver4h == 50  # pre-sweep baseline

        coc.runRecentOrphanSweep(
            leakFixtureDb,
            recentOrphanAgeHours=4.0,
            execute=True,
            nowFn=_frozenNow,
        )

        afterOrphansAgedOver4h = leakFixtureDb.execute(
            'SELECT COUNT(*) FROM realtime_data '
            'WHERE drive_id IS NULL AND timestamp < ?',
            (_iso(_NOW - _dt.timedelta(hours=4)),),
        ).fetchone()[0]
        assert afterOrphansAgedOver4h == 0  # leak class cleared
