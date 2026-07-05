################################################################################
# File Name: test_migration_0023_drop_stale_data_source_check.py
# Purpose/Description: Sprint 55 V0.29.9 (US-458 / F-116 / BL-019 A' / A-10 /
#                      TD-055) -- migration tests for v0023: DISCOVER and DROP
#                      the stale live data_source CHECK that US-424 never ALTERed
#                      away.  Discovery-driven (schema-wide via
#                      INFORMATION_SCHEMA.CHECK_CONSTRAINTS on
#                      CHECK_CLAUSE LIKE '%data_source%'), idempotent, with a
#                      zero-survivor post-condition probe.  Forward-only; v0022
#                      untouched.  Hermetic stateful FakeRunner; no SSH, no
#                      MariaDB (bench-only sprint).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-05    | Rex (US-458) | Initial -- v0023 drop stale data_source CHECK.
# ================================================================================
################################################################################

"""TDD tests for the v0023 drop-stale-data_source-CHECK migration (US-458)."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0023_us458_drop_stale_data_source_check as m0023

# ================================================================================
# Stateful FakeRunner -- models the live DB's data_source CHECK set.  Discovery
# returns the CHECKs still present; a DROP removes the named one; the post-probe
# re-discovery therefore naturally reflects the drops.  No SSH, no MariaDB.
# ================================================================================


def _ok(stdout: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


@dataclass
class FakeRunner:
    # (table, constraint) pairs currently present on the "live DB".
    checks: list[tuple[str, str]] = field(default_factory=list)
    # If set, discovery queries fail (info_schema unreachable).
    failDiscovery: bool = False
    # If set, the DROP of this constraint name fails (and it is NOT removed).
    failDrop: str | None = None
    # If True, a DROP returns success but does NOT remove the check -- models
    # the silent-no-op / wrong-session-context class the post-probe must catch.
    dropNoOp: bool = False
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
        if 'CHECK_CONSTRAINTS' in sql:
            if self.failDiscovery:
                return _fail('information_schema unreachable')
            body = ''.join(f'{t}\t{c}\n' for t, c in self.checks)
            return _ok(body)
        if 'DROP CONSTRAINT' in sql:
            name = sql.split('DROP CONSTRAINT', 1)[1].strip().rstrip(';').strip()
            if self.failDrop is not None and name == self.failDrop:
                return _fail(f"Can't DROP {name}: lock wait timeout")
            if not self.dropNoOp:
                self.checks = [(t, c) for (t, c) in self.checks if c != name]
            return _ok('')
        return _ok('')

    @property
    def emittedSqls(self) -> list[str]:
        return [c['input'] for c in self.calls if c['input']]


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _drops(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if 'DROP CONSTRAINT' in s]


def _discoveries(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if 'CHECK_CONSTRAINTS' in s]


# The stale 4-value CHECK Atlas verified on the live DB (BL-019 A'), one per
# Atlas-named table.  Constraint names are auto-generated / unknown in prod, so
# these are stand-ins -- the migration discovers whatever names exist.
_STALE_CHECKS: list[tuple[str, str]] = [
    ('realtime_data', 'realtime_data_chk_1'),
    ('statistics', 'statistics_chk_1'),
    ('connection_log', 'connection_log_chk_1'),
    ('profiles', 'profiles_chk_1'),
    ('calibration_sessions', 'calibration_sessions_chk_1'),
]


# ================================================================================
# Registry + version
# ================================================================================


class TestRegistration:
    def test_versionIs0023(self) -> None:
        assert m0023.VERSION == '0023'

    def test_v0023RegisteredAfterV0022AndSorted(self) -> None:
        # Placement, not the absolute tail: present, tuple sorted, directly
        # after v0022.  (Avoids the brittle `versions[-1] == '0023'` trap that
        # re-breaks on every later migration -- the v0018 lesson.)
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0023' in versions
        assert versions[versions.index('0023') - 1] == '0022'

    def test_v0022NotRedefinedForwardOnly(self) -> None:
        assert m0023.VERSION not in {'0022'}


# ================================================================================
# SQL shape
# ================================================================================


class TestDiscoverySql:
    def test_discoverySelectsTableAndConstraintFromCheckConstraints(self) -> None:
        sql = m0023.discoverDataSourceCheckSql('obd2db')
        assert sql.startswith(
            'SELECT TABLE_NAME, CONSTRAINT_NAME FROM information_schema.CHECK_CONSTRAINTS',
        )

    def test_discoveryFiltersBySchemaAndDataSourceClause(self) -> None:
        sql = m0023.discoverDataSourceCheckSql('obd2db')
        assert "CONSTRAINT_SCHEMA='obd2db'" in sql
        # The LIKE on CHECK_CLAUSE is what isolates the data_source CHECK from
        # every data_quality CHECK (whose clause never contains 'data_source').
        assert "CHECK_CLAUSE LIKE '%data_source%'" in sql


class TestDropSql:
    def test_dropConstraintByDiscoveredName(self) -> None:
        sql = m0023.dropConstraintSql('realtime_data', 'realtime_data_chk_1')
        assert sql == 'ALTER TABLE realtime_data DROP CONSTRAINT realtime_data_chk_1;'


class TestExpectedTables:
    def test_documentsTheFiveAtlasNamedTables(self) -> None:
        # Coverage-intent constant; the drop itself is discovery-driven.
        assert set(m0023.EXPECTED_STALE_CHECK_TABLES) == {
            'realtime_data',
            'statistics',
            'connection_log',
            'profiles',
            'calibration_sessions',
        }

    def test_dataSourceColumnConstant(self) -> None:
        assert m0023.DATA_SOURCE_COLUMN == 'data_source'


# ================================================================================
# apply() behavior -- coverage, ordering, idempotency, failure modes
# ================================================================================


class TestApply:
    def test_dropsEveryDiscoveredCheck(self) -> None:
        runner = FakeRunner(checks=list(_STALE_CHECKS))
        m0023.apply(_ctx(runner))
        drops = _drops(runner)
        assert len(drops) == len(_STALE_CHECKS)
        # Every discovered constraint got a DROP for its own table.
        for table, name in _STALE_CHECKS:
            assert any(
                f'ALTER TABLE {table} DROP CONSTRAINT {name};' == d for d in drops
            ), f'no DROP emitted for {table}.{name}'

    def test_idempotentReplayNoChecksNoDrops(self) -> None:
        """Fresh create_all DB / already-migrated replay: discovery returns 0
        rows -> no DROP -> zero-survivor post-probe passes."""
        runner = FakeRunner(checks=[])
        m0023.apply(_ctx(runner))  # must not raise
        assert _drops(runner) == []
        # Two discovery calls: the pre-drop scan and the post-condition probe.
        assert len(_discoveries(runner)) == 2

    def test_dropsAcrossMultipleTablesAllRemoved(self) -> None:
        runner = FakeRunner(checks=list(_STALE_CHECKS))
        m0023.apply(_ctx(runner))
        # After apply, the modelled live DB has no data_source CHECK left.
        assert runner.checks == []

    def test_dropsPrecedeFinalPostProbe(self) -> None:
        """Every DROP must run before the post-condition re-discovery, else the
        probe could report survivors that were about to be dropped."""
        runner = FakeRunner(checks=list(_STALE_CHECKS))
        m0023.apply(_ctx(runner))
        emitted = runner.emittedSqls
        last_drop = max(i for i, s in enumerate(emitted) if 'DROP CONSTRAINT' in s)
        last_discovery = max(
            i for i, s in enumerate(emitted) if 'CHECK_CONSTRAINTS' in s
        )
        assert last_drop < last_discovery

    def test_reRunsDiscoveryAsPostProbe(self) -> None:
        runner = FakeRunner(checks=list(_STALE_CHECKS))
        m0023.apply(_ctx(runner))
        # Pre-drop discovery + post-drop probe = at least two discovery queries.
        assert len(_discoveries(runner)) == 2

    def test_discoveryFailureRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner(checks=list(_STALE_CHECKS), failDiscovery=True)
        with pytest.raises(asm.SchemaProbeError, match='discovery probe failed'):
            m0023.apply(_ctx(runner))

    def test_dropFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner(
            checks=list(_STALE_CHECKS), failDrop='statistics_chk_1',
        )
        with pytest.raises(asm.MigrationError, match='statistics_chk_1'):
            m0023.apply(_ctx(runner))

    def test_survivingCheckRaisesSchemaProbeError(self) -> None:
        """If a drop is silently skipped (wrong DB context / filtered replica),
        the DROP returns success but the CHECK persists -- the post-probe
        re-discovers the survivor and fails loud rather than recording success
        over the drift."""
        runner = FakeRunner(checks=[('realtime_data', 'ghost_chk')], dropNoOp=True)
        with pytest.raises(asm.SchemaProbeError, match='survive'):
            m0023.apply(_ctx(runner))
