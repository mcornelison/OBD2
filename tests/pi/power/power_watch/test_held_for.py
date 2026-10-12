################################################################################
# File Name: test_held_for.py
# Purpose/Description: US-748-a -- the one shared dwell helper, heldFor(), that
#                      both power directions use: the loss window
#                      (_smoothedPowerLost) and the late arm (US-748-b/c).
#                      Driven by an injected clock: no real sleeps.
# Author: Rex (Ralph)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-10-11    | Rex (US-748-a) | Initial.
# ================================================================================
################################################################################
from src.pi.power.power_watch.controller import ShutdownSequencer, heldFor


class _FakeClock:
    """A monotonic clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _reads(*values: bool):
    """A predicate replaying ``values`` one per call, then raising if over-read."""
    it = iter(values)
    calls: list[bool] = []

    def predicate() -> bool:
        value = next(it)
        calls.append(value)
        return value

    predicate.calls = calls  # type: ignore[attr-defined]
    return predicate


def test_heldFor_heldForFullDwell_returnsTrueAtDwell():
    """
    Given: a predicate that holds on every 1 s poll
    When: heldFor waits for a 7 s dwell
    Then: True, at t = 7 s, after exactly 7 polls
    """
    clock = _FakeClock()
    predicate = _reads(*([True] * 8))

    result = heldFor(predicate, 7.0, 1.0, clock.sleep, clock.monotonic)

    assert result is True
    assert clock.now == 7.0
    assert len(predicate.calls) == 8  # the start read + one per poll


def test_heldFor_brokenOnePollBeforeDwell_restartsTheRun():
    """
    Given: present x6, absent x1, then present
    When: heldFor waits for a 7 s dwell with restart-on-break (the default)
    Then: it does not return at 6 s; it keeps waiting and returns True only after
          an unbroken 7 s run that starts at the next present read
    """
    clock = _FakeClock()
    # t=0..5 present (6 reads), t=6 absent, t=7..14 present
    predicate = _reads(*([True] * 6 + [False] + [True] * 8))

    result = heldFor(predicate, 7.0, 1.0, clock.sleep, clock.monotonic)

    assert result is True
    assert clock.now == 14.0  # run restarted at t=7, held through t=14


def test_heldFor_absentAtStart_waitsForPresence():
    """
    Given: absent x3 then present
    When: heldFor waits for a 7 s dwell
    Then: True at t = 3 + 7 = 10 s (the run starts at the first present read)
    """
    clock = _FakeClock()
    predicate = _reads(*([False] * 3 + [True] * 8))

    assert heldFor(predicate, 7.0, 1.0, clock.sleep, clock.monotonic) is True
    assert clock.now == 10.0


def test_heldFor_abort_returnsFalse():
    """
    Given: a predicate that never holds and an abort that fires after 3 polls
    When: heldFor waits
    Then: False, and it stops polling at the abort
    """
    clock = _FakeClock()

    result = heldFor(
        lambda: False, 7.0, 1.0, clock.sleep, clock.monotonic,
        abortFn=lambda: clock.now >= 3.0,
    )

    assert result is False
    assert clock.now == 3.0


def test_heldFor_abortMidRun_returnsFalse():
    """
    Given: a predicate that holds, and an abort that fires inside the dwell
    When: heldFor waits for a 7 s dwell
    Then: False -- an abort wins over an unfinished run
    """
    clock = _FakeClock()

    result = heldFor(
        lambda: True, 7.0, 1.0, clock.sleep, clock.monotonic,
        abortFn=lambda: clock.now >= 4.0,
    )

    assert result is False
    assert clock.now == 4.0


def test_heldFor_noRestart_breakReturnsFalseImmediately():
    """
    Given: restartOnBreak=False (the loss direction) and a break at the 3rd poll
    When: heldFor waits for a 7 s dwell
    Then: False at the break, with no further reads
    """
    clock = _FakeClock()
    predicate = _reads(True, True, True, False)

    result = heldFor(
        predicate, 7.0, 1.0, clock.sleep, clock.monotonic, restartOnBreak=False,
    )

    assert result is False
    assert clock.now == 3.0
    assert len(predicate.calls) == 4


def test_heldFor_noRestart_absentAtStart_returnsFalseWithoutSleeping():
    """
    Given: restartOnBreak=False and a predicate already false at the start
    When: heldFor is called
    Then: False with a single read and no sleep
    """
    clock = _FakeClock()
    predicate = _reads(False)

    assert heldFor(
        predicate, 7.0, 1.0, clock.sleep, clock.monotonic, restartOnBreak=False,
    ) is False
    assert clock.sleeps == []


def test_heldFor_zeroDwell_isSingleImmediateCheck():
    """
    Given: dwellSec 0
    When: heldFor is called with a predicate that holds
    Then: True from the single start read, no sleep
    """
    clock = _FakeClock()
    predicate = _reads(True)

    assert heldFor(predicate, 0.0, 1.0, clock.sleep, clock.monotonic) is True
    assert clock.sleeps == []


def test_smoothedPowerLost_confirmsThroughHeldForAtSmoothingSec():
    """
    Given: the loss direction with smoothingSec 7, smoothingPollSec 1, power lost
    When: the sequencer handles the loss
    Then: the window is confirmed at exactly 7 s, through heldFor
          (the 'sustained power-lost confirmed (7s)' path), then poweroff
    """
    clock = _FakeClock()
    calls: list[str] = []
    seq = ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: calls.append(f"pipeline@{clock.now:.0f}"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=3.40,
        totalCapSec=2.0,
        smoothingSec=7.0,
        smoothingPollSec=1.0,
        sleepFn=clock.sleep,
        monotonicFn=clock.monotonic,
    )

    assert seq._smoothedPowerLost() is True
    assert clock.now == 7.0
    assert clock.sleeps == [1.0] * 7
