################################################################################
# File Name: test_migration_0010_speed_pid_calibration.py
# Purpose/Description: Sprint 43 V0.28.0 (US-370 / F-076) -- migration unit tests
#                      for the v0010 speed_pid_calibration CREATE TABLE + 2-ECU
#                      seed substep.  New table (no prior version) so the substep
#                      mirrors v0005/US-368's CREATE-TABLE-IF-NOT-EXISTS +
#                      serverTableExists short-circuit + post-condition probe,
#                      then idempotently seeds the prior (MD346675, 1.0) + new
#                      (MD335287, 0.5 INITIAL ESTIMATE) ECU rows via INSERT IGNORE.
#                      Per Atlas option-(c) 2026-05-29: ecu_signature is a UNIQUE
#                      natural key (no FK to vehicle_info).  Hermetic FakeRunner;
#                      no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-29    | Rex (US-370) | Initial -- F-076 speed_pid_calibration CREATE +
#               |              | 2-ECU seed substep migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0010 speed_pid_calibration CREATE + seed substep (US-370)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES,
    SpeedPidCalibration,
)
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0010_us363_attribution_anomaly_data_quality as m0010,
)

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
    """TABLES-probe handler: 1st call (pre-check) absent, later calls present."""
    state = {'n': 0}

    def handler(_sql: str) -> subprocess.CompletedProcess[str]:
        state['n'] += 1
        return _ok(stdout='0\n' if state['n'] == 1 else '1\n')

    return handler


def _seeds(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if s.startswith('INSERT IGNORE INTO speed_pid_calibration')]


def _creates(runner: FakeRunner) -> list[str]:
    return [
        s for s in runner.emittedSqls
        if s.startswith('CREATE TABLE IF NOT EXISTS speed_pid_calibration')
    ]


# ================================================================================
# DDL shape
# ================================================================================


class TestSpeedPidCalibrationDdl:
    def test_tableConstantMatchesOrm(self) -> None:
        assert m0010.SPEED_PID_CALIBRATION_TABLE == SpeedPidCalibration.__tablename__

    def test_createDdlIsIfNotExists(self) -> None:
        assert m0010.CREATE_SPEED_PID_CALIBRATION_DDL.startswith(
            'CREATE TABLE IF NOT EXISTS speed_pid_calibration',
        )

    def test_createDdlHasAllAc1Columns(self) -> None:
        ddl = m0010.CREATE_SPEED_PID_CALIBRATION_DDL
        for col in (
            'id',
            'ecu_signature',
            'correction_factor',
            'capture_method',
            'captured_at_timestamp_utc',
            'captured_by',
            'provenance',
            'notes',
        ):
            assert col in ddl, f'CREATE DDL missing column {col!r}'

    def test_ecuSignatureIsVarchar32(self) -> None:
        assert 'ecu_signature VARCHAR(32)' in m0010.CREATE_SPEED_PID_CALIBRATION_DDL

    def test_correctionFactorIsDoubleNotNull(self) -> None:
        assert 'correction_factor DOUBLE NOT NULL' in \
            m0010.CREATE_SPEED_PID_CALIBRATION_DDL

    def test_provenanceIsTextNotNull(self) -> None:
        assert 'provenance TEXT NOT NULL' in m0010.CREATE_SPEED_PID_CALIBRATION_DDL

    def test_ecuSignatureHasUniqueKeyNoForeignKey(self) -> None:
        """option-(c): UNIQUE natural key, explicitly NO foreign key."""
        ddl = m0010.CREATE_SPEED_PID_CALIBRATION_DDL
        assert 'UNIQUE KEY' in ddl
        assert 'ecu_signature' in ddl
        assert 'FOREIGN KEY' not in ddl, 'option-(c): no FK to vehicle_info'
        assert 'REFERENCES' not in ddl

    def test_captureMethodCheckCarriesAllEnumValues(self) -> None:
        ddl = m0010.CREATE_SPEED_PID_CALIBRATION_DDL
        for value in SPEED_PID_CALIBRATION_CAPTURE_METHOD_VALUES:
            assert f"'{value}'" in ddl, f'CHECK enum missing {value!r}'


