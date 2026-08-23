################################################################################
# File Name: test_applied_schema_column_defaults.py
# Purpose/Description: US-563 (F-134 / A-10) -- applied-schema guard that asserts
#                      COLUMN DEFAULTS, not only column presence and type.  The
#                      US-459/US-462 guard family proved the DEPLOYED schema
#                      accepts a value; this one proves the DEPLOYED schema does
#                      not hand out a VERDICT to a row nobody assessed.
#                      Two rules, both discovery-driven:
#                        1. NO column named data_quality -- on ANY table, incl.
#                           tables that do not exist yet -- may DEFAULT to an
#                           assessed value.
#                        2. drive_summary.is_real must DEFAULT to NULL.
#                      This is the durable A-10-class fix: it stops the NEXT
#                      column defaulting to a verdict.  Atlas required it to
#                      carry its own acceptance line and its own test rather
#                      than ride as prose inside US-563.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-563) | Initial -- applied-schema COLUMN DEFAULT guard.
# ================================================================================
################################################################################

"""US-563 / F-134 -- the DEPLOYED schema never defaults a verdict column.

Why a guard and not just two ALTERs
-----------------------------------

Changing ``drive_summary``'s two defaults fixes the two columns that shipped the
2026-08-20 misleading read.  It does nothing about the NEXT verdict column
somebody adds with ``DEFAULT 'full'`` because that is what the neighbouring
column already said.  Atlas was explicit: folded in as prose this gets built as
"change two defaults" and the guard quietly does not happen.

So the rule is DISCOVERY-DRIVEN, in the shape v0023/US-458 established: the
probe asks ``information_schema.COLUMNS`` which columns named ``data_quality``
exist on the deployed schema and checks each one's DEFAULT.  A table added
tomorrow is covered without editing this file.  There are **no carve-outs** --
a column-level default that is a verdict is wrong wherever it lives, including
on tables whose writers happen to always set the value today.  ("The writer
always sets it" is a claim about intent, never about enforcement.)

Two layers, mirroring US-459
----------------------------

* **Live probe (deploy gate).**  :class:`TestAppliedSchemaLive` runs against the
  real server and asserts both rules.  It is SKIPPED in-loop (no MariaDB on the
  Windows bench) and only runs when opted in (``OBD2_APPLIED_SCHEMA_TEST=1``).
  A skip is honest here: it never reports green *over* a broken DB.
* **Verdict logic (hermetic, always runs).**  :class:`TestGuardVerdictLogic`
  feeds a fake runner modelling an applied schema and proves the guard goes RED
  on a deliberately wrong DEFAULT -- validationCriteria #2 verbatim.  These test
  the alarm, so the deploy gate cannot silently pass.

The probe reuses v0024's own discovery SQL + default-normalizer, so the
migration and this guard share ONE definition of "the applied default".
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
from src.server.migrations.versions import (
    v0024_us563_unassessed_defaults_and_intake_rename as m0024,
)

_OPT_IN_ENV: str = 'OBD2_APPLIED_SCHEMA_TEST'


# ================================================================================
# The applied-schema probe (reuses v0024's discovery SQL -- define-once)
# ================================================================================


def _probeDataQualityDefaults(ctx: RunnerContext) -> list[tuple[str, str | None]]:
    """Return ``[(table, normalizedDefault), ...]`` for every data_quality column.

    ``normalizedDefault`` is ``None`` when the applied schema declares no default
    (or ``DEFAULT NULL``); otherwise the bare default value with MariaDB's
    quoting stripped.
    """
    sql = m0024.discoverDataQualityDefaultsSql(ctx.creds.dbName)
    res = asm._runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise asm.SchemaProbeError(
            'applied-schema data_quality DEFAULT probe failed: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    found: list[tuple[str, str | None]] = []
    for line in res.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t')
        table = parts[0].strip()
        raw = parts[2] if len(parts) >= 3 else ''
        found.append((table, m0024.normalizeAppliedDefault(raw)))
    return found


def _columnExists(ctx: RunnerContext, tableName: str, columnName: str) -> bool:
    """Return True when the DEPLOYED schema carries the column."""
    sql = m0024.columnExistsSql(ctx.creds.dbName, tableName, columnName)
    res = asm._runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise asm.SchemaProbeError(
            f'applied-schema column probe failed for {tableName}.{columnName}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    txt = res.stdout.strip()
    return bool(txt) and txt.split()[0] not in ('0', 'NULL')


def _probeColumnDefault(
    ctx: RunnerContext, tableName: str, columnName: str,
) -> str | None:
    """Return one column's normalized applied DEFAULT (``None`` = NULL/absent)."""
    sql = m0024.discoverColumnDefaultSql(ctx.creds.dbName, tableName, columnName)
    res = asm._runServerSql(ctx.addrs, ctx.creds, sql, ctx.runner)
    if res.returncode != 0:
        raise asm.SchemaProbeError(
            f'applied-schema DEFAULT probe failed for {tableName}.{columnName}: '
            f'{res.stderr.strip() or res.stdout.strip()}',
        )
    return m0024.normalizeAppliedDefault(res.stdout)


