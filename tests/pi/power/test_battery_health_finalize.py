################################################################################
# File Name: test_battery_health_finalize.py
# Purpose/Description: ARCH-065 T6 -- the boot-time finaliser of the prior drain
#                      (cut step + window rate), and arm's best-effort hook.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T6: created.
################################################################################
"""Tests for src.pi.power.battery_health_finalize (specs/battery-health-design.md sec 6)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.common.time.helper import CANONICAL_ISO_FORMAT
from src.pi.diagnostics.boot_progress import arm
from src.pi.obdii.database_schema import SCHEMA_STARTUP_LOG, ensureDrainVcellTrajectoryTable
from src.pi.power.battery_capacity import TEST_HOLD_S, WINDOW_S, WINDOW_SKIP_S
from src.pi.power.battery_health import (
    DRAIN_TRIGGER_KEYOFF,
    DRAIN_TRIGGER_MONTHLY_TEST,
    ensureBatteryHealthLogCapacityColumns,
    ensureBatteryHealthLogTable,
)
from src.pi.power.battery_health_finalize import (
    MIN_WINDOW_FILL,
    finalizeLatestDrain,
    windowDrainRate,
)
from src.pi.power.power_db import DrainVcellTrajectoryWriter

_CUT = datetime(2026, 10, 27, 17, 0, 0, tzinfo=UTC)
_SLOPE_V_S = -0.00004  # -0.04 mV/s
_CONFIRM_S = 7  # the trajectory starts at the confirmation read, ~7 s after the cut


def _iso(t: datetime) -> str:
    return t.strftime(CANONICAL_ISO_FORMAT)


def _db(
    runtime: int,
    trigger: str = DRAIN_TRIGGER_MONTHLY_TEST,
    startV: float = 4.10,
) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    ensureDrainVcellTrajectoryTable(conn)
    conn.execute(
        "INSERT INTO battery_health_log (start_timestamp, end_timestamp, runtime_seconds, "
        "start_vcell_v, drain_trigger, cell_epoch) VALUES (?, ?, ?, ?, ?, '18650-pack')",
        (_iso(_CUT), _iso(_CUT + timedelta(seconds=runtime)), runtime, startV, trigger))
    for s in range(_CONFIRM_S, runtime + 1):
        conn.execute(
            "INSERT INTO drain_vcell_trajectory (ts_utc, ts_capture, seq, vcell_v, cell_epoch) "
            "VALUES (?, ?, ?, ?, '18650-pack')",
            (_iso(_CUT + timedelta(seconds=s)), 1000.0 + s, s - _CONFIRM_S,
             4.10 + _SLOPE_V_S * s))
    return conn


def _row(conn: sqlite3.Connection, cols: str) -> tuple:
    return conn.execute(f"SELECT {cols} FROM battery_health_log").fetchone()


def test_windowRate_isTheLeastSquaresSlope_inMvPerSecond() -> None:
    pts = [(float(t), 4.1 + _SLOPE_V_S * t) for t in range(WINDOW_SKIP_S, TEST_HOLD_S + 1)]
    assert abs(windowDrainRate(pts) - (-0.04)) < 1e-6


def test_windowRate_underTwoDistinctTimes_isNone() -> None:
    assert windowDrainRate([]) is None
    assert windowDrainRate([(1.0, 4.0)]) is None
    assert windowDrainRate([(1.0, 4.0), (1.0, 4.1)]) is None


def test_aFullMonthlyTest_getsItsRateAndWindow() -> None:
    conn = _db(runtime=700)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2188, priorBootLossAt=_iso(_CUT))
    rate, ws, we, step = _row(
        conn, "drain_rate_mv_s, window_start_s, window_end_s, cut_step_mv")
    assert abs(rate - (-0.04)) < 1e-3
    assert (ws, we) == (WINDOW_SKIP_S, TEST_HOLD_S)
    assert abs(step - 118.8) < 0.05


def test_aShortMonthlyTest_isNotCounted_noRateWritten() -> None:
    conn = _db(runtime=240)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=None, priorBootLossAt=_iso(_CUT))
    assert _row(conn, "drain_rate_mv_s, cut_step_mv") == (None, None)


def test_aMonthlyTestInterruptedBeforeTheWindowFills_getsNoRate() -> None:
    conn = _db(runtime=500)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    assert _row(conn, "drain_rate_mv_s, window_start_s, window_end_s") == (None, None, None)


def test_aSparseWindow_underMinFill_getsNoRate() -> None:
    conn = _db(runtime=700)
    lo = _iso(_CUT + timedelta(seconds=WINDOW_SKIP_S))
    hi = _iso(_CUT + timedelta(seconds=TEST_HOLD_S))
    conn.execute(
        "DELETE FROM drain_vcell_trajectory WHERE ts_utc >= ? AND ts_utc <= ? AND seq % 2 = 0",
        (lo, hi))
    n = conn.execute(
        "SELECT COUNT(*) FROM drain_vcell_trajectory WHERE ts_utc >= ? AND ts_utc <= ?",
        (lo, hi)).fetchone()[0]
    assert n < MIN_WINDOW_FILL * WINDOW_S
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    assert _row(conn, "drain_rate_mv_s")[0] is None


def test_aKeyoff_getsOnlyTheCutStep() -> None:
    conn = _db(runtime=6, trigger=DRAIN_TRIGGER_KEYOFF, startV=4.05)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    rate, step = _row(conn, "drain_rate_mv_s, cut_step_mv")
    assert rate is None and abs(step - 120.0) < 0.05


def test_aLongKeyoff_neverGetsARate() -> None:
    conn = _db(runtime=900, trigger=DRAIN_TRIGGER_KEYOFF)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    assert _row(conn, "drain_rate_mv_s")[0] is None


def test_noPriorVcell_leavesCutStepNull_butStillRatesTheWindow() -> None:
    conn = _db(runtime=700)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=None, priorBootLossAt=_iso(_CUT))
    rate, step = _row(conn, "drain_rate_mv_s, cut_step_mv")
    assert step is None and rate is not None


def test_runningTwice_changesNothing() -> None:
    conn = _db(runtime=700)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2188, priorBootLossAt=_iso(_CUT))
    first = conn.execute("SELECT * FROM battery_health_log").fetchall()
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=3.0, priorBootLossAt=_iso(_CUT))
    assert conn.execute("SELECT * FROM battery_health_log").fetchall() == first


def test_noClosedDrainRow_isANoOp() -> None:
    conn = sqlite3.connect(":memory:")
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    ensureDrainVcellTrajectoryTable(conn)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    assert conn.execute("SELECT COUNT(*) FROM battery_health_log").fetchone()[0] == 0


def test_realWriterTimestamps_matchTheDrainRowFormat_andAreSelected(tmp_path: Path) -> None:
    """ts_utc as DrainVcellTrajectoryWriter stores it (utcIsoNow, canonical
    YYYY-MM-DDTHH:MM:SSZ) range-compares against battery_health_log.start_timestamp."""
    dbPath = str(tmp_path / "obd.db")
    setup = sqlite3.connect(dbPath)
    ensureBatteryHealthLogTable(setup)
    ensureBatteryHealthLogCapacityColumns(setup)
    ensureDrainVcellTrajectoryTable(setup)
    runtime = 700
    setup.execute(
        "INSERT INTO battery_health_log (start_timestamp, end_timestamp, runtime_seconds, "
        "start_vcell_v, drain_trigger, cell_epoch) VALUES (?, ?, ?, 4.10, ?, '18650-pack')",
        (_iso(_CUT), _iso(_CUT + timedelta(seconds=runtime)), runtime, DRAIN_TRIGGER_MONTHLY_TEST))
    setup.commit()
    setup.close()
    clock = {"s": _CONFIRM_S}
    writer = DrainVcellTrajectoryWriter(
        dbPath=dbPath, cellEpoch="18650-pack",
        monotonicFn=lambda: 5000.0 + clock["s"],
        nowIsoFn=lambda: _iso(_CUT + timedelta(seconds=clock["s"])))
    for s in range(_CONFIRM_S, runtime + 1):
        clock["s"] = s
        writer.record(4.10 + _SLOPE_V_S * s)
    conn = sqlite3.connect(dbPath)
    stamp = conn.execute("SELECT ts_utc FROM drain_vcell_trajectory LIMIT 1").fetchone()[0]
    assert datetime.strptime(stamp, CANONICAL_ISO_FORMAT)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    assert abs(_row(conn, "drain_rate_mv_s")[0] - (-0.04)) < 1e-3
    conn.close()


def test_defaultWriterClock_isTheSameCanonicalFormatAsTheDrainRow(tmp_path: Path) -> None:
    """The writer's own default clock (no nowIsoFn injected) stamps the canonical format."""
    dbPath = str(tmp_path / "obd.db")
    setup = sqlite3.connect(dbPath)
    ensureDrainVcellTrajectoryTable(setup)
    setup.commit()
    setup.close()
    DrainVcellTrajectoryWriter(dbPath=dbPath, cellEpoch="e").record(4.0)
    conn = sqlite3.connect(dbPath)
    stamp = conn.execute("SELECT ts_utc FROM drain_vcell_trajectory").fetchone()[0]
    conn.close()
    assert datetime.strptime(stamp, CANONICAL_ISO_FORMAT).strftime(CANONICAL_ISO_FORMAT) == stamp


