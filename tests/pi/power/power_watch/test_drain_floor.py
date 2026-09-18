################################################################################
# File Name: test_drain_floor.py
# Purpose/Description: US-776-b -- the drain stops on its own floor
#                      (pi.powerWatch.drainFloorVolts), above the vcellFloorVolts
#                      emergency backstop, which still takes the pre-pipeline
#                      fast path. Power returning mid-drain cancels and restores
#                      the shed within one poll, before the next pass starts.
#                      Driven through the real chain (_buildRunSync ->
#                      SyncWithServerTask -> runPipeline -> ShutdownSequencer).
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-17    | Rex (US-776-b) | Initial -- drain floor, backstop, power return.
# ================================================================================
################################################################################
"""US-776-b: the drain gets its own floor, above the emergency backstop."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.pipeline import runPipeline
from src.pi.power.power_watch.sync_custody import makeSyncCustodyHook
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask
from src.pi.sync.backlog import BACKLOG_OUTSTANDING, SyncBacklog

# Production values (validator DEFAULTS / config.json).
_PER_TASK_TIMEOUT_SEC = 20.0
_TOTAL_WINDOW_CAP_SEC = 45.0
_VCELL_FLOOR = 3.50
_DRAIN_FLOOR = 3.60
_HEALTHY_VCELL = 3.72
_BATCH = 500
_PASSES = 6

# Wall-clock poll interval; keeps the real test fast.
_POLL_SEC = 0.01
_WAIT_SEC = 5.0


class _Summary:
    """PushSummary stand-in (only the fields _buildRunSync reads)."""

    def __init__(self, rowsPushed: int) -> None:
        self.rowsPushed = rowsPushed
        self.tablesFailed = 0
        self.disabled = False


class _FakeClock:
    """A monotonic clock that never moves: only the floor may end these drains."""

    def __call__(self) -> float:
        return 0.0


class _PassClient:
    """forcePush moving one batch per pass; pass ``blockOnPass`` waits on ``release``."""

    def __init__(self, *, backlog: list[int], blockOnPass: int) -> None:
        self.backlog = backlog
        self.passesStarted = 0
        self._blockOnPass = blockOnPass
        self.blockedEntered = threading.Event()
        self.release = threading.Event()

    def forcePush(self, *, excludeTables=()) -> _Summary:
        self.passesStarted += 1
        if self.passesStarted == self._blockOnPass:
            self.blockedEntered.set()
            self.release.wait()
        pushed = min(self.backlog[0], _BATCH)
        self.backlog[0] -= pushed
        return _Summary(rowsPushed=pushed)


def _readerOver(backlog: list[int]):
    def _read(**_kw) -> SyncBacklog:
        return SyncBacklog(perTable={"realtime_data": backlog[0]})

    return _read


def _pipelineFor(client: _PassClient, backlog: list[int]):
    syncTask = SyncWithServerTask(
        serverReachable=lambda: True,
        runSync=m._buildRunSync(
            client,
            backlogReader=_readerOver(backlog),
            excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
        ),
        writeRecord=lambda _r: None,
    )
    return lambda: runPipeline(
        m.buildV1Tasks(syncTask),
        perTaskTimeoutSec=_PER_TASK_TIMEOUT_SEC,
        sequencerBoundedTasks=(syncTask.name,),
    )


def _sequencer(
    *,
    events: list,
    runPipelineFn,
    vcell,
    isOnBattery=lambda: True,
    prePowerOffFn=None,
    powerRestoredFn=None,
    passesAt=lambda: None,
) -> ShutdownSequencer:
    return ShutdownSequencer(
        isOnBattery=isOnBattery,
        vcell=vcell,
        runPipelineFn=runPipelineFn,
        powerOffFn=lambda: events.append(("poweroff", passesAt())),
        vcellFloor=_VCELL_FLOOR,
        drainFloor=_DRAIN_FLOOR,
        totalCapSec=_TOTAL_WINDOW_CAP_SEC,
        smoothingSec=0.0,
        smoothingPollSec=_POLL_SEC,
        sleepFn=lambda _s: None,
        monotonicFn=_FakeClock(),
        prePowerOffFn=prePowerOffFn,
        powerRestoredFn=powerRestoredFn,
    )


class TestTheDrainStopsOnDrainFloor:
    """VC-1: VCELL reaches drainFloorVolts during pass 3 of 6."""

    def test_vcellDropsToDrainFloorInPass3_noPass4_poweroff_custodyRecordsRemaining(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a 6-pass backlog, VCELL 3.72 V until pass 3 is in flight, then
            3.60 V (= drainFloorVolts, above the 3.50 V backstop)
        When: the shutdown runs
        Then: the poll ends the drain -- no pass 4 -- poweroff runs, and the
            custody record carries the rows still outstanding
        """
        # Arrange
        events: list = []
        backlog = [_PASSES * _BATCH]
        client = _PassClient(backlog=backlog, blockOnPass=3)
        recordPath = tmp_path / "custody.json"

        def _vcell() -> float:
            return _DRAIN_FLOOR if client.blockedEntered.is_set() else _HEALTHY_VCELL

        seq = _sequencer(
            events=events,
            runPipelineFn=_pipelineFor(client, backlog),
            vcell=_vcell,
            prePowerOffFn=makeSyncCustodyHook(
                recordPath=str(recordPath), backlogReader=_readerOver(backlog)
            ),
            passesAt=lambda: client.passesStarted,
        )

        # Act
        try:
            seq.handleOnBattery()
        finally:
            client.release.set()

        # Assert
        assert events == [("poweroff", 3)]
        record = json.loads(recordPath.read_text(encoding="utf-8"))
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["outstandingRows"] == (_PASSES - 2) * _BATCH

    def test_vcellAboveDrainFloor_drainRunsToEmpty(self) -> None:
        """
        Given: VCELL 3.61 V throughout -- above drainFloorVolts
        When: the shutdown runs
        Then: all 6 passes run and the drain ends on an empty backlog
        """
        # Arrange
        events: list = []
        backlog = [_PASSES * _BATCH]
        client = _PassClient(backlog=backlog, blockOnPass=0)
        client.release.set()

        seq = _sequencer(
            events=events,
            runPipelineFn=_pipelineFor(client, backlog),
            vcell=lambda: _DRAIN_FLOOR + 0.01,
            passesAt=lambda: client.passesStarted,
        )

        # Act
        seq.handleOnBattery()

        # Assert
        assert events == [("poweroff", _PASSES)]
        assert backlog[0] == 0

    def test_vcellBetweenTheFloors_pipelineStarts_firstPollEndsIt(self) -> None:
        """
        Given: VCELL 3.55 V -- above the 3.50 V backstop, below the 3.60 V drain
            floor (a depleted pack)
        When: the shutdown runs
        Then: the fast path is NOT taken (the pipeline starts), and the drain's
            own floor ends it at the first poll -- a short drain, by design
        """
        # Arrange
        events: list = []
        backlog = [_PASSES * _BATCH]
        client = _PassClient(backlog=backlog, blockOnPass=1)

        seq = _sequencer(
            events=events,
            runPipelineFn=_pipelineFor(client, backlog),
            vcell=lambda: 3.55,
            passesAt=lambda: client.passesStarted,
        )

        # Act
        try:
            seq.handleOnBattery()
        finally:
            client.release.set()

        # Assert
        # The poll may win the race with pass 1 starting; it never waits past it.
        assert client.blockedEntered.wait(_WAIT_SEC)
        assert [kind for kind, _ in events] == ["poweroff"]
        assert events[0][1] <= 1


