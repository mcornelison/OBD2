################################################################################
# File Name: test_migrations.py
# Purpose/Description: Unit tests for the US-213 server migration registry +
#                      runner + deploy-time gate. Covers: registry validation,
#                      schema_migrations bookkeeping (ensureTracking, getApplied,
#                      _recordApplied), idempotency (runAll is a no-op on a
#                      fully-migrated DB), fresh-apply, added-migration, and
#                      failure-halts behaviours. Migration 0001 (retroactive
#                      US-209 wrapper) is exercised via the scan+plan+apply
#                      seam without touching a network — FakeRunner scripts
#                      every mysql/mysqldump subprocess call.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex          | Initial -- Sprint 16 US-213 TDD (TD-029 closure).
# 2026-09-04    | Rex (US-675) | Registry sanity gains CONTIGUITY (no holes in
#               |              | the chain -- sorted+unique still permits a
#               |              | gap), a non-vacuity proof for it, and an
#               |              | append-proof that re-runs the real guards
#               |              | against a widened registry so no registry
#               |              | guard can be given a shelf life again.
# ================================================================================
################################################################################

"""TDD tests for the US-213 server migration runner + registry."""

from __future__ import annotations

import ast
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import (
    ALL_MIGRATIONS,
    SCHEMA_MIGRATIONS_TABLE,
    Migration,
    MigrationRunner,
    RunnerContext,
    RunReport,
)
from src.server.migrations.runner import (
    SCHEMA_MIGRATIONS_TABLE_DDL,
    RegistryError,
)

# ================================================================================
# FakeRunner -- mirror of tests/scripts/test_apply_server_migrations.py helper
# ================================================================================

@dataclass
class FakeRunner:
    """Minimal scripted runner matching the CommandRunner Protocol."""

    responses: list[tuple[str, subprocess.CompletedProcess[str]]] = field(
        default_factory=list,
    )
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002
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


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=1, stdout='', stderr=stderr,
    )


# ================================================================================
# Helpers
# ================================================================================

def _addrs() -> asm.HostAddresses:
    return asm.HostAddresses(serverHost='10.2.2.2', serverUser='u')


def _creds() -> asm.ServerCreds:
    return asm.ServerCreds(dbUser='u', dbPassword='p', dbName='obd2db')


def _makeCtx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(addrs=_addrs(), creds=_creds(), runner=runner)


def _applyNoop(_ctx: RunnerContext) -> None:
    """Migration applyFn that does nothing (for unit tests)."""
    return None


def _isTailSubscript(node: ast.expr) -> bool:
    """True for ``<anything>[-1]`` -- the absolute-tail read US-675 bans."""
    if not isinstance(node, ast.Subscript):
        return False
    index = node.slice
    return (
        isinstance(index, ast.UnaryOp)
        and isinstance(index.op, ast.USub)
        and isinstance(index.operand, ast.Constant)
        and index.operand.value == 1
    )


def _mkMigration(version: str, description: str = 'x',
                 applyFn: Callable[[RunnerContext], None] | None = None) -> Migration:
    return Migration(
        version=version,
        description=description,
        applyFn=applyFn or _applyNoop,
    )


# ================================================================================
# Registry sanity -- ALL_MIGRATIONS + v0001 shape
# ================================================================================

