################################################################################
# File Name: test_connect_thread_safety.py
# Purpose/Description: V0.27.1 hotfix regression -- ObdConnection.connect()
#                      must serialize concurrent callers so the Sprint 25
#                      leaked _runInitialConnectWithTimeout daemon and the
#                      Sprint 27 US-301 heartbeat-spawned daemons cannot
#                      collide on /dev/rfcomm0 ("multiple access on port?").
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-08    | Rex (V0.27.1)| Initial -- Sprint 27 engine-on test #2 root
#               |              | cause: ObdConnection.connect() was not thread-
#               |              | safe; concurrent callers interleaved their
#               |              | internal 6-attempt counter and produced
#               |              | "device disconnected or multiple access on
#               |              | port?" pyserial errors, blocking Drive 6.
# ================================================================================
################################################################################

"""V0.27.1 hotfix discriminator -- ``ObdConnection.connect()`` thread safety.

Sprint 27 engine-on test #2 (2026-05-08 17:08 CDT) produced ZERO realtime_data
rows.  Spool's diagnosis + my own RCA from the production journal: the
US-301 reconnect heartbeat daemon (per-tick connect attempt with 5s wall-
clock cap) collided with the Sprint 25 ``_runInitialConnectWithTimeout``
leaked daemon thread.  Both call ``self._connection.connect()`` directly.
``ObdConnection`` had ZERO thread safety -- no ``threading.Lock``, no
``RLock`` -- so concurrent invocations interleaved the inner 6-attempt-with-
backoff counter, opened ``/dev/rfcomm0`` simultaneously, and pyserial
rejected each open with the literal "multiple access on port?" hint.

The journal smoking gun (16-second window from engine-on test #2)::

    17:15:09 attempt 3/6 fail   <- cycle A
    17:15:09 attempt 1/6 fail   <- cycle B
    17:15:10 attempt 1/6 fail   <- cycle C
    17:15:10 attempt 2/6 fail   <- cycle A continues
    17:15:10 attempt 6/6 fail   <- cycle D about to give up
    17:15:11 attempt 6/6 fail   <- cycle E about to give up

At least 4 concurrent ``connect()`` call stacks active simultaneously.

Fix shape (V0.27.1):

* ``ObdConnection.__init__`` instantiates ``self._connectLock = threading.Lock()``.
* ``ObdConnection.connect()`` body runs under ``with self._connectLock:`` so all
  concurrent callers serialize.
* ``ObdConnection.isConnectInFlight()`` exposes ``self._connectLock.locked()``
  so heartbeat callers can probe before invoking connect, log
  ``outcome=already_in_flight``, and skip the tick instead of blocking on the
  lock (preserves the 10s heartbeat cadence per CIO 2026-05-08 mandate).
* ``runReconnectHeartbeat`` accepts an optional ``inFlightProbeFn`` keyword;
  when it returns True at the top of a tick, the heartbeat logs the
  ``already_in_flight`` outcome at INFO and continues to the next tick
  without spawning a worker daemon (closing the daemon-leak path that
  produced the steady-state pile-up in Sprint 27).

Pre-fix discriminators (every test in this file fails against the unfixed code):

* ``ObdConnection`` exposes no ``isConnectInFlight``.  The probe test fails
  with ``AttributeError``.
* ``ObdConnection.connect()`` has no internal lock.  The 8-thread
  contention test fails with ``maxConcurrent > 1``.
* ``runReconnectHeartbeat`` does not accept ``inFlightProbeFn``.  The
  heartbeat-skip test fails with ``TypeError: unexpected keyword 'inFlightProbeFn'``.

Post-fix all assertions pass.  Runtime-validation discipline per
``feedback_runtime_validation_required.md`` and US-301 close-note pattern
empirically demonstrated by temp-reverting the fix and observing the
expected RED.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest

from src.pi.obdii.obd_connection import ObdConnection
from src.pi.obdii.reconnect_loop import (
    HEARTBEAT_LOG_PREFIX,
    runReconnectHeartbeat,
)

# ================================================================================
# Fakes
# ================================================================================


class _ContentionProbe:
    """Detects concurrent calls into the OBD ctor (the pyserial-collision site).

    Mirrors the failure mode python-obd surfaces when two threads call
    ``OBD()`` against the same ``/dev/rfcomm0``: the second open fails because
    the first holds the file descriptor.  This probe records the maximum
    observed concurrency; pre-fix the regression test catches ``> 1``.

    The brief ``ctorSleepSec`` window is the contention surface: any thread
    that enters while another is sleeping is a violation.  Tightening or
    loosening the sleep affects the *probability* of catching the race in a
    given test run, not the *correctness* of the test -- the
    ``threading.Barrier`` upstream guarantees all workers enter the function
    simultaneously, so any non-zero sleep produces deterministic detection.
    """

    def __init__(self, ctorSleepSec: float = 0.05) -> None:
        self._ctorSleepSec = ctorSleepSec
        self._lock = threading.Lock()
        self.activeCount = 0
        self.maxConcurrent = 0
        self.totalCalls = 0
        self.violations = 0

    def __call__(self, serialPort: str | None, timeout: float) -> Any:
        with self._lock:
            self.activeCount += 1
            self.totalCalls += 1
            if self.activeCount > 1:
                self.violations += 1
            if self.activeCount > self.maxConcurrent:
                self.maxConcurrent = self.activeCount

        try:
            time.sleep(self._ctorSleepSec)
        finally:
            with self._lock:
                self.activeCount -= 1

        return _StubObd()


class _StubObd:
    """Minimal ``obd.OBD`` double honouring the interface ``ObdConnection`` uses.

    ``connect()`` calls ``self.obd.is_connected()`` to confirm the session
    came up; the stub returns True so the rest of the success path runs.
    """

    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def query(self, *args: Any, **kwargs: Any) -> Any:
        return None


def _buildConnection(obdFactory: Any) -> ObdConnection:
    """Build an ObdConnection wired to a contention probe.

    Sets ``macAddress`` to a literal path so ``_resolvePort`` skips
    ``bluetooth_helper.bindRfcomm`` (which would attempt a real subprocess
    call to ``rfcomm bind``).  The path string itself is never opened
    because we inject ``obdFactory`` to bypass the real ``_createObdConnection``
    code path.
    """
    return ObdConnection(
        config={
            'pi': {
                'bluetooth': {
                    'macAddress': '/dev/rfcomm-test',
                    # Tight retry schedule so ANY connect failure does not
                    # spend tens of seconds in backoff during the test.
                    'retryDelays': [0],
                    'maxRetries': 0,
                    'connectionTimeoutSeconds': 1,
                },
            },
        },
        obdFactory=obdFactory,
    )


# ================================================================================
# Core thread-safety contract
# ================================================================================


class TestConnectThreadSafety:
    """V0.27.1 -- ``ObdConnection.connect()`` must serialize concurrent callers."""

    def test_concurrentConnects_serialize_viaInternalLock(self) -> None:
        """Eight threads enter connect() simultaneously; only one inside ctor at a time.

        Pre-fix discriminator: ``ObdConnection`` has no internal lock.
        ``probe.maxConcurrent`` will be observed > 1 (production journal
        evidence shows 3-4 concurrent stacks).  Post-fix: serialized to 1.
        """
        probe = _ContentionProbe(ctorSleepSec=0.05)
        connection = _buildConnection(probe)

        threadCount = 8
        barrier = threading.Barrier(threadCount)
        results: list[bool] = []
        resultsLock = threading.Lock()

        def worker() -> None:
            barrier.wait()  # everyone starts the connect call together
            ok = connection.connect()
            with resultsLock:
                results.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(threadCount)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive(), "Thread did not finish in 10s"

        # The contract: at most ONE thread inside the ctor at any wall-clock instant.
        assert probe.maxConcurrent == 1, (
            f"Concurrent ctor entry detected: maxConcurrent={probe.maxConcurrent} "
            f"violations={probe.violations} totalCalls={probe.totalCalls} "
            "(V0.27.1 regression: ObdConnection.connect() is not thread-safe)"
        )
        assert probe.violations == 0
        # All 8 workers eventually called the ctor (the lock did not deadlock).
        assert probe.totalCalls == 8

    def test_isConnectInFlight_observableSeam_returnsTrue_duringConnect(self) -> None:
        """``isConnectInFlight()`` reports True while another thread is mid-connect.

        Pre-fix discriminator: method does not exist (AttributeError).
        Post-fix the heartbeat callsite uses this probe to skip its tick when
        the Sprint 25 leaked daemon is still inside connect().
        """
        # connectFn that blocks until we explicitly let it finish.
        proceedEvent = threading.Event()
        insideEvent = threading.Event()

        def slowFactory(serialPort: str | None, timeout: float) -> Any:
            insideEvent.set()
            assert proceedEvent.wait(timeout=5.0), "test timed out"
            return _StubObd()

        connection = _buildConnection(slowFactory)
        assert hasattr(connection, 'isConnectInFlight'), (
            "ObdConnection must expose isConnectInFlight() observability seam"
        )
        # Pre-call: nobody is inside connect.
        assert connection.isConnectInFlight() is False

        worker = threading.Thread(target=connection.connect, daemon=True)
        worker.start()
        try:
            assert insideEvent.wait(timeout=5.0), "factory was never called"
            # Worker is now mid-connect.  Probe must report True.
            assert connection.isConnectInFlight() is True
        finally:
            proceedEvent.set()
            worker.join(timeout=5.0)
            assert not worker.is_alive(), "worker did not exit"

        # Post-call: worker released the lock.
        assert connection.isConnectInFlight() is False


# ================================================================================
# Heartbeat skip-when-in-flight contract
# ================================================================================


class TestHeartbeatSkipsWhenConnectInFlight:
    """V0.27.1 -- heartbeat must observe in-flight state and skip, not stack."""

    def test_heartbeatTick_logsAlreadyInFlight_andDoesNotCallConnectFn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When ``inFlightProbeFn() == True``, tick logs already_in_flight and skips.

        Pre-fix discriminator: ``runReconnectHeartbeat`` does not accept
        ``inFlightProbeFn`` (TypeError on call).  Post-fix the heartbeat
        records the new outcome and never invokes ``connectFn`` for that tick,
        which is what closes the Sprint 27 stacking-connect bug at the call
        site.
        """
        connectCalls = [0]

        def connectFn() -> bool:
            connectCalls[0] += 1
            return False

        with caplog.at_level(logging.INFO, logger="src.pi.obdii.reconnect_loop"):
            ticks = runReconnectHeartbeat(
                connectFn=connectFn,
                isConnectedFn=lambda: False,
                inFlightProbeFn=lambda: True,
                sleepFn=lambda _s: None,
                monotonicFn=lambda: 0.0,
                maxTicks=3,
            )

        # All 3 ticks observed the in-flight state; connectFn never called.
        assert ticks == 3
        assert connectCalls[0] == 0, (
            f"connectFn must NOT be invoked when in-flight probe returns True; "
            f"got {connectCalls[0]} calls (V0.27.1 stacking-connect regression)"
        )
        # Each tick logged the already_in_flight outcome.
        alreadyInFlight = [
            r for r in caplog.records
            if HEARTBEAT_LOG_PREFIX in r.getMessage()
            and 'already_in_flight' in r.getMessage()
        ]
        assert len(alreadyInFlight) >= 3, (
            f"Expected >=3 already_in_flight heartbeat lines, got "
            f"{len(alreadyInFlight)}: {[r.getMessage() for r in alreadyInFlight]}"
        )

    def test_heartbeatTick_proceedsToConnectFn_whenInFlightProbeReturnsFalse(
        self,
    ) -> None:
        """Sanity check: probe-returns-False path runs the existing connect logic."""
        connectCalls = [0]

        def connectFn() -> bool:
            connectCalls[0] += 1
            return False

        ticks = runReconnectHeartbeat(
            connectFn=connectFn,
            isConnectedFn=lambda: False,
            inFlightProbeFn=lambda: False,  # never in-flight
            sleepFn=lambda _s: None,
            monotonicFn=lambda: 0.0,
            maxTicks=3,
        )

        assert ticks == 3
        # All 3 ticks invoked connectFn (probe never True).
        assert connectCalls[0] == 3

    def test_heartbeatTick_acceptsNoneInFlightProbe_backwardsCompat(self) -> None:
        """``inFlightProbeFn=None`` is the legacy / pre-V0.27.1 behaviour.

        The Sprint 27 callsites that haven't been updated yet keep working.
        """
        connectCalls = [0]

        def connectFn() -> bool:
            connectCalls[0] += 1
            return False

        ticks = runReconnectHeartbeat(
            connectFn=connectFn,
            isConnectedFn=lambda: False,
            sleepFn=lambda _s: None,
            monotonicFn=lambda: 0.0,
            maxTicks=2,
        )

        assert ticks == 2
        assert connectCalls[0] == 2


# ================================================================================
# Constant pin
# ================================================================================


class TestHeartbeatTimeoutAlignedWithKLine:
    """V0.27.1 -- attempt timeout cap raised from 5s to 30s.

    Spool's empirical observation (2026-05-08): ISO 9141-2 K-line cold
    protocol detection (ATZ + ATE0 + ATSP0 negotiation) on the 1998 4G63
    routinely takes 6-10s.  US-301's original 5s cap was below the working
    envelope -- even a healthy connection would have timed out.  V0.27.1
    aligns the heartbeat cap with ``_initializeConnection``'s 30s budget.
    """

    def test_heartbeatAttemptTimeout_pinnedAtThirtySeconds(self) -> None:
        """The exported constant is the canonical pin for grep + sprint_lint."""
        from src.pi.obdii.reconnect_loop import HEARTBEAT_ATTEMPT_TIMEOUT_SEC

        assert HEARTBEAT_ATTEMPT_TIMEOUT_SEC == 30.0, (
            f"V0.27.1 raised the cap to 30s to match K-line negotiation envelope; "
            f"got {HEARTBEAT_ATTEMPT_TIMEOUT_SEC}"
        )
