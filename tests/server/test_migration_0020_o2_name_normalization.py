################################################################################
# File Name: test_migration_0020_o2_name_normalization.py
# Purpose/Description: Sprint 55 V0.29.9 (US-454 / D-3 / F-082) -- migration unit
#                      tests for v0020: re-map the one divergent O2
#                      parameter_name label 'O2_BANK1_SENSOR2_V' -> canonical
#                      'O2_B1S2' across every server table carrying a
#                      parameter_name string, with an idempotent WHERE guard and
#                      a zero-survivor post-condition probe.  Forward-only; v0019
#                      untouched.  Hermetic FakeRunner; no SSH, no MariaDB.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-454) | Initial -- v0020 O2 name normalization tests.
# ================================================================================
################################################################################

"""TDD tests for the v0020 O2 sensor name normalization migration (US-454)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0020_us454_o2_name_normalization as m0020

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0018_*)
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
        # Default: UPDATEs succeed; a bare COUNT probe returns 0 survivors.
        stdout = '0\n' if sql.startswith('SELECT COUNT(*)') else ''
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout=stdout, stderr='',
        )

    @property
    def emittedSqls(self) -> list[str]:
        return [c['input'] for c in self.calls if c['input']]


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


def _ctx(runner: FakeRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _updates(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if s.startswith('UPDATE ')]


def _probes(runner: FakeRunner) -> list[str]:
    return [s for s in runner.emittedSqls if s.startswith('SELECT COUNT(*)')]


# ================================================================================
# Registry + version
# ================================================================================


class TestRegistration:
    def test_versionIs0020(self) -> None:
        assert m0020.VERSION == '0020'

    def test_v0020RegisteredAfterV0019AndSorted(self) -> None:
        # Assert placement, not the absolute tail: v0020 is present, the tuple
        # stays sorted, and v0020 directly follows v0019.  (Avoids the brittle
        # `versions[-1] == '0020'` trap that re-breaks on every later migration.)
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0020' in versions
        assert versions[versions.index('0020') - 1] == '0019'

    def test_v0019NotRedefinedForwardOnly(self) -> None:
        assert m0020.VERSION not in {'0019'}


# ================================================================================
# Canonical mapping constants
# ================================================================================


class TestCanonicalMapping:
    def test_oldNameIsTheDivergentLabel(self) -> None:
        assert m0020.OLD_O2_NAME == 'O2_BANK1_SENSOR2_V'

    def test_newNameMatchesRegistryConvention(self) -> None:
        # Canonical == the decoder registry's own obdCommand + the
        # O2_B{bank}S{sensor} convention shared with O2_B1S1.
        assert m0020.NEW_O2_NAME == 'O2_B1S2'

    def test_coversEveryParameterNameTable(self) -> None:
        # Every server table with a parameter_name column must be re-mapped,
        # else a stray O2 row survives the DISTINCT-canonical invariant.
        assert set(m0020.PARAMETER_NAME_TABLES) == {
            'realtime_data',
            'statistics',
            'alert_log',
            'drive_statistics',
            'trend_snapshots',
            'anomaly_log',
        }


# ================================================================================
# Re-map SQL shape
# ================================================================================


class TestRemapSql:
    @pytest.mark.parametrize('table', m0020.PARAMETER_NAME_TABLES)
    def test_updateSetsCanonicalGuardedByVariant(self, table: str) -> None:
        sql = m0020.remapSql(table)
        assert sql.startswith(f'UPDATE {table} SET parameter_name = ')
        assert "'O2_B1S2'" in sql
        # The WHERE guard is what makes the re-map idempotent (a replay
        # matches 0 rows) -- assert it is present.
        assert "WHERE parameter_name = 'O2_BANK1_SENSOR2_V'" in sql

    @pytest.mark.parametrize('table', m0020.PARAMETER_NAME_TABLES)
    def test_postProbeCountsSurvivors(self, table: str) -> None:
        sql = m0020.remainingVariantSql(table)
        assert sql.startswith(f'SELECT COUNT(*) FROM {table}')
        assert "WHERE parameter_name = 'O2_BANK1_SENSOR2_V'" in sql


# ================================================================================
# apply() behavior -- coverage, ordering, idempotency, failure modes
# ================================================================================


class TestApply:
    def test_emitsOneUpdatePerTable(self) -> None:
        runner = FakeRunner()
        m0020.apply(_ctx(runner))
        updates = _updates(runner)
        assert len(updates) == len(m0020.PARAMETER_NAME_TABLES)
        # Every target table got exactly one re-map.
        for table in m0020.PARAMETER_NAME_TABLES:
            assert any(u.startswith(f'UPDATE {table} ') for u in updates), (
                f'no re-map UPDATE emitted for {table}'
            )

    def test_updatesPrecedePostProbes(self) -> None:
        """All re-maps must run before any survivor probe -- else a probe could
        fire on a not-yet-migrated table and spuriously fail."""
        runner = FakeRunner()
        m0020.apply(_ctx(runner))
        emitted = runner.emittedSqls
        last_update = max(i for i, s in enumerate(emitted) if s.startswith('UPDATE '))
        first_probe = min(
            i for i, s in enumerate(emitted) if s.startswith('SELECT COUNT(*)')
        )
        assert last_update < first_probe

    def test_verifiesEveryTable(self) -> None:
        runner = FakeRunner()
        m0020.apply(_ctx(runner))
        assert len(_probes(runner)) == len(m0020.PARAMETER_NAME_TABLES)

    def test_idempotentReplayReRunsGuardedUpdates(self) -> None:
        """A replay on an already-migrated DB (0 variant rows) still runs the
        WHERE-guarded UPDATEs and passes the zero-survivor post-probe."""
        runner = FakeRunner()  # default probe returns '0\n' survivors
        m0020.apply(_ctx(runner))  # must not raise
        assert len(_updates(runner)) == len(m0020.PARAMETER_NAME_TABLES)

    def test_updateFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            ('UPDATE alert_log', lambda _s: _fail('Lock wait timeout')),
        )
        with pytest.raises(asm.MigrationError, match='alert_log'):
            m0020.apply(_ctx(runner))

    def test_survivingVariantRaisesSchemaProbeError(self) -> None:
        """If a re-map silently no-op'd (wrong DB / filtered replica), the
        post-probe finds surviving variant rows and fails loud."""
        runner = FakeRunner()
        runner.handlers.append(
            (
                'SELECT COUNT(*) FROM statistics',
                lambda _s: subprocess.CompletedProcess(
                    args=[], returncode=0, stdout='4\n', stderr='',
                ),
            ),
        )
        with pytest.raises(asm.SchemaProbeError, match='statistics'):
            m0020.apply(_ctx(runner))

    def test_postProbeQueryFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            ('SELECT COUNT(*) FROM realtime_data', lambda _s: _fail('gone away')),
        )
        with pytest.raises(asm.MigrationError, match='realtime_data'):
            m0020.apply(_ctx(runner))

    def test_unparseableProbeRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            (
                'SELECT COUNT(*) FROM anomaly_log',
                lambda _s: subprocess.CompletedProcess(
                    args=[], returncode=0, stdout='NULL-ish garbage\n', stderr='',
                ),
            ),
        )
        with pytest.raises(asm.SchemaProbeError, match='anomaly_log'):
            m0020.apply(_ctx(runner))