class TestTheBackstopFastPathIsUntouched:
    """VC-2 / doNoHarm: below vcellFloorVolts the pipeline is skipped."""

    def test_vcellBelowVcellFloorAtStart_pipelineSkipped_poweroffNow(self) -> None:
        """
        Given: VCELL 3.45 V at the start of a confirmed shutdown
        When: handleOnBattery runs
        Then: the pipeline never runs and poweroff is immediate
        """
        # Arrange
        events: list = []
        pipelineCalls: list[int] = []

        seq = _sequencer(
            events=events,
            runPipelineFn=lambda: pipelineCalls.append(1),
            vcell=lambda: _VCELL_FLOOR - 0.05,
        )

        # Act
        seq.handleOnBattery()

        # Assert
        assert pipelineCalls == []
        assert events == [("poweroff", None)]


class TestPowerReturnMidDrain:
    """VC-3: power returns during pass 2 of 6."""

    def test_powerReturnsInPass2_restoreBeforePass3_noPoweroff(self) -> None:
        """
        Given: a 6-pass drain with healthy VCELL
        When: PLD reads power-present while pass 2 is in flight
        Then: LoadShedder.restore (powerRestoredFn) runs before pass 3 could
            start -- within one poll, not at the end of the drain -- and no
            poweroff runs
        """
        # Arrange
        events: list = []
        backlog = [_PASSES * _BATCH]
        client = _PassClient(backlog=backlog, blockOnPass=2)
        restoredAtPass: list[int] = []

        seq = _sequencer(
            events=events,
            runPipelineFn=_pipelineFor(client, backlog),
            vcell=lambda: _HEALTHY_VCELL,
            isOnBattery=lambda: not client.blockedEntered.is_set(),
            powerRestoredFn=lambda: restoredAtPass.append(client.passesStarted),
        )

        # Act
        try:
            seq.handleOnBattery()
        finally:
            client.release.set()

        # Assert
        assert restoredAtPass == [2]
        assert events == []


class TestMainWiresTheDrainFloor:
    def test_main_readsDrainFloorVolts_andPassesItToTheSequencer(self) -> None:
        """
        Given: the production entrypoint
        When: the sequencer is built
        Then: pi.powerWatch.drainFloorVolts is the drain floor, and vcellFloor
            is still vcellFloorVolts
        """
        # Arrange
        import inspect

        # Act
        source = inspect.getsource(m.main)

        # Assert
        assert 'float(pw_cfg["drainFloorVolts"])' in source
        assert "drainFloor=drainFloorVolts" in source
        assert "vcellFloor=vcellFloorVolts" in source