class TestRegistry:
    def test_ALL_MIGRATIONS_nonEmpty(self):
        assert len(ALL_MIGRATIONS) >= 1, 'registry must contain at least v0001'

    def test_ALL_MIGRATIONS_uniqueVersions(self):
        versions = [m.version for m in ALL_MIGRATIONS]
        assert len(versions) == len(set(versions)), (
            f'duplicate version(s): {versions}'
        )

    def test_ALL_MIGRATIONS_entriesAreMigrationInstances(self):
        for m in ALL_MIGRATIONS:
            assert isinstance(m, Migration)
            assert m.version
            assert m.description
            assert callable(m.applyFn)

    def test_v0001_exists_andIsFirst(self):
        # Retroactive registration of US-209's one-shot DDL is the anchor.
        assert ALL_MIGRATIONS[0].version == '0001'
        assert 'US-195' in ALL_MIGRATIONS[0].description
        assert 'US-200' in ALL_MIGRATIONS[0].description

    def test_versions_areSortedAscending(self):
        # Sorted order lets planPending preserve application order naturally.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions), (
            f'migrations must be in ascending version order: {versions}'
        )

    def test_versions_areContiguous(self):
        """No holes in the chain (US-675).

        Sorted + unique still permits a GAP -- ..'0014', '0016'.. -- which is
        what a migration silently dropped from the registry looks like, and
        nothing in the suite asserted against it before US-675.

        This is the half of the invariant that CANNOT rot: unlike "v0015 is
        last", contiguity stays true through every future append, so it never
        needs hand-editing.  A failure here means a version was removed or
        renumbered -- fix the registry, do not relax this test.
        """
        versions = [int(m.version) for m in ALL_MIGRATIONS]
        expected = list(range(versions[0], versions[0] + len(versions)))
        assert versions == expected, (
            'migration chain has a hole; missing '
            f'{sorted(set(expected) - set(versions))}'
        )

    def test_registryGuardsSurviveTheNextMigration(self, monkeypatch):
        """US-675 VC2 -- adding a migration must not turn these guards red.

        The two guards US-675 retired (``versions[-1] == '0015'`` and
        ``== '0019'``) were red because they encoded a fact with a shelf life:
        each was falsified by the next migration to land.  This is the
        standing proof that the replacements do not share that defect.

        It appends a hypothetical next migration and RE-RUNS THE REAL GUARDS
        -- ``self.test_...()``, not copies of their bodies -- so it cannot
        drift away from the assertions it protects.  Any future registry
        guard written as "version X is last" fails here on the day it is
        written, rather than silently going red four versions later.
        """
        nextVersion = f'{int(ALL_MIGRATIONS[-1].version) + 1:04d}'
        monkeypatch.setattr(
            sys.modules[__name__],
            'ALL_MIGRATIONS',
            (*ALL_MIGRATIONS, _mkMigration(nextVersion)),
        )

        self.test_versions_areSortedAscending()
        self.test_versions_areContiguous()
        self.test_ALL_MIGRATIONS_uniqueVersions()
        self.test_v0001_exists_andIsFirst()

    def test_contiguityGuardActuallyDetectsAHole(self, monkeypatch):
        """``test_versions_areContiguous`` is non-vacuous -- proven, not assumed.

        The real registry has no hole, so that guard passing says nothing
        about whether it CAN fail.  Written as ``expected = list(versions)``
        it would be trivially true and would sit there green forever -- the
        inert-guard shape US-675 exists to remove, and a hole the registry
        itself can never witness because it supplies no gap to detect.

        So the gap is supplied here and the REAL guard is re-run against it.
        """
        gapped = tuple(m for m in ALL_MIGRATIONS if m.version != '0015')
        monkeypatch.setattr(sys.modules[__name__], 'ALL_MIGRATIONS', gapped)

        with pytest.raises(AssertionError, match='hole'):
            self.test_versions_areContiguous()

    def test_noRegistryGuardPinsTheAbsoluteTail(self):
        """The absolute-tail pattern cannot be reintroduced anywhere (TD-062).

        The append-proof above can only protect the guards it re-runs.  A NEW
        migration test file writing ``versions[-1] == '0026'`` would still
        pass on the day it is written and go red four versions later -- which
        is exactly how v0015, v0018 and v0019 each rotted in turn (TD-062
        recorded three recurrences and asked for this guard).

        So the pattern is banned by shape across the whole server suite.

        NOT banned: ``re.match(r'^\\d{4}$', versions[-1])``, which asserts the
        tail's FORM and is satisfied by every future tail.  Three files use
        it legitimately.  The defect is pinning the tail to a LITERAL, so
        that -- and only that -- is what this matches.

        Matched by AST, not by grep, and deliberately: a textual sweep also
        fires on prose, so the retirement notes in this suite (which quote
        the banned line in order to explain it) would be indistinguishable
        from the defect.  Parsing compares real ``==`` nodes and ignores
        comments and docstrings, so the ban can be documented in its own
        terms.
        """
        offenders = []

        for path in sorted(pathlib.Path(__file__).parent.glob('test_*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare) or len(node.ops) != 1:
                    continue
                if not isinstance(node.ops[0], ast.Eq):
                    continue
                if not _isTailSubscript(node.left):
                    continue
                right = node.comparators[0]
                if (
                    isinstance(right, ast.Constant)
                    and isinstance(right.value, str)
                    and re.fullmatch(r'\d{4}', right.value)
                ):
                    offenders.append(
                        f'{path.name}:{node.lineno}: '
                        f'{ast.unparse(node)}'
                    )

        assert not offenders, (
            'absolute-tail assertion(s) reintroduced -- these pass today and '
            'go RED on the next migration.  Assert PLACEMENT (present + '
            'sorted + directly after the predecessor) instead:\n  '
            + '\n  '.join(offenders)
        )


# ================================================================================
# MigrationRunner construction
# ================================================================================

class TestMigrationRunner_Construction:
    def test_emptyRegistry_allowed(self):
        runner = MigrationRunner([])
        ctx = _makeCtx(FakeRunner())
        report = runner.runAll(ctx)
        assert report.applied == []

    def test_duplicateVersions_raises(self):
        with pytest.raises(RegistryError, match='duplicate'):
            MigrationRunner([_mkMigration('0001'), _mkMigration('0001')])

    def test_acceptsTupleOrList(self):
        # Sequence, not list-only -- tuples are canonical per __init__ export.
        assert MigrationRunner((_mkMigration('0001'),))
        assert MigrationRunner([_mkMigration('0001')])


# ================================================================================
# ensureTracking -- CREATE TABLE IF NOT EXISTS schema_migrations
# ================================================================================

class TestEnsureTracking:
    def test_sendsCreateTableIfNotExists(self):
        runner = FakeRunner()
        reg = MigrationRunner([])
        reg.ensureTracking(_makeCtx(runner))
        ddlCalls = [c for c in runner.calls if c['input']
                    and SCHEMA_MIGRATIONS_TABLE in c['input']]
        assert ddlCalls, 'expected a schema_migrations DDL call'
        ddl = ddlCalls[0]['input']
        assert 'CREATE TABLE' in ddl and 'IF NOT EXISTS' in ddl
        assert 'version' in ddl and 'description' in ddl and 'applied_at' in ddl

    def test_sqlFailureRaises(self):
        runner = FakeRunner(responses=[(SCHEMA_MIGRATIONS_TABLE, _fail('syntax'))])
        reg = MigrationRunner([])
        with pytest.raises(asm.MigrationError, match='schema_migrations'):
            reg.ensureTracking(_makeCtx(runner))


# ================================================================================
# getApplied -- SELECT version FROM schema_migrations
# ================================================================================

class TestGetApplied:
    def test_emptyTable_returnsEmptySet(self):
        runner = FakeRunner(responses=[('SELECT version', _ok(stdout=''))])
        reg = MigrationRunner([])
        assert reg.getApplied(_makeCtx(runner)) == set()

    def test_parsesVersionList(self):
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout='0001\n0002\n0003\n'))],
        )
        reg = MigrationRunner([])
        assert reg.getApplied(_makeCtx(runner)) == {'0001', '0002', '0003'}

    def test_stripsWhitespaceAndIgnoresBlanks(self):
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout=' 0001 \n\n0002\n\n'))],
        )
        reg = MigrationRunner([])
        assert reg.getApplied(_makeCtx(runner)) == {'0001', '0002'}

    def test_sqlFailureRaises(self):
        runner = FakeRunner(
            responses=[('SELECT version', _fail('connection refused'))],
        )
        reg = MigrationRunner([])
        with pytest.raises(asm.MigrationError, match='schema_migrations'):
            reg.getApplied(_makeCtx(runner))


