################################################################################
# File Name: test_reconnect_loop_backoff.py
# Purpose/Description: Unit tests for the US-325 exponential backoff added to
#                      runReconnectHeartbeat (I-025: BT reconnect loop fired
#                      at a fixed ~30-60s cadence FOREVER when the OBDLink was
#                      out of range, starving the Pi 5 WiFi+BT combo chip).
#                      Pins the backoff formula, the MAX_BACKOFF_SEC cap, the
#                      exponent clamp, the new log-line fields, the back-compat
#                      first-gap-stays-at-base behavior, and the single-tick
#                      caller signature.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-11    | Rex (US-325) | Initial -- I-025 exponential backoff; CIO
#               |              | 2026-05-11 WiFi-drop debug; Fix #2 (Fix #1 was
#               |              | the OS-side wifi.powersave=2 NetworkManager
#               |              | drop-in shipped in the same story).
# ================================================================================
################################################################################

"""Tests for the US-325 reconnect-heartbeat exponential backoff.

Story scope (I-025 + sprint.json US-325):

* Production evidence (journalctl 2026-05-11): with the OBDLink LX out of
  Bluetooth range, ``_performConnect`` logged ``Connection attempt N/6 failed``
  at a fixed ~30-60s cadence indefinitely -- thousands of failed attempts a day
  hammering ``/dev/rfcomm0``.  On a Pi 5 the WiFi+BT combo chip shares one
  radio; continuous BT activity + the Pi 5 default ``wifi.powersave=ON``
  starved WiFi and the association broke twice in three hours.

* Required behavior (sprint.json formula):

  - ``runReconnectHeartbeat`` tracks a consecutive-failure counter.
  - The inter-attempt sleep grows:
    ``min(BASE * 2 ** min(consecutive_failures, BACKOFF_EXP_CAP), MAX_BACKOFF_SEC)``
    where ``BASE`` is the ``tickIntervalSec`` argument,
    ``BACKOFF_EXP_CAP == 5`` and ``MAX_BACKOFF_SEC == 900`` (15 min).
  - The FIRST inter-attempt gap stays at ``BASE`` (back-compat for short
    outages -- the V0.27.1 US-301 fixed cadence is preserved for the first
    reconnect attempt).
  - The INFO heartbeat line gains ``consecutive_failures=N`` and
    ``next_attempt_in_seconds=X`` fields.
  - A successful connect ends the loop; a re-spawned heartbeat (the next
    outage) starts fresh at ``BASE`` -- no permanent slowdown.

* Pre-fix discriminators: the cadence is a fixed ``tickIntervalSec`` per tick
  (so the 8-tick test sees ``[10, 10, ...]`` not ``[10, 20, 40, ...]``), and
  the ``MAX_BACKOFF_SEC`` / ``BACKOFF_EXP_CAP`` constants do not exist (the
  import fails).  Post-fix every assertion below passes.
"""

from __future__ import annotations

import logging
import threading

import pytest

from src.pi.obdii.reconnect_loop import (
    BACKOFF_EXP_CAP,
    HEARTBEAT_LOG_PREFIX,
    HEARTBEAT_TICK_INTERVAL_SEC,
    MAX_BACKOFF_SEC,
    runReconnectHeartbeat,
)

# ================================================================================
# Fakes
# ================================================================================


class FakeClock:
    """Synchronous fake clock + sleep that advances ``now`` by the sleep arg.

    Records every sleep duration so a test can assert the exact backoff
    ladder without any real wall-clock delay.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _heartbeatLines(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the INFO heartbeat log messages captured so far, in order."""
    return [
        r.getMessage()
        for r in caplog.records
        if HEARTBEAT_LOG_PREFIX in r.getMessage()
    ]


# ================================================================================
# Backoff ladder
# ================================================================================


