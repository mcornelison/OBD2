################################################################################
# File Name: test_migration_0004_drive_summary_reconcile.py
# Purpose/Description: Sprint 19 US-237 -- migration unit tests.  Verifies the
#                      v0004 catch-up DDL emits the right ALTER + DELETE SQL
#                      against a stale (Sprint 7-8) drive_summary shape, is a
#                      no-op against a fully-migrated DB, propagates DDL
#                      failures, and surfaces post-condition probe errors when
#                      the DELETE silently no-ops or a column fails to land.
#                      FakeRunner mirrors the pattern from
#                      tests/server/test_migrations.py so no live MariaDB or
#                      SSH is required.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex          | Initial -- Sprint 19 US-237 TDD.
# ================================================================================
################################################################################

"""TDD tests for the US-237 / V-1 + V-4 drive_summary reconcile migration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0004_us237_drive_summary_reconcile as m0004,
)

# ================================================================================
# FakeRunner -- request-aware scripted subprocess stand-in
# ================================================================================

# Sentinel to distinguish "default 0-rows" from a deliberate empty stdout.
_DEFAULT = object()


@dataclass
class FakeRunner:
    """Scripted runner.  Caller registers handlers keyed by SQL substring;
    each handler returns a CompletedProcess.  Calls that don't match a
    handler return a generic OK (returncode 0, empty stdout) so probes
    behave deterministically.
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

    # Convenience -- scripts where every match returns a fixed string.
    def respondWith(
        self, needle: str, stdout: str = '', stderr: str = '', returncode: int = 0,
    ) -> None:
        cp = subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=stderr,
        )
        self.handlers.append((needle, lambda _sql: cp))

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


# Pre-Sprint-7-8-era column set (what the live MariaDB actually had on
# 2026-04-29).  Per Ralph's V-1 finding in
# offices/pm/inbox/2026-04-29-from-ralph-post-deploy-system-health-drive4.md.
LEGACY_COLS: tuple[str, ...] = (
    'id', 'device_id', 'start_time', 'end_time',
    'duration_seconds', 'profile_id', 'row_count', 'created_at',
)

# Post-migration column set (legacy + every column the ORM declares).
POST_MIGRATION_COLS: tuple[str, ...] = LEGACY_COLS + tuple(
    name for name, _ in m0004.DRIVE_SUMMARY_NEW_COLUMNS
)


def _scriptStaleProbes(runner: FakeRunner, *, postState: bool = False) -> None:
    """Configure a FakeRunner so probes report stale state pre-DDL and
    post-migration state post-DDL.

    The migration emits two column probes (pre-ALTER + post-ALTER
    verification).  In production the second probe hits a real DB that
    now has the ALTERed columns; here we simulate that by flipping the
    response on the second call.

    * ``serverTableExists('drive_summary')`` -> 1
    * ``probeServerColumns('drive_summary')`` first call -> LEGACY_COLS
      (or POST when ``postState=True``); subsequent calls -> POST.
    * indexExists -> 0 (stale) or 1 (post)
    * ``SELECT COUNT(*) ... legacy`` -> 0 (DELETEs landed) or 9 (no-op)
    """
    # serverTableExists uses information_schema.TABLES count.
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))

    # probeServerColumns uses information_schema.COLUMNS.  First call
    # returns the pre-migration shape so the migration knows what to
    # ALTER; second call returns the post-migration shape so the
    # post-condition probe passes.  When postState=True we report the
    # post shape from the start (idempotent re-run path).
    colCalls = {'n': 0}

    def colProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        colCalls['n'] += 1
        cols = (
            POST_MIGRATION_COLS
            if (postState or colCalls['n'] >= 2)
            else LEGACY_COLS
        )
        return _ok(stdout='\n'.join(cols) + '\n')

    runner.handlers.append((
        'information_schema.COLUMNS',
        colProbe,
    ))
    # indexExists uses information_schema.STATISTICS.
    runner.handlers.append((
        'information_schema.STATISTICS',
        lambda _sql: _ok(stdout='1\n' if postState else '0\n'),
    ))
    # Post-condition COUNT(*) ... device_id IN (...sim list...).
    # DELETE on a stale shape removes 9 rows -> COUNT is 0.
    # On postState the rows were already gone -> still 0.
    runner.handlers.append((
        'SELECT COUNT(*) FROM drive_summary WHERE device_id IN',
        lambda _sql: _ok(stdout='0\n'),
    ))


# ================================================================================
# Module shape
# ================================================================================