def test_arm_finalisesThePriorDrain_fromTheOutcomeRecordsVcell(tmp_path: Path) -> None:
    dbPath = tmp_path / "obd.db"
    conn = sqlite3.connect(dbPath)
    conn.executescript(SCHEMA_STARTUP_LOG)
    ensureBatteryHealthLogTable(conn)
    conn.execute(
        "INSERT INTO battery_health_log (start_timestamp, end_timestamp, runtime_seconds, "
        "start_vcell_v, drain_trigger) VALUES (?, ?, 6, 4.05, ?)",
        (_iso(_CUT), _iso(_CUT + timedelta(seconds=6)), DRAIN_TRIGGER_KEYOFF))
    conn.commit()
    conn.close()
    trail = tmp_path / "boot_progress"
    trail.write_text(json.dumps({"stage": "RUNNING", "boot_id": "prior1", "vcell": None}) + "\n",
                     encoding="utf-8")
    outcome = tmp_path / "outcome.json"
    outcome.write_text(json.dumps({"boot_id": "prior1", "vcell_before_cut_v": 4.17, "loss_at": _iso(_CUT)}),
                       encoding="utf-8")
    arm(filePath=str(trail), dbPath=str(dbPath), bootId="new1", nasArchiveDir=str(tmp_path / "n"),
        nasArchiveEnabled=False, outcomeRecordPath=str(outcome))
    conn = sqlite3.connect(dbPath)
    prior = conn.execute(
        "SELECT prior_boot_vcell_before_cut_v FROM startup_log WHERE boot_id='new1'").fetchone()[0]
    step = conn.execute("SELECT cut_step_mv FROM battery_health_log").fetchone()[0]
    conn.close()
    assert prior == 4.17
    assert abs(step - 120.0) < 0.05


