################################################################################
# File Name: test_migration_0023_drop_stale_data_source_check.py
# Purpose/Description: Sprint 55 V0.29.9 (US-458) + Sprint 57 V0.29.11 (US-463 /
#                      BL-021) -- migration tests for v0023: DISCOVER every stale
#                      live data_source CHECK (schema-wide via
#                      INFORMATION_SCHEMA.CHECK_CONSTRAINTS on
#                      CHECK_CLAUSE LIKE '%data_source%'), then strip each by its
#                      SHAPE: an INLINE CHECK (CONSTRAINT_NAME == 'data_source',
#                      i.e. name == column) is stripped by a definition-
#                      preserving MODIFY COLUMN (DROP CONSTRAINT raises 1091 on an
#                      inline CHECK; DROP CHECK is not MariaDB syntax / 1064); a
#                      TABLE-LEVEL (ck_*) CHECK is dropped by DROP CONSTRAINT.
#                      Discovery-driven, idempotent, with a zero-survivor
#                      post-condition probe.  Forward-only; v0022 untouched.
#                      Hermetic stateful FakeRunner; no SSH, no MariaDB.  Note:
#                      the SQLite/create_all path CANNOT reproduce 1091/1064/
#                      inline-CHECK semantics -- a green in-loop test does NOT
#                      validate the MariaDB DDL (US-464's real-MariaDB test +
#                      the live deploy are US-463's TRUE acceptance).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-05    | Rex (US-458) | Initial -- v0023 drop stale data_source CHECK.
# 2026-07-13    | Rex (US-463) | BL-021 -- inline CHECKs stripped via MODIFY
#               |              | COLUMN (preserving the introspected def), not
#               |              | DROP CONSTRAINT; table-level branch retained.
# ================================================================================
################################################################################

