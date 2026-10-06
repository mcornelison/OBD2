################################################################################
# File Name: test_cleanup_orphan_delivery_bound.py
# Purpose/Description: US-838 -- orphan-cleanup deletes ONLY NULL-drive rows the
#                      server already has (id <= the realtime_data sync
#                      high-water mark), never by age alone; an unreadable or
#                      implausible mark deletes NOTHING; every run reports how
#                      many age-eligible rows were held back undelivered.
# Author: Atlas (architect)
# Creation Date: 2026-10-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-05    | Atlas        | US-838 (CIO-directed build, charter override).
#                               Pattern: the EDR retention purge
#                               (edr_persistence_subscriber.maybePurge).
# ================================================================================
################################################################################
"""US-838: retention gates on DELIVERY, never on age alone."""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

from src.pi.data import sync_log

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'cleanup_orphan_realtime_data.py'


def _loadScript():  # noqa: ANN202 -- test helper
    spec = importlib.util.spec_from_file_location('cleanup_orphan_realtime_data', _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules['cleanup_orphan_realtime_data'] = mod
    spec.loader.exec_module(mod)
    return mod


coc = _loadScript()

_NOW = _dt.datetime(2026, 10, 3, 3, 0, 0, tzinfo=_dt.UTC)


def _iso(ts: _dt.datetime) -> str:
    return ts.strftime('%Y-%m-%dT%H:%M:%SZ')


def _db(path: Path | str = ':memory:', *, now: _dt.datetime = _NOW) -> sqlite3.Connection:
    """realtime_data (real AUTOINCREMENT shape) + the REAL sync_log schema.

    ids 1-100: NULL drive, 48 h old   (the 24 h pass's class)
    ids 101-150: NULL drive, 6 h old  (the 4 h sweep's class -- the crank lead-ins)
    ids 151-160: drive 7, 72 h old    (tagged: never touched)

    ``now`` anchors the ages. ``main()`` reads the REAL clock, so its tests pass
    the real now -- a fixed anchor would make them depend on the date they run.
    """
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, '
        'timestamp DATETIME NOT NULL, parameter_name TEXT NOT NULL, value REAL NOT NULL, '
        'drive_id INTEGER)'
    )
    for count, driveId, ageHours in ((100, None, 48), (50, None, 6), (10, 7, 72)):
        ts = _iso(now - _dt.timedelta(hours=ageHours))
        conn.executemany(
            'INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id) VALUES (?,?,?,?)',
            [(ts, 'RPM', 1500.0 + i, driveId) for i in range(count)],
        )
    sync_log.initDb(conn)
    conn.commit()
    return conn


def _deliveredThrough(conn: sqlite3.Connection, lastId: int) -> None:
    sync_log.updateHighWaterMark(conn, 'realtime_data', lastId, 'test-batch')


def _ids(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute('SELECT id FROM realtime_data')}


# =============================================================================
# The defect: age alone authorised the delete
# =============================================================================


class TestDeletesOnlyWhatTheServerHas:

    def test_sweep_undeliveredLeadIn_isHeld(self) -> None:
        """
        Given: the 6 h-old NULL rows (ids 101-150) are NOT yet delivered
               (mark = 100), as on a car parked > 4 h away from home Wi-Fi
        When: the 4 h sweep executes
        Then: NONE of them is deleted, and they are reported as held.
              Against today's predicate (age only) all 50 are deleted.
        """
        conn = _db()
        _deliveredThrough(conn, 100)

        s = coc.runRecentOrphanSweep(conn, execute=True, nowFn=lambda: _NOW)

        assert set(range(101, 151)) <= _ids(conn)
        assert s.heldUndelivered == 50
        assert s.deliveryMark == 100

    def test_belowTheMark_isDeleted_aboveIsHeld(self) -> None:
        """Mark 120: NULL rows 1-120 that are old enough go; 121-150 stay."""
        conn = _db()
        _deliveredThrough(conn, 120)

        main = coc.runCleanup(conn, execute=True, nowFn=lambda: _NOW)
        sweep = coc.runRecentOrphanSweep(conn, execute=True, nowFn=lambda: _NOW)

        assert main.rowsDeleted == 100 and main.heldUndelivered == 0
        assert sweep.rowsDeleted == 20 and sweep.heldUndelivered == 30
        assert _ids(conn) == set(range(121, 161))

    def test_taggedRows_neverDeleted_evenWhenDelivered(self) -> None:
        conn = _db()
        _deliveredThrough(conn, 160)

        coc.runCleanup(conn, execute=True, nowFn=lambda: _NOW)
        coc.runRecentOrphanSweep(conn, execute=True, nowFn=lambda: _NOW)

        assert _ids(conn) == set(range(151, 161))

    def test_dryRun_reportsHeld_withoutDeleting(self) -> None:
        """The 4 h sweep also sees the 48 h rows: 100 delivered + eligible, 50 held."""
        conn = _db()
        _deliveredThrough(conn, 100)

        s = coc.runRecentOrphanSweep(conn, execute=False, nowFn=lambda: _NOW)

        assert (s.eligibleRowCount, s.heldUndelivered, s.rowsDeleted) == (100, 50, 0)
        assert len(_ids(conn)) == 160


