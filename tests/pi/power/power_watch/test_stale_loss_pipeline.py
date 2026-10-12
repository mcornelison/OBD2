################################################################################
# File Name: test_stale_loss_pipeline.py
# Purpose/Description: ARCH-065a final review I1 (Ruling 19) -- a pipeline thread
#                      left running by a CANCELLED loss (power returned mid-
#                      shutdown) must never act on the NEXT loss: its hold must
#                      not label the next loss's row and its sync record must be
#                      dropped.  Also M3 (lastOutcome reset) and M4 (floor-end
#                      logs the record it overwrites).
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author             | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a)  | Ruling 19: created.
################################################################################
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest

import src.pi.power.power_watch.__main__ as m
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.battery_health import (
    ensureBatteryHealthLogCapacityColumns,
    ensureBatteryHealthLogTable,
)
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.tasks.monthly_test_hold import (
    MonthlyTestHoldTask,
    markOpenDrainMonthlyTest,
)
from src.pi.power.power_watch.tasks.sync_with_server import (
    SyncOutcomeRecord,
    SyncWithServerTask,
)

_LOSS_N = "2026-10-02T17:00:00Z"


class _Wall:
    """wallIsoFn whose value the test moves between losses."""

    def __init__(self, iso: str) -> None:
        self.iso = iso

    def __call__(self) -> str:
        return self.iso


def _holder(outcomePath: Path, wall: _Wall) -> m.HomeStateAtLoss:
    return m.HomeStateAtLoss(
        lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        outcomePath=str(outcomePath),
        startFn=lambda _t: None,  # no home-state record: the sync record is the one under test
        wallIsoFn=wall,
    )


def _db(tmp_path: Path) -> str:
    p = str(tmp_path / "obd.db")
    conn = sqlite3.connect(p)
    ensureBatteryHealthLogTable(conn)
    ensureBatteryHealthLogCapacityColumns(conn)
    conn.commit()
    conn.close()
    return p


def _openRow(p: str, start: str) -> None:
    conn = sqlite3.connect(p)
    conn.execute("INSERT INTO battery_health_log (start_timestamp) VALUES (?)", (start,))
    conn.commit()
    conn.close()


def _triggers(p: str) -> list[str]:
    conn = sqlite3.connect(p)
    try:
        return [r[0] for r in conn.execute(
            "SELECT drain_trigger FROM battery_health_log ORDER BY drain_event_id")]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The loss generation
# ---------------------------------------------------------------------------


def test_lossGeneration_increments_onEveryObserve(tmp_path: Path) -> None:
    h = _holder(tmp_path / "o.json", _Wall(_LOSS_N))
    before = h.lossGeneration()
    h.observe()
    first = h.lossGeneration()
    h.observe()
    assert before < first < h.lossGeneration()


# ---------------------------------------------------------------------------
# I1: a stale hold never labels the next loss's row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lossN1",
    [
        "2026-10-02T17:20:00Z",  # well after loss N: outside loss N's band
        "2026-10-02T17:00:10Z",  # inside loss N's band: only the generation saves it
    ],
)
def test_staleHold_fromLossN_wakesDuringLossN1_doesNotLabelLossN1Row(
    tmp_path: Path, lossN1: str
) -> None:
    p = _db(tmp_path)
    wall = _Wall(_LOSS_N)
    h = _holder(tmp_path / "o.json", wall)
    h.observe()  # loss N

    def sleepThroughTheNextLoss(_s: float) -> None:
        # Power returned (loss N cancelled), then power was lost again: loss N+1.
        wall.iso = lossN1
        h.observe()
        _openRow(p, lossN1)  # the collector opens loss N+1's row

    hold = MonthlyTestHoldTask(
        homeStateName=lambda: "AT_HOME_SERVER_REACHABLE",
        isDue=lambda: True,
        markOpenDrain=lambda iso: markOpenDrainMonthlyTest(p, lossIso=iso),
        secondsSinceCut=lambda: 0.0,
        lossIso=h.lossIso,
        lossGeneration=h.lossGeneration,
        sleepFn=sleepThroughTheNextLoss,
    )
    hold.run()
    assert _triggers(p) == ["keyoff"]


def test_hold_snapshotsLossIsoOnce_andPassesItToEveryMark(tmp_path: Path) -> None:
    seen: list[str] = []
    isos = iter(["2026-10-02T17:00:00Z", "2026-10-02T18:00:00Z", "2026-10-02T19:00:00Z"])
    hold = MonthlyTestHoldTask(
        homeStateName=lambda: "AT_HOME_SERVER_REACHABLE",
        isDue=lambda: True,
        markOpenDrain=lambda iso: seen.append(iso) or 1,
        secondsSinceCut=lambda: 0.0,
        lossIso=lambda: next(isos),
        sleepFn=lambda _s: None,
    )
    hold.run()
    assert seen == ["2026-10-02T17:00:00Z", "2026-10-02T17:00:00Z"]


