################################################################################
# File Name: test_reconnect_loop.py
# Purpose/Description: Unit tests for the US-211 backoff-capped reconnect loop.
#                      Injection-based FakeProbe + FakeSleep run the state
#                      machine deterministically in ~0 wall-clock.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-211) | Initial -- Spool Session 6 amended Story 2.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.obdii.reconnect_loop`.

Covers:

* Backoff schedule (1, 5, 10, 30, 60, 60...) matches Spool grounding.
* Cap: entries beyond the schedule stay at 60s.
* ``reset()`` rewinds to the first entry.
* Event logger emits ``adapter_wait`` -> ``reconnect_attempt`` ->
  ``reconnect_success`` per iteration.
* Probe failure loops; probe success returns True.
* ``shouldExitFn`` aborts the loop without a probe-success.
* ``maxIterations`` safety net caps runaway tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.pi.data.connection_logger import (
    EVENT_ADAPTER_WAIT,
    EVENT_RECONNECT_ATTEMPT,
    EVENT_RECONNECT_SUCCESS,
)
from src.pi.obdii.reconnect_loop import (
    BACKOFF_CAP_SECONDS,
    DEFAULT_BACKOFF_SCHEDULE,
    ReconnectLoop,
)

# ================================================================================
# Fakes
# ================================================================================

@dataclass
class FakeProbe:
    """Probe driven by a pre-scripted sequence of bool returns."""
    results: list[bool]
    _calls: int = 0

    def __call__(self) -> bool:
        if self._calls >= len(self.results):
            return self.results[-1] if self.results else False
        value = self.results[self._calls]
        self._calls += 1
        return value

    @property
    def callCount(self) -> int:
        return self._calls


@dataclass
class FakeSleep:
    """Sleep recorder -- collects each requested duration."""
    durations: list[float] = field(default_factory=list)

    def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)


@dataclass
class FakeEventLogger:
    """Event logger recorder -- (event_type, retry_count) tuples."""
    events: list[tuple[str, int]] = field(default_factory=list)

    def __call__(self, eventType: str, retryCount: int) -> None:
        self.events.append((eventType, retryCount))


def _buildLoop(
    probeResults: list[bool],
    *,
    schedule: tuple[int, ...] = DEFAULT_BACKOFF_SCHEDULE,
    shouldExit: Callable[[], bool] | None = None,
) -> tuple[ReconnectLoop, FakeProbe, FakeSleep, FakeEventLogger]:
    probe = FakeProbe(probeResults)
    sleep = FakeSleep()
    events = FakeEventLogger()
    loop = ReconnectLoop(
        probe=probe,
        eventLogger=events,
        sleepFn=sleep,
        schedule=schedule,
        shouldExitFn=shouldExit,
    )
    return loop, probe, sleep, events


# ================================================================================
# Schedule + cap
# ================================================================================

def test_defaultSchedule_matchesSpoolGrounding():
    """Spool Session 6 locked '1, 5, 10, 30, 60, 60... (cap 60)'."""
    assert DEFAULT_BACKOFF_SCHEDULE == (1, 5, 10, 30, 60)
    assert BACKOFF_CAP_SECONDS == 60


def test_getCurrentDelay_returnsScheduleEntry_atEachIteration():
    """Delays step through (1, 5, 10, 30, 60, 60, 60...) and cap at 60."""
    loop, probe, sleep, events = _buildLoop(probeResults=[False] * 10 + [True])

    delaysObserved: list[int] = []
    # Drive the loop; capture every sleep duration.
    ok = loop.waitForAdapter()
    assert ok is True
    # FakeSleep collected the sleep inputs before each probe; compare to
    # the first 11 schedule entries (capped at 60 past index 4).
    for i in range(11):
        expected = DEFAULT_BACKOFF_SCHEDULE[i] if i < len(DEFAULT_BACKOFF_SCHEDULE) else 60
        expected = min(expected, BACKOFF_CAP_SECONDS)
        delaysObserved.append(int(sleep.durations[i]))
    assert delaysObserved == [1, 5, 10, 30, 60, 60, 60, 60, 60, 60, 60]


def test_customScheduleWithLargeValues_clampedToCap():
    """Any entry above 60s is clamped -- no accidental 10-minute sleeps."""
    loop, probe, sleep, events = _buildLoop(
        probeResults=[False, True],
        schedule=(5, 3600),
    )
    loop.waitForAdapter()
    assert sleep.durations == [5.0, BACKOFF_CAP_SECONDS]


# ================================================================================
# Event emission
# ================================================================================

def test_successOnFirstProbe_emitsThreeEventsInOrder():
    """adapter_wait -> reconnect_attempt -> reconnect_success is the minimum flap row set."""
    loop, probe, sleep, events = _buildLoop(probeResults=[True])
    ok = loop.waitForAdapter()
    assert ok is True
    assert events.events == [
        (EVENT_ADAPTER_WAIT, 1),
        (EVENT_RECONNECT_ATTEMPT, 1),
        (EVENT_RECONNECT_SUCCESS, 1),
    ]


