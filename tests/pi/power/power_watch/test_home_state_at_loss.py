################################################################################
# File Name: test_home_state_at_loss.py
# Purpose/Description: US-741 -- every power loss asks the home detector once
#                      and persists its state name into the durable shutdown
#                      record (powerwatch_outcome.json), which the next boot
#                      lands as startup_log.prior_boot_home_state (US-776-f).
#                      A slow or failing detector never delays the poweroff.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-01    | Rex          | Initial -- US-741 home state at every power loss
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: ceilingSec -> joinWaitSec/stallSec.
# 2026-10-05    | Atlas (US-833) | The fast-path test asserted the defect (no
#                               sync_outcome); it now requires INTERRUPTED.
# 2026-10-11    | Rex          | US-776-k1: the key-off sweep decides AWAY /
#               |              | UNKNOWN / JOINING; stateForSync's wait bounded
# ================================================================================
################################################################################
"""The home detector is asked once per power loss and its answer is persisted."""

from __future__ import annotations

import ast
import inspect
import json
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import src.pi.network.home_detector as hd
import src.pi.power.power_watch.__main__ as m
from src.pi.network.home_detector import HomeNetworkDetector, HomeNetworkState, SweepResult
from src.pi.power.power_watch.contract import OutcomeKind
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.tasks.sync_with_server import SyncOutcomeRecord, SyncWithServerTask

_VCELL_FLOOR = 3.30
_VCELL_OK = 3.90


class _Detector:
    """getHomeNetworkState fake: counts calls; raises when given an Exception."""

    def __init__(self, answer: HomeNetworkState | Exception) -> None:
        self._answer = answer
        self.calls = 0

    def __call__(self) -> HomeNetworkState:
        self.calls += 1
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _inline(target: Callable[[], None]) -> None:
    """startFn that runs the observation on the caller's thread (deterministic)."""
    target()


def _sequencer(
    holder: m.HomeStateAtLoss,
    outcomePath: Path,
    *,
    onBattery: Callable[[], bool] = lambda: True,
    vcell: float = _VCELL_OK,
    powerOffs: list[str] | None = None,
) -> ShutdownSequencer:
    """A real ShutdownSequencer wired the way main() wires powerwatch."""
    syncTask = SyncWithServerTask(
        homeState=holder.stateForSync,
        runSync=lambda: None,
        writeRecord=holder.wrapSink(
            m.makeOutcomeSink(str(outcomePath), homeState=holder.stateName)
        ),
        joinWaitSec=120.0,
        stallSec=60.0,
        sleepFn=lambda _s: None,
        monotonic=lambda: 0.0,
    )
    offs = powerOffs if powerOffs is not None else []
    return ShutdownSequencer(
        isOnBattery=onBattery,
        vcell=lambda: vcell,
        runPipelineFn=syncTask.run,
        powerOffFn=lambda: offs.append("poweroff"),
        vcellFloor=_VCELL_FLOOR,
        totalCapSec=45.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        prePowerOffFn=holder.ensureRecorded,
        powerLossObservedFn=holder.observe,
    )


def _record(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "answer",
    [
        HomeNetworkState.AWAY,
        HomeNetworkState.AT_HOME_SERVER_REACHABLE,
        HomeNetworkState.UNKNOWN,
    ],
)
def test_powerLoss_persistsDetectorState_calledExactlyOnce(
    tmp_path: Path, answer: HomeNetworkState
) -> None:
    """
    Given: a detector answering AWAY / AT_HOME_SERVER_REACHABLE / UNKNOWN
    When: a sustained power loss runs the sequencer through the sync task
    Then: the durable record's home_state is that state's name, and the
          detector was called exactly once for the loss
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    detector = _Detector(answer)
    holder = m.HomeStateAtLoss(detector, outcomePath=str(outcomePath), startFn=_inline)
    powerOffs: list[str] = []

    # Act
    _sequencer(holder, outcomePath, powerOffs=powerOffs).handleOnBattery()

    # Assert
    record = _record(outcomePath)
    assert record["home_state"] == answer.name
    assert detector.calls == 1
    assert powerOffs == ["poweroff"]
    assert "sync_outcome" in record  # the sync task's record carries it too


def test_powerLoss_detectorRaises_persistsUnknown(tmp_path: Path) -> None:
    """
    Given: a detector that raises
    When: a power loss runs to poweroff
    Then: home_state is 'UNKNOWN', never empty, and the poweroff happened
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    detector = _Detector(OSError("nmcli exploded"))
    holder = m.HomeStateAtLoss(detector, outcomePath=str(outcomePath), startFn=_inline)
    powerOffs: list[str] = []

    # Act
    _sequencer(holder, outcomePath, powerOffs=powerOffs).handleOnBattery()

    # Assert
    assert _record(outcomePath)["home_state"] == "UNKNOWN"
    assert detector.calls == 1
    assert powerOffs == ["poweroff"]