def test_arm_neverFails_whenTheFinaliserCannotRun(tmp_path: Path) -> None:
    """No battery_health_log table at all: arm still writes its row and re-arms."""
    dbPath = tmp_path / "obd.db"
    sqlite3.connect(dbPath).executescript(SCHEMA_STARTUP_LOG)
    trail = tmp_path / "boot_progress"
    arm(filePath=str(trail), dbPath=str(dbPath), bootId="b1", nasArchiveDir=str(tmp_path / "n"),
        nasArchiveEnabled=False)
    conn = sqlite3.connect(dbPath)
    assert conn.execute("SELECT COUNT(*) FROM startup_log WHERE boot_id='b1'").fetchone()[0] == 1
    conn.close()
    assert '"RUNNING"' in trail.read_text(encoding="utf-8")


def _addRow(conn: sqlite3.Connection, start: datetime, trigger: str, startV: float, *,
            closed: bool, cutStep: float | None = None) -> int:
    end = _iso(start + timedelta(seconds=6)) if closed else None
    cur = conn.execute(
        "INSERT INTO battery_health_log (start_timestamp, end_timestamp, runtime_seconds, "
        "start_vcell_v, drain_trigger, cut_step_mv) VALUES (?, ?, ?, ?, ?, ?)",
        (_iso(start), end, 6 if closed else None, startV, trigger, cutStep))
    return int(cur.lastrowid)


def _steps(conn: sqlite3.Connection) -> dict[int, float | None]:
    return dict(conn.execute("SELECT drain_event_id, cut_step_mv FROM battery_health_log"))


def _bare() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    ensureDrainVcellTrajectoryTable(conn)
    return conn


