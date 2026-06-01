################################################################################
# File Name: test_migration_0011_speed_pid_rekey.py
# Purpose/Description: Sprint 44 V0.28.1 (US-374 / F-076 / B-076 first slice) --
#                      migration unit tests for the v0011 speed_pid_calibration
#                      RE-KEY substep.  v0010 (untouched, forward-only) creates the
#                      option-(c) ecu_signature natural-key shape; this v0011
#                      substep re-keys it FORWARD: ADD ecu_id (FK -> ecu.id),
#                      backfill by matching each row's ecu_signature to its ecu
#                      row, re-point the 2 seed provenance strings, FAIL LOUDLY on
#                      any unmatched row, MODIFY NOT NULL, ADD UNIQUE(ecu_id) + FK,
#                      then DROP the old ecu_signature UNIQUE key + column.
#                      Idempotent: gated on the ecu_signature column's PRESENCE
#                      (its terminal absence == already re-keyed / fresh
#                      create_all).  Hermetic FakeRunner; no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-01    | Rex (US-374) | Initial -- v0011 speed_pid_calibration ecu_id
#               |              | re-key substep migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0011 speed_pid_calibration ecu_id re-key substep (US-374)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
    SpeedPidCalibration,
)
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0011_us376_ecu_identity as m0011

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0011_*)
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


def _spcHandler(
    *, ecu_signature_present: bool, exists: bool = True,
) -> Callable[[str], subprocess.CompletedProcess[str]]:
    """speed_pid_calibration TABLES + COLUMNS probe (static).

    COLUMNS reports ``ecu_signature`` (option-(c) shape) when
    ``ecu_signature_present`` else the re-keyed shape (``ecu_id``, no signature).
    """
    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        if 'information_schema.TABLES' in sql:
            return _ok('1\n' if exists else '0\n')
        if 'information_schema.COLUMNS' in sql:
            cols = ['id', 'correction_factor', 'provenance']
            if ecu_signature_present:
                cols.append('ecu_signature')
            else:
                cols.append('ecu_id')
            return _ok('\n'.join(cols) + '\n')
        return _ok('')
    return handler


def _spcReKeyHandler() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """COLUMNS: ecu_signature present on entry, absent (ecu_id present) after."""
    state = {'n': 0}

    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        if 'information_schema.TABLES' in sql:
            return _ok('1\n')
        if 'information_schema.COLUMNS' in sql:
            state['n'] += 1
            if state['n'] == 1:
                return _ok('id\necu_signature\ncorrection_factor\nprovenance\n')
            return _ok('id\necu_id\ncorrection_factor\nprovenance\n')
        return _ok('')
    return handler


def _ecuTablesAbsentThenPresent() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """ecu TABLES probe: absent on the 1st probe (pre-CREATE), present after."""
    state = {'n': 0}

    def handler(_sql: str) -> subprocess.CompletedProcess[str]:
        state['n'] += 1
        return _ok('0\n' if state['n'] == 1 else '1\n')

    return handler


def _vehicleInfoMigrated() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """vehicle_info already fully migrated (ecu_id present) -> substep no-op."""
    def handler(sql: str) -> subprocess.CompletedProcess[str]:
        if 'information_schema.TABLES' in sql:
            return _ok('1\n')
        return _ok('id\nsource_id\necu_signature\ncal_signature\necu_id\n')
    return handler


# ================================================================================
# Re-key DDL shape
# ================================================================================


