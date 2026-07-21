################################################################################
# File Name: pre_drive_gate.py
# Purpose/Description: US-479 (F-117) pre-drive OBD connect + capture green-light.
#                      The connect-edge capture probe + pure PASS/FAIL gate logic
#                      behind the CIO-runnable scripts/verify_pre_drive.sh wrapper.
#                      Runs the realtime logger and a KOEO/idle DTC read on ONE
#                      connection concurrently -- the exact A-17 race (F-117) that
#                      let a weekend of drives capture zero rows -- so a
#                      happy-path-only pass is impossible: the gate REFUSES to
#                      green-light unless the connect-edge was actually crossed and
#                      capture survived it.
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

"""Pre-drive OBD connect + capture green-light (US-479 / F-117).

Two pieces, both bench-validatable off-Pi and both used by the CIO-runnable
``scripts/verify_pre_drive.sh``:

* :func:`runConnectEdgeCapture` -- drives a real capture window in which the
  realtime logger read loop and a KOEO/idle DTC read run CONCURRENTLY on ONE
  connection.  On a real :class:`~src.pi.obdii.obd_connection.ObdConnection` both
  reads serialize through the single ``_ioLock``; this is the exact connect-edge
  the A-17 race lives on, exercised on purpose so a green cannot happen while the
  race silently kills capture.

* :func:`evaluateGate` -- the pure PASS/FAIL decision.  Its load-bearing rule:
  a run where rows landed but the connect-edge was never exercised (or where the
  two reads interleaved, or a DTC read raised a disconnected-while-reading error)
  can NOT green-light.  That blind spot is what let a weekend of drives capture
  zero rows with a happy-path smoke test reporting "fine".

A bench PASS is explicitly NOT a substitute for the live in-car gate -- same
discipline as ``scripts/verify_live_idle.sh``.  The authoritative gate is the
CIO running this live at warm idle before a drive.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Core PIDs whose sustained coverage proves the ECU is really answering.
# Grounded in config.json ``pi.realtimeData.parameters`` (the logged set) and the
# simulator's PARAMETER_UNITS.  All take the simple Mode-01 float read path (none
# are Spool-v2 decoder parameters), so coverage here means "the ECU returned a
# value for this PID", not "a decoder happened to parse".
# ------------------------------------------------------------------------------
CORE_PIDS: tuple[str, ...] = (
    "RPM",
    "SPEED",
    "COOLANT_TEMP",
    "THROTTLE_POS",
    "ENGINE_LOAD",
    "INTAKE_TEMP",
    "TIMING_ADVANCE",
    "MAF",
    "INTAKE_PRESSURE",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "CONTROL_MODULE_VOLTAGE",
)

#: Minimum rows/sec the live window must sustain (matches verify_live_idle.sh).
DEFAULT_MIN_ROWS_PER_SEC: float = 0.3
#: Minimum distinct core PIDs the ECU must answer (matches verify_live_idle.sh).
DEFAULT_MIN_DISTINCT_PARAMS: int = 8


# ================================================================================
# Value objects
# ================================================================================


@dataclass(frozen=True)
class CaptureResult:
    """Outcome of a connect-edge capture window.

    Attributes:
        rowsWritten: ``realtime_data`` rows written during the window.
        distinctParams: Distinct ``parameter_name`` values written (coverage).
        coveredParams: The set of core PIDs actually written.
        durationSec: Wall-clock length of the capture window.
        dtcReadCount: Number of KOEO/idle DTC reads that completed.
        dtcReadOk: True if every DTC read completed without a
            disconnected-while-reading class error.
        connectEdgeExercised: True when at least one DTC read co-occurred with
            the running realtime logger on the one connection (the A-17 edge).
        interleaveObserved: True if the one non-thread-safe port saw two callers
            at once (serialization regressed); None when the port is not
            instrumented (e.g. the simulator).
        captureError: A disconnected-while-reading class error string, or None.
    """

    rowsWritten: int
    distinctParams: int
    coveredParams: frozenset[str]
    durationSec: float
    dtcReadCount: int
    dtcReadOk: bool
    connectEdgeExercised: bool
    interleaveObserved: bool | None
    captureError: str | None


@dataclass(frozen=True)
class GateVerdict:
    """The PASS/FAIL decision for a capture result."""

    passed: bool
    reason: str


# ================================================================================
# Pure gate-decision logic
# ================================================================================


def evaluateGate(
    result: CaptureResult,
    *,
    minRows: int,
    minDistinctParams: int,
    requireConnectEdge: bool = True,
    requireRows: bool = True,
) -> GateVerdict:
    """Decide whether a capture result may green-light a drive.

    Checks run most-fundamental first so the reported reason names the deepest
    failure.  The connect-edge / interleave / DTC checks come BEFORE the row and
    coverage checks: rows can land while the race is live on a different tick, so
    "rows landed" must never on its own produce a PASS (the whole US-479 point).

    Args:
        result: The capture outcome to judge.
        minRows: Minimum ``realtime_data`` rows for the window.
        minDistinctParams: Minimum distinct core-PID coverage.
        requireConnectEdge: When True (the live/idle gate), refuse to pass if the
            connect-edge was never exercised.  A KOEO-only sub-check keeps this
            True too (it still runs a concurrent read).
        requireRows: When False (the KOEO engine-off sub-check), skip the row and
            coverage floors -- the earliest driveway signal is link + one read.

    Returns:
        A :class:`GateVerdict`.
    """
    if result.captureError:
        return GateVerdict(False, f"FAIL -- capture error: {result.captureError}")

    if result.interleaveObserved is True:
        return GateVerdict(
            False,
            "FAIL -- connect-edge interleave observed: the logger read and the "
            "DTC read hit the one non-thread-safe port at once (A-17 race live)",
        )

    if not result.dtcReadOk:
        return GateVerdict(
            False,
            "FAIL -- KOEO/idle DTC read failed on the connection edge "
            "(disconnected-while-reading class)",
        )

    if requireConnectEdge and not result.connectEdgeExercised:
        return GateVerdict(
            False,
            "FAIL -- connect-edge NOT exercised: no DTC read co-occurred with the "
            "logger, so this is a happy-path-only run and cannot green-light",
        )

    if requireRows and result.rowsWritten < minRows:
        return GateVerdict(
            False,
            f"FAIL -- rows {result.rowsWritten} < required {minRows} "
            "(capture is not landing)",
        )

    if requireRows and result.distinctParams < minDistinctParams:
        return GateVerdict(
            False,
            f"FAIL -- core-PID coverage {result.distinctParams} < required "
            f"{minDistinctParams} (ECU answered too few PIDs)",
        )

    return GateVerdict(
        True,
        f"PASS -- rows={result.rowsWritten} coverage={result.distinctParams} "
        f"dtcReads={result.dtcReadCount} connect-edge=exercised",
    )


def requiredRows(durationSec: float, minRowsPerSec: float) -> int:
    """Floor of ``duration * rows/sec`` -- the minimum rows for a window."""
    return int(durationSec * minRowsPerSec)


# ================================================================================
# Connect-edge capture
# ================================================================================


def _resolveDtcCommandFactory(
    override: Callable[[str], Any] | None,
) -> Callable[[str], Any] | None:
    """Return the DtcClient command factory to use.

    On the Pi (python-obd installed) return ``None`` so :class:`DtcClient` uses
    its real ``defaultCommandFactory`` (real command objects the ELM327 needs).
    Off-Pi (bench, no python-obd) fall back to an identity factory so the string
    command name flows to the simulated/faked port -- mirroring
    ``ObdDataLogger._getObdCommand``.
    """
    if override is not None:
        return override
    from .obd_connection import OBD_AVAILABLE

    if OBD_AVAILABLE:
        return None  # DtcClient's defaultCommandFactory (real command objects)
    return lambda name: name


def runConnectEdgeCapture(
    *,
    connection: Any,
    database: Any,
    config: dict[str, Any],
    durationSec: float,
    koeoOnly: bool = False,
    dtcCommandFactory: Callable[[str], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> CaptureResult:
    """Run a capture window that exercises the A-17 connect-edge on ONE connection.

    Starts the real :class:`~src.pi.obdii.data.realtime.RealtimeDataLogger` in its
    background thread AND runs a KOEO/idle DTC read loop (Mode 03 + Mode 07 probe
    via :class:`~src.pi.obdii.dtc_client.DtcClient`) concurrently on the same
    connection for ``durationSec``.  Both reads go through ``connection.query()``
    -- on a real :class:`ObdConnection` that is the single ``_ioLock`` serialized
    path, so this is the exact race F-117 fixed, exercised on purpose.

    The probe writes to whatever ``database`` it is given (the caller points it at
    a dedicated/temp DB so it never contaminates production drive data) and reports
    row count + distinct core-PID coverage from that DB.

    Args:
        connection: A live ``ObdConnection`` (or ``SimulatedObdConnection``).
            Connected if not already.
        database: An ``ObdDatabase`` with the ``realtime_data`` schema initialized.
        config: Config carrying ``pi.realtimeData.parameters`` (the logged PIDs).
        durationSec: Length of the capture window.
        koeoOnly: When True, still runs the concurrent read but for the earliest
            engine-off signal (the caller relaxes the row/coverage floors).
        dtcCommandFactory: Test/override seam for DtcClient command resolution.
        clock: Monotonic clock seam.
        sleep: Sleep seam.

    Returns:
        A :class:`CaptureResult`.
    """
    from .data.realtime import RealtimeDataLogger
    from .dtc_client import DtcClient

    captureError: str | None = None
    dtcReadCount = 0
    dtcReadOk = True
    loggerStarted = False

    # Ensure the connection is live (simulator needs connect(); a real conn with a
    # port already attached reports isConnected() True and is left as-is).
    if not connection.isConnected():
        try:
            connection.connect()
        except Exception as exc:  # noqa: BLE001 -- surface as a capture error
            return CaptureResult(
                rowsWritten=0,
                distinctParams=0,
                coveredParams=frozenset(),
                durationSec=0.0,
                dtcReadCount=0,
                dtcReadOk=False,
                connectEdgeExercised=False,
                interleaveObserved=_readInterleave(connection),
                captureError=f"connect failed: {exc}",
            )

    rtLogger = RealtimeDataLogger(config, connection, database)
    client = DtcClient(commandFactory=_resolveDtcCommandFactory(dtcCommandFactory))

    start = clock()
    try:
        loggerStarted = rtLogger.start()
    except Exception as exc:  # noqa: BLE001 -- e.g. no params / not connected
        captureError = f"logger start failed: {exc}"

    if loggerStarted:
        # KOEO/idle DTC read loop, concurrent with the logger's background thread.
        # A tiny gap between reads keeps the two loops genuinely overlapping rather
        # than the DTC loop monopolizing the lock.
        try:
            while (clock() - start) < durationSec:
                client.readStoredDtcs(connection)
                client.readPendingDtcs(connection)
                dtcReadCount += 1
                sleep(0.02)
        except Exception as exc:  # noqa: BLE001 -- the disconnected-while-reading class
            dtcReadOk = False
            captureError = captureError or f"dtc read raised: {exc}"

        rtLogger.stop()

    durationActual = clock() - start
    connectEdgeExercised = loggerStarted and dtcReadCount >= 1

    rowsWritten, distinctParams, coveredParams = _readCaptureCounts(database)

    return CaptureResult(
        rowsWritten=rowsWritten,
        distinctParams=distinctParams,
        coveredParams=coveredParams,
        durationSec=durationActual,
        dtcReadCount=dtcReadCount,
        dtcReadOk=dtcReadOk,
        connectEdgeExercised=connectEdgeExercised,
        interleaveObserved=_readInterleave(connection),
        captureError=captureError,
    )


def _readInterleave(connection: Any) -> bool | None:
    """Report whether the underlying port latched a concurrent-access interleave.

    Returns None when the port is not instrumented (the simulator / a real port
    that does not expose the flag) so :func:`evaluateGate` only fails on an
    explicit True.
    """
    port = getattr(connection, "obd", None)
    value = getattr(port, "interleaved", None)
    return bool(value) if value is not None else None


def _readCaptureCounts(database: Any) -> tuple[int, int, frozenset[str]]:
    """Read row count + distinct core-PID coverage from ``realtime_data``."""
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM realtime_data")
            rows = int(cursor.fetchone()[0])
            cursor.execute("SELECT DISTINCT parameter_name FROM realtime_data")
            params = frozenset(str(r[0]) for r in cursor.fetchall())
        return rows, len(params), params
    except Exception as exc:  # noqa: BLE001 -- a probe error is an honest 0
        logger.warning("Failed to read capture counts: %s", exc)
        return 0, 0, frozenset()