# ================================================================================
# Seed DDL values (grounded, no fabrication)
# ================================================================================


class TestSeedDdls:
    def test_priorEcuSeedValues(self) -> None:
        ddl = m0010.SEED_PRIOR_ECU_SPEED_PID_CALIBRATION_DDL
        assert ddl.startswith('INSERT IGNORE INTO speed_pid_calibration')
        assert "'MD346675'" in ddl
        assert '1.0' in ddl
        assert 'gear-math-drive-18-3rd-gear-fit' in ddl

    def test_newEcuSeedValues(self) -> None:
        ddl = m0010.SEED_NEW_ECU_SPEED_PID_CALIBRATION_DDL
        assert ddl.startswith('INSERT IGNORE INTO speed_pid_calibration')
        assert "'MD335287'" in ddl
        assert '0.5' in ddl
        assert 'rough-seed-drive-26-gear-math' in ddl

    def test_newEcuSeedNotesHasInitialEstimateAndQ2(self) -> None:
        """VC#5: new-ECU notes contains 'INITIAL ESTIMATE' + Q2 cross-reference."""
        ddl = m0010.SEED_NEW_ECU_SPEED_PID_CALIBRATION_DDL
        assert 'INITIAL ESTIMATE' in ddl
        assert 'Q2' in ddl


# ================================================================================
# Substep behavior
# ================================================================================


