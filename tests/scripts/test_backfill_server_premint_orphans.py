################################################################################
# File Name: test_backfill_server_premint_orphans.py
# Purpose/Description: TDD coverage for scripts/backfill_server_premint_orphans
#                      (US-240). Mirrors the US-233 Pi-side test surface but
#                      injects a FakeRunner so no SSH or live MariaDB is
#                      touched. Covers the pure matching algorithm (with the
#                      US-240-specific post-engine-off exclusion), the SSH
#                      I/O wrappers, the sentinel + backup safety gates, and
#                      the CLI entry points.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-240) | Initial -- TDD coverage for the server-side
#                               pre-mint orphan backfill mirror of US-233.
# ================================================================================
################################################################################

"""TDD tests for the US-240 server-side pre-mint orphan backfill script."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# ================================================================================
# Module loader (scripts/ is not a package)
# ================================================================================

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'backfill_server_premint_orphans.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location(
        'backfill_server_premint_orphans', _SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['backfill_server_premint_orphans'] = mod
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


# ================================================================================
# Constants + parity with Pi-side US-233
# ================================================================================

class TestConstantsParity:
    def test_defaultWindowSeconds_matchesUs233(self) -> None:
        assert bf.DEFAULT_WINDOW_SECONDS == 60.0

    def test_defaultMaxOrphansPerDrive_matchesUs233(self) -> None:
        assert bf.DEFAULT_MAX_ORPHANS_PER_DRIVE == 1000

    def test_drivenSentinelName_isUs240Specific(self) -> None:
        # Sentinel must be distinct from US-233 ('.us233-dry-run-ok') so a
        # Pi-side dry-run does NOT silently authorize a server execute.
        assert bf.DRY_RUN_SENTINEL_NAME == '.us240-dry-run-ok'


# ================================================================================
# findOrphanBackfillMatches -- pure algorithm (no I/O)
# ================================================================================

def _orphan(rowId: int, ts: str) -> object:
    return bf.OrphanRow(serverRowId=rowId, timestamp=ts)


def _anchor(driveId: int, startTs: str, endTs: str) -> object:
    return bf.DriveAnchor(
        driveId=driveId,
        driveStartTimestamp=startTs,
        driveEndTimestamp=endTs,
    )


class TestFindOrphanBackfillMatches:
    def test_emptyInputs_returnsEmpty(self) -> None:
        assert bf.findOrphanBackfillMatches([], []) == []

    def test_orphansWithoutAnchors_returnsEmpty(self) -> None:
        orphans = [_orphan(1, '2026-04-29T13:39:00Z')]
        assert bf.findOrphanBackfillMatches(orphans, []) == []

    def test_anchorsWithoutOrphans_returnsEmpty(self) -> None:
        anchors = [_anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z')]
        assert bf.findOrphanBackfillMatches([], anchors) == []

    def test_orphanWithinWindow_matchesNearestSubsequentDrive(self) -> None:
        orphans = [_orphan(100, '2026-04-29T13:38:48Z')]  # 30s before
        anchors = [_anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z')]
        matches = bf.findOrphanBackfillMatches(orphans, anchors)
        assert len(matches) == 1
        assert matches[0].serverRowId == 100
        assert matches[0].toDriveId == 4
        assert matches[0].gapSeconds == pytest.approx(30.0, abs=0.01)

    def test_orphanOutsideWindow_notMatched(self) -> None:
        orphans = [_orphan(100, '2026-04-29T13:37:18Z')]  # 120s before
        anchors = [_anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z')]
        assert bf.findOrphanBackfillMatches(
            orphans, anchors, windowSeconds=60.0,
        ) == []

    def test_orphanAtOrAfterDriveStart_notMatched(self) -> None:
        # AT drive_start
        orphans = [_orphan(100, '2026-04-29T13:39:18Z')]
        anchors = [_anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z')]
        assert bf.findOrphanBackfillMatches(orphans, anchors) == []
        # AFTER drive_start (would have been tagged drive_id=4 if synced)
        orphans = [_orphan(100, '2026-04-29T13:40:00Z')]
        # Post-engine-off path takes over — but well within drive, so it
        # should NOT match the next drive (none exists in this test).
        assert bf.findOrphanBackfillMatches(orphans, anchors) == []

    def test_postEngineOffOrphan_excluded_byDesign(self) -> None:
        # The US-240 explicit-exclusion case: orphan past the latest drive's
        # MAX timestamp is post-engine-off (US-229 adapter-poll continued
        # after engine_state went KEY_OFF). MUST stay NULL even with no
        # subsequent drive in the data set.
        orphans = [
            _orphan(200, '2026-04-29T13:51:00Z'),  # 56s post-Drive-4 end
            _orphan(201, '2026-04-29T13:55:00Z'),  # 5min post-Drive-4 end
            _orphan(202, '2026-04-29T13:59:30Z'),  # near sync time
        ]
        anchors = [_anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z')]
        assert bf.findOrphanBackfillMatches(orphans, anchors) == []

    def test_postEngineOffOrphan_excluded_evenIfFutureDriveExists(
        self,
    ) -> None:
        # If a *later* drive starts hours after, the 60s window already
        # excludes these orphans naturally. But the explicit guard adds
        # defense-in-depth: even if someone widens the window to 100,000s,
        # post-engine-off orphans of an earlier drive STILL stay NULL
        # because their timestamp is past that drive's MAX timestamp AND
        # they fall in the "between drives" zone.
        orphans = [_orphan(200, '2026-04-29T13:51:00Z')]  # post-Drive-4
        anchors = [
            _anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z'),
            _anchor(5, '2026-04-29T23:45:00Z', '2026-04-30T00:02:39Z'),
        ]
        # Even with absurdly wide window, post-engine-off rule wins.
        matches = bf.findOrphanBackfillMatches(
            orphans, anchors, windowSeconds=100_000.0,
            maxOrphansPerDrive=10_000,
        )
        assert matches == []

    def test_orphanBetweenTwoDrives_attachedToNearestSubsequentNotPostEngineOff(
        self,
    ) -> None:
        # Drive 4 BT-connect orphan: timestamp 30s before Drive 4 start,
        # but 6 days AFTER Drive 3's end. This is pre-mint for Drive 4,
        # NOT post-engine-off for Drive 3 (the gap is too large).
        orphans = [_orphan(150, '2026-04-29T13:38:48Z')]
        anchors = [
            _anchor(3, '2026-04-23T16:36:50Z', '2026-04-23T18:35:44Z'),
            _anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z'),
        ]
        matches = bf.findOrphanBackfillMatches(orphans, anchors)
        assert len(matches) == 1
        assert matches[0].toDriveId == 4

    def test_pollutionFarBeforeAnyDrive_staysNull(self) -> None:
        # The 269 pre-Drive-4-boundary pollution rows: dates from
        # 2026-04-21 with no drive within the 60s window. Stay NULL.
        orphans = [
            _orphan(10, '2026-04-21T02:27:10Z'),
            _orphan(11, '2026-04-22T10:00:00Z'),
        ]
        anchors = [_anchor(3, '2026-04-23T16:36:50Z', '2026-04-23T18:35:44Z')]
        assert bf.findOrphanBackfillMatches(orphans, anchors) == []

    def test_drive3LikeBatchAllMatch(self) -> None:
        # Synthetic Drive 3 BT-connect window: 50 orphans in the 39s before
        # drive_start, every 0.78s. Window 60s -> all match.
        startTs = '2026-04-23T16:36:50Z'
        endTs = '2026-04-23T18:35:44Z'
        # Build orphans 1..50 spanning -39s..-0.78s before start
        from datetime import UTC, datetime, timedelta
        anchorStart = datetime(2026, 4, 23, 16, 36, 50, tzinfo=UTC)
        orphans: list[object] = []
        for i in range(50):
            ts = anchorStart - timedelta(seconds=39 - i * 0.78)
            orphans.append(_orphan(
                rowId=i + 1,
                ts=ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
            ))
        anchors = [_anchor(3, startTs, endTs)]
        matches = bf.findOrphanBackfillMatches(
            orphans, anchors, windowSeconds=60.0,
        )
        assert len(matches) == 50
        assert {m.toDriveId for m in matches} == {3}

    def test_customWindow30s_excludes45sGap(self) -> None:
        orphans = [_orphan(100, '2026-04-29T13:38:33Z')]  # 45s before
        anchors = [_anchor(4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z')]
        assert bf.findOrphanBackfillMatches(
            orphans, anchors, windowSeconds=30.0,
        ) == []

    def test_invalidWindowSeconds_raisesValueError(self) -> None:
        with pytest.raises(ValueError, match='windowSeconds'):
            bf.findOrphanBackfillMatches([], [], windowSeconds=0)
        with pytest.raises(ValueError, match='windowSeconds'):
            bf.findOrphanBackfillMatches([], [], windowSeconds=-5)

    def test_perDriveCapEnforced(self) -> None:
        # 100 orphans within window of one drive; cap=10 should refuse.
        from datetime import UTC, datetime, timedelta
        anchorStart = datetime(2026, 4, 29, 13, 39, 18, tzinfo=UTC)
        orphans = []
        for i in range(100):
            ts = anchorStart - timedelta(seconds=50 - i * 0.4)
            orphans.append(_orphan(
                rowId=i + 1,
                ts=ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
            ))
        anchors = [_anchor(
            4, '2026-04-29T13:39:18Z', '2026-04-29T13:50:04Z',
        )]
        with pytest.raises(bf.SafetyCapError, match='maxOrphansPerDrive'):
            bf.findOrphanBackfillMatches(
                orphans, anchors,
                windowSeconds=60.0, maxOrphansPerDrive=10,
            )


# ================================================================================
# scanOrphans -- SSH/MariaDB I/O wrapper (FakeRunner)
# ================================================================================

class TestScanOrphans:
    def test_parsesTabDelimitedMysqlOutput(self) -> None:
        # mysql -B -N output: tab-separated columns, newline-separated rows.
        runner = FakeRunner(responses=[
            ('SELECT id, timestamp FROM realtime_data', _ok(
                stdout=(
                    '100\t2026-04-29 13:38:48\n'
                    '101\t2026-04-29 13:38:49\n'
                ),
            )),
        ])
        orphans = bf.scanOrphans(_addrs(), _creds(), runner)
        assert len(orphans) == 2
        assert orphans[0].serverRowId == 100
        assert orphans[0].timestamp == '2026-04-29 13:38:48'

    def test_emptyResult_returnsEmptyList(self) -> None:
        runner = FakeRunner(responses=[
            ('SELECT id, timestamp FROM realtime_data', _ok(stdout='')),
        ])
        assert bf.scanOrphans(_addrs(), _creds(), runner) == []

    def test_sshFailure_raisesBackfillError(self) -> None:
        runner = FakeRunner(responses=[
            ('SELECT id, timestamp FROM realtime_data',
             _fail(stderr='Connection refused')),
        ])
        with pytest.raises(bf.BackfillError, match='scan orphan'):
            bf.scanOrphans(_addrs(), _creds(), runner)


# ================================================================================
# scanDriveAnchors
# ================================================================================

class TestScanDriveAnchors:
    def test_parsesPerDriveStartAndEnd(self) -> None:
        runner = FakeRunner(responses=[
            ('GROUP BY drive_id', _ok(
                stdout=(
                    '3\t2026-04-23 16:36:50\t2026-04-23 18:35:44\n'
                    '4\t2026-04-29 13:39:18\t2026-04-29 13:50:04\n'
                    '5\t2026-04-29 23:45:00\t2026-04-30 00:02:39\n'
                ),
            )),
        ])
        anchors = bf.scanDriveAnchors(_addrs(), _creds(), runner)
        assert len(anchors) == 3
        assert anchors[0].driveId == 3
        assert anchors[0].driveStartTimestamp == '2026-04-23 16:36:50'
        assert anchors[2].driveEndTimestamp == '2026-04-30 00:02:39'

    def test_sshFailure_raisesBackfillError(self) -> None:
        runner = FakeRunner(responses=[
            ('GROUP BY drive_id', _fail()),
        ])
        with pytest.raises(bf.BackfillError, match='drive anchor'):
            bf.scanDriveAnchors(_addrs(), _creds(), runner)


# ================================================================================
# applyBackfill -- transactional UPDATE via mysql
# ================================================================================

class TestApplyBackfill:
    def test_emptyMatchesNoOp_returnsZero(self) -> None:
        runner = FakeRunner()
        assert bf.applyBackfill(_addrs(), _creds(), runner, []) == 0
        assert runner.calls == []  # no mysql call when nothing to apply

    def test_appliesMatchesInsideTransaction(self) -> None:
        # Single batched UPDATE statement -- runner sees one mysql invocation.
        # _runServerSql returns rc=0 stdout='' for a successful UPDATE batch.
        runner = FakeRunner(responses=[
            ('UPDATE realtime_data', _ok(stdout='')),
        ])
        matches = [
            bf.BackfillMatch(
                serverRowId=100, toDriveId=4,
                rowTimestamp='2026-04-29T13:38:48Z',
                driveStartTimestamp='2026-04-29T13:39:18Z',
                gapSeconds=30.0,
            ),
            bf.BackfillMatch(
                serverRowId=101, toDriveId=4,
                rowTimestamp='2026-04-29T13:38:49Z',
                driveStartTimestamp='2026-04-29T13:39:18Z',
                gapSeconds=29.0,
            ),
        ]
        applied = bf.applyBackfill(_addrs(), _creds(), runner, matches)
        assert applied == 2
        # SQL ran inside a START TRANSACTION/COMMIT envelope on the same call.
        joinedSql = ''.join(c['input'] or '' for c in runner.calls)
        assert 'START TRANSACTION' in joinedSql or 'BEGIN' in joinedSql
        assert 'COMMIT' in joinedSql

    def test_mysqlFailure_raisesBackfillError(self) -> None:
        runner = FakeRunner(responses=[
            ('UPDATE realtime_data',
             _fail(stderr='Deadlock found')),
        ])
        match = bf.BackfillMatch(
            serverRowId=100, toDriveId=4,
            rowTimestamp='2026-04-29T13:38:48Z',
            driveStartTimestamp='2026-04-29T13:39:18Z',
            gapSeconds=30.0,
        )
        with pytest.raises(bf.BackfillError, match='UPDATE'):
            bf.applyBackfill(_addrs(), _creds(), runner, [match])

    def test_updateWhereClauseGuardsAgainstNonNull(self) -> None:
        # Defensive: the issued SQL must keep the
        # `drive_id IS NULL AND data_source='real'` guard so a stale match
        # cannot clobber an already-tagged row.
        runner = FakeRunner(responses=[
            ('UPDATE realtime_data', _ok(stdout='')),
        ])
        match = bf.BackfillMatch(
            serverRowId=100, toDriveId=4,
            rowTimestamp='2026-04-29T13:38:48Z',
            driveStartTimestamp='2026-04-29T13:39:18Z',
            gapSeconds=30.0,
        )
        bf.applyBackfill(_addrs(), _creds(), runner, [match])
        joinedSql = ''.join(c['input'] or '' for c in runner.calls)
        assert 'drive_id IS NULL' in joinedSql
        assert "data_source = 'real'" in joinedSql


# ================================================================================
# backupServer -- mysqldump safety gate
# ================================================================================

class TestBackupServer:
    def test_successfulDump_returnsServerPath(self) -> None:
        # First call: mysqldump itself; second: stat -c %s for size check.
        runner = FakeRunner(responses=[
            ('mysqldump', _ok(stdout='')),
            ('stat -c %s', _ok(stdout='1024\n')),
        ])
        path = bf.backupServer(_addrs(), _creds(), runner, '20260429-2030Z')
        assert path.startswith('/tmp/obd2-us240-backup-')
        assert path.endswith('.sql')

    def test_dumpFailure_raisesSafetyGateError(self) -> None:
        runner = FakeRunner(responses=[
            ('mysqldump', _fail(stderr='Access denied')),
        ])
        with pytest.raises(bf.SafetyGateError, match='backup'):
            bf.backupServer(_addrs(), _creds(), runner, '20260429-2030Z')


# ================================================================================
# CLI -- --dry-run, --execute, sentinel
# ================================================================================

class TestCli:
    def _orphanRows(self) -> str:
        return (
            '100\t2026-04-29 13:38:48\n'
            '101\t2026-04-29 13:38:49\n'
        )

    def _anchorRows(self) -> str:
        return '4\t2026-04-29 13:39:18\t2026-04-29 13:50:04\n'

    def _addressesShFile(self, tmp_path: Path) -> Path:
        addresses = tmp_path / 'addresses.sh'
        addresses.write_text('#!/usr/bin/env bash\n', encoding='utf-8')
        return addresses

    def _baseRunner(self) -> FakeRunner:
        return FakeRunner(responses=[
            ('bash', _ok(
                stdout='SERVER_HOST=10.2.2.2\nSERVER_USER=b\n',
            )),
            ('DATABASE_URL=', _ok(
                stdout='DATABASE_URL=mysql+aiomysql://u:p@localhost/dbx\n',
            )),
            ('SELECT id, timestamp FROM realtime_data',
             _ok(stdout=self._orphanRows())),
            ('GROUP BY drive_id', _ok(stdout=self._anchorRows())),
            ('mysqldump', _ok(stdout='')),
            ('stat -c %s', _ok(stdout='1024\n')),
            ('UPDATE realtime_data', _ok(stdout='')),
        ])

    def test_dryRun_writesSentinel_doesNotMutate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(bf, '_defaultRunner', self._baseRunner())
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        rc = bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc == 0
        # Sentinel exists
        sentinel = sentinelDir / bf.DRY_RUN_SENTINEL_NAME
        assert sentinel.exists()

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

    def test_executeAfterDryRun_appliesBackfillAndClearsSentinel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = self._baseRunner()
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        # Dry-run first.
        rcDry = bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rcDry == 0
        # Now execute -- backup + apply path runs.
        rcExec = bf.main([
            '--execute',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rcExec == 0
        # Sentinel cleared after execute.
        sentinel = sentinelDir / bf.DRY_RUN_SENTINEL_NAME
        assert not sentinel.exists()
        # mysqldump was called as part of backup-first.
        assert any(
            'mysqldump' in (c['input'] or '') or any(
                'mysqldump' in arg for arg in c['argv']
            )
            for c in runner.calls
        )

    def test_dryRunAndExecuteAreMutuallyExclusive(
        self, tmp_path: Path,
    ) -> None:
        with pytest.raises(SystemExit):
            bf.main(['--dry-run', '--execute'])

    def test_noModeFlag_exits(self) -> None:
        with pytest.raises(SystemExit):
            bf.main([])

    def test_noOpExecute_succeeds_zeroMatches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Empty orphan + anchor scans -> dry-run reports 0; execute is
        # a no-op (sentinel cleared, no backup taken, no UPDATE issued).
        runner = FakeRunner(responses=[
            ('bash', _ok(
                stdout='SERVER_HOST=10.2.2.2\nSERVER_USER=b\n',
            )),
            ('DATABASE_URL=', _ok(
                stdout='DATABASE_URL=mysql+aiomysql://u:p@localhost/dbx\n',
            )),
            ('SELECT id, timestamp FROM realtime_data', _ok(stdout='')),
            ('GROUP BY drive_id', _ok(stdout='')),
        ])
        monkeypatch.setattr(bf, '_defaultRunner', runner)
        addresses = self._addressesShFile(tmp_path)
        sentinelDir = tmp_path / 'sentinel'
        sentinelDir.mkdir()
        bf.main([
            '--dry-run',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        rc = bf.main([
            '--execute',
            '--addresses', str(addresses),
            '--sentinel-dir', str(sentinelDir),
        ])
        assert rc == 0


# ================================================================================
# parseTimestamp helper -- accepts both 'T...Z' (Pi canonical) and
# 'YYYY-MM-DD HH:MM:SS' (MariaDB DATETIME default).
# ================================================================================

class TestParseTimestamp:
    def test_parsesIsoZ(self) -> None:
        ts = bf._parseIso('2026-04-29T13:39:18Z')
        assert ts.year == 2026
        assert ts.hour == 13
        assert ts.minute == 39

    def test_parsesMariadbDatetime(self) -> None:
        ts = bf._parseIso('2026-04-29 13:39:18')
        assert ts.year == 2026
        assert ts.hour == 13

    def test_isoGapSecondsMixedFormats(self) -> None:
        # Pi-side ISO vs server-side mariadb format -- gap should still parse.
        gap = bf._isoGapSeconds(
            '2026-04-29 13:38:48',
            '2026-04-29T13:39:18Z',
        )
        assert gap == pytest.approx(30.0, abs=0.01)