def assertNoVerdictColumnDefaults(ctx: RunnerContext) -> None:
    """Assert the APPLIED schema hands no row a verdict it did not earn.

    Rule 1: no ``data_quality`` column on any table DEFAULTs to an assessed
    value.  Rule 2: every column in :data:`m0024.NULL_DEFAULT_COLUMNS` DEFAULTs
    to NULL.

    GREEN when the deployed schema distinguishes unassessed from assessed-good;
    RED (``AssertionError``) on any verdict-shaped default -- including one on a
    table that did not exist when this guard was written.
    """
    offenders = [
        f'{table}.{m0024.DATA_QUALITY_COLUMN} DEFAULT {default!r}'
        for table, default in _probeDataQualityDefaults(ctx)
        if default in m0024.ASSESSED_DATA_QUALITY_VALUES
    ]
    if offenders:
        raise AssertionError(
            'applied schema DEFAULTS a quality VERDICT onto unassessed rows: '
            + ', '.join(offenders)
            + f'.  A data_quality column must default to '
            f'{m0024.UNASSESSED_VALUE!r} (or carry no default) -- this is the '
            'F-134 defect that read a pending drive as full-quality.',
        )

    for table, column in m0024.NULL_DEFAULT_COLUMNS:
        applied = _probeColumnDefault(ctx, table, column)
        if applied is not None:
            raise AssertionError(
                f'applied schema gives {table}.{column} DEFAULT {applied!r}; it '
                f'must DEFAULT NULL.  A non-NULL default on a computed column '
                f'reads as a computed verdict on a row nobody computed.',
            )


# ================================================================================
# Hermetic fake runner -- models an applied schema's defaults
# ================================================================================


def _ok(stdout: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


def _fail(stderr: str = 'boom') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr=stderr)


@dataclass
class FakeAppliedDefaultsRunner:
    """Answers the discovery queries from a modeled applied schema.

    ``dataQualityDefaults`` maps table -> the RAW default text MariaDB would
    return (quoted, or the literal ``NULL``).  ``columnDefaults`` maps
    ``(table, column)`` -> raw default text for the single-column probe.
    """

    dataQualityDefaults: dict[str, str] = field(default_factory=dict)
    columnDefaults: dict[tuple[str, str], str] = field(default_factory=dict)
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
        if self.failDiscovery:
            return _fail('information_schema unreachable')
        if f"COLUMN_NAME='{m0024.DATA_QUALITY_COLUMN}'" in sql and 'TABLE_NAME=' not in sql:
            return _ok(''.join(
                f'{t}\t{m0024.DATA_QUALITY_COLUMN}\t{d}\n'
                for t, d in self.dataQualityDefaults.items()
            ))
        for (table, column), default in self.columnDefaults.items():
            if f"TABLE_NAME='{table}'" in sql and f"COLUMN_NAME='{column}'" in sql:
                return _ok(f'{default}\n')
        return _ok('NULL\n')


def _ctx(runner: FakeAppliedDefaultsRunner) -> RunnerContext:
    return RunnerContext(
        addrs=asm.HostAddresses(serverHost='10.27.27.120', serverUser='mcornelison'),
        creds=asm.ServerCreds(dbUser='obd2', dbPassword='secret', dbName='obd2db'),
        runner=runner,
    )


def _healthyRunner(**overrides) -> FakeAppliedDefaultsRunner:
    """A modeled applied schema that satisfies BOTH rules."""
    runner = FakeAppliedDefaultsRunner(
        dataQualityDefaults={
            'drive_summary': f"'{m0024.UNASSESSED_VALUE}'",
            'drive_statistics': f"'{m0024.UNASSESSED_VALUE}'",
            'drives': f"'{m0024.UNASSESSED_VALUE}'",
        },
        columnDefaults={('drive_summary', 'is_real'): 'NULL'},
    )
    for key, value in overrides.items():
        setattr(runner, key, value)
    return runner