class TestSpeedPidCalibrationSubstep:
    def test_absentTableEmitsCreateThenTwoSeeds(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", _absentThenPresent(),
        ))
        m0010._applySpeedPidCalibrationTable(_ctx(runner))
        assert len(_creates(runner)) == 1
        assert len(_seeds(runner)) == 2

    def test_seedFollowsCreate(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", _absentThenPresent(),
        ))
        m0010._applySpeedPidCalibrationTable(_ctx(runner))
        emitted = runner.emittedSqls
        create_idx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('CREATE TABLE IF NOT EXISTS speed_pid_calibration')
        )
        seed_idxs = [
            i for i, s in enumerate(emitted)
            if s.startswith('INSERT IGNORE INTO speed_pid_calibration')
        ]
        assert all(i > create_idx for i in seed_idxs)

    def test_presentTableSkipsCreateButStillSeedsIdempotently(self) -> None:
        """Idempotent: existing table -> no CREATE; INSERT IGNORE seeds re-run
        safely (covers partial-success recovery + create_all-then-migrate)."""
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", lambda _s: _ok(stdout='1\n'),
        ))
        m0010._applySpeedPidCalibrationTable(_ctx(runner))
        assert _creates(runner) == []
        assert len(_seeds(runner)) == 2

    def test_createFailureRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", lambda _s: _ok(stdout='0\n'),
        ))
        runner.handlers.append((
            'CREATE TABLE IF NOT EXISTS speed_pid_calibration',
            lambda _s: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='speed_pid_calibration'):
            m0010._applySpeedPidCalibrationTable(_ctx(runner))

    def test_seedFailureRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", _absentThenPresent(),
        ))
        runner.handlers.append((
            'INSERT IGNORE INTO speed_pid_calibration',
            lambda _s: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='speed_pid_calibration'):
            m0010._applySpeedPidCalibrationTable(_ctx(runner))

    def test_postProbeMissingRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner()
        # Always absent: pre-check absent -> CREATE -> post-probe still absent.
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", lambda _s: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.SchemaProbeError, match='speed_pid_calibration'):
            m0010._applySpeedPidCalibrationTable(_ctx(runner))

    def test_docstringDocumentsUs365Ordering(self) -> None:
        """AC#4: US-365-before-US-370 ordering documented in the substep."""
        doc = m0010._applySpeedPidCalibrationTable.__doc__ or ''
        assert 'US-365' in doc


# ================================================================================
# apply() wiring
# ================================================================================


class TestApplyInvokesSpeedPidSubstep:
    def test_applyEmitsCreateWhenSpeedPidAbsent(self) -> None:
        """apply() runs the speed_pid_calibration substep at the insertion point.

        Everything else reports fully-migrated so only speed_pid_calibration is
        absent; apply() must emit exactly the speed_pid_calibration CREATE.
        """
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", _absentThenPresent(),
        ))
        runner.handlers.append(('ck_drive_summary_data_quality', lambda _s: _ok('1\n')))
        runner.handlers.append((
            'ck_drive_statistics_data_quality',
            lambda _s: _ok(
                "data_quality in ('full','sparse','below_threshold',"
                "'attribution_anomaly')\n",
            ),
        ))
        runner.handlers.append(('chk_drive_id_source_id', lambda _s: _ok('1\n')))
        runner.handlers.append(('information_schema.TABLES', lambda _s: _ok('1\n')))
        runner.handlers.append(('information_schema.STATISTICS', lambda _s: _ok('1\n')))

        def cols(sql: str) -> subprocess.CompletedProcess[str]:
            if "TABLE_NAME='drive_statistics'" in sql:
                return _ok(stdout='summary_id\nparameter_name\ndata_quality\n')
            if "TABLE_NAME='vehicle_info'" in sql:
                return _ok(stdout='ecu_signature\necu_active_marker\n')
            return _ok(stdout='data_quality\n')

        runner.handlers.append(('information_schema.COLUMNS', cols))

        m0010.apply(_ctx(runner))
        assert len(_creates(runner)) == 1, 'apply() must invoke the speed_pid substep'

    def test_speedPidCreateRunsAfterVehicleInfoColumns(self) -> None:
        """AC#4 ordering: US-365 vehicle_info substep runs before US-370.

        Both vehicle_info ECU columns and speed_pid_calibration are absent; the
        emitted-SQL order must put the vehicle_info ecu_signature ADD COLUMN
        before the speed_pid_calibration CREATE.
        """
        runner = FakeRunner()
        # speed_pid absent then present.
        runner.handlers.append((
            "TABLE_NAME='speed_pid_calibration'", _absentThenPresent(),
        ))
        # drive_summary / drive_statistics fully migrated.
        runner.handlers.append(('ck_drive_summary_data_quality', lambda _s: _ok('1\n')))
        runner.handlers.append((
            'ck_drive_statistics_data_quality',
            lambda _s: _ok(
                "data_quality in ('full','sparse','below_threshold',"
                "'attribution_anomaly')\n",
            ),
        ))
        runner.handlers.append(('chk_drive_id_source_id', lambda _s: _ok('1\n')))
        # Other tables present (incl. vehicle_info table); dtc_freeze_frame present.
        runner.handlers.append(('information_schema.TABLES', lambda _s: _ok('1\n')))
        runner.handlers.append(('information_schema.STATISTICS', lambda _s: _ok('0\n')))

        vi_calls = {'n': 0}

        def cols(sql: str) -> subprocess.CompletedProcess[str]:
            if "TABLE_NAME='drive_statistics'" in sql:
                return _ok(stdout='summary_id\nparameter_name\ndata_quality\n')
            if "TABLE_NAME='vehicle_info'" in sql:
                # ECU columns absent first (so the ADDs fire), present after.
                vi_calls['n'] += 1
                if vi_calls['n'] == 1:
                    return _ok(stdout='id\nsource_id\nsource_device\n')
                return _ok(stdout='id\necu_signature\necu_active_marker\n')
            return _ok(stdout='data_quality\n')

        runner.handlers.append(('information_schema.COLUMNS', cols))

        m0010.apply(_ctx(runner))
        emitted = runner.emittedSqls
        vi_add_idx = next(
            i for i, s in enumerate(emitted)
            if s == m0010.ADD_VEHICLE_INFO_ECU_SIGNATURE_DDL
        )
        spc_create_idx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('CREATE TABLE IF NOT EXISTS speed_pid_calibration')
        )
        assert vi_add_idx < spc_create_idx, 'US-365 must run before US-370'