def test_multipleIterations_retryCountMonotonic():
    """Each iteration bumps retry_count; reconnect_success carries the final count."""
    loop, probe, sleep, events = _buildLoop(probeResults=[False, False, True])
    loop.waitForAdapter()

    expected = [
        (EVENT_ADAPTER_WAIT, 1),
        (EVENT_RECONNECT_ATTEMPT, 1),
        (EVENT_ADAPTER_WAIT, 2),
        (EVENT_RECONNECT_ATTEMPT, 2),
        (EVENT_ADAPTER_WAIT, 3),
        (EVENT_RECONNECT_ATTEMPT, 3),
        (EVENT_RECONNECT_SUCCESS, 3),
    ]
    assert events.events == expected


def test_noEventLogger_doesNotRaise():
    """Passing eventLogger=None silences emission without exceptions."""
    loop = ReconnectLoop(
        probe=FakeProbe([True]),
        eventLogger=None,
        sleepFn=FakeSleep(),
    )
    assert loop.waitForAdapter() is True


def test_eventLoggerRaising_doesNotBreakLoop():
    """Event-logger exceptions are swallowed -- observability must not block recovery."""
    def boom(event_type: str, retry_count: int) -> None:
        raise RuntimeError("DB went away")

    loop = ReconnectLoop(
        probe=FakeProbe([True]),
        eventLogger=boom,
        sleepFn=FakeSleep(),
    )
    assert loop.waitForAdapter() is True


# ================================================================================
# Reset
# ================================================================================

def test_reset_rewindsSchedule():
    """reset() after a success means the next drop starts at 1s, not at the cap."""
    loop, probe, sleep, events = _buildLoop(probeResults=[False, False, True, False, True])
    # First recovery -- 3 iterations to reach success.
    loop.waitForAdapter()
    firstRunDelays = list(sleep.durations)
    assert firstRunDelays[:3] == [1.0, 5.0, 10.0]

    # Now simulate another drop: reset() then call waitForAdapter again.
    # The schedule should start from 1s again.
    loop.reset()
    sleep.durations = []
    ok = loop.waitForAdapter()
    assert ok is True
    # probeResults already exhausted the True case; if loop stays alive
    # the iteration count should be 2 (False then True).
    assert sleep.durations[0] == 1.0


def test_reset_isAutomaticallyCalledOnSuccess():
    """Successful waitForAdapter resets internal state -- next call starts fresh."""
    loop, probe, sleep, events = _buildLoop(probeResults=[False, True, False, True])
    loop.waitForAdapter()  # 2 iterations
    sleep.durations = []
    loop.waitForAdapter()  # Should start at delay index 0 again.
    assert sleep.durations[0] == 1.0


# ================================================================================
# Early exit
# ================================================================================

def test_shouldExitFn_true_abortsImmediately_returnsFalse():
    """shouldExitFn fires -> loop returns False without calling probe."""
    flag = {'stop': True}

    loop, probe, sleep, events = _buildLoop(
        probeResults=[True],
        shouldExit=lambda: flag['stop'],
    )
    ok = loop.waitForAdapter()
    assert ok is False
    assert probe.callCount == 0
    assert events.events == []


def test_shouldExitFn_afterSleep_abortsBeforeProbe():
    """shouldExitFn that flips to True after the first sleep returns False."""
    state = {'iter': 0}

    def shouldExit() -> bool:
        # Return False on the first check (before first sleep), True after.
        state['iter'] += 1
        return state['iter'] > 1

    loop, probe, sleep, events = _buildLoop(
        probeResults=[True],
        shouldExit=shouldExit,
    )
    ok = loop.waitForAdapter()
    assert ok is False
    # Event sequence: adapter_wait (iter 1) then bail before probe.
    assert events.events == [(EVENT_ADAPTER_WAIT, 1)]


def test_maxIterations_safetyNet_returnsFalseWhenHit():
    """maxIterations prevents runaway tests with unbounded False probes."""
    loop, probe, sleep, events = _buildLoop(probeResults=[False] * 20)
    ok = loop.waitForAdapter(maxIterations=3)
    assert ok is False
    # Each failed iteration emits 2 events (adapter_wait + reconnect_attempt).
    assert len(events.events) == 6


# ================================================================================
# Probe robustness
# ================================================================================

def test_probeRaising_treatedAsNotReachable():
    """Exceptions from the probe count as 'keep waiting', not a crash."""
    def flaky() -> bool:
        raise OSError("Probe connection refused")

    sleep = FakeSleep()
    events = FakeEventLogger()
    loop = ReconnectLoop(
        probe=flaky,
        eventLogger=events,
        sleepFn=sleep,
    )
    ok = loop.waitForAdapter(maxIterations=2)
    assert ok is False
    # Should have fired 2 adapter_wait + 2 reconnect_attempt (no success).
    assert [e for e, _ in events.events] == [
        EVENT_ADAPTER_WAIT,
        EVENT_RECONNECT_ATTEMPT,
        EVENT_ADAPTER_WAIT,
        EVENT_RECONNECT_ATTEMPT,
    ]
