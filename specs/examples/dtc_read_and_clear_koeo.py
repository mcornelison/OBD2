################################################################################
# File Name: dtc_read_and_clear_koeo.py
# Purpose/Description: SPEC EXAMPLE (reference, not deployed) -- KOEO (key-on /
#                      engine-off) direct DTC read + safety-gated log-then-clear
#                      flow. Distilled from a real read+clear run on the Eclipse
#                      (ECU MD326328, code P0443) on 2026-06-05. Demonstrates the
#                      two mechanics the DTC-viewer feature needs that do not yet
#                      exist in src/: (1) a DTC read independent of DriveDetector
#                      (works at RPM 0), and (2) the log-before-clear safety gate.
# Author: Spool (Tuning SME)
# Creation Date: 2026-06-05
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-05    | Spool        | Initial -- reference for the DTC display + clear
#               |              | feature. Companion to
#               |              | offices/tuner/dtc-display-clear-safety-advisory.md.
# ================================================================================
################################################################################

"""KOEO DTC read + safety-gated clear -- REFERENCE EXAMPLE.

This is a spec example, not deployed code. It mirrors the actual flow run on the
Pi on 2026-06-05 to read and clear a stored P0443 (EVAP purge valve circuit) with
the engine off. Ralph/Atlas: lift the mechanics, integrate into the orchestrator;
do not ship this file.

Two things it demonstrates that the live pipeline does NOT do today:

1. **KOEO read (RPM 0, no drive).** Every current capture path
   (``DtcLogger.logSessionStartDtcs`` / ``maybePeriodicMode03`` /
   ``logDriveEndDtcs``) is gated behind ``DriveDetector._startDrive``, which only
   fires on RPM > threshold for a sustained duration. Key-on/engine-off captures
   nothing. The viewer needs the read below, which queries Mode 03 directly on
   connection and writes ``dtc_log`` rows with ``drive_id = NULL``.

2. **Log-before-clear safety gate.** Mode 04 (clear) is all-or-nothing -- it wipes
   EVERY stored + pending code, the freeze frame, AND all readiness monitors in one
   shot. There is no per-code clear in OBD-II. So the clear here:
     - refuses unless EVERY stored code is clear-eligible (severity verdict comes
       from Spool's taxonomy / the lookup table -- NOT decided here),
     - persists every code AND confirms the server acked the sync BEFORE clearing,
     - re-reads after clearing to confirm success and to catch an instant re-set
       (a code that comes right back is a hard fault -- do not offer a 2nd clear).

Operational caveat (Pi): the ``eclipse-obd`` service holds the single serial
channel to the OBDLink LX. A standalone read/clear must ``systemctl stop
eclipse-obd`` first and restart after (see ``__main__``). The real feature would
run inside the orchestrator, which already owns the connection -- no stop needed.

ECU-specific (MD326328, verified 2026-06-05): Mode 02 freeze-frame is UNSUPPORTED
(returns null). The log-before-clear snapshot therefore falls back to code +
realtime_data; there is no freeze frame to capture.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# python-obd is Pi-only; imported lazily by the runner so this file is readable
# off-Pi as a spec artifact.

# Mode 04 (clear) round-trip needs a beat for the ECU to settle before re-reading.
_POST_CLEAR_SETTLE_SECONDS: float = 2.0


# ================================================================================
# Value objects
# ================================================================================


@dataclass(frozen=True)
class DtcReadResult:
    """One KOEO read of the ECU's diagnostic surface.

    Attributes:
        stored: Mode 03 (code, description) pairs -- the codes that lit the MIL.
        pending: Mode 07 pairs -- leading indicators that fire before the MIL.
        freezeFrameSupported: Whether Mode 02 returned a frame (False on MD326328).
        milOn: Mode 01 PID 01 MIL bit, when decodable.
        capturedAtUtc: When this read was taken (observation time, NOT fault onset).
    """

    stored: list[tuple[str, str]]
    pending: list[tuple[str, str]]
    freezeFrameSupported: bool
    milOn: bool | None
    capturedAtUtc: str


@dataclass
class ClearResult:
    """Outcome of a log-then-clear attempt.

    Attributes:
        attempted: True if Mode 04 was actually issued (gates all passed).
        refusedReason: Why the clear was refused, when ``attempted`` is False.
        clearedCodes: Codes present before the clear.
        residualCodes: Codes still present after the clear -- a non-empty list here
            means at least one code re-set immediately (hard fault; refuse a 2nd
            clear).
    """

    attempted: bool
    refusedReason: str | None = None
    clearedCodes: list[str] = field(default_factory=list)
    residualCodes: list[str] = field(default_factory=list)


# ================================================================================
# Read (KOEO-safe -- works at RPM 0)
# ================================================================================


def readDtcs(connection: Any) -> DtcReadResult:
    """Read the ECU's DTC surface directly. Safe key-on / engine-off.

    Independent of DriveDetector -- this is the read the viewer needs so a
    just-keyed-on car shows its codes without first being driven.

    Args:
        connection: A live ``obd.OBD`` (or compatible) with ``query(cmd,
            force=True)`` returning responses exposing ``is_null()`` + ``value``.

    Returns:
        A :class:`DtcReadResult` snapshot.
    """
    import obd  # lazy: Pi-only

    def query(commandName: str) -> Any:
        cmd = getattr(obd.commands, commandName)
        resp = connection.query(cmd, force=True)
        return None if (resp is None or resp.is_null()) else resp.value

    storedRaw = query('GET_DTC') or []
    pendingRaw = query('GET_CURRENT_DTC') or []
    freeze = query('FREEZE_DTC')  # Mode 02 -- None/unsupported on MD326328
    status = query('STATUS')

    milOn: bool | None = None
    if status is not None:
        # python-obd's Status object exposes ``.MIL`` as a bool when decoded.
        milOn = bool(getattr(status, 'MIL', None)) if hasattr(status, 'MIL') else None

    return DtcReadResult(
        stored=[(str(c), str(d)) for c, d in storedRaw],
        pending=[(str(c), str(d)) for c, d in pendingRaw],
        freezeFrameSupported=freeze is not None,
        milOn=milOn,
        capturedAtUtc=_nowUtcIso(),
    )


# ================================================================================
# Log-then-clear (safety-gated)
# ================================================================================


def logThenClear(
    connection: Any,
    *,
    storedCodes: list[str],
    isClearEligible: Callable[[str], bool],
    persistAndConfirmSynced: Callable[[list[str], str], bool],
) -> ClearResult:
    """Persist + server-confirm DTCs, THEN clear -- with the full safety gate.

    Mode 04 is all-or-nothing; this enforces that you never wipe codes you have
    not durably recorded, and never clear anything above MINOR severity.

    Args:
        connection: Live ``obd.OBD``-like connection.
        storedCodes: The codes currently stored (from :func:`readDtcs`).
        isClearEligible: Severity verdict per code -- True only for MINOR,
            clear-eligible codes. Sourced from Spool's taxonomy / the lookup
            table; NOT decided here. Any False => refuse (Mode 04 hits all codes).
        persistAndConfirmSynced: ``(codes, capturedAtUtc) -> bool``. Must log the
            codes with the timestamp AND return True only once the server has
            ACKed the sync. Returning False blocks the clear.

    Returns:
        A :class:`ClearResult`.
    """
    import obd  # lazy: Pi-only

    if not storedCodes:
        return ClearResult(attempted=False, refusedReason='no stored codes to clear')

    # Gate 1 -- severity. Mode 04 wipes ALL codes, so a single non-eligible code
    # blocks the whole clear (you cannot spare it).
    blocking = [c for c in storedCodes if not isClearEligible(c)]
    if blocking:
        return ClearResult(
            attempted=False,
            refusedReason=f'refusing clear: codes above MINOR present: {blocking}',
        )

    # Gate 2 -- log + server ack BEFORE clearing (no clear of unrecorded codes).
    capturedAtUtc = _nowUtcIso()
    if not persistAndConfirmSynced(storedCodes, capturedAtUtc):
        return ClearResult(
            attempted=False,
            refusedReason='refusing clear: codes not logged + server-acked',
        )

    # Gates passed -- issue Mode 04.
    connection.query(obd.commands.CLEAR_DTC, force=True)
    time.sleep(_POST_CLEAR_SETTLE_SECONDS)

    # Re-read: confirm cleared + catch an instant re-set (hard fault).
    after = readDtcs(connection)
    residual = [code for code, _desc in after.stored]
    return ClearResult(
        attempted=True,
        clearedCodes=list(storedCodes),
        residualCodes=residual,
    )


def _nowUtcIso() -> str:
    """Canonical ISO-8601 UTC timestamp (matches dtc_log's stored format)."""
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ================================================================================
# Runner -- mirrors the real 2026-06-05 Pi run. Reference only.
# ================================================================================

if __name__ == '__main__':
    # On the Pi, the eclipse-obd service owns the serial channel -- stop it first:
    #     sudo systemctl stop eclipse-obd
    # ...and restart it after this exits:
    #     sudo systemctl start eclipse-obd
    # (The real feature runs inside the orchestrator and skips the stop/start.)
    import obd  # noqa: F401  (Pi-only; here so the runner fails loudly off-Pi)

    conn = obd.OBD(fast=False, timeout=12)  # fast=False => full ISO 9141-2 init

    read = readDtcs(conn)
    print(f'stored={read.stored} pending={read.pending} '
          f'freezeFrame={read.freezeFrameSupported} mil={read.milOn} '
          f'at={read.capturedAtUtc}')

    # Example persistence hook: insert into dtc_log + confirm sync. In the real
    # feature this writes the Pi dtc_log table (drive_id NULL for KOEO) and waits
    # for the server sync ack. Stubbed True here for illustration only.
    def _persist(codes: list[str], capturedAtUtc: str) -> bool:
        print(f'LOG {codes} @ {capturedAtUtc} (then confirm server sync ack)')
        return True

    # Severity verdict belongs to Spool's taxonomy / the lookup table. Stub: only
    # the known-MINOR evap codes are clear-eligible here.
    _MINOR = {'P0443', 'P0440', 'P0442', 'P0455'}

    result = logThenClear(
        conn,
        storedCodes=[code for code, _ in read.stored],
        isClearEligible=lambda c: c in _MINOR,
        persistAndConfirmSynced=_persist,
    )
    print(result)

    conn.close()
