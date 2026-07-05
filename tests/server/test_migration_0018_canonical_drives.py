################################################################################
# File Name: test_migration_0018_canonical_drives.py
# Purpose/Description: Sprint 55 V0.29.9 (US-448 / F-104 spine) -- migration unit
#                      tests for v0018: CREATE the canonical ``drives`` identity
#                      table (server-minted drive_id PK anchored by
#                      UNIQUE(source_device, source_drive_id)), then SUBSUME the
#                      existing drive_summary.id by inserting each value in as the
#                      new drive_id (identity preserved).  Forward-only; v0017
#                      untouched.  Hermetic FakeRunner; no SSH, no MariaDB.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-448) | Initial -- v0018 canonical drives migration tests.
# ================================================================================
################################################################################

"""TDD tests for the v0018 canonical ``drives`` identity migration (US-448)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.db.models import (
    DRIVES_SOURCE_UNIQUE_CONSTRAINT,
    DRIVES_TABLE,
)
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0018_us448_canonical_drives as m0018

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


def _absentThenPresent() -> Callable[[str], subprocess.CompletedProcess[str]]:
    """serverTableExists probe: absent on first call, present after CREATE."""
    state = {'n': 0}

    def handler(_sql: str) -> subprocess.CompletedProcess[str]:
        state['n'] += 1
        return _ok(stdout='0\n' if state['n'] == 1 else '1\n')

    return handler


def _creates(runner: FakeRunner) -> list[str]:
    return [
        s for s in runner.emittedSqls
        if s.startswith('CREATE TABLE IF NOT EXISTS drives')
    ]


def _backfills(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if s.startswith('INSERT INTO drives')]


_DRIVES_PROBE = "TABLE_NAME='drives'"


# ================================================================================
# Registry + version
# ================================================================================


class TestRegistration:
    def test_versionIs0018(self) -> None:
        assert m0018.VERSION == '0018'

    def test_v0018RegisteredAfterV0017AndSorted(self) -> None:
        # De-brittled (US-454): the registry keeps growing, so asserting v0018
        # is the ABSOLUTE tail breaks on every later migration (it silently went
        # red when US-453 appended v0019).  The real invariant is that v0018 is
        # present, the tuple stays sorted, and v0018 directly follows v0017.
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0018' in versions
        assert versions[versions.index('0018') - 1] == '0017'

    def test_v0017NotRedefinedForwardOnly(self) -> None:
        assert m0018.VERSION not in {'0017'}


# ================================================================================
# CREATE drives DDL shape
# ================================================================================


class TestCreateDrivesDdl:
    def test_tableConstantMatchesOrm(self) -> None:
        assert m0018.DRIVES_TABLE == DRIVES_TABLE == 'drives'

    def test_createIsIfNotExists(self) -> None:
        assert m0018.CREATE_DRIVES_DDL.startswith(
            'CREATE TABLE IF NOT EXISTS drives',
        )

    def test_driveIdIsServerMintedAutoincrementPk(self) -> None:
        ddl = m0018.CREATE_DRIVES_DDL
        assert 'drive_id' in ddl
        assert 'AUTO_INCREMENT' in ddl
        assert 'PRIMARY KEY' in ddl

    def test_hasAllContractColumns(self) -> None:
        ddl = m0018.CREATE_DRIVES_DDL
        for col in (
            'drive_id', 'source_device', 'source_drive_id',
            'start_time', 'end_time', 'data_source', 'data_quality',
        ):
            assert col in ddl, f'missing column {col!r}'

    def test_sourceDriveIdIsNullable(self) -> None:
        # The advisory Pi id must be nullable so unmappable legacy drives can
        # exist as honest rows (US-451), not be dropped.
        assert 'source_drive_id INT NULL' in m0018.CREATE_DRIVES_DDL

    def test_naturalKeyUniqueConstraint(self) -> None:
        ddl = m0018.CREATE_DRIVES_DDL
        assert DRIVES_SOURCE_UNIQUE_CONSTRAINT in ddl
        assert 'UNIQUE (source_device, source_drive_id)' in ddl

    def test_dataQualityCheckEnum(self) -> None:
        ddl = m0018.CREATE_DRIVES_DDL
        assert 'ck_drives_data_quality' in ddl
        # Enum matches the model SSOT (drive_summary values it subsumes).
        assert "'full'" in ddl
        assert "'attribution_anomaly'" in ddl
        assert "'foreign_vehicle'" in ddl


# ================================================================================
# SUBSUME drive_summary.id backfill DDL shape
# ================================================================================


class TestSubsumeBackfillDdl:
    def test_insertsExplicitDriveIdFromSummaryId(self) -> None:
        """The heart of the spine: drives.drive_id := drive_summary.id."""
        ddl = m0018.BACKFILL_DRIVES_FROM_SUMMARY_DDL
        assert ddl.startswith('INSERT INTO drives (drive_id')
        assert 'SELECT ds.id' in ddl
        assert 'FROM drive_summary ds' in ddl

    def test_piIdDemotedToAdvisorySourceDriveId(self) -> None:
        ddl = m0018.BACKFILL_DRIVES_FROM_SUMMARY_DDL
        assert 'COALESCE(ds.source_id, ds.drive_id)' in ddl

    def test_idempotentNotInGuard(self) -> None:
        # A replay must insert nothing -- the NOT IN guard makes the subsume
        # idempotent (never renumbers, never duplicates).
        assert 'NOT IN (SELECT drive_id FROM drives)' in (
            m0018.BACKFILL_DRIVES_FROM_SUMMARY_DDL
        )


# ================================================================================
# _applyCreateDrives substep behavior
# ================================================================================


class TestCreateDrivesSubstep:
    def test_absentEmitsCreate(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((_DRIVES_PROBE, _absentThenPresent()))
        m0018._applyCreateDrives(_ctx(runner))
        assert len(_creates(runner)) == 1

    def test_presentSkipsCreate(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((_DRIVES_PROBE, lambda _s: _ok(stdout='1\n')))
        m0018._applyCreateDrives(_ctx(runner))
        assert _creates(runner) == []

    def test_createFailureRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append((_DRIVES_PROBE, lambda _s: _ok(stdout='0\n')))
        runner.handlers.append(
            ('CREATE TABLE IF NOT EXISTS drives', lambda _s: _fail('Lock wait')),
        )
        with pytest.raises(asm.MigrationError, match='drives'):
            m0018._applyCreateDrives(_ctx(runner))

    def test_postProbeMissingRaises(self) -> None:
        runner = FakeRunner()
        # Probe returns absent on BOTH the entry probe and the post-probe ->
        # the CREATE silently no-op'd -> SchemaProbeError.
        runner.handlers.append((_DRIVES_PROBE, lambda _s: _ok(stdout='0\n')))
        with pytest.raises(asm.SchemaProbeError, match='drives'):
            m0018._applyCreateDrives(_ctx(runner))


# ================================================================================
# _applySubsumeDriveSummaryId substep behavior
# ================================================================================


class TestSubsumeSubstep:
    def test_emitsBackfill(self) -> None:
        runner = FakeRunner()
        m0018._applySubsumeDriveSummaryId(_ctx(runner))
        assert len(_backfills(runner)) == 1

    def test_backfillFailureRaises(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            ('INSERT INTO drives', lambda _s: _fail('FK error')),
        )
        with pytest.raises(asm.MigrationError, match='subsume'):
            m0018._applySubsumeDriveSummaryId(_ctx(runner))


# ================================================================================
# apply() wiring + ordering
# ================================================================================


class TestApplyOrdering:
    def test_createBeforeSubsume(self) -> None:
        """drives must exist before the subsume INSERT can target it."""
        runner = FakeRunner()
        runner.handlers.append((_DRIVES_PROBE, _absentThenPresent()))

        m0018.apply(_ctx(runner))
        emitted = runner.emittedSqls
        create_idx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('CREATE TABLE IF NOT EXISTS drives')
        )
        backfill_idx = next(
            i for i, s in enumerate(emitted)
            if s.startswith('INSERT INTO drives')
        )
        assert create_idx < backfill_idx, 'drives must be created before subsume'

    def test_alreadyPresentStillSubsumes(self) -> None:
        """Table present (out-of-band) -> skip CREATE but still subsume."""
        runner = FakeRunner()
        runner.handlers.append((_DRIVES_PROBE, lambda _s: _ok(stdout='1\n')))

        m0018.apply(_ctx(runner))
        assert _creates(runner) == []
        assert len(_backfills(runner)) == 1
