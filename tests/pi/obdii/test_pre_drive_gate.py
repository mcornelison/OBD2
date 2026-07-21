################################################################################
# File Name: test_pre_drive_gate.py
# Purpose/Description: US-479 (F-117) pre-drive OBD connect + capture green-light.
#                      Bench-validates (a) the pure PASS/FAIL gate logic -- most
#                      importantly that a happy-path-only run (rows landed but the
#                      connect-edge was never exercised) can NOT green-light -- and
#                      (b) the connect-edge capture: a realtime-logger read loop
#                      and a KOEO DTC read on ONE connection serialize and both
#                      succeed. The serialization machinery under test
#                      (ObdConnection.query / _ioLock, DtcClient) is REAL code;
#                      only the non-thread-safe serial port is faked (hardware
#                      absent off-Pi). A bench PASS is NOT a substitute for the
#                      live in-car gate (same discipline as verify_live_idle.sh).
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-20    | Rex (US-479) | Initial -- pre-drive green-light gate + probe.
# ================================================================================
################################################################################

"""Bench validation for the US-479 pre-drive green-light gate.

The gate's whole reason to exist: a weekend of drives captured ZERO rows because
a KOEO DTC read raced the realtime logger on the one connection (the A-17 race)
and a happy-path smoke test never noticed.  So the gate must (1) EXERCISE the
connect-edge -- a DTC read co-occurring with the logger on ONE connection -- and
(2) REFUSE to green-light if that edge was never crossed, even when rows landed.
These tests pin both.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from src.pi.obdii.obd_connection import ObdConnection
from src.pi.obdii.pre_drive_gate import (
    CORE_PIDS,
    CaptureResult,
    evaluateGate,
    runConnectEdgeCapture,
)

# ================================================================================
# Pure gate-decision logic -- evaluateGate
# ================================================================================


def _cleanResult(**overrides: Any) -> CaptureResult:
    """A fully-green capture result; override one field per test."""
    base = dict(
        rowsWritten=60,
        distinctParams=10,
        coveredParams=frozenset(list(CORE_PIDS)[:10]),
        durationSec=30.0,
        dtcReadCount=4,
        dtcReadOk=True,
        connectEdgeExercised=True,
        interleaveObserved=False,
        captureError=None,
    )
    base.update(overrides)
    return CaptureResult(**base)


def test_evaluateGate_allGreen_passes() -> None:
    """Given rows landed, coverage met, and the connect-edge exercised cleanly,
    the gate PASSES."""
    verdict = evaluateGate(_cleanResult(), minRows=9, minDistinctParams=8)
    assert verdict.passed is True
    assert "PASS" in verdict.reason.upper() or verdict.passed


def test_evaluateGate_connectEdgeNotExercised_failsEvenWhenRowsLanded() -> None:
    """THE load-bearing case: rows landed and coverage is fine, but the KOEO/idle
    DTC read never co-occurred with the logger -> a happy-path-only pass, which
    the gate MUST refuse (this blind spot let a weekend of drives capture zero)."""
    verdict = evaluateGate(
        _cleanResult(connectEdgeExercised=False),
        minRows=9,
        minDistinctParams=8,
    )
    assert verdict.passed is False
    assert "connect-edge" in verdict.reason.lower()


def test_evaluateGate_interleaveObserved_fails() -> None:
    """If the two reads interleaved on the one non-thread-safe port, the A-17 race
    has regressed -- never green-light."""
    verdict = evaluateGate(
        _cleanResult(interleaveObserved=True),
        minRows=9,
        minDistinctParams=8,
    )
    assert verdict.passed is False
    assert "interleave" in verdict.reason.lower()


def test_evaluateGate_dtcReadFailed_fails() -> None:
    """A DTC read that raised a disconnected-while-reading class error is exactly
    the capture-killer; the gate fails."""
    verdict = evaluateGate(
        _cleanResult(dtcReadOk=False),
        minRows=9,
        minDistinctParams=8,
    )
    assert verdict.passed is False
    assert "dtc" in verdict.reason.lower()


def test_evaluateGate_tooFewRows_fails() -> None:
    """Rows below the duration-scaled floor -> capture is not really landing."""
    verdict = evaluateGate(
        _cleanResult(rowsWritten=3),
        minRows=9,
        minDistinctParams=8,
    )
    assert verdict.passed is False
    assert "row" in verdict.reason.lower()


def test_evaluateGate_tooFewParams_fails() -> None:
    """Coverage below the core-PID floor -> the ECU answered too few PIDs."""
    verdict = evaluateGate(
        _cleanResult(distinctParams=3),
        minRows=9,
        minDistinctParams=8,
    )
    assert verdict.passed is False
    assert "coverage" in verdict.reason.lower() or "param" in verdict.reason.lower()


def test_evaluateGate_captureError_fails() -> None:
    """A raised capture-boundary error dominates every other signal."""
    verdict = evaluateGate(
        _cleanResult(captureError="device disconnected while reading"),
        minRows=9,
        minDistinctParams=8,
    )
    assert verdict.passed is False
    assert "disconnected" in verdict.reason.lower() or "error" in verdict.reason.lower()


# ================================================================================
# Connect-edge capture -- runConnectEdgeCapture (real serialization, faked port)
# ================================================================================


class _PortResponse:
    """Minimal python-obd OBDResponse stand-in (value + is_null())."""

    def __init__(self, value: Any, null: bool = False) -> None:
        self.value = value
        self._null = null

    def is_null(self) -> bool:
        return self._null


class _NonThreadSafePort:
    """The ONE python-obd serial port, faked to make an interleave OBSERVABLE.

    Returns a numeric value for Mode-01 PID reads (so the realtime logger writes
    rows), an empty-but-present frame for Mode 03, and null for Mode 07 (the 2G
    DSM's unsupported pending path).  If a second thread enters ``query()`` while
    a first is still inside, it latches :attr:`interleaved` -- correct
    serialization must come from ObdConnection._ioLock, not from this fake.
    """

    def __init__(self, sleep: float = 0.001) -> None:
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
            time.sleep(self._sleep)  # "serial I/O" OUTSIDE the counter lock
            name = command if isinstance(command, str) else getattr(command, "name", str(command))
            with self._counterLock:
                self.reads += 1
            if name == "GET_CURRENT_DTC":
                return _PortResponse(value=[], null=True)
            if name == "GET_DTC":
                return _PortResponse(value=[])
            # Any Mode-01 PID read -> a plausible numeric value so rows land.
            return _PortResponse(value=1234.0)
        finally:
            with self._counterLock:
                self._inFlight -= 1


def _benchConfig(pids: list[str]) -> dict[str, Any]:
    return {
        "pi": {
            "bluetooth": {},
            "realtimeData": {
                "pollingIntervalMs": 100,
                "parameters": [{"name": p, "logData": True} for p in pids],
            },
        }
    }


def _realConnectionWithFakePort() -> tuple[ObdConnection, _NonThreadSafePort]:
    conn = ObdConnection(config={"pi": {"bluetooth": {}}})
    port = _NonThreadSafePort()
    conn.obd = port
    return conn, port


def test_runConnectEdgeCapture_serializes_landsRows_and_exercisesEdge(
    tmp_path: Path,
) -> None:
    """Given ONE real connection driven by a realtime-logger loop AND a KOEO DTC
    read loop, When the capture runs, Then rows land, core-PID coverage is
    recorded, the connect-edge is marked exercised, and the non-thread-safe port
    NEVER saw two callers at once (the _ioLock serialized them)."""
    from src.pi.obdii.database import ObdDatabase

    pids = list(CORE_PIDS)[:9]
    conn, port = _realConnectionWithFakePort()
    db = ObdDatabase(str(tmp_path / "gate.db"))
    db.initialize()

    result = runConnectEdgeCapture(
        connection=conn,
        database=db,
        config=_benchConfig(pids),
        durationSec=0.6,
    )

    assert isinstance(result, CaptureResult)
    assert result.rowsWritten > 0, "no realtime_data rows landed"
    assert result.distinctParams >= 1
    assert result.connectEdgeExercised is True, "the KOEO DTC read never co-occurred"
    assert result.dtcReadCount >= 1
    assert result.dtcReadOk is True
    assert result.captureError is None
    # The real _ioLock must have serialized the two loops on the one port.
    assert result.interleaveObserved is False
    assert port.interleaved is False


def test_runConnectEdgeCapture_koeoOnly_oneReadNoLoggerWindow(tmp_path: Path) -> None:
    """The KOEO (engine-off) sub-check: a single DTC read succeeds on the link
    without requiring the full live-idle logger window -- the earliest driveway
    signal."""
    from src.pi.obdii.database import ObdDatabase

    conn, _port = _realConnectionWithFakePort()
    db = ObdDatabase(str(tmp_path / "gate_koeo.db"))
    db.initialize()

    result = runConnectEdgeCapture(
        connection=conn,
        database=db,
        config=_benchConfig(list(CORE_PIDS)[:9]),
        durationSec=0.5,
        koeoOnly=True,
    )

    assert result.dtcReadCount >= 1
    assert result.dtcReadOk is True
    # KOEO is a link+one-read check, not the authoritative capture window.
    assert result.connectEdgeExercised is True


class _NoLock:
    """A no-op context manager -- stands in for a REVERTED _ioLock so the probe's
    regression-detection teeth can be proven off-Pi (validationCriterion 2)."""

    def __enter__(self) -> _NoLock:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def locked(self) -> bool:
        return False


def test_runConnectEdgeCapture_withRevertedLock_detectsInterleave_andGateFails(
    tmp_path: Path,
) -> None:
    """Validation teeth: with the ObdConnection._ioLock reverted to a no-op, the
    logger read and the DTC read DO interleave on the one non-thread-safe port,
    the probe observes it, and evaluateGate FAILS -- proving the gate would catch
    an A-17 regression rather than green-light it."""
    from src.pi.obdii.database import ObdDatabase

    conn, port = _realConnectionWithFakePort()
    conn._ioLock = _NoLock()  # simulate the F-117 fix being reverted
    db = ObdDatabase(str(tmp_path / "gate_revert.db"))
    db.initialize()

    result = runConnectEdgeCapture(
        connection=conn,
        database=db,
        config=_benchConfig(list(CORE_PIDS)[:9]),
        durationSec=1.0,
    )

    assert port.interleaved is True, "no-lock run should have interleaved the port"
    assert result.interleaveObserved is True
    verdict = evaluateGate(result, minRows=0, minDistinctParams=1)
    assert verdict.passed is False
    assert "interleave" in verdict.reason.lower()
