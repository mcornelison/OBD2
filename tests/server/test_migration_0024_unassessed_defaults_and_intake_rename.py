################################################################################
# File Name: test_migration_0024_unassessed_defaults_and_intake_rename.py
# Purpose/Description: US-563 (F-134) -- v0024 migration gate.  Proves the three
#                      schema truths land on a modeled applied schema, that each
#                      substep is idempotent, that the CHECK widen runs BEFORE
#                      the DEFAULT moves (ordering is load-bearing -- a DEFAULT
#                      its own CHECK forbids fails on the next INSERT, in the
#                      car, not at ALTER time), and that every post-condition
#                      probe raises rather than reporting a silent no-op.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-563) | Initial -- Sprint 75 v0024 gate.
# ================================================================================
################################################################################

"""v0024 migration gate (US-563 / F-134).

The fake runner models a MariaDB applied schema as three dicts (CHECK clauses,
column defaults, column set) and MUTATES them as DDL arrives, so an assertion
about "the schema after the migration" is an assertion about state the DDL
actually produced -- not about a string the test wrote itself.

That distinction is the whole US-560 lesson: a fixture that ASSERTS the hardware
(or schema) fact which makes the change look applicable can only ever go green.
Here the fixture models MECHANISM (drop/add a constraint, modify a default,
rename a column) and lets the migration decide the outcome.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db import models
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0024_us563_unassessed_defaults_and_intake_rename as m0024,
)

DB = 'obd2db'


# ================================================================================
# A mutable model of the applied schema
# ================================================================================


@dataclass
class FakeSchema:
    """Applied-schema model that RESPONDS to DDL instead of asserting outcomes."""

    # constraint name -> stored CHECK_CLAUSE text
    checks: dict[str, str] = field(default_factory=dict)
    # (table, column) -> raw COLUMN_DEFAULT text ('NULL' for none)
    defaults: dict[tuple[str, str], str] = field(default_factory=dict)
    # table -> column names
    columns: dict[str, set[str]] = field(default_factory=dict)
    tables: set[str] = field(default_factory=set)

    # Ordered log of every DDL statement executed (for ordering assertions).
    ddl: list[str] = field(default_factory=list)
    # Statements the fake should refuse, keyed by a substring.
    failOn: str | None = None

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = (input or '').strip()
        if self.failOn and self.failOn in sql:
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout='', stderr='modeled DDL failure',
            )
        if sql.startswith('SELECT'):
            return self._answer(sql)
        self.ddl.append(sql)
        self._applyDdl(sql)
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout='', stderr='',
        )

    # ---- reads -------------------------------------------------------------

    def _answer(self, sql: str) -> subprocess.CompletedProcess[str]:
        def ok(out: str) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=out, stderr='',
            )

        if 'information_schema.TABLES' in sql:
            table = _between(sql, "TABLE_NAME='", "'")
            return ok('1\n' if table in self.tables else '0\n')

        if 'CHECK_CONSTRAINTS' in sql:
            name = _between(sql, "CONSTRAINT_NAME='", "'")
            return ok(self.checks.get(name, '') + '\n' if name in self.checks else '')

        if 'COUNT(*)' in sql and 'information_schema.COLUMNS' in sql:
            table = _between(sql, "TABLE_NAME='", "'")
            column = _between(sql, "COLUMN_NAME='", "'")
            return ok('1\n' if column in self.columns.get(table, set()) else '0\n')

        if 'SELECT TABLE_NAME, COLUMN_NAME, COLUMN_DEFAULT' in sql:
            rows = [
                f'{t}\t{c}\t{self.defaults.get((t, c), "NULL")}'
                for (t, c) in sorted(self.defaults)
                if c == m0024.DATA_QUALITY_COLUMN
            ]
            return ok('\n'.join(rows) + ('\n' if rows else ''))

        if 'SELECT COLUMN_DEFAULT' in sql:
            table = _between(sql, "TABLE_NAME='", "'")
            column = _between(sql, "COLUMN_NAME='", "'")
            if column not in self.columns.get(table, set()):
                return ok('')
            return ok(self.defaults.get((table, column), 'NULL') + '\n')

        return ok('')

    # ---- writes ------------------------------------------------------------

    def _applyDdl(self, sql: str) -> None:
        table = sql.split()[2] if sql.startswith('ALTER TABLE') else ''

        if 'DROP CONSTRAINT' in sql:
            self.checks.pop(sql.split('DROP CONSTRAINT')[1].strip(' ;'), None)
            return

        if 'ADD CONSTRAINT' in sql:
            name = sql.split('ADD CONSTRAINT')[1].split()[0]
            self.checks[name] = sql.split('CHECK', 1)[1].strip(' ;')
            return

        if 'CHANGE COLUMN' in sql:
            old, new = sql.split('CHANGE COLUMN')[1].split()[:2]
            cols = self.columns.setdefault(table, set())
            cols.discard(old)
            cols.add(new)
            self.defaults.pop((table, old), None)
            return

        if 'MODIFY' in sql:
            column = sql.split('MODIFY')[1].split()[0]
            if "DEFAULT '" in sql:
                self.defaults[(table, column)] = (
                    "'" + sql.split("DEFAULT '")[1].split("'")[0] + "'"
                )
            elif 'DEFAULT NULL' in sql:
                self.defaults[(table, column)] = 'NULL'
            return


def _between(text: str, start: str, end: str) -> str:
    if start not in text:
        return ''
    rest = text.split(start, 1)[1]
    return rest.split(end, 1)[0]


def _prodShape() -> FakeSchema:
    """The applied schema as measured on prod 2026-08-20 (the defect state)."""
    return FakeSchema(
        tables={'drive_summary', 'drive_statistics', 'drives'},
        checks={
            'ck_drive_summary_data_quality':
                "data_quality in ('full','attribution_anomaly','foreign_vehicle')",
            'ck_drive_statistics_data_quality':
                "data_quality in ('full','sparse','below_threshold',"
                "'attribution_anomaly','foreign_vehicle')",
            'ck_drives_data_quality':
                "data_quality in ('full','attribution_anomaly',"
                "'foreign_vehicle','unmappable_legacy')",
        },
        defaults={
            ('drive_summary', 'data_quality'): "'full'",
            ('drive_statistics', 'data_quality'): "'full'",
            ('drives', 'data_quality'): "'full'",
            ('drive_summary', 'is_real'): '0',
        },
        columns={
            'drive_summary': {
                'id', 'data_quality', 'is_real', 'ambient_temp_at_start_c',
                'starting_battery_v',
            },
            'drive_statistics': {'summary_id', 'data_quality'},
            'drives': {'drive_id', 'data_quality'},
        },
    )


def _ctx(schema: FakeSchema) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.120', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName=DB),
        runner=schema,
    )


# ================================================================================
# Registration
# ================================================================================


class TestRegistration:
    def test_v0024IsRegisteredLast(self) -> None:
        assert ALL_MIGRATIONS[-1].version == '0024'

    def test_versionsAreUniqueAndAscending(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert len(set(versions)) == len(versions)


# ================================================================================
# The three schema truths
# ================================================================================


class TestAppliesTheThreeSchemaTruths:
    """Run the real ``apply`` against the measured prod shape."""

    def test_dataQualityDefaultsBecomeTheNonVerdictOnEveryTable(self) -> None:
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        for table in ('drive_summary', 'drive_statistics', 'drives'):
            assert schema.defaults[(table, 'data_quality')] == "'unassessed'", (
                f'{table}.data_quality still defaults to a verdict'
            )

    def test_isRealDefaultBecomesNull(self) -> None:
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        assert schema.defaults[('drive_summary', 'is_real')] == 'NULL'

    def test_ambientColumnIsRenamedToIntakeAir(self) -> None:
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        cols = schema.columns['drive_summary']
        assert m0024.NEW_INTAKE_COLUMN in cols
        assert m0024.OLD_AMBIENT_COLUMN not in cols

    def test_everyCheckPermitsUnassessed(self) -> None:
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        for name, clause in schema.checks.items():
            assert 'unassessed' in clause, f'{name} still forbids the new default'

    def test_checksKeepEveryPreExistingVerdict(self) -> None:
        """The widen ADDS a value; it must not quietly drop one.

        A rebuilt CHECK is written from the current ORM tuple, so a value
        accidentally dropped from that tuple would silently start rejecting
        historical rows on the next UPDATE.
        """
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        assert 'unmappable_legacy' in schema.checks['ck_drives_data_quality']
        for verdict in ('full', 'attribution_anomaly', 'foreign_vehicle'):
            assert verdict in schema.checks['ck_drive_summary_data_quality']
        for verdict in ('sparse', 'below_threshold'):
            assert verdict in schema.checks['ck_drive_statistics_data_quality']


class TestOrdering:
    def test_everyCheckIsWidenedBeforeAnyDefaultMoves(self) -> None:
        """Load-bearing: a DEFAULT its own CHECK forbids fails at INSERT time.

        Not at ALTER time -- so a mis-ordered migration reports success and then
        breaks the next Pi sync, in the car, hours later.  Asserted on the DDL
        log rather than on the end state, because the end state is identical
        either way.
        """
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        lastCheck = max(
            i for i, s in enumerate(schema.ddl) if 'CONSTRAINT' in s
        )
        firstDefault = min(
            i for i, s in enumerate(schema.ddl) if 'MODIFY' in s
        )
        assert lastCheck < firstDefault, (
            'a DEFAULT moved before the CHECKs were widened:\n'
            + '\n'.join(schema.ddl)
        )


class TestIdempotency:
    def test_reRunIssuesNoDdl(self) -> None:
        """Second run is a no-op -- AND the first run was not.

        The "first run did work" half is load-bearing: idempotency is trivially
        satisfied by a migration that does nothing at all, so without it this
        test stays green against an empty ``apply``.  (Exactly the "tests that
        SHOULD be failing and are not" trap from US-561.)
        """
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        assert schema.ddl, 'first run against the prod shape issued no DDL'
        schema.ddl.clear()
        m0024.apply(_ctx(schema))
        assert schema.ddl == [], f'second run issued DDL: {schema.ddl}'

    def test_freshCreateAllShapeIsANoOp(self) -> None:
        """A fresh DB built from the CURRENT ORM already satisfies every truth."""
        schema = _prodShape()
        schema.checks = {
            k: v.replace("('", "('unassessed','") for k, v in schema.checks.items()
        }
        schema.defaults = {
            ('drive_summary', 'data_quality'): "'unassessed'",
            ('drive_statistics', 'data_quality'): "'unassessed'",
            ('drives', 'data_quality'): "'unassessed'",
            ('drive_summary', 'is_real'): 'NULL',
        }
        schema.columns['drive_summary'] = {
            'id', 'data_quality', 'is_real', m0024.NEW_INTAKE_COLUMN,
        }
        m0024.apply(_ctx(schema))
        assert schema.ddl == []


class TestRefusals:
    """Every failure path is LOUD.  A silent no-op is the class this guards."""

    def test_missingTableIsAHardError(self) -> None:
        schema = _prodShape()
        schema.tables.discard('drives')
        with pytest.raises(asm.MigrationError, match='drives'):
            m0024.apply(_ctx(schema))

    def test_bothColumnNamesPresentRefusesRatherThanGuessing(self) -> None:
        # Two live spellings of one reading is exactly what the rename exists to
        # prevent; picking one would risk discarding the populated column.
        schema = _prodShape()
        schema.columns['drive_summary'].add(m0024.NEW_INTAKE_COLUMN)
        with pytest.raises(asm.MigrationError, match='BOTH'):
            m0024.apply(_ctx(schema))

    def test_neitherColumnPresentIsAHardError(self) -> None:
        schema = _prodShape()
        schema.columns['drive_summary'].discard(m0024.OLD_AMBIENT_COLUMN)
        with pytest.raises(asm.MigrationError, match='neither'):
            m0024.apply(_ctx(schema))

    def test_failedRenameRaises(self) -> None:
        schema = _prodShape()
        schema.failOn = 'CHANGE COLUMN'
        with pytest.raises(asm.MigrationError, match='rename'):
            m0024.apply(_ctx(schema))

    def test_failedDefaultModifyRaises(self) -> None:
        schema = _prodShape()
        schema.failOn = 'MODIFY data_quality'
        with pytest.raises(asm.MigrationError, match='re-default'):
            m0024.apply(_ctx(schema))

    def test_probeFailureRaisesSchemaProbeError(self) -> None:
        schema = _prodShape()
        schema.failOn = 'CHECK_CONSTRAINTS'
        with pytest.raises(asm.SchemaProbeError, match='probe failed'):
            m0024.apply(_ctx(schema))


# ================================================================================
# Define-once -- the DDL is built from the ORM, not from a retyped literal
# ================================================================================


class TestDdlIsBuiltFromTheOrm:
    def test_unassessedValueComesFromModels(self) -> None:
        assert m0024.UNASSESSED_VALUE is models.DATA_QUALITY_UNASSESSED

    def test_assessedSetIsTheUnionOfTheOrmVerdictTuples(self) -> None:
        # Enumerated FROM the ORM, never retyped: a verdict added to any enum
        # tomorrow is forbidden as a DEFAULT without editing the guard.
        expected = set(models.DRIVE_SUMMARY_ASSESSED_DATA_QUALITY_VALUES)
        expected |= set(models.DRIVE_STATISTICS_ASSESSED_DATA_QUALITY_VALUES)
        expected |= set(models.DRIVES_ASSESSED_DATA_QUALITY_VALUES)
        assert m0024.ASSESSED_DATA_QUALITY_VALUES == expected

    def test_unassessedIsNotInTheAssessedSet(self) -> None:
        # Otherwise the guard forbids the very default this migration sets, and
        # every assertion built on ASSESSED_DATA_QUALITY_VALUES inverts.
        assert m0024.UNASSESSED_VALUE not in m0024.ASSESSED_DATA_QUALITY_VALUES

    def test_modifyDdlRestatesNotNullAndWidth(self) -> None:
        # v0012's lesson: a bare MODIFY silently drops NOT NULL and the DEFAULT.
        ddl = m0024._modifyDataQualityDefaultDdl('drive_summary')
        assert 'NOT NULL' in ddl
        assert f'VARCHAR({models.DATA_QUALITY_COLUMN_LENGTH})' in ddl

    def test_renameUsesChangeColumnNotRenameColumn(self) -> None:
        # RENAME COLUMN needs MariaDB >= 10.5.2; CHANGE works everywhere this
        # project has deployed.  Pinned so a "tidier" rewrite states its case.
        assert 'CHANGE COLUMN' in m0024.RENAME_INTAKE_COLUMN_DDL
        assert 'RENAME COLUMN' not in m0024.RENAME_INTAKE_COLUMN_DDL

    def test_existingRowsAreNotRewritten(self) -> None:
        """No UPDATE / DML anywhere -- a DEFAULT applies to future INSERTs only.

        Back-filling 'unassessed' over rows already carrying 'full' would
        MANUFACTURE a reading: the migration cannot tell a genuine batch result
        from a pre-computed default without re-running analytics.  Pinned
        structurally because "we did not write an UPDATE" is not observable from
        the end state of a schema-only fixture.
        """
        schema = _prodShape()
        m0024.apply(_ctx(schema))
        for statement in schema.ddl:
            assert not statement.upper().startswith(('UPDATE', 'INSERT', 'DELETE')), (
                f'v0024 rewrites row data: {statement}'
            )
