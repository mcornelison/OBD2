################################################################################
# File Name: test_ltft_trend_emitter.py
# Purpose/Description: Tests for the F-096 `ltft-trend` emitter (US-420). The
#   trend reader aggregates per-drive LTFT from realtime_data (real drives only);
#   the schema builder is pure and CLASSIFIES the drift (the SSOT verdict the
#   carousel card only maps to colour); the emit factory is best-effort (write
#   failures logged, never raised -- same contract as the F-103 / US-400/401/404
#   emitters). Covers: the drift-band classifier boundaries (+/-5 ok, +/-10 amber,
#   beyond down); the reader's real-only + non-NULL-drive filter, oldest->newest
#   ordering, per-drive aggregation, and drive-limit bound; the insufficient-data
#   honesty guard (< MIN_DRIVES_FOR_TREND NEVER renders a confident GREEN); the
#   migration direction (improving toward 0 vs worsening); and the never-raise
#   atomic write.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Ralph (Rex)  | Initial implementation (US-420 LTFT trend card).
# ================================================================================
################################################################################

"""Tests for ``pi.splash.ltft_trend_emitter``."""

import json
import os
import sqlite3

from pi.splash.ltft_trend_emitter import (
    LEVEL_AMBER,
    LEVEL_DOWN,
    LEVEL_INSUFFICIENT,
    LEVEL_OK,
    LTFT_PID,
    LTFT_TREND_FILENAME,
    TREND_IMPROVING,
    TREND_STABLE,
    TREND_WORSENING,
    buildLtftTrendState,
    classifyLtftDrift,
    makeLtftTrendEmitter,
    readLtftTrend,
)

_NOW = "2026-07-01T12:00:00Z"


# ---------------------------------------------------------------------------
# Test DB helpers -- a minimal realtime_data + drive_summary the reader queries.
# ---------------------------------------------------------------------------


