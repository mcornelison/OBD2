################################################################################
# File Name: test_truncate_drive_id_1_pollution.py
# Purpose/Description: Unit tests for scripts/truncate_drive_id_1_pollution.py.
#                      Covers the US-227 sync-gate, drive_counter target,
#                      pollution-window orphan scan, fixture-hash safety, table
#                      filtering on (drive_id, data_source) intersection,
#                      sentinel flow, divergence detection, and CLI safety
#                      gates. Real DELETE behavior validated against an
#                      in-memory SQLite DB so the WHERE clause is exercised
#                      against a real query planner without touching a network.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-27    | Rex (US-227) | Initial -- TDD coverage for US-227 truncate
# ================================================================================
################################################################################

"""TDD tests for the US-227 drive_id=1 pollution truncate script."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'truncate_drive_id_1_pollution.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'truncate_drive_id_1_pollution', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['truncate_drive_id_1_pollution'] = mod
    spec.loader.exec_module(mod)
    return mod


tdp = _loadScript()


# ================================================================================
# FakeRunner
# ================================================================================

@dataclass
class FakeRunner:
    """Scripted subprocess runner that matches the CommandRunner Protocol."""

    responses: list[tuple[str, subprocess.CompletedProcess[str]]] = field(
        default_factory=list,
    )
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- matches Protocol
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {'argv': list(argv), 'input': input, 'timeout': timeout},
        )
        argvJoined = ' '.join(argv)
        payload = input or ''
        for needle, response in self.responses:
            if needle in argvJoined or (payload and needle in payload):
                return response
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout='', stderr='',
        )


def _ok(stdout: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


# ================================================================================
# Fixtures: hash-pinned constants and synthetic DBs
# ================================================================================

_EXPECTED_FIXTURE_SHA = (
    '0b90b188fa31f6285d8440ba1a251678a2ac652dd589314a50062fa06c5d38db'
)


@pytest.fixture
def syntheticPiDb(tmp_path: Path) -> Path:
    """Build an in-memory-shape Pi DB with the exact pollution shape."""
    dbPath = tmp_path / 'pi.db'
    conn = sqlite3.connect(dbPath)
    conn.executescript(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        );
        CREATE TABLE connection_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            event_type TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        );
        CREATE TABLE statistics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parameter_name TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        );
        CREATE TABLE drive_summary (
            drive_id INTEGER PRIMARY KEY,
            data_source TEXT NOT NULL DEFAULT 'real'
        );
        CREATE TABLE alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            drive_id INTEGER
        );
        CREATE TABLE drive_counter (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_drive_id INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE sync_log (
            table_name TEXT PRIMARY KEY,
            last_synced_id INTEGER NOT NULL DEFAULT 0,
            last_synced_at TEXT,
            last_batch_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        """,
    )
    # 5 drive_id=1 real rows (the pollution).
    for i in range(5):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value, "
            "data_source, drive_id) VALUES (?, 'RPM', 0.0, 'real', 1)",
            (f'2026-04-21T02:27:{i:02d}Z',),
        )
    # 1 drive_id=1 physics_sim row -- MUST NOT be deleted (data_source filter)
    conn.execute(
        "INSERT INTO realtime_data (timestamp, parameter_name, value, "
        "data_source, drive_id) VALUES (?, 'RPM', 0.0, 'physics_sim', 1)",
        ('2026-04-21T02:27:99Z',),
    )
    # 2 drive_id=3 real rows -- MUST NOT be deleted (Drive 3 preservation)
    for i in range(2):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value, "
            "data_source, drive_id) VALUES (?, 'RPM', 800.0, 'real', 3)",
            (f'2026-04-23T16:36:{50 + i:02d}Z',),
        )
    # 3 NULL drive_id real rows (US-233 territory) -- MUST NOT be deleted
    for i in range(3):
        conn.execute(
            "INSERT INTO realtime_data (timestamp, parameter_name, value, "
            "data_source, drive_id) VALUES (?, 'RPM', 0.0, 'real', NULL)",
            (f'2026-04-23T16:36:{10 + i:02d}Z',),
        )
    # 2 connection_log drive_id=1 real (matches live observation)
    for i in range(2):
        conn.execute(
            "INSERT INTO connection_log (timestamp, event_type, data_source, "
            "drive_id) VALUES (?, 'connect', 'real', 1)",
            (f'2026-04-21T02:27:{i:02d}Z',),
        )
    # drive_counter starts at 3 (post-Drive-3 high-water).
    conn.execute(
        'INSERT INTO drive_counter (id, last_drive_id) VALUES (1, 3)',
    )
    # sync_log cursor satisfies the gate (id >= MIN_REALTIME_SYNC_CURSOR).
    conn.execute(
        "INSERT INTO sync_log (table_name, last_synced_id, last_synced_at, "
        "last_batch_id, status) VALUES "
        "('realtime_data', 3439960, '2026-04-27T13:35:16Z', 'b1', 'ok')",
    )
    conn.commit()
    conn.close()
    return dbPath


