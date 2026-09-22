################################################################################
# File Name: test_connection_signal_readable.py
# Purpose/Description: US-767-a -- ConnectionStatus.signalReadable records whether
#                      the link read that set `connected` completed, so the EDR
#                      gate can tell "link down" from "could not read the link".
#                      `connected` keeps its exact pre-US-767-a meaning.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-a)| Initial -- signalReadable contract, `connected`
#               |              | unchanged table, reader enumeration.
# 2026-09-21    | Rex (US-793-b)| The EDR gate no longer reads signalReadable
#               |              | (it gates on reachability): the producer is
#               |              | now the ONLY module naming the field.
# ================================================================================
################################################################################

"""US-767-a -- the producer records whether its own link read completed.

``ObdConnection._isConnected()`` used to be a bare ``except Exception: return
False``: a raising ``is_connected()`` was byte-identical to a genuinely down
link.  ``getStatus()`` now sets ``signalReadable`` in the same read that sets
``connected``.

The RAISING case is produced here only by patching.  python-obd's
``OBD.is_connected()`` is ``self.status() == OBDStatus.CAR_CONNECTED`` and
``status()`` returns a cached value (``NOT_CONNECTED`` when there is no
interface) with no serial I/O, so no real python-obd call path is known to
raise.  US-767-c's mutation test must still prove the gate never closes on an
unreadable signal.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest

from src.pi.obdii.obd_connection import ObdConnection

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
PRODUCER = SRC_ROOT / "pi" / "obdii" / "obd_connection.py"

_MISSING = object()


class _FakeObd:
    """A python-obd double whose ``is_connected()`` returns or raises."""

    def __init__(self, result: Any) -> None:
        self._result = result

    def is_connected(self) -> bool:
        if isinstance(self._result, BaseException):
            raise self._result
        return bool(self._result)

    def close(self) -> None:
        pass


def _makeConnection(obdResult: Any = _MISSING) -> ObdConnection:
    conn = ObdConnection({"pi": {"bluetooth": {"macAddress": "00:11:22:33:44:55"}}})
    conn.obd = None if obdResult is _MISSING else _FakeObd(obdResult)
    return conn


# ================================================================================
# `connected` is unchanged
# ================================================================================


@pytest.mark.parametrize(
    ("case", "obdResult", "priorConnected", "expectedConnected"),
    [
        # obd None: getStatus() never touched `connected`, and still does not.
        ("obd None, prior False", _MISSING, False, False),
        ("obd None, prior True", _MISSING, True, True),
        ("is_connected True", True, False, True),
        ("is_connected False", False, True, False),
        ("is_connected raising", RuntimeError("port gone"), True, False),
    ],
)
def test_getStatus_connected_sameValueAsBefore(
    case: str, obdResult: Any, priorConnected: bool, expectedConnected: bool
) -> None:
    """
    Given: each case the pre-US-767-a getStatus() handled
    When: getStatus() is called
    Then: `connected` is exactly what it returned before the new field existed
    """
    conn = _makeConnection(obdResult)
    conn._status.connected = priorConnected

    status = conn.getStatus()

    assert status.connected is expectedConnected, case
    assert conn.isConnected() is (expectedConnected if obdResult is not _MISSING else False)


# ================================================================================
# signalReadable
# ================================================================================


def test_getStatus_isConnectedRaises_unreadableAndFaultRecorded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: is_connected() RAISES (patched -- see module docstring)
    When: getStatus() is called
    Then: connected False, signalReadable False, and the exception is logged
    """
    conn = _makeConnection(RuntimeError("serial read exploded"))

    with caplog.at_level(logging.WARNING, logger="src.pi.obdii.obd_connection"):
        status = conn.getStatus()

    assert status.connected is False
    assert status.signalReadable is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "serial read exploded" in warnings[0].getMessage()


def test_getStatus_genuinelyDisconnected_readable() -> None:
    """
    Given: a fake whose is_connected() cleanly returns False
    When: getStatus() is called
    Then: connected False, signalReadable True -- the link is down, and we know it
    """
    status = _makeConnection(False).getStatus()

    assert status.connected is False
    assert status.signalReadable is True


def test_getStatus_connected_readable() -> None:
    """
    Given: is_connected() returns True
    When: getStatus() is called
    Then: connected True, signalReadable True
    """
    status = _makeConnection(True).getStatus()

    assert status.connected is True
    assert status.signalReadable is True


def test_getStatus_obdNone_readableVerdict() -> None:
    """
    Given: no connection object at all
    When: getStatus() is called
    Then: signalReadable True -- "no connection object" is a READABLE verdict
    """
    status = _makeConnection().getStatus()

    assert status.signalReadable is True


def test_getStatus_readRecovers_readableAgainInSamePass() -> None:
    """
    Given: a read that raised, then a clean read
    When: getStatus() is called after each
    Then: signalReadable follows the latest read, not the first fault
    """
    conn = _makeConnection(RuntimeError("blip"))
    assert conn.getStatus().signalReadable is False

    conn.obd = _FakeObd(False)
    status = conn.getStatus()

    assert status.signalReadable is True
    assert status.connected is False


def test_getStatus_obdDroppedAfterFault_readableAgain() -> None:
    """
    Given: a read that raised, then the connection object is released
    When: getStatus() is called
    Then: signalReadable is True, not the stale False from the earlier fault
    """
    conn = _makeConnection(RuntimeError("blip"))
    assert conn.getStatus().signalReadable is False

    conn.obd = None

    assert conn.getStatus().signalReadable is True


def test_repeatedFault_oneWarningPerStreak(caplog: pytest.LogCaptureFixture) -> None:
    """
    Given: is_connected() keeps raising across polls
    When: getStatus() is called repeatedly
    Then: one WARNING for the streak, not one per poll; a new streak warns again
    """
    conn = _makeConnection(RuntimeError("down"))

    with caplog.at_level(logging.DEBUG, logger="src.pi.obdii.obd_connection"):
        for _ in range(5):
            conn.getStatus()
        conn.obd = _FakeObd(True)
        conn.getStatus()
        conn.obd = _FakeObd(RuntimeError("down again"))
        conn.getStatus()

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert "down again" in warnings[1]


def test_isConnected_raising_keepsBoolReturn() -> None:
    """
    Given: is_connected() raises
    When: the public isConnected() is called
    Then: it still returns False (its contract is unchanged)
    """
    assert _makeConnection(RuntimeError("x")).isConnected() is False


# ================================================================================
# Readers
# ================================================================================


def test_signalReadable_noReaderOutsideProducer() -> None:
    """
    Given: every Python module under src/
    When: searched for the new field
    Then: only obd_connection.py names it. US-767-b/c built the EDR gate on
          (connected, signalReadable); US-793-b moved the gate to ECU
          reachability, so it no longer reads this field either. Every other
          module -- capture-health above all -- must never read it.
    """
    assert PRODUCER.is_file(), f"producer not found at {PRODUCER}"
    pattern = re.compile(r"\bsignalReadable\b")

    readers = sorted(
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        for path in SRC_ROOT.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )

    assert readers == ["src/pi/obdii/obd_connection.py"]


def test_toDict_unchanged() -> None:
    """
    Given: the status serialisation consumers see
    When: toDict() is called
    Then: its key set is exactly the pre-US-767-a one
    """
    keys = set(_makeConnection().getStatus().toDict())

    assert keys == {
        "state",
        "macAddress",
        "connected",
        "lastConnectTime",
        "lastErrorTime",
        "lastError",
        "retryCount",
        "totalConnections",
        "totalErrors",
    }