class TestExponentialBackoffLadder:
    """Pin the ``min(BASE * 2 ** min(failures, CAP), MAX)`` schedule."""

    def test_consecutiveFailures_intervalsDoubleUntilExponentCap(self) -> None:
        """8 failed ticks at BASE=10 -> sleeps 10, 20, 40, 80, 160, 320, 320, 320.

        The exponent is clamped at BACKOFF_EXP_CAP (5), so 10 * 2**5 = 320 is
        the steady-state interval once five consecutive failures have piled up.
        Pre-fix this list is ``[10, 10, 10, 10, 10, 10, 10, 10]`` -- the fixed
        ``tickIntervalSec`` cadence -- so this assertion fails before US-325.
        """
        clock = FakeClock()

        ticks = runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=lambda: False,
            sleepFn=clock.sleep,
            monotonicFn=clock.monotonic,
            tickIntervalSec=10.0,
            attemptTimeoutSec=5.0,
            maxTicks=8,
        )

        assert ticks == 8
        assert clock.sleeps == [10.0, 20.0, 40.0, 80.0, 160.0, 320.0, 320.0, 320.0]

    def test_firstGapStaysAtBaseInterval_v0271BackCompat(self) -> None:
        """The first reconnect-attempt gap is still BASE (short-outage back-compat).

        V0.27.1 US-301 invariant: a brief OBDLink dropout still gets a fast
        first retry.  Only the *second* failure onward stretches the cadence.
        """
        clock = FakeClock()

        runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=lambda: False,
            sleepFn=clock.sleep,
            monotonicFn=clock.monotonic,
            tickIntervalSec=10.0,
            maxTicks=2,
        )

        assert clock.sleeps[0] == 10.0
        assert clock.sleeps == [10.0, 20.0]

    def test_backoffCappedAtMaxBackoffSec(self) -> None:
        """A large BASE clamps to MAX_BACKOFF_SEC (15 min) instead of blowing up.

        BASE=300: 300, 600, then 300 * 2**2 = 1200 -> clamped to 900, and it
        stays at 900 thereafter.  Production BASE (10s) never reaches the cap
        (10 * 2**5 = 320 < 900); this test exercises the ceiling explicitly.
        """
        clock = FakeClock()

        runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=lambda: False,
            sleepFn=clock.sleep,
            monotonicFn=clock.monotonic,
            tickIntervalSec=300.0,
            maxTicks=5,
        )

        assert clock.sleeps == [300.0, 600.0, 900.0, 900.0, 900.0]
        assert max(clock.sleeps) == MAX_BACKOFF_SEC

    def test_inFlightSkipDoesNotAdvanceBackoff(self) -> None:
        """An ``already_in_flight`` tick is not a failure -- the counter holds.

        Ticks 1-2: another thread owns ``connect()`` (inFlightProbeFn True) ->
        the heartbeat skips the spawn, sleeps at the *current* backoff level
        (still BASE), and does NOT increment the failure counter.  Ticks 3-4:
        the probe clears; now real attempts fail and the ladder advances from
        BASE.
        """
        clock = FakeClock()
        inFlight = [True, True, False, False]

        def inFlightProbeFn() -> bool:
            return inFlight.pop(0) if inFlight else False

        runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=lambda: False,
            inFlightProbeFn=inFlightProbeFn,
            sleepFn=clock.sleep,
            monotonicFn=clock.monotonic,
            tickIntervalSec=10.0,
            maxTicks=4,
        )

        # Tick1 (in-flight) -> 10. Tick2 (in-flight) -> 10. Tick3 (1st real
        # failure, counter was 0) -> 10. Tick4 (2nd real failure) -> 20.
        assert clock.sleeps == [10.0, 10.0, 10.0, 20.0]


# ================================================================================
# Reset on successful connect
# ================================================================================


class TestBackoffResetsOnSuccess:
    """Successful connect ends the loop; the next outage starts fresh at BASE."""

    def test_successThenNewOutage_startsAtBaseInterval_noPermanentSlowdown(
        self,
    ) -> None:
        clock1 = FakeClock()
        attempts = [0]

        def connectFnFlakyThenUp() -> bool:
            attempts[0] += 1
            return attempts[0] >= 4  # fails 3x, then connects on the 4th tick

        ticks1 = runReconnectHeartbeat(
            connectFn=connectFnFlakyThenUp,
            isConnectedFn=lambda: False,
            sleepFn=clock1.sleep,
            monotonicFn=clock1.monotonic,
            tickIntervalSec=10.0,
            maxTicks=10,
        )

        # 3 failures -> 3 backed-off sleeps; tick 4 connects -> no 4th sleep.
        assert ticks1 == 4
        assert clock1.sleeps == [10.0, 20.0, 40.0]

        # A fresh heartbeat (the daemon is re-spawned on the next dropout) has
        # its own counter -> the first gap is BASE again, not 80s.
        clock2 = FakeClock()
        runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=lambda: False,
            sleepFn=clock2.sleep,
            monotonicFn=clock2.monotonic,
            tickIntervalSec=10.0,
            maxTicks=1,
        )
        assert clock2.sleeps == [10.0]


