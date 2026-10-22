################################################################################
# File Name: test_obd_connection_reachability_ts.py
# Purpose/Description: US-876-c -- ConnectionStatus carries the WALL-CLOCK
#                      canonical-UTC time of the ECU reachability's last
#                      transition (ecuChangedAtUtc) and of the last answer this
#                      session (ecuLastOkAtUtc). Reachability itself runs on the
#                      monotonic clock; these are the event instants link.ecu
#                      publishes, never the publish tick (Atlas C3/C4/C5).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Rex (US-876-c)| Initial -- transition ts per reachability change,
#               |              | decay instant, generation bump, toDict unchanged.
# ================================================================================
################################################################################

"""US-876-c -- the ECU layer's transition time, stamped by the producer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.pi.obdii.obd_connection import ConnectionStatus, ObdConnection, Reachability


class _Clocks:
    """A monotonic clock and a wall clock that the test moves independently."""

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
        self.value = None if null else 800

    def is_null(self) -> bool:
        return self._null


class _FakeObd:
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


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _makeConnection(clocks: _Clocks) -> tuple[ObdConnection, _FakeObd]:
    config: dict[str, Any] = {"pi": {"bluetooth": {"macAddress": "00:11:22:33:44:55"}}}
    conn = ObdConnection(
        config, monotonicFn=clocks.monotonic, wallClockFn=clocks.wallNow
    )
    fake = _FakeObd()
    conn.obd = fake
    return conn, fake


def _read(conn: ObdConnection, fake: _FakeObd, response: Any) -> None:
    fake.next = response
    if isinstance(response, BaseException):
        with pytest.raises(type(response)):
            conn.query("RPM")
    else:
        conn.query("RPM")


def test_construction_notYetAttempted_tsIsTheConstructionInstant() -> None:
    """
    Given: a freshly built connection (the start of this session's first attempt)
    When: getStatus() is read later
    Then: NOT_YET_ATTEMPTED, dated when the connection came up -- not the read
    """
    clocks = _Clocks()
    conn, _ = _makeConnection(clocks)
    built = clocks.wall

    clocks.advance(42)
    status = conn.getStatus()

    assert status.reachability is Reachability.NOT_YET_ATTEMPTED
    assert status.ecuChangedAtUtc == _iso(built)
    assert status.ecuLastOkAtUtc is None


def test_answer_tsIsTheFirstAnswer_notTheLaterAnswersOrThePublish() -> None:
    """
    Given: the ECU answers at T1 and again at T2
    When: getStatus() is read at T3
    Then: the transition ts is T1 (the entry into ANSWERED); lastOk is T2
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)

    clocks.advance(5)
    t1 = clocks.wall
    _read(conn, fake, _Response(null=False))
    clocks.advance(2)
    t2 = clocks.wall
    _read(conn, fake, _Response(null=False))
    clocks.advance(3)
    status = conn.getStatus()

    assert status.reachability is Reachability.ANSWERED
    assert status.ecuChangedAtUtc == _iso(t1)
    assert status.ecuLastOkAtUtc == _iso(t2)


def test_staleDecay_tsIsLastAnswerPlusTheWindow_neverThePublishTick() -> None:
    """
    Given: an answer at T1, then no reads at all (the decay is side-effect free)
    When: getStatus() is read long after the freshness window
    Then: DID_NOT_ANSWER, dated T1 + the window (Atlas C3), not the read time
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)
    window = conn.reachabilityFreshnessSeconds

    t1 = clocks.wall
    _read(conn, fake, _Response(null=False))
    clocks.advance(window + 600)
    status = conn.getStatus()

    assert status.reachability is Reachability.DID_NOT_ANSWER
    assert status.ecuChangedAtUtc == _iso(t1 + timedelta(seconds=window))
    assert status.ecuLastOkAtUtc == _iso(t1)


def test_staleDecay_thenANullRead_keepsTheDecayInstant() -> None:
    """
    Given: an answer that decayed, then a null read much later
    When: getStatus() is read
    Then: still DID_NOT_ANSWER at the decay instant -- the null read is not a
          transition, so it does not re-date the state
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)
    window = conn.reachabilityFreshnessSeconds

    t1 = clocks.wall
    _read(conn, fake, _Response(null=False))
    clocks.advance(window + 300)
    _read(conn, fake, _Response(null=True))
    clocks.advance(10)

    assert conn.getStatus().ecuChangedAtUtc == _iso(t1 + timedelta(seconds=window))


def test_nullRead_fromNotYetAttempted_isATransitionAtTheRead() -> None:
    """
    Given: no read yet, then a null read at T1
    When: getStatus() is read
    Then: DID_NOT_ANSWER dated T1
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)

    clocks.advance(7)
    t1 = clocks.wall
    _read(conn, fake, _Response(null=True))
    clocks.advance(4)
    status = conn.getStatus()

    assert status.reachability is Reachability.DID_NOT_ANSWER
    assert status.ecuChangedAtUtc == _iso(t1)


def test_couldNotDetermine_tsIsTheRaisingRead() -> None:
    """
    Given: a read that raises at T1
    When: getStatus() is read
    Then: COULD_NOT_DETERMINE dated T1
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)

    clocks.advance(3)
    t1 = clocks.wall
    _read(conn, fake, RuntimeError("serial read exploded"))
    clocks.advance(5)
    status = conn.getStatus()

    assert status.reachability is Reachability.COULD_NOT_DETERMINE
    assert status.ecuChangedAtUtc == _iso(t1)


def test_generationBump_resetsToNotYetAttempted_datedTheBump() -> None:
    """
    Given: the ECU answered, then the connection is torn down at T2
    When: getStatus() is read later
    Then: NOT_YET_ATTEMPTED dated T2 (Atlas C4); lastOk survives the bump --
          it is this SESSION's last answer, not this generation's
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)

    t1 = clocks.wall
    _read(conn, fake, _Response(null=False))
    clocks.advance(20)
    t2 = clocks.wall
    conn.disconnect()
    clocks.advance(9)
    status = conn.getStatus()

    assert status.reachability is Reachability.NOT_YET_ATTEMPTED
    assert status.ecuChangedAtUtc == _iso(t2)
    assert status.ecuLastOkAtUtc == _iso(t1)


def test_tsFields_areCanonicalUtc_andStayOutOfToDict() -> None:
    """
    Given: a status after an answer
    When: it is serialised with toDict()
    Then: the new fields are canonical UTC strings and toDict() is unchanged (C5)
    """
    clocks = _Clocks()
    conn, fake = _makeConnection(clocks)
    _read(conn, fake, _Response(null=False))

    status = conn.getStatus()

    assert status.ecuChangedAtUtc is not None
    assert status.ecuChangedAtUtc.endswith("Z") and "T" in status.ecuChangedAtUtc
    assert "ecuChangedAtUtc" not in status.toDict()
    assert "ecuLastOkAtUtc" not in status.toDict()


def test_connectionStatus_defaults_haveNoTransitionTs() -> None:
    """A bare ConnectionStatus has not been stamped by a producer: both None."""
    status = ConnectionStatus()

    assert status.ecuChangedAtUtc is None
    assert status.ecuLastOkAtUtc is None