@pytest.fixture
def realFixturePath() -> Path:
    """Path to the real eclipse_idle.db fixture (read-only check)."""
    return _PROJECT_ROOT / 'data' / 'regression' / 'pi-inputs' / 'eclipse_idle.db'


# ================================================================================
# Constants and policy targets (the script's intent surface)
# ================================================================================

class TestConstants:
    """The script's policy constants pin the Sprint 18 truncate decision."""

    def test_driveIdTargetIsOne(self) -> None:
        assert tdp.DRIVE_ID_TARGET == 1

    def test_driveCounterTargetIsThree(self) -> None:
        # Drive 3 = legitimate high-water. Acceptance #5 + invariant idempotency.
        assert tdp.DRIVE_COUNTER_TARGET == 3

    def test_minRealtimeSyncCursorMatchesDrive3Max(self) -> None:
        # Pre-flight 2026-04-27: Drive 3 max id = 3,439,960.
        assert tdp.MIN_REALTIME_SYNC_CURSOR == 3_439_960

    def test_pollutionWindowMatchesSpoolFinding(self) -> None:
        # Spool consolidated note Section 1: 2026-04-21 02:27 -> 2026-04-23 03:12 UTC.
        assert tdp.POLLUTION_WINDOW_START == '2026-04-21 02:27'
        assert tdp.POLLUTION_WINDOW_END == '2026-04-23 03:12'

    def test_sentinelNameIsUs227Specific(self) -> None:
        # Must NOT collide with US-205's '.us205-dry-run-ok'.
        assert tdp.DRY_RUN_SENTINEL_NAME == '.us227-dry-run-ok'
        assert tdp.DRY_RUN_SENTINEL_NAME != '.us205-dry-run-ok'

    def test_dataSourceTargetIsReal(self) -> None:
        # Story scope is strict: only data_source='real' rows.
        assert tdp.DATA_SOURCE_TARGET == 'real'


# ================================================================================
# Table-target discovery
# ================================================================================

class TestEnumerateTargetTables:
    """The script enumerates Pi tables with both drive_id and data_source."""

    def test_listsTablesWithBothColumns(self, syntheticPiDb: Path) -> None:
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        names = {t.name for t in targets}
        # realtime_data, connection_log, statistics all qualify (both cols).
        assert 'realtime_data' in names
        assert 'connection_log' in names
        assert 'statistics' in names

    def test_excludesAlertLog(self, syntheticPiDb: Path) -> None:
        # alert_log has drive_id but no data_source per US-205 carve-out.
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        names = {t.name for t in targets}
        assert 'alert_log' not in names

    def test_excludesDriveSummary(self, syntheticPiDb: Path) -> None:
        # drive_summary has drive_id+data_source but is per-drive metadata,
        # not a row-stream capture table. US-227 doNotTouch list calls it out.
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        names = {t.name for t in targets}
        assert 'drive_summary' not in names

    def test_eachTargetExposesPollutionRowCount(
        self, syntheticPiDb: Path,
    ) -> None:
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        rt = next(t for t in targets if t.name == 'realtime_data')
        # 5 drive_id=1 real rows in the fixture.
        assert rt.drive1RealRows == 5
        cl = next(t for t in targets if t.name == 'connection_log')
        # 2 drive_id=1 real rows in the fixture.
        assert cl.drive1RealRows == 2


# ================================================================================
# Sync gate
# ================================================================================

class TestSyncGate:
    """The sync_log cursor must be >= Drive 3 max id before --execute."""

    def test_returnsCursorValue(self, syntheticPiDb: Path) -> None:
        cursor = tdp.readRealtimeSyncCursor(syntheticPiDb)
        assert cursor == 3_439_960

    def test_returnsNoneWhenSyncLogEmpty(self, tmp_path: Path) -> None:
        dbPath = tmp_path / 'empty.db'
        conn = sqlite3.connect(dbPath)
        conn.executescript(
            """
            CREATE TABLE sync_log (
                table_name TEXT PRIMARY KEY,
                last_synced_id INTEGER NOT NULL DEFAULT 0,
                last_synced_at TEXT,
                last_batch_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
            );
            """,
        )
        conn.commit()
        conn.close()
        assert tdp.readRealtimeSyncCursor(dbPath) is None


