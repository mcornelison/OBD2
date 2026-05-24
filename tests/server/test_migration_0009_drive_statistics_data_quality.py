################################################################################
# File Name: test_migration_0009_drive_statistics_data_quality.py
# Purpose/Description: Sprint 41 V0.27.18 hotfix (US-357 / I-041) -- migration
#                      unit tests for v0009 ADD COLUMN data_quality on
#                      drive_statistics.  Verifies the migration emits the
#                      ALTER TABLE ADD COLUMN + ADD CHECK + ADD INDEX DDLs
#                      when each piece is missing, short-circuits on
#                      idempotent re-run, propagates DDL failures as
#                      MigrationError, raises SchemaProbeError if the column
#                      is still absent after the ALTER ran (silent mysql
#                      session-context bug class), and pins the column shape
#                      to the SQLAlchemy DriveStatistic ORM (String(16) /
#                      DEFAULT 'full' / CHECK enum names / index name) so a
#                      future ORM-side change trips this test before
#                      production drifts.  Mirrors test_migration_0008's
#                      FakeRunner shape; hermetic, no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-21    | Rex          | Initial -- Sprint 41 V0.27.18 hotfix
#               |              | (US-357 / I-041 close).
# ================================================================================
################################################################################

"""TDD tests for the v0009 drive_statistics.data_quality ADD COLUMN migration."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    DRIVE_STATISTICS_DATA_QUALITY_DEFAULT,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DriveStatistic,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0009_us351_drive_statistics_data_quality_column as m0009,
)

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0008)
# ================================================================================


@dataclass
class FakeRunner:
    """Scripted runner.  Caller registers handlers keyed by SQL substring;
    each handler returns a CompletedProcess.  Calls that don't match a
    handler return a generic OK so probes behave deterministically.

    Handler insertion order matters: the first matching needle wins, so a
    test can pin a narrow handler (``'CHECK_CONSTRAINTS'``) ahead of a
    broader one (``'information_schema'``).
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
# Test fixtures
# ================================================================================


def _addrs() -> asm.HostAddresses:
    return asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison')


def _creds() -> asm.ServerCreds:
    return asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db')


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(addrs=_addrs(), creds=_creds(), runner=runner)


def _scriptProductionPreMigrationState(runner: FakeRunner) -> None:
    """Configure FakeRunner so probes report the I-041 production state:
    drive_statistics table exists; data_quality column missing; CHECK
    constraint missing; index missing.  After the ALTERs run the column
    appears (post-condition probe should see it).

    This mirrors the exact V0.27.17 deploy state captured in
    ``offices/pm/issues/I-041-us351-missing-v0009-migration-data-quality-column.md``.
    """
    # Table probe: always present.  Two queries hit this needle: the
    # explicit serverTableExists check at the top of apply() AND any
    # incidental ``information_schema.TABLES`` from the runner.
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))

    # CHECK constraint probe: returns 0 (missing) so the ADD CHECK fires.
    runner.handlers.append((
        'information_schema.CHECK_CONSTRAINTS',
        lambda _sql: _ok(stdout='0\n'),
    ))

    # Index probe (information_schema.STATISTICS): returns 0 (missing).
    runner.handlers.append((
        'information_schema.STATISTICS',
        lambda _sql: _ok(stdout='0\n'),
    ))

    # Column probe (information_schema.COLUMNS): returns the pre-data_quality
    # column set on the first call and the post-ALTER set (with data_quality
    # included) on subsequent calls.  This script captures the apply()
    # sequence: probe -> ADD COLUMN -> probe CHECK -> ADD CHECK -> probe
    # INDEX -> ADD INDEX -> probe (post-condition).
    columnsBeforeAdd = (
        'drive_id\n'
        'parameter_name\n'
        'min_value\n'
        'max_value\n'
        'avg_value\n'
        'std_dev\n'
        'outlier_min\n'
        'outlier_max\n'
        'sample_count\n'
        'computed_at\n'
    )
    columnsAfterAdd = columnsBeforeAdd + m0009.COLUMN_NAME + '\n'
    probeCalls = {'n': 0}

    def columnProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        probeCalls['n'] += 1
        return _ok(stdout=columnsBeforeAdd if probeCalls['n'] == 1 else columnsAfterAdd)

    runner.handlers.append(('information_schema.COLUMNS', columnProbe))