# ================================================================================
# planPending
# ================================================================================

class TestPlanPending:
    def test_allApplied_returnsEmpty(self):
        reg = MigrationRunner([_mkMigration('0001'), _mkMigration('0002')])
        assert reg.planPending({'0001', '0002'}) == []

    def test_nothingApplied_returnsAll(self):
        a, b = _mkMigration('0001'), _mkMigration('0002')
        reg = MigrationRunner([a, b])
        assert reg.planPending(set()) == [a, b]

    def test_filtersOutAppliedAndPreservesOrder(self):
        a = _mkMigration('0001')
        b = _mkMigration('0002')
        c = _mkMigration('0003')
        reg = MigrationRunner([a, b, c])
        assert reg.planPending({'0002'}) == [a, c]


# ================================================================================
# runAll -- full orchestration
# ================================================================================

class TestRunAll:
    def test_freshDb_appliesAllInOrder(self):
        calls: list[str] = []

        def mkApply(version: str) -> Callable[[RunnerContext], None]:
            def _apply(_ctx: RunnerContext) -> None:
                calls.append(version)
            return _apply

        migrations = [
            _mkMigration('0001', 'first', applyFn=mkApply('0001')),
            _mkMigration('0002', 'second', applyFn=mkApply('0002')),
        ]
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout=''))],
        )
        reg = MigrationRunner(migrations)
        report = reg.runAll(_makeCtx(runner))
        assert report.applied == ['0001', '0002']
        assert report.alreadyApplied == []
        assert calls == ['0001', '0002']

    def test_idempotent_reRunIsNoOp(self):
        calls: list[str] = []

        def mkApply(version: str) -> Callable[[RunnerContext], None]:
            def _apply(_ctx: RunnerContext) -> None:
                calls.append(version)
            return _apply

        migrations = [
            _mkMigration('0001', applyFn=mkApply('0001')),
            _mkMigration('0002', applyFn=mkApply('0002')),
        ]
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout='0001\n0002\n'))],
        )
        reg = MigrationRunner(migrations)
        report = reg.runAll(_makeCtx(runner))
        assert report.applied == []
        assert report.alreadyApplied == ['0001', '0002']
        assert calls == []

    def test_newMigrationAdded_runsOnlyThatOne(self):
        calls: list[str] = []

        def mkApply(version: str) -> Callable[[RunnerContext], None]:
            def _apply(_ctx: RunnerContext) -> None:
                calls.append(version)
            return _apply

        migrations = [
            _mkMigration('0001', applyFn=mkApply('0001')),
            _mkMigration('0002', applyFn=mkApply('0002')),
            _mkMigration('0003', applyFn=mkApply('0003')),
        ]
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout='0001\n0002\n'))],
        )
        reg = MigrationRunner(migrations)
        report = reg.runAll(_makeCtx(runner))
        assert report.applied == ['0003']
        assert calls == ['0003']

    def test_migrationFailure_halts_andRemainderUntouched(self):
        calls: list[str] = []

        def boom(_ctx: RunnerContext) -> None:
            raise asm.MigrationError('DDL exploded')

        def later(_ctx: RunnerContext) -> None:
            calls.append('later')

        migrations = [
            _mkMigration('0001', applyFn=boom),
            _mkMigration('0002', applyFn=later),
        ]
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout=''))],
        )
        reg = MigrationRunner(migrations)
        with pytest.raises(asm.MigrationError, match='DDL exploded'):
            reg.runAll(_makeCtx(runner))
        assert calls == []  # 0002 must NOT have run

    def test_recordAppliedInsertsVersionAndDescription(self):
        migrations = [_mkMigration('0042', 'fortytwo')]
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout=''))],
        )
        reg = MigrationRunner(migrations)
        reg.runAll(_makeCtx(runner))
        inserts = [
            c for c in runner.calls
            if c['input'] and 'INSERT' in c['input']
            and SCHEMA_MIGRATIONS_TABLE in c['input']
        ]
        assert inserts, 'expected an INSERT into schema_migrations'
        sql = inserts[0]['input']
        assert "'0042'" in sql and "'fortytwo'" in sql

    def test_recordAppliedEscapesSingleQuotes(self):
        # Prevent SQL injection via description (defence-in-depth even though
        # the description is always author-controlled).
        migrations = [_mkMigration('0042', "O'Brien's note")]
        runner = FakeRunner(
            responses=[('SELECT version', _ok(stdout=''))],
        )
        reg = MigrationRunner(migrations)
        reg.runAll(_makeCtx(runner))
        inserts = [
            c for c in runner.calls
            if c['input'] and 'INSERT' in c['input']
            and SCHEMA_MIGRATIONS_TABLE in c['input']
        ]
        sql = inserts[0]['input']
        # Each apostrophe in the source string must appear doubled in the
        # emitted SQL. The raw string has 2 apostrophes -> 4 doubled chars.
        assert "O''Brien''s note" in sql


