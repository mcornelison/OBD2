################################################################################
# File Name: test_migration_0005_dtc_log.py
# Purpose/Description: Sprint 19 US-238 -- migration unit tests.  Verifies the
#                      v0005 CREATE TABLE DDL fires when dtc_log is missing,
#                      short-circuits when present, propagates DDL failures,
#                      and surfaces the post-condition probe error when the
#                      CREATE silently no-ops (mysql session-context bug).
#                      FakeRunner mirrors v0004 / test_migrations.py so no live
#                      MariaDB or SSH is required.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex          | Initial -- Sprint 19 US-238 TDD.
# ================================================================================
################################################################################

"""TDD tests for the US-238 / V-2 dtc_log create-table migration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0005_us238_create_dtc_log as m0005,
)

# ================================================================================
# FakeRunner -- request-aware scripted subprocess stand-in (mirrors v0004 test)
# ================================================================================


@dataclass
class FakeRunner:
    """Scripted runner.  Caller registers handlers keyed by SQL substring;
    each handler returns a CompletedProcess.  Calls that don't match a
    handler return a generic OK so probes behave deterministically.
    """

    handlers: list[tuple[str, Callable[[str], subprocess.CompletedProcess[str]]]] = (
        field(default_factory=list)
    )
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = input or ''
        self.calls.append({'argv': list(argv), 'input': sql, 'timeout': timeout})
        for needle, handler in self.handlers:
            if needle in sql:
                return handler(sql)
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout='', stderr='',
        )

    @property
    def emittedSqls(self) -> list[str]:
        return [c['input'] for c in self.calls if c['input']]


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr,
    )


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=1, stdout='', stderr=stderr,
    )


# ================================================================================
# Helpers
# ================================================================================

def _addrs() -> asm.HostAddresses:
    return asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')


def _creds() -> asm.ServerCreds:
    return asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db')


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(addrs=_addrs(), creds=_creds(), runner=runner)


def _scriptMissingTable(runner: FakeRunner) -> None:
    """Configure FakeRunner so the first table probe reports 'missing'
    (the pre-Drive-4 production state) and the post-CREATE probe reports
    'present' (the migration succeeded).  Mirrors v0002's pre+post pattern.
    """
    probeCalls = {'n': 0}

    def tableProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        probeCalls['n'] += 1
        # First call: pre-CREATE -> 0 (missing).  Subsequent calls
        # (post-condition probe) -> 1 (present).
        return _ok(stdout='0\n' if probeCalls['n'] == 1 else '1\n')

    runner.handlers.append((
        'information_schema.TABLES',
        tableProbe,
    ))


def _scriptTablePresent(runner: FakeRunner) -> None:
    """All table probes report 'present' -- idempotent re-run path."""
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))


# ================================================================================
# Module shape
# ================================================================================

class TestModuleExports:
    def test_versionIs0005(self) -> None:
        assert m0005.VERSION == '0005'

    def test_descriptionMentionsUs238(self) -> None:
        assert 'US-238' in m0005.DESCRIPTION

    def test_descriptionMentionsDtcLog(self) -> None:
        assert 'dtc_log' in m0005.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0005.MIGRATION.version == '0005'
        assert callable(m0005.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0005' in versions

    def test_appendedAtEnd(self) -> None:
        # Ascending order invariant from MigrationRunner contract.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions[-1] == '0005'

    def test_uniqueKeyConstantMatchesDdl(self) -> None:
        assert m0005.DTC_LOG_UNIQUE_NAME in m0005.CREATE_DTC_LOG_DDL

    def test_driveIdIndexConstantMatchesDdl(self) -> None:
        assert m0005.DTC_LOG_DRIVE_ID_INDEX in m0005.CREATE_DTC_LOG_DDL


# ================================================================================
# Schema parity -- DDL must mirror the DtcLog ORM (Pi-shape source-of-truth)
# ================================================================================

class TestDdlMirrorsOrm:
    """The migration must declare every column the SQLAlchemy DtcLog model
    declares.  If a future ORM change adds a column, this test fails and
    forces a follow-up migration.
    """

    def test_ddlContainsEveryOrmColumn(self) -> None:
        from src.server.db.models import DtcLog

        ddl = m0005.CREATE_DTC_LOG_DDL
        for col in DtcLog.__table__.columns:
            assert col.name in ddl, (
                f'migration DDL missing ORM column {col.name!r}'
            )

    def test_ddlDeclaresAllTwelveExpectedColumns(self) -> None:
        # Lock the column count so accidental drops show up loud.  Twelve
        # is what the US-204 ORM declares: id + 4 sync + 7 Pi-native.
        expected = {
            'id', 'source_id', 'source_device', 'synced_at', 'sync_batch_id',
            'dtc_code', 'description', 'status',
            'first_seen_timestamp', 'last_seen_timestamp',
            'drive_id', 'data_source',
        }
        ddl = m0005.CREATE_DTC_LOG_DDL
        for col in expected:
            assert col in ddl, f'DDL missing column {col!r}'

    def test_ddlMarksDtcCodeNotNull(self) -> None:
        # Pi-side schema invariant -- DTC code must be present.
        ddl = m0005.CREATE_DTC_LOG_DDL
        assert 'dtc_code              VARCHAR(16) NOT NULL' in ddl

    def test_ddlMarksStatusNotNull(self) -> None:
        ddl = m0005.CREATE_DTC_LOG_DDL
        assert 'status                VARCHAR(16) NOT NULL' in ddl

    def test_ddlMarksSourceIdNotNull(self) -> None:
        ddl = m0005.CREATE_DTC_LOG_DDL
        assert 'source_id             INT NOT NULL' in ddl

    def test_ddlMarksSourceDeviceNotNull(self) -> None:
        ddl = m0005.CREATE_DTC_LOG_DDL
        assert 'source_device         VARCHAR(64) NOT NULL' in ddl

    def test_ddlUsesUtf8mb4(self) -> None:
        # Match v0002 / battery_health_log charset for cross-table joins.
        assert 'utf8mb4' in m0005.CREATE_DTC_LOG_DDL

    def test_ddlUsesInnoDb(self) -> None:
        # InnoDB for transactional sync upsert + FK-future-readiness.
        assert 'ENGINE=InnoDB' in m0005.CREATE_DTC_LOG_DDL

    def test_ddlContainsIfNotExists(self) -> None:
        # Belt-and-suspenders idempotency with the probe.
        assert 'CREATE TABLE IF NOT EXISTS dtc_log' in m0005.CREATE_DTC_LOG_DDL


# ================================================================================
# apply -- table missing path (production state pre-deploy)
# ================================================================================

class TestApplyTableMissing:
    """When dtc_log doesn't exist, the migration emits CREATE TABLE
    and the post-probe verifies it landed.
    """

    def test_emitsCreateTableDdl(self) -> None:
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0005.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert len(creates) == 1, (
            f'expected exactly one CREATE TABLE; got: {creates}'
        )
        assert 'dtc_log' in creates[0]

    def test_emitsExpectedDdlContent(self) -> None:
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0005.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert creates[0] == m0005.CREATE_DTC_LOG_DDL

    def test_runsTwoTableProbesPreAndPost(self) -> None:
        # Pre-check probe (short-circuit) + post-condition probe.
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0005.apply(_ctx(runner))

        tableProbes = [
            s for s in runner.emittedSqls
            if 'information_schema.TABLES' in s
        ]
        assert len(tableProbes) == 2, (
            f'expected pre + post table probes; got {len(tableProbes)}'
        )


# ================================================================================
# apply -- table already present (idempotent re-run + fresh-DB create_all path)
# ================================================================================

class TestApplyTablePresent:
    """When dtc_log already exists (idempotent re-run OR fresh DB where
    SQLAlchemy create_all() owns table creation), apply MUST be a no-op.
    """

    def test_emitsNoCreateTable(self) -> None:
        runner = FakeRunner()
        _scriptTablePresent(runner)
        m0005.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert creates == [], (
            f'idempotent run must not emit CREATE; got: {creates}'
        )

    def test_emitsNoPostConditionProbe(self) -> None:
        # Short-circuit returns before any DDL or post-probe runs.
        runner = FakeRunner()
        _scriptTablePresent(runner)
        m0005.apply(_ctx(runner))

        tableProbes = [
            s for s in runner.emittedSqls
            if 'information_schema.TABLES' in s
        ]
        assert len(tableProbes) == 1, (
            'short-circuit should run the pre-check probe only'
        )


# ================================================================================
# Failure paths -- DDL error + silent no-op
# ================================================================================

class TestFailureModes:
    def test_createFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        _scriptMissingTable(runner)
        # Override: any CREATE TABLE fails with a representative MariaDB error.
        runner.handlers.insert(0, (
            'CREATE TABLE',
            lambda _sql: _fail('Tablespace exists'),
        ))
        with pytest.raises(asm.MigrationError, match='dtc_log'):
            m0005.apply(_ctx(runner))

    def test_postProbeMissingRaisesSchemaProbeError(self) -> None:
        # CREATE returns 0 but the post-probe still reports the table
        # missing -- the silent mysql session-context bug class.  The
        # migration must NOT silently record success.
        runner = FakeRunner()
        # Both probes return 0 (missing) -> trigger CREATE -> still missing.
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(
            asm.SchemaProbeError, match='dtc_log missing after CREATE',
        ):
            m0005.apply(_ctx(runner))


# ================================================================================
# Strong-test discriminator -- pre-US-238 vs post-US-238 codebase divergence
# ================================================================================

class TestProductionFailureModeDiscriminator:
    """Lock the SQL that resolves V-2's specific bug.

    V-2 evidence (Drive 4 health check, 2026-04-29):

        SELECT COUNT(*) FROM dtc_log;
        ERROR 1146 (42S02): Table 'obd2db.dtc_log' doesn't exist

    The fix MUST emit ``CREATE TABLE ... dtc_log`` against a server where
    the table does not exist.  These tests fail loudly if a future refactor
    drops the migration or changes the DDL shape such that the production
    bug class would re-emerge.
    """

    def test_createsExactlyDtcLogTable(self) -> None:
        # Bug scope is narrow -- only dtc_log.  Migration must not
        # accidentally touch other tables.
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0005.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert len(creates) == 1
        # No incidental table creation -- only dtc_log.
        for sql in creates:
            assert 'dtc_log' in sql
            for other in ('drive_summary', 'connection_log', 'realtime_data'):
                assert f'CREATE TABLE IF NOT EXISTS {other}' not in sql

    def test_uniqueKeyMatchesPiSyncContract(self) -> None:
        # The Pi-sync upsert handler in src/server/api/sync.py keys on
        # (source_device, source_id).  If the migration UNIQUE drifts,
        # every Pi sync of dtc_log fails with ON DUPLICATE KEY violation.
        ddl = m0005.CREATE_DTC_LOG_DDL
        assert (
            f'UNIQUE KEY {m0005.DTC_LOG_UNIQUE_NAME} '
            '(source_device, source_id)' in ddl
        )

    def test_driveIdIndexPresent(self) -> None:
        # Per the story invariant: "Indexes on (source_device, source_id)
        # for sync uniqueness; on drive_id for analytics queries."
        ddl = m0005.CREATE_DTC_LOG_DDL
        assert (
            f'KEY {m0005.DTC_LOG_DRIVE_ID_INDEX} (drive_id)' in ddl
        )

    def test_runWouldFireCreateAgainstStaleProductionState(self) -> None:
        """If we replay the EXACT V-2 production state (missing table) the
        migration MUST issue a CREATE.  A future refactor that removes the
        CREATE_DTC_LOG_DDL or short-circuits without DDL would fail this
        test, surfacing the regression before deploy.
        """
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0005.apply(_ctx(runner))

        # Single CREATE TABLE issued -- the V-2 fix is intact.
        createCount = sum(1 for s in runner.emittedSqls if 'CREATE TABLE' in s)
        assert createCount == 1
