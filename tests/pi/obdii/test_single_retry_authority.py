################################################################################
# File Name: test_single_retry_authority.py
# Purpose/Description: US-690 -- one retry authority for the OBD link.  A
#                      wall-clock cap that abandons a connect must CANCEL it,
#                      the recovery loop must not nest connect()'s own retry
#                      loop, and no two retry threads may run at once.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Rex (US-690) | Initial implementation
# ================================================================================
################################################################################

"""US-690: two reconnect loops fight; the retry ceiling under-counts.

The live V0.29.43 trace showed ``connection_log.retry_count`` as two
interleaved series.  Code reading names three ways a second retry loop ran
beside the first, and each has a guard here:

1. **A cap that abandoned without cancelling.**  ``_runInitialConnectWithTimeout``
   gave up waiting on ``connect()`` after 30 s and spawned the PENDING heartbeat
   -- while the abandoned ``connect()`` kept running its own 6-attempt loop.
   :class:`TestCapCancelsWhatItAbandons` runs the REAL cap over a REAL
   ``ObdConnection`` and counts port attempts after the cap fires, with a
   control showing the count without the cancel.
2. **Nested loops.**  ``_reconnectionLoop`` called ``reconnect()`` ->
   ``connect()`` per attempt, so its ceiling of N attempts was N x 6 port
   attempts.  :class:`TestRecoveryLoopIsTheOnlyCounter`.
3. **Unrelated retry threads guarding only against copies of themselves.**
   :class:`TestAtMostOneRetryThread`.

Every ``ObdConnection`` here uses a PATH-style port, so no rfcomm subprocess is
spawned and the file is hermetic on a Windows bench.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from pi.obdii.obd_connection import ObdConnection
from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.obdii.reconnect_loop import runReconnectHeartbeat

# ================================================================================
# Fakes and helpers
# ================================================================================


class RecordingShutdownEvent(threading.Event):
    """Never-set shutdown event that records each backoff and runs a hook."""

    def __init__(self, onWait: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.waits: list[float] = []
        self._onWait = onWait

    def wait(self, timeout: float | None = None) -> bool:  # type: ignore[override]
        self.waits.append(float(timeout if timeout is not None else 0.0))
        if self._onWait is not None:
            self._onWait()
        return False


class CountingFactory:
    """``obd.OBD`` factory that fails every call and runs a hook on each."""

    def __init__(
        self,
        onCall: Callable[[int], None] | None = None,
        succeedOnCall: int | None = None,
    ) -> None:
        self.callCount = 0
        self._onCall = onCall
        self._succeedOnCall = succeedOnCall

    def __call__(self, portstr: str, timeout: int) -> Any:
        self.callCount += 1
        if self._onCall is not None:
            self._onCall(self.callCount)
        if self._succeedOnCall is not None and self.callCount == self._succeedOnCall:
            return _LiveObd()
        raise OSError("OBD connection not active after creation")


class _LiveObd:
    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        pass


def _connection(
    factory: Any,
    *,
    retryDelays: list[int] | None = None,
    maxRetries: int = 5,
    shutdownEvent: threading.Event | None = None,
) -> ObdConnection:
    return ObdConnection(
        {
            "pi": {
                "bluetooth": {
                    "macAddress": "/dev/rfcomm0",
                    "retryDelays": [] if retryDelays is None else retryDelays,
                    "maxRetries": maxRetries,
                    "connectionTimeoutSeconds": 5,
                }
            }
        },
        obdFactory=factory,
        shutdownEvent=shutdownEvent,
    )


def _orchestrator() -> ApplicationOrchestrator:
    config: dict[str, Any] = {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "bluetooth": {
                "macAddress": "/dev/rfcomm0",
                "retryDelays": [],
                "maxRetries": 3,
            },
            "sync": {"enabled": False},
        },
        "server": {},
    }
    return ApplicationOrchestrator(config=config, simulate=False)


@contextmanager
def _parkedThread(name: str) -> Iterator[threading.Thread]:
    """A live thread standing in for a retry thread that has not finished."""
    gate = threading.Event()
    thread = threading.Thread(target=gate.wait, name=name, daemon=True)
    thread.start()
    try:
        yield thread
    finally:
        gate.set()
        thread.join(timeout=2)


def _joinThreadsNamed(prefix: str, timeoutSec: float = 3.0) -> None:
    for thread in threading.enumerate():
        if thread.name.startswith(prefix):
            thread.join(timeout=timeoutSec)


# ================================================================================
# 1. ObdConnection.cancelPendingConnects -- the seam
# ================================================================================


class TestCancelPendingConnects:
    """A cancelled connect makes no further attempt and sleeps no further backoff."""

    def test_uncancelledConnect_runsItsWholeBudget_control(self) -> None:
        """
        Given: an unreachable dongle and maxRetries=5
        When:  connect() runs with no cancel
        Then:  6 port attempts -- the loop a cap used to leave running
        """
        factory = CountingFactory()
        conn = _connection(factory)

        assert conn.connect() is False
        assert factory.callCount == 6

    def test_cancelDuringAttempt_noFurtherAttemptAndNoBackoff(self) -> None:
        """
        Given: connect() with a real backoff ramp, cancelled during attempt 1
        When:  attempt 1 fails
        Then:  it returns False with ONE port attempt and ZERO backoffs slept
        """
        event = RecordingShutdownEvent()
        conn: ObdConnection

        def cancelOnFirst(callNumber: int) -> None:
            if callNumber == 1:
                conn.cancelPendingConnects()

        factory = CountingFactory(onCall=cancelOnFirst)
        conn = _connection(factory, retryDelays=[1, 2, 4, 8, 16], shutdownEvent=event)

        assert conn.connect() is False
        assert factory.callCount == 1
        assert event.waits == []

    def test_cancelDuringBackoff_stopsBeforeTheNextAttempt(self) -> None:
        """
        Given: connect() whose first backoff is where the cancel lands
        When:  the backoff ends
        Then:  no second port attempt is made
        """
        conn: ObdConnection
        event = RecordingShutdownEvent(onWait=lambda: conn.cancelPendingConnects())
        factory = CountingFactory()
        conn = _connection(factory, retryDelays=[1, 2, 4, 8, 16], shutdownEvent=event)

        assert conn.connect() is False
        assert factory.callCount == 1
        assert len(event.waits) == 1

    def test_cancelBeforeACall_doesNotCancelThatLaterCall(self) -> None:
        """
        Given: cancelPendingConnects() ran while nothing was connecting
        When:  a NEW connect() starts afterwards
        Then:  it is unaffected and connects
        """
        factory = CountingFactory(succeedOnCall=2)
        conn = _connection(factory)
        conn.cancelPendingConnects()

        assert conn.connect() is True
        assert factory.callCount == 2

    def test_attemptAlreadyInHandshake_whenCancelled_keepsTheLinkItMade(self) -> None:
        """
        Given: the cancel lands while attempt 1 is inside obd.OBD()
        When:  that handshake succeeds
        Then:  the link is kept -- cancel stops the LOOP, it does not discard a
               live connection every caller is waiting for
        """
        conn: ObdConnection

        def cancelOnFirst(callNumber: int) -> None:
            conn.cancelPendingConnects()

        factory = CountingFactory(onCall=cancelOnFirst, succeedOnCall=1)
        conn = _connection(factory)

        assert conn.connect() is True
        assert conn.isConnected() is True

    def test_cancelPendingConnects_neverBlocksBehindAnInFlightAttempt(self) -> None:
        """
        Given: another thread holds _ioLock inside a slow handshake
        When:  cancelPendingConnects() is called
        Then:  it returns promptly -- the canceller is the one that stopped waiting
        """
        inside = threading.Event()
        release = threading.Event()

        def slowHandshake(callNumber: int) -> None:
            inside.set()
            release.wait(timeout=5)

        conn = _connection(CountingFactory(onCall=slowHandshake), maxRetries=0)
        worker = threading.Thread(target=conn.connect, daemon=True)
        worker.start()
        try:
            assert inside.wait(timeout=5)
            started = time.monotonic()
            conn.cancelPendingConnects()
            assert time.monotonic() - started < 0.5
        finally:
            release.set()
            worker.join(timeout=5)


# ================================================================================
# 2. The caps cancel what they abandon
# ================================================================================


class TestCapCancelsWhatItAbandons:
    """validationCriterion 2: let the wall-clock cap expire."""

    def _runCapOverSlowFirstAttempt(
        self, orch: ApplicationOrchestrator
    ) -> CountingFactory:
        release = threading.Event()

        def slowFirstAttempt(callNumber: int) -> None:
            if callNumber == 1:
                release.wait(timeout=5)

        factory = CountingFactory(onCall=slowFirstAttempt)
        orch._connection = _connection(factory, maxRetries=5)

        completed, success, _error = orch._runInitialConnectWithTimeout(0.1)
        assert completed is False
        assert success is False

        release.set()
        _joinThreadsNamed("obd-connect-gen")
        return factory

    def test_initialConnectCap_cancelsTheAbandonedConnect(self) -> None:
        """
        Given: the REAL initial-connect cap over a REAL ObdConnection whose
               first handshake outlasts the cap
        When:  the cap fires and the handshake then fails
        Then:  the abandoned connect() makes NO further port attempt
        """
        factory = self._runCapOverSlowFirstAttempt(_orchestrator())

        assert factory.callCount == 1, (
            f"abandoned connect() kept retrying after the cap: {factory.callCount} "
            "port attempts -- a second retry loop beside the heartbeat (US-690)"
        )

    def test_initialConnectCap_withoutCancel_leavesALoopRunning_control(self) -> None:
        """
        Given: the same setup with the cancel disabled
        When:  the cap fires
        Then:  the orphan runs its whole 6-attempt budget -- the defect, measured
        """
        orch = _orchestrator()
        orch._cancelAbandonedConnect = lambda: None  # type: ignore[method-assign]

        factory = self._runCapOverSlowFirstAttempt(orch)

        assert factory.callCount == 6

    def test_initialConnectCap_completedConnect_isNotCancelled(self) -> None:
        """
        Given: a connect() that returns within the cap
        When:  _runInitialConnectWithTimeout completes
        Then:  cancelPendingConnects is not called
        """
        orch = _orchestrator()
        fake = MagicMock()
        fake.connect.return_value = False
        orch._connection = fake

        completed, _success, _error = orch._runInitialConnectWithTimeout(2.0)

        assert completed is True
        fake.cancelPendingConnects.assert_not_called()

    def test_heartbeatCap_timeout_callsCancelFn(self) -> None:
        """
        Given: a heartbeat whose connect attempt outlasts attemptTimeoutSec
        When:  the tick times out
        Then:  cancelFn is called exactly once for that tick
        """
        release = threading.Event()
        cancelCalls: list[int] = []

        try:
            runReconnectHeartbeat(
                connectFn=lambda: release.wait(timeout=5),
                isConnectedFn=lambda: False,
                cancelFn=lambda: cancelCalls.append(1),
                sleepFn=lambda _s: None,
                attemptTimeoutSec=0.05,
                maxTicks=1,
            )
        finally:
            release.set()

        assert cancelCalls == [1]

    def test_heartbeatCap_failureOutcome_doesNotCancel(self) -> None:
        """
        Given: a connect attempt that returns False within the cap
        When:  the tick completes
        Then:  cancelFn is not called -- there is nothing left running to cancel
        """
        cancelCalls: list[int] = []

        runReconnectHeartbeat(
            connectFn=lambda: False,
            isConnectedFn=lambda: False,
            cancelFn=lambda: cancelCalls.append(1),
            sleepFn=lambda _s: None,
            maxTicks=2,
        )

        assert cancelCalls == []

    def test_heartbeatCap_cancelFnRaising_doesNotStopTheHeartbeat(self) -> None:
        """
        Given: a cancelFn that raises
        When:  two ticks time out
        Then:  the heartbeat still runs both ticks
        """
        release = threading.Event()

        def badCancel() -> None:
            raise RuntimeError("cancel failed")

        try:
            ticks = runReconnectHeartbeat(
                connectFn=lambda: release.wait(timeout=5),
                isConnectedFn=lambda: False,
                cancelFn=badCancel,
                sleepFn=lambda _s: None,
                attemptTimeoutSec=0.05,
                maxTicks=2,
            )
        finally:
            release.set()

        assert ticks == 2

    @pytest.mark.parametrize(
        "spawnName", ["_spawnReconnectHeartbeatDaemon", "_spawnPostFailureReconnectHeartbeat"]
    )
    def test_everyHeartbeatSpawn_wiresTheConnectionsCancel(
        self, spawnName: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: either orchestrator heartbeat spawn point
        When:  it starts runReconnectHeartbeat
        Then:  cancelFn is wired and reaches the connection's cancelPendingConnects
        """
        captured: dict[str, Any] = {}

        def fakeHeartbeat(**kwargs: Any) -> int:
            captured.update(kwargs)
            return 0

        # Patch the name in the globals the method ACTUALLY resolves against: a
        # dotted-path patch misses when another test has reloaded the module.
        spawnGlobals = getattr(ApplicationOrchestrator, spawnName).__globals__
        monkeypatch.setitem(spawnGlobals, "runReconnectHeartbeat", fakeHeartbeat)
        orch = _orchestrator()
        fake = MagicMock()
        orch._connection = fake

        getattr(orch, spawnName)()
        _joinThreadsNamed("obd-reconnect-heartbeat")
        _joinThreadsNamed("us338-post-failure-reconnect-heartbeat")

        assert captured.get("cancelFn") is not None
        captured["cancelFn"]()
        fake.cancelPendingConnects.assert_called_once()