# ================================================================================
# SCHEMA_MIGRATIONS_TABLE_DDL -- shape sanity
# ================================================================================

class TestSchemaMigrationsTableDdl:
    def test_ddlIsIdempotentCreate(self):
        assert 'IF NOT EXISTS' in SCHEMA_MIGRATIONS_TABLE_DDL

    def test_ddlHasRequiredColumns(self):
        for col in ('version', 'description', 'applied_at'):
            assert col in SCHEMA_MIGRATIONS_TABLE_DDL

    def test_ddlHasPrimaryKeyOnVersion(self):
        assert 'PRIMARY KEY' in SCHEMA_MIGRATIONS_TABLE_DDL

    def test_ddlHasDefaultTimestamp(self):
        assert 'CURRENT_TIMESTAMP' in SCHEMA_MIGRATIONS_TABLE_DDL


# ================================================================================
# RunReport
# ================================================================================

class TestRunReport:
    def test_defaultsAreEmpty(self):
        report = RunReport()
        assert report.applied == []
        assert report.alreadyApplied == []

    def test_isEmptyWhenNothingNewApplied(self):
        report = RunReport(alreadyApplied=['0001', '0002'])
        assert report.isEmpty

    def test_notEmptyWhenSomethingApplied(self):
        report = RunReport(applied=['0002'], alreadyApplied=['0001'])
        assert not report.isEmpty


