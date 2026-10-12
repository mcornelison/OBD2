################################################################################
# File Name: test_purge_outage_telemetry.py
# Purpose/Description: TDD tests for scripts/purge_outage_telemetry.py (US-774).
#                      Pins the backup-then-re-read gate on each tier, the rule
#                      that a server timestamp delete always carries its
#                      event_type filter, the kept server event types, dry-run
#                      leaving both copies unchanged, drives 3-26 unchanged by an
#                      apply, and the drive-2 / recorded-scope stop conditions.
# Author: Rex (US-774)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-774) | Initial -- outage telemetry + drive 2 purge tests.
# ================================================================================
################################################################################

"""TDD tests for the US-774 outage-telemetry and drive 2 purge script."""

from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'purge_outage_telemetry.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location('purge_outage_telemetry', _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['purge_outage_telemetry'] = mod
    spec.loader.exec_module(mod)
    return mod


pot = _loadScript()

_KEPT_TYPES = ('connect_success', 'drive_start', 'drive_end', 'reconnect')
_RETRY_TYPES = ('connect_attempt', 'connect_failure', 'disconnect')
_REAL_DRIVES = range(3, 27)  # drives 3 through 26

# ================================================================================
# Fixtures: minimal copies of each tier
# ================================================================================

_DDL = (
    'CREATE TABLE connection_log ('
    ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
    ' timestamp DATETIME NOT NULL,'
    ' event_type TEXT NOT NULL,'
    ' drive_id INTEGER)',
    'CREATE TABLE realtime_data ('
    ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
    ' timestamp DATETIME NOT NULL,'
    ' parameter_name TEXT NOT NULL,'
    ' value REAL NOT NULL,'
    " data_source TEXT NOT NULL DEFAULT 'real',"
    ' drive_id INTEGER)',
    'CREATE TABLE drive_summary ('
    ' drive_id INTEGER PRIMARY KEY,'
    ' drive_start_timestamp DATETIME)',
    'CREATE TABLE statistics ('
    ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
    ' parameter_name TEXT NOT NULL,'
    ' drive_id INTEGER)',
)


def _exec(path: Path, sql: str, rows: list[tuple] | None = None) -> None:
    conn = sqlite3.connect(path)
    try:
        if rows is None:
            conn.execute(sql)
        else:
            conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def _scalar(path: Path, sql: str) -> int:
    conn = sqlite3.connect(path)
    try:
        return int(conn.execute(sql).fetchone()[0])
    finally:
        conn.close()


def _driveCounts(path: Path) -> dict[int, int]:
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute(
            'SELECT drive_id, COUNT(*) FROM realtime_data'
            ' WHERE drive_id BETWEEN 3 AND 26 GROUP BY drive_id',
        ).fetchall())
    finally:
        conn.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _createTier(path: Path) -> None:
    for ddl in _DDL:
        _exec(path, ddl)


def _seedCommon(path: Path) -> None:
    """Rows both tiers hold: April/May link events, drives 2-26, June events."""
    events = []
    for eventType in (*_RETRY_TYPES, *_KEPT_TYPES):
        events.append(('2026-04-20T10:00:00Z', eventType, None))
        events.append(('2026-05-31 23:59:59', eventType, None))  # legacy format
        events.append(('2026-06-01T00:00:00Z', eventType, None))  # cutoff: kept
    for drive in _REAL_DRIVES:
        events.append(('2026-05-10T09:00:00Z', 'drive_start', drive))
        events.append(('2026-05-10T09:30:00Z', 'drive_end', drive))
    _exec(path, 'INSERT INTO connection_log (timestamp, event_type, drive_id)'
                ' VALUES (?, ?, ?)', events)

    realtime = [('2026-05-10T09:01:00Z', 'RPM', 800.0, 'real', drive)
                for drive in _REAL_DRIVES for _ in range(drive)]
    _exec(path, 'INSERT INTO realtime_data (timestamp, parameter_name, value,'
                ' data_source, drive_id) VALUES (?, ?, ?, ?, ?)', realtime)
    _exec(path, 'INSERT INTO drive_summary (drive_id, drive_start_timestamp) VALUES (?, ?)',
          [(drive, '2026-05-10T09:00:00Z') for drive in _REAL_DRIVES])


@pytest.fixture
def piDb(tmp_path: Path) -> Path:
    path = tmp_path / 'pi' / 'obd.db'
    path.parent.mkdir()
    _createTier(path)
    _seedCommon(path)
    _exec(path, 'INSERT INTO connection_log (timestamp, event_type, drive_id)'
                ' VALUES (?, ?, ?)',
          [('2026-04-02T08:00:00Z', 'drive_start', 2), ('2026-04-02T08:10:00Z', 'drive_end', 2)])
    _exec(path, 'INSERT INTO realtime_data (timestamp, parameter_name, value,'
                ' data_source, drive_id) VALUES (?, ?, ?, ?, ?)',
          [('2026-04-02T08:01:00Z', 'RPM', 900.0, 'physics_sim', 2)] * 5)
    _exec(path, "INSERT INTO drive_summary (drive_id, drive_start_timestamp)"
                " VALUES (2, '2026-04-02T08:00:00Z')")
    return path


