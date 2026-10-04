################################################################################
# File Name: test_sync_to_completion.py
# Purpose/Description: ARCH-065 T3 -- the at-home shutdown sync runs to
#                      COMPLETION (CIO 2026-10-02): no absolute time cap; it
#                      ends delivered, or stalled (backlog did not fall for
#                      stallSec, re-read after every attempt), or at the
#                      battery reserve floor (enforced by the sequencer).
#                      The WiFi-join wait is bounded separately (joinWaitSec).
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | Initial -- ARCH-065 T3 sync to completion.
# ================================================================================
################################################################################
"""ARCH-065 T3: the at-home sync is delivered, stalled, or floored -- never capped."""

from __future__ import annotations

from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.sync_with_server import (
    SyncOutcomeRecord,
    SyncWithServerTask,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


class _Backlog:
    """A backlog each runSync call lowers by `step` rows (0 = no progress), taking `cost` s."""

    def __init__(self, clock: _Clock, rows: int, step: int, cost: float) -> None:
        self.clock, self.rows, self.step, self.cost = clock, rows, step, cost

    def runSync(self) -> None:
        self.clock.now += self.cost
        self.rows = max(0, self.rows - self.step)

    def read(self) -> int:
        return self.rows


def _task(clock, backlog, records, state=HomeNetworkState.AT_HOME_SERVER_REACHABLE):
    return SyncWithServerTask(
        homeState=lambda: state, runSync=backlog.runSync, writeRecord=records.append,
        joinWaitSec=120.0, stallSec=60.0, sleepFn=clock.sleep, monotonic=clock.monotonic,
        backlogReader=backlog.read,
    )


def test_aFiveMinuteSync_isNotCutAt60s_andEndsDelivered() -> None:
    clock = _Clock()
    backlog = _Backlog(clock, rows=45_000, step=1_500, cost=10.0)  # 30 batches x 10 s = 300 s
    records: list[SyncOutcomeRecord] = []
    task = _task(clock, backlog, records)
    assert task.run() is OutcomeKind.DELIVERED
    assert task.lastOutcome is OutcomeKind.DELIVERED
    assert clock.now >= 300.0 and backlog.rows == 0


def test_noProgressFor60s_isStalled_notDelivered() -> None:
    clock = _Clock()
    backlog = _Backlog(clock, rows=500, step=0, cost=5.0)  # returns quietly, pushes nothing
    records: list[SyncOutcomeRecord] = []
    task = _task(clock, backlog, records)
    assert task.run() is OutcomeKind.STALLED
    assert task.lastOutcome is OutcomeKind.STALLED
    assert 60.0 <= clock.now < 60.0 + 20.0
    assert records[0].backlogEnd == 500


def test_runSyncReturningWithBacklogLeft_isNeverDelivered() -> None:
    clock = _Clock()
    backlog = _Backlog(clock, rows=10, step=0, cost=1.0)
    records: list[SyncOutcomeRecord] = []
    assert _task(clock, backlog, records).run() is not OutcomeKind.DELIVERED


def test_joinWait_is120s_andTheStallClockStartsAtAssociation() -> None:
    clock = _Clock()
    backlog = _Backlog(clock, rows=3_000, step=1_500, cost=10.0)
    joinedAt = 100.0
    records: list[SyncOutcomeRecord] = []
    task = SyncWithServerTask(
        homeState=lambda: (HomeNetworkState.AT_HOME_JOINING if clock.now < joinedAt
                           else HomeNetworkState.AT_HOME_SERVER_REACHABLE),
        runSync=backlog.runSync, writeRecord=records.append, joinWaitSec=120.0, stallSec=60.0,
        sleepFn=clock.sleep, monotonic=clock.monotonic, backlogReader=backlog.read,
    )
    assert task.run() is OutcomeKind.DELIVERED  # 100 s of joining did not count as a stall


def test_neverJoins_isJoiningTimeoutAt120s() -> None:
    clock = _Clock()
    backlog = _Backlog(clock, rows=10, step=10, cost=1.0)
    records: list[SyncOutcomeRecord] = []
    out = _task(clock, backlog, records, state=HomeNetworkState.AT_HOME_JOINING).run()
    assert out is OutcomeKind.AT_HOME_JOINING_TIMEOUT
    assert 118.0 <= clock.now <= 122.0