class TestModuleExports:
    def test_versionIs0004(self) -> None:
        assert m0004.VERSION == '0004'

    def test_descriptionMentionsUs237(self) -> None:
        assert 'US-237' in m0004.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0004.MIGRATION.version == '0004'
        assert callable(m0004.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0004' in versions

    def test_appendsAfterV0003(self) -> None:
        # Ascending order invariant from MigrationRunner contract.  Locked
        # against v0003's position rather than the tail so future migrations
        # (US-238 v0005, etc.) don't bounce this test on every sprint.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions.index('0004') == versions.index('0003') + 1

    def test_legacyDeviceIdsLockedToThree(self) -> None:
        # CIO directive 2026-04-29 named exactly these three; locking
        # the count makes accidental scope-creep visible.
        assert m0004.LEGACY_SIM_DEVICE_IDS == (
            'sim-eclipse-gst',
            'sim-eclipse-gst-multi',
            'eclipse-gst-day1',
        )

    def test_columnListMirrorsOrm(self) -> None:
        """Every name in DRIVE_SUMMARY_NEW_COLUMNS must exist on the ORM model."""
        from src.server.db.models import DriveSummary

        ormCols = {c.name for c in DriveSummary.__table__.columns}
        for name, _type in m0004.DRIVE_SUMMARY_NEW_COLUMNS:
            assert name in ormCols, (
                f'migration column {name!r} not declared on DriveSummary ORM'
            )


# ================================================================================
# apply -- fresh-DB short-circuit
# ================================================================================

class TestApplyFreshDb:
    def test_tableMissing_isNoOp(self) -> None:
        # Fresh DB: SQLAlchemy create_all() owns table creation; the
        # migration must NOT issue any ALTER / DELETE.
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        m0004.apply(_ctx(runner))
        ddlOrDml = [s for s in runner.emittedSqls
                    if 'ALTER' in s or s.startswith('DELETE')]
        assert ddlOrDml == [], (
            'fresh-DB short-circuit must not emit ALTER or DELETE'
        )


# ================================================================================
# apply -- stale (Sprint 7-8) DB
# ================================================================================

class TestApplyStaleDb:
    def test_emitsAlterForEveryMissingColumn(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))

        # Every column in DRIVE_SUMMARY_NEW_COLUMNS must show up in an
        # ALTER ... ADD COLUMN ... emission.
        emitted = ' | '.join(runner.emittedSqls)
        for colName, _colType in m0004.DRIVE_SUMMARY_NEW_COLUMNS:
            assert (
                f'ALTER TABLE drive_summary ADD COLUMN {colName} ' in emitted
            ), f'expected ALTER for {colName}; got: {emitted}'

    def test_emitsAlterAddIndex(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        joined = ' | '.join(runner.emittedSqls)
        assert (
            f'ADD INDEX {m0004.DRIVE_SUMMARY_INDEX_NAME} (drive_id)' in joined
        )

    def test_emitsAlterAddUnique(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        joined = ' | '.join(runner.emittedSqls)
        assert (
            f'ADD UNIQUE KEY {m0004.DRIVE_SUMMARY_UNIQUE_NAME} '
            '(source_device, source_id)' in joined
        )

    def test_emitsCascadeDeleteForDriveStatistics(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        cascade = [
            s for s in runner.emittedSqls
            if 'DELETE FROM drive_statistics' in s
        ]
        assert cascade, 'expected one cascade-delete on drive_statistics'
        # Sub-select must reference the legacy device filter.
        sql = cascade[0]
        for d in m0004.LEGACY_SIM_DEVICE_IDS:
            assert f"'{d}'" in sql

    def test_emitsLegacyDeleteOnDriveSummary(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        # The legacy-row delete is exactly:
        # 'DELETE FROM drive_summary WHERE device_id IN (...)'
        legacyDeletes = [
            s for s in runner.emittedSqls
            if s.startswith('DELETE FROM drive_summary WHERE device_id IN')
        ]
        assert legacyDeletes, (
            'expected one legacy DELETE on drive_summary'
        )

    def test_cascadeDeletePrecedesParentDelete(self) -> None:
        """Cascade child rows BEFORE the parent rows so no FK orphans."""
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        emitted = runner.emittedSqls
        cascadeIdx = next(
            i for i, s in enumerate(emitted)
            if 'DELETE FROM drive_statistics' in s
        )
        parentIdx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('DELETE FROM drive_summary WHERE device_id IN')
        )
        assert cascadeIdx < parentIdx, (
            'drive_statistics cascade must run before drive_summary parent delete'
        )

    def test_emissionOrder_alterBeforeDelete(self) -> None:
        """All ALTER must precede all DELETE so post-migration probes see new schema."""
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        emitted = runner.emittedSqls
        lastAlter = max(
            (i for i, s in enumerate(emitted) if 'ALTER TABLE drive_summary' in s),
            default=-1,
        )
        firstDelete = min(
            (i for i, s in enumerate(emitted) if s.startswith('DELETE FROM ')),
            default=10**9,
        )
        assert lastAlter < firstDelete, (
            'ALTER statements must precede DELETE statements'
        )


# ================================================================================
# apply -- already-migrated DB (idempotent re-run path)
# ================================================================================

class TestApplyIdempotent:
    def test_postMigratedDb_emitsNoAlter(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner, postState=True)
        m0004.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if 'ALTER' in s]
        assert alters == [], (
            f'idempotent run must not emit ALTER; got: {alters}'
        )

    def test_postMigratedDb_stillRunsDeletes(self) -> None:
        # DELETE phases run unconditionally; on a post-migrated DB they
        # match 0 rows but still emit (cheap; harmless).  Only failure
        # would be a hard-coded "skip if already migrated" gate.
        runner = FakeRunner()
        _scriptStaleProbes(runner, postState=True)
        m0004.apply(_ctx(runner))
        deletes = [s for s in runner.emittedSqls if s.startswith('DELETE')]
        assert len(deletes) == 2, (
            'expected cascade + parent DELETE even on migrated DB'
        )


# ================================================================================
# Failure paths
# ================================================================================

class TestFailureModes:
    def test_alterFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        # Override: any ALTER fails.
        runner.handlers.insert(0, (
            'ALTER TABLE drive_summary ADD COLUMN',
            lambda _sql: _fail('Cannot add column source_id'),
        ))
        with pytest.raises(asm.MigrationError, match='source_id'):
            m0004.apply(_ctx(runner))

    def test_deleteFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        runner.handlers.insert(0, (
            'DELETE FROM drive_statistics',
            lambda _sql: _fail('FK lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_statistics'):
            m0004.apply(_ctx(runner))

    def test_postProbeColumnMissingRaisesSchemaProbeError(self) -> None:
        # All ALTERs "succeed" but the post-probe still reports a stale
        # column list -- mysql session-context bug.  The migration MUST
        # NOT silently record success.
        runner = FakeRunner()

        # First column probe: stale (triggers ALTERs).
        # Second column probe (post): still stale (silent no-op).
        col_calls = {'n': 0}

        def colProbe(_sql: str) -> subprocess.CompletedProcess[str]:
            col_calls['n'] += 1
            return _ok(stdout='\n'.join(LEGACY_COLS) + '\n')

        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        runner.handlers.append((
            'information_schema.COLUMNS',
            colProbe,
        ))
        runner.handlers.append((
            'information_schema.STATISTICS',
            lambda _sql: _ok(stdout='0\n'),
        ))
        runner.handlers.append((
            'SELECT COUNT(*) FROM drive_summary WHERE device_id IN',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.SchemaProbeError, match='columns missing'):
            m0004.apply(_ctx(runner))
        assert col_calls['n'] >= 2  # pre + post probes both fired

    def test_postProbeSimRowsRemainRaisesSchemaProbeError(self) -> None:
        # The post-DELETE COUNT comes back non-zero -- silent failure mode
        # we want to make loud.
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        # Mid-run: stale columns; post-run: full columns (so column-probe passes).
        col_calls = {'n': 0}

        def colProbe(_sql: str) -> subprocess.CompletedProcess[str]:
            col_calls['n'] += 1
            cols = LEGACY_COLS if col_calls['n'] == 1 else POST_MIGRATION_COLS
            return _ok(stdout='\n'.join(cols) + '\n')

        runner.handlers.append((
            'information_schema.COLUMNS',
            colProbe,
        ))
        runner.handlers.append((
            'information_schema.STATISTICS',
            lambda _sql: _ok(stdout='0\n'),
        ))
        # Post-DELETE COUNT(*) returns 9 -- DELETE silently no-opped.
        runner.handlers.append((
            'SELECT COUNT(*) FROM drive_summary WHERE device_id IN',
            lambda _sql: _ok(stdout='9\n'),
        ))
        with pytest.raises(asm.SchemaProbeError, match='legacy sim'):
            m0004.apply(_ctx(runner))


# ================================================================================
# Strong-test discriminator -- pre-US-237 vs post-US-237 codebase divergence
# ================================================================================

class TestProductionFailureModeDiscriminator:
    """Verify the migration emits the SQL that resolves V-1's specific bug.

    The Drive 4 health check found 148 sync failures with:

        Unknown column 'drive_summary.source_id' in 'SELECT'

    The fix MUST add ``source_id`` and ``source_device`` columns and a
    UNIQUE key on the pair.  These tests fail loudly if a future refactor
    drops any of those three pieces.
    """

    def test_addsSourceIdColumn(self) -> None:
        names = [c for c, _t in m0004.DRIVE_SUMMARY_NEW_COLUMNS]
        assert 'source_id' in names

    def test_addsSourceDeviceColumn(self) -> None:
        names = [c for c, _t in m0004.DRIVE_SUMMARY_NEW_COLUMNS]
        assert 'source_device' in names

    def test_uniqueKeyOnSourceDeviceSourceId(self) -> None:
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        joined = ' | '.join(runner.emittedSqls)
        # Both the column order AND the index name must match the ORM
        # contract; the sync upsert handler queries ON DUPLICATE KEY
        # against this exact (source_device, source_id) pair.
        assert '(source_device, source_id)' in joined

    def test_runsAgainstStaleSchemaProducesAtLeastElevenAlters(self) -> None:
        """Concrete count of ALTER ... ADD COLUMN against a Sprint 7-8 shape.

        Locks the scope: 11 missing columns means the migration reaches
        every ORM-declared US-206/US-195/US-200 column.  Drift catches
        on test failure if a future change drops one.
        """
        runner = FakeRunner()
        _scriptStaleProbes(runner)
        m0004.apply(_ctx(runner))
        addColumns = [
            s for s in runner.emittedSqls
            if 'ALTER TABLE drive_summary ADD COLUMN' in s
        ]
        assert len(addColumns) == 11
