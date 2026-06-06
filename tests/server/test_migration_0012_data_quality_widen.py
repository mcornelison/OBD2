################################################################################
# File Name: test_migration_0012_data_quality_widen.py
# Purpose/Description: Sprint 45 V0.28.2 (US-377 / F-107) -- regression guard +
#                      migration unit tests for the data_quality column-width
#                      hotfix.  The V0.28.1 IRL drill hit MariaDB DataError 1406
#                      ("Data too long") recomputing the dual-attribution drives
#                      23+24: drive_summary.data_quality and
#                      drive_statistics.data_quality were VARCHAR(16) but their
#                      own CHECK enums permit 'attribution_anomaly' (19 chars).
#                      SQLite (no width enforcement) never caught it.  This file
#                      adds:
#                        (1) a width-INVARIANT guard -- every CHECK ``IN (...)``
#                            enum column must be wide enough for its longest
#                            permitted value (the SSOT regression guard), and
#                        (2) v0012 migration tests -- MODIFY both columns to
#                            VARCHAR(20), idempotent via a CHARACTER_MAXIMUM_LENGTH
#                            probe, failure propagation, registry registration.
#                      Mirrors test_migration_0010's FakeRunner shape; hermetic,
#                      no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-377) | Initial -- data_quality VARCHAR(16)->VARCHAR(20)
#               |              | width hotfix; width-invariant guard + v0012
#               |              | migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0012 data_quality column-width hotfix (US-377 / F-107)."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    DATA_QUALITY_COLUMN_LENGTH,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
    Base,
    DriveStatistic,
    DriveSummary,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0012_us377_data_quality_widen as m0012,
)

# ================================================================================
# Width INVARIANT -- the load-bearing regression guard
# ================================================================================
#
# A VARCHAR column fronted by a CHECK ``col IN ('a','b',...)`` constraint must be
# at least as wide as its longest permitted value, or an INSERT/UPDATE of that
# value fails on MariaDB (DataError 1406) while passing silently on SQLite.  The
# V0.27.18 dual-attribution tripwire ('attribution_anomaly', 19 chars) tripped
# exactly this on a VARCHAR(16) column.  These tests pin the invariant so the
# SQLite-vs-MariaDB false-pass class cannot regress.


_DATA_QUALITY_COLUMNS = (
    (DriveSummary, DRIVE_SUMMARY_DATA_QUALITY_VALUES),
    (DriveStatistic, DRIVE_STATISTICS_DATA_QUALITY_VALUES),
)


class TestDataQualityColumnWidthInvariant:
    @pytest.mark.parametrize(
        ('model', 'values'),
        _DATA_QUALITY_COLUMNS,
        ids=lambda arg: arg.__tablename__ if hasattr(arg, '__tablename__') else '',
    )
    def test_dataQualityColumnWideEnoughForLongestCheckValue(
        self, model: type, values: tuple[str, ...],
    ) -> None:
        """
        Given: a data_quality column with a CHECK enum permitting
               'attribution_anomaly' (19 chars)
        When:  we read the ORM column's declared String length
        Then:  the length is >= the longest permitted value
        """
        column = model.__table__.columns['data_quality']
        longest = max(len(v) for v in values)
        assert column.type.length is not None
        assert column.type.length >= longest, (
            f'{model.__tablename__}.data_quality is VARCHAR'
            f'({column.type.length}) but its CHECK enum permits a '
            f'{longest}-char value; widen the column or a MariaDB '
            f'INSERT/UPDATE of that value raises DataError 1406.'
        )

    def test_attributionAnomalyFitsBothColumns(self) -> None:
        """The specific value that tripped the V0.28.1 drill must fit."""
        for model, _values in _DATA_QUALITY_COLUMNS:
            column = model.__table__.columns['data_quality']
            assert column.type.length >= len('attribution_anomaly')


