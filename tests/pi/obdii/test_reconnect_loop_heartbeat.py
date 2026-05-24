################################################################################
# File Name: test_reconnect_loop_heartbeat.py
# Purpose/Description: Unit tests for the US-301 reconnect heartbeat
#                      (Spool 2026-05-08 BUG-1: 11-hour daemon silence).
#                      Pinning 10s tick cadence + per-tick connect attempt +
#                      INFO heartbeat log shape + boot canary contract.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (US-301) | Initial -- Spool Story A; CIO 10-sec heartbeat
#               |              | mandate; mirrors V0.24.1 canary discipline.
# 2026-05-11    | Rex (US-325) | I-025: runReconnectHeartbeat gained exponential
#               |              | backoff, so the fixed-10s-cadence assertion in
#               |              | test_emitsThreeOrMoreHeartbeatsInThirtySeconds
#               |              | was renamed/updated to pin the per-tick
#               |              | heartbeat (US-301 invariant: no silent thread)
#               |              | while the gaps now follow the US-325 ladder
#               |              | (full ladder pinned in
#               |              | test_reconnect_loop_backoff.py).  Every other
#               |              | test here is unchanged -- the first inter-
#               |              | attempt gap still equals the base interval.
# ================================================================================
################################################################################

"""Tests for the US-301 reconnect heartbeat.

Story scope (Spool 2026-05-08 inbox note + CIO verbatim direction):

* Production evidence: ZERO retry attempts logged across an 11-hour PENDING
  window. The single ``initial-obd-connect`` daemon thread spawned by
  ``_runInitialConnectWithTimeout`` is the *only* thing trying; if it hangs
  in BT pairing it never recovers without a service restart.

* Required behavior:

  - 10-second-cadence INFO heartbeat:
    ``RECONNECT HEARTBEAT | ticks=N | last_attempt_seconds_ago=X | last_attempt_outcome=Y``
  - Per-tick connect attempt with 5s wall-clock cap.
  - Loop exits when ``isConnectedFn()`` returns True (connection up) OR
    when ``shutdownEvent`` fires (SIGTERM).
  - Boot canary ``_verifyReconnectDaemonAlive`` ERROR-logs if the daemon
    thread is missing or dead (V0.24.1 boot-canary discipline).

* Pre-fix discriminator: ``runReconnectHeartbeat`` does not exist; the boot
  canary does not exist. Imports fail at collection time. Post-fix all four
  acceptance criteria green.
"""

from __future__ import annotations

import logging
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.reconnect_loop import (
    HEARTBEAT_ATTEMPT_TIMEOUT_SEC,
    HEARTBEAT_LOG_PREFIX,
    HEARTBEAT_TICK_INTERVAL_SEC,
    runReconnectHeartbeat,
)

# ================================================================================
# Fakes
# ================================================================================