class TestReKeyDdl:
    def test_tableConstantMatchesOrm(self) -> None:
        assert m0011.SPEED_PID_CALIBRATION_TABLE == SpeedPidCalibration.__tablename__

    def test_addColumnIsNullableInt(self) -> None:
        assert m0011.ADD_SPEED_PID_ECU_ID_DDL == (
            'ALTER TABLE speed_pid_calibration ADD COLUMN ecu_id INT NULL;'
        )

    def test_backfillJoinsEcuOnSignature(self) -> None:
        ddl = m0011.BACKFILL_SPEED_PID_ECU_ID_DDL
        assert 'UPDATE speed_pid_calibration' in ddl
        assert 'JOIN ecu' in ddl
        assert 'spc.ecu_signature = e.ecu_signature' in ddl
        assert 'spc.ecu_id = e.id' in ddl
        assert 'WHERE spc.ecu_id IS NULL' in ddl

    def test_modifyNotNull(self) -> None:
        assert m0011.MODIFY_SPEED_PID_ECU_ID_NOT_NULL_DDL == (
            'ALTER TABLE speed_pid_calibration MODIFY ecu_id INT NOT NULL;'
        )

    def test_addUniqueOnEcuId(self) -> None:
        ddl = m0011.ADD_SPEED_PID_ECU_ID_UNIQUE_DDL
        assert 'uq_speed_pid_calibration_ecu_id' in ddl
        assert '(ecu_id)' in ddl

    def test_addFkReferencesEcuId(self) -> None:
        ddl = m0011.ADD_SPEED_PID_ECU_FK_DDL
        assert 'fk_speed_pid_calibration_ecu' in ddl
        assert 'FOREIGN KEY (ecu_id)' in ddl
        assert 'REFERENCES ecu(id)' in ddl

    def test_dropsOldSignatureUniqueThenColumn(self) -> None:
        assert 'uq_speed_pid_calibration_ecu_signature' in \
            m0011.DROP_SPEED_PID_ECU_SIGNATURE_UNIQUE_DDL
        assert 'DROP COLUMN ecu_signature' in \
            m0011.DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL


# ================================================================================
# Seed provenance re-point (grounded; Spool 2026-06-01) -- gates VC#6
# ================================================================================


class TestProvenanceRepoint:
    def test_priorEcuRepointIsEmpiricalPrefixed(self) -> None:
        ddl = m0011.REPOINT_PRIOR_ECU_PROVENANCE_DDL
        assert "ecu_signature = 'MD346675'" in ddl
        assert 'empirical-Drive-18-gear-math-fit' in ddl
        # VC#6: the prior-ECU seed MUST be empirical-prefixed (gate includes it).
        assert m0011.SPEED_PID_PRIOR_ECU_PROVENANCE.startswith(
            SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
        )

    def test_newEcuRepointIsNotEmpiricalPrefixed(self) -> None:
        ddl = m0011.REPOINT_NEW_ECU_PROVENANCE_DDL
        assert "ecu_signature = 'MD335287'" in ddl
        assert 'gear-math-sanity-check-Drive-26-CIO-corrected' in ddl
        # VC#6: the new-ECU rough seed must NOT be empirical-prefixed (excluded).
        assert not m0011.SPEED_PID_NEW_ECU_PROVENANCE.startswith(
            SPEED_PID_CALIBRATION_EMPIRICAL_PROVENANCE_PREFIX,
        )


# ================================================================================
# _applySpeedPidCalibrationRekey substep behavior
# ================================================================================


