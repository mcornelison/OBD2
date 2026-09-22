################################################################################
# File Name: test_reachability_transition_log.py
# Purpose/Description: US-793-c -- an ECU reachability TRANSITION writes exactly
#                      one connection_log row (event_type ecu_reachability) and a
#                      steady state writes none, so the server can see which
#                      reachability state the EDR gate saw.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-21    | Rex (US-793-c)| Initial -- one row per transition, none in
#               |              | steady state, status read writes nothing.
# ================================================================================
################################################################################

"""US-793-c -- reachability transitions are visible in connection_log.

The four states are design-patterns.md §5 (unreachable != unreadable !=
not-yet-attempted).  The row's ``error_message`` carries the new state's
value; ``success`` is 1 only for ``answered``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from src.pi.data.connection_logger import (
    EVENT_CONNECT_ATTEMPT,
    EVENT_ECU_REACHABILITY,
    resetDedupStateForTests,
)
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.obd_connection import ObdConnection, Reachability

MAC = "00:11:22:33:44:55"


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
    """A linked python-obd double whose next query result is settable."""

    def __init__(self) -> None:
        self.next: Any = _Response(null=False)

    def is_connected(self) -> bool:
        return True

    def query(self, command: Any, force: bool = False) -> Any:
        if isinstance(self.next, BaseException):
            raise self.next
        return self.next

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _freshDedup() -> Iterator[None]:
    resetDedupStateForTests()
    yield
    resetDedupStateForTests()


@pytest.fixture
def db(tmp_path) -> ObdDatabase:
    database = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    database.initialize()
    return database


def _makeConnection(db: ObdDatabase, clock: _Clock) -> tuple[ObdConnection, _FakeObd]:
    conn = ObdConnection({"pi": {"bluetooth": {"macAddress": MAC}}}, db, monotonicFn=clock)
    fake = _FakeObd()
    conn.obd = fake
    return conn, fake


def _answer(conn: ObdConnection, fake: _FakeObd) -> None:
    fake.next = _Response(null=False)
    conn.query("RPM")


def _noAnswer(conn: ObdConnection, fake: _FakeObd) -> None:
    fake.next = _Response(null=True)
    conn.query("RPM")


def _unreadable(conn: ObdConnection, fake: _FakeObd) -> None:
    fake.next = RuntimeError("serial read exploded")
    with pytest.raises(RuntimeError):
        conn.query("RPM")


def _reachabilityRows(db: ObdDatabase) -> list[tuple[str, int]]:
    with db.connect() as dbConn:
        return [
            (row[0], row[1])
            for row in dbConn.execute(
                "SELECT error_message, success FROM connection_log "
                "WHERE event_type = ? ORDER BY id",
                (EVENT_ECU_REACHABILITY,),
            ).fetchall()
        ]


def _allEventTypes(db: ObdDatabase) -> list[str]:
    with db.connect() as dbConn:
        return [
            row[0]
            for row in dbConn.execute(
                "SELECT event_type FROM connection_log ORDER BY id"
            ).fetchall()
        ]


def test_keyOn_transitionThenSteadyState_exactlyOneRow(db: ObdDatabase) -> None:
    """
    Given: a fresh connection (NOT_YET_ATTEMPTED)
    When: the ECU answers, then keeps answering for ten minutes of reads
    Then: exactly one row (answered) -- the transition logs, the repeats do not
    """
    clock = _Clock()
    conn, fake = _makeConnection(db, clock)

    _answer(conn, fake)
    assert _reachabilityRows(db) == [("answered", 1)]

    for _ in range(600):
        clock.now += 1.0
        _answer(conn, fake)

    assert conn.getStatus().reachability is Reachability.ANSWERED
    assert _reachabilityRows(db) == [("answered", 1)]


def test_everyTransition_oneRowEach_inOrder(db: ObdDatabase) -> None:
    """
    Given: a connection walking through every reachability state
    When: answered -> (stale) did_not_answer -> could_not_determine ->
          answered -> disconnect (new generation: not_yet_attempted)
    Then: one row per transition, each naming the new state, none for repeats
    """
    clock = _Clock()
    conn, fake = _makeConnection(db, clock)

    _answer(conn, fake)
    _noAnswer(conn, fake)  # answer still fresh: ANSWERED, no row
    clock.now += conn.reachabilityFreshnessSeconds + 1.0
    _noAnswer(conn, fake)  # stale: DID_NOT_ANSWER
    _noAnswer(conn, fake)  # repeat
    _unreadable(conn, fake)  # COULD_NOT_DETERMINE
    _unreadable(conn, fake)  # repeat
    _answer(conn, fake)
    conn.disconnect()

    assert _reachabilityRows(db) == [
        ("answered", 1),
        ("did_not_answer", 0),
        ("could_not_determine", 0),
        ("answered", 1),
        ("not_yet_attempted", 0),
    ]


def test_startingState_isNotReportedAsATransition(db: ObdDatabase) -> None:
    """
    Given: a connection that never read the ECU (NOT_YET_ATTEMPTED)
    When: it disconnects
    Then: no reachability row -- nothing changed
    """
    conn, _ = _makeConnection(db, _Clock())

    conn.disconnect()

    assert _reachabilityRows(db) == []
    assert _allEventTypes(db) == ["disconnect"]


def test_statusRead_writesNoRow(db: ObdDatabase) -> None:
    """
    Given: an ANSWERED that has gone stale with no read since
    When: getStatus() is read, repeatedly
    Then: it reports DID_NOT_ANSWER but writes nothing -- the status read the
          gate makes while closed stays side-effect free
    """
    clock = _Clock()
    conn, fake = _makeConnection(db, clock)
    _answer(conn, fake)
    clock.now += conn.reachabilityFreshnessSeconds + 1.0

    for _ in range(5):
        assert conn.getStatus().reachability is Reachability.DID_NOT_ANSWER

    assert _reachabilityRows(db) == [("answered", 1)]


def test_reachabilityRow_doesNotReopenTheOutageTracker(db: ObdDatabase) -> None:
    """
    Given: a connect_attempt already logged for this outage
    When: a reachability transition is logged, then connect_attempt repeats
    Then: the repeat is still suppressed -- a reachability row is not a link
          state change and must not re-arm US-340b's "still trying" rows
    """
    clock = _Clock()
    conn, fake = _makeConnection(db, clock)

    conn._logConnectionEvent(EVENT_CONNECT_ATTEMPT)
    _answer(conn, fake)
    conn._logConnectionEvent(EVENT_CONNECT_ATTEMPT)

    assert _allEventTypes(db) == [EVENT_CONNECT_ATTEMPT, EVENT_ECU_REACHABILITY]


def test_noDatabase_queryStillWorks() -> None:
    """
    Given: a connection with no database
    When: the ECU answers
    Then: the read returns normally; nothing is written anywhere
    """
    conn = ObdConnection({"pi": {"bluetooth": {"macAddress": MAC}}}, None)
    fake = _FakeObd()
    conn.obd = fake

    response = conn.query("RPM")

    assert response is fake.next
