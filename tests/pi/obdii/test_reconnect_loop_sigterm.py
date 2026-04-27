################################################################################
# File Name: test_reconnect_loop_sigterm.py
# Purpose/Description: US-232 / TD-035 -- ReconnectLoop (US-211 artifact)
#                      wakes from its backoff sleep when the shutdown event
#                      is set by a signal handler.  Symmetric with the
#                      ObdConnection.connect() responsiveness test so both
#                      retry surfaces observe SIGTERM inside 2s.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-232) | Initial -- TD-035 close.
# ================================================================================
################################################################################

"""Tests for :class:`ReconnectLoop` event-wake semantics.

Complements :mod:`test_reconnect_loop.py` (deterministic schedule + event-
logger coverage) with SIGTERM responsiveness: the loop must expose a
``shutdownEvent`` seam so a ``threading.Event`` flipped from the main-
thread signal handler wakes the loop from its backoff sleep AND the
shouldExit check short-circuits the next iteration.

Pattern: a real :class:`threading.Event` is set from a helper thread
100ms after :meth:`waitForAdapter` starts blocking in a long sleep.
"""

from __future__ import annotations

import threading
import time

from src.pi.obdii.reconnect_loop import ReconnectLoop


def _failingProbe() -> bool:
    return False


# ================================================================================
# Core SIGTERM responsiveness
# ================================================================================

def test_reconnectLoop_wakesFromSleep_whenShutdownEventSet_within2s() -> None:
    """Event.set() from a helper thread wakes waitForAdapter() within 2s.

    Uses a 60s schedule so a passing test proves the event wakes the sleep
    (and not the schedule simply running out).
    """
    shutdownEvent = threading.Event()

    loop = ReconnectLoop(
        probe=_failingProbe,
        eventLogger=None,
        schedule=(60, 60, 60, 60),
        shutdownEvent=shutdownEvent,
    )

    def signalAfterDelay() -> None:
        time.sleep(0.1)
        shutdownEvent.set()

    trigger = threading.Thread(target=signalAfterDelay, daemon=True)
    started = time.monotonic()
    trigger.start()
    result = loop.waitForAdapter()
    elapsed = time.monotonic() - started

    assert result is False, "waitForAdapter() must return False on shutdown"
    assert elapsed < 3.0, (
        f"ReconnectLoop did not wake on event.set() -- slept {elapsed:.2f}s"
    )

    trigger.join(timeout=1.0)


def test_reconnectLoop_shutdownEvent_preSet_exitsImmediately() -> None:
    """Pre-set event causes waitForAdapter() to return False without sleeping."""
    shutdownEvent = threading.Event()
    shutdownEvent.set()

    probeCalls: list[int] = []

    def trackedProbe() -> bool:
        probeCalls.append(1)
        return False

    loop = ReconnectLoop(
        probe=trackedProbe,
        eventLogger=None,
        schedule=(60, 60),
        shutdownEvent=shutdownEvent,
    )

    started = time.monotonic()
    result = loop.waitForAdapter()
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 1.0, f"pre-set event should bail instantly but took {elapsed:.2f}s"
    assert probeCalls == [], "probe must not be called when event is pre-set"


def test_reconnectLoop_shutdownEvent_overridesShouldExitFn_when_both_passed() -> None:
    """shutdownEvent seam composes with shouldExitFn -- either can abort.

    When shutdownEvent is set, the loop exits regardless of shouldExitFn;
    when shouldExitFn returns True, the loop exits regardless of event
    state. Co-existence preserves US-211's existing semantics.
    """
    shutdownEvent = threading.Event()
    shouldExitCalls: list[int] = []

    def shouldExit() -> bool:
        shouldExitCalls.append(1)
        return False  # Never exits via this path

    loop = ReconnectLoop(
        probe=_failingProbe,
        eventLogger=None,
        schedule=(60,),
        shutdownEvent=shutdownEvent,
        shouldExitFn=shouldExit,
    )

    def signalAfterDelay() -> None:
        time.sleep(0.1)
        shutdownEvent.set()

    trigger = threading.Thread(target=signalAfterDelay, daemon=True)
    trigger.start()

    started = time.monotonic()
    result = loop.waitForAdapter()
    elapsed = time.monotonic() - started

    assert result is False
    assert elapsed < 3.0
    # shouldExitFn was consulted at least once before the event was set.
    assert len(shouldExitCalls) >= 1

    trigger.join(timeout=1.0)


def test_reconnectLoop_noShutdownEvent_preservesExistingBehavior() -> None:
    """Without shutdownEvent, loop behaves exactly as before (backwards compat).

    Deterministic FakeSleep proves the loop still honors an injected sleep
    function and probe-success path unchanged.
    """
    probeResults = [True]
    probeIdx = [0]

    def probe() -> bool:
        idx = probeIdx[0]
        probeIdx[0] += 1
        return probeResults[min(idx, len(probeResults) - 1)]

    sleeps: list[float] = []

    def fakeSleep(t: float) -> None:
        sleeps.append(t)

    loop = ReconnectLoop(
        probe=probe,
        eventLogger=None,
        sleepFn=fakeSleep,
        schedule=(1, 5, 10),
    )

    assert loop.waitForAdapter() is True
    assert sleeps == [1.0]


def test_reconnectLoop_shutdownEvent_setDuringSleep_stopsNextProbe() -> None:
    """Event set during sleep -> next probe is not dispatched.

    Probe counter proves the loop aborted during the sleep rather than
    completing the sleep and running another probe iteration.
    """
    shutdownEvent = threading.Event()
    probeCalls: list[int] = []

    def probe() -> bool:
        probeCalls.append(1)
        return False

    loop = ReconnectLoop(
        probe=probe,
        eventLogger=None,
        schedule=(60,),
        shutdownEvent=shutdownEvent,
    )

    def signalAfterDelay() -> None:
        time.sleep(0.1)
        shutdownEvent.set()

    trigger = threading.Thread(target=signalAfterDelay, daemon=True)
    trigger.start()

    # The loop enters the sleep BEFORE it calls the probe the first time;
    # event fires mid-sleep -> second shouldExit check short-circuits ->
    # probe should never run.
    result = loop.waitForAdapter()

    assert result is False
    assert probeCalls == [], (
        f"probe must not be called when event fires mid-sleep, got {len(probeCalls)} calls"
    )

    trigger.join(timeout=1.0)


# ================================================================================
# buildDefaultReconnectLoop plumbing (production factory must accept event)
# ================================================================================

def test_buildDefaultReconnectLoop_acceptsShutdownEvent() -> None:
    """The production factory must plumb shutdownEvent through to the loop.

    Orchestrator wiring (US-232 bt_resilience change) builds the loop via
    this factory; if the kwarg is missing, production would not get the
    SIGTERM fix even though the class supports it.
    """
    from src.pi.obdii.reconnect_loop import buildDefaultReconnectLoop

    shutdownEvent = threading.Event()
    loop = buildDefaultReconnectLoop(
        database=None,
        macAddress='00:04:3E:85:0D:FB',
        rfcommDevice=0,
        shutdownEvent=shutdownEvent,
    )

    # The loop must see the same event instance -- test by pre-setting it
    # and confirming waitForAdapter exits immediately.
    shutdownEvent.set()
    started = time.monotonic()
    result = loop.waitForAdapter()
    elapsed = time.monotonic() - started
    assert result is False
    assert elapsed < 1.0