"""TDD tests for the v0023 strip-stale-data_source-CHECK migration (US-458/463)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0023_us458_drop_stale_data_source_check as m0023

# ================================================================================
# Stateful FakeRunner -- models the live DB's data_source CHECK set + column
# defs.  Discovery returns the CHECKs still present; an inline strip (MODIFY
# COLUMN) or a table-level DROP CONSTRAINT removes the matching one; the
# post-probe re-discovery therefore naturally reflects the strips.  No SSH,
# no MariaDB -- and no way to reproduce the real 1091/1064 (that is US-464 +
# the live deploy); this proves the CONTROL FLOW + SQL shape only.
# ================================================================================


def _ok(stdout: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


# The live definition Atlas introspected for all 5 tables (BL-021 ruling):
# VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
# DEFAULT 'real'.  mysql -B -N returns this as one tab-delimited row.
_LIVE_COLDEF: tuple[str, str, str, str, str] = (
    'varchar(16)',
    'utf8mb4',
    'utf8mb4_unicode_ci',
    'NO',
    "'real'",
)


def _alterTable(sql: str) -> str:
    """Return the table named right after ``ALTER TABLE`` in a DDL statement."""
    return sql.split('ALTER TABLE', 1)[1].split()[0].strip()


def _introspectTable(sql: str) -> str:
    """Return the table name from an introspection ``TABLE_NAME='...'`` clause."""
    return sql.split("TABLE_NAME='", 1)[1].split("'", 1)[0]


@dataclass
class FakeRunner:
    # (table, constraint) pairs currently present on the "live DB".  An inline
    # CHECK has constraint == 'data_source'; a table-level one has a ck_* name.
    checks: list[tuple[str, str]] = field(default_factory=list)
    # Live column def per table for the data_source column (introspection source).
    colDefs: dict[str, tuple[str, str, str, str, str]] = field(default_factory=dict)
    # If set, discovery queries fail (info_schema unreachable).
    failDiscovery: bool = False
    # If set, the column-def introspection for this table fails.
    failIntrospect: str | None = None
    # If set, the MODIFY COLUMN on this table fails (and it is NOT stripped).
    failModify: str | None = None
    # If set, the DROP CONSTRAINT of this name fails (and it is NOT removed).
    failDrop: str | None = None
    # If True, a MODIFY returns success but does NOT strip -- models the silent
    # no-op / wrong-session-context class the post-probe must catch.
    modifyNoOp: bool = False
    # If True, a DROP returns success but does NOT remove the check.
    dropNoOp: bool = False
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = input or ''
        self.calls.append({'argv': list(argv), 'input': sql})
        if 'CHECK_CONSTRAINTS' in sql:
            if self.failDiscovery:
                return _fail('information_schema unreachable')
            body = ''.join(f'{t}\t{c}\n' for t, c in self.checks)
            return _ok(body)
        if 'information_schema.COLUMNS' in sql and 'COLUMN_TYPE' in sql:
            table = _introspectTable(sql)
            if self.failIntrospect is not None and table == self.failIntrospect:
                return _fail('information_schema.COLUMNS unreachable')
            row = self.colDefs.get(table)
            if row is None:
                return _ok('')  # column not found -> empty row
            return _ok('\t'.join(row) + '\n')
        if 'MODIFY COLUMN' in sql:
            table = _alterTable(sql)
            if self.failModify is not None and table == self.failModify:
                return _fail(f"Can't MODIFY {table}: lock wait timeout")
            if not self.modifyNoOp:
                # Re-declaring the column strips its inline data_source CHECK.
                self.checks = [
                    (t, c)
                    for (t, c) in self.checks
                    if not (t == table and c == m0023.DATA_SOURCE_COLUMN)
                ]
            return _ok('')
        if 'DROP CONSTRAINT' in sql:
            name = sql.split('DROP CONSTRAINT', 1)[1].strip().rstrip(';').strip()
            if self.failDrop is not None and name == self.failDrop:
                return _fail(f"Can't DROP {name}: lock wait timeout")
            if not self.dropNoOp:
                self.checks = [(t, c) for (t, c) in self.checks if c != name]
            return _ok('')
        return _ok('')

    @property
    def emittedSqls(self) -> list[str]:
        return [c['input'] for c in self.calls if c['input']]


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _modifies(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if 'MODIFY COLUMN' in s]


def _drops(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if 'DROP CONSTRAINT' in s]


def _discoveries(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if 'CHECK_CONSTRAINTS' in s]


# The 5 tables Atlas verified (BL-019 A' / BL-021).  All 5 carry an INLINE
# data_source CHECK -- MariaDB names an inline (column-level) CHECK after the
# column, so CONSTRAINT_NAME == 'data_source'.
_INLINE_STALE_CHECKS: list[tuple[str, str]] = [
    (t, m0023.DATA_SOURCE_COLUMN) for t in m0023.EXPECTED_STALE_CHECK_TABLES
]


def _liveColDefs() -> dict[str, tuple[str, str, str, str, str]]:
    return {t: _LIVE_COLDEF for t in m0023.EXPECTED_STALE_CHECK_TABLES}


def _inlineRunner() -> FakeRunner:
    return FakeRunner(checks=list(_INLINE_STALE_CHECKS), colDefs=_liveColDefs())


# ================================================================================
# Registry + version
# ================================================================================


class TestRegistration:
    def test_versionIs0023(self) -> None:
        assert m0023.VERSION == '0023'

    def test_v0023RegisteredAfterV0022AndSorted(self) -> None:
        # Placement, not the absolute tail: present, tuple sorted, directly
        # after v0022.  (Avoids the brittle `versions[-1] == '0023'` trap that
        # re-breaks on every later migration -- the v0018 lesson.)
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0023' in versions
        assert versions[versions.index('0023') - 1] == '0022'

    def test_v0022NotRedefinedForwardOnly(self) -> None:
        assert m0023.VERSION not in {'0022'}


# ================================================================================
# SQL shape -- discovery, drop, introspect, modify
# ================================================================================


class TestDiscoverySql:
    def test_discoverySelectsTableAndConstraintFromCheckConstraints(self) -> None:
        sql = m0023.discoverDataSourceCheckSql('obd2db')
        assert sql.startswith(
            'SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS',
        )

    def test_discoveryFiltersBySchemaAndDataSourceClause(self) -> None:
        sql = m0023.discoverDataSourceCheckSql('obd2db')
        assert "CONSTRAINT_SCHEMA='obd2db'" in sql
        # The LIKE on CHECK_CLAUSE is what isolates the data_source CHECK from
        # every data_quality CHECK (whose clause never contains 'data_source').
        assert "CHECK_CLAUSE LIKE '%data_source%'" in sql


class TestDropSql:
    def test_dropConstraintByDiscoveredName(self) -> None:
        # Retained for the table-level (ck_*) branch.
        sql = m0023.dropConstraintSql('realtime_data', 'ck_realtime_data_data_source')
        assert sql == (
            'ALTER TABLE realtime_data DROP CONSTRAINT ck_realtime_data_data_source;'
        )


class TestIntrospectSql:
    def test_selectsTheModifyPreservingAttributes(self) -> None:
        sql = m0023.introspectColumnDefSql('obd2db', 'realtime_data', 'data_source')
        assert 'FROM information_schema.COLUMNS' in sql
        for col in (
            'COLUMN_TYPE',
            'CHARACTER_SET_NAME',
            'COLLATION_NAME',
            'IS_NULLABLE',
            'COLUMN_DEFAULT',
        ):
            assert col in sql

    def test_filtersBySchemaTableColumn(self) -> None:
        sql = m0023.introspectColumnDefSql('obd2db', 'realtime_data', 'data_source')
        assert "TABLE_SCHEMA='obd2db'" in sql
        assert "TABLE_NAME='realtime_data'" in sql
        assert "COLUMN_NAME='data_source'" in sql


class TestModifyColumnSql:
    def test_preservesEveryIntrospectedAttributeAndDropsCheck(self) -> None:
        colDef = m0023.ColumnDef(
            columnType='varchar(16)',
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci',
            notNull=True,
            default="'real'",
        )
        sql = m0023.modifyColumnStripCheckSql('realtime_data', 'data_source', colDef)
        assert sql == (
            'ALTER TABLE realtime_data MODIFY COLUMN data_source varchar(16) '
            'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL '
            "DEFAULT 'real';"
        )
        # The whole point: re-declaring the column carries NO CHECK, so the
        # inline CHECK that was part of the old definition is dropped.
        assert 'CHECK' not in sql

    def test_omitsDefaultWhenNoneAndEmitsExplicitNullable(self) -> None:
        colDef = m0023.ColumnDef(
            columnType='varchar(16)',
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci',
            notNull=False,
            default=None,
        )
        sql = m0023.modifyColumnStripCheckSql('profiles', 'data_source', colDef)
        assert 'DEFAULT' not in sql
        assert sql.endswith('NULL;')
        assert 'NOT NULL' not in sql

    def test_omitsCharsetCollateWhenAbsent(self) -> None:
        # A non-string column (defensive): no charset/collation to preserve.
        colDef = m0023.ColumnDef(
            columnType='int(11)', charset=None, collation=None,
            notNull=True, default='0',
        )
        sql = m0023.modifyColumnStripCheckSql('t', 'c', colDef)
        assert 'CHARACTER SET' not in sql
        assert 'COLLATE' not in sql
        assert sql == 'ALTER TABLE t MODIFY COLUMN c int(11) NOT NULL DEFAULT 0;'


class TestExpectedTables:
    def test_documentsTheFiveAtlasNamedTables(self) -> None:
        # Coverage-intent constant; the strip itself is discovery-driven.
        assert set(m0023.EXPECTED_STALE_CHECK_TABLES) == {
            'realtime_data',
            'statistics',
            'connection_log',
            'profiles',
            'calibration_sessions',
        }

    def test_dataSourceColumnConstant(self) -> None:
        assert m0023.DATA_SOURCE_COLUMN == 'data_source'


# ================================================================================
# apply() behavior -- inline branch (MODIFY COLUMN), coverage, idempotency,
# failure modes
# ================================================================================


class TestApplyInlineBranch:
    def test_stripsEveryInlineCheckViaModifyColumn(self) -> None:
        runner = _inlineRunner()
        m0023.apply(_ctx(runner))
        modifies = _modifies(runner)
        assert len(modifies) == len(_INLINE_STALE_CHECKS)
        # An inline CHECK must NEVER be dropped via DROP CONSTRAINT (1091).
        assert _drops(runner) == []
        for table in m0023.EXPECTED_STALE_CHECK_TABLES:
            assert any(
                f'ALTER TABLE {table} MODIFY COLUMN data_source' in s
                for s in modifies
            ), f'no MODIFY COLUMN emitted for {table}'

    def test_modifyPreservesTheIntrospectedColumnDef(self) -> None:
        runner = _inlineRunner()
        m0023.apply(_ctx(runner))
        for s in _modifies(runner):
            # collation/default/nullability/length all re-stated; no CHECK.
            assert 'varchar(16)' in s
            assert 'CHARACTER SET utf8mb4' in s
            assert 'COLLATE utf8mb4_unicode_ci' in s
            assert 'NOT NULL' in s
            assert "DEFAULT 'real'" in s
            assert 'CHECK' not in s

    def test_introspectsBeforeModifying(self) -> None:
        """The live def must be READ before the column is re-declared, else the
        MODIFY would reset attributes it never observed."""
        runner = _inlineRunner()
        m0023.apply(_ctx(runner))
        emitted = runner.emittedSqls
        first_introspect = next(
            i for i, s in enumerate(emitted)
            if 'information_schema.COLUMNS' in s and 'COLUMN_TYPE' in s
        )
        first_modify = next(i for i, s in enumerate(emitted) if 'MODIFY COLUMN' in s)
        assert first_introspect < first_modify

    def test_allInlineChecksRemovedAfterApply(self) -> None:
        runner = _inlineRunner()
        m0023.apply(_ctx(runner))
        assert runner.checks == []

    def test_modifiesPrecedeFinalPostProbe(self) -> None:
        runner = _inlineRunner()
        m0023.apply(_ctx(runner))
        emitted = runner.emittedSqls
        last_modify = max(i for i, s in enumerate(emitted) if 'MODIFY COLUMN' in s)
        last_discovery = max(
            i for i, s in enumerate(emitted) if 'CHECK_CONSTRAINTS' in s
        )
        assert last_modify < last_discovery

    def test_reRunsDiscoveryAsPostProbe(self) -> None:
        runner = _inlineRunner()
        m0023.apply(_ctx(runner))
        assert len(_discoveries(runner)) == 2


class TestApplyTableLevelBranch:
    def test_tableLevelCheckDroppedViaDropConstraint(self) -> None:
        """A genuinely table-level (ck_*) constraint keeps the DROP CONSTRAINT
        path -- no MODIFY COLUMN, no introspection needed."""
        runner = FakeRunner(checks=[('statistics', 'ck_statistics_data_source')])
        m0023.apply(_ctx(runner))
        drops = _drops(runner)
        assert drops == [
            'ALTER TABLE statistics DROP CONSTRAINT ck_statistics_data_source;',
        ]
        assert _modifies(runner) == []
        assert runner.checks == []

    def test_mixedInlineAndTableLevelBranchIndependently(self) -> None:
        runner = FakeRunner(
            checks=[
                ('realtime_data', 'data_source'),  # inline
                ('statistics', 'ck_statistics_data_source'),  # table-level
            ],
            colDefs={'realtime_data': _LIVE_COLDEF},
        )
        m0023.apply(_ctx(runner))
        assert any('MODIFY COLUMN data_source' in s for s in _modifies(runner))
        assert any(
            'DROP CONSTRAINT ck_statistics_data_source' in s for s in _drops(runner)
        )
        assert runner.checks == []


class TestApplyIdempotencyAndFailures:
    def test_idempotentReplayNoChecksNoStrip(self) -> None:
        """Fresh create_all DB / already-migrated replay: discovery returns 0
        rows -> no MODIFY / no DROP -> zero-survivor post-probe passes."""
        runner = FakeRunner(checks=[])
        m0023.apply(_ctx(runner))  # must not raise
        assert _modifies(runner) == []
        assert _drops(runner) == []
        # Two discovery calls: the pre-strip scan and the post-condition probe.
        assert len(_discoveries(runner)) == 2

    def test_discoveryFailureRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner(checks=list(_INLINE_STALE_CHECKS), failDiscovery=True)
        with pytest.raises(asm.SchemaProbeError, match='discovery probe failed'):
            m0023.apply(_ctx(runner))

    def test_introspectFailureRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner(
            checks=[('realtime_data', 'data_source')],
            colDefs={'realtime_data': _LIVE_COLDEF},
            failIntrospect='realtime_data',
        )
        with pytest.raises(asm.SchemaProbeError, match='introspection failed'):
            m0023.apply(_ctx(runner))

    def test_introspectMissingColumnRaisesSchemaProbeError(self) -> None:
        # Discovery says there's an inline CHECK, but the column def comes back
        # empty (wrong DB context) -> never MODIFY a column we couldn't read.
        runner = FakeRunner(checks=[('realtime_data', 'data_source')], colDefs={})
        with pytest.raises(asm.SchemaProbeError, match='not found'):
            m0023.apply(_ctx(runner))

    def test_modifyFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner(
            checks=[('statistics', 'data_source')],
            colDefs={'statistics': _LIVE_COLDEF},
            failModify='statistics',
        )
        with pytest.raises(asm.MigrationError, match='statistics'):
            m0023.apply(_ctx(runner))

    def test_dropFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner(
            checks=[('statistics', 'ck_statistics_data_source')],
            failDrop='ck_statistics_data_source',
        )
        with pytest.raises(asm.MigrationError, match='ck_statistics_data_source'):
            m0023.apply(_ctx(runner))

    def test_survivingInlineCheckRaisesSchemaProbeError(self) -> None:
        """If a MODIFY is silently skipped (wrong DB context / filtered replica),
        it returns success but the CHECK persists -- the post-probe re-discovers
        the survivor and fails loud rather than recording success over drift."""
        runner = FakeRunner(
            checks=[('realtime_data', 'data_source')],
            colDefs={'realtime_data': _LIVE_COLDEF},
            modifyNoOp=True,
        )
        with pytest.raises(asm.SchemaProbeError, match='survive'):
            m0023.apply(_ctx(runner))
