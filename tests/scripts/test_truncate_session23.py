################################################################################
# File Name: test_truncate_session23.py
# Purpose/Description: Unit tests for scripts/truncate_session23.py.
#                      Uses a FakeRunner injected into the script's SSH seam so
#                      the tests never touch a network. Covers divergence
#                      detection, report rendering, DSN + addresses parsing,
#                      fixture hash verification, sentinel flow, Pi table
#                      scan, and safety-gate CLI behavior (--execute without
#                      sentinel; --execute with divergence).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-205) | Initial -- TDD coverage for US-205 script.
# ================================================================================
################################################################################

"""TDD tests for the US-205 truncate script."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'truncate_session23.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'truncate_session23', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['truncate_session23'] = mod
    spec.loader.exec_module(mod)
    return mod


ts = _loadScript()


# ================================================================================
# FakeRunner -- scripted subprocess responses
# ================================================================================

@dataclass
class FakeRunner:
    """Minimal scripted runner matching the CommandRunner Protocol."""

    responses: list[tuple[str, subprocess.CompletedProcess[str]]] = field(
        default_factory=list,
    )
    calls: list[dict] = field(default_factory=list)
    matcher: Callable[[Sequence[str], str], bool] | None = None

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


# ================================================================================
# loadAddresses
# ================================================================================

class TestLoadAddresses:
    def test_loadAddresses_happyPath_parsesEnvFromBash(self, tmp_path: Path):
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
        envBlob = (
            'PI_HOST=10.1.1.1\nPI_USER=alice\nPI_PATH=/srv/pi\n'
            'PI_PORT=22\nSERVER_HOST=10.2.2.2\nSERVER_USER=bob\n'
        )
        runner = FakeRunner(
            responses=[('bash', _ok(stdout=envBlob))],
        )
        addrs = ts.loadAddresses(addresses, runner=runner)
        assert addrs.piHost == '10.1.1.1'
        assert addrs.piUser == 'alice'
        assert addrs.piPath == '/srv/pi'
        assert addrs.piPort == '22'
        assert addrs.serverHost == '10.2.2.2'
        assert addrs.serverUser == 'bob'

    def test_loadAddresses_missingFile_raises(self, tmp_path: Path):
        with pytest.raises(ts.TruncateError, match='not found'):
            ts.loadAddresses(tmp_path / 'nope.sh', runner=FakeRunner())

    def test_loadAddresses_missingVars_raises(self, tmp_path: Path):
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('x', encoding='utf-8')
        runner = FakeRunner(
            responses=[('bash', _ok(stdout='PI_HOST=10.1.1.1\n'))],
        )
        with pytest.raises(ts.TruncateError, match='missing required vars'):
            ts.loadAddresses(addresses, runner=runner)


# ================================================================================
# loadServerCreds (DSN parser)
# ================================================================================

class TestLoadServerCreds:
    def _addrs(self):
        return ts.HostAddresses(
            piHost='10.1.1.1', piUser='a', piPath='/p', piPort='22',
            serverHost='10.2.2.2', serverUser='b',
        )

    def test_loadServerCreds_parseAiomysqlDsn(self):
        dsn = 'DATABASE_URL=mysql+aiomysql://u:p@localhost/dbx\n'
        runner = FakeRunner(responses=[('ssh', _ok(stdout=dsn))])
        creds = ts.loadServerCreds(self._addrs(), runner=runner)
        assert creds.dbUser == 'u'
        assert creds.dbPassword == 'p'
        assert creds.dbName == 'dbx'

    def test_loadServerCreds_malformed_raises(self):
        runner = FakeRunner(responses=[('ssh', _ok(stdout='DATABASE_URL=garbage\n'))])
        with pytest.raises(ts.TruncateError, match='malformed'):
            ts.loadServerCreds(self._addrs(), runner=runner)

    def test_loadServerCreds_sshFail_raises(self):
        runner = FakeRunner(responses=[('ssh', _fail())])
        with pytest.raises(ts.TruncateError, match='DATABASE_URL'):
            ts.loadServerCreds(self._addrs(), runner=runner)


# ================================================================================
# Fixture hash verify
# ================================================================================

class TestVerifyFixtureHash:
    def test_verifyFixtureHash_real_fileMatches(self):
        match, sha, nbytes = ts.verifyFixtureHash(_PROJECT_ROOT)
        assert match, (
            f'Live fixture hash moved; expected '
            f'{ts.FIXTURE_EXPECTED_SHA256[:16]}... got {sha[:16]}...'
        )
        assert nbytes == ts.FIXTURE_EXPECTED_BYTES

    def test_verifyFixtureHash_absentFile_returnsFalse(self, tmp_path: Path):
        match, sha, nbytes = ts.verifyFixtureHash(tmp_path)
        assert match is False
        assert sha == ''
        assert nbytes == 0


# ================================================================================
# Divergence detection
# ================================================================================

class TestDivergenceDetected:
    def _goodPiTable(self, name: str) -> ts.TableState:
        return ts.TableState(
            name=name, rows=10, dataSourceRows=10,
            hasDataSourceColumn=True, hasDriveIdColumn=True,
        )

    def _goodServerTable(self, name: str) -> ts.TableState:
        return ts.TableState(
            name=name, rows=10, dataSourceRows=10,
            hasDataSourceColumn=True, hasDriveIdColumn=True,
        )

    def _cleanReport(self) -> ts.StateReport:
        return ts.StateReport(
            piTables=[self._goodPiTable(n) for n in ts.PI_TABLES],
            serverTables=[self._goodServerTable(n) for n in ts.SERVER_TABLES],
            piDriveCounterLast=0,
            serverHasDriveCounter=True,
            serverDriveCounterLast=0,
            fixtureShaMatches=True,
            fixtureSha=ts.FIXTURE_EXPECTED_SHA256,
            fixtureBytes=ts.FIXTURE_EXPECTED_BYTES,
        )

    def test_divergenceDetected_allGood_returnsEmpty(self):
        assert ts.divergenceDetected(self._cleanReport()) == []

    def test_divergenceDetected_alertLogMissingDataSource_notCountedAsDivergence(self):
        report = self._cleanReport()
        # alert_log is intentionally excluded from CAPTURE_TABLES per
        # data_source.py; spec carve-out mirrored here.  US-209 honored
        # the same carve-out on the server mirror so both sides lack the
        # column (per Spool amendment 2 2026-04-20).
        for t in report.piTables:
            if t.name == 'alert_log':
                t.hasDataSourceColumn = False
                t.dataSourceRows = None
        for t in report.serverTables:
            if t.name == 'alert_log':
                t.hasDataSourceColumn = False
                t.dataSourceRows = None
        assert ts.divergenceDetected(report) == []

    def test_divergenceDetected_serverMissingDataSource_flagged(self):
        report = self._cleanReport()
        for t in report.serverTables:
            if t.name == 'realtime_data':
                t.hasDataSourceColumn = False
                t.dataSourceRows = None
        reasons = ts.divergenceDetected(report)
        assert any('Server realtime_data missing data_source' in r for r in reasons)

    def test_divergenceDetected_serverMissingDriveId_flagged(self):
        report = self._cleanReport()
        for t in report.serverTables:
            if t.name == 'connection_log':
                t.hasDriveIdColumn = False
        reasons = ts.divergenceDetected(report)
        assert any('Server connection_log missing drive_id' in r for r in reasons)

    def test_divergenceDetected_serverMissingDriveCounter_flagged(self):
        report = self._cleanReport()
        report.serverHasDriveCounter = False
        reasons = ts.divergenceDetected(report)
        assert any('drive_counter table' in r for r in reasons)

    def test_divergenceDetected_fixtureHashMismatch_flagged(self):
        report = self._cleanReport()
        report.fixtureShaMatches = False
        report.fixtureSha = 'deadbeef' + '0' * 56
        reasons = ts.divergenceDetected(report)
        assert any('SHA-256 mismatch' in r for r in reasons)


# ================================================================================
# Pi table scan (mocked runner)
# ================================================================================

class TestScanPiState:
    def _addrs(self) -> ts.HostAddresses:
        return ts.HostAddresses(
            piHost='10.1.1.1', piUser='u', piPath='/p',
            piPort='22', serverHost='10.2.2.2', serverUser='u',
        )

    def test_scanPiState_realtimeData_reportsDataSourceCountsAndRange(self):
        # PRAGMA response containing data_source + drive_id.
        pragma = (
            '0|id|INTEGER|0||1\n'
            '1|timestamp|TEXT|0||0\n'
            '2|data_source|TEXT|1|\'real\'|0\n'
            '3|drive_id|INTEGER|0||0\n'
        )

        def runner(argv, *, input=None, timeout=None):  # noqa: A002
            sql = input or ''
            if 'PRAGMA table_info(realtime_data)' in sql:
                return _ok(stdout=pragma)
            if "WHERE data_source='real'" in sql and 'realtime_data' in sql:
                return _ok(stdout='12345\n')
            if 'SELECT COUNT(*) FROM realtime_data;' in sql:
                return _ok(stdout='20000\n')
            if 'SELECT MIN(timestamp)' in sql and 'realtime_data' in sql:
                return _ok(stdout='2026-04-19 07:18:50|2026-04-20 19:00:00\n')
            if 'PRAGMA table_info' in sql:
                # Other tables -> no data_source, minimal columns.
                return _ok(stdout='0|id|INTEGER|0||1\n')
            if 'SELECT COUNT(*)' in sql:
                return _ok(stdout='0\n')
            if 'SELECT last_drive_id' in sql:
                return _ok(stdout='7\n')
            return _ok(stdout='')

        piTables, counter = ts.scanPiState(self._addrs(), runner)
        rt = next(t for t in piTables if t.name == 'realtime_data')
        assert rt.rows == 20000
        assert rt.dataSourceRows == 12345
        assert rt.hasDataSourceColumn is True
        assert rt.hasDriveIdColumn is True
        assert rt.earliestTs == '2026-04-19 07:18:50'
        assert rt.latestTs == '2026-04-20 19:00:00'
        assert counter == 7


# ================================================================================
# Report rendering (smoke)
# ================================================================================

class TestRenderReport:
    def test_renderReport_includesSectionsAndDivergence(self):
        report = ts.StateReport(
            piTables=[
                ts.TableState(
                    name='realtime_data', rows=100, dataSourceRows=50,
                    hasDataSourceColumn=True, hasDriveIdColumn=True,
                    earliestTs='2026-04-19 00:00', latestTs='2026-04-20 12:00',
                ),
                ts.TableState(
                    name='alert_log', rows=5, dataSourceRows=None,
                    hasDataSourceColumn=False, hasDriveIdColumn=True,
                ),
            ],
            serverTables=[
                ts.TableState(
                    name='realtime_data', rows=100, dataSourceRows=None,
                    hasDataSourceColumn=False, hasDriveIdColumn=False,
                ),
            ],
            piDriveCounterLast=1,
            serverHasDriveCounter=False,
            fixtureShaMatches=True,
            fixtureSha=ts.FIXTURE_EXPECTED_SHA256,
            fixtureBytes=ts.FIXTURE_EXPECTED_BYTES,
            aiRecsWindowCount=0,
            calibSessionsWindowCount=0,
            divergenceReasons=['demo reason'],
        )
        text = ts.renderReport(report)
        assert 'Pi tables' in text
        assert 'Server tables' in text
        assert 'Orphan scan' in text
        assert 'Regression fixture' in text
        assert 'DIVERGENCE DETECTED' in text
        assert 'demo reason' in text
        # alert_log ABSENT marker visible:
        assert 'data_source column ABSENT' in text
        # Ranges rendered:
        assert '2026-04-19 00:00' in text


# ================================================================================
# CLI safety gates (main)
# ================================================================================

class TestMainSafetyGates:
    def _patchMain(
        self, monkeypatch: pytest.MonkeyPatch, report: ts.StateReport,
    ) -> None:
        monkeypatch.setattr(
            ts, 'loadAddresses',
            lambda path, runner=None: ts.HostAddresses(
                piHost='1', piUser='u', piPath='/p', piPort='22',
                serverHost='2', serverUser='u',
            ),
        )
        monkeypatch.setattr(
            ts, 'loadServerCreds',
            lambda addrs, runner=None: ts.ServerCreds(
                dbUser='u', dbPassword='p', dbName='db',
            ),
        )
        monkeypatch.setattr(
            ts, '_buildReport',
            lambda addrs, creds, runner, projectRoot: report,
        )

    def test_main_dryRun_noDivergence_exitZero_andWritesSentinel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ):
        report = ts.StateReport(
            fixtureShaMatches=True, fixtureSha=ts.FIXTURE_EXPECTED_SHA256,
            fixtureBytes=ts.FIXTURE_EXPECTED_BYTES,
            serverHasDriveCounter=True,
        )
        self._patchMain(monkeypatch, report)
        rc = ts.main(['--dry-run', '--project-root', str(tmp_path)])
        assert rc == 0
        sentinel = tmp_path / ts.DRY_RUN_SENTINEL_NAME
        assert sentinel.exists()

    def test_main_executeWithoutSentinel_exitsTwo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ):
        report = ts.StateReport(
            fixtureShaMatches=True, fixtureSha=ts.FIXTURE_EXPECTED_SHA256,
            fixtureBytes=ts.FIXTURE_EXPECTED_BYTES,
            serverHasDriveCounter=True,
        )
        self._patchMain(monkeypatch, report)
        rc = ts.main(['--execute', '--project-root', str(tmp_path)])
        assert rc == 2
        err = capsys.readouterr().err
        assert 'requires a prior successful --dry-run' in err

    def test_main_executeWithDivergence_exitsThree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ):
        # Pre-write a sentinel so the dry-run gate passes, then inject
        # a divergence-flagged report so --execute exits 3 (not 2).
        (tmp_path / ts.DRY_RUN_SENTINEL_NAME).write_text('ok', encoding='utf-8')
        report = ts.StateReport(
            fixtureShaMatches=True, fixtureSha=ts.FIXTURE_EXPECTED_SHA256,
            fixtureBytes=ts.FIXTURE_EXPECTED_BYTES,
            serverHasDriveCounter=True,
            divergenceReasons=['Server realtime_data missing data_source column'],
        )
        self._patchMain(monkeypatch, report)
        rc = ts.main(['--execute', '--project-root', str(tmp_path)])
        assert rc == 3
        err = capsys.readouterr().err
        assert 'refusing --execute' in err
        assert 'Server realtime_data missing data_source' in err

    def test_main_dryRunAndExecute_mutuallyExclusive(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            ts.main([
                '--dry-run', '--execute', '--project-root', str(tmp_path),
            ])


# ================================================================================
# Service-state preservation (Spool amendment 3 hygiene fix)
# ================================================================================

class TestRunExecuteServiceState:
    """--execute must RESTORE, not force-start, the Pi service.

    If the operator stopped the service before running --execute (to keep
    the clean-slate state through multiple runs, or because first-drive
    is imminent), the finally block must NOT restart it.  Otherwise
    every --execute race-repopulates via the benchtest hygiene bug
    (Spool amendment 3, 2026-04-20).
    """

    def _addrs(self) -> ts.HostAddresses:
        return ts.HostAddresses(
            piHost='10.1.1.1', piUser='a', piPath='/p', piPort='22',
            serverHost='10.2.2.2', serverUser='b',
        )

    def _creds(self) -> ts.ServerCreds:
        return ts.ServerCreds(dbUser='u', dbPassword='p', dbName='d')

    def _reportWithTables(self) -> ts.StateReport:
        return ts.StateReport(
            piTables=[
                ts.TableState(
                    name='realtime_data', rows=5, dataSourceRows=5,
                    hasDataSourceColumn=True, hasDriveIdColumn=True,
                ),
            ],
            serverTables=[
                ts.TableState(
                    name='realtime_data', rows=5, dataSourceRows=5,
                    hasDataSourceColumn=True, hasDriveIdColumn=True,
                ),
            ],
            fixtureShaMatches=True,
            fixtureSha=ts.FIXTURE_EXPECTED_SHA256,
            fixtureBytes=ts.FIXTURE_EXPECTED_BYTES,
            serverHasDriveCounter=True,
        )

    def _runnerFor(self, *, serviceActive: bool) -> FakeRunner:
        # Must answer the is-active probe + swallow everything else OK.
        return FakeRunner(
            responses=[
                ('systemctl is-active',
                 _ok(stdout='active\n' if serviceActive else 'inactive\n')),
            ],
        )

    def test_runExecute_whenServiceWasInactive_doesNotRestart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        # Sentinel pretend already written by an earlier dry-run.
        (tmp_path / ts.DRY_RUN_SENTINEL_NAME).write_text('ok', encoding='utf-8')
        # Make the fixture-hash check happy without touching real files.
        monkeypatch.setattr(
            ts, 'verifyFixtureHash',
            lambda _root: (True, ts.FIXTURE_EXPECTED_SHA256,
                           ts.FIXTURE_EXPECTED_BYTES),
        )
        runner = self._runnerFor(serviceActive=False)
        rc = ts._runExecute(
            self._addrs(), self._creds(), runner, tmp_path,
            self._reportWithTables(),
        )
        assert rc == 0
        starts = [
            c for c in runner.calls
            if 'systemctl start eclipse-obd.service' in ' '.join(c['argv'])
        ]
        assert starts == [], (
            'finally block restarted a service that was already stopped'
        )

    def test_runExecute_whenServiceWasActive_restartsIt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ):
        (tmp_path / ts.DRY_RUN_SENTINEL_NAME).write_text('ok', encoding='utf-8')
        monkeypatch.setattr(
            ts, 'verifyFixtureHash',
            lambda _root: (True, ts.FIXTURE_EXPECTED_SHA256,
                           ts.FIXTURE_EXPECTED_BYTES),
        )
        runner = self._runnerFor(serviceActive=True)
        rc = ts._runExecute(
            self._addrs(), self._creds(), runner, tmp_path,
            self._reportWithTables(),
        )
        assert rc == 0
        starts = [
            c for c in runner.calls
            if 'systemctl start eclipse-obd.service' in ' '.join(c['argv'])
        ]
        assert len(starts) == 1, (
            'finally block must restore a service that was previously active'
        )


# ================================================================================
# Sentinel round-trip
# ================================================================================

class TestSentinelRoundTrip:
    def test_writeThenReadSentinel_recoversKeys(self, tmp_path: Path):
        report = ts.StateReport(
            fixtureSha='abc', divergenceReasons=['x', 'y'],
        )
        ts._writeSentinel(tmp_path, report)
        parsed = ts._readSentinel(tmp_path)
        assert parsed is not None
        assert parsed['fixtureSha'] == 'abc'

    def test_readSentinel_missing_returnsNone(self, tmp_path: Path):
        assert ts._readSentinel(tmp_path) is None