# ================================================================================
# Heartbeat log-line shape
# ================================================================================


class TestHeartbeatLogLineFields:
    """The INFO heartbeat gains ``consecutive_failures`` + ``next_attempt_in_seconds``."""

    def test_heartbeatLineCarriesFailureCountAndNextInterval(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock = FakeClock()

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            runReconnectHeartbeat(
                connectFn=lambda: False,
                isConnectedFn=lambda: False,
                sleepFn=clock.sleep,
                monotonicFn=clock.monotonic,
                tickIntervalSec=10.0,
                maxTicks=3,
            )

        lines = _heartbeatLines(caplog)
        assert len(lines) == 3
        # Tick 1: no failures yet, the upcoming gap is BASE.
        assert "consecutive_failures=0" in lines[0]
        assert "next_attempt_in_seconds=10.0" in lines[0]
        # Tick 2: one failure behind us, the upcoming gap is 2*BASE.
        assert "consecutive_failures=1" in lines[1]
        assert "next_attempt_in_seconds=20.0" in lines[1]
        # Tick 3: two failures, upcoming gap 4*BASE.
        assert "consecutive_failures=2" in lines[2]
        assert "next_attempt_in_seconds=40.0" in lines[2]
        # The pre-US-325 fields are still present (no regression for grep tooling).
        assert all("last_attempt_outcome=" in ln for ln in lines)

    def test_inFlightHeartbeatLineAlsoCarriesNewFields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        clock = FakeClock()

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            runReconnectHeartbeat(
                connectFn=lambda: False,
                isConnectedFn=lambda: False,
                inFlightProbeFn=lambda: True,
                sleepFn=clock.sleep,
                monotonicFn=clock.monotonic,
                tickIntervalSec=10.0,
                maxTicks=2,
            )

        lines = _heartbeatLines(caplog)
        assert len(lines) == 2
        for ln in lines:
            assert "last_attempt_outcome=already_in_flight" in ln
            assert "consecutive_failures=0" in ln  # in-flight ticks aren't failures
            assert "next_attempt_in_seconds=10.0" in ln


# ================================================================================
# Constants + signature back-compat
# ================================================================================


class TestBackoffConstantsAndSignature:
    """Public constants + the single-tick caller signature stay stable."""

    def test_backoffConstantsExported(self) -> None:
        assert MAX_BACKOFF_SEC == 900.0
        assert BACKOFF_EXP_CAP == 5
        # The production BASE is still the V0.27.1 / CIO-mandated 10s.
        assert HEARTBEAT_TICK_INTERVAL_SEC == 10.0

    def test_singleTickCallerSignatureUnchanged(self) -> None:
        """Callers that pass only the two required fns (+ test seams) still work.

        Back-compat guard: US-325 must not require any new keyword at the call
        site -- the lifecycle daemon spawns ``runReconnectHeartbeat`` without
        passing ``tickIntervalSec`` (it gets the default BASE).
        """
        callCount = [0]

        def connectFn() -> bool:
            callCount[0] += 1
            return False

        ticks = runReconnectHeartbeat(
            connectFn=connectFn,
            isConnectedFn=lambda: False,
            sleepFn=lambda _s: None,
            monotonicFn=lambda: 0.0,
            maxTicks=1,
        )
        assert ticks == 1
        assert callCount[0] == 1

    def test_shutdownEventStillAbortsLoop_unchanged(self) -> None:
        """SIGTERM via shutdownEvent exits at the next tick boundary (regression)."""
        shutdown = threading.Event()
        callCount = [0]

        def connectFn() -> bool:
            callCount[0] += 1
            if callCount[0] >= 2:
                shutdown.set()
            return False

        ticks = runReconnectHeartbeat(
            connectFn=connectFn,
            isConnectedFn=lambda: False,
            shutdownEvent=shutdown,
            sleepFn=lambda _s: None,
            monotonicFn=lambda: 0.0,
            maxTicks=10,
        )
        assert ticks == 2
        assert callCount[0] == 2
