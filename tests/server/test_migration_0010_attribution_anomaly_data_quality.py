################################################################################
# File Name: test_migration_0010_attribution_anomaly_data_quality.py
# Purpose/Description: Sprint 43 V0.28.0 (US-363 / F-107) -- migration unit tests
#                      for v0010: ADD COLUMN data_quality (+ CHECK + index) to
#                      drive_summary AND extend the drive_statistics data_quality
#                      CHECK enum with 'attribution_anomaly' (DROP + re-ADD).
#                      Verifies DDL parity against the SQLAlchemy ORM, the
#                      INFORMATION_SCHEMA-probe idempotency (production state
#                      emits the rebuild; fully-migrated / fresh-create_all DB is
#                      a no-op), failure propagation, and registry registration.
#                      Mirrors test_migration_0009's FakeRunner shape; hermetic,
#                      no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-363) | Initial -- F-107 attribution-anomaly tripwire
#               |              | schema migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0010 attribution-anomaly data_quality migration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    DATA_QUALITY_ATTRIBUTION_ANOMALY,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_DEFAULT,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
    DriveStatistic,
    DriveSummary,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0010_us363_attribution_anomaly_data_quality as m0010,
)

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0009)
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


# drive_summary column sets (newline-separated, as probeServerColumns parses).
_DRIVE_SUMMARY_COLS_BEFORE = (
    'id\ndevice_id\nstart_time\nend_time\nduration_seconds\nprofile_id\n'
    'row_count\nis_real\ncreated_at\ndata_source\nsource_id\nsource_device\n'
    'synced_at\nsync_batch_id\ndrive_start_timestamp\nambient_temp_at_start_c\n'
    'starting_battery_v\nbarometric_kpa_at_start\ndrive_id\n'
)
_DRIVE_SUMMARY_COLS_AFTER = _DRIVE_SUMMARY_COLS_BEFORE + 'data_quality\n'

# drive_statistics CHECK_CLAUSE before/after the rebuild.
_DS_CLAUSE_3VALUE = "data_quality in ('full','sparse','below_threshold')\n"
_DS_CLAUSE_4VALUE = (
    "data_quality in ('full','sparse','below_threshold',"
    "'attribution_anomaly')\n"
)

# drive_statistics column sets for the US-371 rename substep (apply() now runs
# it after the US-363 substeps).  Pre-rename carries drive_id; post carries
# summary_id.
_DRIVE_STATS_COLS_PRE_RENAME = (
    'drive_id\nparameter_name\nmin_value\nmax_value\navg_value\nstd_dev\n'
    'outlier_min\noutlier_max\nsample_count\ndata_quality\ncomputed_at\n'
)
_DRIVE_STATS_COLS_POST_RENAME = (
    'summary_id\nparameter_name\nmin_value\nmax_value\navg_value\nstd_dev\n'
    'outlier_min\noutlier_max\nsample_count\ndata_quality\ncomputed_at\n'
)

# vehicle_info column sets for the US-365 ECU-lineage substep.  BEFORE = the
# VIN-decoded-only shape; AFTER = the five ECU columns + the generated marker.
_VEHICLE_INFO_COLS_BEFORE = (
    'id\nsource_id\nsource_device\nsynced_at\nvin\nmake\nmodel\nyear\nengine\n'
    'fuel_type\ntransmission\ndrive_type\nbody_class\nplant_city\n'
    'plant_country\nraw_api_response\ncreated_at\nupdated_at\n'
)
_VEHICLE_INFO_COLS_AFTER = _VEHICLE_INFO_COLS_BEFORE + (
    'ecu_signature\ncal_signature\necu_install_timestamp_utc\n'
    'ecu_removal_timestamp_utc\nnotes\necu_active_marker\n'
)


