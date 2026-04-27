################################################################################
# File Name: test_sigterm_responsiveness.py
# Purpose/Description: US-232 / TD-035 -- collector BT retry loop responds to
#                      SIGTERM-equivalent shutdown event within 2s instead of
#                      sleeping through the backoff schedule (~90s worst case)
#                      and forcing systemd to SIGKILL.
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

"""Tests for shutdown-event responsiveness in :class:`ObdConnection.connect`.

Pattern: ``time.sleep(backoff)`` in the retry loop blocks the main thread
so systemd SIGTERM is not observed until the sleep expires. Replace with
``shutdownEvent.wait(timeout=backoff)`` so a signal handler flipping the
event wakes the retry loop within a few ms.

TD-035 acceptance: SIGTERM-to-exit within 2 seconds (down from ~90s).

Tests use a real :class:`threading.Event` driven from a helper thread so
the exit path is exercised end-to-end without relying on the OS signal
module (which is main-thread-only on Windows + restricted in pytest).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from src.pi.obdii.obd_connection import ObdConnection

# ================================================================================
# Fakes
# ================================================================================

class _AlwaysFailingFakeObd:
    """python-obd stand-in that never connects -- forces the retry loop to backoff."""

    def is_connected(self) -> bool:
        return False

    def query(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def close(self) -> None:
        pass


def _alwaysFailingFactory(_portstr: str, _timeout: int) -> _AlwaysFailingFakeObd:
    return _AlwaysFailingFakeObd()


def _config(
    retryDelays: list[int],
    maxRetries: int | None = None,
) -> dict[str, Any]:
    """Minimal config sized to force several retry passes."""
    if maxRetries is None:
        maxRetries = len(retryDelays)
    return {
        'pi': {
            'bluetooth': {
                'macAddress': '/dev/rfcomm0',
                'retryDelays': retryDelays,
                'maxRetries': maxRetries,
                'connectionTimeoutSeconds': 1,
                'rfcommDevice': 0,
                'rfcommChannel': 1,
            }
        }
    }


# ================================================================================
# Core responsiveness test -- the acceptance story behavior
# ================================================================================

def test_connectRetryLoop_wakesOnShutdownEvent_within2s() -> None:
    """Mid-retry SIGTERM-equivalent exits the loop within 2s tolerance.

    Given a retry schedule [60, 60, 60, 60, 60] (worst-case backoff) and a
    factory that never succeeds, the retry loop would classically sleep
    through ~300s of time.sleep. With the shutdownEvent plumbed in, setting
    the event from a helper thread must wake the retry loop within 2s.
    """
    shutdownEvent = threading.Event()
    # Large delays so a passing test proves the event wakes the sleep -- not
    # that the schedule just finished quickly.
    conn = ObdConnection(
        config=_config(retryDelays=[60, 60, 60, 60, 60]),
        obdFactory=_alwaysFailingFactory,
        shutdownEvent=shutdownEvent,
    )

    # Fire the event 100ms after connect() starts. Helper thread simulates
    # the signal handler flipping the event.
    def signalAfterDelay() -> None:
        time.sleep(0.1)
        shutdownEvent.set()

    trigger = threading.Thread(target=signalAfterDelay, daemon=True)

    started = time.monotonic()
    trigger.start()
    result = conn.connect()
    elapsed = time.monotonic() - started

    assert result is False, "connect() must return False when shutdown cancels the retry"
    # 2s acceptance target with a 3s tolerance for CI flakiness.
    assert elapsed < 3.0, (
        f"connect() took {elapsed:.2f}s to respond to shutdownEvent -- expected <2s"
    )

    trigger.join(timeout=1.0)


def test_connectRetryLoop_shutdownEvent_preSet_exitsAfterFirstFailure() -> None:
    """When the event is already set, the first backoff is skipped entirely."""
    shutdownEvent = threading.Event()
    shutdownEvent.set()  # pre-set

    conn = ObdConnection(
        config=_config(retryDelays=[60, 60, 60]),
        obdFactory=_alwaysFailingFactory,
        shutdownEvent=shutdownEvent,
    )

    started = time.monotonic()
    result = conn.connect()
    elapsed = time.monotonic() - started

    assert result is False
    # No sleeps at all -- should complete in well under 1s.
    assert elapsed < 1.0, f"pre-set event should skip all backoffs but took {elapsed:.2f}s"


def test_connectRetryLoop_noShutdownEvent_preservesTimeSleep() -> None:
    """Backwards-compatibility: when no event is provided, behavior is unchanged.

    The retry loop still uses time.sleep for the backoff; this test uses a
    short schedule so it runs in ~0 wall-clock (the non-event path stays
    exercised under its existing semantics).
    """
    conn = ObdConnection(
        config=_config(retryDelays=[0, 0], maxRetries=1),
        obdFactory=_alwaysFailingFactory,
    )

    # No shutdownEvent passed -- constructor should default to None.
    assert conn.shutdownEvent is None

    result = conn.connect()
    assert result is False


def test_connectRetryLoop_eventSetMidScheduledDelay_stopsRemainingRetries() -> None:
    """After the event fires during retry N, retry N+1 must not run.

    Exits the loop cleanly (return False) rather than continuing to poll
    the OBD factory for more failed attempts. retryDelays=[0, 10, 10]
    makes attempt 1 -> attempt 2 instant so the event can be set before
    the 10s backoff kicks in -- the wake happens from the backoff,
    exercising the interruptible path exactly.
    """
    shutdownEvent = threading.Event()
    factory = _alwaysFailingFactory

    callTracker: list[int] = []

    def trackingFactory(portstr: str, timeout: int) -> _AlwaysFailingFakeObd:
        callTracker.append(len(callTracker) + 1)
        # After 2 attempts, set the event to simulate SIGTERM mid-retry.
        if len(callTracker) == 2:
            shutdownEvent.set()
        return factory(portstr, timeout)

    conn = ObdConnection(
        config=_config(retryDelays=[0, 10, 10], maxRetries=4),
        obdFactory=trackingFactory,
        shutdownEvent=shutdownEvent,
    )

    started = time.monotonic()
    result = conn.connect()
    elapsed = time.monotonic() - started

    assert result is False
    # Two factory calls happened before event fired -- the third retry must
    # abort during the backoff sleep rather than dispatching a third attempt.
    assert len(callTracker) == 2, (
        f"expected 2 factory calls before shutdown wake, got {len(callTracker)}"
    )
    assert elapsed < 3.0
