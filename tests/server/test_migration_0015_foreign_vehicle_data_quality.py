################################################################################
# File Name: test_migration_0015_foreign_vehicle_data_quality.py
# Purpose/Description: US-424 (F-116) migration unit tests for v0015 -- widen the
#                      data_quality CHECK enums on drive_summary + drive_statistics
#                      with 'foreign_vehicle' (DROP + re-ADD the named
#                      constraint).  Verifies DDL parity against the ORM enums,
#                      INFORMATION_SCHEMA-probe idempotency (production emits the
#                      rebuild; already-widened DB is a no-op), post-condition
#                      probe, failure propagation, and registry registration.
#                      Hermetic FakeRunner -- no SSH, no MariaDB (mirrors
#                      test_migration_0010_attribution_anomaly_data_quality).
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-424) | Initial -- F-116 foreign-vehicle data_quality
#               |              | CHECK-widen migration tests.
# 2026-09-04    | Rex (US-675) | Registry guard de-fused.  RED since v0016
#               |              | because it asserted "v0015 is LAST" -- a fact
#               |              | with a shelf life.  Restated as PLACEMENT
#               |              | (follows v0014) + a shelf-life proof that
#               |              | re-runs the guard against a widened registry.
# ================================================================================
################################################################################

"""TDD tests for the v0015 foreign_vehicle data_quality CHECK-widen migration."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    DATA_QUALITY_FOREIGN_VEHICLE,
    DRIVE_STATISTICS_DATA_QUALITY_VALUES,
    DRIVE_SUMMARY_DATA_QUALITY_VALUES,
    DriveStatistic,
    DriveSummary,
)
from src.server.migrations import ALL_MIGRATIONS, Migration
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0015_us424_foreign_vehicle_data_quality as m0015,
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


# CHECK_CLAUSE strings -- stale (pre-v0015, no foreign_vehicle) then widened.
_SUMMARY_CLAUSE_STALE = "data_quality in ('full','attribution_anomaly')\n"
_SUMMARY_CLAUSE_WIDE = (
    "data_quality in ('full','attribution_anomaly','foreign_vehicle')\n"
)
_STATS_CLAUSE_STALE = (
    "data_quality in ('full','sparse','below_threshold','attribution_anomaly')\n"
)
_STATS_CLAUSE_WIDE = (
    "data_quality in ('full','sparse','below_threshold','attribution_anomaly',"
    "'foreign_vehicle')\n"
)


def _scriptProductionState(runner: FakeRunner) -> None:
    """Live state: both CHECKs exist with the stale (no foreign_vehicle) clause.

    Each table's CHECK_CLAUSE probe returns the stale clause on the entry probe
    and the widened clause on the post-condition probe.
    """
    runner.handlers.append((
        'information_schema.TABLES', lambda _s: _ok(stdout='1\n'),
    ))

    summaryCalls = {'n': 0}

    def summaryClause(_s: str) -> subprocess.CompletedProcess[str]:
        summaryCalls['n'] += 1
        return _ok(
            stdout=_SUMMARY_CLAUSE_STALE if summaryCalls['n'] == 1
            else _SUMMARY_CLAUSE_WIDE,
        )

    runner.handlers.append(('ck_drive_summary_data_quality', summaryClause))

    statsCalls = {'n': 0}

    def statsClause(_s: str) -> subprocess.CompletedProcess[str]:
        statsCalls['n'] += 1
        return _ok(
            stdout=_STATS_CLAUSE_STALE if statsCalls['n'] == 1
            else _STATS_CLAUSE_WIDE,
        )

    runner.handlers.append(('ck_drive_statistics_data_quality', statsClause))


def _scriptFullyMigratedState(runner: FakeRunner) -> None:
    """Both CHECKs already carry foreign_vehicle (fresh create_all or re-run)."""
    runner.handlers.append((
        'information_schema.TABLES', lambda _s: _ok(stdout='1\n'),
    ))
    runner.handlers.append((
        'ck_drive_summary_data_quality',
        lambda _s: _ok(stdout=_SUMMARY_CLAUSE_WIDE),
    ))
    runner.handlers.append((
        'ck_drive_statistics_data_quality',
        lambda _s: _ok(stdout=_STATS_CLAUSE_WIDE),
    ))


# ================================================================================
# Module shape + registry
# ================================================================================


class TestModuleExports:
    def test_versionIs0015(self) -> None:
        assert m0015.VERSION == '0015'

    def test_descriptionMentionsUs424(self) -> None:
        assert 'US-424' in m0015.DESCRIPTION

    def test_descriptionMentionsForeignVehicle(self) -> None:
        assert 'foreign_vehicle' in m0015.DESCRIPTION

    def test_migrationSymbolPresent(self) -> None:
        assert m0015.MIGRATION.version == '0015'
        assert callable(m0015.MIGRATION.applyFn)

    def test_inAllMigrations(self) -> None:
        assert '0015' in [m.version for m in ALL_MIGRATIONS]

    def test_v0015RegisteredAfterV0014AndSorted(self) -> None:
        """Placement, not the absolute tail.

        RENAMED from ``test_registryStaysSortedWithV0015AtTail`` by US-675.
        That guard asserted ``versions[-1] == '0015'`` and had been RED since
        v0016 landed -- four versions of standing red.

        "Is LAST" was never an invariant.  It is a fact with a shelf life:
        every future migration falsifies it simply by existing, so the guard
        must be hand-edited on each one or it goes red and stays red.  Bumping
        the literal to the current tail only re-arms the same fuse, so the
        claim is restated as PLACEMENT, which survives every append.

        Matches the pattern ARCH-020 established on v0024 and that
        v0018 / v0020-v0024 already use.  The placement claim is not
        redundant: v0015 has no successor test file, so nothing else in the
        suite pins where it sits in the chain.
        """
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0015' in versions
        assert versions[versions.index('0015') - 1] == '0014'

    def test_v0015GuardSurvivesTheNextMigration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """US-675 VC2 -- the shelf-life proof, and why this file has two guards.

        Appends a hypothetical future migration and RE-RUNS THE REAL GUARD
        above against the widened registry -- ``self.test_...()``, not a copy
        of its assertion body, so this cannot drift away from the thing it
        protects.

        Green here means the guard cannot be re-broken by the mere act of
        adding v0026.  Restoring ``assert versions[-1] == '0015'`` still
        passes on today's registry and fails HERE -- which is precisely the
        failure mode that let the original guard rot unnoticed for four
        versions.
        """
        hypothetical = Migration(
            version='9999',
            description='hypothetical future migration (US-675 shelf-life probe)',
            applyFn=lambda _ctx: None,
        )
        monkeypatch.setattr(
            sys.modules[__name__],
            'ALL_MIGRATIONS',
            (*ALL_MIGRATIONS, hypothetical),
        )

        self.test_v0015RegisteredAfterV0014AndSorted()

    def test_constantsMatchOrm(self) -> None:
        assert m0015.DRIVE_SUMMARY_TABLE == DriveSummary.__tablename__
        assert m0015.DRIVE_STATISTICS_TABLE == DriveStatistic.__tablename__

    def test_checkNamesMatchOrm(self) -> None:
        for model, name in (
            (DriveSummary, m0015.DRIVE_SUMMARY_CHECK_NAME),
            (DriveStatistic, m0015.DRIVE_STATISTICS_CHECK_NAME),
        ):
            ormCheckNames = {
                c.name for c in model.__table__.constraints
                if c.name and 'data_quality' in c.name
            }
            assert name in ormCheckNames, (
                f'{name!r} must match the ORM; ORM has {ormCheckNames}'
            )


# ================================================================================
# DDL parity -- ADD DDLs carry foreign_vehicle + every ORM enum value
# ================================================================================


class TestDdlParity:
    def test_summaryDropTargetsNamedConstraint(self) -> None:
        ddl = m0015.DROP_DRIVE_SUMMARY_CHECK_DDL
        assert ddl.startswith('ALTER TABLE drive_summary')
        assert f'DROP CONSTRAINT {m0015.DRIVE_SUMMARY_CHECK_NAME}' in ddl

    def test_statsDropTargetsNamedConstraint(self) -> None:
        ddl = m0015.DROP_DRIVE_STATISTICS_CHECK_DDL
        assert ddl.startswith('ALTER TABLE drive_statistics')
        assert f'DROP CONSTRAINT {m0015.DRIVE_STATISTICS_CHECK_NAME}' in ddl

    def test_summaryAddIncludesForeignVehicleAndAllOrmValues(self) -> None:
        ddl = m0015.ADD_DRIVE_SUMMARY_CHECK_DDL
        assert DATA_QUALITY_FOREIGN_VEHICLE in ddl
        for value in DRIVE_SUMMARY_DATA_QUALITY_VALUES:
            assert f"'{value}'" in ddl
        assert f'ADD CONSTRAINT {m0015.DRIVE_SUMMARY_CHECK_NAME}' in ddl

    def test_statsAddIncludesForeignVehicleAndAllOrmValues(self) -> None:
        ddl = m0015.ADD_DRIVE_STATISTICS_CHECK_DDL
        assert DATA_QUALITY_FOREIGN_VEHICLE in ddl
        for value in DRIVE_STATISTICS_DATA_QUALITY_VALUES:
            assert f"'{value}'" in ddl
        assert f'ADD CONSTRAINT {m0015.DRIVE_STATISTICS_CHECK_NAME}' in ddl

    def test_ormEnumsCarryForeignVehicle(self) -> None:
        assert DATA_QUALITY_FOREIGN_VEHICLE in DRIVE_SUMMARY_DATA_QUALITY_VALUES
        assert DATA_QUALITY_FOREIGN_VEHICLE in DRIVE_STATISTICS_DATA_QUALITY_VALUES


# ================================================================================
# apply -- production state (the load-bearing deploy path)
# ================================================================================


class TestApplyProductionState:
    def test_rebuildsBothChecks(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        m0015.apply(_ctx(runner))
        for checkName in (
            m0015.DRIVE_SUMMARY_CHECK_NAME,
            m0015.DRIVE_STATISTICS_CHECK_NAME,
        ):
            drops = [
                s for s in runner.emittedSqls
                if f'DROP CONSTRAINT {checkName}' in s
            ]
            adds = [
                s for s in runner.emittedSqls
                if f'ADD CONSTRAINT {checkName}' in s
            ]
            assert len(drops) == 1, f'{checkName}: {drops}'
            assert len(adds) == 1, f'{checkName}: {adds}'

    def test_emitsExactlyTheExpectedAlters(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        m0015.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [
            m0015.DROP_DRIVE_SUMMARY_CHECK_DDL,
            m0015.ADD_DRIVE_SUMMARY_CHECK_DDL,
            m0015.DROP_DRIVE_STATISTICS_CHECK_DDL,
            m0015.ADD_DRIVE_STATISTICS_CHECK_DDL,
        ], '\n  '.join(['unexpected ALTER set:', *alters])


# ================================================================================
# apply -- fully-migrated / fresh create_all (idempotent no-op)
# ================================================================================


class TestApplyFullyMigrated:
    def test_emitsNoAlterTable(self) -> None:
        runner = FakeRunner()
        _scriptFullyMigratedState(runner)
        m0015.apply(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], f'idempotent re-run must not ALTER; got {alters}'


# ================================================================================
# Failure paths
# ================================================================================


class TestFailureModes:
    def test_tableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.insert(0, (
            'information_schema.TABLES', lambda _s: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_summary'):
            m0015.apply(_ctx(runner))

    def test_addFailureRaises(self) -> None:
        runner = FakeRunner()
        _scriptProductionState(runner)
        runner.handlers.insert(0, (
            f'ADD CONSTRAINT {m0015.DRIVE_SUMMARY_CHECK_NAME}',
            lambda _s: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='ck_drive_summary_data_quality'):
            m0015.apply(_ctx(runner))

    def test_postProbeStillStaleRaisesSchemaProbeError(self) -> None:
        """The post-condition probe never sees foreign_vehicle -> raises."""
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES', lambda _s: _ok(stdout='1\n'),
        ))
        # Both probes (entry + post) return the stale clause -> post-condition trips.
        runner.handlers.append((
            'ck_drive_summary_data_quality',
            lambda _s: _ok(stdout=_SUMMARY_CLAUSE_STALE),
        ))
        with pytest.raises(asm.SchemaProbeError, match='foreign_vehicle'):
            m0015.apply(_ctx(runner))
