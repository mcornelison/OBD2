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
# 2026-10-03    | Atlas (ARCH-065a)  | Ruling 19: the hold is gated on the loss's HOME
#               |                    | STATE (AT_HOME_STATE_NAMES); markOpenDrain takes the
#               |                    | snapshotted lossIso; the mark's band is lossRowBand.
################################################################################
import logging
import sqlite3

import pytest

from src.pi.network.home_detector import AT_HOME_STATE_NAMES, HomeNetworkState
from src.pi.power.battery_capacity import TEST_HOLD_S, WINDOW_S, WINDOW_SKIP_S
from src.pi.power.battery_health import (
    LOSS_ROW_AFTER_S,
    LOSS_ROW_BEFORE_S,
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

_HOME = HomeNetworkState.AT_HOME_SERVER_REACHABLE.name
_AWAY = HomeNetworkState.AWAY.name
_LOSS = "2026-10-02T17:00:00Z"


def _hold(state, due, since=7.0, **kw):
    slept: list[float] = []
    marked: list[bool] = []
    kw.setdefault("lossIso", lambda: _LOSS)
    task = MonthlyTestHoldTask(
        homeStateName=lambda: state, isDue=lambda: due,
        markOpenDrain=lambda _iso: marked.append(True) or 1,
        secondsSinceCut=lambda: since, sleepFn=slept.append, **kw,
    )
    return task, slept, marked


def test_timings_haveOneOwner() -> None:
    assert (WINDOW_SKIP_S, WINDOW_S, TEST_HOLD_S) == (60, 600, 660)


def test_atHomeAndDue_holdsUntilTestHoldAfterTheCut_andMarksTheRow() -> None:
    task, slept, marked = _hold(_HOME, True, since=300.0)
    assert task.run() is OutcomeKind.OK
    assert sum(slept) == TEST_HOLD_S - 300.0 and marked == [True, True]


def test_holdSecDefaultsToTheSsot() -> None:
    task, slept, _ = _hold(_HOME, True, since=0.0)
    task.run()
    assert slept == [float(TEST_HOLD_S)]


def test_alreadyPastTheHold_marksButDoesNotSleep() -> None:
    task, slept, marked = _hold(_HOME, True, since=TEST_HOLD_S + 1.0)
    task.run()
    assert slept == [] and marked == [True, True]


@pytest.mark.parametrize("state", [HomeNetworkState.AWAY.name, HomeNetworkState.UNKNOWN.name])
def test_notAtHome_neverHolds(state) -> None:
    task, slept, marked = _hold(state, True)
    task.run()
    assert slept == [] and marked == []


@pytest.mark.parametrize("state", sorted(AT_HOME_STATE_NAMES))
def test_everyAtHomeState_holdsWhenDue(state) -> None:
    task, slept, marked = _hold(state, True, since=0.0)
    task.run()
    assert slept == [float(TEST_HOLD_S)] and marked == [True, True]


def test_atHomeSet_isTheHomeDetectorsOwner() -> None:
    """Ruling 19 SSOT: the hold and the boot finaliser read ONE at-home set."""
    import src.pi.power.battery_health_finalize as fin
    import src.pi.power.power_watch.tasks.monthly_test_hold as hold
    from src.pi.network import home_detector

    assert hold.AT_HOME_STATE_NAMES is home_detector.AT_HOME_STATE_NAMES
    assert fin.AT_HOME_STATE_NAMES is home_detector.AT_HOME_STATE_NAMES
    assert not hasattr(hold, "AT_HOME_OUTCOMES")


def test_notDue_neverHolds() -> None:
    for state in AT_HOME_STATE_NAMES:
        task, slept, _ = _hold(state, False)
        task.run()
        assert slept == []


def test_aBrokenDependency_neverRaises() -> None:
    def boom() -> bool:
        raise RuntimeError("db locked")

    task = MonthlyTestHoldTask(
        homeStateName=lambda: _HOME, isDue=boom, markOpenDrain=lambda _iso: None,
        secondsSinceCut=lambda: 0.0, sleepFn=lambda _s: None,
    )
    assert task.run() is OutcomeKind.OK


def _db(tmp_path, rows):
    p = str(tmp_path / "obd.db")
    conn = sqlite3.connect(p)
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    for start, trig, epoch, runtime, *rate in rows:
        conn.execute(
            "INSERT INTO battery_health_log (start_timestamp, end_timestamp, runtime_seconds, drain_trigger, "
            "cell_epoch, drain_rate_mv_s) VALUES (?, ?, ?, ?, ?, ?)",
            (start, start, runtime, trig, epoch, rate[0] if rate else None))
    conn.commit()
    conn.close()
    return p


def test_due_whenNoCountedTestForThisPack_in30Days(tmp_path) -> None:
    p = _db(tmp_path, [("2026-09-27T14:06:59Z", "monthly_test", "18650-pack", 8169, -0.04)])
    assert not isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-20T00:00:00Z", intervalDays=30)
    assert isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-28T00:00:00Z", intervalDays=30)
    assert isMonthlyTestDue(p, cellEpoch="new-pack", nowIso="2026-10-01T00:00:00Z", intervalDays=30)


def test_anInterruptedTest_noRate_doesNotCount(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "monthly_test", "18650-pack", TEST_HOLD_S - 1)])
    assert isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-02T00:00:00Z", intervalDays=30)


def test_aRatedTest_counts_byTheRateNotTheRuntime(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "monthly_test", "18650-pack", 10, -0.04)])
    assert not isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-02T00:00:00Z", intervalDays=30)


