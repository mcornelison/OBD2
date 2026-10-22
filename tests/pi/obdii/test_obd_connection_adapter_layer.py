################################################################################
# File Name: test_obd_connection_adapter_layer.py
# Purpose/Description: US-876-d -- ConnectionStatus carries the ADAPTER
#                      observation: whether the ELM answered (obd.status() of
#                      THIS attempt's object, read before the partial close; a
#                      connect success; any answered query on a held session,
#                      ATRV included), the wall time it took that value, and
#                      the last answer. Null after 2 x the reconnect
#                      heartbeat's longest interval (Atlas L4, D1-D6).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-876-d)| Initial -- connect-time status() read, D6
#               |              | candidate-only, ATRV on a held session,
#               |              | freshness bound, toDict unchanged.
# ================================================================================
################################################################################

"""US-876-d -- the adapter layer's evidence, recorded by the connection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.pi.obdii.obd_connection import ConnectionStatus, ObdConnection, Reachability
from src.pi.obdii.reconnect_loop import BACKOFF_EXP_CAP, HEARTBEAT_TICK_INTERVAL_SEC

# python-OBD 0.7.3 obd/utils.py OBDStatus values (Atlas D1).
_NOT_CONNECTED = "Not Connected"
_ELM_CONNECTED = "ELM Connected"
_OBD_CONNECTED = "OBD Connected"
_CAR_CONNECTED = "Car Connected"

_NO_STATUS = object()


class _Clocks:
    """A monotonic clock and a wall clock that move together."""

    def __init__(self) -> None:
        self.mono = 1000.0
        self.wall = datetime(2026, 10, 22, 15, 0, 0, tzinfo=UTC)

    def monotonic(self) -> float:
        return self.mono

    def wallNow(self) -> datetime:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.mono += seconds
        self.wall += timedelta(seconds=seconds)


class _Response:
    def __init__(self, null: bool) -> None:
        self._null = null
        self.value = None if null else 12.6

    def is_null(self) -> bool:
        return self._null


class _AtrvCommand:
    """python-obd's ELM_VOLTAGE: an ``AT`` command the dongle answers itself."""

    name = "ELM_VOLTAGE"
    command = b"ATRV"


class _AttemptObd:
    """What one connect attempt's factory returns.

    ``status`` is the python-OBD status string, an exception to raise, or
    ``_NO_STATUS`` for a fake with no ``status()`` method at all.
    """

    def __init__(self, *, connected: bool, status: Any = _NO_STATUS) -> None:
        self._connected = connected
        self.closed = False
        if status is not _NO_STATUS:
            self.status = self._makeStatus(status)

    @staticmethod
    def _makeStatus(status: Any) -> Any:
        def _status() -> Any:
            if isinstance(status, BaseException):
                raise status
            return status

        return _status

    def is_connected(self) -> bool:
        return self._connected

    def query(self, command: Any, force: bool = False) -> Any:
        return self.next

    def close(self) -> None:
        self.closed = True


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _makeConnection(
    clocks: _Clocks, factory: Any = None, *, config: dict[str, Any] | None = None
) -> ObdConnection:
    # A literal device path: no rfcomm bind or release is ever attempted.
    bluetooth = {"macAddress": "/dev/rfcomm0", "retryDelays": []}
    bluetooth.update(config or {})
    return ObdConnection(
        {"pi": {"bluetooth": bluetooth}},
        obdFactory=factory,
        monotonicFn=clocks.monotonic,
        wallClockFn=clocks.wallNow,
    )


def _attemptReturning(obd: Any) -> Any:
    return lambda port, timeout: obd


def _attemptRaising(error: BaseException) -> Any:
    def _factory(port: Any, timeout: Any) -> Any:
        raise error

    return _factory


# ---------------------------------------------------------------------------
# Connect-time observation
# ---------------------------------------------------------------------------


def test_elmAnsweredAtConnect_ecuSilent_adapterAnswered_ecuNotYetAttempted() -> None:
    """
    Given: a connect attempt where the ELM answers ATZ but the ECU is silent
           (key off: status 'ELM Connected', is_connected() False)
    When: the attempt fails and getStatus() is read later
    Then: adapterAnswered True, dated the attempt; the ECU layer is untouched
    """
    clocks = _Clocks()
    obd = _AttemptObd(connected=False, status=_ELM_CONNECTED)
    conn = _makeConnection(clocks, _attemptReturning(obd))

    clocks.advance(4)
    attemptAt = clocks.wall
    assert conn.connectOnce() is False
    clocks.advance(30)
    status = conn.getStatus()

    assert status.adapterAnswered is True
    assert status.adapterChangedAtUtc == _iso(attemptAt)
    assert status.adapterLastOkAtUtc == _iso(attemptAt)
    assert status.reachability is Reachability.NOT_YET_ATTEMPTED
    # Fix B unchanged: the partial connection was still closed after the read.
    assert obd.closed is True
    assert conn.obd is None