# ================================================================================
# Migration 0001 -- retroactive US-209 wrapper
# ================================================================================

class TestV0001:
    def test_importModuleAndMigrationSymbol(self):
        from src.server.migrations.versions import v0001_us195_us200_catch_up as m0001
        assert m0001.MIGRATION.version == '0001'
        assert 'US-195' in m0001.MIGRATION.description
        assert 'US-200' in m0001.MIGRATION.description

    def test_apply_onFullyMigratedServer_isNoOp(self, monkeypatch):
        # When scanServerSchema reports every table has data_source + drive_id
        # and drive_counter exists, planMigrations returns an empty plan and
        # applyPlan is a no-op. Verify no DDL is emitted.
        from src.server.migrations.versions import v0001_us195_us200_catch_up as m0001

        # Stub asm so scanServerSchema returns a fully-migrated SchemaState.
        fullState = asm.SchemaState(
            tables=[
                asm.ColumnProbe(
                    tableName=t, exists=True,
                    hasDataSource=True, hasDriveId=True,
                    hasDriveIdIndex=(t in asm.DRIVE_ID_TABLES),
                )
                for t in dict.fromkeys(asm.CAPTURE_TABLES + asm.DRIVE_ID_TABLES)
            ],
            hasDriveCounterTable=True,
        )
        monkeypatch.setattr(
            m0001, 'scanServerSchema',
            lambda addrs, creds, runner: fullState,
        )
        applyPlanCalls: list = []
        monkeypatch.setattr(
            m0001, 'applyPlan',
            lambda *a, **kw: applyPlanCalls.append((a, kw)) or [],
        )
        m0001.apply(_makeCtx(FakeRunner()))
        assert applyPlanCalls == [], (
            'apply must NOT call applyPlan when plan is empty'
        )

    def test_apply_onStaleServer_callsApplyPlan(self, monkeypatch):
        from src.server.migrations.versions import v0001_us195_us200_catch_up as m0001

        staleState = asm.SchemaState(
            tables=[
                asm.ColumnProbe(
                    tableName='realtime_data', exists=True,
                    hasDataSource=False, hasDriveId=False,
                    hasDriveIdIndex=False,
                ),
            ],
            hasDriveCounterTable=False,
        )
        monkeypatch.setattr(
            m0001, 'scanServerSchema',
            lambda addrs, creds, runner: staleState,
        )
        applyPlanCalls: list = []

        def _fakeApplyPlan(addrs, creds, runner, plan):
            applyPlanCalls.append(plan)
            return [(s, 0.01) for s, _ in plan.statements]

        monkeypatch.setattr(m0001, 'applyPlan', _fakeApplyPlan)
        m0001.apply(_makeCtx(FakeRunner()))
        assert len(applyPlanCalls) == 1
        assert not applyPlanCalls[0].isEmpty, (
            'stale server -> applyPlan should receive a non-empty plan'
        )