def _scriptProductionPreMigrationState(runner: FakeRunner) -> None:
    """v0009-migrated production state: drive_summary has NO data_quality
    column; its CHECK + index are absent; drive_statistics CHECK exists with
    the 3-value (no attribution_anomaly) clause.  After the ALTERs, the column
    appears and the drive_statistics clause carries the 4th value.
    """
    # drive_summary CHECK-existence probe (COUNT) -- missing -> 0.
    runner.handlers.append((
        'ck_drive_summary_data_quality',
        lambda _sql: _ok(stdout='0\n'),
    ))

    # US-372 chk_drive_id_source_id CHECK-existence probe -- absent on the
    # entry check (0 -> backfill + ADD fire), present on the post-condition
    # probe (1).
    chkInvariantCalls = {'n': 0}

    def chkInvariantProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        chkInvariantCalls['n'] += 1
        return _ok(stdout='0\n' if chkInvariantCalls['n'] == 1 else '1\n')

    runner.handlers.append(('chk_drive_id_source_id', chkInvariantProbe))

    # drive_statistics CHECK_CLAUSE probe -- 3-value first, 4-value post-rebuild.
    clauseCalls = {'n': 0}

    def clauseProbe(_sql: str) -> subprocess.CompletedProcess[str]:
        clauseCalls['n'] += 1
        return _ok(
            stdout=_DS_CLAUSE_3VALUE if clauseCalls['n'] == 1
            else _DS_CLAUSE_4VALUE,
        )

    runner.handlers.append(('ck_drive_statistics_data_quality', clauseProbe))

    # Table-exists probes (both tables) -> present.
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))
    # Index probe -> missing.
    runner.handlers.append((
        'information_schema.STATISTICS',
        lambda _sql: _ok(stdout='0\n'),
    ))
    # Column probe -> branch by table.  drive_summary: before-set first,
    # after-set post-ALTER (US-363).  drive_statistics: pre-rename (drive_id)
    # first, post-rename (summary_id) after the US-371 RENAME.
    dsSummaryCalls = {'n': 0}
    dsStatsCalls = {'n': 0}
    viCalls = {'n': 0}

    def columnProbe(sql: str) -> subprocess.CompletedProcess[str]:
        if "TABLE_NAME='drive_statistics'" in sql:
            dsStatsCalls['n'] += 1
            return _ok(
                stdout=_DRIVE_STATS_COLS_PRE_RENAME if dsStatsCalls['n'] == 1
                else _DRIVE_STATS_COLS_POST_RENAME,
            )
        if "TABLE_NAME='vehicle_info'" in sql:
            # US-365: ECU columns absent first (start probe), present after the
            # ADDs (post-condition probe).
            viCalls['n'] += 1
            return _ok(
                stdout=_VEHICLE_INFO_COLS_BEFORE if viCalls['n'] == 1
                else _VEHICLE_INFO_COLS_AFTER,
            )
        dsSummaryCalls['n'] += 1
        return _ok(
            stdout=_DRIVE_SUMMARY_COLS_BEFORE if dsSummaryCalls['n'] == 1
            else _DRIVE_SUMMARY_COLS_AFTER,
        )

    runner.handlers.append(('information_schema.COLUMNS', columnProbe))


def _scriptFullyMigratedState(runner: FakeRunner) -> None:
    """drive_summary already has the column / CHECK / index; drive_statistics
    CHECK clause already carries attribution_anomaly.  Models the idempotent
    re-run AND the fresh-DB create_all path (ORM owns the 4-value enum).
    """
    runner.handlers.append((
        'ck_drive_summary_data_quality',
        lambda _sql: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'ck_drive_statistics_data_quality',
        lambda _sql: _ok(stdout=_DS_CLAUSE_4VALUE),
    ))
    # US-372 invariant CHECK already present -> substep is a no-op.
    runner.handlers.append((
        'chk_drive_id_source_id',
        lambda _sql: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.STATISTICS',
        lambda _sql: _ok(stdout='1\n'),
    ))

    def columnProbe(sql: str) -> subprocess.CompletedProcess[str]:
        # drive_statistics already renamed (summary_id present) -> US-371 no-op.
        if "TABLE_NAME='drive_statistics'" in sql:
            return _ok(stdout=_DRIVE_STATS_COLS_POST_RENAME)
        # vehicle_info already has the ECU columns -> US-365 no-op.
        if "TABLE_NAME='vehicle_info'" in sql:
            return _ok(stdout=_VEHICLE_INFO_COLS_AFTER)
        return _ok(stdout=_DRIVE_SUMMARY_COLS_AFTER)

    runner.handlers.append(('information_schema.COLUMNS', columnProbe))


# ================================================================================
# Module shape + registry
# ================================================================================