@pytest.fixture
def serverDb(tmp_path: Path) -> Path:
    path = tmp_path / 'server' / 'obd2db.sqlite'
    path.parent.mkdir()
    _createTier(path)
    _seedCommon(path)
    # The two drive 2 markers, stamped after the cutoff so only drive_id selects them.
    _exec(path, 'INSERT INTO connection_log (timestamp, event_type, drive_id)'
                ' VALUES (?, ?, ?)',
          [('2026-06-02T08:00:00Z', 'drive_start', 2), ('2026-06-02T08:10:00Z', 'drive_end', 2)])
    return path


def _url(path: Path) -> str:
    return f'sqlite:///{path.as_posix()}'


def _args(piDb: Path, serverDb: Path, *extra: str) -> list[str]:
    return ['--pi-db', str(piDb), '--server-url', _url(serverDb),
            '--backup-dir', str(piDb.parent.parent / 'backups'), *extra]


# ================================================================================
# Generated SQL
# ================================================================================

class TestServerStatements:
    def test_everyServerTimestampStatement_carriesTheEventTypeFilter(self):
        statements = pot.buildServerStatements()

        timestamped = [s for s in statements if 'timestamp' in s.deleteSql]
        assert timestamped, 'the server plan must hold its pre-June statement'
        for statement in timestamped:
            assert 'event_type IN (' in statement.deleteSql, statement.deleteSql

    def test_theDriveTwoStatement_isTheOneExemptionAndCarriesNoTimestamp(self):
        exempt = [s for s in pot.buildServerStatements() if 'event_type' not in s.deleteSql]

        assert [s.deleteSql for s in exempt] == ['DELETE FROM connection_log WHERE drive_id = 2']

    def test_aServerTimestampPredicateWithoutEventTypes_cannotBeProduced(self):
        with pytest.raises(ValueError, match='event_type'):
            pot.timestampPredicate('server', ())

    def test_serverTimestampStatement_namesOnlyTheRetryTypes(self):
        (statement,) = [s for s in pot.buildServerStatements() if 'timestamp' in s.deleteSql]

        assert statement.deleteSql == (
            "DELETE FROM connection_log WHERE timestamp < '2026-06-01'"
            " AND event_type IN ('connect_attempt', 'connect_failure', 'disconnect')"
        )
        for kept in _KEPT_TYPES:
            assert f"'{kept}'" not in statement.deleteSql

    @pytest.mark.parametrize('eventType', _KEPT_TYPES)
    def test_serverTimestampStatement_neverMatchesAKeptType(self, tmp_path: Path, eventType):
        path = tmp_path / 'server.db'
        _createTier(path)
        _exec(path, 'INSERT INTO connection_log (timestamp, event_type) VALUES (?, ?)',
              [('2026-04-01T00:00:00Z', eventType), ('2026-05-31 12:00:00', eventType)])
        (statement,) = [s for s in pot.buildServerStatements() if 'timestamp' in s.deleteSql]

        assert _scalar(path, f'SELECT COUNT(*) FROM connection_log WHERE {statement.where}') == 0

    def test_piPreJuneStatement_deletesEveryEventTypeByRuledScope(self):
        (statement,) = [s for s in pot.buildPiStatements() if s.table == 'connection_log']

        assert statement.deleteSql == "DELETE FROM connection_log WHERE timestamp < '2026-06-01'"


# ================================================================================
# Dry run
# ================================================================================

