################################################################################
# File Name: test_migration_0010_us371_drive_statistics_rename.py
# Purpose/Description: Sprint 43 V0.28.0 (US-371 / F-076) -- migration unit tests
#                      for the v0010 substep that renames the misleading
#                      drive_id column on drive_statistics (which actually holds
#                      a drive_summary.id FK, NOT a Pi-assigned drive_id) to
#                      summary_id.  The rename is COMPLETE, not additive: no
#                      deprecated alias survives.  Verifies the RENAME DDL shape,
#                      DDL/ORM parity, the INFORMATION_SCHEMA-probe idempotency
#                      (pre-rename production state emits the RENAME; a fresh
#                      create_all DB / prior run is a no-op), and post-condition
#                      probing.  Mirrors test_migration_0010's FakeRunner shape;
#                      hermetic, no SSH, no MariaDB.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-371) | Initial -- F-076 drive_statistics drive_id ->
#               |              | summary_id rename substep tests.
# ================================================================================
################################################################################

"""TDD tests for the v0010 US-371 drive_statistics drive_id -> summary_id rename."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import DriveStatistic
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import (
    v0010_us363_attribution_anomaly_data_quality as m0010,
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


# drive_statistics column sets (newline-separated, as probeServerColumns parses).
_DS_COLS_PRE_RENAME = (
    'drive_id\nparameter_name\nmin_value\nmax_value\navg_value\nstd_dev\n'
    'outlier_min\noutlier_max\nsample_count\ndata_quality\ncomputed_at\n'
)
_DS_COLS_POST_RENAME = (
    'summary_id\nparameter_name\nmin_value\nmax_value\navg_value\nstd_dev\n'
    'outlier_min\noutlier_max\nsample_count\ndata_quality\ncomputed_at\n'
)


def _scriptDriveStatsColumnProbe(
    runner: FakeRunner, *, alreadyRenamed: bool,
) -> None:
    """Script the drive_statistics column probe used by the rename substep.

    ``alreadyRenamed`` False  -> pre-rename column set first, post-rename after
    the ALTER (the success path).  True -> post-rename set on every probe (the
    idempotent no-op path).
    """
    # Table-exists probe -> present.
    runner.handlers.append((
        'information_schema.TABLES',
        lambda _sql: _ok(stdout='1\n'),
    ))

    columnCalls = {'n': 0}

    def columnProbe(sql: str) -> subprocess.CompletedProcess[str]:
        # Only the drive_statistics column probe is relevant here.
        if "TABLE_NAME='drive_statistics'" not in sql:
            return _ok(stdout='')
        columnCalls['n'] += 1
        if alreadyRenamed:
            return _ok(stdout=_DS_COLS_POST_RENAME)
        return _ok(
            stdout=_DS_COLS_PRE_RENAME if columnCalls['n'] == 1
            else _DS_COLS_POST_RENAME,
        )

    runner.handlers.append(('information_schema.COLUMNS', columnProbe))


# ================================================================================
# RENAME DDL shape + module exports
# ================================================================================


class TestRenameDdl:
    def test_oldAndNewColumnNameConstants(self) -> None:
        assert m0010.DRIVE_STATISTICS_OLD_DRIVE_ID_COLUMN == 'drive_id'
        assert m0010.DRIVE_STATISTICS_SUMMARY_ID_COLUMN == 'summary_id'

    def test_renameDdlIsRenameNotDropOrAdd(self) -> None:
        ddl = m0010.RENAME_DRIVE_STATISTICS_COLUMN_DDL
        assert ddl.startswith('ALTER TABLE drive_statistics')
        assert 'RENAME COLUMN drive_id TO summary_id' in ddl
        assert 'DROP' not in ddl.upper()
        assert 'ADD COLUMN' not in ddl.upper()

    def test_renameDdlInExports(self) -> None:
        assert 'RENAME_DRIVE_STATISTICS_COLUMN_DDL' in m0010.__all__


# ================================================================================
# ORM parity -- the column is summary_id now, with no drive_id alias
# ================================================================================


class TestDriveStatisticOrmRenamed:
    def test_summaryIdColumnExists(self) -> None:
        assert 'summary_id' in DriveStatistic.__table__.columns

    def test_driveIdColumnGone(self) -> None:
        # Complete rename, not additive: no deprecated alias survives.
        assert 'drive_id' not in DriveStatistic.__table__.columns

    def test_summaryIdAttributeAccessible(self) -> None:
        assert hasattr(DriveStatistic, 'summary_id')
        assert not hasattr(DriveStatistic, 'drive_id')

    def test_summaryIdIsPrimaryKey(self) -> None:
        assert DriveStatistic.__table__.columns['summary_id'].primary_key

    def test_summaryIdKeepsForeignKeyToDriveSummary(self) -> None:
        col = DriveStatistic.__table__.columns['summary_id']
        targets = {fk.target_fullname for fk in col.foreign_keys}
        assert 'drive_summary.id' in targets


# ================================================================================
# apply substep -- pre-rename production state emits the RENAME
# ================================================================================


class TestApplyRenameSubstep:
    def test_preRenameStateEmitsRename(self) -> None:
        runner = FakeRunner()
        _scriptDriveStatsColumnProbe(runner, alreadyRenamed=False)
        m0010._applyDriveStatisticsSummaryIdRename(_ctx(runner))
        renames = [
            s for s in runner.emittedSqls
            if 'RENAME COLUMN drive_id TO summary_id' in s
        ]
        assert len(renames) == 1

    def test_alreadyRenamedIsNoOp(self) -> None:
        runner = FakeRunner()
        _scriptDriveStatsColumnProbe(runner, alreadyRenamed=True)
        m0010._applyDriveStatisticsSummaryIdRename(_ctx(runner))
        alters = [s for s in runner.emittedSqls if s.startswith('ALTER TABLE')]
        assert alters == [], f'fresh-create_all / re-run must not ALTER; got {alters}'

    def test_tableMissingRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='0\n'),
        ))
        with pytest.raises(asm.MigrationError, match='drive_statistics'):
            m0010._applyDriveStatisticsSummaryIdRename(_ctx(runner))

    def test_renameFailureRaises(self) -> None:
        runner = FakeRunner()
        _scriptDriveStatsColumnProbe(runner, alreadyRenamed=False)
        runner.handlers.insert(0, (
            'RENAME COLUMN drive_id TO summary_id',
            lambda _sql: _fail('Lock wait timeout'),
        ))
        with pytest.raises(asm.MigrationError, match='summary_id'):
            m0010._applyDriveStatisticsSummaryIdRename(_ctx(runner))

    def test_postProbeMissingSummaryIdRaises(self) -> None:
        runner = FakeRunner()
        # Both column probes return the pre-rename set (drive_id never becomes
        # summary_id), so the post-condition probe trips.
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))
        runner.handlers.append((
            'information_schema.COLUMNS',
            lambda _sql: _ok(stdout=_DS_COLS_PRE_RENAME),
        ))
        with pytest.raises(asm.SchemaProbeError, match='summary_id'):
            m0010._applyDriveStatisticsSummaryIdRename(_ctx(runner))


# ================================================================================
# apply() wires the rename substep in
# ================================================================================


class TestApplyIncludesRename:
    def test_applyEmitsRenameOnPreRenameDb(self) -> None:
        runner = FakeRunner()
        # US-363 drive_summary path: column/CHECK/index already present (no-op).
        runner.handlers.append((
            'ck_drive_summary_data_quality',
            lambda _sql: _ok(stdout='1\n'),
        ))
        runner.handlers.append((
            'ck_drive_statistics_data_quality',
            lambda _sql: _ok(
                stdout="data_quality in ('full','sparse','below_threshold',"
                "'attribution_anomaly')\n",
            ),
        ))
        runner.handlers.append((
            'information_schema.STATISTICS',
            lambda _sql: _ok(stdout='1\n'),
        ))
        # US-372 invariant CHECK already present -> substep is a no-op.
        runner.handlers.append((
            'chk_drive_id_source_id',
            lambda _sql: _ok(stdout='1\n'),
        ))

        # Column probe: drive_summary already migrated; drive_statistics still
        # has drive_id (pre-rename), then summary_id post-ALTER.
        dsCalls = {'n': 0}

        def columnProbe(sql: str) -> subprocess.CompletedProcess[str]:
            if "TABLE_NAME='drive_statistics'" in sql:
                dsCalls['n'] += 1
                return _ok(
                    stdout=_DS_COLS_PRE_RENAME if dsCalls['n'] == 1
                    else _DS_COLS_POST_RENAME,
                )
            if "TABLE_NAME='vehicle_info'" in sql:
                # US-365 vehicle_info ECU lineage already present -> no-op.
                return _ok(
                    stdout='ecu_signature\ncal_signature\n'
                    'ecu_install_timestamp_utc\necu_removal_timestamp_utc\n'
                    'notes\necu_active_marker\n',
                )
            # drive_summary already has data_quality.
            return _ok(stdout='data_quality\n')

        runner.handlers.append(('information_schema.COLUMNS', columnProbe))
        runner.handlers.append((
            'information_schema.TABLES',
            lambda _sql: _ok(stdout='1\n'),
        ))

        m0010.apply(_ctx(runner))
        assert any(
            'RENAME COLUMN drive_id TO summary_id' in s
            for s in runner.emittedSqls
        )