def test_floorFastPath_skipsPipeline_stillPersistsHomeState(tmp_path: Path) -> None:
    """
    Given: VCELL already at the floor, so the sequencer skips the pipeline
    When: the power loss powers off at once
    Then: the record still carries the detector's answer, sync_outcome reads
          INTERRUPTED, and the detector was called once

    US-833 (2026-10-05): this test used to assert ``"sync_outcome" not in
    record`` -- it PINNED the defect (a fast-path poweroff left the
    shutdown-sync record silent, so prior_boot_sync_* landed NULL). Do not
    restore that assertion: silence must not be the floor's signature.
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    detector = _Detector(HomeNetworkState.AT_HOME_SERVER_REACHABLE)
    holder = m.HomeStateAtLoss(detector, outcomePath=str(outcomePath), startFn=_inline)
    powerOffs: list[str] = []

    # Act
    _sequencer(holder, outcomePath, vcell=3.00, powerOffs=powerOffs).handleOnBattery()

    # Assert
    record = _record(outcomePath)
    assert record["home_state"] == "AT_HOME_SERVER_REACHABLE"
    assert record["sync_outcome"] == OutcomeKind.INTERRUPTED.name
    assert detector.calls == 1
    assert powerOffs == ["poweroff"]


def test_blip_persistsHomeState_noPoweroff(tmp_path: Path) -> None:
    """
    Given: a power-lost signal that does not survive smoothing (a blip)
    When: the sequencer cancels
    Then: the loss was still observed once and its home state persisted
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    detector = _Detector(HomeNetworkState.AWAY)
    holder = m.HomeStateAtLoss(detector, outcomePath=str(outcomePath), startFn=_inline)
    powerOffs: list[str] = []

    # Act
    _sequencer(
        holder, outcomePath, onBattery=lambda: False, powerOffs=powerOffs
    ).handleOnBattery()

    # Assert
    assert _record(outcomePath)["home_state"] == "AWAY"
    assert detector.calls == 1
    assert powerOffs == []


def test_slowDetector_neverDelaysPoweroff_recordsUnknown(tmp_path: Path) -> None:
    """
    Given: a detector that has not answered by the time the floor fast path
           powers off (real thread, blocked on an event)
    When: the power loss powers off
    Then: the poweroff is not held up, home_state reads 'UNKNOWN', and the
          late answer does not overwrite the record already written
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    release = threading.Event()
    entered = threading.Event()
    calls: list[int] = []

    def slowDetector() -> HomeNetworkState:
        calls.append(1)
        entered.set()
        release.wait(timeout=10.0)
        return HomeNetworkState.AT_HOME_SERVER_REACHABLE

    threads: list[threading.Thread] = []

    def startFn(target: Callable[[], None]) -> None:
        th = threading.Thread(target=target, daemon=True)
        threads.append(th)
        th.start()

    holder = m.HomeStateAtLoss(slowDetector, outcomePath=str(outcomePath), startFn=startFn)
    powerOffs: list[str] = []

    # Act
    _sequencer(holder, outcomePath, vcell=3.00, powerOffs=powerOffs).handleOnBattery()
    poweredOffBeforeAnswer = powerOffs == ["poweroff"] and not release.is_set()
    assert entered.wait(timeout=5.0)
    release.set()
    threads[0].join(timeout=5.0)

    # Assert
    assert poweredOffBeforeAnswer
    assert _record(outcomePath)["home_state"] == "UNKNOWN"
    assert calls == [1]


def test_secondLoss_asksDetectorAgain(tmp_path: Path) -> None:
    """
    Given: a blip, then a real loss, in one boot
    When: each runs through the sequencer
    Then: each loss asks the detector once (two calls), and the record holds
          the second loss's answer
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    answers = iter([HomeNetworkState.AWAY, HomeNetworkState.AT_HOME_SERVER_REACHABLE])
    calls: list[int] = []

    def detector() -> HomeNetworkState:
        calls.append(1)
        return next(answers)

    holder = m.HomeStateAtLoss(detector, outcomePath=str(outcomePath), startFn=_inline)

    # Act
    _sequencer(holder, outcomePath, onBattery=lambda: False).handleOnBattery()
    _sequencer(holder, outcomePath).handleOnBattery()

    # Assert
    assert len(calls) == 2
    assert _record(outcomePath)["home_state"] == "AT_HOME_SERVER_REACHABLE"


