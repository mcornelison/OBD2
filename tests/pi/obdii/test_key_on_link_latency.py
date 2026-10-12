################################################################################
# File Name: test_key_on_link_latency.py
# Purpose/Description: US-751 -- the key-on link delay is backoff latency.
#                      Model wake -> connection attempt over the real
#                      heartbeat, prove retries are one visible series, and
#                      pin that mid-session recovery, idle attempt count,
#                      radio cadence and rfcomm cleanup did not regress.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Rex (US-751) | Initial implementation
# ================================================================================
################################################################################

"""US-751: key-on link delay is backoff latency, not a missing trigger.

``connection_log`` on 2026-09-14 showed the Pi retrying all night at the ~320 s
heartbeat ceiling (plus a ~42-45 s attempt), then connecting 30 minutes after
key-on.  A key-on that lands just after a failed attempt waits out the whole
ceiling.  These tests drive the REAL :func:`runReconnectHeartbeat` over a
simulated car on a fake clock:

* without a wake the modelled wake -> attempt latency is the ceiling (control);
* with ``wakeEvent`` it is 0 s when the wake lands in a backoff, and at most one
  in-flight attempt when it lands mid-attempt -- both within Atlas's 60 s target;
* a heartbeat that is never woken keeps its exact cadence (I-025 duty cycle).

Constants below are the measured figures the story quotes, not tuning knobs.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

import pi.obdii.obd_connection as obdConnectionModule
from pi.obdii.obd_connection import ObdConnection
from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.obdii.reconnect_loop import (
    BACKOFF_EXP_CAP,
    HEARTBEAT_TICK_INTERVAL_SEC,
    runReconnectHeartbeat,
)

#: connection_log 2026-09-14: each failed key-off attempt took ~42-45 s.
MEASURED_ATTEMPT_SEC = 45.0

#: Atlas ruling 2026-09-14 (US-751 acceptance): bounded key-on latency <= 60 s.
KEY_ON_TARGET_SEC = 60.0

#: The production heartbeat's idle ceiling: 10 s * 2 ** 5 = 320 s (US-325).
CEILING_SEC = HEARTBEAT_TICK_INTERVAL_SEC * 2**BACKOFF_EXP_CAP

NEVER = float("inf")


# ================================================================================
# The simulated car
# ================================================================================


class SleepingCar:
    """A fake clock plus an ECU that answers only once the key is on.

    ``connect`` is the heartbeat's per-tick attempt: it costs
    ``MEASURED_ATTEMPT_SEC`` of modelled time and succeeds only when it STARTED
    after key-on.  ``sleep`` is the heartbeat's backoff.  When ``wakeEvent`` is
    given, the wake fires at ``wakeAt`` -- cutting a backoff short exactly as
    ``Event.wait`` does, or landing mid-attempt without interrupting it.
    """

    def __init__(
        self,
        keyOnAt: float,
        wakeEvent: threading.Event | None = None,
        wakeAt: float | None = None,
    ) -> None:
        self.now = 0.0
        self.keyOnAt = keyOnAt
        self.wakeEvent = wakeEvent
        self.wakeAt = keyOnAt if wakeAt is None else wakeAt
        self.wakeSent = False
        self.attemptStarts: list[float] = []
        self.sleeps: list[float] = []
        self.connectedAt: float | None = None

    def _wakeDue(self, until: float) -> bool:
        return (
            self.wakeEvent is not None
            and not self.wakeSent
            and self.now <= self.wakeAt <= until
        )

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        target = self.now + seconds
        if self._wakeDue(target):
            assert self.wakeEvent is not None
            self.wakeSent = True
            self.now = self.wakeAt
            self.wakeEvent.set()
            return
        self.now = target

    def connect(self) -> bool:
        start = self.now
        self.attemptStarts.append(start)
        end = start + MEASURED_ATTEMPT_SEC
        if self._wakeDue(end):
            assert self.wakeEvent is not None
            self.wakeSent = True
            self.wakeEvent.set()
        self.now = end
        if start >= self.keyOnAt:
            self.connectedAt = end
            return True
        return False

    def isConnected(self) -> bool:
        return self.connectedAt is not None

    def firstAttemptAtOrAfter(self, moment: float) -> float:
        return next(start for start in self.attemptStarts if start >= moment)


def _drive(car: SleepingCar, maxTicks: int, wakeEvent: threading.Event | None = None) -> int:
    return runReconnectHeartbeat(
        connectFn=car.connect,
        isConnectedFn=car.isConnected,
        sleepFn=car.sleep,
        monotonicFn=lambda: car.now,
        wakeEvent=wakeEvent,
        maxTicks=maxTicks,
    )


def _overnightAttemptStarts(ticks: int) -> list[float]:
    """Attempt start times of a heartbeat against a car that never wakes."""
    car = SleepingCar(keyOnAt=NEVER)
    _drive(car, maxTicks=ticks)
    return car.attemptStarts


# ================================================================================
# 1. Modelled wake -> attempt latency
# ================================================================================


class TestWakeToAttemptLatency:
    """validationCriterion 1: simulated ECU-wake transition, latency measured."""

    def test_noWake_keyOnJustAfterACeilingAttempt_waitsOutTheCeiling_control(self) -> None:
        """
        Given: a heartbeat at its 320 s ceiling after a night of failures
        When:  the key goes on 1 s after an attempt fails, and nothing wakes it
        Then:  the next attempt starts 319 s later -- the 2026-09-14 defect
        """
        starts = _overnightAttemptStarts(ticks=12)
        keyOnAt = starts[10] + MEASURED_ATTEMPT_SEC + 1.0
        car = SleepingCar(keyOnAt=keyOnAt)

        _drive(car, maxTicks=20)

        latency = car.firstAttemptAtOrAfter(keyOnAt) - keyOnAt
        assert latency == pytest.approx(CEILING_SEC - 1.0)
        assert latency > KEY_ON_TARGET_SEC

    def test_wakeInABackoff_attemptsImmediately(self) -> None:
        """
        Given: the same overnight heartbeat and the same key-on moment
        When:  the wake is signalled at key-on
        Then:  the attempt starts AT the wake (0 s), the heartbeat consumed the
               wake, and the link is up one attempt later -- 45 s, inside the
               60 s target.  (The fake ends the sleep at the wake the way
               Event.wait does; test_wakeEndsARealBackoffSleep proves the real
               sleep is interruptible.)
        """
        starts = _overnightAttemptStarts(ticks=12)
        keyOnAt = starts[10] + MEASURED_ATTEMPT_SEC + 1.0
        wake = threading.Event()
        car = SleepingCar(keyOnAt=keyOnAt, wakeEvent=wake)

        _drive(car, maxTicks=20, wakeEvent=wake)

        latency = car.firstAttemptAtOrAfter(keyOnAt) - keyOnAt
        assert wake.is_set() is False, "the heartbeat never consumed the wake"
        assert latency == pytest.approx(0.0)
        assert car.connectedAt is not None
        assert car.connectedAt - keyOnAt <= KEY_ON_TARGET_SEC

    def test_wakeDuringAnAttempt_isBoundedByThatOneAttempt(self) -> None:
        """
        Given: the key goes on 1 s into an attempt that started with the ECU asleep
        When:  the wake is signalled then
        Then:  the next attempt starts when that attempt returns (44 s), not
               after a ceiling backoff -- the connect attempt itself is the floor
        """
        starts = _overnightAttemptStarts(ticks=12)
        keyOnAt = starts[10] + 1.0
        wake = threading.Event()
        car = SleepingCar(keyOnAt=keyOnAt, wakeEvent=wake)

        _drive(car, maxTicks=20, wakeEvent=wake)

        latency = car.firstAttemptAtOrAfter(keyOnAt) - keyOnAt
        assert wake.is_set() is False, "the heartbeat never consumed the wake"
        assert latency == pytest.approx(MEASURED_ATTEMPT_SEC - 1.0)
        assert latency <= KEY_ON_TARGET_SEC

    def test_wake_restartsTheLadderAtTheBaseInterval(self) -> None:
        """
        Given: a heartbeat at its ceiling, woken, with the ECU still asleep
        When:  the attempts after the wake keep failing
        Then:  the backoffs climb again from 10 s -- the ladder a boot pays
        """
        starts = _overnightAttemptStarts(ticks=12)
        wakeAt = starts[10] + MEASURED_ATTEMPT_SEC + 1.0
        wake = threading.Event()
        car = SleepingCar(keyOnAt=NEVER, wakeEvent=wake, wakeAt=wakeAt)

        _drive(car, maxTicks=15, wakeEvent=wake)

        cutIndex = car.sleeps.index(CEILING_SEC)
        while car.sleeps[cutIndex] == CEILING_SEC:
            cutIndex += 1
        # sleeps[cutIndex - 1] is the ceiling backoff the wake cut short.
        assert car.sleeps[cutIndex : cutIndex + 3] == [10.0, 20.0, 40.0]
        assert wake.is_set() is False

    def test_wakeEndsARealBackoffSleep(self) -> None:
        """
        Given: the heartbeat's DEFAULT sleep with a 30 s backoff
        When:  another thread signals the wake 50 ms in
        Then:  the heartbeat is back attempting within a few seconds, not 30
        """
        wake = threading.Event()
        attempts: list[float] = []

        def connectFn() -> bool:
            attempts.append(time.monotonic())
            return False

        timer = threading.Timer(0.05, wake.set)
        started = time.monotonic()
        timer.start()
        try:
            runReconnectHeartbeat(
                connectFn=connectFn,
                isConnectedFn=lambda: False,
                wakeEvent=wake,
                tickIntervalSec=30.0,
                maxTicks=2,
            )
        finally:
            timer.cancel()

        assert len(attempts) == 2
        assert attempts[1] - started < 5.0


# ================================================================================
# 2. Idle cost: attempt count and radio cadence
# ================================================================================


class TestIdleCostUnchanged:
    """validationCriteria 4 and 7: bounded attempts, unchanged duty cycle."""

    def test_neverWoken_cadenceIsIdenticalToNoWakeEvent(self) -> None:
        """
        Given: two heartbeats against a car that never wakes
        When:  one carries an unset wakeEvent and the other none
        Then:  their backoffs and attempt times are identical
        """
        plain = SleepingCar(keyOnAt=NEVER)
        _drive(plain, maxTicks=15)

        wake = threading.Event()
        withSeam = SleepingCar(keyOnAt=NEVER)
        _drive(withSeam, maxTicks=15, wakeEvent=wake)

        assert withSeam.sleeps == plain.sleeps
        assert withSeam.attemptStarts == plain.attemptStarts

    def test_twelveHoursAsleep_attemptsAreBoundedAndBackedOff(self) -> None:
        """
        Given: an ECU asleep for 12 hours
        When:  the heartbeat runs the whole time
        Then:  attempts never stop, stay at or under one per ceiling cycle after
               the ramp, and no gap after the ramp is shorter than the ceiling
               -- not US-673's 275-retry loop
        """
        horizon = 12 * 3600.0
        car = SleepingCar(keyOnAt=NEVER)

        runReconnectHeartbeat(
            connectFn=car.connect,
            isConnectedFn=lambda: car.now >= horizon,
            sleepFn=car.sleep,
            monotonicFn=lambda: car.now,
        )

        bound = horizon / (CEILING_SEC + MEASURED_ATTEMPT_SEC) + BACKOFF_EXP_CAP + 1
        assert 0 < len(car.attemptStarts) <= bound
        assert all(gap == CEILING_SEC for gap in car.sleeps[BACKOFF_EXP_CAP:])


# ================================================================================
# 3. Retries are ONE visible series
# ================================================================================


class _FailingThenLiveFactory:
    """``obd.OBD`` factory: fails until ``liveFromCall``, then returns a live link."""

    def __init__(self, liveFromCall: float = NEVER) -> None:
        self.callCount = 0
        self.liveFromCall = liveFromCall

    def __call__(self, portstr: str, timeout: int) -> Any:
        self.callCount += 1
        if self.callCount >= self.liveFromCall:
            return _LiveObd()
        raise OSError("OBD connection not active after creation")


class _LiveObd:
    def __init__(self) -> None:
        self.alive = True

    def is_connected(self) -> bool:
        return self.alive

    def close(self) -> None:
        self.alive = False


def _pathConnection(factory: Any, maxRetries: int = 2) -> ObdConnection:
    return ObdConnection(
        {
            "pi": {
                "bluetooth": {
                    "macAddress": "/dev/rfcomm0",
                    "retryDelays": [],
                    "maxRetries": maxRetries,
                    "connectionTimeoutSeconds": 5,
                }
            }
        },
        obdFactory=factory,
    )


def _orchestrator() -> ApplicationOrchestrator:
    config: dict[str, Any] = {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "bluetooth": {"macAddress": "/dev/rfcomm0", "retryDelays": [], "maxRetries": 3},
            "sync": {"enabled": False},
        },
        "server": {},
    }
    return ApplicationOrchestrator(config=config, simulate=False)


def _recordRows(conn: ObdConnection, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    monkeypatch.setattr(
        conn,
        "_logConnectionEvent",
        lambda eventType, success=False, errorMessage=None, retryCount=0: rows.append(
            (eventType, retryCount)
        ),
    )
    return rows


class TestRetriesAreOneVisibleSeries:
    """validationCriteria 2 and 6: obdLink.retries visible; retry_count one series."""

    def test_bootConnectThenHeartbeat_retryCountIsOneMonotonicSeries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: the boot connect() (3 attempts) failing, then the PENDING
               heartbeat's single attempts through the REAL connect closure
        When:  every attempt fails
        Then:  connect_attempt rows read 0..6 -- one series, not 0,1,2 then 0,0,0,0
        """
        conn = _pathConnection(_FailingThenLiveFactory())
        rows = _recordRows(conn, monkeypatch)
        orch = _orchestrator()
        orch._connection = conn

        assert conn.connect() is False
        runReconnectHeartbeat(
            connectFn=orch._buildHeartbeatConnectFn(),
            isConnectedFn=conn.isConnected,
            sleepFn=lambda _s: None,
            maxTicks=4,
        )

        attemptRows = [count for event, count in rows if event == "connect_attempt"]
        assert attemptRows == list(range(7))

    def test_heartbeatBackoff_obdLinkRetriesAndStateAreHonestEveryTick(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: a PENDING heartbeat failing against a sleeping ECU
        When:  obdLink is read during every backoff, then the ECU wakes
        Then:  retries climb 1, 2, 3 (not 0 throughout), the state never claims
               a link it does not have, and the connected read is LINKED
        """
        from pi.splash.system_status_emitter import OBD_LINKED

        conn = _pathConnection(_FailingThenLiveFactory(liveFromCall=4))
        _recordRows(conn, monkeypatch)
        orch = _orchestrator()
        orch._connection = conn
        readings: list[tuple[str, int, bool]] = []

        def readDuringBackoff(_seconds: float) -> None:
            status = conn.getStatus()
            readings.append((status.state.value, status.retryCount, status.connected))

        runReconnectHeartbeat(
            connectFn=orch._buildHeartbeatConnectFn(),
            isConnectedFn=conn.isConnected,
            sleepFn=readDuringBackoff,
            maxTicks=10,
        )

        assert [retries for _state, retries, _conn in readings] == [1, 2, 3]
        assert all(not connected and state != "connected" for state, _r, connected in readings)
        linkState, retries, available, _reason = orch._gatherObdLinkState()
        assert (linkState, retries, available) == (OBD_LINKED, 3, True)

    def test_successfulConnect_nextOutageCountsFromZero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: an outage that ended in a connection after 2 failures
        When:  the link drops and a new outage's attempts fail
        Then:  the new outage's rows start again at 0
        """
        factory = _FailingThenLiveFactory(liveFromCall=3)
        conn = _pathConnection(factory)
        rows = _recordRows(conn, monkeypatch)

        assert conn.connect() is True
        conn.disconnect()
        factory.liveFromCall = NEVER
        rows.clear()
        conn.connectOnce()
        conn.connectOnce()

        assert [count for event, count in rows if event == "connect_attempt"] == [0, 1]


# ================================================================================
# 4. Mid-session recovery still works
# ================================================================================


class TestMidSessionRecoveryUnchanged:
    """validationCriterion 3: a link drop followed by the link returning."""

    def test_linkDropThenReturn_recoveryLoopReconnects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: a live session over a REAL ObdConnection whose link then drops
        When:  the REAL recovery loop runs and the dongle answers on its 2nd try
        Then:  the link is up, recovery is over, and no heartbeat was needed
        """
        factory = _FailingThenLiveFactory(liveFromCall=1)
        conn = _pathConnection(factory)
        _recordRows(conn, monkeypatch)
        assert conn.connect() is True

        assert conn.obd is not None
        conn.obd.alive = False
        factory.callCount = 0
        factory.liveFromCall = 2

        orch = _orchestrator()
        spawned: list[int] = []
        monkeypatch.setattr(orch, "_spawnPostFailureReconnectHeartbeat", lambda: spawned.append(1))
        orch._connection = conn
        orch._reconnectDelays = []
        orch._maxReconnectAttempts = 3
        orch._isReconnecting = True
        orch._reconnectAttempt = 0

        orch._reconnectionLoop()

        assert conn.isConnected() is True
        assert orch._isReconnecting is False
        assert orch._reconnectAttempt == 0
        assert spawned == []


# ================================================================================
# 5. No stale rfcomm node held across a failed attempt
# ================================================================================


class _HalfOpenObd:
    """What obd.OBD() returns with the adapter up and the ECU asleep."""

    def __init__(self, closes: list[int]) -> None:
        self._closes = closes

    def is_connected(self) -> bool:
        return False

    def close(self) -> None:
        self._closes.append(1)


class TestNoStaleRfcommAcrossAFailedAttempt:
    """validationCriterion 5: the OBD layer does not hold /dev/rfcomm0 open."""

    def test_heartbeatAttemptsAgainstSleepingEcu_closeAndReleaseEveryBind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: a MAC-configured connection whose adapter answers but ECU sleeps
        When:  three heartbeat attempts fail
        Then:  every open is closed, every bind is released, and nothing is left
               bound or open -- a /dev/rfcomm0 seen beside "Connected: no" is
               rfcomm-bind.service's lazy boot binding, not a held session
        """
        helper = obdConnectionModule.bluetooth_helper
        binds: list[str] = []
        releases: list[int] = []
        closes: list[int] = []

        def fakeBind(macAddress: str, device: int, channel: int) -> str:
            binds.append(macAddress)
            return f"/dev/rfcomm{device}"

        def noBluez(macAddress: str) -> Any:
            raise RuntimeError("bluez not present on the bench")

        monkeypatch.setattr(helper, "bindRfcomm", fakeBind)
        monkeypatch.setattr(helper, "releaseRfcomm", lambda device: releases.append(device))
        monkeypatch.setattr(helper, "ensureTrusted", noBluez)

        conn = ObdConnection(
            {
                "pi": {
                    "bluetooth": {
                        "macAddress": "00:04:3E:00:00:01",
                        "retryDelays": [],
                        "maxRetries": 0,
                    }
                }
            },
            obdFactory=lambda portstr, timeout: _HalfOpenObd(closes),
        )
        _recordRows(conn, monkeypatch)
        orch = _orchestrator()
        orch._connection = conn

        runReconnectHeartbeat(
            connectFn=orch._buildHeartbeatConnectFn(),
            isConnectedFn=conn.isConnected,
            sleepFn=lambda _s: None,
            maxTicks=3,
        )

        assert len(binds) == 3
        assert closes == [1, 1, 1]
        assert releases == [0, 0, 0]
        assert conn.obd is None
        assert conn._boundRfcomm is False


# ================================================================================
# 6. The wake seam reaches both heartbeats
# ================================================================================


class TestWakeSeamWiring:
    """requestObdLinkWake() is the one entry point; both heartbeats observe it."""

    @pytest.mark.parametrize(
        "spawnName", ["_spawnReconnectHeartbeatDaemon", "_spawnPostFailureReconnectHeartbeat"]
    )
    def test_everyHeartbeatSpawn_wiresTheOrchestratorsWakeEvent(
        self, spawnName: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: either orchestrator heartbeat spawn point
        When:  it starts runReconnectHeartbeat
        Then:  wakeEvent is the orchestrator's event, and requestObdLinkWake sets it
        """
        from unittest.mock import MagicMock

        captured: dict[str, Any] = {}

        def fakeHeartbeat(**kwargs: Any) -> int:
            captured.update(kwargs)
            return 0

        spawnGlobals = getattr(ApplicationOrchestrator, spawnName).__globals__
        monkeypatch.setitem(spawnGlobals, "runReconnectHeartbeat", fakeHeartbeat)
        orch = _orchestrator()
        orch._connection = MagicMock()

        getattr(orch, spawnName)()
        for thread in threading.enumerate():
            if thread.name in (
                "obd-reconnect-heartbeat",
                "us338-post-failure-reconnect-heartbeat",
            ):
                thread.join(timeout=3)

        assert captured.get("wakeEvent") is orch._obdWakeEvent
        assert orch._obdWakeEvent.is_set() is False
        orch.requestObdLinkWake("test")
        assert orch._obdWakeEvent.is_set() is True
