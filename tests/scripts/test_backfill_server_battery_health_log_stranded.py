################################################################################
# File Name: test_backfill_server_battery_health_log_stranded.py
# Purpose/Description: TDD coverage for
#                      scripts/backfill_server_battery_health_log_stranded.py
#                      (US-323 / B-073).  The script reads Pi-side authoritative
#                      battery_health_log close-event data for the stranded
#                      drain_event_ids (default 11-15), checks server-side state
#                      for idempotency, and emits/applies server-side MariaDB
#                      UPDATE statements.  Tests inject a FakeRunner so no SSH,
#                      SQLite file, or live MariaDB is touched.  Covers the pure
#                      planBackfill/renderUpdateSql seam (incl. the phantom-
#                      column discriminator: server schema has NO *_vcell_v
#                      columns, only end_timestamp/end_soc/runtime_seconds), the
#                      SSH I/O wrappers, the sentinel + backup safety gates, and
#                      the CLI entry points.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex (US-323) | Initial -- TDD coverage for the stranded
#                               battery_health_log server-side backfill (B-073).
# ================================================================================
################################################################################

"""TDD tests for the US-323 / B-073 server-side battery_health_log backfill.

The server-side ``battery_health_log`` table (v0002 migration +
:class:`src.server.db.models.BatteryHealthLog`) carries
``end_timestamp``, ``end_soc`` and ``runtime_seconds`` but *not* the
``start_vcell_v`` / ``end_vcell_v`` columns that the US-289 rename added
Pi-side.  The sprint.json scope text + B-073 backlog both name
``end_vcell_v`` as an UPDATE target -- that is phantom-column drift (same
family as US-322's ``timestamp_ms``).  These tests pin the actual server
column set so the script stays honest against the live schema.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is importable, but use the explicit loader to mirror
# the sibling backfill-script tests and keep the module name stable)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = (
    _PROJECT_ROOT / 'scripts'
    / 'backfill_server_battery_health_log_stranded.py'
)


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'backfill_server_battery_health_log_stranded', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['backfill_server_battery_health_log_stranded'] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _loadScript()


# ================================================================================
# FakeRunner -- scripted subprocess responses keyed by needle
# ================================================================================

@dataclass
class FakeRunner:
    """Minimal scripted runner matching the CommandRunner Protocol."""

    responses: list[tuple[str, subprocess.CompletedProcess[str]]] = field(
        default_factory=list,
    )
    calls: list[dict] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        input: str | None = None,  # noqa: A002 -- matches Protocol
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(
            {'argv': list(argv), 'input': input, 'timeout': timeout},
        )
        argvJoined = ' '.join(argv)
        payload = input or ''
        for needle, response in self.responses:
            if needle in argvJoined or (payload and needle in payload):
                return response
        return subprocess.CompletedProcess(
            args=list(argv), returncode=0, stdout='', stderr='',
        )


def _ok(stdout: str = '', stderr: str = '') -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr,
    )


def _fail(
    stderr: str = 'boom', rc: int = 1,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout='', stderr=stderr,
    )


def _addrs() -> object:
    return bf.HostAddresses(serverHost='10.2.2.2', serverUser='b')


def _creds() -> object:
    return bf.ServerCreds(dbUser='u', dbPassword='p', dbName='dbx')


def _piCoords() -> object:
    return bf.PiCoordinates(
        piHost='10.2.2.1', piUser='a', piDbPath='/x/data/obd.db',
    )


# ================================================================================
# Constants
# ================================================================================

class TestConstants:
    def test_strandedDrainEventIds_are11Through15(self) -> None:
        assert bf.STRANDED_DRAIN_EVENT_IDS == (11, 12, 13, 14, 15)

    def test_backfillColumns_matchServerSchema_noVcellColumn(self) -> None:
        # Phantom-column discriminator: the server-side battery_health_log
        # (v0002 migration) has NO *_vcell_v columns.  The UPDATE target
        # set is exactly end_timestamp/end_soc/runtime_seconds.
        assert bf.BACKFILL_COLUMNS == (
            'end_timestamp', 'end_soc', 'runtime_seconds',
        )
        assert 'end_vcell_v' not in bf.BACKFILL_COLUMNS
        assert 'start_vcell_v' not in bf.BACKFILL_COLUMNS

    def test_drySentinelName_isUs323Specific(self) -> None:
        # Distinct from the US-240 ('.us240-dry-run-ok') sentinel so a
        # pre-mint-orphan dry-run does NOT silently authorize this execute.
        assert bf.DRY_RUN_SENTINEL_NAME == '.us323-dry-run-ok'


# ================================================================================
# Pure planning: planBackfill (no I/O)
# ================================================================================

def _pi(eventId: int, endTs: str | None, endSoc: float | None,
        runtimeSeconds: int | None) -> object:
    return bf.PiDrainRow(
        drainEventId=eventId,
        endTimestamp=endTs,
        endSoc=endSoc,
        runtimeSeconds=runtimeSeconds,
    )


def _srv(rowId: int, endTs: str | None) -> object:
    return bf.ServerDrainRow(rowId=rowId, endTimestamp=endTs)


_PI_FULL: list = [
    _pi(11, '2026-05-10T00:52:28Z', 3.42, 757),
    _pi(12, '2026-05-10T01:12:43Z', 3.44, 642),
    _pi(13, '2026-05-10T02:34:59Z', 3.43, 612),
    _pi(14, '2026-05-10T03:47:44Z', 3.42, 722),
    _pi(15, '2026-05-10T14:13:49Z', 3.445, 786),
]
_SRV_ALL_NULL: list = [_srv(i, None) for i in (11, 12, 13, 14, 15)]


class TestPlanBackfill:
    def test_allStranded_producesOneBackfillRowPerId(self) -> None:
        plan = bf.planBackfill(
            _PI_FULL, _SRV_ALL_NULL,
            drainEventIds=(11, 12, 13, 14, 15),
        )
        assert [r.rowId for r in plan.toUpdate] == [11, 12, 13, 14, 15]
        assert plan.skipped == []

    def test_backfillRow_carriesPiAuthoritativeValuesVerbatim(self) -> None:
        plan = bf.planBackfill(
            _PI_FULL, _SRV_ALL_NULL, drainEventIds=(15,),
        )
        row = plan.toUpdate[0]
        assert row.rowId == 15
        assert row.endTimestamp == '2026-05-10T14:13:49Z'
        assert row.endSoc == pytest.approx(3.445)
        assert row.runtimeSeconds == 786

    def test_alreadyPopulatedServerRow_isSkipped_forIdempotency(self) -> None:
        srv = [
            _srv(11, '2026-05-10T00:52:28Z'),  # already populated server-side
            _srv(12, None),
        ]
        plan = bf.planBackfill(_PI_FULL, srv, drainEventIds=(11, 12))
        assert [r.rowId for r in plan.toUpdate] == [12]
        assert any(s.rowId == 11 and 'populated' in s.reason
                   for s in plan.skipped)

    def test_missingServerRow_isSkipped(self) -> None:
        srv = [_srv(12, None)]  # row 11 absent server-side
        plan = bf.planBackfill(_PI_FULL, srv, drainEventIds=(11, 12))
        assert [r.rowId for r in plan.toUpdate] == [12]
        assert any(s.rowId == 11 and 'server row' in s.reason.lower()
                   for s in plan.skipped)

    def test_missingPiRow_isSkipped_withStopConditionReason(self) -> None:
        # stopCondition[1]: Pi-side authoritative data unavailable for a
        # stranded id -> the row stays permanently stranded; we do NOT
        # fabricate values.
        piPartial = [r for r in _PI_FULL if r.drainEventId != 13]
        plan = bf.planBackfill(
            piPartial, _SRV_ALL_NULL, drainEventIds=(11, 12, 13, 14, 15),
        )
        assert 13 not in [r.rowId for r in plan.toUpdate]
        skip13 = next(s for s in plan.skipped if s.rowId == 13)
        assert 'pi' in skip13.reason.lower()
        assert 'stranded' in skip13.reason.lower()

    def test_unclosedPiRow_isSkipped(self) -> None:
        # A Pi row whose end_timestamp is still NULL has no close-event to
        # replay -- skip rather than write a half-row server-side.
        piWithOpen = [
            _pi(11, None, None, None),  # never closed Pi-side
            *[r for r in _PI_FULL if r.drainEventId != 11],
        ]
        plan = bf.planBackfill(
            piWithOpen, _SRV_ALL_NULL, drainEventIds=(11, 12),
        )
        assert 11 not in [r.rowId for r in plan.toUpdate]
        assert any(s.rowId == 11 and 'not closed' in s.reason.lower()
                   for s in plan.skipped)

    def test_emptyInputs_producesEmptyPlan(self) -> None:
        plan = bf.planBackfill([], [], drainEventIds=())
        assert plan.toUpdate == []
        assert plan.skipped == []


# ================================================================================
# Pure rendering: renderUpdateSql (no I/O)
# ================================================================================

def _upd(rowId: int, endTs: str, endSoc: float | None,
         runtimeSeconds: int | None) -> object:
    return bf.BackfillRow(
        rowId=rowId,
        endTimestamp=endTs,
        endSoc=endSoc,
        runtimeSeconds=runtimeSeconds,
    )


class TestRenderUpdateSql:
    def test_emptyRows_producesEmptyString(self) -> None:
        assert bf.renderUpdateSql([]) == ''

    def test_emitsTransactionWrappedUpdates(self) -> None:
        sql = bf.renderUpdateSql([_upd(15, '2026-05-10T14:13:49Z', 3.445, 786)])
        assert sql.strip().startswith('START TRANSACTION;')
        assert sql.strip().endswith('COMMIT;')

    def test_oneUpdatePerRow(self) -> None:
        rows = [
            _upd(11, '2026-05-10T00:52:28Z', 3.42, 757),
            _upd(12, '2026-05-10T01:12:43Z', 3.44, 642),
        ]
        sql = bf.renderUpdateSql(rows)
        assert sql.count('UPDATE battery_health_log SET') == 2

    def test_updateCarriesIdempotencyGuard(self) -> None:
        # Every UPDATE must keep `AND end_timestamp IS NULL` so re-running
        # the SQL after a clean apply touches zero rows (SQL-level
        # idempotency, defense beyond the plan-level skip).
        sql = bf.renderUpdateSql([_upd(11, '2026-05-10T00:52:28Z', 3.42, 757)])
        assert 'WHERE id = 11' in sql
        assert 'end_timestamp IS NULL' in sql

    def test_updateSetClause_onlyServerColumns_noVcell(self) -> None:
        # Phantom-column discriminator: would FAIL if the SET clause ever
        # included end_vcell_v / start_vcell_v (absent from server schema).
        sql = bf.renderUpdateSql([_upd(11, '2026-05-10T00:52:28Z', 3.42, 757)])
        assert 'end_timestamp =' in sql
        assert 'end_soc =' in sql
        assert 'runtime_seconds =' in sql
        assert 'vcell_v' not in sql

    def test_endTimestampQuotedAsSqlString(self) -> None:
        sql = bf.renderUpdateSql([_upd(11, '2026-05-10T00:52:28Z', 3.42, 757)])
        assert "end_timestamp = '2026-05-10T00:52:28Z'" in sql

    def test_nullRuntimeSeconds_emittedAsSqlNull(self) -> None:
        sql = bf.renderUpdateSql([_upd(11, '2026-05-10T00:52:28Z', 3.42, None)])
        assert 'runtime_seconds = NULL' in sql

    def test_nullEndSoc_emittedAsSqlNull(self) -> None:
        sql = bf.renderUpdateSql([_upd(11, '2026-05-10T00:52:28Z', None, 757)])
        assert 'end_soc = NULL' in sql


# ================================================================================
# I/O wrappers -- scanPiRows / scanServerRows / applyBackfill / backupServer
# ================================================================================

class TestScanPiRows:
    def test_parsesPipeDelimitedSqliteOutput(self) -> None:
        runner = FakeRunner(responses=[
            ('sqlite3', _ok(stdout=(
                '11|2026-05-10T00:52:28Z|3.42|757\n'
                '12|2026-05-10T01:12:43Z|3.44|642\n'
            ))),
        ])
        rows = bf.scanPiRows(_piCoords(), runner, drainEventIds=(11, 12))
        assert len(rows) == 2
        assert rows[0].drainEventId == 11
        assert rows[0].endTimestamp == '2026-05-10T00:52:28Z'
        assert rows[0].endSoc == pytest.approx(3.42)
        assert rows[0].runtimeSeconds == 757

    def test_emptyEndTimestampParsedAsNone(self) -> None:
        # sqlite3 list-mode renders SQL NULL as an empty field.
        runner = FakeRunner(responses=[
            ('sqlite3', _ok(stdout='11|||\n')),
        ])
        rows = bf.scanPiRows(_piCoords(), runner, drainEventIds=(11,))
        assert rows[0].endTimestamp is None
        assert rows[0].endSoc is None
        assert rows[0].runtimeSeconds is None

    def test_sshFailure_raisesBackfillError(self) -> None:
        runner = FakeRunner(responses=[('sqlite3', _fail(stderr='no such db'))])
        with pytest.raises(bf.BackfillError, match='[Pp]i'):
            bf.scanPiRows(_piCoords(), runner, drainEventIds=(11,))

    def test_passwordlessRemote_queriesByDrainEventId(self) -> None:
        runner = FakeRunner(responses=[('sqlite3', _ok(stdout=''))])
        bf.scanPiRows(_piCoords(), runner, drainEventIds=(11, 12, 13))
        # The remote command targets the Pi host + the obd.db path + the
        # IN-list of stranded ids, and uses sqlite3 -readonly (never mutates).
        joined = ' '.join(runner.calls[0]['argv'])
        assert 'a@10.2.2.1' in joined
        assert '/x/data/obd.db' in joined
        assert 'sqlite3 -readonly' in joined
        assert 'drain_event_id' in joined
        assert '(11,12,13)' in joined.replace(' ', '')


class TestScanServerRows:
    def test_parsesTabDelimitedMysqlOutput(self) -> None:
        runner = FakeRunner(responses=[
            ('SELECT id, end_timestamp FROM battery_health_log',
             _ok(stdout='11\tNULL\n12\t2026-05-10 01:12:43\n')),
        ])
        rows = bf.scanServerRows(_addrs(), _creds(), runner,
                                 drainEventIds=(11, 12))
        byId = {r.rowId: r for r in rows}
        assert byId[11].endTimestamp is None  # literal "NULL" -> None
        assert byId[12].endTimestamp == '2026-05-10 01:12:43'

    def test_sshFailure_raisesBackfillError(self) -> None:
        runner = FakeRunner(responses=[
            ('SELECT id, end_timestamp FROM battery_health_log',
             _fail(stderr='Access denied')),
        ])
        with pytest.raises(bf.BackfillError, match='server'):
            bf.scanServerRows(_addrs(), _creds(), runner,
                              drainEventIds=(11,))


class TestApplyBackfill:
    def test_emptyRows_returnsZero_noSubprocessCall(self) -> None:
        runner = FakeRunner()
        assert bf.applyBackfill(_addrs(), _creds(), runner, []) == 0
        assert runner.calls == []

    def test_pipesUpdateSqlToMysql(self) -> None:
        runner = FakeRunner(responses=[('UPDATE battery_health_log', _ok())])
        n = bf.applyBackfill(
            _addrs(), _creds(), runner,
            [_upd(11, '2026-05-10T00:52:28Z', 3.42, 757)],
        )
        assert n == 1
        assert any('UPDATE battery_health_log' in (c['input'] or '')
                   for c in runner.calls)

    def test_nonZeroReturn_raisesBackfillError(self) -> None:
        runner = FakeRunner(responses=[
            ('UPDATE battery_health_log', _fail(stderr='deadlock')),
        ])
        with pytest.raises(bf.BackfillError, match='UPDATE'):
            bf.applyBackfill(
                _addrs(), _creds(), runner,
                [_upd(11, '2026-05-10T00:52:28Z', 3.42, 757)],
            )


class TestBackupServer:
    def test_invokesMysqldumpForBatteryHealthLog(self) -> None:
        runner = FakeRunner(responses=[
            ('mysqldump', _ok(stdout='')),
            ('stat -c %s', _ok(stdout='2048\n')),
        ])
        path = bf.backupServer(_addrs(), _creds(), runner, '20260511-1200Z')
        assert path.startswith('/tmp/obd2-us323-backup-')
        assert path.endswith('.sql')
        assert any('battery_health_log' in arg
                   for c in runner.calls for arg in c['argv'])

    def test_dumpFailure_raisesSafetyGateError(self) -> None:
        runner = FakeRunner(responses=[('mysqldump', _fail(stderr='denied'))])
        with pytest.raises(bf.SafetyGateError, match='backup'):
            bf.backupServer(_addrs(), _creds(), runner, '20260511-1200Z')


# ================================================================================
# CLI -- --dry-run, --execute, sentinel
# ================================================================================

class TestCli:
    def _addressesShFile(self, tmp_path: Path) -> Path:
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
        return addresses

    def _envDump(self) -> str:
        return (
            'SERVER_HOST=10.2.2.2\nSERVER_USER=b\n'
            'PI_HOST=10.2.2.1\nPI_USER=a\nPI_PATH=/x\n'
        )

    def _piRows(self) -> str:
        return (
            '11|2026-05-10T00:52:28Z|3.42|757\n'
            '12|2026-05-10T01:12:43Z|3.44|642\n'
            '13|2026-05-10T02:34:59Z|3.43|612\n'
            '14|2026-05-10T03:47:44Z|3.42|722\n'
            '15|2026-05-10T14:13:49Z|3.445|786\n'
        )

    def _serverRowsAllNull(self) -> str:
        return '\n'.join(f'{i}\tNULL' for i in (11, 12, 13, 14, 15)) + '\n'

    def _serverRowsAllPopulated(self) -> str:
        return (
            '11\t2026-05-10 00:52:28\n12\t2026-05-10 01:12:43\n'
            '13\t2026-05-10 02:34:59\n14\t2026-05-10 03:47:44\n'
            '15\t2026-05-10 14:13:49\n'
        )

    def _baseRunner(self, *, serverRows: str | None = None) -> FakeRunner:
        return FakeRunner(responses=[
            ('bash', _ok(stdout=self._envDump())),
            ('DATABASE_URL=', _ok(
                stdout='DATABASE_URL=mysql+aiomysql://u:p@localhost/dbx\n',
            )),
            ('sqlite3', _ok(stdout=self._piRows())),
            ('SELECT id, end_timestamp FROM battery_health_log',
             _ok(stdout=serverRows or self._serverRowsAllNull())),
            ('mysqldump', _ok(stdout='')),
            ('stat -c %s', _ok(stdout='2048\n')),
            ('UPDATE battery_health_log', _ok(stdout='')),
        ])

    def test_noModeFlag_exits(self) -> None:
        with pytest.raises(SystemExit):
            bf.main([])

    def test_dryRunAndExecuteAreMutuallyExclusive(self) -> None:
        with pytest.raises(SystemExit):
            bf.main(['--dry-run', '--execute'])

    def test_dryRun_reportsPlanWritesSentinel_doesNotMutate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = self._baseRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        rc = bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc == 0
        assert (sentinelDir / bf.DRY_RUN_SENTINEL_NAME).exists()
        # No UPDATE went out during the dry-run.
        assert not any('UPDATE battery_health_log' in (c['input'] or '')
                       for c in runner.calls)

    def test_executeRequiresPriorDryRun(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bf, '_defaultRunner', self._baseRunner())
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'no-sentinel'
        sentinelDir.mkdir()
        rc = bf.main([
            '--execute',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc == 2

    def test_executeAfterDryRun_appliesBackfill_clearsSentinel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = self._baseRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        assert bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 0
        assert bf.main([
            '--execute',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ]) == 0
        assert not (sentinelDir / bf.DRY_RUN_SENTINEL_NAME).exists()
        # mysqldump (backup-first) AND the UPDATE both went out.
        assert any('mysqldump' in arg
                   for c in runner.calls for arg in c['argv'])
        assert any('UPDATE battery_health_log' in (c['input'] or '')
                   for c in runner.calls)

    def test_allServerRowsPopulated_dryRunReportsNothingToDo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = self._baseRunner(serverRows=self._serverRowsAllPopulated())
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        rc = bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc == 0
        # Idempotent: execute is a no-op (no backup, no UPDATE).
        rc2 = bf.main([
            '--execute',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc2 == 0
        assert not any('UPDATE battery_health_log' in (c['input'] or '')
                       for c in runner.calls)

    def test_missingPiAuthoritativeData_dryRunReportsStranded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        # Pi DB returns nothing for 11-15 (e.g. Pi DB reset) -> per
        # stopCondition[1] these rows stay stranded; the report says so and
        # the run still exits 0 (nothing to backfill, no error).
        runner = self._baseRunner()
        # Override the sqlite3 response to be empty.
        runner.responses = [
            (n, (r if n != 'sqlite3' else _ok(stdout='')))
            for n, r in runner.responses
        ]
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        rc = bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        captured = capsys.readouterr()
        assert rc == 0
        assert 'stranded' in captured.out.lower()
