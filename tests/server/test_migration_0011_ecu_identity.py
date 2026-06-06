################################################################################
# File Name: test_migration_0011_ecu_identity.py
# Purpose/Description: Sprint 44 V0.28.1 (US-376 / B-076 first slice) -- migration
#                      unit tests for v0011: CREATE the normalized ecu identity
#                      table (pair-keyed) + seed 3 grounded rows, then ADD
#                      vehicle_info.ecu_id, backfill it by matching each row's
#                      (ecu_signature, cal_signature) text to its ecu row
#                      (COALESCE(cal, sig) maps the legacy NULL-cal sentinel),
#                      FAIL LOUDLY on any unmatched row, MODIFY NOT NULL, and ADD
#                      the FK.  v0010 is untouched (forward-only).  Hermetic
#                      FakeRunner; no SSH, no MariaDB.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-376) | Initial -- v0011 ecu table + vehicle_info.ecu_id
#               |              | FK migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0011 ecu-identity + vehicle_info.ecu_id migration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    ECU_SEED_PAIRS,
    Ecu,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0011_us376_ecu_identity as m0011

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0010_*)
# ================================================================================


@dataclass
class FakeRunner:
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
        self.calls.append({'argv': list(argv), 'input': sql})
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
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _absentThenPresent() -> Callable[[str], subprocess.CompletedProcess[str]]:
    state = {'n': 0}

    def handler(_sql: str) -> subprocess.CompletedProcess[str]:
        state['n'] += 1
        return _ok(stdout='0\n' if state['n'] == 1 else '1\n')

    return handler


def _seeds(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if s.startswith('INSERT IGNORE INTO ecu')]


def _creates(runner: FakeRunner) -> list[str]:
    return [
        s for s in runner.emittedSqls
        if s.startswith('CREATE TABLE IF NOT EXISTS ecu')
    ]


# ================================================================================
# Registry + version
# ================================================================================


class TestRegistration:
    def test_v0011RegisteredBeforeV0012(self) -> None:
        # v0012 (US-377 data_quality widen) was appended after v0011; the
        # durable invariant is that the registry stays sorted ascending and
        # v0011 sits immediately before v0012 (the tail is asserted by the
        # v0012 migration test).
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert versions[versions.index('0011') + 1] == '0012'

    def test_versionIs0011(self) -> None:
        assert m0011.VERSION == '0011'

    def test_v0010NotModifiedForwardOnly(self) -> None:
        """v0011 is a NEW module -- it must not redefine v0010's version."""
        assert m0011.VERSION not in {'0010'}


# ================================================================================
# ecu CREATE + seed DDL shape
# ================================================================================


class TestEcuDdl:
    def test_tableConstantMatchesOrm(self) -> None:
        assert m0011.ECU_TABLE == Ecu.__tablename__ == 'ecu'

    def test_createIsIfNotExists(self) -> None:
        assert m0011.CREATE_ECU_DDL.startswith('CREATE TABLE IF NOT EXISTS ecu')

    def test_createHasOnlyIdentityColumns(self) -> None:
        ddl = m0011.CREATE_ECU_DDL
        for col in ('id', 'ecu_signature', 'cal_signature'):
            assert col in ddl
        # No lineage / timestamp columns belong on the identity dimension.
        # Check only the column-definition portion (the table COMMENT
        # legitimately uses words like "per-lineage-row").
        coldefs = ddl.split('COMMENT')[0].lower()
        for forbidden in ('install', 'removal', 'timestamp', 'lineage'):
            assert forbidden not in coldefs, f'ecu must not carry {forbidden!r}'

    def test_signaturesAreVarchar32NotNull(self) -> None:
        ddl = m0011.CREATE_ECU_DDL
        assert 'ecu_signature VARCHAR(32) NOT NULL' in ddl
        assert 'cal_signature VARCHAR(32) NOT NULL' in ddl

    def test_pairUniqueKey(self) -> None:
        ddl = m0011.CREATE_ECU_DDL
        assert 'uq_ecu_signature_cal_signature' in ddl
        assert '(ecu_signature, cal_signature)' in ddl

    def test_carriesImmutabilityComment(self) -> None:
        ddl = m0011.CREATE_ECU_DDL.lower()
        assert 'comment' in ddl
        assert 'immutable' in ddl
        assert 'unkcal' in ddl

    def test_threeSeedsCoverAllPairs(self) -> None:
        joined = '\n'.join(m0011.SEED_ECU_DDLS)
        assert len(m0011.SEED_ECU_DDLS) == 3
        for sig, cal in ECU_SEED_PAIRS:
            assert f"('{sig}', '{cal}')" in joined, f'missing seed ({sig},{cal})'

    def test_seedsAreInsertIgnore(self) -> None:
        for ddl in m0011.SEED_ECU_DDLS:
            assert ddl.startswith('INSERT IGNORE INTO ecu (ecu_signature, cal_signature)')


