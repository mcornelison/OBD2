################################################################################
# File Name: test_bt_link_drop_transport_reset.py
# Purpose/Description: US-512 AC3 -- mid-session BT link drop -> transport reset
#                      -> capture resumes, driven with real threads through the
#                      real ObdConnection / BtResilienceMixin / ReconnectLoop.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Rex (US-512) | Initial -- BT capture hardening (BL-025 P1).
# ================================================================================
################################################################################

"""Mid-session link drop, recovered in-process, with nothing stubbed out.

``tests/pi/integration/test_bt_flap_in_process.py`` (US-221) already proves the
capture loop survives a flap -- but it drives a hand-written
``_FlappingConnection`` whose ``reconnect()`` simply flips a boolean.  That fake
cannot express the defect US-512 fixes, because the defect lives BELOW the
connection object: in the kernel rfcomm binding that outlives the link, and in
``bindRfcomm``'s idempotent short-circuit that therefore keeps handing the same
dead tty back.

So everything real here is real:

* the real :class:`~src.pi.obdii.obd_connection.ObdConnection`,
* the real :mod:`~src.pi.obdii.bluetooth_helper` (bind / release / reset /
  ``rfcomm show`` parsing / the reachability probe's BOTH layers),
* the real :class:`~src.pi.obdii.orchestrator.bt_resilience.BtResilienceMixin`,
* the real :class:`~src.pi.obdii.reconnect_loop.ReconnectLoop`,
* the real ``connection_log`` in a real SQLite file,
* a real capture THREAD polling concurrently with the drop.

Only two things are faked, both at the operating-system boundary: the
``rfcomm``/``bluetoothctl`` CLIs (the dev box is Windows) and the python-obd
handle.  Both come from :mod:`tests.pi.obdii.bt_stack_fake`, whose whole model
is the single fact the bug turns on -- a bind entry survives its link.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator
from typing import Any

import pytest

from src.pi.data.connection_logger import (
    EVENT_BT_DISCONNECT,
    EVENT_RECONNECT_SUCCESS,
    logConnectionEvent,
)
from src.pi.obdii import bluetooth_helper
from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.obd_connection import ObdConnection
from src.pi.obdii.orchestrator.bt_resilience import BtResilienceMixin
from src.pi.obdii.reconnect_loop import ReconnectLoop
from tests.pi.obdii.bt_stack_fake import DEFAULT_MAC, FakeBtStack

# Bounded so a regression fails the suite in seconds rather than hanging it.
RECOVERY_DEADLINE_S = 10.0


# ================================================================================
# Fixtures + harness
# ================================================================================

@pytest.fixture
def freshDb(tmp_path) -> Generator[ObdDatabase, None, None]:
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    yield db


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> FakeBtStack:
    fake = FakeBtStack()
    monkeypatch.setattr("src.pi.obdii.bluetooth_helper._defaultRunner", fake.runner)
    return fake


class _CaptureOrchestrator(BtResilienceMixin):
    """Minimal composing shell -- the mixin under test is the real one."""

    def __init__(self, database: ObdDatabase, connection: Any, stack: FakeBtStack) -> None:
        self._database = database
        self._connection = connection
        self._stack = stack
        # Production wires the orchestrator's SIGTERM event into the loop
        # (US-232); the harness reuses that same seam as its bound, so a
        # regression fails in seconds instead of spinning the suite forever.
        self._shutdownEvent = threading.Event()
        self._reconnectLoopFactory = self._buildLoop
        self.fatalSignals: list[BaseException] = []

    def _buildLoop(self) -> ReconnectLoop:
        """A REAL ReconnectLoop whose probe is the REAL reachability check.

        ``isRfcommReachable`` is used unmodified -- both layers, the device-node
        stat AND the ``rfcomm show`` round-trip -- with only its two injection
        seams pointed at the fake OS.  That matters: the probe answering
        honestly about the binding is exactly what the reset has to restore.
        """
        def probe() -> bool:
            return bluetooth_helper.isRfcommReachable(
                device=0,
                subprocessRunner=self._stack.runner,
                pathExists=self._stack.pathExists,
            )

        def eventLogger(eventType: str, retryCount: int) -> None:
            logConnectionEvent(
                database=self._database,
                eventType=eventType,
                macAddress=DEFAULT_MAC,
                success=(eventType == EVENT_RECONNECT_SUCCESS),
                retryCount=retryCount,
            )

        return ReconnectLoop(
            probe=probe,
            eventLogger=eventLogger,
            # Collapse the real 1/5/10/30/60s schedule to a 5ms tick so the
            # drill runs in milliseconds -- the loop LOGIC (probe, event rows,
            # exit checks) is untouched.  Waiting on the event rather than
            # sleeping keeps the abort instantaneous.
            sleepFn=lambda _seconds: self._shutdownEvent.wait(0.005),
            shutdownEvent=self._shutdownEvent,
        )


class _CaptureThread:
    """A real polling thread that routes capture errors through the mixin.

    Mirrors ``RealtimeDataLogger._pollCycle``'s contract: query, and on an
    exception hand it to the orchestrator's capture-error handler on the SAME
    thread -- which is where the reconnect actually happens in production.
    """

    def __init__(self, connection: ObdConnection, orchestrator: _CaptureOrchestrator) -> None:
        self._connection = connection
        self._orchestrator = orchestrator
        self._stop = threading.Event()
        self.successes = 0
        self.failures = 0
        self.threadIdent: int | None = None
        self.unhandled: list[BaseException] = []
        self._thread = threading.Thread(target=self._run, daemon=True, name="capture")

    def _run(self) -> None:
        self.threadIdent = threading.get_ident()
        while not self._stop.is_set():
            try:
                self._connection.query("RPM")
                self.successes += 1
            except Exception as exc:  # noqa: BLE001 -- this IS the capture boundary
                self.failures += 1
                try:
                    self._orchestrator.handleCaptureError(exc)
                except BaseException as fatal:  # noqa: BLE001
                    self.unhandled.append(fatal)
                    return
            self._stop.wait(0.01)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Also abort any reconnect loop the thread is parked in -- otherwise a
        # regression leaves a daemon thread spinning for the rest of the suite.
        self._orchestrator._shutdownEvent.set()
        self._thread.join(timeout=5.0)

    def isAlive(self) -> bool:
        return self._thread.is_alive()

    def waitForSuccesses(self, target: int, timeout: float = RECOVERY_DEADLINE_S) -> bool:
        deadline = threading.Event()
        step = 0.02
        waited = 0.0
        while waited < timeout:
            if self.successes >= target:
                return True
            deadline.wait(step)
            waited += step
        return False


def _config() -> dict[str, Any]:
    return {
        "pi": {
            "bluetooth": {
                "macAddress": DEFAULT_MAC,
                "retryDelays": [0],
                "maxRetries": 1,
                "connectionTimeoutSeconds": 5,
            }
        }
    }


def _readEventTypes(db: ObdDatabase) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT event_type FROM connection_log ORDER BY id"
        ).fetchall()
    return [row[0] for row in rows]


# ================================================================================
# The drill
# ================================================================================

@pytest.mark.integration
class TestMidSessionLinkDropRecovers:

    def test_linkDropsMidCapture_transportIsResetAndCaptureResumes(
        self, freshDb, stack
    ) -> None:
        """
        Given: capture running on a live BT link
        When:  the link drops mid-session (the bind entry survives it)
        Then:  the transport is reset (release -> re-bind) and capture resumes
               in the same process, on the same thread

        THE MUTATION THAT PROVES IT: make the recovery tear down without
        re-binding and the reopen lands on the surviving dead entry forever --
        successes never advance past the drop and this times out.
        """
        pidBefore = os.getpid()
        conn = ObdConnection(_config(), database=freshDb, obdFactory=stack.obdFactory)
        assert conn.connect() is True

        orch = _CaptureOrchestrator(freshDb, conn, stack)
        capture = _CaptureThread(conn, orch)
        capture.start()
        try:
            assert capture.waitForSuccesses(3), "capture never got going"
            threadBefore = capture.threadIdent

            stack.dropLink()
            countAtDrop = capture.successes

            resumed = capture.waitForSuccesses(countAtDrop + 5)

            assert resumed, (
                "capture did not resume after the link drop -- the reopen is "
                "still landing on the stale binding"
            )
            assert capture.failures >= 1, "the drop was never actually observed"
            assert stack.isFresh() is True, "recovery reused the dead binding"
            assert capture.threadIdent == threadBefore
            assert capture.isAlive() is True
            assert capture.unhandled == []
            assert os.getpid() == pidBefore
        finally:
            capture.stop()

    def test_linkDrop_releasesThenRebinds_notTheIdempotentShortCircuit(
        self, freshDb, stack
    ) -> None:
        """The command trace must show the reset, not a bare re-open."""
        conn = ObdConnection(_config(), database=freshDb, obdFactory=stack.obdFactory)
        conn.connect()
        orch = _CaptureOrchestrator(freshDb, conn, stack)
        capture = _CaptureThread(conn, orch)
        capture.start()
        try:
            capture.waitForSuccesses(2)
            releasesBefore = stack.releaseCount()
            bindsBefore = stack.bindCount()

            stack.dropLink()
            countAtDrop = capture.successes
            assert capture.waitForSuccesses(countAtDrop + 3)

            assert stack.releaseCount() > releasesBefore
            assert stack.bindCount() > bindsBefore
        finally:
            capture.stop()

    def test_linkDrop_writesTheFlapTimeline(self, freshDb, stack) -> None:
        """The recovery must remain legible after the fact in connection_log."""
        conn = ObdConnection(_config(), database=freshDb, obdFactory=stack.obdFactory)
        conn.connect()
        orch = _CaptureOrchestrator(freshDb, conn, stack)
        capture = _CaptureThread(conn, orch)
        capture.start()
        try:
            capture.waitForSuccesses(2)
            stack.dropLink()
            countAtDrop = capture.successes
            assert capture.waitForSuccesses(countAtDrop + 3)
        finally:
            capture.stop()

        events = _readEventTypes(freshDb)
        assert EVENT_BT_DISCONNECT in events
        assert EVENT_RECONNECT_SUCCESS in events
        assert events.index(EVENT_BT_DISCONNECT) < events.index(EVENT_RECONNECT_SUCCESS)

    def test_linkDrop_recoveryNeverTouchesTheRadio(self, freshDb, stack) -> None:
        """AC4 across the WHOLE recovery, not just the helper in isolation.

        The 07-03 capture killer was a persisted rfkill soft-block; any recovery
        that cycles the radio risks systemd-rfkill saving that state at
        shutdown and re-blocking BT on the next boot.  eclipse-rfkill-unblock
        .service is the standing net -- this keeps us from needing it.
        """
        conn = ObdConnection(_config(), database=freshDb, obdFactory=stack.obdFactory)
        conn.connect()
        orch = _CaptureOrchestrator(freshDb, conn, stack)
        capture = _CaptureThread(conn, orch)
        capture.start()
        try:
            capture.waitForSuccesses(2)
            stack.dropLink()
            countAtDrop = capture.successes
            capture.waitForSuccesses(countAtDrop + 3)
        finally:
            capture.stop()

        for line in stack.commandLines():
            assert not line.startswith("rfkill"), line
            assert not line.startswith("hciconfig"), line
            assert not line.startswith("nmcli"), line
            assert "power off" not in line, line

    def test_repeatedDrops_eachOneRecovers(self, freshDb, stack) -> None:
        """A flapping link (the real in-car case) must not degrade into a
        stuck state after the first recovery."""
        conn = ObdConnection(_config(), database=freshDb, obdFactory=stack.obdFactory)
        conn.connect()
        orch = _CaptureOrchestrator(freshDb, conn, stack)
        capture = _CaptureThread(conn, orch)
        capture.start()
        try:
            for _drop in range(3):
                assert capture.waitForSuccesses(capture.successes + 2)
                stack.dropLink()
                countAtDrop = capture.successes
                assert capture.waitForSuccesses(countAtDrop + 3), (
                    f"capture stuck after drop {_drop + 1}"
                )
        finally:
            capture.stop()