class TestReKeySubstep:
    def test_signaturePresentEmitsFullReKey(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(('speed_pid_calibration WHERE ecu_id IS NULL', lambda _s: _ok('0\n')))
        runner.handlers.append(('speed_pid_calibration', _spcReKeyHandler()))
        m0011._applySpeedPidCalibrationRekey(_ctx(runner))
        emitted = runner.emittedSqls
        for ddl in (
            m0011.ADD_SPEED_PID_ECU_ID_DDL,
            m0011.BACKFILL_SPEED_PID_ECU_ID_DDL,
            m0011.REPOINT_PRIOR_ECU_PROVENANCE_DDL,
            m0011.REPOINT_NEW_ECU_PROVENANCE_DDL,
            m0011.MODIFY_SPEED_PID_ECU_ID_NOT_NULL_DDL,
            m0011.ADD_SPEED_PID_ECU_ID_UNIQUE_DDL,
            m0011.ADD_SPEED_PID_ECU_FK_DDL,
            m0011.DROP_SPEED_PID_ECU_SIGNATURE_UNIQUE_DDL,
            m0011.DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL,
        ):
            assert ddl in emitted, f'missing re-key DDL: {ddl!r}'

    def test_dropColumnComesAfterBackfillAndUniqueDrop(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(('speed_pid_calibration WHERE ecu_id IS NULL', lambda _s: _ok('0\n')))
        runner.handlers.append(('speed_pid_calibration', _spcReKeyHandler()))
        m0011._applySpeedPidCalibrationRekey(_ctx(runner))
        emitted = runner.emittedSqls
        backfill_idx = emitted.index(m0011.BACKFILL_SPEED_PID_ECU_ID_DDL)
        drop_uq_idx = emitted.index(m0011.DROP_SPEED_PID_ECU_SIGNATURE_UNIQUE_DDL)
        drop_col_idx = emitted.index(m0011.DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL)
        assert backfill_idx < drop_col_idx, 'backfill must precede dropping its source'
        assert drop_uq_idx < drop_col_idx, 'unique key dropped before its column'

    def test_signatureAbsentIsNoOp(self) -> None:
        """Fresh create_all / already re-keyed: ecu_signature gone -> no-op."""
        runner = FakeRunner()
        runner.handlers.append(
            ('speed_pid_calibration', _spcHandler(ecu_signature_present=False)),
        )
        m0011._applySpeedPidCalibrationRekey(_ctx(runner))
        emitted = runner.emittedSqls
        assert m0011.ADD_SPEED_PID_ECU_ID_DDL not in emitted
        assert m0011.BACKFILL_SPEED_PID_ECU_ID_DDL not in emitted
        assert m0011.DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL not in emitted

    def test_unmatchedRowFailsLoudly(self) -> None:
        runner = FakeRunner()
        # Backfill leaves 1 row unresolved -> FAIL LOUDLY, never NULL ecu_id.
        runner.handlers.append(('speed_pid_calibration WHERE ecu_id IS NULL', lambda _s: _ok('1\n')))
        runner.handlers.append(
            ('speed_pid_calibration', _spcHandler(ecu_signature_present=True)),
        )
        with pytest.raises(asm.MigrationError, match='speed_pid_calibration'):
            m0011._applySpeedPidCalibrationRekey(_ctx(runner))
        emitted = runner.emittedSqls
        # The destructive ops must NOT have run on the unresolved table.
        assert m0011.MODIFY_SPEED_PID_ECU_ID_NOT_NULL_DDL not in emitted
        assert m0011.DROP_SPEED_PID_ECU_SIGNATURE_COLUMN_DDL not in emitted

    def test_missingTableRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            ('speed_pid_calibration', _spcHandler(ecu_signature_present=True, exists=False)),
        )
        with pytest.raises(asm.MigrationError, match='speed_pid_calibration'):
            m0011._applySpeedPidCalibrationRekey(_ctx(runner))


# ================================================================================
# apply() wiring + cross-substep ordering
# ================================================================================


class TestApplyWiring:
    def test_applyInvokesReKeyAfterEcuCreate(self) -> None:
        """ecu identity table must be created before the speed_pid FK re-key."""
        runner = FakeRunner()
        # ecu table absent -> CREATE, then present (keyed on its TABLES probe).
        runner.handlers.append(("TABLE_NAME='ecu'", _ecuTablesAbsentThenPresent()))
        # vehicle_info already fully migrated (ecu_id present) -> substep no-op.
        runner.handlers.append(("TABLE_NAME='vehicle_info'", _vehicleInfoMigrated()))
        # speed_pid re-key path.
        runner.handlers.append(
            ('speed_pid_calibration WHERE ecu_id IS NULL', lambda _s: _ok('0\n')),
        )
        runner.handlers.append(('speed_pid_calibration', _spcReKeyHandler()))

        m0011.apply(_ctx(runner))
        emitted = runner.emittedSqls
        ecu_create_idx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('CREATE TABLE IF NOT EXISTS ecu')
        )
        spc_add_idx = next(
            i for i, s in enumerate(emitted)
            if s == m0011.ADD_SPEED_PID_ECU_ID_DDL
        )
        assert ecu_create_idx < spc_add_idx, 'ecu must exist before the speed_pid re-key'