class TestDryRun:
    def test_dryRun_reportsEachTierSeparatelyAndChangesNeitherDatabase(
        self, piDb: Path, serverDb: Path, capsys,
    ):
        piHash, serverHash = _sha256(piDb), _sha256(serverDb)

        rc = pot.main(_args(piDb, serverDb))

        out = capsys.readouterr().out
        assert rc == pot.EXIT_OK
        assert _sha256(piDb) == piHash
        assert _sha256(serverDb) == serverHash
        # Pi: 7 types x 2 pre-June + 24x2 drive markers + 2 drive 2 markers.
        assert "[DRY-RUN] pi connection_log WHERE timestamp < '2026-06-01' -> 64 row(s)" in out
        assert '[DRY-RUN] pi realtime_data WHERE drive_id = 2 -> 5 row(s)' in out
        assert '[DRY-RUN] pi drive_summary WHERE drive_id = 2 -> 1 row(s)' in out
        assert '[DRY-RUN] server connection_log WHERE timestamp' in out
        assert "'disconnect') -> 6 row(s)" in out
        assert '[DRY-RUN] server connection_log WHERE drive_id = 2 -> 2 row(s)' in out
        assert not list((piDb.parent.parent / 'backups').glob('*'))

    def test_dryRun_printsTheServerKeptTypeCounts(self, piDb: Path, serverDb: Path, capsys):
        pot.main(_args(piDb, serverDb))

        out = capsys.readouterr().out
        assert "server keep before 2026-06-01: connect_success=2" in out
        assert "drive_start=26" in out

    def test_onlyOneTier_runsThatTierAlone(self, piDb: Path, capsys):
        rc = pot.main(['--pi-db', str(piDb)])

        out = capsys.readouterr().out
        assert rc == pot.EXIT_OK
        assert '[DRY-RUN] pi realtime_data' in out
        assert 'server' not in out

    def test_noTier_exitsNonZero(self):
        assert pot.main([]) != pot.EXIT_OK

    def test_missingPiDb_exitsNonZero(self, tmp_path: Path):
        assert pot.main(['--pi-db', str(tmp_path / 'absent.db')]) == pot.EXIT_MISSING_INPUT


# ================================================================================
# Apply
# ================================================================================

class TestApply:
    def test_apply_deletesExactlyTheRuledScopeOnBothTiers(self, piDb: Path, serverDb: Path):
        rc = pot.main(_args(piDb, serverDb, '--apply'))

        assert rc == pot.EXIT_OK
        assert _scalar(piDb, "SELECT COUNT(*) FROM connection_log WHERE timestamp < '2026-06-01'") == 0
        assert _scalar(piDb, 'SELECT COUNT(*) FROM connection_log') == 7
        assert _scalar(piDb, 'SELECT COUNT(*) FROM realtime_data WHERE drive_id = 2') == 0
        assert _scalar(piDb, 'SELECT COUNT(*) FROM drive_summary WHERE drive_id = 2') == 0
        for eventType in _RETRY_TYPES:
            assert _scalar(serverDb, 'SELECT COUNT(*) FROM connection_log WHERE'
                                     f" event_type = '{eventType}'") == 1  # the June row
        for eventType in ('connect_success', 'reconnect'):
            assert _scalar(serverDb, 'SELECT COUNT(*) FROM connection_log WHERE'
                                     f" event_type = '{eventType}'") == 3
        assert _scalar(serverDb, "SELECT COUNT(*) FROM connection_log WHERE event_type"
                                 " IN ('drive_start','drive_end') AND drive_id BETWEEN 3 AND 26") == 48
        assert _scalar(serverDb, 'SELECT COUNT(*) FROM connection_log WHERE drive_id = 2') == 0

    def test_apply_leavesRealtimeCountsForDrives3To26Identical(
        self, piDb: Path, serverDb: Path,
    ):
        before = (_driveCounts(piDb), _driveCounts(serverDb))

        pot.main(_args(piDb, serverDb, '--apply'))

        assert (_driveCounts(piDb), _driveCounts(serverDb)) == before
        assert len(before[1]) == len(_REAL_DRIVES)

    def test_apply_writesReadableBackupsOfEachTier(self, piDb: Path, serverDb: Path):
        pot.main(_args(piDb, serverDb, '--apply'))

        backupDir = piDb.parent.parent / 'backups'
        (piBackup,) = backupDir.glob('obd.db.bak-us774-*')
        (serverBackup,) = backupDir.glob('server-connection_log.bak-us774-*.jsonl')
        assert _scalar(piBackup, 'SELECT COUNT(*) FROM realtime_data WHERE drive_id = 2') == 5
        rows = pot.readServerBackup(serverBackup)
        assert len(rows) == 7 * 3 + 24 * 2 + 2

    def test_apply_thenDryRun_reportsNothingLeft(self, piDb: Path, serverDb: Path, capsys):
        pot.main(_args(piDb, serverDb, '--apply'))
        capsys.readouterr()

        rc = pot.main(_args(piDb, serverDb))

        out = capsys.readouterr().out
        assert rc == pot.EXIT_OK
        assert '-> 0 row(s)' in out
        assert '-> 1 row(s)' not in out

    @pytest.mark.parametrize('failingTier', ['pi', 'server'])
    def test_backupThatCannotBeReRead_exitsNonZeroAndDeletesNothing(
        self, piDb: Path, serverDb: Path, monkeypatch, failingTier: str,
    ):
        realPi, realServer = pot.verifyPiBackup, pot.verifyServerBackup

        def _unreadable(*args, **kwargs) -> None:
            raise pot.BackupVerificationError('cannot re-read the backup')

        monkeypatch.setattr(pot, 'verifyPiBackup', _unreadable if failingTier == 'pi' else realPi)
        monkeypatch.setattr(
            pot, 'verifyServerBackup', _unreadable if failingTier == 'server' else realServer,
        )
        piHash, serverHash = _sha256(piDb), _sha256(serverDb)

        rc = pot.main(_args(piDb, serverDb, '--apply'))

        assert rc == pot.EXIT_BACKUP_FAILED
        assert _sha256(piDb) == piHash
        assert _sha256(serverDb) == serverHash

    def test_verifyServerBackup_rejectsATruncatedFile(self, serverDb: Path, tmp_path: Path):
        engine = pot.makeEngine(_url(serverDb))
        statements = pot.buildServerStatements()
        try:
            with engine.connect() as conn:
                backup, digest = pot.backupServerTables(conn, statements, tmp_path)
                lines = backup.read_text(encoding='utf-8').splitlines()
                backup.write_text('\n'.join(lines[:-1]) + '\n', encoding='utf-8')

                with pytest.raises(pot.BackupVerificationError):
                    pot.verifyServerBackup(conn, statements, backup, digest)
        finally:
            engine.dispose()

    def test_verifyPiBackup_rejectsACopyWhoseCountsDiffer(self, piDb: Path, tmp_path: Path):
        other = tmp_path / 'other.db'
        _createTier(other)

        with pytest.raises(pot.BackupVerificationError):
            pot.verifyPiBackup(other, pot.buildPiStatements(), expected=[64, 5, 1])


