################################################################################
# File Name: test_obd_connect_failure_cleanup.py
# Purpose/Description: A+B fix contract for the ObdConnection connect path
#                      (Atlas RCA 2026-07-27, A-17 / capture-dead-since-0703).
#                      The US-441 regression held _ioLock across the ENTIRE
#                      multi-attempt retry loop + backoff sleeps, and the
#                      failure path never closed the partially-opened obd. On a
#                      failing link a timed-out-but-still-running connect daemon
#                      monopolized the lock (disconnect() could never run to
#                      free the port), and each retry re-opened /dev/rfcommN over
#                      an unclosed stale handle -> "device reports readiness to
#                      read but returned no data (device disconnected or multiple
#                      access on port?)" -> 0 rows captured for 24 days.
# Author: Atlas (Architect)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""A+B connect-path fix contract for :class:`ObdConnection`.

A. connect() must NOT hold ``_ioLock`` across its backoff sleep -- disconnect()
   / query() must be able to interleave and free the serial port while a
   (possibly orphaned) connect grinds through retries.
B. every failed attempt must close its partial obd before the next open, so no
   stale half-open ``/dev/rfcommN`` handle survives to collide with the next
   ``obd.OBD(portstr=...)`` construction ("multiple access on port").

Uses the DI ``obdFactory`` (no serial hardware). Both tests MUST fail on the
pre-fix code and pass after.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from src.pi.obdii.obd_connection import ObdConnection


class _DeadObd:
    """A python-obd double that "opens the port" but never connects.

    Drives the retry+fail path (``is_connected()`` is always False) and records
    ``close()`` so the test can assert the failure path cleaned up.
    """

    def __init__(self) -> None:
        self.closed = False
        # python-obd exposes this; the supported-PID probe reads it (no query).
        self.supported_commands: list[Any] = []

    def is_connected(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True

    def query(self, cmd: Any) -> Any:  # pragma: no cover - never reached
        return None


def _conn(factory: Any, *, retryDelays: list[int | float], maxRetries: int) -> ObdConnection:
    """An ObdConnection whose factory returns the injected obd double.

    ``macAddress`` is a literal path so ``_resolvePort`` skips the real
    ``rfcomm bind`` subprocess.
    """
    return ObdConnection(
        config={'pi': {'bluetooth': {
            'macAddress': '/dev/rfcomm-test',
            'retryDelays': retryDelays,
            'maxRetries': maxRetries,
            'connectionTimeoutSeconds': 1,
        }}},
        obdFactory=factory,
    )


class TestFailedConnectClosesPartialPort:
    """(B) every failed attempt closes its partial obd before the next open."""

    def test_failedConnect_closesEveryPartialObd(self) -> None:
        created: list[_DeadObd] = []

        def factory(serialPort: str | None, timeout: float) -> Any:
            obd = _DeadObd()
            created.append(obd)
            return obd

        conn = _conn(factory, retryDelays=[0], maxRetries=2)

        assert conn.connect() is False
        assert len(created) == 3, f"expected 3 attempts (maxRetries+1), got {len(created)}"
        assert all(o.closed for o in created), (
            "a failed connect attempt left its obd open -> the stale "
            "/dev/rfcommN handle collides with the next open ('multiple access "
            f"on port'): closed flags = {[o.closed for o in created]}"
        )


class TestConnectReleasesLockDuringBackoff:
    """(A) connect() must not hold _ioLock across its backoff sleep."""

    def test_disconnect_completesDuringConnectBackoff(self) -> None:
        attemptStarted = threading.Event()

        def factory(serialPort: str | None, timeout: float) -> Any:
            attemptStarted.set()
            return _DeadObd()  # never connects -> fail -> enter backoff

        conn = _conn(factory, retryDelays=[2.0], maxRetries=1)

        connectThread = threading.Thread(target=conn.connect, daemon=True)
        connectThread.start()
        assert attemptStarted.wait(timeout=5.0), "connect never ran attempt 0"

        # Attempt 0 has failed; connect() is now in its 2.0s backoff before
        # attempt 1. disconnect() must be able to acquire _ioLock NOW.
        disconnectDone = threading.Event()

        def doDisconnect() -> None:
            conn.disconnect()
            disconnectDone.set()

        start = time.monotonic()
        threading.Thread(target=doDisconnect, daemon=True).start()
        acquired = disconnectDone.wait(timeout=1.0)
        elapsed = time.monotonic() - start

        assert acquired, (
            f"disconnect() blocked >1s ({elapsed:.2f}s) waiting for _ioLock -- "
            "connect() is holding the lock across its backoff (US-441 "
            "regression: the connect lock monopolizes the port lifecycle so the "
            "port can never be freed while a connect grinds through retries)"
        )
        connectThread.join(timeout=5.0)
