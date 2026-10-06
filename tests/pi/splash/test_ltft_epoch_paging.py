################################################################################
# File Name: test_ltft_epoch_paging.py
# Purpose/Description: US-420 / F-096 (reopened) -- the LTFT trend epoch is read
#                      back to the adaptive-memory RESET, not to a drive count.
#                      The reader pages back (LTFT only, classified by the ONE
#                      isAdaptiveResetDrive) until it finds a reset or exhausts
#                      history; the baseline is the EPOCH mean (contract:
#                      specs/grounded-knowledge.md, LTFT trend contract), and the
#                      payload's per-drive bars stay the newest window.
# Author: Atlas (architect)
# Creation Date: 2026-10-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-05    | Atlas        | US-420 (CIO-directed build, charter override).
# ================================================================================
################################################################################
"""F-096: the epoch reaches back to the reset; raising the count stays rejected."""

from __future__ import annotations

import datetime as _dt
import json
import sqlite3
from pathlib import Path

import pytest

import pi.splash.ltft_trend_emitter as lte  # the siblings' path (one module identity)

_T0 = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)
_SAMPLES = 25  # > GATE_MIN_QUALIFYING_SAMPLES (20)


def _db() -> sqlite3.Connection:
    """The columns the reader touches, in the real realtime_data / drive_summary shape."""
    conn = sqlite3.connect(':memory:')
    conn.execute(
        'CREATE TABLE realtime_data (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME NOT NULL, '
        "parameter_name TEXT NOT NULL, value REAL NOT NULL, data_source TEXT NOT NULL DEFAULT 'real', "
        'drive_id INTEGER)'
    )
    conn.execute('CREATE TABLE drive_summary (drive_id INTEGER PRIMARY KEY, drive_start_timestamp TEXT)')
    return conn


def _drive(conn: sqlite3.Connection, driveId: int, ltft: float) -> None:
    """One WARM, closed-loop drive whose every LTFT sample reads ``ltft``.

    ltft == 0.0 makes it an adaptive-memory RESET (bit-identical zero).
    """
    rows = []
    for i in range(_SAMPLES):
        ts = (_T0 + _dt.timedelta(hours=driveId, seconds=i)).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows += [
            (ts, lte.COOLANT_PID, 90.0, driveId),
            (ts, lte.FUEL_SYSTEM_PID, float(lte.FUEL_SYSTEM_CLOSED_LOOP), driveId),
            (ts, lte.LTFT_PID, ltft, driveId),
            (ts, lte.STFT_PID, 1.0, driveId),
        ]
    conn.executemany(
        'INSERT INTO realtime_data (timestamp, parameter_name, value, drive_id) VALUES (?,?,?,?)', rows,
    )
    conn.execute('INSERT INTO drive_summary VALUES (?, ?)', (driveId, rows[0][0]))


def _history(n: int, *, resets: tuple[int, ...] = (), special: dict[int, float] | None = None,
             ltft: float = 1.0) -> sqlite3.Connection:
    conn = _db()
    for d in range(1, n + 1):
        value = 0.0 if d in resets else (special or {}).get(d, ltft)
        _drive(conn, d, value)
    conn.commit()
    return conn


def _state(conn: sqlite3.Connection) -> dict:
    """The payload exactly as the production emitter builds it from the reader."""
    rows = lte.readLtftDriveRows(conn)
    return lte.buildLtftTrendState(
        driveRecords=lte.buildDriveRecords(rows),
        nowIso='2026-10-05T00:00:00Z',
        historyExhausted=rows.historyExhausted,
    )


# =============================================================================
# The defect: a reset beyond the 20-drive window left the card blank
# =============================================================================


