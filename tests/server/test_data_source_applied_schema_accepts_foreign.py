################################################################################
# File Name: test_data_source_applied_schema_accepts_foreign.py
# Purpose/Description: US-459 (F-116 / A-10) -- applied-schema guard that the
#                      DEPLOYED server DB accepts data_source='foreign'.  US-424
#                      widened the Pi + server Python enum tuples but never
#                      ALTERed the live obd2db, so a stale 4-value data_source
#                      CHECK (no 'foreign') survived on the deployed DB and
#                      rejected synced foreign-tagged rows (the drive-33
#                      landmine).  US-458/v0023 drops it.  This test asserts the
#                      APPLIED schema -- via the v0023 information_schema probe --
#                      NOT the Python enum tuples (which are already equal and
#                      would ship GREEN over the broken live DB: the exact
#                      mocked-green / IRL-miss that shipped this drift, Atlas
#                      CRITICAL).  The live probe is a deploy-time gate (skipped
#                      in-loop, no MariaDB on the bench); the hermetic verdict
#                      tests prove the probe goes RED on a surviving CHECK.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-05    | Rex (US-459) | Initial -- applied-schema accepts-'foreign' guard.
# ================================================================================
################################################################################

"""US-459 / F-116 -- the DEPLOYED schema accepts ``data_source='foreign'``.

Atlas CRITICAL ruling: this guard must assert the **applied / deployed** schema
(``information_schema`` shows no rejecting ``data_source`` CHECK, or an
insert-and-rollback probe per table) -- **never** a Python enum-tuple compare.
The Pi and server tuples are already pinned equal
(``tests/pi/data/test_data_source_foreign_marker.py``); a tuple compare would
therefore be GREEN even while the live DB rejects ``'foreign'`` -- which is the
exact drift that shipped (US-424 changed the enum, never ALTERed obd2db).

Two layers:

* **Live probe (deploy gate).**  ``TestAppliedSchemaLive`` runs the v0023
  ``information_schema.CHECK_CONSTRAINTS`` discovery against the real server and
  asserts zero surviving ``data_source`` CHECKs.  It is SKIPPED in-loop (no
  MariaDB on the Windows bench) and only runs when opted in
  (``OBD2_APPLIED_SCHEMA_TEST=1``) against chi-srv-01 after US-458 deploys --
  GREEN post-drop, RED if any stale/new rejecting CHECK survives.  A skip is
  honest here: it never reports green *over* a broken DB.

* **Verdict logic (hermetic, always runs).**  ``TestProbeVerdictLogic`` feeds a
  stateful fake runner that models the applied schema's CHECK set and proves the
  probe FAILS RED on a modeled surviving CHECK and passes on none.  These test
  the alarm, not the live DB, so the deploy gate cannot silently pass.

The probe reuses v0023's own ``discoverDataSourceCheckSql`` so "a ``data_source``
CHECK" has a single definition shared by the migration and this guard.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts import apply_server_migrations as asm
from src.server.migrations.runner import RunnerContext
from src.server.migrations.versions import v0023_us458_drop_stale_data_source_check as m0023

# Opt-in env flag for the live deploy-time probe.  Unset in-loop / CI so the
# guard never attempts SSH + mysql against a server it cannot reach; the PM /
# QA sets it when running against chi-srv-01 after US-458 deploys.
_OPT_IN_ENV: str = 'OBD2_APPLIED_SCHEMA_TEST'


# ================================================================================
# The applied-schema probe (reuses v0023's discovery SQL -- define-once)
# ================================================================================


def _probeAppliedDataSourceChecks(ctx: RunnerContext) -> list[tuple[str, str]]:
    """Return ``[(table, constraint), ...]`` for every applied data_source CHECK.

    Runs the same ``information_schema.CHECK_CONSTRAINTS`` query v0023 uses to
    verify its own drop, so the migration and this guard agree on what "a
    ``data_source`` CHECK" is.  An empty list means the deployed schema carries
    no rejecting CHECK -> it accepts ``data_source='foreign'``.
    """
    sql = m0023.discoverDataSourceCheckSql(ctx.creds.dbName)
    res = asm._runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise asm.SchemaProbeError(
            'applied-schema data_source CHECK probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    checks: list[tuple[str, str]] = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            checks.append((parts[0], parts[1]))
    return checks


def assertAppliedSchemaAcceptsForeign(ctx: RunnerContext) -> None:
    """Assert the APPLIED schema has no rejecting ``data_source`` CHECK.

    GREEN when the deployed schema accepts ``data_source='foreign'`` on every
    table (US-458/v0023 dropped the stale CHECK); RED (``AssertionError``) if a
    stale or newly re-introduced rejecting CHECK survives on any table.
    """
    survivors = _probeAppliedDataSourceChecks(ctx)
    if survivors:
        rendered = ', '.join(f'{t}.{c}' for t, c in survivors)
        raise AssertionError(
            "applied schema REJECTS data_source='foreign': a rejecting "
            f'data_source CHECK still survives ({rendered}). US-458/v0023 must '
            'drop it -- this is the F-116 drive-33 sync landmine.',
        )


# ================================================================================
# Hermetic stateful fake runner -- models the applied schema's CHECK set
# ================================================================================


def _ok(stdout: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


@dataclass
class FakeAppliedSchemaRunner:
    """A runner that answers the discovery query from a modeled CHECK set."""

    # (table, constraint) pairs the modeled applied schema still carries.
    checks: list[tuple[str, str]] = field(default_factory=list)
    # If set, the discovery query fails (information_schema unreachable).
    failDiscovery: bool = False
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
        if 'CHECK_CONSTRAINTS' in sql:
            if self.failDiscovery:
                return _fail('information_schema unreachable')
            return _ok(''.join(f'{t}\t{c}\n' for t, c in self.checks))
        return _ok('')


def _ctx(runner: FakeAppliedSchemaRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.10', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


# ================================================================================
# Verdict logic (hermetic, always runs) -- proves the alarm fires
# ================================================================================


class TestProbeVerdictLogic:
    """Prove the applied-schema probe's RED/GREEN verdict -- NOT the live DB.

    The live assertion is :class:`TestAppliedSchemaLive` (skipped in-loop).
    These test the alarm itself so the deploy gate can never silently pass.
    """

    def test_greenWhenNoDataSourceCheck(self) -> None:
        ctx = _ctx(FakeAppliedSchemaRunner(checks=[]))
        assertAppliedSchemaAcceptsForeign(ctx)  # must not raise
        assert _probeAppliedDataSourceChecks(ctx) == []

    def test_redWhenStaleCheckSurvives(self) -> None:
        ctx = _ctx(FakeAppliedSchemaRunner(checks=[('realtime_data', 'stale_chk')]))
        with pytest.raises(AssertionError, match='REJECTS'):
            assertAppliedSchemaAcceptsForeign(ctx)

    def test_redOnEveryF116DataSourceTable(self) -> None:
        # A stale CHECK on ANY of the F-116 data_source tables trips the alarm.
        for table in m0023.EXPECTED_STALE_CHECK_TABLES:
            ctx = _ctx(FakeAppliedSchemaRunner(checks=[(table, f'{table}_chk')]))
            with pytest.raises(AssertionError):
                assertAppliedSchemaAcceptsForeign(ctx)

    def test_raisesWhenDiscoveryUnreachable(self) -> None:
        # An unreachable probe is loud, never a false pass.
        ctx = _ctx(FakeAppliedSchemaRunner(failDiscovery=True))
        with pytest.raises(asm.SchemaProbeError, match='probe failed'):
            assertAppliedSchemaAcceptsForeign(ctx)

    def test_probeReusesV0023DiscoverySql(self) -> None:
        # Define-once: the probe uses the SAME SQL v0023 uses to verify its own
        # drop, so migration and guard share one definition of a data_source
        # CHECK (no second, drift-prone copy).
        ctx = _ctx(FakeAppliedSchemaRunner(checks=[]))
        _probeAppliedDataSourceChecks(ctx)
        assert any(
            s == m0023.discoverDataSourceCheckSql('obd2db') for s in ctx.runner.calls
        )


# ================================================================================
# Design guard -- this asserts the APPLIED schema, never a Python enum tuple
# ================================================================================


def test_probesAppliedSchemaNotAPythonEnumTuple() -> None:
    """[ATLAS CRITICAL] the guard probes the DEPLOYED schema, it never compares
    the Pi and server Python enum tuples (already equal -> a compare would ship
    GREEN over a broken live DB: the exact miss that shipped this drift).

    Pinned by a self-scan: this module must not reference the enum-tuple
    constant by name, so a future "simplification" into a tuple compare fails
    here instead of silently defeating the guard.
    """
    forbidden = 'DATA_SOURCE' + '_VALUES'  # split to avoid a literal self-match
    source = Path(__file__).read_text(encoding='utf-8')
    assert forbidden not in source


# ================================================================================
# Live deploy-time probe (skipped in-loop; runs against chi-srv-01)
# ================================================================================


@pytest.fixture
def liveCtx() -> RunnerContext:
    """Resolve a real server :class:`RunnerContext`, or skip on the bench.

    Deploy-time / PM-integration gate: opt in with ``OBD2_APPLIED_SCHEMA_TEST=1``
    and run against chi-srv-01 after US-458 deploys.  In-loop this SKIPS -- there
    is no MariaDB on the Windows dev bench, and a skip is honest (it never
    reports green over a live DB it did not actually probe).
    """
    if not os.environ.get(_OPT_IN_ENV):
        pytest.skip(
            'applied-schema probe is a deploy-time gate: set '
            f'{_OPT_IN_ENV}=1 and run against chi-srv-01 after US-458 deploys '
            '(no live MariaDB on the bench).',
        )
    addressesSh = Path(__file__).resolve().parents[2] / 'deploy' / 'addresses.sh'
    addrs = asm.loadAddresses(addressesSh)
    creds = asm.loadServerCreds(addrs)
    return RunnerContext(addrs=addrs, creds=creds, runner=asm._defaultRunner)


class TestAppliedSchemaLive:
    """The real gate: the DEPLOYED schema accepts ``data_source='foreign'``."""

    def test_appliedSchemaHasNoRejectingDataSourceCheck(self, liveCtx: RunnerContext) -> None:
        # GREEN after US-458 drops the stale CHECK; RED if any rejecting
        # data_source CHECK (stale or newly re-introduced) survives on the
        # deployed DB -- the applied-schema assertion, not a tuple compare.
        assertAppliedSchemaAcceptsForeign(liveCtx)