# ================================================================================
# Verdict logic (hermetic, always runs) -- proves the alarm fires
# ================================================================================


class TestGuardVerdictLogic:
    """Prove the guard's RED/GREEN verdict -- NOT the live DB.

    The live assertion is :class:`TestAppliedSchemaLive` (skipped in-loop).
    """

    def test_greenWhenNoVerdictDefaultAnywhere(self) -> None:
        ctx = _ctx(_healthyRunner())
        assertNoVerdictColumnDefaults(ctx)  # must not raise

    @pytest.mark.parametrize('verdict', sorted(m0024.ASSESSED_DATA_QUALITY_VALUES))
    def test_redOnAnyAssessedValueAsADefault(self, verdict: str) -> None:
        """validationCriteria #2: point the guard at a deliberately wrong DEFAULT.

        Parametrized over EVERY assessed value, not just 'full' -- the defect is
        "defaults to a verdict", and re-defaulting to 'sparse' would be the same
        bug wearing a different word.
        """
        runner = _healthyRunner()
        runner.dataQualityDefaults['drive_summary'] = f"'{verdict}'"
        with pytest.raises(AssertionError, match='VERDICT'):
            assertNoVerdictColumnDefaults(_ctx(runner))

    def test_redOnAVerdictDefaultOnAnyTable(self) -> None:
        # Discovery-driven, no carve-outs: the alarm fires wherever the column
        # lives, not only on the table this story happened to be about.
        for table in ('drive_summary', 'drive_statistics', 'drives'):
            runner = _healthyRunner()
            runner.dataQualityDefaults[table] = "'full'"
            with pytest.raises(AssertionError, match=table):
                assertNoVerdictColumnDefaults(_ctx(runner))

    def test_redOnAVerdictDefaultOnATableThatDoesNotExistYet(self) -> None:
        """The durable half: it stops the NEXT column defaulting to a verdict.

        A table nobody has written yet is discovered by the probe and judged by
        the same rule.  Without this the guard is a two-column assertion wearing
        a discovery query.
        """
        runner = _healthyRunner()
        runner.dataQualityDefaults['some_future_rollup'] = "'full'"
        with pytest.raises(AssertionError, match='some_future_rollup'):
            assertNoVerdictColumnDefaults(_ctx(runner))

    def test_redWhenIsRealDefaultsToZero(self) -> None:
        # The literal 2026-08-20 read: is_real=0 on a drive nobody assessed.
        runner = _healthyRunner()
        runner.columnDefaults[('drive_summary', 'is_real')] = '0'
        with pytest.raises(AssertionError, match='is_real'):
            assertNoVerdictColumnDefaults(_ctx(runner))

    def test_redWhenIsRealDefaultsToOne(self) -> None:
        # Both directions -- a default of 1 is the same false confidence with a
        # friendlier value, and would be far harder to notice.
        runner = _healthyRunner()
        runner.columnDefaults[('drive_summary', 'is_real')] = '1'
        with pytest.raises(AssertionError, match='is_real'):
            assertNoVerdictColumnDefaults(_ctx(runner))

    def test_greenWhenDataQualityHasNoDefaultAtAll(self) -> None:
        # AC-2 permits either remedy: an explicit unassessed value, OR dropping
        # the default entirely.  Both must pass or the guard over-specifies.
        runner = _healthyRunner()
        runner.dataQualityDefaults['drive_summary'] = 'NULL'
        assertNoVerdictColumnDefaults(_ctx(runner))

    def test_raisesWhenDiscoveryUnreachable(self) -> None:
        # An unreachable probe is loud, never a false pass (US-459's rule).
        with pytest.raises(asm.SchemaProbeError, match='probe failed'):
            assertNoVerdictColumnDefaults(_ctx(_healthyRunner(failDiscovery=True)))

    def test_probeReusesV0024DiscoverySql(self) -> None:
        # Define-once: migration and guard share one definition of "the applied
        # default", so a change to the probe cannot drift them apart.
        ctx = _ctx(_healthyRunner())
        _probeDataQualityDefaults(ctx)
        assert any(
            s == m0024.discoverDataQualityDefaultsSql('obd2db')
            for s in ctx.runner.calls
        )