def test_aLongUnratedMonthlyTest_doesNotCount(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "monthly_test", "18650-pack", TEST_HOLD_S + 500)])
    assert isMonthlyTestDue(p, cellEpoch="18650-pack", nowIso="2026-10-02T00:00:00Z", intervalDays=30)


def test_markOpenDrain_setsTheTriggerOnTheOpenRowOnly(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-01T00:00:00Z", "keyoff", "18650-pack", 6)])
    conn = sqlite3.connect(p)
    conn.execute("INSERT INTO battery_health_log (start_timestamp) VALUES ('2026-10-02T17:00:00Z')")
    conn.commit()
    conn.close()
    assert markOpenDrainMonthlyTest(p, lossIso="2026-10-02T17:00:03Z") == 1
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


def _openRow(p, start):
    conn = sqlite3.connect(p)
    conn.execute("INSERT INTO battery_health_log (start_timestamp) VALUES (?)", (start,))
    conn.commit()
    conn.close()


def _triggers(p):
    conn = sqlite3.connect(p)
    try:
        return [r[0] for r in conn.execute("SELECT drain_trigger FROM battery_health_log ORDER BY drain_event_id")]
    finally:
        conn.close()


def test_staleOpenRow_beforeTheLoss_isNotLabelled(tmp_path) -> None:
    p = _db(tmp_path, [])
    _openRow(p, "2026-10-02T16:00:00Z")
    assert markOpenDrainMonthlyTest(p, lossIso="2026-10-02T17:00:00Z") == 0
    assert _triggers(p) == ["keyoff"]


def test_rowOpenedSlightlyBeforeTheLossStamp_withinSlack_isLabelled(tmp_path) -> None:
    p = _db(tmp_path, [])
    _openRow(p, "2026-10-02T16:59:57Z")
    assert markOpenDrainMonthlyTest(p, lossIso="2026-10-02T17:00:00Z") == 1


def test_collectorOpensTheRowLate_theAfterSleepMarkLabelsIt(tmp_path) -> None:
    p = _db(tmp_path, [])
    _openRow(p, "2026-10-02T16:00:00Z")  # stale, must stay keyoff
    loss = "2026-10-02T17:00:00Z"
    task = MonthlyTestHoldTask(
        homeStateName=lambda: _HOME, isDue=lambda: True,
        markOpenDrain=lambda iso: markOpenDrainMonthlyTest(p, lossIso=iso),
        secondsSinceCut=lambda: 0.0, lossIso=lambda: loss,
        sleepFn=lambda _s: _openRow(p, "2026-10-02T17:00:02Z"),  # opened DURING the hold
    )
    task.run()
    assert _triggers(p) == ["keyoff", "monthly_test"]


def test_firstMarkRaises_holdStillSleepsTheFullRemainder() -> None:
    calls = []
    slept: list[float] = []

    def mark(_iso: str) -> int:
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return 1

    task = MonthlyTestHoldTask(
        homeStateName=lambda: _HOME, isDue=lambda: True, markOpenDrain=mark,
        secondsSinceCut=lambda: 100.0, sleepFn=slept.append, lossIso=lambda: _LOSS,
    )
    assert task.run() is OutcomeKind.OK
    assert slept == [TEST_HOLD_S - 100.0] and len(calls) == 2


def test_neitherMarkMatches_warnsNamingTheLoss(caplog) -> None:
    task = MonthlyTestHoldTask(
        homeStateName=lambda: _HOME, isDue=lambda: True, markOpenDrain=lambda _iso: 0,
        secondsSinceCut=lambda: 0.0, sleepFn=lambda _s: None, lossIso=lambda: "2026-10-02T17:00:00Z",
    )
    with caplog.at_level(logging.INFO):
        task.run()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "2026-10-02T17:00:00Z" in warnings[0].getMessage()


def test_skip_logsWhy(caplog) -> None:
    with caplog.at_level(logging.INFO):
        _hold(_AWAY, True)[0].run()
        _hold(_HOME, False)[0].run()
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("not at home" in m and "AWAY" in m for m in msgs)
    assert any("not due" in m for m in msgs)


# ---------------------------------------------------------------------------
# Ruling 19: the mark selects through the ONE band helper (battery_health)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "labelled"),
    [
        ("2026-10-02T16:59:55Z", True),   # loss - LOSS_ROW_BEFORE_S: in
        ("2026-10-02T16:59:54Z", False),  # one second earlier: out
        ("2026-10-02T17:00:30Z", True),   # loss + LOSS_ROW_AFTER_S: in
        ("2026-10-02T17:00:31Z", False),  # one second later: out (no upper bound before)
    ],
)
def test_mark_bandEdges(tmp_path, start, labelled) -> None:
    assert (LOSS_ROW_BEFORE_S, LOSS_ROW_AFTER_S) == (5, 30)
    p = _db(tmp_path, [])
    _openRow(p, start)
    assert markOpenDrainMonthlyTest(p, lossIso=_LOSS) == (1 if labelled else 0)


def test_mark_neverLabelsAClosedRowInTheBand(tmp_path) -> None:
    p = _db(tmp_path, [("2026-10-02T17:00:02Z", "keyoff", "18650-pack", 6)])  # closed
    assert markOpenDrainMonthlyTest(p, lossIso=_LOSS) == 0
    assert _triggers(p) == ["keyoff"]


def test_noLossIso_marksNothing() -> None:
    task, slept, marked = _hold(_HOME, True, since=0.0, lossIso=lambda: None)
    task.run()
    assert marked == [] and slept == [float(TEST_HOLD_S)]