# ================================================================================
# Divergence detection
# ================================================================================

class TestDivergenceDetected:
    def test_allGreenReturnsEmpty(self) -> None:
        report = tdp.StateReport(
            piTargets=[
                tdp.TableTarget(
                    name='realtime_data',
                    drive1RealRows=5,
                    hasDataSourceColumn=True,
                    hasDriveIdColumn=True,
                ),
            ],
            serverTargets=[
                tdp.TableTarget(
                    name='realtime_data',
                    drive1RealRows=5,
                    hasDataSourceColumn=True,
                    hasDriveIdColumn=True,
                ),
            ],
            piRealtimeSyncCursor=3_439_960,
            piDriveCounterLast=3,
            serverHasDriveCounter=True,
            serverDriveCounterLast=3,
            fixtureShaMatches=True,
            fixtureSha=_EXPECTED_FIXTURE_SHA,
            fixtureBytes=188_416,
            aiRecsWindowCount=0,
            calibSessionsWindowCount=0,
        )
        assert tdp.divergenceDetected(report) == []

    def test_syncGateBelowThresholdReturnsReason(self) -> None:
        report = tdp.StateReport(
            piTargets=[],
            serverTargets=[],
            piRealtimeSyncCursor=149,  # the pre-deploy cursor
            piDriveCounterLast=3,
            serverHasDriveCounter=True,
            serverDriveCounterLast=3,
            fixtureShaMatches=True,
            fixtureSha=_EXPECTED_FIXTURE_SHA,
            fixtureBytes=188_416,
            aiRecsWindowCount=0,
            calibSessionsWindowCount=0,
        )
        reasons = tdp.divergenceDetected(report)
        assert any('sync' in r.lower() for r in reasons)

    def test_syncCursorMissingReturnsReason(self) -> None:
        report = tdp.StateReport(
            piTargets=[],
            serverTargets=[],
            piRealtimeSyncCursor=None,
            piDriveCounterLast=3,
            serverHasDriveCounter=True,
            serverDriveCounterLast=3,
            fixtureShaMatches=True,
            fixtureSha=_EXPECTED_FIXTURE_SHA,
            fixtureBytes=188_416,
            aiRecsWindowCount=0,
            calibSessionsWindowCount=0,
        )
        reasons = tdp.divergenceDetected(report)
        assert any('sync' in r.lower() for r in reasons)

    def test_fixtureHashMismatchReturnsReason(self) -> None:
        report = tdp.StateReport(
            piTargets=[],
            serverTargets=[],
            piRealtimeSyncCursor=3_439_960,
            piDriveCounterLast=3,
            serverHasDriveCounter=True,
            serverDriveCounterLast=3,
            fixtureShaMatches=False,
            fixtureSha='deadbeef',
            fixtureBytes=0,
            aiRecsWindowCount=0,
            calibSessionsWindowCount=0,
        )
        reasons = tdp.divergenceDetected(report)
        assert any('fixture' in r.lower() for r in reasons)

    def test_orphanRowsInWindowReturnReason(self) -> None:
        # ai_recommendations or calibration_sessions in the window halts
        # per stopCondition #2 -- surface to operator, do not delete.
        report = tdp.StateReport(
            piTargets=[],
            serverTargets=[],
            piRealtimeSyncCursor=3_439_960,
            piDriveCounterLast=3,
            serverHasDriveCounter=True,
            serverDriveCounterLast=3,
            fixtureShaMatches=True,
            fixtureSha=_EXPECTED_FIXTURE_SHA,
            fixtureBytes=188_416,
            aiRecsWindowCount=2,  # orphans found
            calibSessionsWindowCount=0,
        )
        reasons = tdp.divergenceDetected(report)
        assert any('orphan' in r.lower() or 'ai_recommendations' in r for r in reasons)

    def test_driveCounterBelowTargetReturnsReason(self) -> None:
        # If counter regressed below 3, refuse (would mint a new drive_id=2,3
        # that conflicts with Drive 2/3 already present).
        report = tdp.StateReport(
            piTargets=[],
            serverTargets=[],
            piRealtimeSyncCursor=3_439_960,
            piDriveCounterLast=1,  # regressed
            serverHasDriveCounter=True,
            serverDriveCounterLast=3,
            fixtureShaMatches=True,
            fixtureSha=_EXPECTED_FIXTURE_SHA,
            fixtureBytes=188_416,
            aiRecsWindowCount=0,
            calibSessionsWindowCount=0,
        )
        reasons = tdp.divergenceDetected(report)
        assert any('drive_counter' in r.lower() for r in reasons)


