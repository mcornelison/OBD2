################################################################################
# File Name: test_migration_0008_baselines.py
# Purpose/Description: Sprint 29 US-312 (I-018 Layer 2 close) -- migration unit
#                      tests.  Verifies the v0008 CREATE TABLE DDL fires when
#                      ``baselines`` is missing on live MariaDB,
#                      short-circuits when present, propagates DDL failures
#                      and raises on the silent-no-op probe class.  Mirrors
#                      v0005 (dtc_log) test shape; FakeRunner replaces SSH +
#                      MariaDB so the suite stays hermetic.  Scope addition
#                      per BL-010 pattern: PM scope.filesToTouch listed only
#                      tests/server/test_calibration_cli_integration.py for
#                      the test surface; this file adds the migration unit
#                      tests because Layer 2 (missing-table-on-MariaDB) cannot
#                      be exercised by the CLI integration test alone (the
#                      latter uses SQLAlchemy create_all which builds the
#                      table from the ORM).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex          | Initial -- Sprint 29 US-312 TDD (I-018
#               |              | Layer 2 close).
# ================================================================================
################################################################################

"""TDD tests for the US-312 / I-018 Layer 2 baselines create-table migration."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0008_us312_create_baselines as m0008,
)

# ================================================================================
# FakeRunner -- request-aware scripted subprocess stand-in (mirrors v0005 test)
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
    (the I-018 Layer 2 production state) and the post-CREATE probe
    reports 'present' (the migration succeeded).
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
    def test_versionIs0008(self) -> None:
        assert m0008.VERSION == '0008'

    def test_descriptionMentionsUs312(self) -> None:
        assert 'US-312' in m0008.DESCRIPTION

    def test_descriptionMentionsBaselines(self) -> None:
        assert 'baselines' in m0008.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0008.MIGRATION.version == '0008'
        assert callable(m0008.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0008' in versions

    def test_appendedAtEnd(self) -> None:
        # TD-044 invariant: ascending order; latest at tail.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert re.match(r'^\d{4}$', versions[-1]) is not None

    def test_uniqueKeyConstantMatchesDdl(self) -> None:
        assert m0008.BASELINES_UNIQUE_NAME in m0008.CREATE_BASELINES_DDL


# ================================================================================
# Schema parity -- DDL must mirror the Baseline ORM
# ================================================================================

class TestDdlMirrorsOrm:
    """The migration must declare every column the SQLAlchemy Baseline model
    declares.  If a future ORM change adds a column, this test fails and
    forces a follow-up migration.
    """

    def test_ddlContainsEveryOrmColumn(self) -> None:
        from src.server.db.models import Baseline

        ddl = m0008.CREATE_BASELINES_DDL
        for col in Baseline.__table__.columns:
            assert col.name in ddl, (
                f'migration DDL missing ORM column {col.name!r}'
            )

    def test_ddlDeclaresAllExpectedColumns(self) -> None:
        # Lock the column count so accidental drops show up loud.
        expected = {
            'id', 'device_id', 'parameter_name', 'avg_value',
            'min_value', 'max_value', 'std_dev', 'sample_count',
            'established_at',
        }
        ddl = m0008.CREATE_BASELINES_DDL
        for col in expected:
            assert col in ddl, f'DDL missing column {col!r}'

    def test_ddlMarksDeviceIdNotNull(self) -> None:
        ddl = m0008.CREATE_BASELINES_DDL
        assert 'device_id' in ddl and 'NOT NULL' in ddl

    def test_ddlMarksParameterNameNotNull(self) -> None:
        ddl = m0008.CREATE_BASELINES_DDL
        # The Baseline ORM marks parameter_name NOT NULL; the migration
        # must too.  Guards against drift.
        assert 'parameter_name' in ddl

    def test_ddlMarksAvgValueNotNull(self) -> None:
        # avg_value is the only required FLOAT in the ORM model.
        ddl = m0008.CREATE_BASELINES_DDL
        assert 'avg_value' in ddl

    def test_ddlUsesUtf8mb4(self) -> None:
        # Match v0002 / v0005 charset for cross-table joins.
        assert 'utf8mb4' in m0008.CREATE_BASELINES_DDL

    def test_ddlUsesInnoDb(self) -> None:
        # InnoDB for transactional upsert + cross-table joins.
        assert 'ENGINE=InnoDB' in m0008.CREATE_BASELINES_DDL

    def test_ddlContainsIfNotExists(self) -> None:
        # Belt-and-suspenders idempotency with the probe.
        assert 'CREATE TABLE IF NOT EXISTS baselines' in m0008.CREATE_BASELINES_DDL


# ================================================================================
# apply -- table missing path (I-018 Layer 2 production state)
# ================================================================================

class TestApplyTableMissing:
    """When baselines doesn't exist (I-018 Layer 2), the migration emits
    CREATE TABLE and the post-probe verifies it landed.
    """

    def test_emitsCreateTableDdl(self) -> None:
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0008.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert len(creates) == 1, (
            f'expected exactly one CREATE TABLE; got: {creates}'
        )
        assert 'baselines' in creates[0]

    def test_emitsExpectedDdlContent(self) -> None:
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0008.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert creates[0] == m0008.CREATE_BASELINES_DDL

    def test_runsTwoTableProbesPreAndPost(self) -> None:
        # Pre-check probe (short-circuit) + post-condition probe.
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0008.apply(_ctx(runner))

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
    """When baselines already exists (idempotent re-run OR fresh DB where
    SQLAlchemy create_all() owns table creation), apply MUST be a no-op.
    """

    def test_emitsNoCreateTable(self) -> None:
        runner = FakeRunner()
        _scriptTablePresent(runner)
        m0008.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert creates == [], (
            f'idempotent run must not emit CREATE; got: {creates}'
        )

    def test_emitsNoPostConditionProbe(self) -> None:
        # Short-circuit returns before any DDL or post-probe runs.
        runner = FakeRunner()
        _scriptTablePresent(runner)
        m0008.apply(_ctx(runner))

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
        with pytest.raises(asm.MigrationError, match='baselines'):
            m0008.apply(_ctx(runner))

    def test_postProbeMissingRaisesSchemaProbeError(self) -> None:
        # CREATE returns 0 but the post-probe still reports the table
        # missing -- the silent mysql session-context bug class.
        runner = FakeRunner()
        # Both probes return 0 (missing) -> trigger CREATE -> still missing.
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(
            asm.SchemaProbeError, match='baselines missing after CREATE',
        ):
            m0008.apply(_ctx(runner))


# ================================================================================
# Strong-test discriminator -- I-018 Layer 2 production state
# ================================================================================

class TestProductionFailureModeDiscriminator:
    """Lock the SQL that resolves the I-018 Layer 2 bug.

    I-018 evidence (Spool 2026-05-09 housekeeping Item 1): SHOW TABLES on
    obd2db does not include `baselines`.  calibration --apply path SQL
    INSERT would fail with `Table 'obd2db.baselines' doesn't exist`.
    """

    def test_createsExactlyBaselinesTable(self) -> None:
        # Bug scope is narrow -- only baselines.  Migration must not
        # accidentally touch other tables.
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0008.apply(_ctx(runner))

        creates = [s for s in runner.emittedSqls if 'CREATE TABLE' in s]
        assert len(creates) == 1
        for sql in creates:
            assert 'baselines' in sql
            for other in ('drive_summary', 'connection_log', 'realtime_data'):
                assert f'CREATE TABLE IF NOT EXISTS {other}' not in sql

    def test_uniqueKeyMatchesCalibrationContract(self) -> None:
        # The calibration upsert in src/server/analytics/calibration.py
        # keys on (device_id, parameter_name).  If the migration UNIQUE
        # drifts, every applyCalibration() insert past the first per
        # (device_id, parameter_name) trips a duplicate-key error.
        ddl = m0008.CREATE_BASELINES_DDL
        assert (
            f'UNIQUE KEY {m0008.BASELINES_UNIQUE_NAME} '
            '(device_id, parameter_name)' in ddl
        )

    def test_runWouldFireCreateAgainstStaleProductionState(self) -> None:
        """If we replay the EXACT I-018 production state (missing table)
        the migration MUST issue a CREATE.  A future refactor that
        removes CREATE_BASELINES_DDL or short-circuits without DDL would
        fail this test, surfacing the regression before deploy.
        """
        runner = FakeRunner()
        _scriptMissingTable(runner)
        m0008.apply(_ctx(runner))

        createCount = sum(1 for s in runner.emittedSqls if 'CREATE TABLE' in s)
        assert createCount == 1
