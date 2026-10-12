################################################################################
# File Name: test_migration_preflight_fk_topology.py
# Purpose/Description: US-462 (F-104 / A-10) -- applied-schema FK/CHECK topology
#                      preflight.  A-10 ORM-vs-live-DB drift has now shipped 3x
#                      (BL-018/019/020): the ORM/migration declares a
#                      drive-identity FK the deployed MariaDB never got.  This
#                      guard asserts the APPLIED FK topology via
#                      information_schema (NEVER create_all / ORM-metadata --
#                      the US-459 theater trap Atlas flagged) and fails the
#                      deploy fast, naming table + column + expected FK target,
#                      instead of surfacing mid-migration.
#
#                      Two layers, mirroring US-459
#                      (tests/server/test_data_source_applied_schema_accepts_foreign.py):
#                        (1) HERMETIC verdict tests (always run): a stateful fake
#                            runner models the applied KEY_COLUMN_USAGE topology
#                            and proves the guard goes RED on a missing expected
#                            drive-identity FK, GREEN when all present, and LOUD
#                            (not a false pass) when information_schema is
#                            unreachable.
#                        (2) The LIVE preflight is WIRED into
#                            scripts/apply_server_migrations.runRegistry BEFORE
#                            the migration set (see TestWiredPreflight): it
#                            fails the deploy on drift, gates the expected set by
#                            the applied-migration ledger so a still-pending
#                            migration's own output FK is not required yet (no
#                            deadlock on the BL-020 resume-deploy), and SKIPS
#                            HONESTLY when MariaDB is unreachable.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (US-462) | Initial -- applied-schema FK topology preflight.
# ================================================================================
################################################################################