# ================================================================================
# Local DELETE executor (synthetic SQLite, real query planner)
# ================================================================================

class TestExecuteLocalTruncate:
    """Validate the DELETE WHERE drive_id=1 AND data_source='real' is correct."""

    def test_deletesOnlyDrive1RealRows(self, syntheticPiDb: Path) -> None:
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        # No more drive_id=1 real rows.
        n = conn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id=1 AND data_source='real'",
        ).fetchone()[0]
        assert n == 0
        # connection_log drive_id=1 real also gone.
        n = conn.execute(
            "SELECT COUNT(*) FROM connection_log "
            "WHERE drive_id=1 AND data_source='real'",
        ).fetchone()[0]
        assert n == 0
        conn.close()

    def test_preservesDrive3RealRows(self, syntheticPiDb: Path) -> None:
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        n = conn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id=3 AND data_source='real'",
        ).fetchone()[0]
        assert n == 2  # all drive_id=3 rows preserved
        conn.close()

    def test_preservesNullDriveIdRows(self, syntheticPiDb: Path) -> None:
        # US-233 territory -- US-227 does not touch NULL drive_id rows.
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        n = conn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id IS NULL AND data_source='real'",
        ).fetchone()[0]
        assert n == 3
        conn.close()

    def test_preservesDrive1NonRealRows(self, syntheticPiDb: Path) -> None:
        # data_source='physics_sim' on drive_id=1 must not be touched
        # (story scope is strict: data_source='real' only).
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        n = conn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id=1 AND data_source!='real'",
        ).fetchone()[0]
        assert n == 1
        conn.close()

    def test_advancesDriveCounterToTarget(self, syntheticPiDb: Path) -> None:
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        v = conn.execute(
            'SELECT last_drive_id FROM drive_counter WHERE id=1',
        ).fetchone()[0]
        assert v == 3
        conn.close()

    def test_doesNotRegressDriveCounter(self, syntheticPiDb: Path) -> None:
        # If counter is already > target (e.g., later drives shipped), do
        # NOT regress it. Idempotency invariant.
        conn = sqlite3.connect(syntheticPiDb)
        conn.execute(
            'UPDATE drive_counter SET last_drive_id=5 WHERE id=1',
        )
        conn.commit()
        conn.close()
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        v = conn.execute(
            'SELECT last_drive_id FROM drive_counter WHERE id=1',
        ).fetchone()[0]
        assert v == 5  # not regressed
        conn.close()

    def test_idempotentReRunOnTruncatedDb(self, syntheticPiDb: Path) -> None:
        targets = tdp.enumerateTargetTables(syntheticPiDb)
        tdp.executeLocalTruncate(syntheticPiDb, targets, driveCounterTarget=3)
        # Second run on the now-empty drive_id=1 set must be a no-op.
        targetsAfter = tdp.enumerateTargetTables(syntheticPiDb)
        # 0 rows to delete now.
        rt = next(t for t in targetsAfter if t.name == 'realtime_data')
        assert rt.drive1RealRows == 0
        # Re-run: no exception, no row-count change anywhere.
        tdp.executeLocalTruncate(syntheticPiDb, targetsAfter, driveCounterTarget=3)
        conn = sqlite3.connect(syntheticPiDb)
        rtRows = conn.execute(
            'SELECT COUNT(*) FROM realtime_data',
        ).fetchone()[0]
        # 1 physics_sim drive_id=1 + 2 drive_id=3 + 3 NULL = 6.
        assert rtRows == 6
        conn.close()

    def test_runsTransactionally(self, syntheticPiDb: Path) -> None:
        # Force an error halfway through and assert nothing committed.
        # We do this by passing a target with a nonexistent table name
        # in the middle; the BEGIN/COMMIT wrap should roll the partial
        # work back.
        targets = list(tdp.enumerateTargetTables(syntheticPiDb))
        # Inject a bogus target between two real ones.
        bogus = tdp.TableTarget(
            name='nonexistent_table_xyz',
            drive1RealRows=1,
            hasDataSourceColumn=True,
            hasDriveIdColumn=True,
        )
        injected = [targets[0], bogus, *targets[1:]]
        with pytest.raises(Exception):
            tdp.executeLocalTruncate(
                syntheticPiDb, injected, driveCounterTarget=3,
            )
        # Pre-existing drive_id=1 real rows still there (rolled back).
        conn = sqlite3.connect(syntheticPiDb)
        n = conn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id=1 AND data_source='real'",
        ).fetchone()[0]
        assert n == 5  # rollback intact
        conn.close()