@pytest.mark.parametrize("statusValue", [_ELM_CONNECTED, _OBD_CONNECTED, _CAR_CONNECTED])
def test_elmConnectedOrBetter_onAFailedAttempt_isAnswered(statusValue: str) -> None:
    clocks = _Clocks()
    conn = _makeConnection(
        clocks, _attemptReturning(_AttemptObd(connected=False, status=statusValue))
    )

    conn.connectOnce()

    assert conn.getStatus().adapterAnswered is True


@pytest.mark.parametrize(
    "statusValue",
    [_NOT_CONNECTED, None, RuntimeError("status exploded"), "Garbage"],
    ids=["not-connected", "none", "raises", "unknown-string"],
)
def test_belowTheElm_noneOrARaise_isDidNotAnswer(statusValue: Any) -> None:
    clocks = _Clocks()
    obd = _AttemptObd(connected=False, status=statusValue)
    conn = _makeConnection(clocks, _attemptReturning(obd))

    conn.connectOnce()
    status = conn.getStatus()

    assert status.adapterAnswered is False
    assert status.adapterLastOkAtUtc is None
    assert obd.closed is True


def test_aFakeWithoutStatus_isDidNotAnswer_andCleanupIsUnchanged() -> None:
    """
    Given: a test double with no status() method (every pre-US-876-d fake)
    When: its attempt fails
    Then: did not answer -- and it is still closed and dropped (Fix B)
    """
    clocks = _Clocks()
    obd = _AttemptObd(connected=False)
    conn = _makeConnection(clocks, _attemptReturning(obd))

    assert conn.connectOnce() is False

    assert conn.getStatus().adapterAnswered is False
    assert obd.closed is True
    assert conn.obd is None


def test_portOpenFails_isDidNotAnswer_neverThePreviousSessionsStatus() -> None:
    """
    D6: self.obd is not cleared before the factory runs. A factory raise must
    read as did-not-answer even while the previous session's object (which
    would say 'Car Connected') is still on self.obd.
    """
    clocks = _Clocks()
    previous = _AttemptObd(connected=True, status=_CAR_CONNECTED)
    conn = _makeConnection(clocks, _attemptRaising(OSError("could not open port")))
    conn.obd = previous

    clocks.advance(2)
    failedAt = clocks.wall
    assert conn.connectOnce() is False
    status = conn.getStatus()

    assert status.adapterAnswered is False
    assert status.adapterChangedAtUtc == _iso(failedAt)


def test_aConnectSuccess_isAnAnsweredObservation() -> None:
    clocks = _Clocks()
    conn = _makeConnection(
        clocks, _attemptReturning(_AttemptObd(connected=True, status=_CAR_CONNECTED))
    )

    clocks.advance(1)
    connectedAt = clocks.wall
    assert conn.connectOnce() is True
    status = conn.getStatus()

    assert status.adapterAnswered is True
    assert status.adapterChangedAtUtc == _iso(connectedAt)


def test_answeredThenAFailedAttempt_changesValue_keepsTheLastOk() -> None:
    clocks = _Clocks()
    answering = _AttemptObd(connected=False, status=_ELM_CONNECTED)
    conn = _makeConnection(clocks, _attemptReturning(answering))
    conn.connectOnce()
    okAt = clocks.wall

    conn._obdFactory = _attemptRaising(OSError("gone"))
    clocks.advance(320)
    failedAt = clocks.wall
    conn.connectOnce()
    status = conn.getStatus()

    assert status.adapterAnswered is False
    assert status.adapterChangedAtUtc == _iso(failedAt)
    assert status.adapterLastOkAtUtc == _iso(okAt)


def test_aRepeatedValue_keepsItsFirstChangeInstant() -> None:
    clocks = _Clocks()
    conn = _makeConnection(
        clocks, _attemptReturning(_AttemptObd(connected=False, status=_ELM_CONNECTED))
    )
    conn.connectOnce()
    firstAt = clocks.wall
    clocks.advance(320)
    conn.connectOnce()
    secondAt = clocks.wall

    status = conn.getStatus()

    assert status.adapterChangedAtUtc == _iso(firstAt)
    assert status.adapterLastOkAtUtc == _iso(secondAt)