class TestModuleExports:
    def test_versionIs0010(self) -> None:
        assert m0010.VERSION == '0010'

    def test_descriptionMentionsUs363(self) -> None:
        assert 'US-363' in m0010.DESCRIPTION

    def test_descriptionMentionsAttributionAnomaly(self) -> None:
        assert 'attribution_anomaly' in m0010.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0010.MIGRATION.version == '0010'
        assert callable(m0010.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        versions = [m.version for m in ALL_MIGRATIONS]
        assert '0010' in versions

    def test_registryStaysSortedWithV0010BeforeV0011(self) -> None:
        # v0011 (US-376) was appended after v0010; the durable invariant is that
        # the registry stays sorted ascending and v0010 sits immediately before
        # v0011 (the new tail is asserted by the v0011 migration test).
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0010' in versions
        assert versions[versions.index('0010') + 1] == '0011'

    def test_constantsMatchOrm(self) -> None:
        assert m0010.DRIVE_SUMMARY_TABLE == DriveSummary.__tablename__
        assert m0010.DRIVE_STATISTICS_TABLE == DriveStatistic.__tablename__
        assert m0010.DRIVE_SUMMARY_COLUMN == 'data_quality'

    def test_driveSummaryCheckNameMatchesOrm(self) -> None:
        ormCheckNames = {
            c.name for c in DriveSummary.__table__.constraints
            if c.name and 'data_quality' in c.name
        }
        assert m0010.DRIVE_SUMMARY_CHECK_NAME in ormCheckNames, (
            f'migration CHECK name {m0010.DRIVE_SUMMARY_CHECK_NAME!r} must '
            f'match the ORM; ORM has {ormCheckNames}'
        )

    def test_driveSummaryIndexNameMatchesOrm(self) -> None:
        ormIndexNames = {idx.name for idx in DriveSummary.__table__.indexes}
        assert m0010.DRIVE_SUMMARY_INDEX_NAME in ormIndexNames, (
            f'migration index name {m0010.DRIVE_SUMMARY_INDEX_NAME!r} must '
            f'match the ORM; ORM has {ormIndexNames}'
        )

    def test_driveStatisticsCheckNameMatchesOrm(self) -> None:
        ormCheckNames = {
            c.name for c in DriveStatistic.__table__.constraints
            if c.name and 'data_quality' in c.name
        }
        assert m0010.DRIVE_STATISTICS_CHECK_NAME in ormCheckNames


# ================================================================================
# DDL parity -- drive_summary column shape mirrors the ORM
# ================================================================================


class TestDriveSummaryDdlMirrorsOrm:
    def test_addColumnDdlIsAdditiveAlter(self) -> None:
        ddl = m0010.ADD_DRIVE_SUMMARY_COLUMN_DDL
        assert ddl.startswith('ALTER TABLE drive_summary')
        assert 'ADD COLUMN data_quality' in ddl
        assert 'DROP' not in ddl.upper()
        assert 'RENAME' not in ddl.upper()

    def test_addColumnDdlUsesFrozenHistoricalWidth(self) -> None:
        # v0010 historically created drive_summary.data_quality as
        # VARCHAR(16) and is a SHIPPED, forward-only migration (never
        # edited).  The ORM later widened to VARCHAR(20) (US-377 / v0012)
        # so 'attribution_anomaly' (19 chars) fits; v0012 reconciles the
        # live column.  Current-width ORM parity lives in
        # test_migration_0012's width-invariant guard; pin v0010's FROZEN
        # width here so the shipped DDL is never silently rewritten.
        assert 'VARCHAR(16)' in m0010.ADD_DRIVE_SUMMARY_COLUMN_DDL

    def test_addColumnDdlMarksNotNull(self) -> None:
        assert 'NOT NULL' in m0010.ADD_DRIVE_SUMMARY_COLUMN_DDL

    def test_addColumnDdlDefaultMatchesOrm(self) -> None:
        ddl = m0010.ADD_DRIVE_SUMMARY_COLUMN_DDL
        assert f"DEFAULT '{DRIVE_SUMMARY_DATA_QUALITY_DEFAULT}'" in ddl
        assert DRIVE_SUMMARY_DATA_QUALITY_DEFAULT == 'full'

    def test_addCheckDdlAllowedValuesMatchOrm(self) -> None:
        ddl = m0010.ADD_DRIVE_SUMMARY_CHECK_DDL
        for value in DRIVE_SUMMARY_DATA_QUALITY_VALUES:
            assert f"'{value}'" in ddl
        assert DATA_QUALITY_ATTRIBUTION_ANOMALY in ddl

    def test_addCheckDdlUsesCorrectConstraintName(self) -> None:
        assert (
            f'ADD CONSTRAINT {m0010.DRIVE_SUMMARY_CHECK_NAME}'
            in m0010.ADD_DRIVE_SUMMARY_CHECK_DDL
        )

    def test_addIndexDdlUsesCorrectName(self) -> None:
        ddl = m0010.ADD_DRIVE_SUMMARY_INDEX_DDL
        assert f'ADD INDEX {m0010.DRIVE_SUMMARY_INDEX_NAME}' in ddl
        assert f'({m0010.DRIVE_SUMMARY_COLUMN})' in ddl


# ================================================================================
# DDL parity -- drive_statistics CHECK rebuild carries the new value
# ================================================================================


class TestDriveStatisticsCheckDdl:
    def test_dropDdlTargetsNamedConstraint(self) -> None:
        ddl = m0010.DROP_DRIVE_STATISTICS_CHECK_DDL
        assert ddl.startswith('ALTER TABLE drive_statistics')
        assert f'DROP CONSTRAINT {m0010.DRIVE_STATISTICS_CHECK_NAME}' in ddl

    def test_addDdlIncludesAttributionAnomalyAndAllOrmValues(self) -> None:
        ddl = m0010.ADD_DRIVE_STATISTICS_CHECK_DDL
        assert DATA_QUALITY_ATTRIBUTION_ANOMALY in ddl
        for value in DRIVE_STATISTICS_DATA_QUALITY_VALUES:
            assert f"'{value}'" in ddl

    def test_addDdlUsesCorrectConstraintName(self) -> None:
        assert (
            f'ADD CONSTRAINT {m0010.DRIVE_STATISTICS_CHECK_NAME}'
            in m0010.ADD_DRIVE_STATISTICS_CHECK_DDL
        )


# ================================================================================
# apply -- production state (v0009-migrated; the load-bearing deploy path)
# ================================================================================


class TestApplyProductionState:
    def test_emitsDriveSummaryAddColumn(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0010.apply(_ctx(runner))
        adds = [
            s for s in runner.emittedSqls
            if 'ADD COLUMN data_quality' in s and 'drive_summary' in s
        ]
        assert len(adds) == 1

    def test_emitsDriveSummaryCheckAndIndex(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0010.apply(_ctx(runner))
        assert any(
            f'ADD CONSTRAINT {m0010.DRIVE_SUMMARY_CHECK_NAME}' in s
            for s in runner.emittedSqls
        )
        assert any(
            f'ADD INDEX {m0010.DRIVE_SUMMARY_INDEX_NAME}' in s
            for s in runner.emittedSqls
        )

    def test_rebuildsDriveStatisticsCheck(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0010.apply(_ctx(runner))
        drops = [
            s for s in runner.emittedSqls
            if f'DROP CONSTRAINT {m0010.DRIVE_STATISTICS_CHECK_NAME}' in s
        ]
        adds = [
            s for s in runner.emittedSqls
            if f'ADD CONSTRAINT {m0010.DRIVE_STATISTICS_CHECK_NAME}' in s
        ]
        assert len(drops) == 1
        assert len(adds) == 1

    def test_emitsExactlyTheExpectedAlters(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        m0010.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [
            m0010.ADD_DRIVE_SUMMARY_COLUMN_DDL,
            m0010.ADD_DRIVE_SUMMARY_CHECK_DDL,
            m0010.ADD_DRIVE_SUMMARY_INDEX_DDL,
            m0010.DROP_DRIVE_STATISTICS_CHECK_DDL,
            m0010.ADD_DRIVE_STATISTICS_CHECK_DDL,
            # US-371 rename substep runs after the US-363 substeps in apply().
            m0010.RENAME_DRIVE_STATISTICS_COLUMN_DDL,
            # US-365 vehicle_info ECU-lineage substep runs at the insertion
            # point (after US-371; before any US-370 FK substep).  Five ADD
            # COLUMNs, two MODIFY ... NOT NULL (the backfill UPDATE between them
            # is not an ALTER), the generated marker column, the unique index.
            m0010.ADD_VEHICLE_INFO_ECU_SIGNATURE_DDL,
            m0010.ADD_VEHICLE_INFO_CAL_SIGNATURE_DDL,
            m0010.ADD_VEHICLE_INFO_ECU_INSTALL_DDL,
            m0010.ADD_VEHICLE_INFO_ECU_REMOVAL_DDL,
            m0010.ADD_VEHICLE_INFO_NOTES_DDL,
            m0010.MODIFY_VEHICLE_INFO_ECU_SIGNATURE_NOT_NULL_DDL,
            m0010.MODIFY_VEHICLE_INFO_ECU_INSTALL_NOT_NULL_DDL,
            m0010.ADD_VEHICLE_INFO_ACTIVE_MARKER_DDL,
            m0010.ADD_VEHICLE_INFO_SINGLE_ACTIVE_INDEX_DDL,
            # US-372 invariant substep runs LAST (after the US-368 CREATE, which
            # is not an ALTER): the drive_id/source_id CHECK.  Its two backfill
            # UPDATEs are not ALTERs and so do not appear in this list.
            m0010.ADD_DRIVE_SUMMARY_DRIVE_ID_CHECK_DDL,
        ], '\n  '.join(['unexpected ALTER set:', *alters])


# ================================================================================
# apply -- fully-migrated / fresh create_all (idempotent no-op)
# ================================================================================


class TestApplyFullyMigrated:
    def test_emitsNoAlterTable(self) -> None:
        runner = FakeRunner()
        _scriptFullyMigratedState(runner)
        m0010.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], f'idempotent re-run must not ALTER; got {alters}'


# ================================================================================
# Failure paths
# ================================================================================


class TestFailureModes:
    def test_driveSummaryTableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.insert(0, (
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_summary'):
            m0010.apply(_ctx(runner))

    def test_addColumnFailureRaises(self) -> None:
        runner = FakeRunner()
        _scriptProductionPreMigrationState(runner)
        runner.handlers.insert(0, (
            'ADD COLUMN data_quality',
            lambda _sql: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='data_quality'):
            m0010.apply(_ctx(runner))

    def test_postProbeMissingColumnRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner()
        # Both column probes return the pre-add set (no data_quality), so the
        # post-condition probe trips.
        runner.handlers.append((
            'ck_drive_summary_data_quality',
            lambda _sql: _ok(stdout='0\n'),
        ))
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        runner.handlers.append((
            'information_schema.STATISTICS',
            lambda _sql: _ok(stdout='0\n'),
        ))
        runner.handlers.append((
            'information_schema.COLUMNS',
            lambda _sql: _ok(stdout=_DRIVE_SUMMARY_COLS_BEFORE),
        ))
        with pytest.raises(asm.SchemaProbeError, match='data_quality.*missing'):
            m0010.apply(_ctx(runner))


# ================================================================================
# US-365 / F-108 -- vehicle_info ECU-lineage substep
# ================================================================================


def _scriptVehicleInfoProduction(runner: FakeRunner) -> None:
    """vehicle_info exists with VIN-only columns; ECU columns + marker index
    absent.  Column probe returns BEFORE then AFTER (post-condition); index
    probe returns missing.
    """
    runner.handlers.append((
        'information_schema.TABLES', lambda _s: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.STATISTICS', lambda _s: _ok(stdout='0\n'),
    ))
    calls = {'n': 0}

    def colProbe(_s: str) -> subprocess.CompletedProcess[str]:
        calls['n'] += 1
        return _ok(
            stdout=_VEHICLE_INFO_COLS_BEFORE if calls['n'] == 1
            else _VEHICLE_INFO_COLS_AFTER,
        )

    runner.handlers.append(('information_schema.COLUMNS', colProbe))


def _scriptVehicleInfoMigrated(runner: FakeRunner) -> None:
    """vehicle_info already carries all ECU columns + the unique marker index."""
    runner.handlers.append((
        'information_schema.TABLES', lambda _s: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.STATISTICS', lambda _s: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'information_schema.COLUMNS',
        lambda _s: _ok(stdout=_VEHICLE_INFO_COLS_AFTER),
    ))


class TestVehicleInfoSubstepExports:
    def test_tableConstantMatchesOrm(self) -> None:
        from src.server.db.models import VehicleInfo
        assert m0010.VEHICLE_INFO_TABLE == VehicleInfo.__tablename__

    def test_markerColumnAndIndexMatchOrm(self) -> None:
        from src.server.db.models import (
            VEHICLE_INFO_ACTIVE_MARKER_COLUMN,
            VEHICLE_INFO_SINGLE_ACTIVE_INDEX,
            VehicleInfo,
        )
        # Migration references the same marker column + index name as the ORM.
        assert m0010.VEHICLE_INFO_ACTIVE_MARKER_COLUMN == (
            VEHICLE_INFO_ACTIVE_MARKER_COLUMN
        )
        ormIndexNames = {
            c.name for c in VehicleInfo.__table__.constraints if c.name
        }
        assert VEHICLE_INFO_SINGLE_ACTIVE_INDEX in ormIndexNames

    def test_markerDdlUsesOrmGeneratedExpression(self) -> None:
        from src.server.db.models import VEHICLE_INFO_ACTIVE_MARKER_EXPR
        assert VEHICLE_INFO_ACTIVE_MARKER_EXPR in (
            m0010.ADD_VEHICLE_INFO_ACTIVE_MARKER_DDL
        )
        assert 'STORED' in m0010.ADD_VEHICLE_INFO_ACTIVE_MARKER_DDL


class TestVehicleInfoDdlShape:
    def test_addColumnDdlsAreAdditiveAlters(self) -> None:
        for ddl in (
            m0010.ADD_VEHICLE_INFO_ECU_SIGNATURE_DDL,
            m0010.ADD_VEHICLE_INFO_CAL_SIGNATURE_DDL,
            m0010.ADD_VEHICLE_INFO_ECU_INSTALL_DDL,
            m0010.ADD_VEHICLE_INFO_ECU_REMOVAL_DDL,
            m0010.ADD_VEHICLE_INFO_NOTES_DDL,
        ):
            assert ddl.startswith('ALTER TABLE vehicle_info')
            assert 'ADD COLUMN' in ddl
            assert 'DROP' not in ddl.upper()

    def test_requiredColumnsTightenedToNotNull(self) -> None:
        assert 'NOT NULL' in m0010.MODIFY_VEHICLE_INFO_ECU_SIGNATURE_NOT_NULL_DDL
        assert 'NOT NULL' in m0010.MODIFY_VEHICLE_INFO_ECU_INSTALL_NOT_NULL_DDL

    def test_uniqueIndexDdlNamesMarkerColumn(self) -> None:
        ddl = m0010.ADD_VEHICLE_INFO_SINGLE_ACTIVE_INDEX_DDL
        assert 'ADD UNIQUE INDEX' in ddl
        assert m0010.VEHICLE_INFO_SINGLE_ACTIVE_INDEX in ddl
        assert m0010.VEHICLE_INFO_ACTIVE_MARKER_COLUMN in ddl

    def test_legacyBackfillUsesUnknownSentinel(self) -> None:
        from src.server.db.models import VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN
        ddl = m0010.BACKFILL_VEHICLE_INFO_LEGACY_DDL
        assert ddl.startswith('UPDATE vehicle_info')
        assert VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN in ddl


class TestVehicleInfoSubstepBehavior:
    def test_productionEmitsFiveAddColumns(self) -> None:
        runner = FakeRunner()
        _scriptVehicleInfoProduction(runner)
        m0010._applyVehicleInfoEcuColumns(_ctx(runner))
        adds = [
            s for s in runner.emittedSqls
            if s.startswith('ALTER TABLE vehicle_info') and 'ADD COLUMN' in s
            and 'ecu_active_marker' not in s
        ]
        assert len(adds) == 5, f'expected 5 ECU ADD COLUMNs, got {adds}'

    def test_productionEmitsMarkerAndUniqueIndex(self) -> None:
        runner = FakeRunner()
        _scriptVehicleInfoProduction(runner)
        m0010._applyVehicleInfoEcuColumns(_ctx(runner))
        assert any(
            'ecu_active_marker' in s and 'ADD COLUMN' in s
            for s in runner.emittedSqls
        )
        assert any(
            'ADD UNIQUE INDEX' in s
            and m0010.VEHICLE_INFO_SINGLE_ACTIVE_INDEX in s
            for s in runner.emittedSqls
        )

    def test_productionEmitsLegacyBackfillAndNotNullTighten(self) -> None:
        runner = FakeRunner()
        _scriptVehicleInfoProduction(runner)
        m0010._applyVehicleInfoEcuColumns(_ctx(runner))
        assert any(s.startswith('UPDATE vehicle_info') for s in runner.emittedSqls)
        modifies = [
            s for s in runner.emittedSqls
            if s.startswith('ALTER TABLE vehicle_info') and 'NOT NULL' in s
        ]
        assert len(modifies) == 2

    def test_migratedIsPureNoOp(self) -> None:
        """Fully-migrated re-run emits no ALTER and no backfill UPDATE."""
        runner = FakeRunner()
        _scriptVehicleInfoMigrated(runner)
        m0010._applyVehicleInfoEcuColumns(_ctx(runner))
        mutating = [
            s for s in runner.emittedSqls
            if s.startswith('ALTER TABLE') or s.startswith('UPDATE')
        ]
        assert mutating == [], f'idempotent re-run must not mutate; got {mutating}'

    def test_tableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES', lambda _s: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='vehicle_info'):
            m0010._applyVehicleInfoEcuColumns(_ctx(runner))