class TestReadsBackToTheReset:

    def test_resetBeyondTheWindow_isFound_epochStartsAfterIt(self) -> None:
        """
        Given: 60 drives, the reset at drive 30 -- 30 drives before the newest
        When: the reader runs (driveLimit 20)
        Then: the epoch starts at 31, NOT clipped, and the card is sufficient.
              Today's reader stops at drive 41 and publishes 'epoch clipped'.
        """
        state = _state(_history(60, resets=(30,)))

        assert state['epochStartDriveId'] == 31
        assert state['epochClipped'] is False
        assert state['epochBreak'] is True
        assert state['sufficient'] is True
        assert state['reason'] is None

    def test_readerReturnsTheResetDrive_andTheWholeEpoch(self) -> None:
        rows = lte.readLtftDriveRows(_history(60, resets=(30,)))

        assert sorted(rows) == list(range(30, 61))
        assert rows.historyExhausted is False  # it stopped AT a reset, not at the end

    def test_noResetInAllHistory_isExhausted_notClipped(self) -> None:
        """No reset anywhere in 45 drives: the epoch is all of history, start = the oldest."""
        conn = _history(45)
        rows = lte.readLtftDriveRows(conn)

        assert rows.historyExhausted is True
        assert sorted(rows) == list(range(1, 46))
        state = _state(conn)
        assert (state['epochStartDriveId'], state['epochClipped']) == (1, False)

    def test_resetInsideTheWindow_noPaging_sameDrivesAsToday(self) -> None:
        """The common case is untouched: the newest 20, the boundary already among them."""
        conn = _history(60, resets=(50,))

        rows = lte.readLtftDriveRows(conn)

        assert sorted(rows) == list(range(41, 61))
        assert _state(conn)['epochStartDriveId'] == 51

    def test_theResetTestIsTheOneDefinition_zeroVarianceIsNotAReset(self) -> None:
        """
        Drive 30 has ZERO VARIANCE at -2.344 (the drive-33 shape) and is NOT a
        reset; the real reset is drive 10. A variance-based boundary search would
        stop at 30. isAdaptiveResetDrive (bit-identity to 0.000) does not.
        """
        state = _state(_history(60, resets=(10,), special={30: -2.344}))

        assert state['epochStartDriveId'] == 11

    def test_twoResetsBeyondTheWindow_theNewestOneBounds(self) -> None:
        state = _state(_history(80, resets=(15, 35)))

        assert state['epochStartDriveId'] == 36


# =============================================================================
# The contract: baseline = EPOCH mean; the bars stay the newest window
# =============================================================================


class TestEpochBaselineAndDisplayWindow:

    def test_baselineIsTheEpochMean_notTheWindowMean(self) -> None:
        """
        Epoch 31..60: drives 31-40 at +2.0, 41-60 at +0.5.
        Epoch grand mean = (10*2.0 + 20*0.5)/30 = 1.0; the newest-20 window mean is 0.5.
        The contract's baseline is the EPOCH's grand mean.
        """
        special = {d: 2.0 for d in range(31, 41)}
        state = _state(_history(60, resets=(30,), special=special, ltft=0.5))

        assert state['baseline'] == pytest.approx(1.0)
        assert state['driveCount'] == 30
        assert state['epochDriveCount'] == 30

    def test_pointsAreTheNewestDisplayWindow_oneBarPerDrive(self) -> None:
        """The card draws one labelled bar per point; a 30-drive epoch still shows the newest 20."""
        state = _state(_history(60, resets=(30,)))

        assert [p['driveId'] for p in state['points']] == list(range(41, 61))
        assert state['current']['driveId'] == 60

    def test_shortEpoch_pointsAreTheWholeEpoch(self) -> None:
        state = _state(_history(60, resets=(50,)))

        assert [p['driveId'] for p in state['points']] == list(range(51, 61))
        assert state['driveCount'] == 10


# =============================================================================
# The emitter seam
# =============================================================================


class TestEmitterTrustsTheReader:

    def test_productionReader_noResetEver_isNotClipped(self, tmp_path: Path) -> None:
        conn = _history(45)
        emit = lte.makeLtftTrendEmitter(
            str(tmp_path), driveRowsReader=lambda: lte.readLtftDriveRows(conn),
            nowIsoFn=lambda: '2026-10-05T00:00:00Z',
        )

        emit()

        payload = json.loads((tmp_path / lte.LTFT_TREND_FILENAME).read_text(encoding='utf-8'))
        assert (payload['epochStartDriveId'], payload['epochClipped']) == (1, False)

    def test_plainDictReader_keepsTheCountFallback(self, tmp_path: Path) -> None:
        """A reader that returns a plain dict (no exhaustion flag) keeps the old rule:
        exactly driveLimit drives with no reset reads as CLIPPED -- the safe failure."""
        conn = _history(45)
        windowOnly = {k: v for k, v in lte.readLtftDriveRows(conn).items() if k > 25}
        emit = lte.makeLtftTrendEmitter(
            str(tmp_path), driveRowsReader=lambda: dict(windowOnly),
            nowIsoFn=lambda: '2026-10-05T00:00:00Z',
        )

        emit()

        payload = json.loads((tmp_path / lte.LTFT_TREND_FILENAME).read_text(encoding='utf-8'))
        assert payload['epochClipped'] is True

    def test_raisingTheDriveCountIsStillRejected(self) -> None:
        """🔴 Do NOT fix this with a bigger DEFAULT_TREND_DRIVES (ruled 2026-09-22)."""
        assert lte.DEFAULT_TREND_DRIVES == 20