class FakeClock:
    """Synchronous fake clock + sleep that advances ``now`` by the sleep arg.

    Used to drive the heartbeat in ~0 wall-clock while pinning the
    ``last_attempt_seconds_ago`` field deterministically.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# ================================================================================
# runReconnectHeartbeat -- the loop body
# ================================================================================


class TestRunReconnectHeartbeat:
    """Pinning the heartbeat contract (US-301 cadence + canary)."""

    def test_emitsHeartbeatEveryTick_cadenceFollowsExponentialBackoff(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A heartbeat fires every tick (US-301); the gaps back off (US-325).

        US-301 acceptance criterion: while the adapter is unreachable the
        heartbeat keeps emitting an INFO line every tick (no silent thread).
        US-325 / I-025 narrowed the cadence from a fixed ``tickIntervalSec``
        to ``min(BASE * 2 ** min(failures, 5), MAX_BACKOFF_SEC)`` so a Pi away
        from the car stops hammering ``/dev/rfcomm0``; the first gap stays at
        ``BASE`` for short-outage back-compat.  The full backoff ladder is
        pinned in ``test_reconnect_loop_backoff.py``.
        """
        clock = FakeClock()

        def connectFn() -> bool:
            return False  # never connects (engine off)

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            ticks = runReconnectHeartbeat(
                connectFn=connectFn,
                isConnectedFn=lambda: False,
                sleepFn=clock.sleep,
                monotonicFn=clock.monotonic,
                tickIntervalSec=10.0,
                attemptTimeoutSec=5.0,
                maxTicks=4,
            )

        assert ticks == 4
        # First gap == BASE (back-compat), then doubles per US-325.
        assert clock.sleeps == [10.0, 20.0, 40.0, 80.0]
        # A heartbeat line on every tick -- the US-301 no-silent-thread invariant.
        heartbeats = [r for r in caplog.records if HEARTBEAT_LOG_PREFIX in r.getMessage()]
        assert len(heartbeats) == 4, (
            f"Expected one heartbeat per tick, got {len(heartbeats)}: "
            f"{[r.getMessage() for r in heartbeats]}"
        )

    def test_eachTickCallsConnectFn_perStoryScope(self) -> None:
        """Acceptance criterion: each tick attempts connect."""
        callCount = [0]

        def connectFn() -> bool:
            callCount[0] += 1
            return False

        ticks = runReconnectHeartbeat(
            connectFn=connectFn,
            isConnectedFn=lambda: False,
            sleepFn=lambda _s: None,
            monotonicFn=lambda: 0.0,
            tickIntervalSec=10.0,
            attemptTimeoutSec=5.0,
            maxTicks=5,
        )

        assert ticks == 5
        assert callCount[0] == 5, (
            f"Expected 5 connect attempts (one per tick), got {callCount[0]}"
        )

    def test_heartbeatFormatPinnedFirstTickShowsNeverOutcome(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """First-tick heartbeat shows ``last_attempt_outcome=never`` (no prior attempt)."""
        clock = FakeClock()

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            runReconnectHeartbeat(
                connectFn=lambda: False,
                isConnectedFn=lambda: False,
                sleepFn=clock.sleep,
                monotonicFn=clock.monotonic,
                maxTicks=1,
            )

        msgs = [r.getMessage() for r in caplog.records if HEARTBEAT_LOG_PREFIX in r.getMessage()]
        assert len(msgs) == 1
        assert "ticks=1" in msgs[0]
        assert "last_attempt_outcome=never" in msgs[0]

    def test_heartbeatSecondTickReportsPriorOutcomeAndElapsed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Second tick: ``last_attempt_outcome=failure`` and ``seconds_ago=10.0``."""
        clock = FakeClock()

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            runReconnectHeartbeat(
                connectFn=lambda: False,
                isConnectedFn=lambda: False,
                sleepFn=clock.sleep,
                monotonicFn=clock.monotonic,
                tickIntervalSec=10.0,
                maxTicks=2,
            )

        msgs = [r.getMessage() for r in caplog.records if HEARTBEAT_LOG_PREFIX in r.getMessage()]
        assert len(msgs) == 2
        assert "ticks=2" in msgs[1]
        assert "last_attempt_outcome=failure" in msgs[1]
        assert "last_attempt_seconds_ago=10.0" in msgs[1]

    def test_exitsOnConnectionRestored(self) -> None:
        """When ``isConnectedFn()`` returns True, loop returns without further ticks."""
        states = [False, False, True]

        def isConnectedFn() -> bool:
            return states.pop(0) if states else True

        ticks = runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=isConnectedFn,
            sleepFn=lambda _s: None,
            monotonicFn=lambda: 0.0,
            maxTicks=10,
        )

        # Tick1: isConnected=False -> attempt + sleep. Tick2: False -> attempt + sleep.
        # Tick3: isConnected returns True at top of loop -> exits BEFORE attempt.
        assert ticks == 2

    def test_exitsOnShutdownEvent_loudBailWithinSingleTick(self) -> None:
        """SIGTERM via shutdownEvent aborts the loop at next tick boundary."""
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

        # Tick1: attempt (count=1, no shutdown). Tick2: attempt (count=2, shutdown.set).
        # Sleep returns. Tick3: shutdown observed at top -> exit.
        assert ticks == 2
        assert callCount[0] == 2

    def test_connectSuccessExitsCleanly_logsAtInfo(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When connectFn returns True, loop exits and logs success."""
        attempts = [0]

        def connectFn() -> bool:
            attempts[0] += 1
            return attempts[0] >= 3

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            ticks = runReconnectHeartbeat(
                connectFn=connectFn,
                isConnectedFn=lambda: False,
                sleepFn=lambda _s: None,
                monotonicFn=lambda: 0.0,
                maxTicks=10,
            )

        assert ticks == 3
        assert attempts[0] == 3
        assert any(
            "adapter connected" in r.getMessage().lower()
            for r in caplog.records
            if r.levelno == logging.INFO
        )

    def test_failureOutcomeLogsAtWarningLevel_loudBail(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Per V0.24.1 lesson: every retry failure is WARNING-level, not silent."""
        with caplog.at_level(logging.WARNING, logger="src.pi.obdii.reconnect_loop"):
            runReconnectHeartbeat(
                connectFn=lambda: False,
                isConnectedFn=lambda: False,
                sleepFn=lambda _s: None,
                monotonicFn=lambda: 0.0,
                maxTicks=2,
            )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 2, (
            f"Expected >=2 WARNING-level loud bails, got {len(warnings)}"
        )

    def test_connectFnExceptionClassifiedAsErrorOutcome(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Exception from connectFn does not crash the loop; logs WARNING."""

        def connectFn() -> bool:
            raise RuntimeError("simulated BT stack glitch")

        with caplog.at_level(logging.WARNING, logger="src.pi.obdii.reconnect_loop"):
            ticks = runReconnectHeartbeat(
                connectFn=connectFn,
                isConnectedFn=lambda: False,
                sleepFn=lambda _s: None,
                monotonicFn=lambda: 0.0,
                maxTicks=2,
            )

        assert ticks == 2  # loop survives the exception
        assert any(
            "error" in r.getMessage().lower() or "raised" in r.getMessage().lower()
            for r in caplog.records
            if r.levelno == logging.WARNING
        )

    def test_constantsExportedForCallSiteDiscoverability(self) -> None:
        """Public constants pin the heartbeat contract for grep + sprint_lint.

        V0.27.1 raised the attempt cap from 5s to 30s after Sprint 27 engine-
        on test #2 evidence showed 5s was below the empirical K-line cold-
        protocol-detection envelope (~6-10s) on the 1998 4G63 ECU.  The 10s
        tick interval is preserved per the CIO 2026-05-08 mandate.
        """
        assert HEARTBEAT_TICK_INTERVAL_SEC == 10.0
        assert HEARTBEAT_ATTEMPT_TIMEOUT_SEC == 30.0
        assert HEARTBEAT_LOG_PREFIX == "RECONNECT HEARTBEAT"


# ================================================================================
# _verifyReconnectDaemonAlive -- boot canary mirroring V0.24.1
# ================================================================================


class TestVerifyReconnectDaemonAlive:
    """V0.24.1-style boot canary: ERROR-logs if daemon dead AND state is PENDING."""

    def _buildStubOrchestrator(
        self, daemonThread: threading.Thread | None, isPending: bool = True
    ) -> Any:
        """Minimal LifecycleMixin-shaped stub for canary unit tests."""
        from src.pi.obdii.orchestrator.lifecycle import LifecycleMixin

        stub = SimpleNamespace()
        stub._reconnectHeartbeatThread = daemonThread
        stub._isInPendingConnectState = lambda: isPending
        # Bind the canary as an unbound method call.
        stub._verifyReconnectDaemonAlive = (
            LifecycleMixin._verifyReconnectDaemonAlive.__get__(stub, type(stub))
        )
        return stub

    def test_canaryErrorLogsWhenThreadIsNoneAndPending(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        stub = self._buildStubOrchestrator(daemonThread=None, isPending=True)
        with caplog.at_level(logging.ERROR, logger="pi.obdii.orchestrator"):
            stub._verifyReconnectDaemonAlive()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        msg = errors[0].getMessage()
        assert "reconnect" in msg.lower() and "heartbeat" in msg.lower()
        assert "fail" in msg.lower() or "not alive" in msg.lower() or "none" in msg.lower()

    def test_canaryErrorLogsWhenThreadIsDeadAndPending(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        deadThread = threading.Thread(target=lambda: None, name="heartbeat-dead-fixture")
        deadThread.start()
        deadThread.join()
        assert not deadThread.is_alive()

        stub = self._buildStubOrchestrator(daemonThread=deadThread, isPending=True)
        with caplog.at_level(logging.ERROR, logger="pi.obdii.orchestrator"):
            stub._verifyReconnectDaemonAlive()

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "fail" in errors[0].getMessage().lower() or "not alive" in errors[0].getMessage().lower()

    def test_canaryPassesWhenThreadAliveAndPending(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        keepAlive = threading.Event()

        def liveTarget() -> None:
            keepAlive.wait(timeout=2.0)

        liveThread = threading.Thread(
            target=liveTarget, name="heartbeat-live-fixture", daemon=True
        )
        liveThread.start()
        try:
            assert liveThread.is_alive()
            stub = self._buildStubOrchestrator(daemonThread=liveThread, isPending=True)
            with caplog.at_level(logging.INFO, logger="pi.obdii.orchestrator"):
                stub._verifyReconnectDaemonAlive()
            errors = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert errors == [], (
                f"Live thread should not trigger ERROR; got: "
                f"{[r.getMessage() for r in errors]}"
            )
            infos = [r for r in caplog.records if r.levelno == logging.INFO]
            assert any("pass" in r.getMessage().lower() for r in infos), (
                "Expected INFO-level PASSED log when daemon alive (mirrors V0.24.1 canary)"
            )
        finally:
            keepAlive.set()
            liveThread.join(timeout=2.0)

    def test_canarySilentWhenNotInPendingState(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Defense-in-depth: if connection is up, missing daemon is not an ERROR."""
        stub = self._buildStubOrchestrator(daemonThread=None, isPending=False)
        with caplog.at_level(logging.ERROR, logger="pi.obdii.orchestrator"):
            stub._verifyReconnectDaemonAlive()
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert errors == []
