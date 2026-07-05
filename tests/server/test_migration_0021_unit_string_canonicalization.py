################################################################################
# File Name: test_migration_0021_unit_string_canonicalization.py
# Purpose/Description: Sprint 55 V0.29.9 (US-455 / D-4 / F-082) -- migration unit
#                      tests for v0021: re-map the divergent abbreviated unit
#                      strings on realtime_data.unit ('V'->'volt',
#                      'kPa'->'kilopascal', 's'->'second') to the python-obd
#                      native canonical form, with an idempotent WHERE guard and
#                      a zero-survivor post-condition probe.  Forward-only; v0020
#                      untouched.  Hermetic FakeRunner; no SSH, no MariaDB.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-04    | Rex (US-455) | Initial -- v0021 unit-string canonicalization.
# ================================================================================
################################################################################

"""TDD tests for the v0021 unit-string canonicalization migration (US-455)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations import ALL_MIGRATIONS
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0021_us455_unit_string_canonicalization as m0021

# ================================================================================
# FakeRunner -- scripted subprocess stand-in (mirrors test_migration_0020_*)
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
    def test_versionIs0021(self) -> None:
        assert m0021.VERSION == '0021'

    def test_v0021RegisteredAfterV0020AndSorted(self) -> None:
        # Assert placement, not the absolute tail: v0021 is present, the tuple
        # stays sorted, and v0021 directly follows v0020.  (Avoids the brittle
        # `versions[-1] == '0021'` trap that re-breaks on every later migration.)
        versions = [m.version for m in ALL_MIGRATIONS]
        assert versions == sorted(versions)
        assert '0021' in versions
        assert versions[versions.index('0021') - 1] == '0020'

    def test_v0020NotRedefinedForwardOnly(self) -> None:
        assert m0021.VERSION not in {'0020'}


# ================================================================================
# Canonical mapping constants
# ================================================================================


class TestCanonicalMapping:
    def test_targetsRealtimeDataUnitColumn(self) -> None:
        # realtime_data is the only table carrying the Pi-emitted physical-unit
        # string (drive_derived_signals' *_unit columns are a separate,
        # server-computed path and out of scope).
        assert m0021.UNIT_TABLE == 'realtime_data'

    def test_remapIsAbbreviationToNative(self) -> None:
        # Grounded in the decoder test fixtures, which feed the python-obd NATIVE
        # unit as the decoder input ('volt'/'kilopascal'/'second').
        assert m0021.UNIT_REMAP == {
            'V': 'volt',
            'kPa': 'kilopascal',
            's': 'second',
        }

    def test_dtcCountNotReMapped(self) -> None:
        # DTC 'count' has no native pint unit and no colliding twin -> untouched.
        assert 'count' not in m0021.UNIT_REMAP
        assert 'count' not in m0021.UNIT_REMAP.values()


# ================================================================================
# Re-map SQL shape
# ================================================================================


class TestRemapSql:
    @pytest.mark.parametrize(('old', 'new'), list(m0021.UNIT_REMAP.items()))
    def test_updateSetsCanonicalGuardedByAbbreviation(self, old: str, new: str) -> None:
        sql = m0021.remapSql(old, new)
        assert sql.startswith(f'UPDATE {m0021.UNIT_TABLE} SET unit = ')
        assert f"unit = '{new}'" in sql
        # The WHERE guard is what makes the re-map idempotent (a replay
        # matches 0 rows) -- assert it is present.
        assert f"WHERE unit = '{old}'" in sql

    @pytest.mark.parametrize('old', list(m0021.UNIT_REMAP))
    def test_postProbeCountsSurvivors(self, old: str) -> None:
        sql = m0021.remainingVariantSql(old)
        assert sql.startswith(f'SELECT COUNT(*) FROM {m0021.UNIT_TABLE}')
        assert f"WHERE unit = '{old}'" in sql


# ================================================================================
# apply() behavior -- coverage, ordering, idempotency, failure modes
# ================================================================================


class TestApply:
    def test_emitsOneUpdatePerMapping(self) -> None:
        runner = FakeRunner()
        m0021.apply(_ctx(runner))
        updates = _updates(runner)
        assert len(updates) == len(m0021.UNIT_REMAP)
        # Every abbreviation got exactly one re-map to its canonical form.
        for old, new in m0021.UNIT_REMAP.items():
            assert any(
                f"unit = '{new}'" in u and f"WHERE unit = '{old}'" in u
                for u in updates
            ), f'no re-map UPDATE emitted for {old!r} -> {new!r}'

    def test_updatesPrecedePostProbes(self) -> None:
        """All re-maps must run before any survivor probe -- else a probe could
        fire on a not-yet-migrated value and spuriously fail."""
        runner = FakeRunner()
        m0021.apply(_ctx(runner))
        emitted = runner.emittedSqls
        last_update = max(i for i, s in enumerate(emitted) if s.startswith('UPDATE '))
        first_probe = min(
            i for i, s in enumerate(emitted) if s.startswith('SELECT COUNT(*)')
        )
        assert last_update < first_probe

    def test_verifiesEveryMapping(self) -> None:
        runner = FakeRunner()
        m0021.apply(_ctx(runner))
        assert len(_probes(runner)) == len(m0021.UNIT_REMAP)

    def test_idempotentReplayReRunsGuardedUpdates(self) -> None:
        """A replay on an already-migrated DB (0 abbreviation rows) still runs the
        WHERE-guarded UPDATEs and passes the zero-survivor post-probe."""
        runner = FakeRunner()  # default probe returns '0\n' survivors
        m0021.apply(_ctx(runner))  # must not raise
        assert len(_updates(runner)) == len(m0021.UNIT_REMAP)

    def test_updateFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            ("SET unit = 'volt'", lambda _s: _fail('Lock wait timeout')),
        )
        with pytest.raises(asm.MigrationError, match="'V'"):
            m0021.apply(_ctx(runner))

    def test_survivingVariantRaisesSchemaProbeError(self) -> None:
        """If a re-map silently no-op'd (wrong DB / filtered replica), the
        post-probe finds surviving abbreviation rows and fails loud."""
        runner = FakeRunner()
        runner.handlers.append(
            (
                "SELECT COUNT(*) FROM realtime_data WHERE unit = 'kPa'",
                lambda _s: subprocess.CompletedProcess(
                    args=[], returncode=0, stdout='4\n', stderr='',
                ),
            ),
        )
        with pytest.raises(asm.SchemaProbeError, match="'kPa'"):
            m0021.apply(_ctx(runner))

    def test_postProbeQueryFailureRaisesMigrationError(self) -> None:
        runner = FakeRunner()
        runner.handlers.append(
            (
                "SELECT COUNT(*) FROM realtime_data WHERE unit = 's'",
                lambda _s: _fail('gone away'),
            ),
        )
        with pytest.raises(asm.MigrationError, match="'s'"):
            m0021.apply(_ctx(runner))

    def test_unparseableProbeRaisesSchemaProbeError(self) -> None:
        runner = FakeRunner()
        # Only abbreviations are probed; target the 'V' abbreviation probe.
        runner.handlers.append(
            (
                "SELECT COUNT(*) FROM realtime_data WHERE unit = 'V'",
                lambda _s: subprocess.CompletedProcess(
                    args=[], returncode=0, stdout='NULL-ish garbage\n', stderr='',
                ),
            ),
        )
        with pytest.raises(asm.SchemaProbeError, match="'V'"):
            m0021.apply(_ctx(runner))