"""US-462 / F-104 -- the APPLIED schema carries the drive-identity FK topology.

Atlas Q3 ruling: this preflight must assert the **applied / deployed** schema
(``information_schema.KEY_COLUMN_USAGE``) -- **never** ``create_all`` /
ORM-metadata.  The ORM and the migration already agree on the FK; a
metadata-only compare would be GREEN even while the live DB lacks the FK -- the
exact A-10 drift that shipped 3x (BL-018/019/020).

The verdict logic (:func:`preflight.assertDriveIdentityFks`) is pure and always
runs here.  The wired path (:func:`preflight.assertAppliedMigrationFkTopology`,
called from :func:`scripts.apply_server_migrations.runRegistry` before the
migration set) gates the expected FK set by the applied-migration ledger so the
BL-020 resume-deploy (v0022 still pending) is not deadlocked, and skips honestly
when MariaDB is unreachable.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS, MigrationRunner, RunnerContext
from src.server.migrations import versions as _versions_pkg
from src.server.migrations.preflight import (
    DRIVE_IDENTITY_FKS,
    PreflightError,
    assertAppliedMigrationFkTopology,
    assertDriveIdentityFks,
    findMissingDriveIdentityFks,
)
from src.server.migrations.versions import v0022_us451_drive_identity_collapse as m0022

# ================================================================================
# Response helpers
# ================================================================================


def _ok(stdout: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


# ================================================================================
# Stateful fake runner -- models the APPLIED KEY_COLUMN_USAGE topology + ledger
# ================================================================================


@dataclass
class FakeFkSchemaRunner:
    """Answer information_schema probes from a modeled applied schema.

    * ``presentFks`` -- set of ``(table, referencedTable)`` pairs the modeled
      applied schema still carries on ``summary_id`` (mirrors what the real
      ``_fkNameReferencing`` KEY_COLUMN_USAGE query would find).
    * ``appliedVersions`` -- the ``schema_migrations`` ledger (SELECT version).
    * ``reachable`` -- when False, the ``SELECT 1`` reachability probe fails so
      the wired guard skips honestly (the Windows bench case).
    * ``failLedger`` -- when True, the ledger read fails loud.
    """

    presentFks: set[tuple[str, str]] = field(default_factory=set)
    appliedVersions: list[str] = field(default_factory=list)
    reachable: bool = True
    failLedger: bool = False
    calls: list[str] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- subprocess API parity
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        sql = input or ''
        self.calls.append(sql)
        if 'KEY_COLUMN_USAGE' in sql:
            table = _extract(sql, r"AND TABLE_NAME='([^']+)'")
            ref = _extract(sql, r"REFERENCED_TABLE_NAME='([^']+)'")
            if (table, ref) in self.presentFks:
                return _ok(f'fk_{table}_{ref}\n')
            return _ok('')
        if 'SELECT version' in sql:
            if self.failLedger:
                return _fail('schema_migrations unreadable')
            return _ok(''.join(f'{v}\n' for v in self.appliedVersions))
        if sql.strip().startswith('SELECT 1'):
            return _ok('1\n') if self.reachable else _fail('unreachable')
        # CREATE TABLE IF NOT EXISTS schema_migrations (ensureTracking) + misc.
        return _ok('')


def _extract(sql: str, pattern: str) -> str:
    match = re.search(pattern, sql)
    return match.group(1) if match else ''


def _ctx(runner: FakeFkSchemaRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _allPresent() -> set[tuple[str, str]]:
    """The (table, drives) pairs for every expected drive-identity FK."""
    return {(fk.table, fk.refTable) for fk in DRIVE_IDENTITY_FKS}


# ================================================================================
# Expected-FK registry -- define-once against v0022's own constants
# ================================================================================


class TestExpectedForeignKeys:
    def test_registryNonEmpty(self) -> None:
        assert len(DRIVE_IDENTITY_FKS) >= 2

    def test_coversTheTwoCollapseTables(self) -> None:
        tables = {fk.table for fk in DRIVE_IDENTITY_FKS}
        assert m0022.DRIVE_STATISTICS_TABLE in tables
        assert m0022.DRIVE_DERIVED_SIGNALS_TABLE in tables

    def test_allTargetDrivesDriveId(self) -> None:
        # The canonical identity is drives.drive_id (US-448 collapse target).
        for fk in DRIVE_IDENTITY_FKS:
            assert fk.refColumn == 'drive_id'
            assert fk.refTable == m0022.DRIVES_TABLE

    def test_sourceVersionMatchesTheCreatingMigration(self) -> None:
        # v0022 is the migration that establishes these FKs -- the ledger gate
        # keys off this so a pending v0022 does not deadlock the BL-020 deploy.
        for fk in DRIVE_IDENTITY_FKS:
            assert fk.sourceVersion == m0022.VERSION

    def test_definedFromV0022Constants(self) -> None:
        # Define-once: the expected FK names ARE v0022's ForeignKey names, so a
        # future rename trips here instead of silently drifting the guard.
        byTable = {fk.table: fk for fk in DRIVE_IDENTITY_FKS}
        assert (
            byTable[m0022.DRIVE_STATISTICS_TABLE].constraintName
            == m0022.DRIVE_STATISTICS_FK_NAME
        )
        assert (
            byTable[m0022.DRIVE_DERIVED_SIGNALS_TABLE].constraintName
            == m0022.DRIVE_DERIVED_SIGNALS_FK_NAME
        )


# ================================================================================
# Verdict logic (hermetic, always runs) -- proves the alarm fires
# ================================================================================


class TestVerdictLogic:
    def test_greenWhenAllExpectedFksPresent(self) -> None:
        ctx = _ctx(FakeFkSchemaRunner(presentFks=_allPresent()))
        assertDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS)  # must not raise
        assert findMissingDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS) == []

    def test_redWhenAnExpectedFkIsMissing(self) -> None:
        # drive_statistics FK absent (the BL-020 state-3 drift shape).
        present = _allPresent() - {
            (m0022.DRIVE_STATISTICS_TABLE, m0022.DRIVES_TABLE),
        }
        ctx = _ctx(FakeFkSchemaRunner(presentFks=present))
        with pytest.raises(PreflightError) as excinfo:
            assertDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS)
        msg = str(excinfo.value)
        # Message names table + column + expected FK target (validationCriteria).
        assert m0022.DRIVE_STATISTICS_TABLE in msg
        assert 'summary_id' in msg
        assert f'{m0022.DRIVES_TABLE}.drive_id' in msg

    def test_redListsEveryMissingFkNotJustTheFirst(self) -> None:
        ctx = _ctx(FakeFkSchemaRunner(presentFks=set()))  # nothing present
        with pytest.raises(PreflightError) as excinfo:
            assertDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS)
        msg = str(excinfo.value)
        for fk in DRIVE_IDENTITY_FKS:
            assert fk.table in msg

    def test_findMissingReturnsTheDelta(self) -> None:
        present = _allPresent() - {
            (m0022.DRIVE_DERIVED_SIGNALS_TABLE, m0022.DRIVES_TABLE),
        }
        ctx = _ctx(FakeFkSchemaRunner(presentFks=present))
        missing = findMissingDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS)
        assert [fk.table for fk in missing] == [m0022.DRIVE_DERIVED_SIGNALS_TABLE]

    def test_raisesWhenProbeUnreachable(self) -> None:
        # A failed information_schema probe is loud (SchemaProbeError from the
        # reused v0022 probe), never a false GREEN.
        def _boom(argv, *, input=None, timeout=None):  # noqa: A002
            if input and 'KEY_COLUMN_USAGE' in input:
                return _fail('information_schema unreachable')
            return _ok('')

        ctx = RunnerContext(
            addrs=asm.HostAddresses(serverHost='h', serverUser='u'),
            creds=asm.ServerCreds(dbUser='u', dbPassword='p', dbName='obd2db'),
            runner=_boom,
        )
        with pytest.raises(asm.SchemaProbeError):
            assertDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS)

    def test_probeUsesKeyColumnUsageNotCreateAll(self) -> None:
        # Assert the APPLIED schema -- the probe issues an information_schema
        # KEY_COLUMN_USAGE query, never inspects ORM metadata.
        ctx = _ctx(FakeFkSchemaRunner(presentFks=_allPresent()))
        findMissingDriveIdentityFks(ctx, DRIVE_IDENTITY_FKS)
        assert any('KEY_COLUMN_USAGE' in s for s in ctx.runner.calls)


# ================================================================================
# Wired preflight -- ledger gate + honest skip (deploy behaviour)
# ================================================================================


class TestWiredPreflight:
    def _reg(self) -> MigrationRunner:
        return MigrationRunner(ALL_MIGRATIONS)

    def test_pendingMigrationFksNotYetRequired_noDeadlock(self) -> None:
        # BL-020 resume shape: schema_migrations=0021 (v0022 PENDING), the
        # drive-identity FKs are absent -- but v0022 has not run yet, so the
        # preflight must NOT block (else the reconciling deploy deadlocks).
        runner = FakeFkSchemaRunner(
            presentFks=set(),  # FKs not applied yet
            appliedVersions=['0018', '0019', '0020', '0021'],
        )
        assertAppliedMigrationFkTopology(_ctx(runner), self._reg())  # no raise

    def test_appliedMigrationFkMissing_failsFast(self) -> None:
        # Regression drift: v0022 IS recorded applied, yet its promised FK
        # vanished from the applied schema -> fail the deploy fast.
        runner = FakeFkSchemaRunner(
            presentFks=set(),
            appliedVersions=['0018', '0019', '0020', '0021', '0022'],
        )
        with pytest.raises(PreflightError, match='summary_id'):
            assertAppliedMigrationFkTopology(_ctx(runner), self._reg())

    def test_fullyReconciled_passes(self) -> None:
        runner = FakeFkSchemaRunner(
            presentFks=_allPresent(),
            appliedVersions=['0018', '0019', '0020', '0021', '0022'],
        )
        assertAppliedMigrationFkTopology(_ctx(runner), self._reg())  # no raise

    def test_unreachableMariaDb_skipsHonestly(self, capsys) -> None:
        # No live MariaDB (bench): the guard must SKIP, never report a false
        # pass -- and never hard-fail before runAll gets its own chance.
        runner = FakeFkSchemaRunner(
            presentFks=set(),
            appliedVersions=['0022'],
            reachable=False,
        )
        assertAppliedMigrationFkTopology(_ctx(runner), self._reg())  # no raise
        out = capsys.readouterr().out.lower()
        assert 'skip' in out

    def test_wiredIntoRunRegistryBeforeRunAll(self, monkeypatch, tmp_path) -> None:
        # The guard is CALLED by runRegistry BEFORE the migration set runs.
        addressesPath = tmp_path / 'addresses.sh'
        addressesPath.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
        monkeypatch.setattr(asm, 'loadAddresses', lambda p, runner=None: _ctx(
            FakeFkSchemaRunner()).addrs)
        monkeypatch.setattr(asm, 'loadServerCreds', lambda a, runner=None: _ctx(
            FakeFkSchemaRunner()).creds)

        order: list[str] = []
        import src.server.migrations.preflight as pf

        def _spyPreflight(ctx, reg, **kw):
            order.append('preflight')

        monkeypatch.setattr(pf, 'assertAppliedMigrationFkTopology', _spyPreflight)
        monkeypatch.setattr(
            MigrationRunner, 'runAll',
            lambda self, ctx: order.append('runAll') or __import__(
                'src.server.migrations.runner', fromlist=['RunReport'],
            ).RunReport(),
        )
        asm.runRegistry(addressesPath, runner=FakeFkSchemaRunner())
        assert order == ['preflight', 'runAll'], (
            'preflight must run BEFORE the migration set'
        )


# ================================================================================
# Design guard -- assert the APPLIED schema, never create_all / ORM metadata
# ================================================================================


def test_preflightModuleNeverUsesCreateAllOrOrmMetadata() -> None:
    """[ATLAS Q3] the guard probes the DEPLOYED schema via information_schema,
    it never falls back to ``create_all`` / ORM-metadata (the US-459 theater
    trap).  Pinned by a self-scan so a future "simplification" fails here.
    """
    source = Path(_versions_pkg.__file__).resolve().parents[1] / 'preflight.py'
    text = source.read_text(encoding='utf-8')
    # Forbid the create_all INVOCATION (call form) -- prose may mention the name
    # while documenting that the guard deliberately avoids it.
    assert 'create_all(' not in text
    assert '.metadata' not in text
    # ...and prove it positively reads the applied schema.
    assert 'KEY_COLUMN_USAGE' in text or '_fkNameReferencing' in text
