################################################################################
# File Name: test_monthly_test_hold.py
# Purpose/Description: ARCH-065 T5 -- the monthly test hold task, its due check
#                      and the open-row label; timings come from the SSOT.
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | ARCH-065 T5: created.
################################################################################
import sqlite3

from src.pi.power.battery_capacity import TEST_HOLD_S, WINDOW_S, WINDOW_SKIP_S
from src.pi.power.battery_health import (
    ensureBatteryHealthLogCapacityColumns,
    ensureBatteryHealthLogTable,
    resolveCellEpoch,
)
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.monthly_test_hold import (
    MonthlyTestHoldTask,
    isMonthlyTestDue,
    markOpenDrainMonthlyTest,
)

_AT_HOME = (OutcomeKind.DELIVERED, OutcomeKind.STALLED, OutcomeKind.AT_HOME_SERVER_DOWN,
            OutcomeKind.PROBE_MISCONFIGURED)


def _hold(outcome, due, since=7.0, **kw):
    slept: list[float] = []
    marked: list[bool] = []
    task = MonthlyTestHoldTask(
        lastSyncOutcome=lambda: outcome, isDue=lambda: due, markOpenDrain=lambda: marked.append(True),
        secondsSinceCut=lambda: since, sleepFn=slept.append, **kw,
    )
    return task, slept, marked


def test_timings_haveOneOwner() -> None:
    assert (WINDOW_SKIP_S, WINDOW_S, TEST_HOLD_S) == (60, 600, 660)


def test_atHomeAndDue_holdsUntilTestHoldAfterTheCut_andMarksTheRow() -> None:
    task, slept, marked = _hold(OutcomeKind.DELIVERED, True, since=300.0)
    assert task.run() is OutcomeKind.OK
    assert sum(slept) == TEST_HOLD_S - 300.0 and marked == [True]


def test_holdSecDefaultsToTheSsot() -> None:
    task, slept, _ = _hold(OutcomeKind.DELIVERED, True, since=0.0)
    task.run()
    assert slept == [float(TEST_HOLD_S)]


def test_alreadyPastTheHold_marksButDoesNotSleep() -> None:
    task, slept, marked = _hold(OutcomeKind.DELIVERED, True, since=TEST_HOLD_S + 1.0)
    task.run()
    assert slept == [] and marked == [True]


def test_away_neverHolds() -> None:
    task, slept, marked = _hold(OutcomeKind.AWAY, True)
    task.run()
    assert slept == [] and marked == []


def test_notDue_neverHolds() -> None:
    for outcome in _AT_HOME:
        task, slept, _ = _hold(outcome, False)
        task.run()
        assert slept == []


def test_aBrokenDependency_neverRaises() -> None:
    def boom() -> bool:
        raise RuntimeError("db locked")

    task = MonthlyTestHoldTask(
        lastSyncOutcome=lambda: OutcomeKind.DELIVERED, isDue=boom, markOpenDrain=lambda: None,
        secondsSinceCut=lambda: 0.0, sleepFn=lambda _s: None,
    )
    assert task.run() is OutcomeKind.OK


def _db(tmp_path, rows):
    p = str(tmp_path / "obd.db")
    conn = sqlite3.connect(p)
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    for start, trig, epoch, runtime in rows:
        conn.execute(
            "INSERT INTO battery_health_log (start_timestamp, end_timestamp, runtime_seconds, drain_trigger, cell_epoch) "
            "VALUES (?, ?, ?, ?, ?)", (start, start, runtime, trig, epoch))
    conn.commit()
    conn.close()
    return p


def test_due_whenNoCountedTestForThisPack_in30Days(tmp_path) -> None:
    p = _db(tmp_path, [("2026-09-27T14:06:59Z", "monthly_test", "18650-pack", 8169)])
    assert not isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-20T00:00:00Z", intervalDays=30)
    assert isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-28T00:00:00Z", intervalDays=30)
    assert isMonthlyTestDue(p, cellEpoch="new-pack", nowIso="2026-10-01T00:00:00Z", intervalDays=30)


def test_anInterruptedTest_doesNotCount(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "monthly_test", "18650-pack", TEST_HOLD_S - 1)])
    assert isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-02T00:00:00Z", intervalDays=30)


def test_aTestOfExactlyTestHold_counts(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "monthly_test", "18650-pack", TEST_HOLD_S)])
    assert not isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-02T00:00:00Z", intervalDays=30)


def test_markOpenDrain_setsTheTriggerOnTheOpenRowOnly(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "keyoff", "18650-pack", 6)])
    conn = sqlite3.connect(p)
    conn.execute("INSERT INTO battery_health_log (start_timestamp) VALUES ('2026-10-02T17:00:00Z')")
    conn.commit()
    conn.close()
    markOpenDrainMonthlyTest(p)
    conn = sqlite3.connect(p)
    assert conn.execute("SELECT drain_trigger FROM battery_health_log ORDER BY drain_event_id").fetchall() == [
        ("keyoff",), ("monthly_test",)]


def test_resolveCellEpoch_presentMissingEmpty() -> None:
    assert resolveCellEpoch({"pi": {"power": {"cellEpoch": "18650-pack"}}}) == "18650-pack"
    assert resolveCellEpoch({}) == "unknown"
    assert resolveCellEpoch({"pi": {}}) == "unknown"
    assert resolveCellEpoch({"pi": {"power": {}}}) == "unknown"
    assert resolveCellEpoch({"pi": {"power": {"cellEpoch": ""}}}) == "unknown"
    assert resolveCellEpoch({"pi": {"power": {"cellEpoch": None}}}) == "unknown"