def test_main_wiresHomeStateAtLossIntoTheLossPath() -> None:
    """
    Given: the production entrypoint
    When: main()'s source is parsed
    Then: the loss hook starts the observation, the sync task reads it, its
          sink is serialised with it, and the pre-poweroff hook backs it up
    """
    # Arrange
    tree = ast.parse(inspect.getsource(m.main))
    source = ast.unparse(tree)

    # Assert
    assert "HomeStateAtLoss(detector.getHomeNetworkState" in source
    assert "homeState=homeStateAtLoss.stateForSync" in source
    assert "homeStateAtLoss.wrapSink(" in source
    sinkCalls = [
        {kw.arg: ast.unparse(kw.value) for kw in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "makeOutcomeSink"
    ]
    assert any(
        c.get("homeState") == "homeStateAtLoss.stateName"
        and c.get("wallVcell") == "homeStateAtLoss.vcellBeforeCut"
        for c in sinkCalls
    )
    composed = [
        [ast.unparse(arg) for arg in node.args]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "composePrePowerOffHooks"
    ]
    assert ["lossHeartbeat.start", "loadShedder.shed", "homeStateAtLoss.observe"] in composed
    assert any("homeStateAtLoss.ensureRecorded" in args for args in composed)


def test_joiningPolls_readLive_persistAtLossAnswer(tmp_path: Path) -> None:
    """
    Given: the loss-time answer is AT_HOME_JOINING and a later poll associates
    When: the sync task waits for the rejoin and drains
    Then: the polls read the detector live, and the persisted home_state is
          the answer at the power loss (AT_HOME_JOINING)
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    answers = iter(
        [HomeNetworkState.AT_HOME_JOINING, HomeNetworkState.AT_HOME_SERVER_REACHABLE]
    )
    calls: list[int] = []

    def detector() -> HomeNetworkState:
        calls.append(1)
        return next(answers)

    holder = m.HomeStateAtLoss(detector, outcomePath=str(outcomePath), startFn=_inline)

    # Act
    _sequencer(holder, outcomePath).handleOnBattery()

    # Assert
    record = _record(outcomePath)
    assert len(calls) == 2
    assert record["home_state"] == "AT_HOME_JOINING"
    assert record["sync_outcome"] == "DELIVERED"


def test_secondsSinceLoss_measuresFromObserve_andIsZeroBefore() -> None:
    """One loss time, stamped in observe() on the injected monotonic clock."""
    clock = [100.0]
    h = m.HomeStateAtLoss(
        lambda: HomeNetworkState.AWAY, outcomePath="unused.json",
        startFn=lambda _t: None, monotonicFn=lambda: clock[0],
        wallIsoFn=lambda: "2026-10-02T17:00:00Z",
    )
    assert h.secondsSinceLoss() == 0.0 and h.lossIso() is None
    h.observe()
    clock[0] = 142.5
    assert h.secondsSinceLoss() == 42.5 and h.lossIso() == "2026-10-02T17:00:00Z"


def test_main_wiresTheMonthlyHoldTask_boundedBySequencer() -> None:
    source = ast.unparse(ast.parse(inspect.getsource(m.main)))
    assert "secondsSinceCut=homeStateAtLoss.secondsSinceLoss" in source
    assert "buildV1Tasks(syncTask, holdTask)" in source
    assert "sequencerBoundedTasks=(syncTask.name, holdTask.name)" in source
    assert "660" not in source and "testHoldSec" not in source


# =============================================================================
# US-776-k1: every key-off decides home from a fresh sweep, not the cache
# =============================================================================


class _Sweep:
    """detector.sweep fake: counts calls, returns a fixed SweepResult."""

    def __init__(self, result: SweepResult) -> None:
        self._result = result
        self.calls = 0

    def __call__(self) -> SweepResult:
        self.calls += 1
        return self._result


@pytest.mark.parametrize(
    ("sweepResult", "expected"),
    [
        (SweepResult.NOT_VISIBLE, HomeNetworkState.AWAY),
        (SweepResult.FAILED, HomeNetworkState.UNKNOWN),
        (SweepResult.VISIBLE, HomeNetworkState.AT_HOME_JOINING),
    ],
)
def test_US776k1_sweepAlone_decidesAwayUnknownJoining_noDetectorRead(
    tmp_path: Path, sweepResult: SweepResult, expected: HomeNetworkState
) -> None:
    """
    Given: a key-off whose sweep reads NOT_VISIBLE / FAILED / VISIBLE
    When: the loss is observed and the sync task asks for the state
    Then: AWAY / UNKNOWN / AT_HOME_JOINING, decided by the sweep ALONE -- the
          cached detector read is never called -- and that name is persisted
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    detector = _Detector(HomeNetworkState.AT_HOME_SERVER_REACHABLE)
    sweep = _Sweep(sweepResult)
    holder = m.HomeStateAtLoss(
        detector, outcomePath=str(outcomePath), startFn=_inline,
        sweep=sweep, observationTimeoutSec=13.0,
    )

    # Act
    holder.observe()
    state = holder.stateForSync()

    # Assert
    assert state is expected
    assert sweep.calls == 1
    assert detector.calls == 0
    assert _record(outcomePath)["home_state"] == expected.name


def test_US776k1_sweepActiveHome_continuesOnTheDetectorPath(tmp_path: Path) -> None:
    """
    Given: a key-off whose sweep reads ACTIVE_HOME (wlan0 associated to home)
    When: the loss is observed
    Then: the sweep runs FIRST, then the existing detector read decides the
          state (server reachable / down), called once
    """
    # Arrange
    order: list[str] = []
    outcomePath = tmp_path / "powerwatch_outcome.json"

    def sweep() -> SweepResult:
        order.append("sweep")
        return SweepResult.ACTIVE_HOME

    def detector() -> HomeNetworkState:
        order.append("detector")
        return HomeNetworkState.AT_HOME_SERVER_DOWN

    holder = m.HomeStateAtLoss(
        detector, outcomePath=str(outcomePath), startFn=_inline,
        sweep=sweep, observationTimeoutSec=13.0,
    )

    # Act
    holder.observe()
    state = holder.stateForSync()

    # Assert
    assert state is HomeNetworkState.AT_HOME_SERVER_DOWN
    assert order == ["sweep", "detector"]


def test_US776k1_sweepRaises_readsUnknown_neverAway(tmp_path: Path) -> None:
    """A sweep that raises (it should not) is a scan with no answer: UNKNOWN."""
    # Arrange
    detector = _Detector(HomeNetworkState.AWAY)

    def sweep() -> SweepResult:
        raise OSError("nmcli exploded")

    holder = m.HomeStateAtLoss(
        detector, outcomePath=str(tmp_path / "o.json"), startFn=_inline,
        sweep=sweep, observationTimeoutSec=13.0,
    )

    # Act
    holder.observe()

    # Assert
    assert holder.stateForSync() is HomeNetworkState.UNKNOWN
    assert detector.calls == 0


def test_US776k1_observationNeverReturns_stateForSyncBoundedReturnsUnknown(
    tmp_path: Path,
) -> None:
    """
    Given: an observation that never returns (its thread never runs) and a
           fake wait that reports the bound expiring -- no real sleep
    When: the sync task asks for this loss's state
    Then: the wait is bounded by the WHOLE observation's bound, the answer is
          UNKNOWN (never AWAY), the detector is not called in its place, and
          the persisted state agrees with what the sync acted on
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    detector = _Detector(HomeNetworkState.AWAY)
    sweep = _Sweep(SweepResult.NOT_VISIBLE)
    waits: list[float] = []

    def waitFn(_event: threading.Event, timeout: float) -> bool:
        waits.append(timeout)
        return False

    holder = m.HomeStateAtLoss(
        detector, outcomePath=str(outcomePath), startFn=lambda _t: None,
        sweep=sweep, observationTimeoutSec=13.0, waitFn=waitFn,
    )

    # Act
    holder.observe()
    state = holder.stateForSync()

    # Assert
    assert state is HomeNetworkState.UNKNOWN
    assert waits == [13.0]
    assert detector.calls == 0 and sweep.calls == 0
    assert holder.stateName() == "UNKNOWN"


def test_US776k1_lateAnswerAfterTimeout_doesNotReplaceTheUnknownTheSyncUsed(
    tmp_path: Path,
) -> None:
    """A timed-out observation's late answer does not relabel the loss."""
    # Arrange
    deferred: list[Callable[[], None]] = []
    holder = m.HomeStateAtLoss(
        _Detector(HomeNetworkState.AWAY), outcomePath=str(tmp_path / "o.json"),
        startFn=deferred.append, sweep=_Sweep(SweepResult.NOT_VISIBLE),
        observationTimeoutSec=13.0, waitFn=lambda _e, _t: False,
    )
    holder.observe()
    assert holder.stateForSync() is HomeNetworkState.UNKNOWN

    # Act -- the observation finally finishes
    deferred[0]()

    # Assert
    assert holder.stateName() == "UNKNOWN"


def test_US776k1_awayKeyOff_addsNoWaitBeyondTheSmoothingWindow(tmp_path: Path) -> None:
    """
    Given: a 7 s smoothing window on a virtual clock, and an away key-off
           whose sweep (NOT_VISIBLE) runs in parallel with that window
    When: the sequencer confirms the loss and runs the sync task
    Then: the Pi powers off at t = 7 s exactly -- the sync's state read did
          not wait (the observation had already answered) -- with outcome AWAY
    """
    # Arrange
    outcomePath = tmp_path / "powerwatch_outcome.json"
    clock = [0.0]
    deferred: list[Callable[[], None]] = []
    waits: list[float] = []
    powerOffAt: list[float] = []

    def sleepFn(seconds: float) -> None:
        # The observation thread runs during the window: start it on the
        # window's first poll, as a real daemon thread would.
        while deferred:
            deferred.pop()()
        clock[0] += seconds

    def waitFn(event: threading.Event, timeout: float) -> bool:
        waits.append(timeout)
        return event.is_set()

    detector = _Detector(HomeNetworkState.AT_HOME_SERVER_REACHABLE)
    holder = m.HomeStateAtLoss(
        detector, outcomePath=str(outcomePath), startFn=deferred.append,
        sweep=_Sweep(SweepResult.NOT_VISIBLE), observationTimeoutSec=13.0,
        waitFn=waitFn, monotonicFn=lambda: clock[0],
    )
    syncTask = SyncWithServerTask(
        homeState=holder.stateForSync,
        runSync=lambda: None,
        writeRecord=holder.wrapSink(
            m.makeOutcomeSink(str(outcomePath), homeState=holder.stateName)
        ),
        joinWaitSec=120.0,
        stallSec=60.0,
        sleepFn=sleepFn,
        monotonic=lambda: clock[0],
    )
    sequencer = ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: _VCELL_OK,
        runPipelineFn=syncTask.run,
        powerOffFn=lambda: powerOffAt.append(clock[0]),
        vcellFloor=_VCELL_FLOOR,
        totalCapSec=45.0,
        smoothingSec=7.0,
        smoothingPollSec=1.0,
        sleepFn=sleepFn,
        monotonicFn=lambda: clock[0],
        prePowerOffFn=holder.ensureRecorded,
        powerLossObservedFn=holder.observe,
    )

    # Act
    sequencer.handleOnBattery()

    # Assert
    assert powerOffAt == [7.0]
    assert waits == [13.0]  # one bounded wait, already answered
    assert detector.calls == 0
    record = _record(outcomePath)
    assert record["home_state"] == "AWAY"
    assert record["sync_outcome"] == OutcomeKind.AWAY.name


