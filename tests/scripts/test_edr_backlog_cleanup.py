################################################################################
# File Name: test_edr_backlog_cleanup.py
# Purpose/Description: TDD tests for scripts/edr_backlog_cleanup.py (US-769).
#                      Pins dry-run-by-default, per-day per-table kept/deleted
#                      counts, drive-event-only keep windows with their pads and
#                      the unmatched-start extension, the refusal on a
#                      non-canonical drive event, the verified backup before
#                      --apply, and idempotency.
# Author: Rex (US-769)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-769) | Initial -- one-time EDR backlog cleanup tests.
# ================================================================================
################################################################################

"""TDD tests for the US-769 one-time EDR backlog cleanup script."""

from __future__ import annotations

import datetime as _dt
import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / 'scripts' / 'edr_backlog_cleanup.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location('edr_backlog_cleanup', _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['edr_backlog_cleanup'] = mod
    spec.loader.exec_module(mod)
    return mod


ebc = _loadScript()

_UTC = _dt.UTC


def _dtUtc(text: str) -> _dt.datetime:
    return _dt.datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=_UTC)


# ================================================================================
# Fixture DB: the real Pi DDL for the EDR tables, a minimal connection_log
# ================================================================================

def _createDb(path: Path) -> None:
    from common.edr.sensor_schema import EDR_INDEXES, EDR_SCHEMAS

    conn = sqlite3.connect(path)
    try:
        for _, ddl in EDR_SCHEMAS:
            conn.execute(ddl)
        for _, ddl in EDR_INDEXES:
            conn.execute(ddl)
        conn.execute(
            'CREATE TABLE connection_log ('
            ' id INTEGER PRIMARY KEY AUTOINCREMENT,'
            ' timestamp DATETIME NOT NULL,'
            ' event_type TEXT NOT NULL,'
            ' drive_id INTEGER)',
        )
        conn.commit()
    finally:
        conn.close()


def _addEvents(path: Path, events: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            'INSERT INTO connection_log (timestamp, event_type) VALUES (?, ?)', events,
        )
        conn.commit()
    finally:
        conn.close()


def _addImu(path: Path, timestamps: list[str]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            'INSERT INTO edr_imu_sample (ts_utc, ts_capture, seq) VALUES (?, 0.0, ?)',
            [(ts, i) for i, ts in enumerate(timestamps)],
        )
        conn.commit()
    finally:
        conn.close()


def _addLight(path: Path, timestamps: list[str]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            'INSERT INTO edr_light_sample (ts_utc, ts_capture, seq) VALUES (?, 0.0, ?)',
            [(ts, i) for i, ts in enumerate(timestamps)],
        )
        conn.commit()
    finally:
        conn.close()


def _timestamps(path: Path, table: str) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute(f'SELECT ts_utc FROM {table} ORDER BY ts_utc')]  # noqa: S608
    finally:
        conn.close()


def _count(path: Path, table: str) -> int:
    return len(_timestamps(path, table))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# One drive 16:32:57 -> 16:35:21 => keep window [16:31:57, 16:40:21].
_DRIVE = [('2026-09-14T16:32:57Z', 'drive_start'), ('2026-09-14T16:35:21Z', 'drive_end')]
_IMU_ROWS = [
    '2026-09-13T09:00:00Z',  # previous day, outside -> delete
    '2026-09-14T15:00:00Z',  # outside -> delete
    '2026-09-14T16:31:56Z',  # one second before the pad -> delete
    '2026-09-14T16:31:57Z',  # exactly start - 60 s -> keep
    '2026-09-14T16:34:00Z',  # inside -> keep
    '2026-09-14T16:40:21Z',  # exactly end + 300 s -> keep
    '2026-09-14T16:40:22Z',  # one second after the pad -> delete
]
_LIGHT_ROWS = ['2026-09-14T16:33:00Z', '2026-09-14T20:00:00Z']


@pytest.fixture
def seededDb(tmp_path: Path) -> Path:
    path = tmp_path / 'obd.db'
    _createDb(path)
    _addEvents(path, _DRIVE)
    _addImu(path, _IMU_ROWS)
    _addLight(path, _LIGHT_ROWS)
    return path


# ================================================================================
# keepWindows -- pads, pairing, unmatched starts
# ================================================================================

