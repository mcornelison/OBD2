################################################################################
# File Name: test_migration_0010_dtc_freeze_frame.py
# Purpose/Description: Sprint 43 V0.28.0 (US-368 / F-109) -- migration unit tests
#                      for the v0010 dtc_freeze_frame CREATE TABLE substep.  The
#                      freeze-frame table is brand new (no prior version), so the
#                      substep mirrors v0005's CREATE-TABLE-IF-NOT-EXISTS +
#                      serverTableExists short-circuit + post-condition probe
#                      pattern.  Verifies DDL shape (columns, FKs, JSON, unique
#                      key), absent->create, present->no-op idempotency, failure
#                      propagation, and that the shared apply() invokes it.
#                      Hermetic FakeRunner; no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- F-109 dtc_freeze_frame CREATE TABLE
#               |              | substep migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0010 dtc_freeze_frame CREATE TABLE substep (US-368)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import DtcFreezeFrame
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0010_us363_attribution_anomaly_data_quality as m0010,
)

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0009/0010)
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


def _freezeFrameAbsentThenPresent() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """TABLES-probe handler: 1st call (pre-check) absent, later calls present."""
    state = {'n': 0}

    def handler(_sql: str) -> subprocess.CompletedProcess[str]:
        state['n'] += 1
        return _ok(stdout='0\n' if state['n'] == 1 else '1\n')

    return handler


# ================================================================================
# Module exports + DDL shape
# ================================================================================


class TestDtcFreezeFrameDdl:
    def test_tableConstantMatchesOrm(self) -> None:
        assert m0010.DTC_FREEZE_FRAME_TABLE == DtcFreezeFrame.__tablename__

    def test_createDdlIsIfNotExists(self) -> None:
        ddl = m0010.CREATE_DTC_FREEZE_FRAME_DDL
        assert ddl.startswith('CREATE TABLE IF NOT EXISTS dtc_freeze_frame')

    def test_createDdlHasAllAc1Columns(self) -> None:
        ddl = m0010.CREATE_DTC_FREEZE_FRAME_DDL
        for col in (
            'id',
            'dtc_log_id',
            'captured_at_timestamp_utc',
            'pid_responses_json',
            'vehicle_info_id',
        ):
            assert col in ddl, f'CREATE DDL missing column {col!r}'

    def test_createDdlHasJsonColumn(self) -> None:
        assert 'pid_responses_json         JSON' in m0010.CREATE_DTC_FREEZE_FRAME_DDL \
            or 'pid_responses_json JSON' in m0010.CREATE_DTC_FREEZE_FRAME_DDL

    def test_createDdlHasForeignKeys(self) -> None:
        ddl = m0010.CREATE_DTC_FREEZE_FRAME_DDL
        assert 'REFERENCES dtc_log(id)' in ddl
        assert 'REFERENCES vehicle_info(id)' in ddl

    def test_createDdlHasSourceUniqueKey(self) -> None:
        ddl = m0010.CREATE_DTC_FREEZE_FRAME_DDL
        assert 'UNIQUE KEY' in ddl
        assert '(source_device, source_id)' in ddl


# ================================================================================
# Substep behavior
# ================================================================================


class TestDtcFreezeFrameSubstep:
    def test_absentTableEmitsCreate(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='dtc_freeze_frame'", _freezeFrameAbsentThenPresent(),
        ))
        m0010._applyDtcFreezeFrameTable(_ctx(runner))
        creates = [
            s for s in runner.emittedSqls
            if s.startswith('CREATE TABLE IF NOT EXISTS dtc_freeze_frame')
        ]
        assert len(creates) == 1

    def test_presentTableIsNoOp(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='dtc_freeze_frame'", lambda _s: _ok(stdout='1\n'),
        ))
        m0010._applyDtcFreezeFrameTable(_ctx(runner))
        creates = [s for s in runner.emittedSqls if s.startswith('CREATE TABLE')]
        assert creates == [], f'present table must be a no-op; got {creates}'

    def test_createFailureRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            "TABLE_NAME='dtc_freeze_frame'", lambda _s: _ok(stdout='0\n'),
        ))
        runner.handlers.append((
            'CREATE TABLE IF NOT EXISTS dtc_freeze_frame',
            lambda _s: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='dtc_freeze_frame'):
            m0010._applyDtcFreezeFrameTable(_ctx(runner))

    def test_postProbeMissingRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner()
        # Always absent: pre-check absent -> CREATE -> post-probe still absent.
        runner.handlers.append((
            "TABLE_NAME='dtc_freeze_frame'", lambda _s: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.SchemaProbeError, match='dtc_freeze_frame'):
            m0010._applyDtcFreezeFrameTable(_ctx(runner))


class TestApplyInvokesFreezeFrameSubstep:
    def test_applyEmitsCreateWhenFreezeFrameAbsent(self) -> None:
        """The shared apply() runs the dtc_freeze_frame substep.

        Generic TABLES/STATISTICS/COLUMNS probes report a fully-migrated DB so
        the US-363/371/365 substeps are no-ops; only dtc_freeze_frame is absent,
        so apply() must emit exactly the freeze-frame CREATE.
        """
        runner = FakeRunner()
        # dtc_freeze_frame: absent then present (specific handler wins -- inserted
        # first so it beats the generic information_schema.TABLES handler).
        runner.handlers.append((
            "TABLE_NAME='dtc_freeze_frame'", _freezeFrameAbsentThenPresent(),
        ))
        # Everything else fully migrated -> no other DDL.
        runner.handlers.append(('ck_drive_summary_data_quality', lambda _s: _ok('1\n')))
        runner.handlers.append((
            'ck_drive_statistics_data_quality',
            lambda _s: _ok(
                "data_quality in ('full','sparse','below_threshold',"
                "'attribution_anomaly')\n",
            ),
        ))
        # US-372 invariant CHECK already present -> substep is a no-op.
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
        creates = [
            s for s in runner.emittedSqls
            if s.startswith('CREATE TABLE IF NOT EXISTS dtc_freeze_frame')
        ]
        assert len(creates) == 1, 'apply() must invoke the dtc_freeze_frame substep'
