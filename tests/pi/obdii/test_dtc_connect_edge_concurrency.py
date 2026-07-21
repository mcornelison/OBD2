################################################################################
# File Name: test_dtc_connect_edge_concurrency.py
# Purpose/Description: US-474 (F-117/A-17) NON-MOCKED connect-edge concurrency
#                      regression. A realtime-logger read and a KOEO DTC read on
#                      ONE ObdConnection must serialize through the single
#                      _ioLock with no interleave and no lost reads -- the exact
#                      GAP-1 the F-117 fix left untested. The serialization
#                      machinery under test (ObdConnection.query, its _ioLock,
#                      DtcClient._serializedQuery) is the REAL code; only the
#                      non-thread-safe serial port is faked (hardware absent
#                      off-Pi). Reverting the _ioLock makes this test go RED.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-20    | Rex (US-474) | Initial -- connect-edge race guard (F-117 GAP-1).
# ================================================================================
################################################################################

"""Connect-edge concurrency regression for the A-17 capture-killing race (US-474).

Background (offices/architect/findings 2026-07-17): python-obd wraps ONE ELM327
serial port that is NOT thread-safe.  The realtime logger reads through
``ObdConnection.query()`` under the single ``_ioLock`` (US-441/F-117), but the
DTC read paths used to hit RAW ``connection.obd.query()``, bypassing the lock.
A key-on (US-404) / session-start DTC read firing on the connection edge then
interleaved with the logger's read -> "device disconnected while reading" ->
0 rows captured -> the drive never armed.  US-474 removed the last raw path (the
``getattr(connection, 'query')`` fallback in :meth:`DtcClient._serializedQuery`).

This test drives a REAL :class:`ObdConnection` and a REAL :class:`DtcClient`
concurrently -- a logger read loop and a KOEO DTC read loop on the SAME
connection object -- against a hand-faked serial port that LATCHES whenever two
threads are inside its ``query()`` at once.  With the ``_ioLock`` serialization
in place the port never sees a concurrent caller (deterministic GREEN); revert
the ``with self._ioLock:`` in :meth:`ObdConnection.query` and the interleave
latches -> the assertion fails RED, proving the test guards the race.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from src.pi.obdii.dtc_client import DtcClient
from src.pi.obdii.obd_connection import ObdConnection

# Iteration count + per-read "serial I/O" duration.  Small enough that the fully
# serialized run stays well under a second (~ITER*3 reads * SLEEP), large enough
# that an UN-serialized run overlaps within the first couple of iterations so the
# revert-the-lock validation step reliably goes RED.
_ITER = 30
_READ_SLEEP_S = 0.001


class _PortResponse:
    """Minimal stand-in for a python-obd OBDResponse (value + is_null())."""

    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _NonThreadSafePort:
    """In-memory stand-in for the ONE python-obd serial port.

    The real port is NOT thread-safe: two threads driving ``query()`` at once
    interleave the ELM327 request/response frames -- the real-world "device
    disconnected while reading".  This fake makes that interleave OBSERVABLE: if
    a second thread enters ``query()`` while a first is still inside it, it
    latches :attr:`interleaved`.  The tiny counter lock guards only the bookkeeping;
    the simulated I/O ``sleep`` happens OUTSIDE it, so a genuinely concurrent
    caller is always seen.  It is NOT a serialization lock -- correct
    serialization must come from :class:`ObdConnection`'s ``_ioLock``.
    """

    def __init__(self, sleep: float = _READ_SLEEP_S) -> None:
        self._sleep = sleep
        self._counterLock = threading.Lock()
        self._inFlight = 0
        self.interleaved = False
        self.reads = 0

    def is_connected(self) -> bool:
        return True

    def query(self, command: Any, *args: Any, **kwargs: Any) -> _PortResponse:
        with self._counterLock:
            self._inFlight += 1
            if self._inFlight > 1:
                self.interleaved = True
        try:
            # The "serial I/O" -- outside the counter lock, so a concurrent
            # caller widens the observed window instead of being serialized here.
            time.sleep(self._sleep)
            name = command if isinstance(command, str) else getattr(command, "name", str(command))
            with self._counterLock:
                self.reads += 1
            # Mode 07 (GET_CURRENT_DTC) returns null on the 2G DSM (unsupported);
            # every other read returns an empty-but-present frame.
            return _PortResponse(value=[], null=(name == "GET_CURRENT_DTC"))
        finally:
            with self._counterLock:
                self._inFlight -= 1


def _makeConnection() -> tuple[ObdConnection, _NonThreadSafePort]:
    """Build a real ObdConnection with a faked non-thread-safe port attached.

    No hardware, no connect() -- we attach the fake port directly so the REAL
    ``query()`` / ``_ioLock`` / ``isConnected()`` code paths run against it.
    """
    conn = ObdConnection(config={"pi": {"bluetooth": {}}})
    port = _NonThreadSafePort()
    conn.obd = port
    return conn, port


def test_loggerRead_and_koeoDtcRead_serializeThroughIoLock_noInterleave() -> None:
    """Given ONE connection, When the realtime logger read loop and a KOEO DTC
    read loop run concurrently, Then every read serializes through the single
    _ioLock: the non-thread-safe port never sees a concurrent caller, nothing
    raises a "disconnected while reading" class error, and no read is lost.
    """
    conn, port = _makeConnection()
    client = DtcClient(commandFactory=lambda name: name)

    errors: list[BaseException] = []
    loggerReads = 0

    def loggerLoop() -> None:
        nonlocal loggerReads
        try:
            for _ in range(_ITER):
                # The exact realtime-logger read path: ObdConnection.query().
                resp = conn.query("RPM")
                assert resp is not None, "logger read returned nothing (lost read)"
                loggerReads += 1
        except BaseException as exc:  # noqa: BLE001 -- capture the race's failure mode
            errors.append(exc)

    def dtcLoop() -> None:
        try:
            for _ in range(_ITER):
                # The KOEO connect-edge read path (US-404): Mode 03 + Mode 07,
                # both routed through DtcClient -> connection.query() now.
                client.readStoredDtcs(conn)
                client.readPendingDtcs(conn)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threadLogger = threading.Thread(target=loggerLoop, name="logger-read")
    threadDtc = threading.Thread(target=dtcLoop, name="koeo-dtc-read")
    threadLogger.start()
    threadDtc.start()
    threadLogger.join()
    threadDtc.join()

    # (1) No "device disconnected while reading" class failure surfaced.
    assert not errors, f"a concurrent read raised (disconnected-while-reading class): {errors!r}"

    # (2) The single non-thread-safe port never saw two threads at once -- the
    # _ioLock serialized the logger read against the DTC read (revert the lock
    # and this latches True -> RED, proving the guard).
    assert port.interleaved is False, (
        "logger read and KOEO DTC read INTERLEAVED on the one non-thread-safe "
        "port -- the ObdConnection._ioLock serialization regressed and the "
        "F-117/A-17 capture-killing race is back"
    )

    # (3) No lost reads: every logger read completed, and every DTC read (Mode 03
    # + Mode 07 per iteration) reached the port.  Total = logger + 2*DTC.
    assert loggerReads == _ITER
    assert port.reads == _ITER + (2 * _ITER)


def test_dtcRead_hasNoRawUnlockedQueryPath() -> None:
    """A connection exposing ONLY .obd.query (no top-level query()) must now
    FAIL loudly rather than silently taking the removed raw unlocked path.

    This pins the US-474 contract change: :meth:`DtcClient._serializedQuery` no
    longer falls back to ``connection.obd.query`` via ``getattr`` -- a connection
    without ``query()`` is a contract violation (AttributeError), not a silent
    lock bypass.
    """

    class _LegacyRawOnlyConnection:
        """Pre-US-474 shape: only .obd.query + isConnected, no query() member."""

        def __init__(self) -> None:
            self.obd = _NonThreadSafePort()

        def isConnected(self) -> bool:
            return True

    client = DtcClient(commandFactory=lambda name: name)

    # The removed getattr fallback would have quietly used .obd.query; now the
    # missing typed query() member surfaces instead of silently bypassing _ioLock.
    try:
        client.readStoredDtcs(_LegacyRawOnlyConnection())  # type: ignore[arg-type]
    except AttributeError:
        pass
    else:  # pragma: no cover - defensive: a silent raw path would reach here
        raise AssertionError(
            "DtcClient took a raw path on a connection lacking query() -- the "
            "US-474 getattr fallback was NOT removed"
        )
