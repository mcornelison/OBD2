################################################################################
# File Name: test_drain_floor_dwell.py
# Purpose/Description: ARCH-065 T4 -- the reserve floor (drainFloorVolts) holds
#                      for drainFloorDwellReads consecutive reads before it ends
#                      the drain, and a floor-ended drain is recorded as
#                      RESERVE_FLOOR (never overwritten by a late sync record).
# Author: Atlas (ARCH-065a)
# Creation Date: 2026-10-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author            | Description
# ================================================================================
# 2026-10-03    | Atlas (ARCH-065a) | Initial -- ARCH-065 T4.
# ================================================================================
################################################################################
"""Threshold + dwell (specs/design-patterns.md section 1) on the reserve floor."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import src.pi.power.power_watch.__main__ as m
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.tasks.sync_with_server import SyncOutcomeRecord
from src.pi.power.types import DRAIN_TERMINATION_DRAIN_FLOOR


def _seq(reads, dwell, **kw):
    it = iter(reads)

    def vcell():
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v

    return ShutdownSequencer(
        isOnBattery=lambda: True, vcell=vcell, runPipelineFn=lambda: None,
        powerOffFn=lambda: None, vcellFloor=3.50, totalCapSec=45, smoothingSec=0,
        smoothingPollSec=0.0, drainFloor=3.60, drainFloorDwellReads=dwell, **kw,
    )


def test_oneDipBelowTheFloor_doesNotEndTheDrain() -> None:
    seq = _seq([3.59, 3.70, 3.70, 3.70, 3.70, 3.70, 3.70], dwell=5)
    done = threading.Event()
    threading.Timer(0.05, done.set).start()
    end = seq._pollPipeline(done, floorReadable=True)
    assert end.reason is None


def test_fiveConsecutiveReadsBelow_endTheDrainAtTheFloor() -> None:
    seq = _seq([3.59] * 5 + [3.70] * 50, dwell=5)
    end = seq._pollPipeline(threading.Event(), floorReadable=True)
    assert end.reason == DRAIN_TERMINATION_DRAIN_FLOOR


def test_dwellOfOne_isTodaysBehaviour() -> None:
    seq = _seq([3.59] + [3.70] * 50, dwell=1)
    end = seq._pollPipeline(threading.Event(), floorReadable=True)
    assert end.reason == DRAIN_TERMINATION_DRAIN_FLOOR


def test_aFailedRead_neitherCountsNorResetsTheDwell() -> None:
    # 4 low, a failed read, then the 5th low read: still ends at the floor.
    seq = _seq([3.59] * 4 + [OSError("i2c")] + [3.59] + [3.70] * 50, dwell=5)
    end = seq._pollPipeline(threading.Event(), floorReadable=True)
    assert end.reason == DRAIN_TERMINATION_DRAIN_FLOOR


def test_aRecoveryReadResetsTheDwell() -> None:
    seq = _seq([3.59] * 4 + [3.70] + [3.59] * 4 + [3.70] * 3, dwell=5)
    done = threading.Event()
    threading.Timer(0.2, done.set).start()
    end = seq._pollPipeline(done, floorReadable=True)
    assert end.reason is None


def _readOutcome(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _homeState(tmp_path, vcell=3.91):
    path = tmp_path / "powerwatch_outcome.json"
    hs = m.HomeStateAtLoss(
        lambda: HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        outcomePath=str(path), startFn=lambda fn: fn(), vcellBeforeCut=lambda: vcell,
    )
    return path, hs


def test_floorEndedDrain_writesReserveFloor_withHomeStateAndPreCutVcell(tmp_path) -> None:
    path, hs = _homeState(tmp_path)
    release = threading.Event()  # the pipeline never finishes on its own
    seq = _seq(
        [3.59] * 50, dwell=5, powerLossObservedFn=hs.observe,
        prePowerOffFn=m.composePrePowerOffHooks(
            m.buildFloorEndHook(lambda: seq.lastDrainEndReason, hs), hs.ensureRecorded,
        ),
    )
    seq._runPipeline = lambda: release.wait(5)
    try:
        seq.handleOnBattery()
    finally:
        release.set()
    rec = _readOutcome(path)
    assert rec["sync_outcome"] == "RESERVE_FLOOR"
    assert rec["vcell_before_cut_v"] == 3.91
    assert rec["home_state"] == hs.stateName()


def test_lateSyncRecord_doesNotOverwriteReserveFloor(tmp_path) -> None:
    path, hs = _homeState(tmp_path)
    hs.observe()
    hs.recordFloorEnd()
    sink = hs.wrapSink(m.makeOutcomeSink(str(path), homeState=hs.stateName))
    sink(SyncOutcomeRecord(OutcomeKind.OK, "late", 0, 0))
    assert _readOutcome(path)["sync_outcome"] == "RESERVE_FLOOR"


def test_nextLoss_acceptsSyncRecordsAgain(tmp_path) -> None:
    path, hs = _homeState(tmp_path)
    hs.observe()
    hs.recordFloorEnd()
    hs.observe()
    sink = hs.wrapSink(m.makeOutcomeSink(str(path), homeState=hs.stateName))
    sink(SyncOutcomeRecord(OutcomeKind.OK, "fresh", 0, 0))
    assert _readOutcome(path)["sync_outcome"] == "OK"
    # and ensureRecorded does not clobber an already-written floor end
    hs.observe()
    hs.recordFloorEnd()
    hs.ensureRecorded()
    assert _readOutcome(path)["sync_outcome"] == "RESERVE_FLOOR"