class TestDefaultNormalizer:
    """``normalizeAppliedDefault`` -- the one place quoting is decided."""

    @pytest.mark.parametrize('raw', ['NULL', 'null', '', '   ', '\n'])
    def test_absentOrNullReadsAsNone(self, raw: str) -> None:
        assert m0024.normalizeAppliedDefault(raw) is None

    @pytest.mark.parametrize(
        ('raw', 'expected'),
        [
            ("'full'", 'full'),
            ('full', 'full'),
            ("  'unassessed'  \n", 'unassessed'),
            ('0', '0'),
            ("'attribution_anomaly'", 'attribution_anomaly'),
        ],
    )
    def test_stripsMariaDbQuoting(self, raw: str, expected: str) -> None:
        assert m0024.normalizeAppliedDefault(raw) == expected

    def test_aQuotedNullStringIsNotSqlNull(self) -> None:
        """``DEFAULT 'NULL'`` is a four-character string, not an absent default.

        Sounds pedantic; it is the difference between "no verdict" and a column
        whose verdict is the word NULL.  Coerce-or-None, never coerce-or-hope.
        """
        assert m0024.normalizeAppliedDefault("'NULL'") == 'NULL'


# ================================================================================
# Design guard -- this asserts the APPLIED schema, never the ORM
# ================================================================================


def test_guardProbesAppliedSchemaNotTheOrmModel() -> None:
    """[US-459 lesson, inherited] the guard probes the DEPLOYED schema.

    An ORM assertion is already covered by
    ``tests/server/test_drive_summary_unassessed_and_intake_air.py`` and would
    ship GREEN over a live DB that never got ALTERed -- which is EXACTLY the
    drift that shipped this defect class before (US-424 changed the enum and
    never touched obd2db).  Pinned by a self-scan so a future "simplification"
    into a model compare fails here instead of silently defeating the guard.
    """
    forbidden = 'DriveSummary' + '.__table__'
    source = Path(__file__).read_text(encoding='utf-8')
    assert forbidden not in source


# ================================================================================
# Live deploy-time probe (skipped in-loop; runs against chi-srv-01)
# ================================================================================


@pytest.fixture
def liveCtx() -> RunnerContext:
    """Resolve a real server :class:`RunnerContext`, or skip on the bench."""
    if not os.environ.get(_OPT_IN_ENV):
        pytest.skip(
            'applied-schema DEFAULT probe is a deploy-time gate: set '
            f'{_OPT_IN_ENV}=1 and run against chi-srv-01 after US-563 deploys '
            '(no live MariaDB on the bench).',
        )
    addressesSh = Path(__file__).resolve().parents[2] / 'deploy' / 'addresses.sh'
    addrs = asm.loadAddresses(addressesSh)
    creds = asm.loadServerCreds(addrs)
    return RunnerContext(addrs=addrs, creds=creds, runner=asm._defaultRunner)


class TestAppliedSchemaLive:
    """The real gate: the DEPLOYED schema defaults no verdict (validationCriteria #1)."""

    def test_appliedSchemaDefaultsNoVerdict(self, liveCtx: RunnerContext) -> None:
        assertNoVerdictColumnDefaults(liveCtx)

    def test_appliedSchemaCarriesTheRenamedIntakeAirColumn(
        self, liveCtx: RunnerContext,
    ) -> None:
        """The third of validationCriteria #1 -- "column renamed".

        Read off the applied schema, not the ORM.  Asserted as a POSITIVE
        (the new column EXISTS) plus a negative (the mislabeled one is gone):
        a default-probe alone would pass vacuously on a column that is simply
        absent, which is US-552's "absence assertions pass on a missing thing"
        gotcha wearing a schema hat.
        """
        assert _columnExists(
            liveCtx, m0024.DRIVE_SUMMARY_TABLE, m0024.NEW_INTAKE_COLUMN,
        ), f'{m0024.NEW_INTAKE_COLUMN} absent from the deployed drive_summary'
        assert not _columnExists(
            liveCtx, m0024.DRIVE_SUMMARY_TABLE, m0024.OLD_AMBIENT_COLUMN,
        ), (
            f'{m0024.OLD_AMBIENT_COLUMN} survives alongside the honest name -- '
            f'two live spellings of one reading is how a mislabel outlives its '
            f'own rename'
        )
