################################################################################
# File Name: test_connection_reachability.py
# Purpose/Description: US-793-a -- ConnectionStatus.reachability records whether
#                      the ECU answered, as one of FOUR distinguishable states,
#                      derived from what ObdConnection.query() already observes.
#                      A Bluetooth link is not an ECU; `connected` is unchanged.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-21    | Rex (US-793-a)| Initial -- four states, NOT_YET_ATTEMPTED per
#               |              | generation, freshness degrade, no-poll status read.
# ================================================================================
################################################################################

"""US-793-a -- the producer records ECU reachability, not just the link.

The dongle has constant power and is lit with the key out, so ``connected`` is
True on a parked car.  ``reachability`` is the separate fact the EDR gate
(US-793-b) needs: did the ECU answer a read the data path already made?
"""

from __future__ import annotations

from typing import Any

import pytest

from src.pi.obdii.drive.types import DEFAULT_DRIVE_END_DURATION_SECONDS
from src.pi.obdii.obd_connection import (
    ConnectionStatus,
    ObdConnection,
    ObdConnectionError,
    Reachability,
)

FRESHNESS_S = 60.0


class _Clock:
    """An injectable monotonic clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Response:
    """A python-obd response double."""

    def __init__(self, null: bool) -> None:
        self._null = null
        self.value = None if null else 800

    def is_null(self) -> bool:
        return self._null


class _FakeObd:
    """A python-obd double that counts every OBD request it is sent."""

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.queries: list[Any] = []
        self.next: Any = _Response(null=False)

    def is_connected(self) -> bool:
        return self.connected

    def query(self, command: Any, force: bool = False) -> Any:
        self.queries.append(command)
        if isinstance(self.next, BaseException):
            raise self.next
        return self.next

    def close(self) -> None:
        pass


def _makeConnection(
    clock: _Clock, analysis: dict[str, Any] | None = None
) -> tuple[ObdConnection, _FakeObd]:
    config: dict[str, Any] = {"pi": {"bluetooth": {"macAddress": "00:11:22:33:44:55"}}}
    if analysis is not None:
        config["pi"]["analysis"] = analysis
    conn = ObdConnection(config, monotonicFn=clock)
    fake = _FakeObd()
    conn.obd = fake
    return conn, fake


def _answer(conn: ObdConnection, fake: _FakeObd, command: Any = "RPM") -> None:
    fake.next = _Response(null=False)
    conn.query(command)


def _noAnswer(conn: ObdConnection, fake: _FakeObd, command: Any = "RPM") -> None:
    fake.next = _Response(null=True)
    conn.query(command)


def _unreadable(conn: ObdConnection, fake: _FakeObd, command: Any = "RPM") -> None:
    fake.next = RuntimeError("serial read exploded")
    with pytest.raises(RuntimeError):
        conn.query(command)


# ================================================================================
# Four distinguishable states
# ================================================================================


def test_reachability_fourStates_allDistinct() -> None:
    """
    Given: the Reachability vocabulary
    When: each member is constructed
    Then: there are exactly four and no two collapse (by identity or by value)
    """
    members = [
        Reachability.ANSWERED,
        Reachability.DID_NOT_ANSWER,
        Reachability.COULD_NOT_DETERMINE,
        Reachability.NOT_YET_ATTEMPTED,
    ]

    assert len(set(members)) == 4
    assert len({m.value for m in members}) == 4
    assert set(Reachability) == set(members)


@pytest.mark.parametrize(
    ("drive", "expected"),
    [
        (_answer, Reachability.ANSWERED),
        (_noAnswer, Reachability.DID_NOT_ANSWER),
        (_unreadable, Reachability.COULD_NOT_DETERMINE),
    ],
)
def test_getStatus_eachObservedOutcome_reportsItsOwnState(drive: Any, expected: Any) -> None:
    """
    Given: one ECU read through the data path with each outcome
    When: getStatus() is read
    Then: each outcome maps to its own state
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock)

    drive(conn, fake)

    assert conn.getStatus().reachability is expected