def _makeDb() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT '2026-07-01T00:00:00Z',
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            profile_id TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE drive_summary (
            drive_id INTEGER PRIMARY KEY,
            drive_start_timestamp TEXT NOT NULL
        )
        """
    )
    return conn


def _seedDrive(
    conn: sqlite3.Connection,
    driveId: int,
    ltftValues: list[float],
    *,
    ts: str | None = None,
    dataSource: str = "real",
    parameterName: str = LTFT_PID,
    addSummary: bool = True,
) -> None:
    """Seed one drive's worth of LTFT samples (+ an optional drive_summary row)."""
    if addSummary and ts is not None:
        conn.execute(
            "INSERT INTO drive_summary (drive_id, drive_start_timestamp) VALUES (?, ?)",
            (driveId, ts),
        )
    for value in ltftValues:
        conn.execute(
            "INSERT INTO realtime_data (parameter_name, value, unit, data_source, "
            "drive_id) VALUES (?, ?, '%', ?, ?)",
            (parameterName, value, dataSource, driveId),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# classifyLtftDrift -- the pure drift-band classifier (grounded thresholds).
# ---------------------------------------------------------------------------


def test_classifyLtftDrift_withinFivePercent_isOk():
    """|LTFT| <= 5 % -> ok (the normal band). Sign is irrelevant (abs)."""
    assert classifyLtftDrift(0.0) == LEVEL_OK
    assert classifyLtftDrift(5.0) == LEVEL_OK  # boundary inclusive
    assert classifyLtftDrift(-4.9) == LEVEL_OK
    assert classifyLtftDrift(-5.0) == LEVEL_OK


def test_classifyLtftDrift_fiveToTen_isAmber():
    """5 % < |LTFT| <= 10 % -> amber (attention band)."""
    assert classifyLtftDrift(5.1) == LEVEL_AMBER
    assert classifyLtftDrift(-8.0) == LEVEL_AMBER
    assert classifyLtftDrift(10.0) == LEVEL_AMBER  # boundary inclusive


def test_classifyLtftDrift_beyondTen_isDown():
    """|LTFT| > 10 % -> down (drift: vacuum leak / failing sensor / fuel delivery)."""
    assert classifyLtftDrift(10.1) == LEVEL_DOWN
    assert classifyLtftDrift(-14.0) == LEVEL_DOWN
    assert classifyLtftDrift(22.0) == LEVEL_DOWN


# ---------------------------------------------------------------------------
# readLtftTrend -- per-drive aggregation over real drives (oldest -> newest).
# ---------------------------------------------------------------------------


def test_readLtftTrend_aggregatesPerDrive_oldestFirst():
    """Given multiple real drives with LTFT samples,
    When readLtftTrend runs,
    Then each drive is one avg/min/max row, ordered oldest (lowest id) first."""
    conn = _makeDb()
    _seedDrive(conn, 31, [-8.0, -6.0], ts="2026-06-28T10:00:00Z")  # avg -7.0
    _seedDrive(conn, 32, [-6.0, -4.0], ts="2026-06-29T10:00:00Z")  # avg -5.0
    _seedDrive(conn, 33, [-3.0, -1.0], ts="2026-06-30T10:00:00Z")  # avg -2.0

    drives = readLtftTrend(conn)

    assert [d["driveId"] for d in drives] == [31, 32, 33]  # oldest -> newest
    assert drives[0]["ltftAvg"] == -7.0
    assert drives[0]["ltftMin"] == -8.0
    assert drives[0]["ltftMax"] == -6.0
    assert drives[0]["sampleCount"] == 2
    assert drives[0]["ts"] == "2026-06-28T10:00:00Z"
    assert drives[-1]["ltftAvg"] == -2.0


def test_readLtftTrend_excludesFixtureAndNullDrive():
    """Only data_source='real' rows with a non-NULL drive_id feed the trend --
    a fixture/bench drive and NULL-drive rows must never enter the tune signal."""
    conn = _makeDb()
    _seedDrive(conn, 40, [-6.0, -6.0], ts="2026-06-30T10:00:00Z")  # real -> counts
    _seedDrive(conn, 41, [99.0, 99.0], ts="2026-06-30T11:00:00Z", dataSource="fixture")
    # A NULL drive_id real row (pre-drive noise) -- excluded.
    conn.execute(
        "INSERT INTO realtime_data (parameter_name, value, unit, data_source, "
        "drive_id) VALUES (?, 50.0, '%', 'real', NULL)",
        (LTFT_PID,),
    )
    conn.commit()

    drives = readLtftTrend(conn)

    assert [d["driveId"] for d in drives] == [40]
    assert drives[0]["ltftAvg"] == -6.0  # the fixture 99 % never leaked in


def test_readLtftTrend_respectsDriveLimit_keepsMostRecent():
    """driveLimit bounds the window to the N most-recent drives (still oldest
    -> newest in the result)."""
    conn = _makeDb()
    for driveId in range(20, 26):  # 6 drives
        _seedDrive(conn, driveId, [-5.0], ts=f"2026-06-2{driveId - 20}T10:00:00Z")

    drives = readLtftTrend(conn, driveLimit=3)

    assert [d["driveId"] for d in drives] == [23, 24, 25]  # last 3, oldest-first


def test_readLtftTrend_noSummaryRow_tsIsNoneNotFabricated():
    """A drive with trims but no drive_summary row carries ts=None (honest),
    never a fabricated timestamp (LEFT JOIN)."""
    conn = _makeDb()
    _seedDrive(conn, 50, [-6.0], ts=None, addSummary=False)

    drives = readLtftTrend(conn)

    assert drives[0]["driveId"] == 50
    assert drives[0]["ts"] is None


def test_readLtftTrend_noRealRows_returnsEmpty():
    """No real LTFT rows -> empty list (the builder renders insufficient)."""
    conn = _makeDb()
    assert readLtftTrend(conn) == []


# ---------------------------------------------------------------------------
# buildLtftTrendState -- the pure classify-and-assemble SSOT.
# ---------------------------------------------------------------------------


def _drive(driveId: int, avg: float, ts: str | None = None) -> dict:
    return {
        "driveId": driveId,
        "ts": ts,
        "ltftAvg": avg,
        "ltftMin": avg,
        "ltftMax": avg,
        "sampleCount": 1,
    }


def test_buildLtftTrendState_healthyInBand_headlineOk():
    """A sufficient window sitting in the +/-5 % band -> headline level ok, the
    current point is the newest drive, and each point carries its own level."""
    drives = [_drive(31, -4.0), _drive(32, -3.0), _drive(33, -2.0)]
    state = buildLtftTrendState(drives=drives, nowIso=_NOW)

    assert state["pid"] == LTFT_PID
    assert state["sufficient"] is True
    assert state["level"] == LEVEL_OK
    assert state["driveCount"] == 3
    assert state["current"]["driveId"] == 33
    assert state["current"]["level"] == LEVEL_OK
    assert [p["level"] for p in state["points"]] == [LEVEL_OK, LEVEL_OK, LEVEL_OK]
    assert state["ts"] == _NOW


def test_buildLtftTrendState_driftBeyondTen_headlineDown():
    """A current drift beyond +/-10 % -> headline level down (visually distinct
    from a healthy trend -- the AC's core honesty)."""
    drives = [_drive(31, -6.0), _drive(32, -9.0), _drive(33, -14.0)]
    state = buildLtftTrendState(drives=drives, nowIso=_NOW)

    assert state["level"] == LEVEL_DOWN
    assert state["current"]["level"] == LEVEL_DOWN
    assert state["points"][-1]["level"] == LEVEL_DOWN


def test_buildLtftTrendState_insufficient_neverGreen():
    """Honest-instrument: below MIN_DRIVES_FOR_TREND the headline is forced to
    `insufficient` -- a single in-band reading must NOT masquerade as healthy."""
    state = buildLtftTrendState(drives=[_drive(33, -2.0)], nowIso=_NOW)

    assert state["sufficient"] is False
    assert state["level"] == LEVEL_INSUFFICIENT
    assert state["level"] != LEVEL_OK
    assert state["trend"] is None
    # The single point still carries its own honest per-drive level.
    assert state["current"]["level"] == LEVEL_OK
    assert state["driveCount"] == 1


def test_buildLtftTrendState_empty_rendersInsufficientNoCurrent():
    """No drives at all -> insufficient, no current point, empty points, no crash."""
    state = buildLtftTrendState(drives=[], nowIso=_NOW)

    assert state["sufficient"] is False
    assert state["level"] == LEVEL_INSUFFICIENT
    assert state["current"] is None
    assert state["points"] == []


def test_buildLtftTrendState_migratingTowardZero_isImproving():
    """|LTFT| shrinking across the window (e.g. -8 -> -3) -> improving (healthy
    migration toward 0)."""
    drives = [_drive(31, -8.0), _drive(32, -5.0), _drive(33, -3.0)]
    state = buildLtftTrendState(drives=drives, nowIso=_NOW)
    assert state["trend"] == TREND_IMPROVING


def test_buildLtftTrendState_growingAwayFromZero_isWorsening():
    """|LTFT| growing across the window (-3 -> -12) -> worsening."""
    drives = [_drive(31, -3.0), _drive(32, -8.0), _drive(33, -12.0)]
    state = buildLtftTrendState(drives=drives, nowIso=_NOW)
    assert state["trend"] == TREND_WORSENING


def test_buildLtftTrendState_flatWithinEpsilon_isStable():
    """A window that barely moves (within the epsilon dead-band) -> stable, so
    float noise doesn't flip the verdict."""
    drives = [_drive(31, -4.0), _drive(32, -4.1), _drive(33, -4.2)]
    state = buildLtftTrendState(drives=drives, nowIso=_NOW)
    assert state["trend"] == TREND_STABLE


# ---------------------------------------------------------------------------
# makeLtftTrendEmitter -- best-effort atomic writer over the DB reader seam.
# ---------------------------------------------------------------------------


def test_emitter_writesLtftTrendFile_fromReader(tmp_path):
    """The emit callable reads via the injected reader, classifies, and writes
    states/ltft-trend with the pinned payload (provisioning the dir if absent)."""
    statesDir = str(tmp_path / "states")  # does NOT exist yet
    drives = [_drive(32, -3.0, ts="a"), _drive(33, -6.0, ts="b")]
    emit = makeLtftTrendEmitter(
        statesDir, trendReader=lambda: drives, nowIsoFn=lambda: _NOW
    )

    emit()

    written = json.loads(
        (tmp_path / "states" / LTFT_TREND_FILENAME).read_text(encoding="utf-8")
    )
    assert written["sufficient"] is True
    assert written["current"]["driveId"] == 33
    assert written["level"] == LEVEL_AMBER  # newest drive -6.0 is in the 5-10 band
    assert written["ts"] == _NOW


def test_emitter_endToEnd_overSeededDb(tmp_path):
    """End-to-end: a seeded SQLite reader -> the emitter writes an honest state."""
    conn = _makeDb()
    _seedDrive(conn, 61, [-9.0, -7.0], ts="2026-06-29T10:00:00Z")  # avg -8
    _seedDrive(conn, 62, [-4.0, -2.0], ts="2026-06-30T10:00:00Z")  # avg -3
    statesDir = str(tmp_path / "states")
    emit = makeLtftTrendEmitter(
        statesDir, trendReader=lambda: readLtftTrend(conn), nowIsoFn=lambda: _NOW
    )

    emit()

    written = json.loads(
        (tmp_path / "states" / LTFT_TREND_FILENAME).read_text(encoding="utf-8")
    )
    assert written["driveCount"] == 2
    assert written["level"] == LEVEL_OK  # current avg -3 is in-band
    assert written["trend"] == TREND_IMPROVING  # -8 -> -3 migrates toward 0


def test_emitter_neverRaises_onReaderFailure(tmp_path):
    """Best-effort: a reader that raises is logged, never propagated -- the emit
    hook must never block its owning tier."""
    statesDir = str(tmp_path / "states")

    def boom() -> list[dict]:
        raise RuntimeError("db gone")

    emit = makeLtftTrendEmitter(statesDir, trendReader=boom, nowIsoFn=lambda: _NOW)
    emit()  # must not raise

    assert not os.path.exists(os.path.join(statesDir, LTFT_TREND_FILENAME))


def test_emitter_neverRaises_onWriteFailure(tmp_path):
    """A write failure (states parent is a file) is logged, never raised."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    statesDir = str(blocker / "states")  # parent is a file -> mkdir fails
    emit = makeLtftTrendEmitter(
        statesDir, trendReader=lambda: [_drive(1, -3.0), _drive(2, -2.0)],
        nowIsoFn=lambda: _NOW,
    )
    emit()  # must not raise

    assert not os.path.exists(statesDir)
