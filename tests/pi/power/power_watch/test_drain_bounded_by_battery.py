################################################################################
# File Name: test_drain_bounded_by_battery.py
# Purpose/Description: US-776-a -- the shutdown drain is bounded by the battery,
#                      not by three timers. Each of the three old bounds is
#                      named and driven through the REAL chain
#                      (_buildRunSync -> SyncWithServerTask -> runPipeline ->
#                      ShutdownSequencer): (1) _buildRunSync's budgetSec
#                      pass-fitting bound, (2) runPipeline's per-task
#                      th.join(timeout=perTaskTimeoutSec) thread abandonment,
#                      (3) the sequencer's done.wait(timeout=totalCapSec) cap.
#                      The floor is re-read by the sequencer's poll, so a
#                      forcePush that never returns still ends in poweroff.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-17    | Rex (US-776-a) | Initial -- the drain is bounded by the battery.
# ================================================================================
################################################################################
"""US-776-a: the drain ends on an empty backlog or the VCELL floor, not a timer."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.power.power_watch import __main__ as m
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.pipeline import runPipeline
from src.pi.power.power_watch.sync_custody import makeSyncCustodyHook
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask
from src.pi.sync.backlog import (
    BACKLOG_DELIVERED,
    BACKLOG_OUTSTANDING,
    BACKLOG_UNKNOWN,
    SyncBacklog,
)

# Production values (config.json / validator DEFAULTS), so "past the old cap"
# is measured against the real old cap.
_PER_TASK_TIMEOUT_SEC = 20.0
_TOTAL_WINDOW_CAP_SEC = 45.0
_VCELL_FLOOR = 3.50
_HEALTHY_VCELL = 4.05

# Wall-clock poll interval for the tests. The fake clock carries the story's
# seconds; this only keeps the real test fast.
_POLL_SEC = 0.01


@dataclass
class _Summary:
    """PushSummary stand-in (only the fields _buildRunSync reads)."""

    rowsPushed: int = 0
    tablesFailed: int = 0
    disabled: bool = False


class _FakeClock:
    """A shared monotonic clock the fake forcePush advances."""

    def __init__(self) -> None:
        self.t = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            return self.t

    def advance(self, seconds: float) -> None:
        with self._lock:
            self.t += seconds


class _DrainingClient:
    """forcePush that moves one batch per pass, each pass costing ``passSec``."""

    def __init__(
        self,
        *,
        clock: _FakeClock,
        passSec: float,
        backlog: list[int],
        wallSecPerPass: float = 0.0,
    ) -> None:
        self._clock = clock
        self._passSec = passSec
        self._wallSecPerPass = wallSecPerPass
        self.backlog = backlog  # [remaining]; shared with the reader
        self.excludeTablesPerPass: list[tuple[str, ...]] = []

    def forcePush(self, *, excludeTables=()) -> _Summary:
        self.excludeTablesPerPass.append(tuple(excludeTables))
        if self._wallSecPerPass:
            time.sleep(self._wallSecPerPass)
        self._clock.advance(self._passSec)
        pushed = min(self.backlog[0], 500)
        self.backlog[0] -= pushed
        return _Summary(rowsPushed=pushed)


def _readerOver(backlog: list[int]):
    def _read(**_kw) -> SyncBacklog:
        return SyncBacklog(perTable={"realtime_data": backlog[0]})

    return _read


def _sequencer(
    *,
    events: list[str],
    runPipelineFn,
    clock: _FakeClock,
    vcell=lambda: _HEALTHY_VCELL,
    isOnBattery=lambda: True,
    prePowerOffFn=None,
) -> ShutdownSequencer:
    return ShutdownSequencer(
        isOnBattery=isOnBattery,
        vcell=vcell,
        runPipelineFn=runPipelineFn,
        powerOffFn=lambda: events.append("poweroff"),
        vcellFloor=_VCELL_FLOOR,
        totalCapSec=_TOTAL_WINDOW_CAP_SEC,
        smoothingSec=0.0,
        smoothingPollSec=_POLL_SEC,
        sleepFn=lambda _s: None,
        monotonicFn=clock,
        prePowerOffFn=prePowerOffFn,
    )


def _productionPipeline(syncTask, *, perTaskTimeoutSec: float = _PER_TASK_TIMEOUT_SEC):
    """The pipeline exactly as main() wires it."""
    return lambda: runPipeline(
        m.buildV1Tasks(syncTask),
        perTaskTimeoutSec=perTaskTimeoutSec,
        sequencerBoundedTasks=(syncTask.name,),
    )


class TestTheDrainOutlivesAllThreeTimers:
    """VC-1: six 15 s passes run to completion, past the old 45 s cap."""

    def test_sixPassesOf15s_allRun_thenPoweroff_pastTheOld45sCap(self) -> None:
        """
        Given: a backlog needing 6 passes of 15 s each, server reachable, VCELL
            healthy, and the production perTaskTimeoutSec=20 / totalCapSec=45
        When: the real drain runs through the real pipeline and sequencer
        Then: all 6 passes run (90 s on the clock), THEN poweroff

        Bound 1 (_buildRunSync budgetSec): a 15 s pass against the old 20 s
        budget stopped after pass 1. Bound 3 (sequencer totalCapSec): the old
        done.wait(45) stopped the window at pass 3. Neither ends it now.
        """
        # Arrange
        clock = _FakeClock()
        events: list[str] = []
        backlog = [6 * 500]
        client = _DrainingClient(clock=clock, passSec=15.0, backlog=backlog)
        syncTask = SyncWithServerTask(
            serverReachable=lambda: True,
            runSync=m._buildRunSync(
                client,
                backlogReader=_readerOver(backlog),
                excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            ),
            writeRecord=lambda _r: events.append("fault-record"),
        )

        def _pipeline() -> None:
            _productionPipeline(syncTask)()
            events.append("pipeline-done")

        seq = _sequencer(events=events, runPipelineFn=_pipeline, clock=clock)

        # Act
        seq.handleOnBattery()

        # Assert
        assert len(client.excludeTablesPerPass) == 6
        assert clock() == 90.0
        assert clock() > _TOTAL_WINDOW_CAP_SEC
        assert backlog[0] == 0
        assert events == ["pipeline-done", "poweroff"]

    def test_everyPass_excludesTheShutdownDrainExcludedTables(self) -> None:
        """
        Given: a multi-pass drain
        When: it runs
        Then: EVERY pass pushes with excludeTables == SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            not just the first
        """
        # Arrange
        clock = _FakeClock()
        backlog = [4 * 500]
        client = _DrainingClient(clock=clock, passSec=15.0, backlog=backlog)
        runSync = m._buildRunSync(
            client,
            backlogReader=_readerOver(backlog),
            excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
        )

        # Act
        runSync()

        # Assert
        assert len(client.excludeTablesPerPass) == 4
        assert SHUTDOWN_DRAIN_EXCLUDED_TABLES
        for passTables in client.excludeTablesPerPass:
            assert passTables == tuple(SHUTDOWN_DRAIN_EXCLUDED_TABLES)

    def test_realRunPipeline_drainLongerThanPerTaskTimeout_isNotAbandoned(self) -> None:
        """
        Given: the REAL runPipeline, a perTaskTimeoutSec shorter than the drain
            takes in WALL-CLOCK time
        When: the sync task is wired as main() wires it (sequencerBoundedTasks)
        Then: every pass runs and the task returns OK -- neither abandoned nor
            truncated

        Bound 2 (runPipeline th.join(timeout=perTaskTimeoutSec)): the join used
        to return at the timeout and ABANDON the daemon thread, which kept
        calling forcePush and writing SQLite while poweroff ran.
        """
        # Arrange -- 6 passes x 0.1 s real = 0.6 s against a 0.2 s per-task bound
        clock = _FakeClock()
        backlog = [6 * 500]
        client = _DrainingClient(
            clock=clock, passSec=15.0, backlog=backlog, wallSecPerPass=0.1
        )
        syncTask = SyncWithServerTask(
            serverReachable=lambda: True,
            runSync=m._buildRunSync(
                client,
                backlogReader=_readerOver(backlog),
                excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            ),
            writeRecord=lambda _r: None,
        )

        # Act
        results = _productionPipeline(syncTask, perTaskTimeoutSec=0.2)()

        # Assert
        assert results == {syncTask.name: OutcomeKind.OK}
        assert len(client.excludeTablesPerPass) == 6
        assert backlog[0] == 0

    def test_realRunPipeline_unlistedTask_keepsItsPerTaskBound(self) -> None:
        """
        Given: a task NOT named in sequencerBoundedTasks (a future plugin task)
        When: it outlives perTaskTimeoutSec
        Then: it is still bounded -- the exemption is per task, not global
        """
        # Arrange
        release = threading.Event()

        class _Plugin:
            name = "future_plugin"

            def run(self) -> OutcomeKind:
                release.wait(5.0)
                return OutcomeKind.OK

        # Act
        t0 = time.monotonic()
        try:
            results = runPipeline(
                [_Plugin()],
                perTaskTimeoutSec=0.2,
                sequencerBoundedTasks=(SyncWithServerTask.name,),
            )
        finally:
            release.set()

        # Assert
        assert time.monotonic() - t0 < 3.0
        assert results == {"future_plugin": OutcomeKind.REAL_ERROR}


class TestMainWiresTheSyncTaskAsSequencerBounded:
    """The pipeline exemption is inert unless main() names the sync task."""

    def test_main_passesTheSyncTaskNameAsSequencerBounded(self) -> None:
        """
        Given: the production entrypoint
        When: the pipeline is built
        Then: the sync task -- and only it -- is joined without perTaskTimeoutSec
        """
        # Arrange
        import inspect

        # Act
        source = inspect.getsource(m.main)

        # Assert
        assert "sequencerBoundedTasks=(syncTask.name,)" in source


class TestTheFloorEndsADrainThatNeverReachesAPassBoundary:
    """VC-2: forcePush blocks forever; the sequencer's poll still sees the floor."""

    def test_forcePushBlocksIndefinitely_floorReached_poweroffRuns(self) -> None:
        """
        Given: forcePush that never returns (A-24: WiFi drops mid-pass) and a
            VCELL that falls to the floor while it is blocked
        When: the shutdown runs
        Then: the sequencer's poll re-reads the floor and powers off; the drain
            never reaches a pass boundary (the backlog reader is never called)
        """
        # Arrange
        clock = _FakeClock()
        events: list[str] = []
        entered = threading.Event()
        release = threading.Event()
        readerCalls: list[int] = []

        class _BlockedClient:
            calls = 0

            def forcePush(self, *, excludeTables=()) -> _Summary:
                _BlockedClient.calls += 1
                entered.set()
                release.wait()
                return _Summary(rowsPushed=0)

        def _reader(**_kw) -> SyncBacklog:
            readerCalls.append(1)
            return SyncBacklog(perTable={"realtime_data": 1})

        syncTask = SyncWithServerTask(
            serverReachable=lambda: True,
            runSync=m._buildRunSync(
                _BlockedClient(),
                backlogReader=_reader,
                excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            ),
            writeRecord=lambda _r: None,
        )
        # Healthy at the pre-pipeline read and while the push is in flight,
        # then at the floor. The clock also races past the old 45 s cap first,
        # so the floor -- not a timer -- is what ends it.
        readings = iter([_HEALTHY_VCELL, _HEALTHY_VCELL, _HEALTHY_VCELL])
        vcellCalls: list[int] = []

        def _vcell() -> float:
            vcellCalls.append(1)
            if len(vcellCalls) > 1:  # a poll, not the pre-pipeline read
                assert entered.wait(5.0), "forcePush never started"
                clock.advance(30.0)
            return next(readings, _VCELL_FLOOR)

        seq = _sequencer(
            events=events,
            runPipelineFn=_productionPipeline(syncTask),
            clock=clock,
            vcell=_vcell,
        )

        # Act
        try:
            seq.handleOnBattery()
        finally:
            release.set()

        # Assert
        assert events == ["poweroff"]
        assert _BlockedClient.calls == 1
        assert readerCalls == []
        assert clock() > _TOTAL_WINDOW_CAP_SEC

    def test_blockedPipeline_vcellUnreadable_blindCapStillPowersOff(self) -> None:
        """
        Given: a pipeline that never finishes AND a VCELL that cannot be read
        When: the shutdown runs
        Then: poweroff still happens once the floor has been blind for
            totalCapSec -- a hung pipeline never blocks poweroff
        """
        # Arrange
        clock = _FakeClock()
        events: list[str] = []
        release = threading.Event()

        def _vcell() -> float:
            clock.advance(10.0)
            raise OSError("i2c read failed")

        seq = _sequencer(
            events=events,
            runPipelineFn=lambda: release.wait(),
            clock=clock,
            vcell=_vcell,
        )

        # Act
        try:
            seq.handleOnBattery()
        finally:
            release.set()

        # Assert
        assert events == ["poweroff"]
        assert clock() >= _TOTAL_WINDOW_CAP_SEC

    def test_bootGraceLoss_floorNotConsultedDuringDrain_capBoundsIt(self) -> None:
        """
        Given: a loss inside bootGrace (US-788: floor suppressed) and a boot-sag
            VCELL that reads below the floor
        When: the drain runs
        Then: the low reading does not end it (the floor is not read); the old
            totalCapSec does, exactly as before this story
        """
        # Arrange
        clock = _FakeClock()
        events: list[str] = []
        release = threading.Event()
        vcellReads: list[int] = []

        def _vcell() -> float:
            vcellReads.append(1)
            return 3.30

        def _pipeline() -> None:
            while not release.wait(_POLL_SEC):
                clock.advance(5.0)

        seq = _sequencer(
            events=events, runPipelineFn=_pipeline, clock=clock, vcell=_vcell
        )

        # Act
        try:
            seq.handleOnBattery(suppressFloorFastPath=True)
        finally:
            release.set()

        # Assert
        assert events == ["poweroff"]
        assert vcellReads == []
        assert clock() >= _TOTAL_WINDOW_CAP_SEC

    def test_powerReturnsDuringDrain_pollCancels_noPoweroff(self) -> None:
        """
        Given: a drain in progress
        When: isOnBattery reads False at a poll
        Then: the sequencer stops waiting and cancels -- no poweroff
        """
        # Arrange
        clock = _FakeClock()
        events: list[str] = []
        release = threading.Event()
        onBattery = {"v": True}
        polls: list[int] = []

        def _vcell() -> float:
            polls.append(1)
            if len(polls) >= 3:
                onBattery["v"] = False
            return _HEALTHY_VCELL

        seq = _sequencer(
            events=events,
            runPipelineFn=lambda: release.wait(),
            clock=clock,
            vcell=_vcell,
            isOnBattery=lambda: onBattery["v"],
        )

        # Act
        try:
            seq.handleOnBattery()
        finally:
            release.set()

        # Assert
        assert events == []