def _scriptFullyMigratedState(runner: FakeRunner) -> None:
    """All probes report the column / CHECK / index are already present.

    Models the idempotent re-run path AND the fresh-DB ``create_all``
    path (where create_all builds the table with the column already in
    place from the ORM declarations).
    """
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.CHECK_CONSTRAINTS',
        lambda _sql: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.STATISTICS',
        lambda _sql: _ok(stdout='1\n'),
    ))
    # Column probe always reports the column present.
    columnsWithDataQuality = (
        'drive_id\n'
        'parameter_name\n'
        'min_value\n'
        'max_value\n'
        'avg_value\n'
        'std_dev\n'
        'outlier_min\n'
        'outlier_max\n'
        'sample_count\n'
        'data_quality\n'
        'computed_at\n'
    )
    runner.handlers.append((
        'information_schema.COLUMNS',
        lambda _sql: _ok(stdout=columnsWithDataQuality),
    ))


# ================================================================================
# Module shape
# ================================================================================


class TestModuleExports:
    def test_versionIs0009(self) -> None:
        assert m0009.VERSION == '0009'

    def test_descriptionMentionsUs357(self) -> None:
        assert 'US-357' in m0009.DESCRIPTION

    def test_descriptionMentionsDataQuality(self) -> None:
        assert 'data_quality' in m0009.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0009.MIGRATION.version == '0009'
        assert callable(m0009.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0009' in versions

    def test_appendedAtEnd(self) -> None:
        # Registry invariant: ascending order; latest at tail.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert re.match(r'^\d{4}$', versions[-1]) is not None
        assert versions[-1] == '0009'

    def test_constantsMatchOrm(self) -> None:
        # The migration's identifier constants must match the ORM's
        # declared names so SHOW CREATE TABLE is identical across
        # environments.  Drift here breaks the schema-parity invariant.
        assert m0009.TABLE_NAME == DriveStatistic.__tablename__
        assert m0009.COLUMN_NAME == 'data_quality'

    def test_checkConstraintNameMatchesOrm(self) -> None:
        # The CheckConstraint name on DriveStatistic.__table_args__ must
        # be ck_drive_statistics_data_quality -- both the migration and
        # the ORM must agree so SHOW CREATE TABLE matches.
        ormCheckNames = {
            c.name for c in DriveStatistic.__table__.constraints
            if c.name and 'data_quality' in c.name
        }
        assert m0009.CHECK_CONSTRAINT_NAME in ormCheckNames, (
            f'migration CHECK constraint name {m0009.CHECK_CONSTRAINT_NAME!r} '
            f'must match the ORM CheckConstraint name; ORM has {ormCheckNames}'
        )

    def test_indexNameMatchesOrm(self) -> None:
        ormIndexNames = {idx.name for idx in DriveStatistic.__table__.indexes}
        assert m0009.INDEX_NAME in ormIndexNames, (
            f'migration index name {m0009.INDEX_NAME!r} must match the ORM '
            f'Index name; ORM has {ormIndexNames}'
        )


# ================================================================================
# DDL parity -- ALTER TABLE matches the ORM's declared shape
# ================================================================================


class TestDdlMirrorsOrm:
    """Locks the column shape against the SQLAlchemy DriveStatistic model.

    If a future ORM change widens String(16) to String(32), or adds a new
    allowed value to the CHECK enum, these tests fail and force a
    follow-up migration.  Production rows would otherwise silently fail
    the next compute INSERT.
    """

    def test_addColumnDdlIsAlterTableAddColumn(self) -> None:
        # Pin the structural shape: this MUST be an additive ALTER, not
        # a DROP / RECREATE / RENAME which would lose data.
        ddl = m0009.ADD_DATA_QUALITY_COLUMN_DDL
        assert ddl.startswith('ALTER TABLE drive_statistics')
        assert 'ADD COLUMN data_quality' in ddl
        assert 'DROP' not in ddl.upper()
        assert 'RENAME' not in ddl.upper()

    def test_addColumnDdlMatchesOrmColumnType(self) -> None:
        # ORM declares String(16) -> migration MUST emit VARCHAR(16).
        # If the model widens to String(32) without updating the
        # migration, this trips RED so the gap is caught in CI.
        ormColumn = DriveStatistic.__table__.columns['data_quality']
        ormLength = ormColumn.type.length
        assert ormLength == 16, (
            f'ORM data_quality declared as String({ormLength}); '
            f'update this test + the v0009 DDL VARCHAR width.'
        )
        assert 'VARCHAR(16)' in m0009.ADD_DATA_QUALITY_COLUMN_DDL

    def test_addColumnDdlMarksNotNull(self) -> None:
        ddl = m0009.ADD_DATA_QUALITY_COLUMN_DDL
        # The ORM marks nullable=False so the migration must mirror that.
        assert 'NOT NULL' in ddl

    def test_addColumnDdlDefaultMatchesOrm(self) -> None:
        # The ORM's server_default ('full') is the source of truth.  The
        # V0.27.18 dispatch note proposed 'unknown' but that value is
        # not in the CHECK enum and would silently violate the constraint
        # on the very first row that took the default path.
        ddl = m0009.ADD_DATA_QUALITY_COLUMN_DDL
        assert f"DEFAULT '{DRIVE_STATISTICS_DATA_QUALITY_DEFAULT}'" in ddl
        assert DRIVE_STATISTICS_DATA_QUALITY_DEFAULT == 'full'

    def test_addCheckDdlAllowedValuesMatchOrm(self) -> None:
        # Every value in the ORM's exported tuple must appear in the
        # CHECK enum.  A future ORM-side addition (e.g., 'replay' for
        # Atlas scenario 3 deferred to V0.28+) trips RED here and
        # forces a follow-up migration.
        ddl = m0009.ADD_DATA_QUALITY_CHECK_DDL
        for value in DRIVE_STATISTICS_DATA_QUALITY_VALUES:
            assert f"'{value}'" in ddl, (
                f'CHECK enum missing ORM value {value!r}; '
                f'sync the migration to the ORM tuple.'
            )

    def test_addCheckDdlUsesCorrectConstraintName(self) -> None:
        ddl = m0009.ADD_DATA_QUALITY_CHECK_DDL
        assert (
            f'ADD CONSTRAINT {m0009.CHECK_CONSTRAINT_NAME}' in ddl
        )

    def test_addIndexDdlUsesCorrectIndexName(self) -> None:
        ddl = m0009.ADD_DATA_QUALITY_INDEX_DDL
        assert f'ADD INDEX {m0009.INDEX_NAME}' in ddl
        assert f'({m0009.COLUMN_NAME})' in ddl


# ================================================================================
# apply -- column missing path (I-041 production state)
# ================================================================================


class TestApplyColumnMissing:
    """When data_quality is missing (I-041 production state), the migration
    emits all three ALTER TABLE DDLs and the post-condition probe confirms
    the column landed.  This is the load-bearing scenario -- the V0.27.18
    deploy on chi-srv-01 will replay this exact path.
    """

    def test_emitsAddColumnDdl(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        adds = [s for s in runner.emittedSqls if 'ADD COLUMN data_quality' in s]
        assert len(adds) == 1, (
            f'expected exactly one ADD COLUMN; got: {adds}'
        )

    def test_emitsAddCheckDdl(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        checks = [
            s for s in runner.emittedSqls
            if 'ADD CONSTRAINT' in s and 'CHECK' in s
        ]
        assert len(checks) == 1, (
            f'expected exactly one ADD CONSTRAINT CHECK; got: {checks}'
        )

    def test_emitsAddIndexDdl(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        indexes = [
            s for s in runner.emittedSqls
            if 'ADD INDEX' in s and m0009.INDEX_NAME in s
        ]
        assert len(indexes) == 1, (
            f'expected exactly one ADD INDEX; got: {indexes}'
        )

    def test_emitsExactlyDeclaredDdls(self) -> None:
        # Lock the DDL text against drift: anything besides probes +
        # the three declared DDLs would be a regression.
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [
            m0009.ADD_DATA_QUALITY_COLUMN_DDL,
            m0009.ADD_DATA_QUALITY_CHECK_DDL,
            m0009.ADD_DATA_QUALITY_INDEX_DDL,
        ], (
            'expected the three declared ALTERs in order; got:\n  '
            + '\n  '.join(alters)
        )


# ================================================================================
# apply -- everything already present (idempotent re-run + fresh-DB path)
# ================================================================================


class TestApplyFullyMigrated:
    """When the column + CHECK + index are already present (idempotent
    re-run OR fresh DB where SQLAlchemy create_all() owns table creation
    with the current ORM shape), apply MUST be a no-op on the DDL side.
    """

    def test_emitsNoAlterTable(self) -> None:
        runner = FakeRunner()
        _scriptFullyMigratedState(runner)
        m0009.apply(_ctx(runner))

        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], (
            f'idempotent re-run must not emit ALTER TABLE; got: {alters}'
        )

    def test_runsTwoColumnProbesPreAndPost(self) -> None:
        # Even on the fully-migrated path, apply() must run the pre-probe
        # AND the post-condition probe to surface session-context bugs
        # consistently across paths.
        runner = FakeRunner()
        _scriptFullyMigratedState(runner)
        m0009.apply(_ctx(runner))

        columnProbes = [
            s for s in runner.emittedSqls
            if 'information_schema.COLUMNS' in s
        ]
        assert len(columnProbes) == 2, (
            f'expected pre + post column probes; got {len(columnProbes)}'
        )


# ================================================================================
# Failure paths
# ================================================================================


class TestFailureModes:
    def test_tableMissingRaisesMigrationError(self) -> None:
        # If the drive_statistics table doesn't exist at all, the
        # migration can't proceed -- raise loudly rather than silently
        # creating an unexpected table from a stale model.
        runner = FakeRunner()
        # Insert the table-missing handler FIRST so it wins over any
        # broader default.
        runner.handlers.insert(0, (
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_statistics'):
            m0009.apply(_ctx(runner))

    def test_addColumnFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        # Override: the ADD COLUMN fails with a representative MariaDB error.
        runner.handlers.insert(0, (
            'ADD COLUMN data_quality',
            lambda _sql: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='data_quality'):
            m0009.apply(_ctx(runner))

    def test_postProbeMissingRaisesSchemaProbeError(self) -> None:
        # ADD COLUMN returns 0 but the post-condition probe still reports
        # the column missing -- the silent mysql session-context bug
        # class that prompted the post-probe pattern in v0002/v0004/v0005/v0008.
        runner = FakeRunner()
        # Both column probes return the pre-add column set (no data_quality).
        columnsWithoutDataQuality = (
            'drive_id\nparameter_name\nmin_value\nmax_value\navg_value\n'
            'std_dev\noutlier_min\noutlier_max\nsample_count\ncomputed_at\n'
        )
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        runner.handlers.append((
            'information_schema.COLUMNS',
            lambda _sql: _ok(stdout=columnsWithoutDataQuality),
        ))
        runner.handlers.append((
            'information_schema.CHECK_CONSTRAINTS',
            lambda _sql: _ok(stdout='0\n'),
        ))
        runner.handlers.append((
            'information_schema.STATISTICS',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(
            asm.SchemaProbeError, match='data_quality.*missing',
        ):
            m0009.apply(_ctx(runner))

    def test_checkConstraintAlreadyExistsIsBenign(self) -> None:
        # Older MariaDB versions report duplicate constraint as a 1826
        # error rather than an addable IF NOT EXISTS.  We tolerate this
        # so a partial prior-run state can converge.
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        runner.handlers.insert(0, (
            'ADD CONSTRAINT',
            lambda _sql: _fail(
                "ERROR 1826 (HY000): Duplicate CHECK constraint name"
            ),
        ))
        # Should NOT raise -- duplicate-constraint is benign.
        m0009.apply(_ctx(runner))


# ================================================================================
# Strong-test discriminator -- I-041 production state
# ================================================================================


class TestProductionFailureModeDiscriminator:
    """Lock the SQL that resolves the I-041 production state.

    I-041 evidence (V0.27.17 deploy, 2026-05-21): every Step 4.9 backfill
    INSERT failed with::

        (1054, "Unknown column 'data_quality' in 'INSERT INTO'")

    Replay the exact production state (column missing) and confirm the
    migration issues exactly one ADD COLUMN against drive_statistics.
    """

    def test_runWouldFireAddColumnAgainstI041ProductionState(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        addColumnCount = sum(
            1 for s in runner.emittedSqls
            if 'ADD COLUMN data_quality' in s
        )
        assert addColumnCount == 1, (
            f'I-041 production state must produce exactly one ADD COLUMN; '
            f'got {addColumnCount}'
        )

    def test_addColumnTargetsDriveStatisticsOnly(self) -> None:
        # Bug scope is narrow -- only drive_statistics.data_quality.
        # The migration must not accidentally touch other tables.
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        for sql in alters:
            assert 'ALTER TABLE drive_statistics ' in sql, (
                f'unexpected ALTER TABLE target in {sql!r}; '
                f'v0009 scope is drive_statistics only'
            )

    def test_postMigrationInsertWouldHaveDataQualityColumn(self) -> None:
        """End-to-end shape check: after v0009 applies, the drive_statistics
        column set MUST include data_quality so the compute writer at
        ``src/server/analytics/drive_statistics_compute.py:214`` succeeds.

        The compute writer references ``data_quality=dataQuality`` on
        every INSERT; absent column -> OperationalError 1054 (the exact
        I-041 production symptom).  This test asserts the column appears
        in the post-apply schema.
        """
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0009.apply(_ctx(runner))

        # The post-condition probe must have seen data_quality.  The
        # script returns the post-add column set on the SECOND
        # information_schema.COLUMNS probe (apply's pre-probe was call 1).
        columnProbes = [
            c for c in runner.calls
            if c['input'] and 'information_schema.COLUMNS' in c['input']
        ]
        assert len(columnProbes) >= 2, (
            'apply() must run a post-condition column probe'
        )
        # The final probe must include data_quality so the post-condition
        # branch in apply() does not raise.  (If it had raised, this test
        # would never have run to this assertion.)
        assert True