# ================================================================================
# Width INVARIANT -- generic audit over EVERY CHECK ``IN (...)`` enum column
# ================================================================================
#
# US-377 conditionalOutcome: "if other CHECK-enum columns have the same width
# mismatch, fold the audit in."  This scans all mapped tables for CHECK
# constraints of the form ``<col> IN ('a','b',...)`` and asserts the referenced
# String column is wide enough for the longest literal -- so the audit is
# codified, not a one-time eyeball, and any future enum column is covered for
# free.

_CHECK_IN_RE = re.compile(
    r"(?P<col>\w+)\s+IN\s+\((?P<values>[^)]*)\)",
    re.IGNORECASE,
)
_LITERAL_RE = re.compile(r"'((?:[^']|'')*)'")


def _checkInEnumColumns() -> list[tuple[str, str, int]]:
    """Return (table, column, longest_value_len) for every CHECK ``col IN (...)``.

    Walks the ORM metadata so a newly added enum CHECK is audited automatically.
    Only String/VARCHAR columns are returned (the width invariant is meaningless
    for non-text columns).
    """
    found: list[tuple[str, str, int]] = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            sqltext = getattr(constraint, 'sqltext', None)
            if sqltext is None:
                continue
            clause = str(sqltext)
            match = _CHECK_IN_RE.search(clause)
            if not match:
                continue
            colName = match.group('col')
            column = table.columns.get(colName)
            if column is None:
                continue
            length = getattr(column.type, 'length', None)
            if length is None:
                # Non-text or unbounded column -- width invariant N/A.
                continue
            literals = _LITERAL_RE.findall(match.group('values'))
            if not literals:
                continue
            longest = max(len(v.replace("''", "'")) for v in literals)
            found.append((table.name, colName, longest))
    return found


class TestAllCheckEnumColumnsWideEnough:
    def test_auditFindsTheTwoDataQualityColumns(self) -> None:
        """Sanity: the audit actually discovers the columns it must guard."""
        audited = {(t, c) for t, c, _ in _checkInEnumColumns()}
        assert ('drive_summary', 'data_quality') in audited
        assert ('drive_statistics', 'data_quality') in audited

    def test_everyCheckEnumColumnFitsItsLongestValue(self) -> None:
        """No CHECK-enum String column is narrower than its longest value."""
        offenders: list[str] = []
        for tableName, colName, longest in _checkInEnumColumns():
            column = Base.metadata.tables[tableName].columns[colName]
            if column.type.length < longest:
                offenders.append(
                    f'{tableName}.{colName} VARCHAR({column.type.length}) '
                    f'< {longest}-char enum value',
                )
        assert not offenders, 'CHECK-enum columns too narrow:\n  ' + '\n  '.join(
            offenders,
        )


# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0010)
# ================================================================================


@dataclass
class FakeRunner:
    """Scripted runner.  First matching needle wins (insertion order)."""

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


def _addrs() -> asm.HostAddresses:
    return asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')


def _creds() -> asm.ServerCreds:
    return asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db')


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(addrs=_addrs(), creds=_creds(), runner=runner)


def _scriptWidthState(runner: FakeRunner, *, before: int, after: int) -> None:
    """Script the table-exists + CHARACTER_MAXIMUM_LENGTH probes.

    The width probe returns ``before`` on its first call per table and ``after``
    on every subsequent call (the post-condition probe).  Both tables are
    present.
    """
    runner.handlers.append((
        'information_schema.TABLES', lambda _s: _ok(stdout='1\n'),
    ))
    perTableCalls: dict[str, int] = {}

    def widthProbe(sql: str) -> subprocess.CompletedProcess[str]:
        table = 'drive_summary' if "TABLE_NAME='drive_summary'" in sql else (
            'drive_statistics'
        )
        perTableCalls[table] = perTableCalls.get(table, 0) + 1
        value = before if perTableCalls[table] == 1 else after
        return _ok(stdout=f'{value}\n')

    runner.handlers.append(('CHARACTER_MAXIMUM_LENGTH', widthProbe))


# ================================================================================
# Module shape + registry
# ================================================================================


