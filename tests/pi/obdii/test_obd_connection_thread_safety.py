################################################################################
# File Name: test_obd_connection_thread_safety.py
# Purpose/Description: US-441 (F-117/A-17) -- the ObdConnection WRAPPER must
#                      serialize EVERY .obd access behind one lock so the
#                      realtime logger's reads can no longer interleave with an
#                      orphaned connect/query daemon on the single non-thread-
#                      safe python-obd serial port (the capture-killing race),
#                      and a superseded (timed-out) daemon must be epoch-fenced
#                      from touching a connection a newer owner holds.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-441) | Initial -- the GAP-1 real-concurrency contract.
#               |              | Atlas A-17 RCA: the V0.27.1 lock guarded only
#               |              | connect(); the realtime logger read
#               |              | self.connection.obd.query() DIRECTLY (logger.py
#               |              | :220/290), racing the left-running timeout
#               |              | daemons -> "device disconnected while reading"
#               |              | -> 0 rows on every connect.  These tests exercise
#               |              | the ACTUAL wrapper (not a mock-at-lifecycle) and
#               |              | must FAIL pre-fix (direct .obd access interleaves)
#               |              | / PASS after (wrapper query() serializes).
# ================================================================================
################################################################################

"""US-441 real-concurrency contract for :class:`ObdConnection` (F-117/A-17).

Atlas's live RCA (`findings/2026-07-03-obd-capture-rca-...`): with eclipse-obd
stopped, a raw single-threaded ``python-obd`` session reads RPM flawlessly, but
eclipse-obd itself captures **zero** rows -- its connect/query timeout daemons
are left running (TD-036/US-244) and the US-301 heartbeat adds a second connect
path, so an orphaned thread drives ``self._connection.obd`` at the same instant
the realtime logger reads it.  ``python-obd``'s connection wraps one serial port
and is NOT thread-safe, so the ELM327 frames interleave and the logger's read
returns empty.

The fix (US-441): ONE lock on the WRAPPER guards every ``.obd`` access, and every
caller (the logger's direct reads included) goes through it.  A monotonically
increasing generation fences a superseded daemon from a connection a newer owner
now holds.

These tests are the GAP-1 verification criterion -- they hit the real
``ObdConnection.query()`` path, NOT a lifecycle mock:

* ``TestSerializedObdAccess`` -- proves the RACE exists on raw ``.obd.query()``
  (the pre-fix path) AND that the wrapper's ``query()`` serializes it away.
* ``TestEpochFence`` -- proves a superseded connect/query daemon is dropped and
  cannot touch a connection a newer generation owns, while a live reader (no
  generation) is never fenced.
* ``TestCrossLayerLoggerRace`` -- spins the actual ``ObdDataLogger`` read path
  concurrently with an orphaned daemon against the SAME wrapper and asserts no
  serial-I/O interleaving.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from src.pi.obdii.data.logger import ObdDataLogger
from src.pi.obdii.obd_connection import (
    ObdConnection,
    ObdConnectionSupersededError,
)

# ================================================================================
# Fakes
# ================================================================================


class _InterleaveDetectingObd:
    """A ``python-obd`` double that flags any concurrent entry into ``query()``.

    Mirrors the real failure surface: two threads inside ``query()`` at the same
    wall-clock instant = interleaved ELM327 frames = the capture bug.  The brief
    sleep is the contention window; the counter is guarded by its own tiny lock
    so the *detection* is race-free even though the *thing detected* is a race.
    """

    def __init__(self, querySleepSec: float = 0.01) -> None:
        self._querySleepSec = querySleepSec
        self._lock = threading.Lock()
        self.active = 0
        self.maxConcurrent = 0
        self.queryCalls = 0
        self.interleaved = False
        # python-obd exposes this; the supported-PID probe reads it (no query).
        self.supported_commands: list[Any] = []

    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        pass

    def query(self, cmd: Any) -> Any:
        with self._lock:
            self.active += 1
            self.queryCalls += 1
            if self.active > self.maxConcurrent:
                self.maxConcurrent = self.active
            if self.active > 1:
                self.interleaved = True
        time.sleep(self._querySleepSec)
        with self._lock:
            self.active -= 1
        return SimpleNamespace(value=800.0, unit="rpm", is_null=lambda: False)


def _buildConnection(theObd: _InterleaveDetectingObd) -> ObdConnection:
    """An ObdConnection whose factory always returns ``theObd``.

    ``macAddress`` is a literal path so ``_resolvePort`` skips the real
    ``rfcomm bind`` subprocess; the injected factory bypasses the real
    ``obd.OBD(...)`` ctor so no serial hardware is touched.
    """
    return ObdConnection(
        config={
            'pi': {
                'bluetooth': {
                    'macAddress': '/dev/rfcomm-test',
                    'retryDelays': [0],
                    'maxRetries': 0,
                    'connectionTimeoutSeconds': 1,
                },
            },
        },
        obdFactory=lambda serialPort, timeout: theObd,
    )


# ================================================================================
# 1. Serialized .obd access (the core race)
# ================================================================================


class TestSerializedObdAccess:
    """The wrapper serializes every OBD read; raw ``.obd.query`` does not."""

    def test_rawObdQuery_interleaves_provingTheRaceIsReal(self) -> None:
        """RED discriminator: two threads on ``conn.obd.query()`` DO interleave.

        This is the pre-US-441 logger path (``self.connection.obd.query(cmd)``).
        The assertion proves the detector actually catches a race -- so the
        serialized-path assertion below is meaningful (a test that cannot go
        RED proves nothing).
        """
        theObd = _InterleaveDetectingObd(querySleepSec=0.05)
        conn = _buildConnection(theObd)
        assert conn.connect() is True

        threadCount = 6
        barrier = threading.Barrier(threadCount)

        def worker() -> None:
            barrier.wait()
            conn.obd.query("RPM")  # RAW access -- bypasses the wrapper lock

        threads = [threading.Thread(target=worker) for _ in range(threadCount)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive()

        assert theObd.interleaved is True, (
            "Raw .obd.query() must interleave (maxConcurrent="
            f"{theObd.maxConcurrent}); if this fails the detector is broken and "
            "the serialized-path test below is meaningless"
        )
        assert theObd.maxConcurrent > 1

    def test_wrapperQuery_serializes_noInterleaving(self) -> None:
        """GREEN: the same threads through ``conn.query()`` never overlap.

        Post-US-441 the logger calls the wrapper's ``query()`` which holds the
        single ``_ioLock`` for the whole read -- so ``maxConcurrent`` stays 1.
        """
        theObd = _InterleaveDetectingObd(querySleepSec=0.05)
        conn = _buildConnection(theObd)
        assert conn.connect() is True

        threadCount = 6
        barrier = threading.Barrier(threadCount)

        def worker() -> None:
            barrier.wait()
            conn.query("RPM")  # serialized wrapper path

        threads = [threading.Thread(target=worker) for _ in range(threadCount)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
            assert not t.is_alive()

        assert theObd.interleaved is False, (
            f"Wrapper query() must serialize: maxConcurrent={theObd.maxConcurrent} "
            "(US-441 regression -- the _ioLock is not guarding every .obd access)"
        )
        assert theObd.maxConcurrent == 1
        assert theObd.queryCalls == threadCount

    def test_connectAndQuery_doNotInterleave(self) -> None:
        """A connect (which drives the port) and a query never overlap.

        The connect factory sleeps so the window is wide; a query fired at the
        same instant must wait for the connect to release ``_ioLock``.
        """
        theObd = _InterleaveDetectingObd(querySleepSec=0.02)

        insideConnect = threading.Event()
        releaseConnect = threading.Event()

        def slowFactory(serialPort: str | None, timeout: float) -> Any:
            insideConnect.set()
            assert releaseConnect.wait(timeout=5.0), "connect never released"
            return theObd

        conn = ObdConnection(
            config={'pi': {'bluetooth': {
                'macAddress': '/dev/rfcomm-test',
                'retryDelays': [0], 'maxRetries': 0,
                'connectionTimeoutSeconds': 1,
            }}},
            obdFactory=slowFactory,
        )

        connectThread = threading.Thread(target=conn.connect, daemon=True)
        connectThread.start()
        assert insideConnect.wait(timeout=5.0), "factory never ran"

        # A query fired now must BLOCK on _ioLock (connect holds it).
        queryReturned = threading.Event()

        def doQuery() -> None:
            conn.query("RPM")
            queryReturned.set()

        queryThread = threading.Thread(target=doQuery, daemon=True)
        queryThread.start()

        # While connect holds the lock the query cannot have completed.
        assert queryReturned.wait(timeout=0.3) is False, (
            "query() ran while connect() held _ioLock -- not serialized"
        )

        releaseConnect.set()
        connectThread.join(timeout=5.0)
        queryThread.join(timeout=5.0)
        assert queryReturned.is_set()
        assert theObd.interleaved is False


# ================================================================================
# 2. Epoch fence -- superseded daemons are dropped
# ================================================================================


class TestEpochFence:
    """A timed-out daemon may not touch a connection a newer generation owns."""

    def test_supersededQuery_raisesAndDoesNotTouchObd(self) -> None:
        theObd = _InterleaveDetectingObd()
        conn = _buildConnection(theObd)
        assert conn.connect() is True  # generation -> 1

        staleGen = conn.activeGeneration()
        assert staleGen == 1

        # Reconnect: disconnect (gen 2) + connect (gen 3) -> staleGen is stale.
        conn.disconnect()
        assert conn.connect() is True
        assert conn.activeGeneration() == 3

        callsBefore = theObd.queryCalls
        with pytest.raises(ObdConnectionSupersededError):
            conn.query("RPM", callerGeneration=staleGen)

        assert theObd.queryCalls == callsBefore, (
            "A fenced (superseded) query must NOT reach the serial port"
        )

    def test_currentGenerationQuery_passes(self) -> None:
        theObd = _InterleaveDetectingObd()
        conn = _buildConnection(theObd)
        assert conn.connect() is True

        gen = conn.activeGeneration()
        resp = conn.query("RPM", callerGeneration=gen)  # matches -> allowed
        assert resp is not None
        assert theObd.queryCalls == 1

    def test_liveReader_noGeneration_isNeverFenced(self) -> None:
        """The logger passes no generation -> always reads the CURRENT port."""
        theObd = _InterleaveDetectingObd()
        conn = _buildConnection(theObd)
        assert conn.connect() is True
        conn.disconnect()
        assert conn.connect() is True  # generation has advanced twice

        resp = conn.query("RPM")  # no callerGeneration -> current, not fenced
        assert resp is not None
        assert theObd.queryCalls == 1

    def test_supersededConnect_doesNotReopenPort(self) -> None:
        """A superseded connect daemon must not re-open over a newer connection."""
        calls = {'n': 0}

        theObd = _InterleaveDetectingObd()

        def countingFactory(serialPort: str | None, timeout: float) -> Any:
            calls['n'] += 1
            return theObd

        conn = ObdConnection(
            config={'pi': {'bluetooth': {
                'macAddress': '/dev/rfcomm-test',
                'retryDelays': [0], 'maxRetries': 0,
                'connectionTimeoutSeconds': 1,
            }}},
            obdFactory=countingFactory,
        )
        assert conn.connect() is True  # generation -> 1, factory called once
        assert calls['n'] == 1

        # A daemon that captured generation 0 (before the connect won) wakes:
        # its re-open is fenced -- factory NOT called again.
        result = conn.connect(callerGeneration=0)
        assert result is True  # reports current connectedness
        assert calls['n'] == 1, "Superseded connect must not re-open the port"


# ================================================================================
# 3. Cross-layer: the actual logger read path vs an orphaned daemon
# ================================================================================


class TestCrossLayerLoggerRace:
    """The real ObdDataLogger read path must not interleave with an orphan."""

    def test_loggerReads_concurrentWithOrphanDaemon_noInterleaving(self) -> None:
        """Spin ``ObdDataLogger.queryParameter`` against a left-running daemon.

        This is the exact cross-layer race the A-17 RCA describes: the logger
        reads through the wrapper while an orphaned query daemon also drives the
        wrapper.  Both now route through ``_ioLock`` -> no interleaving.
        """
        theObd = _InterleaveDetectingObd(querySleepSec=0.02)
        conn = _buildConnection(theObd)
        assert conn.connect() is True

        # A MagicMock-free minimal DB stand-in (logReading is never called here).
        db = SimpleNamespace()
        dataLogger = ObdDataLogger(conn, db)

        stop = threading.Event()

        def loggerLoop() -> None:
            while not stop.is_set():
                try:
                    dataLogger.queryParameter("RPM")
                except Exception:  # noqa: BLE001 -- only the interleave flag matters
                    pass

        def orphanDaemon() -> None:
            while not stop.is_set():
                try:
                    conn.query("RPM")  # a left-running query daemon path
                except Exception:  # noqa: BLE001
                    pass

        threads = [
            threading.Thread(target=loggerLoop),
            threading.Thread(target=loggerLoop),
            threading.Thread(target=orphanDaemon),
        ]
        for t in threads:
            t.start()
        time.sleep(0.4)  # let the loops contend
        stop.set()
        for t in threads:
            t.join(timeout=5.0)
            assert not t.is_alive()

        assert theObd.queryCalls > 0, "the loops never actually queried"
        assert theObd.interleaved is False, (
            f"logger read interleaved with the orphan daemon "
            f"(maxConcurrent={theObd.maxConcurrent}) -- the F-117/A-17 race is "
            "not closed"
        )
        assert theObd.maxConcurrent == 1