# ================================================================================
# 3. The recovery loop is the only counter
# ================================================================================


class TestRecoveryLoopIsTheOnlyCounter:
    """validationCriterion 1: trace a failed connect end to end."""

    def test_recoveryLoop_nAttempts_isNPortAttempts_andNoInnerSeries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: the REAL recovery loop (maxRetries=3) over a REAL ObdConnection
               whose own connect() budget is 6 attempts
        When:  every attempt fails
        Then:  exactly 3 port attempts, and every connect_attempt row the
               connection logs carries retry index 0 -- no second, inner series
               counting underneath the loop's own counter
        """
        factory = CountingFactory()
        conn = _connection(factory, maxRetries=5)
        logged: list[tuple[str, int]] = []
        monkeypatch.setattr(
            conn,
            "_logConnectionEvent",
            lambda eventType, success=False, errorMessage=None, retryCount=0: (
                logged.append((eventType, retryCount))
            ),
        )

        orch = _orchestrator()
        monkeypatch.setattr(orch, "_spawnPostFailureReconnectHeartbeat", lambda: None)
        orch._connection = conn
        orch._reconnectDelays = []
        orch._maxReconnectAttempts = 3
        orch._isReconnecting = True
        orch._reconnectAttempt = 0

        orch._reconnectionLoop()

        attemptRows = [count for event, count in logged if event == "connect_attempt"]
        assert orch._reconnectAttempt == 3
        assert factory.callCount == 3, (
            f"{factory.callCount} port attempts under a 3-attempt ceiling -- the "
            "recovery loop is nesting connect()'s own retry loop (US-690)"
        )
        assert attemptRows == [0, 0, 0]


# ================================================================================
# 4. At most one retry thread
# ================================================================================


class TestAtMostOneRetryThread:
    """Each retry thread used to guard only against copies of itself."""

    def test_noRetryThreadAlive_namesNone(self) -> None:
        assert _orchestrator()._liveRetryAuthorityName() is None

    @pytest.mark.parametrize(
        ("attribute", "name"),
        [
            ("_reconnectHeartbeatThread", "obd-reconnect-heartbeat"),
            ("_postFailureReconnectHeartbeatThread", "us338-post-failure-reconnect-heartbeat"),
        ],
    )
    def test_liveHeartbeat_recoveryLoopDoesNotStart(self, attribute: str, name: str) -> None:
        """
        Given: a heartbeat thread still alive
        When:  the connection is lost and _startReconnection runs
        Then:  no second retry loop starts and no attempt is made
        """
        orch = _orchestrator()
        fake = MagicMock()
        orch._connection = fake

        with _parkedThread(name) as thread:
            setattr(orch, attribute, thread)
            orch._startReconnection()

            assert orch._reconnectThread is None
            assert orch._isReconnecting is False
            fake.reconnectOnce.assert_not_called()

    def test_liveRecoveryLoop_postFailureHeartbeatDoesNotSpawnBesideIt(self) -> None:
        """
        Given: the recovery-loop thread is alive and the caller is another thread
        When:  _spawnPostFailureReconnectHeartbeat runs
        Then:  no heartbeat is spawned
        """
        orch = _orchestrator()
        orch._connection = MagicMock()

        with _parkedThread("connection-recovery") as thread:
            orch._reconnectThread = thread
            orch._spawnPostFailureReconnectHeartbeat()

            assert getattr(orch, "_postFailureReconnectHeartbeatThread", None) is None

    def test_recoveryLoopHandoff_fromItsOwnThread_stillSpawnsTheHeartbeat(self) -> None:
        """
        Given: the recovery loop exhausting its attempts on its OWN thread
        When:  it hands off to the post-failure heartbeat
        Then:  the heartbeat IS spawned -- the loop does not block its own handoff
        """
        orch = _orchestrator()
        fake = MagicMock()
        fake.reconnectOnce.return_value = False
        fake.connectOnce.return_value = True
        orch._connection = fake
        orch._reconnectDelays = []
        orch._maxReconnectAttempts = 1

        orch._startReconnection()
        assert orch._reconnectThread is not None
        orch._reconnectThread.join(timeout=5)

        heartbeat = getattr(orch, "_postFailureReconnectHeartbeatThread", None)
        assert heartbeat is not None
        heartbeat.join(timeout=5)