class TestKeepWindows:
    def test_pairedDrive_padsStartBy60AndEndBy300(self):
        windows = ebc.keepWindows([
            ebc.DriveEvent(1, _dtUtc('2026-09-14T16:32:57Z'), 'drive_start'),
            ebc.DriveEvent(2, _dtUtc('2026-09-14T16:35:21Z'), 'drive_end'),
        ])

        assert len(windows) == 1
        assert windows[0].start == _dtUtc('2026-09-14T16:31:57Z')
        assert windows[0].end == _dtUtc('2026-09-14T16:40:21Z')
        assert windows[0].unmatched is False

    def test_unmatchedStart_extendsToNextStartWhenSooner(self):
        windows = ebc.keepWindows([
            ebc.DriveEvent(1, _dtUtc('2026-09-14T10:00:00Z'), 'drive_start'),
            ebc.DriveEvent(2, _dtUtc('2026-09-14T11:00:00Z'), 'drive_start'),
            ebc.DriveEvent(3, _dtUtc('2026-09-14T11:30:00Z'), 'drive_end'),
        ])

        assert windows[0].unmatched is True
        assert windows[0].end == _dtUtc('2026-09-14T11:00:00Z')
        assert windows[1].unmatched is False
        assert windows[1].end == _dtUtc('2026-09-14T11:35:00Z')

    def test_unmatchedStart_extendsTwoHoursWhenNextStartIsLater(self):
        windows = ebc.keepWindows([
            ebc.DriveEvent(1, _dtUtc('2026-09-14T10:00:00Z'), 'drive_start'),
            ebc.DriveEvent(2, _dtUtc('2026-09-14T15:00:00Z'), 'drive_start'),
        ])

        assert windows[0].end == _dtUtc('2026-09-14T12:00:00Z')
        assert windows[1].end == _dtUtc('2026-09-14T17:00:00Z')
        assert all(w.unmatched for w in windows)

    def test_sameSecondStartAndEnd_pairInIdOrder(self):
        windows = ebc.keepWindows([
            ebc.DriveEvent(2, _dtUtc('2026-09-14T10:00:00Z'), 'drive_end'),
            ebc.DriveEvent(1, _dtUtc('2026-09-14T10:00:00Z'), 'drive_start'),
        ])

        assert len(windows) == 1
        assert windows[0].unmatched is False


# ================================================================================
# Dry run is the default and writes nothing
# ================================================================================