# ================================================================================
# vehicle_info.ecu_id DDL shape
# ================================================================================


class TestVehicleInfoEcuIdDdl:
    def test_addColumnIsNullableInt(self) -> None:
        assert m0011.ADD_VEHICLE_INFO_ECU_ID_DDL == (
            'ALTER TABLE vehicle_info ADD COLUMN ecu_id INT NULL;'
        )

    def test_backfillJoinsEcuAndCoalescesCal(self) -> None:
        ddl = m0011.BACKFILL_VEHICLE_INFO_ECU_ID_DDL
        assert 'UPDATE vehicle_info' in ddl
        assert 'JOIN ecu' in ddl
        # The legacy NULL-cal sentinel resolves via COALESCE(cal, sig).
        assert 'COALESCE(vi.cal_signature, vi.ecu_signature)' in ddl
        # Derives the transitional text column from the ecu row (coherence).
        assert 'vi.cal_signature = e.cal_signature' in ddl
        assert 'vi.ecu_id = e.id' in ddl

    def test_modifyNotNull(self) -> None:
        assert m0011.MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL == (
            'ALTER TABLE vehicle_info MODIFY ecu_id INT NOT NULL;'
        )

    def test_addFkReferencesEcuId(self) -> None:
        ddl = m0011.ADD_VEHICLE_INFO_ECU_FK_DDL
        assert 'fk_vehicle_info_ecu' in ddl
        assert 'FOREIGN KEY (ecu_id)' in ddl
        assert 'REFERENCES ecu(id)' in ddl


# ================================================================================
# _applyEcuTable substep behavior
# ================================================================================


class TestEcuTableSubstep:
    def test_absentEmitsCreateThenThreeSeeds(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("TABLE_NAME='ecu'", _absentThenPresent()))
        m0011._applyEcuTable(_ctx(runner))
        assert len(_creates(runner)) == 1
        assert len(_seeds(runner)) == 3

    def test_presentSkipsCreateButStillSeeds(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("TABLE_NAME='ecu'", lambda _s: _ok(stdout='1\n')))
        m0011._applyEcuTable(_ctx(runner))
        assert _creates(runner) == []
        assert len(_seeds(runner)) == 3

    def test_createFailureRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("TABLE_NAME='ecu'", lambda _s: _ok(stdout='0\n')))
        runner.handlers.append(
            ('CREATE TABLE IF NOT EXISTS ecu', lambda _s: _fail('Lock wait')),
        )
        with pytest.raises(asm.MigrationError, match='ecu'):
            m0011._applyEcuTable(_ctx(runner))

    def test_postProbeMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("TABLE_NAME='ecu'", lambda _s: _ok(stdout='0\n')))
        with pytest.raises(asm.SchemaProbeError, match='ecu'):
            m0011._applyEcuTable(_ctx(runner))


# ================================================================================
# _applyVehicleInfoEcuIdFk substep behavior
# ================================================================================


