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
# ================================================================================
################################################################################
"""The home detector is asked once per power loss and its answer is persisted."""

from __future__ import annotations

import ast
import inspect
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import src.pi.power.power_watch.__main__ as m
from src.pi.network.home_detector import HomeNetworkState
from src.pi.power.power_watch.controller import ShutdownSequencer
from src.pi.power.power_watch.tasks.sync_with_server import SyncWithServerTask

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
    Then: the record still carries the detector's answer (no sync ran, so no
          sync_outcome), and the detector was called once
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
    assert "sync_outcome" not in record
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
    assert "homeState=homeStateAtLoss.stateName" in source
    assert "makeOutcomeSink(outcomePath" in source
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