def test_US776k1_replay_20261011_131447_cacheWithoutHome_sweepVisible_isJoining(
    tmp_path: Path,
) -> None:
    """
    Given: the 2026-10-11 13:14:47 key-off -- wlan0 not associated, the cached
           scan list WITHOUT home (so the cached read says AWAY), and a fresh
           sweep that lists home ('DeathstarWifi', config 'DeathStarWiFi')
    When: the key-off is observed through a REAL HomeNetworkDetector
    Then: the state is AT_HOME_JOINING, not AWAY
    """
    # Arrange
    def sweepRunner(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="no:Neighbor5G\nno:DeathstarWifi\n", stderr="",
        )

    detector = HomeNetworkDetector(
        {"pi": {"homeNetwork": {"ssid": "DeathStarWiFi", "sweepTimeoutSec": 6}}},
        ssidReader=lambda: "",
        scanReader=lambda: ["Neighbor5G"],
        ipReader=lambda: [],
        sweepRunner=sweepRunner,
    )
    assert detector.getHomeNetworkState() is HomeNetworkState.AWAY  # today's answer
    holder = m.HomeStateAtLoss(
        detector.getHomeNetworkState, outcomePath=str(tmp_path / "o.json"),
        startFn=_inline, sweep=detector.sweep,
        observationTimeoutSec=detector.observationBoundSec,
    )

    # Act
    holder.observe()

    # Assert
    assert holder.stateForSync() is HomeNetworkState.AT_HOME_JOINING


