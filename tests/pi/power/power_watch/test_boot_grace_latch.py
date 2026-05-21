################################################################################
# File Name: test_boot_grace_latch.py
# Purpose/Description: US-344 / Sprint 40 / V0.27.16 -- F-7 boot-grace latch
#                      regression gate. The Atlas + CIO live in-car drill on
#                      2026-05-20 reproduced a state-machine bug in the
#                      __main__._pldWatchLoop polling loop: an in-grace
#                      power-loss event ignored at line ~308 latched
#                      prevLost=True, so the post-grace edge-only check
#                      (lost AND not prevLost) was permanently False if the
#                      HAT did not toggle the GPIO6 line back to HIGH. The
#                      sequencer stayed silent for 5.5 min (Test 2 capture)
#                      while GPIO6 stayed LOW and the HAT drained.
#
#                      These tests pin the fix: post-boot-grace fires on
#                      LEVEL (lost AND not firedAlready), not EDGE. The
#                      in-grace branch keeps edge-only logging so a single
#                      transient logs the "ignoring" line once, not every
#                      poll. The firedAlready guard prevents double-fire
#                      after handleOnBattery has been called.
#
#                      Smoothing path (handleOnBattery internal VCELL
#                      averaging) is the abort surface for transient glitches
#                      that resolve mid-window; that is owned by controller.py
#                      and is NOT re-tested here (preserved-by-construction).
# Author: (US-344 F-7 fix 2026-05-20)
# Creation Date: 2026-05-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-20    | US-344  | Initial -- F-7 boot-grace latch regression gate.
# ================================================================================
################################################################################
"""F-7 regression gate: in-grace transient + level-stuck-LOW post-grace must
fire the ShutdownSequencer (not silently latch the loop blind).

Atlas finding: offices/architect/findings/2026-05-20-shutdown-sequencer-
boot-grace-latch-bug.md (live in-car drill 2026-05-20, Test 2 reproducer).
"""
from __future__ import annotations

import threading

from src.pi.power.power_watch.__main__ import _runPldWatchLoop


class _FakeSequencer:
    """Records handleOnBattery() invocations. Fast return (no smoothing /
    pipeline / poweroff) so the test exercises the trigger logic only --
    the smoothing path is unit-tested in test_controller.py."""

    def __init__(self) -> None:
        self.fireCount = 0

    def handleOnBattery(self) -> None:
        self.fireCount += 1


class _CountingStop:
    """Duck-typed stop.wait(timeout=...) that returns False for the first
    ``maxIters`` calls then True, bounding the loop deterministically
    without real timing."""

    def __init__(self, maxIters: int) -> None:
        self._calls = 0
        self._maxIters = maxIters

    def wait(self, timeout: float) -> bool:  # noqa: ARG002 -- duck-typed
        self._calls += 1
        return self._calls > self._maxIters


def _runLoop(
    *,
    states: list[bool],
    times: list[float],
    bootGraceSec: float,
    maxIters: int,
    sequencer: _FakeSequencer,
) -> None:
    """Drive _runPldWatchLoop with a scripted isPowerLost sequence and clock.

    ``states[0]`` is consumed by the init prevLost read; subsequent entries
    are consumed one-per-iteration. ``times`` are consumed once per loop
    iteration (the init read does not call monotonicFn).
    """
    statesIter = iter(states)
    timesIter = iter(times)
    _runPldWatchLoop(
        isPowerLostFn=lambda: next(statesIter, states[-1]),
        stop=_CountingStop(maxIters),
        serviceStartMono=0.0,
        bootGraceSec=bootGraceSec,
        pldPollSec=0.001,
        pldGpioPin=6,
        handleLock=threading.Lock(),
        shutdownSequencer=sequencer,
        monotonicFn=lambda: next(timesIter, 999.0),
    )