class TestNegativeCases:
    """Away from home nothing changes; a bad reading never becomes DELIVERED."""

    def test_serverUnreachable_forcePushNeverCalled_poweroffWithoutWaiting(self) -> None:
        """
        Given: serverReachable False
        When: the shutdown runs
        Then: forcePush is never called and poweroff proceeds without waiting
            out a poll interval (regressionCheck: same time-to-poweroff)
        """
        # Arrange
        clock = _FakeClock()
        events: list[str] = []
        backlog = [9000]
        client = _DrainingClient(clock=clock, passSec=15.0, backlog=backlog)
        syncTask = SyncWithServerTask(
            serverReachable=lambda: False,
            runSync=m._buildRunSync(
                client,
                backlogReader=_readerOver(backlog),
                excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            ),
            writeRecord=lambda _r: events.append("fault-record"),
        )
        slowPoll = 5.0
        seq = ShutdownSequencer(
            isOnBattery=lambda: True,
            vcell=lambda: _HEALTHY_VCELL,
            runPipelineFn=_productionPipeline(syncTask),
            powerOffFn=lambda: events.append("poweroff"),
            vcellFloor=_VCELL_FLOOR,
            totalCapSec=_TOTAL_WINDOW_CAP_SEC,
            smoothingSec=0.0,
            smoothingPollSec=slowPoll,
            sleepFn=lambda _s: None,
            monotonicFn=clock,
        )

        # Act
        t0 = time.monotonic()
        seq.handleOnBattery()
        elapsed = time.monotonic() - t0

        # Assert
        assert client.excludeTablesPerPass == []
        assert events == ["poweroff"]
        assert elapsed < slowPoll

    def _runWithCustody(self, tmp_path: Path, *, client, reader) -> dict:
        clock = _FakeClock()
        events: list[str] = []
        recordPath = tmp_path / "custody.json"
        syncTask = SyncWithServerTask(
            serverReachable=lambda: True,
            runSync=m._buildRunSync(
                client,
                backlogReader=reader,
                excludeTables=SHUTDOWN_DRAIN_EXCLUDED_TABLES,
            ),
            writeRecord=lambda _r: None,
        )
        seq = _sequencer(
            events=events,
            runPipelineFn=_productionPipeline(syncTask),
            clock=clock,
            prePowerOffFn=makeSyncCustodyHook(
                recordPath=str(recordPath), backlogReader=reader
            ),
        )
        seq.handleOnBattery()
        assert events == ["poweroff"]
        return json.loads(recordPath.read_text(encoding="utf-8"))

    def test_unknownBacklog_endsTheDrain_recordsUnknown(self, tmp_path: Path) -> None:
        """
        Given: a backlog that cannot be read
        When: the drain runs
        Then: it ends after one pass and custody records UNKNOWN, never DELIVERED
        """
        # Arrange
        clock = _FakeClock()
        client = _DrainingClient(clock=clock, passSec=15.0, backlog=[9000])

        def _unknown(**_kw) -> SyncBacklog:
            return SyncBacklog(perTable={}, unreadableTables=("realtime_data",))

        # Act
        record = self._runWithCustody(tmp_path, client=client, reader=_unknown)

        # Assert
        assert len(client.excludeTablesPerPass) == 1
        assert record["verdict"] == BACKLOG_UNKNOWN
        assert record["verdict"] != BACKLOG_DELIVERED

    def test_failingPass_endsTheDrain_recordsOutstanding(self, tmp_path: Path) -> None:
        """
        Given: a pass that fails (tables failed after retries)
        When: the drain runs
        Then: the drain ends (after the task's one retry) and custody records
            OUTSTANDING, never DELIVERED
        """
        # Arrange
        backlog = [2000]

        class _FailingClient:
            calls = 0

            def forcePush(self, *, excludeTables=()) -> _Summary:
                _FailingClient.calls += 1
                return _Summary(rowsPushed=0, tablesFailed=1)

        # Act
        record = self._runWithCustody(
            tmp_path, client=_FailingClient(), reader=_readerOver(backlog)
        )

        # Assert -- first attempt + SyncWithServerTask's single retry
        assert _FailingClient.calls == 2
        assert record["verdict"] == BACKLOG_OUTSTANDING
        assert record["verdict"] != BACKLOG_DELIVERED