# ---------------------------------------------------------------------------
# I1: a stale sync record is dropped; lastOutcome is not overwritten
# ---------------------------------------------------------------------------


def test_staleSyncRecord_fromLossN_arrivingDuringLossN1_isDropped(tmp_path: Path, caplog) -> None:
    outcomePath = tmp_path / "powerwatch_outcome.json"
    wall = _Wall(_LOSS_N)
    h = _holder(outcomePath, wall)
    states = iter([HomeNetworkState.AT_HOME_SERVER_REACHABLE, HomeNetworkState.AWAY])
    task: SyncWithServerTask

    def runSyncOfLossN() -> None:
        # Loss N is cancelled while its drain is still pushing; loss N+1 begins
        # and its own pipeline runs the same task to completion (AWAY).
        wall.iso = "2026-10-02T17:20:00Z"
        h.observe()
        task._runSync = lambda: None  # noqa: SLF001 -- loss N+1 pushes nothing
        task.run()

    task = SyncWithServerTask(
        homeState=lambda: next(states),
        runSync=runSyncOfLossN,
        writeRecord=h.wrapSink(m.makeOutcomeSink(
            str(outcomePath), homeState=h.stateName, lossAt=h.lossIso)),
        joinWaitSec=120.0,
        stallSec=60.0,
        sleepFn=lambda _s: None,
        monotonic=lambda: 0.0,
        lossGeneration=h.lossGeneration,
    )
    h.observe()  # loss N
    with caplog.at_level(logging.INFO):
        task.run()  # loss N's (now stale) DELIVERED lands after loss N+1's AWAY
    record = json.loads(outcomePath.read_text(encoding="utf-8"))
    assert record["sync_outcome"] == "AWAY"
    assert record["loss_at"] == "2026-10-02T17:20:00Z"
    assert task.lastOutcome is OutcomeKind.AWAY
    assert any("stale record from a cancelled loss dropped" in r.getMessage()
               for r in caplog.records)


def test_wrapSink_dropsARecordOfAnOlderGeneration(tmp_path: Path) -> None:
    written: list[SyncOutcomeRecord] = []
    h = _holder(tmp_path / "o.json", _Wall(_LOSS_N))
    h.observe()
    old = h.lossGeneration()
    h.observe()
    sink = h.wrapSink(written.append)
    sink(SyncOutcomeRecord(OutcomeKind.DELIVERED, "stale", 1, 0, lossGeneration=old))
    sink(SyncOutcomeRecord(OutcomeKind.AWAY, "current", 1, 1, lossGeneration=h.lossGeneration()))
    assert [r.detail for r in written] == ["current"]


# ---------------------------------------------------------------------------
# M3: lastOutcome is reset at the start of every run
# ---------------------------------------------------------------------------


def test_syncRun_resetsLastOutcome_atTheStart() -> None:
    seenDuringRun: list[object] = []
    task: SyncWithServerTask

    def homeState() -> HomeNetworkState:
        seenDuringRun.append(task.lastOutcome)
        return HomeNetworkState.AWAY

    task = SyncWithServerTask(
        homeState=homeState, runSync=lambda: None, writeRecord=lambda _r: None,
        joinWaitSec=1.0, stallSec=1.0, sleepFn=lambda _s: None, monotonic=lambda: 0.0,
    )
    task.run()
    task.run()
    assert seenDuringRun == [None, None]
    assert task.lastOutcome is OutcomeKind.AWAY


# ---------------------------------------------------------------------------
# M4: the floor-end record names what it overwrites
# ---------------------------------------------------------------------------


def test_recordFloorEnd_logsTheKindItOverwrites(tmp_path: Path, caplog) -> None:
    outcomePath = tmp_path / "o.json"
    h = _holder(outcomePath, _Wall(_LOSS_N))
    h.observe()
    h.wrapSink(m.makeOutcomeSink(str(outcomePath)))(
        SyncOutcomeRecord(OutcomeKind.STALLED, "x", 5, 5, lossGeneration=h.lossGeneration()))
    with caplog.at_level(logging.INFO):
        h.recordFloorEnd()
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert any("overwrit" in msg and "STALLED" in msg for msg in infos)


def test_recordFloorEnd_withNothingWritten_logsNoOverwrite(tmp_path: Path, caplog) -> None:
    h = _holder(tmp_path / "o.json", _Wall(_LOSS_N))
    h.observe()
    with caplog.at_level(logging.INFO):
        h.recordFloorEnd()
    assert not any("overwrit" in r.getMessage() for r in caplog.records)
