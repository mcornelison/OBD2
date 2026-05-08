################################################################################
# File Name: test_sync_history_retention_migration.py
# Purpose/Description: Sprint 26 US-300 (B-053 Story 3, BL-010 close) -- TDD
#                      tests for the v0007 sync_history retention migration.
#                      Verifies the DELETE clause shape (DELETE FROM sync_history
#                      WHERE started_at < NOW() - INTERVAL 90 DAY) fires when
#                      the table exists, raises MigrationError when the table
#                      is missing, raises MigrationError on DELETE failure,
#                      raises SchemaProbeError when the post-condition probe
#                      shows old rows still present (silent no-op class), and
#                      uses the SYNC_HISTORY_RETENTION_DAYS env override when
#                      set.  FakeRunner mirrors v0004 / v0005 / v0006 tests so
#                      no live MariaDB or SSH is required.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex          | Initial -- Sprint 26 US-300 TDD (BL-010 close).
# ================================================================================
################################################################################

"""TDD tests for the US-300 / B-053 Story 3 sync_history retention migration."""

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
    v0007_sync_history_retention as m0007,
)

# ================================================================================
# FakeRunner -- request-aware scripted subprocess stand-in (mirrors v0004-v0006)
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


def _scriptTablePresentAndPostProbeClean(runner: FakeRunner) -> None:
    """Configure FakeRunner so:
      * pre-DELETE table-existence probe returns COUNT(*)=1 (table present)
      * post-DELETE row-count probe returns 0 (no stale rows remain)
    """
    probeCalls = {'n': 0}

    def tableProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        probeCalls['n'] += 1
        # First call: information_schema.TABLES probe -> 1 (present).
        return _ok(stdout='1\n')

    runner.handlers.append((
        'information_schema.TABLES',
        tableProbe,
    ))
    # Post-DELETE row-count probe -- COUNT(*) FROM sync_history WHERE started_at...
    runner.handlers.append((
        'COUNT(*) FROM sync_history',
        lambda _sql: _ok(stdout='0\n'),
    ))


def _scriptTableMissing(runner: FakeRunner) -> None:
    """Pre-condition probe reports table missing -- short-circuit error path."""
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='0\n'),
    ))


# ================================================================================
# Module shape
# ================================================================================