class TestDryRun:
    def test_noApply_leavesRowCountsAndBytesIdentical(self, seededDb: Path, capsys):
        imuBefore = _count(seededDb, 'edr_imu_sample')
        lightBefore = _count(seededDb, 'edr_light_sample')
        shaBefore = _sha256(seededDb)

        rc = ebc.main(['--db', str(seededDb)])

        assert rc == 0
        assert _count(seededDb, 'edr_imu_sample') == imuBefore
        assert _count(seededDb, 'edr_light_sample') == lightBefore
        assert _sha256(seededDb) == shaBefore
        assert 'DRY-RUN' in capsys.readouterr().out
        assert list(seededDb.parent.glob('*.bak-us769-*')) == []

    def test_output_carriesKeptAndDeletedPerDayPerTable(self, seededDb: Path, capsys):
        ebc.main(['--db', str(seededDb)])

        out = capsys.readouterr().out
        assert 'edr_imu_sample 2026-09-13 kept=0 deleted=1' in out
        assert 'edr_imu_sample 2026-09-14 kept=3 deleted=3' in out
        assert 'edr_light_sample 2026-09-14 kept=1 deleted=1' in out

    def test_planCleanup_countsPerTablePerDay(self, seededDb: Path):
        conn = sqlite3.connect(seededDb)
        try:
            windows = ebc.keepWindows(ebc.readDriveEvents(conn))
            plan = ebc.planCleanup(conn, windows)
        finally:
            conn.close()

        assert plan['edr_imu_sample'] == {
            '2026-09-13': ebc.DayCounts(kept=0, deleted=1),
            '2026-09-14': ebc.DayCounts(kept=3, deleted=3),
        }
        assert plan['edr_light_sample'] == {'2026-09-14': ebc.DayCounts(kept=1, deleted=1)}

    def test_unmatchedStart_isPrintedOnTheRun(self, tmp_path: Path, capsys):
        path = tmp_path / 'obd.db'
        _createDb(path)
        _addEvents(path, [('2026-09-14T10:00:00Z', 'drive_start')])

        rc = ebc.main(['--db', str(path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert 'UNMATCHED drive_start' in out
        assert '2026-09-14T10:00:00Z' in out
        assert '2026-09-14T12:00:00Z' in out


# ================================================================================
# Keep windows come only from canonical drive events
# ================================================================================

class TestDriveEventShape:
    @pytest.mark.parametrize(
        'badTimestamp',
        ['2026-09-14 16:32:57', '2026-09-14T16:32:57.123Z', '2026-09-14T16:32:57+00:00',
         '2026-13-14T16:32:57Z'],
    )
    def test_nonCanonicalDriveEvent_exitsNonZeroAndDeletesNothing(
        self, seededDb: Path, badTimestamp: str, capsys,
    ):
        _addEvents(seededDb, [(badTimestamp, 'drive_end')])
        shaBefore = _sha256(seededDb)

        rc = ebc.main(['--db', str(seededDb), '--apply'])

        captured = capsys.readouterr()
        assert rc != 0
        assert _sha256(seededDb) == shaBefore
        assert _timestamps(seededDb, 'edr_imu_sample') == sorted(_IMU_ROWS)
        assert repr(badTimestamp) in captured.err
        assert list(seededDb.parent.glob('*.bak-us769-*')) == []

    def test_nonCanonicalLinkEvent_isIgnoredAndMakesNoWindow(self, seededDb: Path):
        # Link events are stored in two timestamp formats; they never feed windows.
        _addEvents(seededDb, [
            ('2026-09-14 15:00:00', 'connect_success'),
            ('2026-09-14T15:00:00Z', 'reconnect'),
        ])
        conn = sqlite3.connect(seededDb)
        try:
            events = ebc.readDriveEvents(conn)
        finally:
            conn.close()

        assert [e.eventType for e in events] == ['drive_start', 'drive_end']

    def test_nonCanonicalEdrTimestamp_exitsNonZeroAndDeletesNothing(self, seededDb: Path, capsys):
        _addImu(seededDb, ['2026-09-14 16:34:00'])
        shaBefore = _sha256(seededDb)

        rc = ebc.main(['--db', str(seededDb), '--apply'])

        assert rc != 0
        assert _sha256(seededDb) == shaBefore
        assert 'edr_imu_sample' in capsys.readouterr().err


# ================================================================================
# --apply: verified backup first, deletes only outside windows, idempotent
# ================================================================================

class TestApply:
    def test_apply_deletesOnlyRowsOutsideEveryWindow(self, seededDb: Path):
        rc = ebc.main(['--db', str(seededDb), '--apply'])

        assert rc == 0
        assert _timestamps(seededDb, 'edr_imu_sample') == [
            '2026-09-14T16:31:57Z', '2026-09-14T16:34:00Z', '2026-09-14T16:40:21Z',
        ]
        assert _timestamps(seededDb, 'edr_light_sample') == ['2026-09-14T16:33:00Z']

    def test_apply_writesAReadableBackupHoldingTheOriginalRows(self, seededDb: Path):
        ebc.main(['--db', str(seededDb), '--apply'])

        backups = list(seededDb.parent.glob('obd.db.bak-us769-*'))
        assert len(backups) == 1
        assert _timestamps(backups[0], 'edr_imu_sample') == sorted(_IMU_ROWS)

    def test_apply_thenDryRun_reportsZeroToDelete(self, seededDb: Path, capsys):
        ebc.main(['--db', str(seededDb), '--apply'])
        capsys.readouterr()

        rc = ebc.main(['--db', str(seededDb)])

        out = capsys.readouterr().out
        assert rc == 0
        assert 'total edr_imu_sample kept=3 deleted=0' in out
        assert 'total edr_light_sample kept=1 deleted=0' in out

    def test_backupThatCannotBeReRead_exitsNonZeroAndDeletesNothing(
        self, seededDb: Path, monkeypatch,
    ):
        def _unreadable(backupPath: Path, expected: list) -> None:
            raise ebc.BackupVerificationError(f'cannot re-read {backupPath}')

        monkeypatch.setattr(ebc, 'verifyBackup', _unreadable)

        rc = ebc.main(['--db', str(seededDb), '--apply'])

        assert rc != 0
        assert _timestamps(seededDb, 'edr_imu_sample') == sorted(_IMU_ROWS)

    def test_verifyBackup_rejectsACopyWhoseDriveWindowsDiffer(self, seededDb: Path, tmp_path: Path):
        conn = sqlite3.connect(seededDb)
        try:
            windows = ebc.keepWindows(ebc.readDriveEvents(conn))
        finally:
            conn.close()
        other = tmp_path / 'other.db'
        _createDb(other)

        with pytest.raises(ebc.BackupVerificationError):
            ebc.verifyBackup(other, windows)

    def test_noDriveEvents_everyRowIsOutsideAWindow(self, tmp_path: Path, capsys):
        path = tmp_path / 'obd.db'
        _createDb(path)
        _addImu(path, ['2026-09-14T16:34:00Z'])

        rc = ebc.main(['--db', str(path)])

        out = capsys.readouterr().out
        assert rc == 0
        assert 'keep windows: 0' in out
        assert 'edr_imu_sample 2026-09-14 kept=0 deleted=1' in out


class TestMissingInputs:
    def test_missingDb_exitsNonZero(self, tmp_path: Path):
        assert ebc.main(['--db', str(tmp_path / 'absent.db')]) != 0