def test_getStatus_noReadYet_notYetAttempted_notCouldNotDetermine() -> None:
    """
    Given: a live link and no OBD read attempted (the parked-car cold boot)
    When: getStatus() is read
    Then: NOT_YET_ATTEMPTED -- never COULD_NOT_DETERMINE, which fails OPEN
    """
    conn, _ = _makeConnection(_Clock())

    status = conn.getStatus()

    assert status.reachability is Reachability.NOT_YET_ATTEMPTED
    assert status.reachability is not Reachability.COULD_NOT_DETERMINE


def test_getStatus_noConnectionObject_notYetAttempted() -> None:
    """
    Given: no python-obd object at all (before the first connect)
    When: getStatus() is read
    Then: NOT_YET_ATTEMPTED
    """
    conn, _ = _makeConnection(_Clock())
    conn.obd = None

    assert conn.getStatus().reachability is Reachability.NOT_YET_ATTEMPTED


def test_connectionStatus_defaultReachability_notYetAttempted() -> None:
    """
    Given: a freshly constructed ConnectionStatus
    When: reachability is read
    Then: NOT_YET_ATTEMPTED
    """
    assert ConnectionStatus().reachability is Reachability.NOT_YET_ATTEMPTED


def test_newGeneration_resetsToNotYetAttempted() -> None:
    """
    Given: the ECU answered on the previous connection generation
    When: the connection is torn down and a new object is in place
    Then: NOT_YET_ATTEMPTED -- an answer belongs to its own generation
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock)
    _answer(conn, fake)
    assert conn.getStatus().reachability is Reachability.ANSWERED

    conn.disconnect()
    conn.obd = _FakeObd()

    assert conn.getStatus().reachability is Reachability.NOT_YET_ATTEMPTED


# ================================================================================
# The ECU, not the adapter
# ================================================================================


def test_adapterLevelAnswer_isNotAnEcuAnswer() -> None:
    """
    Given: only the adapter-level ELM_VOLTAGE (ATRV) read answered -- the dongle
           measures pin 16 with the key out
    When: getStatus() is read
    Then: still NOT_YET_ATTEMPTED; an adapter answer is not the ECU answering
    """
    conn, fake = _makeConnection(_Clock())

    _answer(conn, fake, "ELM_VOLTAGE")

    assert conn.getStatus().reachability is Reachability.NOT_YET_ATTEMPTED


def test_adapterLevelCommandObject_byAtPrefix_isNotAnEcuAnswer() -> None:
    """
    Given: a python-obd command object whose request is an ELM327 AT command
    When: it answers
    Then: reachability is unchanged
    """
    conn, fake = _makeConnection(_Clock())

    class _Cmd:
        name = "ELM_VERSION"
        command = b"ATI"

    _answer(conn, fake, _Cmd())

    assert conn.getStatus().reachability is Reachability.NOT_YET_ATTEMPTED


def test_ecuCommandObject_answered() -> None:
    """
    Given: a python-obd Mode-01 command object
    When: it answers
    Then: ANSWERED
    """
    conn, fake = _makeConnection(_Clock())

    class _Cmd:
        name = "RPM"
        command = b"010C"

    _answer(conn, fake, _Cmd())

    assert conn.getStatus().reachability is Reachability.ANSWERED


# ================================================================================
# Freshness
# ================================================================================


def test_answered_pastFreshnessBound_degradesToDidNotAnswer_withNoPoll() -> None:
    """
    Given: the ECU answered once
    When: the injected clock advances past the freshness bound, no new read
    Then: DID_NOT_ANSWER -- ANSWERED never latches, and no OBD request was made
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock, {"driveEndDurationSeconds": FRESHNESS_S})
    _answer(conn, fake)
    requests = len(fake.queries)

    clock.now += FRESHNESS_S
    assert conn.getStatus().reachability is Reachability.ANSWERED

    clock.now += 0.001
    status = conn.getStatus()

    assert status.reachability is Reachability.DID_NOT_ANSWER
    assert len(fake.queries) == requests


