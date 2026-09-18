################################################################################
# File Name: test_boot_grace_scope.py
# Purpose/Description: US-788 -- bootGrace scopes the VCELL floor fast path,
#                      not the TRIGGER. An in-grace PLD loss runs the normal
#                      path (loss hook = shed + heartbeat, smoothing, bounded
#                      pipeline, graceful poweroff) with only the floor fast
#                      path suppressed. Outside grace behaviour is unchanged,
#                      floor fast path included.
# Author: Rex (Ralph)
# Creation Date: 2026-09-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-09-17    | Rex     | Initial -- US-788.
# ================================================================================
################################################################################
"""US-788: bootGrace stops gating the trigger; only the VCELL floor fast path."""
from __future__ import annotations

import threading

from src.common.config.validator import DEFAULTS
from src.pi.power.power_watch.__main__ import _runPldWatchLoop
from src.pi.power.power_watch.controller import ShutdownSequencer

BOOT_GRACE_SEC = 120.0
VCELL_FLOOR = 3.50


class _CountingStop:
    """stop.wait() that returns False ``maxIters`` times, then True."""

    def __init__(self, maxIters: int) -> None:
        self._calls = 0
        self._maxIters = maxIters

    def wait(self, timeout: float) -> bool:  # noqa: ARG002 -- duck-typed
        self._calls += 1
        return self._calls > self._maxIters


class _RecordingSequencer:
    """Records every handleOnBattery call's keyword arguments."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def handleOnBattery(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def _runLoop(*, states: list[bool], times: list[float], sequencer: object) -> None:
    """Drive the watch loop: states[0] is the init read, then one per tick."""
    statesIter = iter(states)
    timesIter = iter(times)
    _runPldWatchLoop(
        isPowerLostFn=lambda: next(statesIter, states[-1]),
        stop=_CountingStop(len(times)),
        serviceStartMono=0.0,
        bootGraceSec=BOOT_GRACE_SEC,
        pldPollSec=0.0,
        pldGpioPin=6,
        handleLock=threading.Lock(),
        shutdownSequencer=sequencer,
        monotonicFn=lambda: next(timesIter, 999.0),
    )


def _sequencer(*, vcellVolts: float, calls: list[str]) -> ShutdownSequencer:
    return ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: vcellVolts,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=VCELL_FLOOR,
        totalCapSec=2.0,
        smoothingSec=0.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        prePowerOffFn=lambda: calls.append("drainClose"),
        powerLossObservedFn=lambda: calls.append("shed+heartbeat"),
        powerRestoredFn=lambda: calls.append("restore"),
    )


# --- the watch loop: the trigger is no longer gated ---------------------------


def test_lossAtT10_insideGrace_callsHandleOnBattery_withFloorFastPathSuppressed():
    sequencer = _RecordingSequencer()

    _runLoop(states=[False, True], times=[10.0], sequencer=sequencer)

    assert sequencer.calls == [{"suppressFloorFastPath": True}]


def test_lossAtT200_outsideGrace_callsHandleOnBattery_exactlyAsBefore():
    sequencer = _RecordingSequencer()

    _runLoop(states=[False, True], times=[200.0], sequencer=sequencer)

    assert sequencer.calls == [{}]  # the pre-US-788 bare call


def test_inGraceLoss_stillLost_doesNotRefireEveryPoll():
    sequencer = _RecordingSequencer()

    _runLoop(states=[False, True, True, True], times=[10.0, 11.0, 12.0], sequencer=sequencer)

    assert len(sequencer.calls) == 1


def test_inGraceBlip_thenPostGraceLoss_stillFiresPostGrace():
    """An in-grace fire must not consume the post-grace firedAlready guard."""
    sequencer = _RecordingSequencer()

    _runLoop(
        states=[False, True, False, True],
        times=[10.0, 11.0, 200.0],
        sequencer=sequencer,
    )

    assert sequencer.calls == [{"suppressFloorFastPath": True}, {}]


def test_inGraceLoss_whileHandleInFlight_isNotReentered():
    sequencer = _RecordingSequencer()
    lock = threading.Lock()
    lock.acquire()
    statesIter = iter([False, True])

    _runPldWatchLoop(
        isPowerLostFn=lambda: next(statesIter, True),
        stop=_CountingStop(1),
        serviceStartMono=0.0,
        bootGraceSec=BOOT_GRACE_SEC,
        pldPollSec=0.0,
        pldGpioPin=6,
        handleLock=lock,
        shutdownSequencer=sequencer,
        monotonicFn=lambda: 10.0,
    )

    assert sequencer.calls == []


# --- the validation criteria, end to end through the real sequencer -----------


def test_lossAtT10_vcellHealthy_runsTheWholeNormalPath():
    calls: list[str] = []

    _runLoop(states=[False, True], times=[10.0], sequencer=_sequencer(vcellVolts=3.9, calls=calls))

    assert calls == ["shed+heartbeat", "pipeline", "drainClose", "poweroff"]


def test_lossAtT10_vcellBelowFloor_runsPipeline_floorFastPathNotTaken():
    calls: list[str] = []

    _runLoop(states=[False, True], times=[10.0], sequencer=_sequencer(vcellVolts=3.30, calls=calls))

    assert calls == ["shed+heartbeat", "pipeline", "drainClose", "poweroff"]


def test_lossAtT200_vcellBelowFloor_takesFloorFastPath_asToday():
    calls: list[str] = []

    _runLoop(
        states=[False, True], times=[200.0], sequencer=_sequencer(vcellVolts=3.30, calls=calls)
    )

    assert calls == ["shed+heartbeat", "drainClose", "poweroff"]


def test_suppressedFloorFastPath_inGraceBlip_stillCancelsAndRestores():
    calls: list[str] = []
    reads = iter([True, False])
    sequencer = ShutdownSequencer(
        isOnBattery=lambda: next(reads, False),
        vcell=lambda: 3.30,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=VCELL_FLOOR,
        totalCapSec=2.0,
        smoothingSec=1.0,
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
        powerLossObservedFn=lambda: calls.append("shed+heartbeat"),
        powerRestoredFn=lambda: calls.append("restore"),
    )

    sequencer.handleOnBattery(suppressFloorFastPath=True)

    assert calls == ["shed+heartbeat", "restore"]


def test_suppressedFloorFastPath_doesNotReadVcell():
    """The suppression reuses the failed-read branch; there is nothing to read."""
    calls: list[str] = []

    def _vcell() -> float:
        calls.append("vcellRead")
        return 3.30

    sequencer = _sequencer(vcellVolts=3.30, calls=calls)
    sequencer._vcell = _vcell

    sequencer.handleOnBattery(suppressFloorFastPath=True)

    assert "vcellRead" not in calls
    assert "pipeline" in calls


# --- scope, not duration -------------------------------------------------------


def test_noPowerWatchConstantChanged():
    assert DEFAULTS["pi.powerWatch.bootGraceSec"] == 120
    assert DEFAULTS["pi.powerWatch.smoothingSec"] == 5
    assert DEFAULTS["pi.powerWatch.vcellFloorVolts"] == 3.50