# ================================================================================
# apply_server_migrations.runRegistry -- the --run-all CLI entry point
# ================================================================================

class TestRunRegistryEntryPoint:
    def test_runRegistry_isCallable(self):
        # Smoke: the enhancement hook exists.
        assert hasattr(asm, 'runRegistry')
        assert callable(asm.runRegistry)

    def test_main_runAll_noopOnFullyMigrated(self, tmp_path, monkeypatch, capsys):
        # End-to-end: CLI parses --run-all, delegates to runRegistry, which
        # uses MigrationRunner(ALL_MIGRATIONS).runAll. Patch the moving
        # parts so we never touch a network.
        addressesPath = tmp_path / 'addresses.sh'
        addressesPath.write_text('#!/usr/bin/env bash\n', encoding='utf-8')

        monkeypatch.setattr(
            asm, 'loadAddresses',
            lambda path, runner=None: _addrs(),
        )
        monkeypatch.setattr(
            asm, 'loadServerCreds',
            lambda addrs, runner=None: _creds(),
        )
        from src.server.migrations.versions import v0001_us195_us200_catch_up as m0001
        monkeypatch.setattr(m0001, 'scanServerSchema',
                            lambda a, c, r: asm.SchemaState(
                                tables=[], hasDriveCounterTable=True,
                            ))
        monkeypatch.setattr(m0001, 'applyPlan', lambda *a, **kw: [])

        # Scripted runner: schema_migrations is already present + all
        # migrations are recorded as applied.
        appliedList = '\n'.join(m.version for m in ALL_MIGRATIONS) + '\n'

        def fakeRunner(argv, *, input=None, timeout=None):
            if input and 'SELECT version' in input:
                return _ok(stdout=appliedList)
            # US-462 preflight: a fully-migrated DB carries the drive-identity
            # FKs, so the applied-schema KEY_COLUMN_USAGE probe returns a name.
            if input and 'KEY_COLUMN_USAGE' in input:
                return _ok(stdout='fk_present\n')
            return _ok()

        monkeypatch.setattr(asm, '_defaultRunner', fakeRunner)
        rc = asm.main(['--run-all', '--addresses', str(addressesPath)])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'already applied' in out or '0 applied' in out or 'idempotent' in out

    def test_main_runAll_errorExitsNonZero(self, tmp_path, monkeypatch):
        addressesPath = tmp_path / 'addresses.sh'
        addressesPath.write_text('x', encoding='utf-8')
        monkeypatch.setattr(
            asm, 'loadAddresses',
            lambda path, runner=None: _addrs(),
        )
        monkeypatch.setattr(
            asm, 'loadServerCreds',
            lambda addrs, runner=None: _creds(),
        )

        # Scripted runner: EVERY mysql call fails.  ensureTracking fires
        # first and raises, so the registry never reads appliedRows.
        def fakeRunner(argv, *, input=None, timeout=None):
            return _fail('mariadb auth denied')

        monkeypatch.setattr(asm, '_defaultRunner', fakeRunner)
        rc = asm.main(['--run-all', '--addresses', str(addressesPath)])
        assert rc != 0