def test_US776k1_observationBound_isSweepPlusTheDetectorsOwnBoundedCalls() -> None:
    """
    The whole observation's bound: the sweep timeout plus the worst case of
    getHomeNetworkState (SSID read, cache read, IP read, server probe).
    """
    # Arrange
    detector = HomeNetworkDetector(
        {"pi": {"homeNetwork": {"sweepTimeoutSec": 6, "pingTimeoutSeconds": 3}}}
    )

    # Assert
    assert detector.observationBoundSec == pytest.approx(
        6 + 2 * hd._NMCLI_TIMEOUT_SECONDS + hd._HOSTNAME_TIMEOUT_SECONDS + 3
    )


def test_US776k1_main_wiresTheSweepAndTheBoundIntoHomeStateAtLoss() -> None:
    """main() hands HomeStateAtLoss the detector's sweep and observation bound."""
    tree = ast.parse(inspect.getsource(m.main))
    calls = [
        {kw.arg: ast.unparse(kw.value) for kw in node.keywords}
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "HomeStateAtLoss"
    ]
    assert len(calls) == 1
    assert calls[0].get("sweep") == "detector.sweep"
    assert calls[0].get("observationTimeoutSec") == "detector.observationBoundSec"


def test_everyRecordPath_carriesTheLossTime_asLossAt(tmp_path: Path) -> None:
    """ARCH-065 T6 fix: the one loss time (lossIso) rides on the home-state, floor-end
    and sync-sink records, so the next boot can find the loss's drain row."""
    outcomePath = tmp_path / "powerwatch_outcome.json"
    h = m.HomeStateAtLoss(
        lambda: HomeNetworkState.AWAY, outcomePath=str(outcomePath), startFn=_inline,
        wallIsoFn=lambda: "2026-10-02T17:00:00Z",
    )
    h.observe()
    assert _record(outcomePath)["loss_at"] == "2026-10-02T17:00:00Z"
    outcomePath.unlink()
    h.recordFloorEnd()
    assert _record(outcomePath)["loss_at"] == "2026-10-02T17:00:00Z"
    outcomePath.unlink()
    sink = m.makeOutcomeSink(str(outcomePath), lossAt=h.lossIso)
    sink(SyncOutcomeRecord(OutcomeKind.DELIVERED, "ok", 1, 0, None, None))
    assert _record(outcomePath)["loss_at"] == "2026-10-02T17:00:00Z"
    assert "lossAt=homeStateAtLoss.lossIso" in ast.unparse(ast.parse(inspect.getsource(m.main)))