def test_freshnessBound_defaultsToDriveEndDuration() -> None:
    """
    Given: no pi.analysis.driveEndDurationSeconds configured
    When: the answer ages just past the drive detector's own ECU-silence bound
    Then: DID_NOT_ANSWER -- one silence bound, not a second number
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock)
    _answer(conn, fake)

    clock.now += DEFAULT_DRIVE_END_DURATION_SECONDS
    assert conn.getStatus().reachability is Reachability.ANSWERED

    clock.now += 0.001
    assert conn.getStatus().reachability is Reachability.DID_NOT_ANSWER


def test_freshAnswer_notOverriddenByOneNullPid() -> None:
    """
    Given: the ECU answered, then one PID came back null inside the bound
    When: getStatus() is read
    Then: still ANSWERED -- a live ECU with one unsupported PID is still answering
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock)
    _answer(conn, fake)
    clock.now += 1.0

    _noAnswer(conn, fake, "O2_B1S2")

    assert conn.getStatus().reachability is Reachability.ANSWERED


def test_staleAnswer_thenUnreadableRead_couldNotDetermine() -> None:
    """
    Given: a stale answer, then a read that raised
    When: getStatus() is read
    Then: COULD_NOT_DETERMINE -- the latest attempt could not be read
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock)
    _answer(conn, fake)
    clock.now += DEFAULT_DRIVE_END_DURATION_SECONDS + 1

    _unreadable(conn, fake)

    assert conn.getStatus().reachability is Reachability.COULD_NOT_DETERMINE


def test_unreadable_thenNullRead_didNotAnswer() -> None:
    """
    Given: a read that raised, then a read the ECU did not answer
    When: getStatus() is read
    Then: DID_NOT_ANSWER -- the latest completed read is the verdict
    """
    conn, fake = _makeConnection(_Clock())
    _unreadable(conn, fake)

    _noAnswer(conn, fake)

    assert conn.getStatus().reachability is Reachability.DID_NOT_ANSWER


# ================================================================================
# `connected` is unchanged, and the status read is not a poll
# ================================================================================


def test_linkedToDongle_noEcu_connectedTrueAndDidNotAnswer() -> None:
    """
    Given: parked, key out, dongle lit, BT linked; the ECU does not answer
    When: getStatus() is read
    Then: connected=True AND reachability=DID_NOT_ANSWER at the same time
    """
    conn, fake = _makeConnection(_Clock())
    _noAnswer(conn, fake)

    status = conn.getStatus()

    assert status.connected is True
    assert status.reachability is Reachability.DID_NOT_ANSWER


def test_getStatus_issuesNoObdRequest() -> None:
    """
    Given: a live connection in each reachability state
    When: getStatus() is read repeatedly
    Then: not one OBD request is sent -- a status read is never a poll
    """
    clock = _Clock()
    conn, fake = _makeConnection(clock)

    for _ in range(3):
        conn.getStatus()
    assert fake.queries == []

    _answer(conn, fake)
    requests = len(fake.queries)
    for _ in range(3):
        conn.getStatus()
        clock.now += DEFAULT_DRIVE_END_DURATION_SECONDS

    assert len(fake.queries) == requests


def test_fencedOrUnconnectedQuery_isNotAnAttempt() -> None:
    """
    Given: a query refused before any I/O (obd is None)
    When: getStatus() is read
    Then: NOT_YET_ATTEMPTED -- no read reached the ECU
    """
    conn, _ = _makeConnection(_Clock())
    conn.obd = None

    with pytest.raises(ObdConnectionError):
        conn.query("RPM")

    assert conn.getStatus().reachability is Reachability.NOT_YET_ATTEMPTED