# ================================================================================
# Fixture hash invariance (real fixture file)
# ================================================================================

class TestFixtureHashIntegrity:
    """Run against the real fixture; truncate must NEVER touch it."""

    def test_realFixtureHashMatchesPin(self, realFixturePath: Path) -> None:
        if not realFixturePath.exists():
            pytest.skip('fixture not present in this checkout')
        matches, sha, nbytes = tdp.verifyFixtureHash(_PROJECT_ROOT)
        assert matches is True
        assert sha == _EXPECTED_FIXTURE_SHA
        assert nbytes == 188_416


# ================================================================================
# Sentinel + CLI safety gates
# ================================================================================

class TestCli:
    """The --execute flag is gated behind a successful prior --dry-run."""

    def test_dryRunWritesSentinel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Build a real Pi DB the script can scan; stub the server-side bits.
        piDb = tmp_path / 'pi.db'
        conn = sqlite3.connect(piDb)
        conn.executescript(
            """
            CREATE TABLE realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                data_source TEXT NOT NULL DEFAULT 'real', drive_id INTEGER
            );
            CREATE TABLE drive_counter (
                id INTEGER PRIMARY KEY CHECK (id=1),
                last_drive_id INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO drive_counter VALUES (1, 3);
            CREATE TABLE sync_log (
                table_name TEXT PRIMARY KEY,
                last_synced_id INTEGER NOT NULL DEFAULT 0,
                last_synced_at TEXT, last_batch_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
            );
            INSERT INTO sync_log VALUES
              ('realtime_data', 3439960, '2026-04-27T13:35:16Z', 'b1', 'ok');
            """,
        )
        conn.commit()
        conn.close()

        # Stub: when run with --local, the script must not require server
        # connectivity. This is the test mode for offline exercise.
        rc = tdp.main([
            '--dry-run',
            '--local',
            '--db', str(piDb),
            '--project-root', str(_PROJECT_ROOT),
            '--sentinel-dir', str(tmp_path),
        ])
        assert rc == 0
        assert (tmp_path / tdp.DRY_RUN_SENTINEL_NAME).exists()

    def test_executeWithoutSentinelRefuses(
        self, tmp_path: Path,
    ) -> None:
        piDb = tmp_path / 'pi.db'
        conn = sqlite3.connect(piDb)
        conn.executescript(
            """
            CREATE TABLE realtime_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                data_source TEXT NOT NULL DEFAULT 'real', drive_id INTEGER
            );
            CREATE TABLE drive_counter (
                id INTEGER PRIMARY KEY CHECK (id=1),
                last_drive_id INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO drive_counter VALUES (1, 3);
            CREATE TABLE sync_log (
                table_name TEXT PRIMARY KEY,
                last_synced_id INTEGER NOT NULL DEFAULT 0,
                last_synced_at TEXT, last_batch_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
            );
            INSERT INTO sync_log VALUES
              ('realtime_data', 3439960, '2026-04-27T13:35:16Z', 'b1', 'ok');
            """,
        )
        conn.commit()
        conn.close()
        # No sentinel file -> --execute must refuse.
        rc = tdp.main([
            '--execute',
            '--local',
            '--db', str(piDb),
            '--project-root', str(_PROJECT_ROOT),
            '--sentinel-dir', str(tmp_path),
        ])
        assert rc != 0

    def test_executeAfterDryRunRunsTruncate(
        self, syntheticPiDb: Path, tmp_path: Path,
    ) -> None:
        # Dry-run first to drop the sentinel, then execute.
        rc1 = tdp.main([
            '--dry-run',
            '--local',
            '--db', str(syntheticPiDb),
            '--project-root', str(_PROJECT_ROOT),
            '--sentinel-dir', str(tmp_path),
        ])
        assert rc1 == 0
        rc2 = tdp.main([
            '--execute',
            '--local',
            '--db', str(syntheticPiDb),
            '--project-root', str(_PROJECT_ROOT),
            '--sentinel-dir', str(tmp_path),
            '--no-backup',  # synthetic DB; backup is exercised in live runs
        ])
        assert rc2 == 0
        conn = sqlite3.connect(syntheticPiDb)
        n = conn.execute(
            "SELECT COUNT(*) FROM realtime_data "
            "WHERE drive_id=1 AND data_source='real'",
        ).fetchone()[0]
        assert n == 0
        conn.close()

    def test_dryRunAndExecuteAreMutuallyExclusive(self) -> None:
        with pytest.raises(SystemExit):
            tdp.main(['--dry-run', '--execute'])

    def test_neitherFlagExits(self) -> None:
        with pytest.raises(SystemExit):
            tdp.main([])
