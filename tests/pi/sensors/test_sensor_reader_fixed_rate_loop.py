################################################################################
# File Name: test_sensor_reader_fixed_rate_loop.py
# Purpose/Description: ARCH-064d -- the reader poll loop keeps a FIXED-RATE
#     schedule. It used to wait a full interval AFTER each poll's work, so the
#     real period was 1/sampleHz + work: MEASURED on drive 96 (2026-09-30) as
#     24.72 ms against a configured 20 ms (sampleHz 50), i.e. 40.5 Hz, which made
#     the stored IMU cadence 1.62 Hz against a configured 2.
# Author: Atlas (ARCH-064d, CIO-directed build)
# Creation Date: 2026-09-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""The sensor poll loop runs at sampleHz, not at 1 / (1/sampleHz + work)."""

from __future__ import annotations

import pytest

from pi.bus.bus import SampleBus
from pi.sensors.sensor_reader import _BaseSensorReader, nextPollDeadline

INTERVAL_S = 0.020  # sampleHz 50
WORK_S = 0.0047     # the per-poll work MEASURED on drive 96 (24.72 - 20.00 ms)


class TestNextPollDeadline:
    def test_onTime_advancesByExactlyOneInterval(self) -> None:
        assert nextPollDeadline(1.000, now=1.0047, intervalS=INTERVAL_S) == pytest.approx(1.020)

    def test_deadlineIsAnchoredToTheSchedule_notToWhenWorkFinished(self) -> None:
        """The defect: the old loop computed 'now + interval' (1.0247 here)."""
        due = nextPollDeadline(1.000, now=1.0047, intervalS=INTERVAL_S)
        assert due != pytest.approx(1.0047 + INTERVAL_S)

    def test_overrun_skipsMissedTicks_neverBurstsToCatchUp(self) -> None:
        # A 55 ms stall past a 20 ms schedule: ticks at 1.02, 1.04 are gone; the
        # next deadline is the first tick still in the future (1.06), on-phase.
        due = nextPollDeadline(1.000, now=1.055, intervalS=INTERVAL_S)
        assert due == pytest.approx(1.060)

    def test_overrunLandingExactlyOnATick_isNotReturnedAsDue(self) -> None:
        due = nextPollDeadline(1.000, now=1.040, intervalS=INTERVAL_S)
        assert due > 1.040


class _FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


class _FakeStop:
    """Stands in for the reader's threading.Event: wait() advances the fake clock."""

    def __init__(self, clock: _FakeClock, maxWaits: int) -> None:
        self._clock, self._left, self._set = clock, maxWaits, False
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def clear(self) -> None:
        self._set = False

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        self._clock.t += max(0.0, timeout)
        self._left -= 1
        if self._left <= 0:
            self._set = True
        return self._set


class _TimedReader(_BaseSensorReader):
    source = "fake"
    stateTopic = "state.fake"

    def __init__(self, clock: _FakeClock, workS: float, **kw) -> None:
        super().__init__(SampleBus(), sampleHz=50, deviceFactory=lambda: object(), clockFn=clock, **kw)
        self._clockRef, self._workS = clock, workS
        self.pollTimes: list[float] = []

    def pollOnce(self) -> None:  # the work: record, then burn WORK_S of clock
        self.pollTimes.append(self._clockRef.t)
        self._clockRef.t += self._workS

    def _readAndPublish(self, seq: int) -> None:  # pragma: no cover - pollOnce overridden
        raise AssertionError


def _periods(times: list[float]) -> list[float]:
    return [b - a for a, b in zip(times, times[1:])]


def test_loopPeriodIsTheInterval_notIntervalPlusWork() -> None:
    clock = _FakeClock()
    reader = _TimedReader(clock, WORK_S)
    reader._stop = _FakeStop(clock, maxWaits=200)
    reader._loop()
    periods = _periods(reader.pollTimes)
    assert len(periods) >= 150
    assert all(p == pytest.approx(INTERVAL_S, abs=1e-9) for p in periods)
    # 200 polls span 199 intervals of 20 ms -- 50 Hz, not the measured 40.5 Hz.
    rate = (len(reader.pollTimes) - 1) / (reader.pollTimes[-1] - reader.pollTimes[0])
    assert rate == pytest.approx(50.0, rel=1e-6)


def test_oldBehaviourWouldHaveBeen40Hz_soThisTestCanFail() -> None:
    """Pin the discriminating power: interval+work at these numbers is 40.5 Hz."""
    assert 1.0 / (INTERVAL_S + WORK_S) == pytest.approx(40.49, abs=0.01)


def test_workLongerThanTheInterval_neverWaitsNegative_andStaysOnPhase() -> None:
    clock = _FakeClock()
    reader = _TimedReader(clock, workS=0.030)  # every poll overruns a 20 ms slot
    reader._stop = _FakeStop(clock, maxWaits=20)
    reader._loop()
    assert all(w >= 0.0 for w in reader._stop.waits)
    start = reader.pollTimes[0]
    # every poll starts on a 20 ms schedule tick (the schedule is never re-anchored)
    for t in reader.pollTimes:
        ticks = (t - start) / INTERVAL_S
        assert ticks == pytest.approx(round(ticks), abs=1e-6)


def test_defaultClockIsMonotonic() -> None:
    import time

    reader = _BaseSensorReader(SampleBus(), sampleHz=50, deviceFactory=lambda: object())
    assert reader._clock is time.monotonic