# ================================================================================
# Stop conditions
# ================================================================================

class TestStopConditions:
    def test_driveTwoRowsInAnotherTable_stopsAndDeletesNothing(
        self, piDb: Path, serverDb: Path, capsys,
    ):
        _exec(piDb, "INSERT INTO statistics (parameter_name, drive_id) VALUES ('RPM', 2)")
        piHash = _sha256(piDb)

        rc = pot.main(_args(piDb, serverDb, '--apply'))

        err = capsys.readouterr().err
        assert rc == pot.EXIT_SCOPE_SURPRISE
        assert 'statistics' in err
        assert _sha256(piDb) == piHash
        assert not list((piDb.parent.parent / 'backups').glob('*'))

    def test_serverDriveTwoRealtimeRows_areOutsideTheServerScopeAndStop(
        self, piDb: Path, serverDb: Path, capsys,
    ):
        _exec(serverDb, "INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id)"
                        " VALUES ('2026-04-02T08:01:00Z', 'RPM', 1.0, 2)")

        rc = pot.main(_args(piDb, serverDb, '--apply'))

        assert rc == pot.EXIT_SCOPE_SURPRISE
        assert 'server realtime_data' in capsys.readouterr().err

    def test_piDriveTwoRealtimeRowThatIsNotSimulated_stops(
        self, piDb: Path, serverDb: Path, capsys,
    ):
        _exec(piDb, "UPDATE realtime_data SET data_source = 'real'"
                    " WHERE id = (SELECT MIN(id) FROM realtime_data WHERE drive_id = 2)")

        rc = pot.main(_args(piDb, serverDb, '--apply'))

        assert rc == pot.EXIT_SCOPE_SURPRISE
        assert 'physics_sim' in capsys.readouterr().err

    def test_countAboveTheRecordedScope_stopsAndReportsTheObservedCount(
        self, piDb: Path, serverDb: Path, monkeypatch, capsys,
    ):
        monkeypatch.setitem(pot.RECORDED_SCOPE, ('pi', 'realtime_data'), 4)

        rc = pot.main(_args(piDb, serverDb, '--apply'))

        err = capsys.readouterr().err
        assert rc == pot.EXIT_SCOPE_SURPRISE
        assert 'observed 5' in err and 'recorded 4' in err
        assert _scalar(piDb, 'SELECT COUNT(*) FROM realtime_data WHERE drive_id = 2') == 5

    def test_aDeleteThatTouchesAKeptRow_rollsBackTheTier(
        self, serverDb: Path, monkeypatch,
    ):
        from sqlalchemy import text

        realDelete = pot._executeDeletes
        serverHash = _sha256(serverDb)

        def _widerDelete(conn, statements):  # noqa: ANN202 -- simulates a wider delete
            deleted = realDelete(conn, statements)
            conn.execute(text("DELETE FROM connection_log WHERE event_type = 'connect_success'"))
            return deleted

        monkeypatch.setattr(pot, '_executeDeletes', _widerDelete)

        rc = pot.main(['--server-url', _url(serverDb),
                       '--backup-dir', str(serverDb.parent / 'backups'), '--apply'])

        assert rc == pot.EXIT_INVARIANT_BROKEN
        assert _sha256(serverDb) == serverHash