class TestModuleExports:
    def test_versionIs0012(self) -> None:
        assert m0012.VERSION == '0012'

    def test_descriptionMentionsUs377(self) -> None:
        assert 'US-377' in m0012.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0012.MIGRATION.version == '0012'
        assert callable(m0012.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0012' in versions

    def test_registryStaysSortedWithV0012AtTail(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert versions[-1] == '0012'
        assert versions[versions.index('0012') - 1] == '0011'

    def test_targetWidthMatchesOrmConstant(self) -> None:
        assert m0012.TARGET_WIDTH == DATA_QUALITY_COLUMN_LENGTH

    def test_constantsMatchOrm(self) -> None:
        assert m0012.DRIVE_SUMMARY_TABLE == DriveSummary.__tablename__
        assert m0012.DRIVE_STATISTICS_TABLE == DriveStatistic.__tablename__
        assert m0012.COLUMN_NAME == 'data_quality'


# ================================================================================
# DDL parity -- MODIFY both columns to the ORM width, preserving NOT NULL/DEFAULT
# ================================================================================


class TestModifyDdl:
    @pytest.mark.parametrize(
        ('ddl', 'table'),
        [
            (None, 'drive_summary'),
            (None, 'drive_statistics'),
        ],
    )
    def test_modifyDdlIsWideningModify(self, ddl: None, table: str) -> None:
        ddl_str = (
            m0012.MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL if table == 'drive_summary'
            else m0012.MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL
        )
        assert ddl_str.startswith(f'ALTER TABLE {table}')
        assert f'MODIFY {m0012.COLUMN_NAME} VARCHAR({m0012.TARGET_WIDTH})' in ddl_str
        assert 'DROP' not in ddl_str.upper()
        assert 'RENAME' not in ddl_str.upper()

    def test_modifyDdlPreservesNotNull(self) -> None:
        assert 'NOT NULL' in m0012.MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL
        assert 'NOT NULL' in m0012.MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL

    def test_modifyDdlPreservesDefaultFull(self) -> None:
        assert "DEFAULT 'full'" in m0012.MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL
        assert "DEFAULT 'full'" in m0012.MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL

    def test_targetWidthFitsAttributionAnomaly(self) -> None:
        assert m0012.TARGET_WIDTH >= len('attribution_anomaly')


# ================================================================================
# apply -- production state (VARCHAR(16); the load-bearing deploy path)
# ================================================================================


class TestApplyProductionState:
    def test_emitsBothModifyAlters(self) -> None:
        runner = FakeRunner()
        _scriptWidthState(runner, before=16, after=20)
        m0012.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [
            m0012.MODIFY_DRIVE_SUMMARY_DATA_QUALITY_DDL,
            m0012.MODIFY_DRIVE_STATISTICS_DATA_QUALITY_DDL,
        ], '\n  '.join(['unexpected ALTER set:', *alters])


# ================================================================================
# apply -- already wide / fresh create_all (idempotent no-op)
# ================================================================================


class TestApplyFullyMigrated:
    def test_emitsNoAlterWhenAlreadyWide(self) -> None:
        runner = FakeRunner()
        _scriptWidthState(runner, before=20, after=20)
        m0012.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], f'idempotent re-run must not ALTER; got {alters}'

    def test_widerThanTargetIsAlsoNoOp(self) -> None:
        runner = FakeRunner()
        _scriptWidthState(runner, before=32, after=32)
        m0012.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == []


# ================================================================================
# Failure paths
# ================================================================================


class TestFailureModes:
    def test_tableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES', lambda _s: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_summary'):
            m0012.apply(_ctx(runner))

    def test_modifyFailureRaises(self) -> None:
        runner = FakeRunner()
        _scriptWidthState(runner, before=16, after=20)
        runner.handlers.insert(0, (
            'MODIFY data_quality',
            lambda _s: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='data_quality'):
            m0012.apply(_ctx(runner))

    def test_postProbeStillNarrowRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner()
        # Width stays 16 even after the MODIFY "ran" -> post-condition trips.
        _scriptWidthState(runner, before=16, after=16)
        with pytest.raises(asm.SchemaProbeError, match='data_quality'):
            m0012.apply(_ctx(runner))