class TestModuleExports:
    def test_versionIs0007(self) -> None:
        assert m0007.VERSION == '0007'

    def test_descriptionMentionsB053(self) -> None:
        assert 'B-053' in m0007.DESCRIPTION

    def test_descriptionMentionsSyncHistory(self) -> None:
        assert 'sync_history' in m0007.DESCRIPTION

    def test_descriptionMentions90Days(self) -> None:
        assert '90' in m0007.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0007.MIGRATION.version == '0007'
        assert callable(m0007.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0007' in versions

    def test_appendedAtEnd(self) -> None:
        # TD-044 SemVer-shape regex (mirrors v0005 / v0006 tests).
        versions = [m.version for m in ALL_MIGRATIONS]
        assert re.match(r'^\d{4}$', versions[-1]) is not None

    def test_defaultRetentionIs90Days(self) -> None:
        assert m0007.RETENTION_DAYS_DEFAULT == 90

    def test_targetTableConstantIsSyncHistory(self) -> None:
        # Lock the table name -- BL-010 root cause was a sync_log/sync_history
        # naming conflation.  Pin the constant so the bug class can't return
        # via a future rename without breaking this test.
        assert m0007.TARGET_TABLE == 'sync_history'


# ================================================================================
# DDL shape -- must target sync_history with INTERVAL N DAY clause
# ================================================================================


class TestDeleteSqlShape:
    def test_deleteSqlTargetsSyncHistory(self) -> None:
        sql = m0007.buildDeleteSql(90)
        assert 'DELETE FROM sync_history' in sql

    def test_deleteSqlUsesStartedAtColumn(self) -> None:
        # SyncHistory.started_at is the DATETIME NOT NULL column on the live
        # table (src/server/db/models.py:469).  No other column matches.
        sql = m0007.buildDeleteSql(90)
        assert 'started_at' in sql

    def test_deleteSqlUsesIntervalDayClause(self) -> None:
        # MariaDB-native INTERVAL N DAY syntax (matches v0006 / models.py
        # DateTime column type; documented in BL-010 resolution).
        sql = m0007.buildDeleteSql(90)
        assert 'INTERVAL 90 DAY' in sql

    def test_deleteSqlDoesNotReferenceSyncLog(self) -> None:
        # BL-010 discriminator: the Pi-side `sync_log` cursor table MUST NOT
        # appear in this migration.  If a future refactor accidentally
        # reintroduces the wrong name, this test fails loudly.
        sql = m0007.buildDeleteSql(90)
        assert 'sync_log' not in sql

    def test_deleteSqlHonoursCustomDayCount(self) -> None:
        # Configurability invariant: the day-count is a parameter, not hardcoded.
        sql = m0007.buildDeleteSql(30)
        assert 'INTERVAL 30 DAY' in sql
        assert 'INTERVAL 90 DAY' not in sql


# ================================================================================
# apply -- happy path (table present, no stale rows post-DELETE)
# ================================================================================


class TestApplyHappyPath:
    def test_emitsExactlyOneDeleteAgainstSyncHistory(self) -> None:
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE FROM sync_history' in s]
        assert len(deletes) == 1, (
            f'expected exactly one DELETE FROM sync_history; got: {deletes}'
        )

    def test_emittedDeleteUsesNinetyDayHorizonByDefault(self) -> None:
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE FROM sync_history' in s]
        assert 'INTERVAL 90 DAY' in deletes[0]

    def test_runsPreProbeBeforeDelete(self) -> None:
        # Refusal of the BL-010 bug class: the migration MUST verify
        # sync_history exists before issuing DELETE.  Otherwise a stray
        # mysql session-context bug or a rename could silently fail.
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        sqls = runner.emittedSqls
        tableProbeIdx = next(
            i for i, s in enumerate(sqls)
            if 'information_schema.TABLES' in s and 'sync_history' in s
        )
        deleteIdx = next(
            i for i, s in enumerate(sqls) if 'DELETE FROM sync_history' in s
        )
        assert tableProbeIdx < deleteIdx, (
            'pre-condition probe must precede DELETE'
        )

    def test_runsPostConditionProbeAfterDelete(self) -> None:
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        sqls = runner.emittedSqls
        deleteIdx = next(
            i for i, s in enumerate(sqls) if 'DELETE FROM sync_history' in s
        )
        countProbeIdx = next(
            i for i, s in enumerate(sqls)
            if 'COUNT(*) FROM sync_history' in s
        )
        assert countProbeIdx > deleteIdx, (
            'post-condition row-count probe must run after DELETE'
        )

    def test_doesNotTouchPiSideSyncLog(self) -> None:
        # Pi-side sync_log is a 10-row cursor table -- orthogonal concern,
        # MUST NOT be referenced by this migration.  BL-010 invariant.
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        for sql in runner.emittedSqls:
            assert 'sync_log' not in sql, (
                f'sync_log must not appear in any emitted SQL; got: {sql!r}'
            )


# ================================================================================
# apply -- failure paths
# ================================================================================


class TestApplyFailureModes:
    def test_tableMissingRaisesMigrationError(self) -> None:
        # If sync_history doesn't exist on this server, something is deeply
        # wrong (likely a fresh DB pre-create_all, or a wrong default DB).
        # The migration must fail loud rather than silently no-op.
        runner = FakeRunner()
        _scriptTableMissing(runner)
        with pytest.raises(asm.MigrationError, match='sync_history'):
            m0007.apply(_ctx(runner))

    def test_tableMissingDoesNotEmitDelete(self) -> None:
        runner = FakeRunner()
        _scriptTableMissing(runner)
        with pytest.raises(asm.MigrationError):
            m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE' in s]
        assert deletes == [], (
            f'short-circuit on missing table must not emit DELETE; got: {deletes}'
        )

    def test_deleteFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        # Override: any DELETE fails with a representative MariaDB error.
        runner.handlers.insert(0, (
            'DELETE FROM sync_history',
            lambda _sql: _fail('Lock wait timeout exceeded'),
        ))
        with pytest.raises(asm.MigrationError, match='sync_history'):
            m0007.apply(_ctx(runner))

    def test_postProbeShowingStaleRowsRaisesSchemaProbeError(self) -> None:
        # Silent no-op class: DELETE returncode=0 but old rows still exist.
        # Mirrors v0005's "CREATE returned 0 but post-probe shows table
        # missing" guard.  Without this, the runner would silently record
        # the version against an unchanged retention state.
        runner = FakeRunner()
        # Table present pre-DELETE.
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        # Post-DELETE row-count probe reports 17 stale rows still present.
        runner.handlers.append((
            'COUNT(*) FROM sync_history',
            lambda _sql: _ok(stdout='17\n'),
        ))
        with pytest.raises(
            asm.SchemaProbeError, match='sync_history',
        ):
            m0007.apply(_ctx(runner))


# ================================================================================
# Configurable retention horizon (env override)
# ================================================================================


class TestRetentionHorizonOverride:
    """SYNC_HISTORY_RETENTION_DAYS env var overrides the 90-day default."""

    def test_envOverrideChangesIntervalClause(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('SYNC_HISTORY_RETENTION_DAYS', '30')
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE FROM sync_history' in s]
        assert 'INTERVAL 30 DAY' in deletes[0]
        assert 'INTERVAL 90 DAY' not in deletes[0]

    def test_envOverrideUnsetUsesDefault(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv('SYNC_HISTORY_RETENTION_DAYS', raising=False)
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE FROM sync_history' in s]
        assert 'INTERVAL 90 DAY' in deletes[0]

    def test_envOverrideInvalidFallsBackToDefault(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Garbage env value -- be conservative, fall back to the documented
        # 90-day default rather than silently dropping rows over a misparse.
        monkeypatch.setenv('SYNC_HISTORY_RETENTION_DAYS', 'not-a-number')
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE FROM sync_history' in s]
        assert 'INTERVAL 90 DAY' in deletes[0]

    def test_envOverrideNegativeFallsBackToDefault(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Negative day-count would mean "rows from the future" -- nonsensical.
        # Fall back to default rather than build a malformed clause.
        monkeypatch.setenv('SYNC_HISTORY_RETENTION_DAYS', '-5')
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE FROM sync_history' in s]
        assert 'INTERVAL 90 DAY' in deletes[0]


# ================================================================================
# Strong-test discriminator -- BL-010 bug class regression gate
# ================================================================================


class TestBl010BugClassDiscriminator:
    """Lock the contract that BL-010 found.

    BL-010 evidence (Rex audit, 2026-05-08):

        US-300 originally targeted nonexistent server `sync_log` table.
        Actual bloating table is `sync_history` (src/server/db/models.py:462).
        Pi-side `sync_log` is a 10-row cursor (src/pi/data/sync_log.py:152).

    These tests fail loudly if a future refactor reintroduces the wrong
    table name or accidentally widens the migration to touch the Pi-side
    cursor table.
    """

    def test_targetTableIsSyncHistoryNotSyncLog(self) -> None:
        # Pin the table name in BOTH the constant AND the emitted SQL.
        assert m0007.TARGET_TABLE == 'sync_history'
        sql = m0007.buildDeleteSql(90)
        assert 'sync_history' in sql

    def test_emittedSqlNeverReferencesSyncLogTable(self) -> None:
        # Across every code path (happy path, env override, etc.) `sync_log`
        # must never appear in the emitted SQL.  This is the single most
        # important regression gate for BL-010.
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        for sql in runner.emittedSqls:
            # Whole-word match -- "sync_history" contains "sync_h" not
            # "sync_log".  Use boundary check.
            assert not re.search(r'\bsync_log\b', sql), (
                f'sync_log must not appear in emitted SQL: {sql!r}'
            )

    def test_doesNotReferenceOtherTables(self) -> None:
        # Bug scope is narrow -- only sync_history.  No incidental DELETEs.
        runner = FakeRunner()
        _scriptTablePresentAndPostProbeClean(runner)
        m0007.apply(_ctx(runner))

        deletes = [s for s in runner.emittedSqls if 'DELETE' in s]
        for sql in deletes:
            for other in (
                'drive_summary', 'connection_log', 'realtime_data',
                'battery_health_log', 'dtc_log', 'analysis_history',
            ):
                assert other not in sql, (
                    f'incidental DELETE on {other!r}: {sql!r}'
                )