def test_hardCut_theOpenRowOfTheLoss_getsTheStep_andAnOlderClosedRowIsUntouched() -> None:
    conn = _bare()
    old = _addRow(conn, _CUT - timedelta(days=2), DRAIN_TRIGGER_KEYOFF, 4.0, closed=True)
    loss = _addRow(conn, _CUT, DRAIN_TRIGGER_KEYOFF, 4.05, closed=False)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    steps = _steps(conn)
    assert steps[old] is None
    assert abs(steps[loss] - 120.0) < 0.05


def test_blipThenLoss_theStampLandsOnTheLaterOpenRow_notTheEarlierClosedOne() -> None:
    conn = _bare()
    blip = _addRow(conn, _CUT - timedelta(hours=3), DRAIN_TRIGGER_KEYOFF, 4.0, closed=True)
    loss = _addRow(conn, _CUT, DRAIN_TRIGGER_KEYOFF, 4.05, closed=False)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    assert _steps(conn)[blip] is None and _steps(conn)[loss] is not None


def test_noRowNearTheLoss_stampsNothing() -> None:
    conn = _bare()
    old = _addRow(conn, _CUT - timedelta(hours=3), DRAIN_TRIGGER_KEYOFF, 4.0, closed=True)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    assert _steps(conn)[old] is None


def test_noLossAt_changesNothing() -> None:
    conn = _db(runtime=700)
    before = conn.execute("SELECT * FROM battery_health_log").fetchall()
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=None)
    assert conn.execute("SELECT * FROM battery_health_log").fetchall() == before


def test_theLossBand_isFiveSecondsBeforeToThirtyAfter() -> None:
    conn = _bare()
    early = _addRow(conn, _CUT - timedelta(seconds=6), DRAIN_TRIGGER_KEYOFF, 4.0, closed=False)
    late = _addRow(conn, _CUT + timedelta(seconds=31), DRAIN_TRIGGER_KEYOFF, 4.0, closed=False)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    assert _steps(conn) == {early: None, late: None}
    edge = _addRow(conn, _CUT + timedelta(seconds=30), DRAIN_TRIGGER_KEYOFF, 4.0, closed=False)
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    assert _steps(conn)[edge] is not None


def test_anOpenMonthlyTest_withAFullWindow_isRated() -> None:
    conn = _db(runtime=700)
    conn.execute("UPDATE battery_health_log SET end_timestamp = NULL, runtime_seconds = NULL")
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    rate, ws, we = _row(conn, "drain_rate_mv_s, window_start_s, window_end_s")
    assert abs(rate - (-0.04)) < 1e-3 and (ws, we) == (WINDOW_SKIP_S, TEST_HOLD_S)


def test_aBunchedWindow_enoughPointsButSpanTooShort_isNotRated() -> None:
    conn = _bare()
    _addRow(conn, _CUT, DRAIN_TRIGGER_MONTHLY_TEST, 4.10, closed=False)
    n = int(MIN_WINDOW_FILL * WINDOW_S) + 20
    for i in range(n):  # 500 points crammed into ~100 s of the window
        conn.execute(
            "INSERT INTO drain_vcell_trajectory (ts_utc, ts_capture, seq, vcell_v, cell_epoch) "
            "VALUES (?, ?, ?, ?, 'e')",
            (_iso(_CUT + timedelta(seconds=WINDOW_SKIP_S + i // 5)), 2000.0 + i * 0.2, i,
             4.1 - 1e-6 * i))
    assert n >= MIN_WINDOW_FILL * WINDOW_S
    finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.2, priorBootLossAt=_iso(_CUT))
    assert _row(conn, "drain_rate_mv_s")[0] is None


def test_theCutStep_isCommittedEvenWhenTheWindowParseFails(tmp_path: Path) -> None:
    path = str(tmp_path / "x.db")
    conn = sqlite3.connect(path)
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    conn.execute(
        "INSERT INTO battery_health_log (start_timestamp, start_vcell_v, drain_trigger) "
        "VALUES (?, 4.05, ?)", (_iso(_CUT), DRAIN_TRIGGER_MONTHLY_TEST))
    conn.commit()
    try:  # no drain_vcell_trajectory table: the window query raises after the step
        finalizeLatestDrain(conn, priorBootVcellBeforeCutV=4.17, priorBootLossAt=_iso(_CUT))
    except sqlite3.OperationalError:
        pass
    conn.rollback()
    conn.close()
    other = sqlite3.connect(path)
    assert other.execute("SELECT cut_step_mv FROM battery_health_log").fetchone()[0] is not None
    other.close()