def _viColsHandler(present: bool) -> Callable[[str], subprocess.CompletedProcess[str]]:
    """COLUMNS probe: vehicle_info with or without ecu_id (static)."""
    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        if "TABLE_NAME='vehicle_info'" in sql:
            cols = 'id\nsource_id\necu_signature\ncal_signature\n'
            if present:
                cols += 'ecu_id\n'
            return _ok(stdout=cols)
        return _ok(stdout='')
    return handler


def _viColsAbsentThenPresent() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """COLUMNS probe: ecu_id absent on the entry probe, present after the ADD."""
    state = {'n': 0}

    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        if "TABLE_NAME='vehicle_info'" in sql:
            state['n'] += 1
            cols = 'id\nsource_id\necu_signature\ncal_signature\n'
            if state['n'] > 1:
                cols += 'ecu_id\n'
            return _ok(stdout=cols)
        return _ok(stdout='')
    return handler


class TestVehicleInfoEcuIdSubstep:
    def test_freshAddEmitsAddBackfillModifyFk(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("information_schema.TABLES", lambda _s: _ok('1\n')))
        runner.handlers.append(("information_schema.COLUMNS", _viColsAbsentThenPresent()))
        # No unresolved rows after backfill.
        runner.handlers.append(("WHERE ecu_id IS NULL", lambda _s: _ok('0\n')))
        m0011._applyVehicleInfoEcuIdFk(_ctx(runner))
        emitted = runner.emittedSqls
        assert m0011.ADD_VEHICLE_INFO_ECU_ID_DDL in emitted
        assert m0011.BACKFILL_VEHICLE_INFO_ECU_ID_DDL in emitted
        assert m0011.MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL in emitted
        assert m0011.ADD_VEHICLE_INFO_ECU_FK_DDL in emitted

    def test_alreadyPresentIsNoOp(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("information_schema.TABLES", lambda _s: _ok('1\n')))
        runner.handlers.append(("information_schema.COLUMNS", _viColsHandler(present=True)))
        m0011._applyVehicleInfoEcuIdFk(_ctx(runner))
        emitted = runner.emittedSqls
        assert m0011.ADD_VEHICLE_INFO_ECU_ID_DDL not in emitted
        assert m0011.BACKFILL_VEHICLE_INFO_ECU_ID_DDL not in emitted
        assert m0011.MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL not in emitted

    def test_unmatchedRowFailsLoudly(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(("information_schema.TABLES", lambda _s: _ok('1\n')))
        runner.handlers.append(("information_schema.COLUMNS", _viColsHandler(present=False)))
        # Backfill left 2 rows unresolved -> FAIL LOUDLY, never NULL ecu_id.
        runner.handlers.append(("WHERE ecu_id IS NULL", lambda _s: _ok('2\n')))
        with pytest.raises(asm.MigrationError, match='ecu'):
            m0011._applyVehicleInfoEcuIdFk(_ctx(runner))
        # MODIFY NOT NULL must NOT have run on the unresolved table.
        assert m0011.MODIFY_VEHICLE_INFO_ECU_ID_NOT_NULL_DDL not in runner.emittedSqls


# ================================================================================
# apply() wiring + ordering
# ================================================================================


class TestApplyOrdering:
    def test_ecuCreatedBeforeVehicleInfoFk(self) -> None:
        """ecu table must exist before the vehicle_info FK references it."""
        runner = FakeRunner()
        runner.handlers.append(("TABLE_NAME='ecu'", _absentThenPresent()))
        runner.handlers.append(("information_schema.TABLES", lambda _s: _ok('1\n')))
        runner.handlers.append(("information_schema.COLUMNS", _viColsAbsentThenPresent()))
        runner.handlers.append(("WHERE ecu_id IS NULL", lambda _s: _ok('0\n')))

        m0011.apply(_ctx(runner))
        emitted = runner.emittedSqls
        ecu_create_idx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('CREATE TABLE IF NOT EXISTS ecu')
        )
        fk_idx = next(
            i for i, s in enumerate(emitted)
            if s == m0011.ADD_VEHICLE_INFO_ECU_FK_DDL
        )
        assert ecu_create_idx < fk_idx, 'ecu must be created before the FK'