# ---------------------------------------------------------------------------
# Held-session observation (D4)
# ---------------------------------------------------------------------------


def test_heldSessionAtrv_isAdapterAnswered_atThatTime_andNotAnEcuRead() -> None:
    """
    Given: a held session (the link up) and an ATRV read that returns a voltage
    When: getStatus() is read
    Then: adapter answered, dated the ATRV; the ECU reachability is untouched
          (the _recordEcuRead AT early return still ignores it)
    """
    clocks = _Clocks()
    conn = _makeConnection(clocks)
    obd = _AttemptObd(connected=True)
    obd.next = _Response(null=False)
    conn.obd = obd

    clocks.advance(7)
    atrvAt = clocks.wall
    conn.query(_AtrvCommand())
    clocks.advance(3)
    status = conn.getStatus()

    assert status.adapterAnswered is True
    assert status.adapterChangedAtUtc == _iso(atrvAt)
    assert status.adapterLastOkAtUtc == _iso(atrvAt)
    assert status.reachability is Reachability.NOT_YET_ATTEMPTED


def test_heldSessionNullRead_isNoAdapterObservation() -> None:
    clocks = _Clocks()
    conn = _makeConnection(clocks)
    obd = _AttemptObd(connected=True)
    obd.next = _Response(null=True)
    conn.obd = obd

    conn.query(_AtrvCommand())

    assert conn.getStatus().adapterAnswered is None


def test_theRealEcuPath_isUnchanged_andAnAnsweredEcuReadIsTheElmAnswering() -> None:
    clocks = _Clocks()
    conn = _makeConnection(clocks)
    obd = _AttemptObd(connected=True)
    obd.next = _Response(null=False)
    conn.obd = obd

    conn.query("RPM")
    status = conn.getStatus()

    assert status.reachability is Reachability.ANSWERED
    assert status.adapterAnswered is True


# ---------------------------------------------------------------------------
# Freshness (D5)
# ---------------------------------------------------------------------------


def test_freshnessBound_isTwiceTheHeartbeatsLongestInterval_notTheRetryCeiling() -> None:
    clocks = _Clocks()
    conn = _makeConnection(clocks, config={"retryCeilingSeconds": 30})

    assert conn.adapterFreshnessSeconds == (
        2 * HEARTBEAT_TICK_INTERVAL_SEC * 2 ** BACKOFF_EXP_CAP
    )
    assert conn.adapterFreshnessSeconds == 640


def test_noObservationForTheBound_isNull_justInsideItIsNot() -> None:
    """
    Given: the ELM answered once
    When: 640 s pass with no further observation, then one more second
    Then: still answered at 640 s; {None, None} at 641 s (lastOk survives)
    """
    clocks = _Clocks()
    conn = _makeConnection(
        clocks, _attemptReturning(_AttemptObd(connected=False, status=_ELM_CONNECTED))
    )
    conn.connectOnce()
    okAt = clocks.wall

    clocks.advance(640)
    inside = conn.getStatus()
    insideAnswered, insideTs = inside.adapterAnswered, inside.adapterChangedAtUtc
    clocks.advance(1)
    stale = conn.getStatus()

    assert (insideAnswered, insideTs) == (True, _iso(okAt))
    assert stale.adapterAnswered is None
    assert stale.adapterChangedAtUtc is None
    assert stale.adapterLastOkAtUtc == _iso(okAt)


def test_aStaleObservation_reEntersDatedTheNewEvent_evenWithTheSameValue() -> None:
    clocks = _Clocks()
    conn = _makeConnection(
        clocks, _attemptReturning(_AttemptObd(connected=False, status=_ELM_CONNECTED))
    )
    conn.connectOnce()
    clocks.advance(700)
    againAt = clocks.wall
    conn.connectOnce()

    assert conn.getStatus().adapterChangedAtUtc == _iso(againAt)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_adapterFields_defaultNull_andStayOutOfToDict() -> None:
    status = ConnectionStatus()

    assert status.adapterAnswered is None
    assert status.adapterChangedAtUtc is None
    assert status.adapterLastOkAtUtc is None
    assert not {
        "adapterAnswered", "adapterChangedAtUtc", "adapterLastOkAtUtc"
    } & set(status.toDict())


def test_noObservationYet_isNull() -> None:
    clocks = _Clocks()
    status = _makeConnection(clocks).getStatus()

    assert status.adapterAnswered is None
    assert status.adapterChangedAtUtc is None
    assert status.adapterLastOkAtUtc is None