def test_inGraceTransient_thenLevelStuckPostGrace_firesShutdown():
    """THE F-7 fix gate. Atlas + CIO Test 2 reproducer: a power-loss event
    during boot-grace, then GPIO6 stays LOW past boot-grace expiry. Pre-fix
    the sequencer was silent for 5.5 min (edge-only post-grace check, prevLost
    latched True by the in-grace ignore). Post-fix the sequencer fires on
    LEVEL the first post-grace tick.
    """
    sequencer = _FakeSequencer()
    # init: healthy. iter1 (in-grace t=10ms): transient lost. iter2 (in-grace
    # t=20ms): still lost. iter3 (POST-grace t=60ms): level-stuck lost -> FIRE.
    # iter4 (post-grace t=70ms): still lost, but firedAlready guard prevents
    # double-fire.
    _runLoop(
        states=[False, True, True, True, True],
        times=[0.010, 0.020, 0.060, 0.070],
        bootGraceSec=0.050,
        maxIters=4,
        sequencer=sequencer,
    )
    assert sequencer.fireCount == 1, (
        f"F-7: expected 1 fire (level-stuck-LOW post-grace), got "
        f"{sequencer.fireCount}. Edge-only check latched the sequencer blind."
    )


def test_freshBoot_noInGraceTransient_postGraceLoss_firesShutdown():
    """Atlas Test 1 control (Cycle-A happy path): clean boot, healthy through
    boot-grace, then post-grace key-off. Must fire. Pre-fix AND post-fix
    pass this -- guards against regressing the Sprint 39 IRL-accepted path.
    """
    sequencer = _FakeSequencer()
    # init: healthy. iter1 (post-grace, t=60ms): still healthy. iter2 (t=70ms):
    # fresh edge False->True (key-off) -> FIRE.
    _runLoop(
        states=[False, False, True, True],
        times=[0.060, 0.070, 0.080],
        bootGraceSec=0.050,
        maxIters=2,
        sequencer=sequencer,
    )
    assert sequencer.fireCount == 1, (
        f"Regression: Cycle-A happy path failed to fire ({sequencer.fireCount} fires)"
    )


def test_inGraceTransient_thenRecovery_postGraceFreshLoss_firesShutdown():
    """Atlas Test 2 phase 2 recovery path: in-grace transient that recovers
    (HAT comes back HIGH), then post-grace fresh edge (key-off). Must fire.
    Verifies recovery in-grace doesn't latch the loop in a wrong state for
    a subsequent fresh edge.
    """
    sequencer = _FakeSequencer()
    # init: healthy. iter1 (in-grace t=10ms): transient lost. iter2 (in-grace
    # t=20ms): recovered. iter3 (post-grace t=60ms): fresh loss -> FIRE.
    _runLoop(
        states=[False, True, False, True, True],
        times=[0.010, 0.020, 0.060, 0.070],
        bootGraceSec=0.050,
        maxIters=3,
        sequencer=sequencer,
    )
    assert sequencer.fireCount == 1, (
        f"Test 2 phase 2 recovery path failed ({sequencer.fireCount} fires)"
    )


def test_firedAlready_preventsDoubleFire_postGrace():
    """Once handleOnBattery has fired, level-stuck post-grace must not re-fire.
    handleOnBattery is state-tracked internally; double-fire would race with
    the running pipeline. The firedAlready flag is the re-entry guard now
    that the post-grace check is level-based.
    """
    sequencer = _FakeSequencer()
    # All ticks post-grace, all lost. Must fire EXACTLY once.
    _runLoop(
        states=[False, True, True, True, True, True, True],
        times=[0.100, 0.200, 0.300, 0.400, 0.500],
        bootGraceSec=0.050,
        maxIters=5,
        sequencer=sequencer,
    )
    assert sequencer.fireCount == 1, (
        f"firedAlready guard broken: {sequencer.fireCount} fires "
        f"(level-stuck-LOW should fire exactly once, not every poll)"
    )
