################################################################################
# File Name: test_apply_server_migrations.py
# Purpose/Description: Unit tests for scripts/apply_server_migrations.py (US-209).
#                      Uses an injectable FakeRunner so the tests never touch a
#                      network.  Covers: address + DSN loader reuse, schema
#                      probes (column / table / index), full schema scan, plan
#                      generation across clean/partial/fully-migrated states,
#                      report rendering, backup safety gates, DDL execution
#                      timing guards, sentinel round-trip, and the --execute
#                      CLI refusal path.
#
# Author: Agent3 (Ralph)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Agent3       | Initial -- TDD coverage for US-209 script.
# ================================================================================
################################################################################

"""TDD tests for the US-209 apply_server_migrations script."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'apply_server_migrations.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'apply_server_migrations', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['apply_server_migrations'] = mod
    spec.loader.exec_module(mod)
    return mod


asm = _loadScript()


# ================================================================================
# FakeRunner -- scripted subprocess responses keyed by needle
# ================================================================================

@dataclass
class FakeRunner:
    """Minimal scripted runner matching the CommandRunner Protocol."""

    responses: list[tuple[str, subprocess.CompletedProcess[str]]] = field(
        default_factory=list,
    )
    calls: list[dict] = field(default_factory=list)
    matcher: Callable[[Sequence[str], str], bool] | None = None

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


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr,
    )


def _fail(
    stderr: str = 'boom', rc: int = 1,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout='', stderr=stderr,
    )


# ================================================================================
# Constants parity -- if Pi-side scope moves, US-209 must move with it
# ================================================================================

class TestConstantsParity:
    def test_captureTables_matchPiCaptureTables(self):
        from src.pi.obdii.data_source import CAPTURE_TABLES as pi_capture
        assert set(asm.CAPTURE_TABLES) == set(pi_capture), (
            'CAPTURE_TABLES drifted from Pi-side data_source.py -- '
            f'Pi={sorted(pi_capture)} server={sorted(asm.CAPTURE_TABLES)}'
        )

    def test_driveIdTables_matchPiDriveIdTables(self):
        from src.pi.obdii.drive_id import DRIVE_ID_TABLES as pi_drive_tables
        assert set(asm.DRIVE_ID_TABLES) == set(pi_drive_tables), (
            'DRIVE_ID_TABLES drifted from Pi-side drive_id.py -- '
            f'Pi={sorted(pi_drive_tables)} server={sorted(asm.DRIVE_ID_TABLES)}'
        )

    def test_driveCounterName_matchesPi(self):
        from src.pi.obdii.drive_id import DRIVE_COUNTER_TABLE as pi_counter
        assert asm.DRIVE_COUNTER_TABLE == pi_counter

    def test_dataSourceDdl_containsAllEnumValues(self):
        ddl = asm.DATA_SOURCE_COLUMN_DDL
        for value in ('real', 'replay', 'physics_sim', 'fixture'):
            assert f"'{value}'" in ddl

    def test_dataSourceDdl_hasNotNullAndDefault(self):
        ddl = asm.DATA_SOURCE_COLUMN_DDL
        assert 'NOT NULL' in ddl
        assert "DEFAULT 'real'" in ddl
        assert 'CHECK' in ddl

    def test_driveIdDdl_isBigintNullable(self):
        assert asm.DRIVE_ID_COLUMN_DDL == 'drive_id BIGINT NULL'


# ================================================================================
# loadAddresses -- server fields only
# ================================================================================

class TestLoadAddresses:
    def test_loadAddresses_happyPath_parsesServerFromBash(self, tmp_path: Path):
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
        envBlob = (
            'SERVER_HOST=10.2.2.2\nSERVER_USER=bob\nPI_HOST=ignored\n'
        )
        runner = FakeRunner(responses=[('bash', _ok(stdout=envBlob))])
        addrs = asm.loadAddresses(addresses, runner=runner)
        assert addrs.serverHost == '10.2.2.2'
        assert addrs.serverUser == 'bob'

    def test_loadAddresses_missingFile_raises(self, tmp_path: Path):
        with pytest.raises(asm.MigrationError, match='not found'):
            asm.loadAddresses(tmp_path / 'nope.sh', runner=FakeRunner())

    def test_loadAddresses_missingServerVars_raises(self, tmp_path: Path):
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('x', encoding='utf-8')
        runner = FakeRunner(responses=[('bash', _ok(stdout='PI_HOST=1.1.1.1\n'))])
        with pytest.raises(asm.MigrationError, match='missing required vars'):
            asm.loadAddresses(addresses, runner=runner)


# ================================================================================
# loadServerCreds
# ================================================================================

class TestLoadServerCreds:
    def _addrs(self) -> asm.HostAddresses:
        return asm.HostAddresses(serverHost='10.2.2.2', serverUser='b')

    def test_loadServerCreds_parseAiomysqlDsn(self):
        dsn = 'DATABASE_URL=mysql+aiomysql://u:p@localhost/dbx\n'
        runner = FakeRunner(responses=[('ssh', _ok(stdout=dsn))])
        creds = asm.loadServerCreds(self._addrs(), runner=runner)
        assert creds.dbUser == 'u'
        assert creds.dbPassword == 'p'
        assert creds.dbName == 'dbx'

    def test_loadServerCreds_malformed_raises(self):
        runner = FakeRunner(
            responses=[('ssh', _ok(stdout='DATABASE_URL=garbage\n'))],
        )
        with pytest.raises(asm.MigrationError, match='malformed'):
            asm.loadServerCreds(self._addrs(), runner=runner)

    def test_loadServerCreds_sshFail_raises(self):
        runner = FakeRunner(responses=[('ssh', _fail())])
        with pytest.raises(asm.MigrationError, match='DATABASE_URL'):
            asm.loadServerCreds(self._addrs(), runner=runner)


# ================================================================================
# Schema probes
# ================================================================================

def _addrs() -> asm.HostAddresses:
    return asm.HostAddresses(serverHost='10.2.2.2', serverUser='u')


def _creds() -> asm.ServerCreds:
    return asm.ServerCreds(dbUser='u', dbPassword='p', dbName='obd2db')


class TestProbeServerColumns:
    def test_probeServerColumns_parsesColumnList(self):
        cols = 'id\nsource_id\ntimestamp\nparameter_name\n'
        runner = FakeRunner(responses=[('information_schema.COLUMNS', _ok(stdout=cols))])
        result = asm.probeServerColumns(_addrs(), _creds(), 'realtime_data', runner)
        assert result == ['id', 'source_id', 'timestamp', 'parameter_name']

    def test_probeServerColumns_probeFailure_raises(self):
        runner = FakeRunner(responses=[('mysql', _fail(stderr='auth denied'))])
        with pytest.raises(asm.SchemaProbeError, match='auth denied'):
            asm.probeServerColumns(_addrs(), _creds(), 'realtime_data', runner)

    def test_probeServerColumns_tableMissing_returnsEmpty(self):
        # When TABLE_NAME matches nothing, information_schema returns zero rows.
        runner = FakeRunner(
            responses=[('information_schema.COLUMNS', _ok(stdout=''))],
        )
        result = asm.probeServerColumns(_addrs(), _creds(), 'nope', runner)
        assert result == []


class TestServerTableExists:
    def test_serverTableExists_truthyCount_returnsTrue(self):
        runner = FakeRunner(
            responses=[('information_schema.TABLES', _ok(stdout='1\n'))],
        )
        assert asm.serverTableExists(_addrs(), _creds(), 'realtime_data', runner)

    def test_serverTableExists_zeroCount_returnsFalse(self):
        runner = FakeRunner(
            responses=[('information_schema.TABLES', _ok(stdout='0\n'))],
        )
        assert not asm.serverTableExists(_addrs(), _creds(), 'nope', runner)

    def test_serverTableExists_probeFails_raises(self):
        runner = FakeRunner(responses=[('mysql', _fail())])
        with pytest.raises(asm.SchemaProbeError):
            asm.serverTableExists(_addrs(), _creds(), 'x', runner)


class TestIndexExists:
    def test_indexExists_truthyCount_returnsTrue(self):
        runner = FakeRunner(
            responses=[('information_schema.STATISTICS', _ok(stdout='1\n'))],
        )
        assert asm.indexExists(
            _addrs(), _creds(), 'realtime_data', 'IX_realtime_data_drive_id', runner,
        )

    def test_indexExists_zeroCount_returnsFalse(self):
        runner = FakeRunner(
            responses=[('information_schema.STATISTICS', _ok(stdout='0\n'))],
        )
        assert not asm.indexExists(
            _addrs(), _creds(), 'realtime_data', 'IX_realtime_data_drive_id', runner,
        )


# ================================================================================
# Full schema scan -- multi-response routing
# ================================================================================

def _preMigrationResponder(argv, *, input=None, timeout=None):  # noqa: A002
    """Plain function satisfying CommandRunner Protocol (no class monkey-patch).

    Simulates the chi-srv-01 pre-US-209 state documented in Ralph's
    2026-04-20 US-205 halt note: every in-scope capture table exists but
    lacks data_source + drive_id + index; drive_counter is absent.
    """
    sql = input or ''
    if 'information_schema.TABLES' in sql:
        if "TABLE_NAME='drive_counter'" in sql:
            return _ok(stdout='0\n')
        return _ok(stdout='1\n')
    if 'information_schema.COLUMNS' in sql:
        return _ok(
            stdout='id\nsource_id\nsource_device\nsynced_at\n'
                   'sync_batch_id\ntimestamp\nparameter_name\nvalue\n'
                   'unit\nprofile_id\n',
        )
    if 'information_schema.STATISTICS' in sql:
        return _ok(stdout='0\n')
    return _ok(stdout='')


class TestScanServerSchema:
    def test_scanServerSchema_preMigration_reportsAllGaps(self):
        state = asm.scanServerSchema(_addrs(), _creds(), _preMigrationResponder)

        assert state.hasDriveCounterTable is False
        # Every in-scope table should be probed.
        tableNames = {p.tableName for p in state.tables}
        for t in asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES:
            assert t in tableNames, f'missing probe for {t}'
        # All probes should report ABSENT on data_source/drive_id.
        for probe in state.tables:
            assert probe.exists is True
            assert probe.hasDataSource is False
            assert probe.hasDriveId is False
            assert probe.hasDriveIdIndex is False


# ================================================================================
# Migration planning
# ================================================================================

def _probe(
    name: str, *, ds: bool, did: bool, idx: bool, exists: bool = True,
) -> asm.ColumnProbe:
    return asm.ColumnProbe(
        tableName=name,
        exists=exists,
        hasDataSource=ds,
        hasDriveId=did,
        hasDriveIdIndex=idx,
    )


class TestPlanMigrations:
    def _preMigrationState(self) -> asm.SchemaState:
        probes = []
        union = tuple(dict.fromkeys(asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES))
        for t in union:
            probes.append(_probe(t, ds=False, did=False, idx=False))
        return asm.SchemaState(tables=probes, hasDriveCounterTable=False)

    def _fullyMigratedState(self) -> asm.SchemaState:
        probes = []
        union = tuple(dict.fromkeys(asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES))
        for t in union:
            isCapture = t in asm.CAPTURE_TABLES
            isDrive = t in asm.DRIVE_ID_TABLES
            probes.append(_probe(t, ds=isCapture, did=isDrive, idx=isDrive))
        return asm.SchemaState(tables=probes, hasDriveCounterTable=True)

    def test_planMigrations_fullyMigrated_emitsZeroStatements(self):
        plan = asm.planMigrations(self._fullyMigratedState())
        assert plan.isEmpty is True
        assert plan.statements == []

    def test_planMigrations_preMigration_coversDataSource_driveId_indexes_counter(
        self,
    ):
        plan = asm.planMigrations(self._preMigrationState())
        sqls = [sql for sql, _ in plan.statements]
        # One ADD COLUMN data_source per CAPTURE_TABLES entry.
        for t in asm.CAPTURE_TABLES:
            assert any(
                s.startswith(f'ALTER TABLE {t} ADD COLUMN data_source')
                for s in sqls
            ), f'data_source ALTER missing for {t}'
        # One ADD COLUMN drive_id per DRIVE_ID_TABLES entry.
        for t in asm.DRIVE_ID_TABLES:
            assert any(
                s.startswith(f'ALTER TABLE {t} ADD COLUMN drive_id')
                for s in sqls
            ), f'drive_id ALTER missing for {t}'
        # One ADD INDEX per DRIVE_ID_TABLES entry.
        for t in asm.DRIVE_ID_TABLES:
            indexName = f'IX_{t}_drive_id'
            assert any(
                f'ADD INDEX {indexName}' in s for s in sqls
            ), f'drive_id index missing for {t}'
        # CREATE drive_counter + seed.
        assert any('CREATE TABLE' in s and 'drive_counter' in s for s in sqls)
        assert any('INSERT IGNORE' in s and 'drive_counter' in s for s in sqls)

    def test_planMigrations_partialState_onlyEmitMissing(self):
        """realtime_data done; others need data_source + drive_id + index."""
        probes = []
        union = tuple(dict.fromkeys(asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES))
        for t in union:
            if t == 'realtime_data':
                probes.append(_probe(t, ds=True, did=True, idx=True))
            else:
                isCapture = t in asm.CAPTURE_TABLES
                isDrive = t in asm.DRIVE_ID_TABLES
                probes.append(_probe(
                    t, ds=not isCapture, did=not isDrive, idx=not isDrive,
                ))
        state = asm.SchemaState(tables=probes, hasDriveCounterTable=True)
        plan = asm.planMigrations(state)
        sqls = [sql for sql, _ in plan.statements]
        # realtime_data should not appear at all.
        assert not any('ALTER TABLE realtime_data' in s for s in sqls)
        # drive_counter should not appear (already present).
        assert not any('CREATE TABLE' in s for s in sqls)
        # Other capture tables missing data_source should appear.
        assert any(
            'ALTER TABLE connection_log ADD COLUMN data_source' in s
            for s in sqls
        )

    def test_planMigrations_missingTable_skipsTable(self):
        """A non-existent table produces no ALTER statements."""
        probes = [_probe('realtime_data', ds=False, did=False, idx=False, exists=False)]
        # Include the rest in migrated state so plan is minimal.
        union = tuple(dict.fromkeys(asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES))
        for t in union:
            if t == 'realtime_data':
                continue
            isCapture = t in asm.CAPTURE_TABLES
            isDrive = t in asm.DRIVE_ID_TABLES
            probes.append(_probe(t, ds=isCapture, did=isDrive, idx=isDrive))
        state = asm.SchemaState(tables=probes, hasDriveCounterTable=True)
        plan = asm.planMigrations(state)
        sqls = [sql for sql, _ in plan.statements]
        assert not any('ALTER TABLE realtime_data' in s for s in sqls)

    def test_planMigrations_indexOnlyMissing_emitsIndexStatement(self):
        """drive_id column present, index absent -> emit only the ADD INDEX."""
        probes = []
        union = tuple(dict.fromkeys(asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES))
        for t in union:
            if t == 'realtime_data':
                probes.append(_probe(t, ds=True, did=True, idx=False))
            else:
                isCapture = t in asm.CAPTURE_TABLES
                isDrive = t in asm.DRIVE_ID_TABLES
                probes.append(_probe(t, ds=isCapture, did=isDrive, idx=isDrive))
        state = asm.SchemaState(tables=probes, hasDriveCounterTable=True)
        plan = asm.planMigrations(state)
        sqls = [sql for sql, _ in plan.statements]
        assert any('ADD INDEX IX_realtime_data_drive_id' in s for s in sqls)
        assert not any('ADD COLUMN data_source' in s for s in sqls)
        assert not any('ADD COLUMN drive_id' in s for s in sqls)


# ================================================================================
# Report rendering
# ================================================================================

class TestRenderPlan:
    def test_renderPlan_nonEmpty_listsEachStatement(self):
        plan = asm.MigrationPlan(
            statements=[
                ('ALTER TABLE realtime_data ADD COLUMN x INT', 'reason 1'),
                ('CREATE TABLE drive_counter (id INT)', 'reason 2'),
            ],
        )
        state = asm.SchemaState(
            tables=[_probe('realtime_data', ds=False, did=False, idx=False)],
            hasDriveCounterTable=False,
        )
        text = asm.renderPlan(state, plan)
        assert 'Migration plan' in text
        assert 'reason 1' in text
        assert 'reason 2' in text
        assert 'ALTER TABLE realtime_data' in text

    def test_renderPlan_emptyPlan_saysUpToDate(self):
        plan = asm.MigrationPlan(statements=[])
        state = asm.SchemaState(
            tables=[_probe('realtime_data', ds=True, did=True, idx=True)],
            hasDriveCounterTable=True,
        )
        text = asm.renderPlan(state, plan)
        assert 'already up to date' in text.lower()

    def test_renderPlan_missingTable_flaggedInScan(self):
        plan = asm.MigrationPlan(statements=[])
        state = asm.SchemaState(
            tables=[_probe('realtime_data', ds=False, did=False, idx=False, exists=False)],
            hasDriveCounterTable=False,
        )
        text = asm.renderPlan(state, plan)
        assert 'TABLE MISSING' in text


# ================================================================================
# Backup safety gates
# ================================================================================

class TestBackupServer:
    def test_backupServer_failure_raises(self):
        runner = FakeRunner(
            responses=[('mysqldump', _fail(stderr='perm denied'))],
        )
        with pytest.raises(asm.SafetyGateError, match='perm denied'):
            asm.backupServer(_addrs(), _creds(), runner, 'T')

    def test_backupServer_happyPath_returnsDumpPath(self):
        runner = FakeRunner(
            responses=[
                ('mysqldump', _ok(stdout='')),
                ('stat', _ok(stdout='1024\n')),
            ],
        )
        path = asm.backupServer(_addrs(), _creds(), runner, 'T')
        assert path == '/tmp/obd2-migration-backup-T.sql'

    def test_backupServer_oversized_raises(self):
        oversized = str(asm.BACKUP_MAX_BYTES + 1)
        runner = FakeRunner(
            responses=[
                ('mysqldump', _ok(stdout='')),
                ('stat', _ok(stdout=f'{oversized}\n')),
            ],
        )
        with pytest.raises(asm.SafetyGateError, match='too large'):
            asm.backupServer(_addrs(), _creds(), runner, 'T')


# ================================================================================
# applyPlan -- DDL execution + timing
# ================================================================================

class TestApplyPlan:
    def test_applyPlan_empty_returnsEmptyResults(self):
        plan = asm.MigrationPlan(statements=[])
        results = asm.applyPlan(_addrs(), _creds(), FakeRunner(), plan)
        assert results == []

    def test_applyPlan_happyPath_allStatementsRun(self):
        plan = asm.MigrationPlan(
            statements=[
                ('ALTER TABLE x ADD COLUMN y INT', 'reason'),
                ('CREATE TABLE z (id INT)', 'create z'),
            ],
        )
        runner = FakeRunner()  # default: all calls succeed
        results = asm.applyPlan(_addrs(), _creds(), runner, plan)
        assert len(results) == 2
        assert results[0][0] == 'ALTER TABLE x ADD COLUMN y INT'
        assert results[1][0] == 'CREATE TABLE z (id INT)'
        # mysql invoked once per DDL (via ssh), so 2 calls at minimum.
        mysqlCalls = [c for c in runner.calls if 'mysql' in ' '.join(c['argv'])]
        assert len(mysqlCalls) == 2

    def test_applyPlan_ddlFails_raisesMigrationError(self):
        plan = asm.MigrationPlan(
            statements=[
                ('ALTER TABLE x ADD COLUMN y INT', 'reason'),
            ],
        )
        runner = FakeRunner(
            responses=[('mysql', _fail(stderr='syntax error near y'))],
        )
        with pytest.raises(asm.MigrationError, match='syntax error near y'):
            asm.applyPlan(_addrs(), _creds(), runner, plan)


# ================================================================================
# Sentinel round-trip + CLI safety gates (main())
# ================================================================================

class TestSentinelRoundTrip:
    def test_writeAndRead_roundTrip(self, tmp_path: Path):
        plan = asm.MigrationPlan(
            statements=[('ALTER TABLE x ADD COLUMN y INT', 'reason')],
        )
        asm._writeSentinel(tmp_path, plan)
        data = asm._readSentinel(tmp_path)
        assert data is not None
        assert data.get('planLen') == '1'

    def test_readSentinel_absent_returnsNone(self, tmp_path: Path):
        assert asm._readSentinel(tmp_path) is None


class TestMainSafetyGates:
    def test_execute_withoutSentinel_exits2(
        self, tmp_path: Path, monkeypatch, capsys,
    ):
        """--execute refuses without a prior dry-run sentinel."""
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')

        # Install a module-level runner that fully simulates the server so
        # scan + plan succeed, but no sentinel exists -> main() returns 2.
        def _runner(argv, *, input=None, timeout=None):  # noqa: A002
            joined = ' '.join(argv)
            sql = input or ''
            if 'bash' in joined and 'env' in joined:
                return _ok(
                    stdout='SERVER_HOST=10.1.1.1\nSERVER_USER=u\n',
                )
            if 'DATABASE_URL' in joined or 'DATABASE_URL' in sql:
                return _ok(stdout='DATABASE_URL=mysql+aiomysql://u:p@h/db\n')
            if 'information_schema.TABLES' in sql:
                return _ok(stdout='1\n')
            if 'information_schema.COLUMNS' in sql:
                return _ok(
                    stdout='id\ntimestamp\nparameter_name\nvalue\n'
                           'data_source\ndrive_id\n',
                )
            if 'information_schema.STATISTICS' in sql:
                return _ok(stdout='1\n')
            return _ok(stdout='')

        monkeypatch.setattr(asm, '_defaultRunner', _runner)
        rc = asm.main([
            '--execute',
            '--project-root', str(tmp_path),
            '--addresses', str(addresses),
        ])
        assert rc == 2
        err = capsys.readouterr().err
        assert 'requires a prior successful --dry-run' in err

    def test_dryRun_writesSentinel_andExits0(
        self, tmp_path: Path, monkeypatch,
    ):
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')

        def _runner(argv, *, input=None, timeout=None):  # noqa: A002
            joined = ' '.join(argv)
            sql = input or ''
            if 'bash' in joined and 'env' in joined:
                return _ok(stdout='SERVER_HOST=10.1.1.1\nSERVER_USER=u\n')
            if 'DATABASE_URL' in joined or 'DATABASE_URL' in sql:
                return _ok(stdout='DATABASE_URL=mysql+aiomysql://u:p@h/db\n')
            if 'information_schema.TABLES' in sql:
                # drive_counter absent, all others present.
                if "TABLE_NAME='drive_counter'" in sql:
                    return _ok(stdout='0\n')
                return _ok(stdout='1\n')
            if 'information_schema.COLUMNS' in sql:
                # pre-US-195 shape (no data_source, no drive_id)
                return _ok(
                    stdout='id\ntimestamp\nparameter_name\nvalue\n',
                )
            if 'information_schema.STATISTICS' in sql:
                return _ok(stdout='0\n')
            return _ok(stdout='')

        monkeypatch.setattr(asm, '_defaultRunner', _runner)
        rc = asm.main([
            '--dry-run',
            '--project-root', str(tmp_path),
            '--addresses', str(addresses),
        ])
        assert rc == 0
        sentinel = tmp_path / asm.DRY_RUN_SENTINEL_NAME
        assert sentinel.exists()