# =============================================================================
# No readable mark => delete NOTHING (the EDR purge's rule)
# =============================================================================


class TestUnreadableMarkDeletesNothing:

    def test_neverSynced_markZero_deletesNothing(self) -> None:
        """No sync_log row yet (status 'pending', mark 0): nothing is delivered.
        The 24 h pass holds the 100 48 h rows; the 4 h sweep then holds all 150."""
        conn = _db()

        main = coc.runCleanup(conn, execute=True, nowFn=lambda: _NOW)
        sweep = coc.runRecentOrphanSweep(conn, execute=True, nowFn=lambda: _NOW)

        assert len(_ids(conn)) == 160
        assert (main.heldUndelivered, sweep.heldUndelivered) == (100, 150)

    def test_noSyncLogTable_deletesNothing_andSaysUnreadable(self) -> None:
        conn = _db()
        conn.execute('DROP TABLE sync_log')

        s = coc.runCleanup(conn, execute=True, nowFn=lambda: _NOW)

        assert len(_ids(conn)) == 160
        assert s.deliveryMark is None
        assert 'unreadable' in s.markNote
        assert s.heldUndelivered == 100

    def test_markAboveEveryIssuedId_isImplausible_deletesNothing(self) -> None:
        """
        A mark above the highest id the table EVER issued (sqlite_sequence) is the
        US-809 rebuild shape: `id <= mark` would then pass UNDELIVERED rows.
        """
        conn = _db()
        _deliveredThrough(conn, 5000)

        s = coc.runRecentOrphanSweep(conn, execute=True, nowFn=lambda: _NOW)

        assert len(_ids(conn)) == 160
        assert s.deliveryMark is None
        assert 'implausible' in s.markNote

    def test_markEqualToLastIssuedId_onAnEmptiedTable_isPlausible(self) -> None:
        """Every row delivered and purged: MAX(id) is NULL but sqlite_sequence remembers."""
        conn = _db()
        _deliveredThrough(conn, 160)
        conn.execute('DELETE FROM realtime_data')
        conn.commit()

        s = coc.runCleanup(conn, execute=True, nowFn=lambda: _NOW)

        assert s.deliveryMark == 160
        assert s.markNote == ''


# =============================================================================
# The record: every run says what it held back (ARCH-060: silence is not a record)
# =============================================================================


def test_main_logsMarkAndHeld_onBothPasses_evenWhenNothingIsDeleted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    dbPath = tmp_path / 'obd.db'
    conn = _db(dbPath, now=_dt.datetime.now(_dt.UTC))
    _deliveredThrough(conn, 100)
    conn.close()

    assert coc.main(['--db', str(dbPath), '--execute']) == 0

    out = capsys.readouterr().out
    # The printed lines only (the logger also writes them to stdout, prefixed).
    lines = [line for line in out.splitlines() if line.startswith('[') and 'cutoff=' in line]
    assert len(lines) == 2
    assert all('deliveryMark=100' in line for line in lines)
    assert 'heldUndelivered=0' in lines[0]
    assert 'heldUndelivered=50' in lines[1]


def test_main_unreadableMark_warnsLoudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    dbPath = tmp_path / 'obd.db'
    conn = _db(dbPath)
    conn.execute('DROP TABLE sync_log')
    conn.commit()
    conn.close()

    assert coc.main(['--db', str(dbPath), '--execute']) == 0

    out = capsys.readouterr().out
    assert 'deliveryMark=UNREADABLE' in out
    assert 'deleting nothing' in out
