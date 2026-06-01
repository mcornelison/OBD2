################################################################################
# File Name: freeze_frame.py
# Purpose/Description: Pi-side Mode 02 freeze-frame capture (US-368 / F-109).
#                      Mode02Client enumerates the 16 freeze-frame PIDs (the
#                      Mode 02 / DTC_<NAME> mirror of the project's Mode 01 set)
#                      via the python-obd command-factory seam.  FreezeFrameCapture
#                      is the orchestration layer fired on a MIL_ON rising edge:
#                      it enumerates Mode 02, resolves the active vehicle_info VIN,
#                      and writes one dtc_freeze_frame row keyed by (dtc_log_id,
#                      captured_at).  Mode 02 unavailable -> row with {} + a notes
#                      gap explanation (graceful degradation), never a crash.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- Mode02Client + FreezeFrameCapture.
# ================================================================================
################################################################################

"""Mode 02 freeze-frame capture (US-368 / F-109).

Mode 02 returns the freeze-frame: the snapshot of a Mode-01-shaped PID set
recorded by the ECU at the instant a DTC tripped.  python-obd exposes the
Mode 02 commands as ``DTC_<NAME>`` mirrors of the Mode 01 ``<NAME>`` commands.
:data:`FREEZE_FRAME_PARAMETERS` is the grounded 16-PID set -- every entry is a
real member of :data:`src.pi.obdii.obd_parameters.REALTIME_PARAMETERS` (the
project's polled Mode 01 set) and maps to a canonical SAE J1979 freeze-frame
PID ($04-$11 + $1F + $44).

Design mirrors :mod:`src.pi.obdii.dtc_logger`:

* The python-obd dependency is the ``commandFactory`` seam; tests inject a
  string-returning stub so nothing imports ``obd`` off-Pi.
* The database is injected (``DatabaseLike`` with a ``connect()`` context
  manager) -- :class:`FreezeFrameCapture` owns the single-row INSERT.
* Mode 02 unavailability is the healthy 2G-DSM case (freeze-frame support is
  spotty); it degrades to an empty snapshot + notes, never an exception.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .dtc_client import ObdConnectionLike, defaultCommandFactory
from .dtc_freeze_frame_schema import DTC_FREEZE_FRAME_TABLE

__all__ = [
    'FREEZE_FRAME_PARAMETERS',
    'DatabaseLike',
    'FreezeFrameCapture',
    'FreezeFrameResult',
    'MODE_02_UNAVAILABLE_NOTE',
    'Mode02Client',
]

logger = logging.getLogger(__name__)


# The 16 freeze-frame PIDs.  Each is a real REALTIME_PARAMETERS member (the
# project's Mode 01 set) and mirrors a canonical SAE J1979 freeze-frame PID;
# python-obd exposes the Mode 02 command as ``DTC_<NAME>``.  Order follows the
# PID number ($04..$11, then $1F run-time, then $44 commanded-equiv-ratio).
FREEZE_FRAME_PARAMETERS: tuple[str, ...] = (
    'ENGINE_LOAD',          # $04
    'COOLANT_TEMP',         # $05
    'SHORT_FUEL_TRIM_1',    # $06
    'LONG_FUEL_TRIM_1',     # $07
    'SHORT_FUEL_TRIM_2',    # $08
    'LONG_FUEL_TRIM_2',     # $09
    'FUEL_PRESSURE',        # $0A
    'INTAKE_PRESSURE',      # $0B (MAP)
    'RPM',                  # $0C
    'SPEED',                # $0D
    'TIMING_ADVANCE',       # $0E
    'INTAKE_TEMP',          # $0F
    'MAF',                  # $10
    'THROTTLE_POS',         # $11
    'RUN_TIME',             # $1F
    'COMMANDED_EQUIV_RATIO',  # $44
)

# python-obd Mode 02 command-name prefix (freeze-frame mirror of Mode 01).
_MODE_02_PREFIX: str = 'DTC_'

MODE_02_UNAVAILABLE_NOTE: str = (
    'Mode 02 freeze-frame PIDs unavailable at capture time '
    '(ECU returned no freeze-frame data); snapshot empty.'
)


# ================================================================================
# Database protocol -- matches ObdDatabase (mirrors dtc_logger.DatabaseLike)
# ================================================================================


class DatabaseLike(Protocol):
    """Structural interface satisfied by
    :class:`src.pi.obdii.database.ObdDatabase` and test stand-ins.
    """

    def connect(self) -> Any: ...  # context manager yielding sqlite3.Connection


# ================================================================================
# Result object
# ================================================================================


@dataclass(frozen=True)
class FreezeFrameResult:
    """Per-capture summary returned from :meth:`FreezeFrameCapture.captureOnMilEvent`.

    Attributes:
        rowId: The dtc_freeze_frame row id written.
        pidCount: Number of Mode 02 PIDs captured (0 when unavailable).
        vehicleInfoVin: Active vehicle_info VIN resolved at capture time, or
            ``None`` when no vehicle_info row exists yet.
        degraded: True when Mode 02 was unavailable (empty snapshot + notes).
    """

    rowId: int
    pidCount: int
    vehicleInfoVin: str | None
    degraded: bool


# ================================================================================
# Mode 02 client
# ================================================================================


class Mode02Client:
    """Enumerate the 16 freeze-frame PIDs via Mode 02 (``DTC_<NAME>``).

    Stateless between calls.  Each PID is queried independently and tolerated
    individually: a null / missing / un-decodable response simply omits that
    PID from the result dict, so an ECU with partial Mode 02 support yields a
    partial snapshot and a fully-unsupported ECU yields ``{}``.
    """

    def __init__(self, commandFactory: Callable[[str], Any] | None = None) -> None:
        """Args:
            commandFactory: Optional override for python-obd command
                resolution.  Defaults to
                :func:`src.pi.obdii.dtc_client.defaultCommandFactory`.  Tests
                inject a string-returning stub so no ``obd`` import occurs
                off-Pi.
        """
        self._commandFactory = commandFactory or defaultCommandFactory

    def enumerate(self, connection: ObdConnectionLike) -> dict[str, float]:
        """Query Mode 02 for each freeze-frame PID; return the available ones.

        Args:
            connection: Live OBD connection (only ``obd.query`` is touched).

        Returns:
            ``{pid_name: value}`` for every freeze-frame PID that returned a
            non-null, numeric value.  Empty dict when Mode 02 is unsupported.
        """
        snapshot: dict[str, float] = {}
        for name in FREEZE_FRAME_PARAMETERS:
            try:
                cmd = self._commandFactory(f"{_MODE_02_PREFIX}{name}")
                response = connection.obd.query(cmd)
                value = self._extractValue(response)
                if value is not None:
                    snapshot[name] = value
            except Exception as exc:  # noqa: BLE001 -- one bad PID must not abort
                logger.debug("Mode 02 query for %s failed: %s", name, exc)
        return snapshot

    @staticmethod
    def _extractValue(response: Any) -> float | None:
        """Pull a float out of a python-obd response, tolerating shape drift.

        Returns ``None`` for null responses, missing values, and values that
        do not coerce to float (the PID is simply skipped).
        """
        if response is None:
            return None
        isNull = getattr(response, 'is_null', None)
        if callable(isNull):
            try:
                if isNull():
                    return None
            except Exception:  # noqa: BLE001 -- null-check must not raise
                return None
        value = getattr(response, 'value', None)
        if value is None:
            return None
        # python-obd wraps numerics in a pint Quantity (``.magnitude``).
        magnitude = getattr(value, 'magnitude', value)
        try:
            return float(magnitude)
        except (TypeError, ValueError):
            return None


# ================================================================================
# Freeze-frame capture orchestration
# ================================================================================


class FreezeFrameCapture:
    """Persist a Mode 02 freeze-frame into ``dtc_freeze_frame``.

    Fired on a MIL_ON rising edge: enumerate Mode 02, resolve the active
    vehicle_info VIN, and write one row keyed by ``(dtc_log_id, captured_at)``.
    """

    def __init__(
        self,
        *,
        database: DatabaseLike,
        mode02Client: Mode02Client | None = None,
    ) -> None:
        self._database = database
        self._client = mode02Client or Mode02Client()

    def captureOnMilEvent(
        self,
        *,
        connection: ObdConnectionLike,
        dtcLogId: int | None,
    ) -> FreezeFrameResult:
        """Capture + persist one freeze-frame for a MIL event.

        Args:
            connection: Live OBD connection for the Mode 02 enumeration.
            dtcLogId: dtc_log row id the freeze-frame belongs to (``None`` when
                no DTC row is resolved yet).

        Returns:
            :class:`FreezeFrameResult` describing the written row.

        Note:
            ``captured_at_timestamp_utc`` is left to the schema DEFAULT
            (canonical ISO-8601 UTC at the DB boundary) so US-202 timestamps
            stay authoritative -- no naive Python clock here.
        """
        snapshot = self._client.enumerate(connection)
        degraded = not snapshot
        notes = MODE_02_UNAVAILABLE_NOTE if degraded else None

        with self._database.connect() as conn:
            # When the caller does not pin a dtc_log_id (the orchestrator's
            # MIL-edge dispatch path), bind to the most-recent DTC -- the code
            # the MIL event just logged is the one that tripped the freeze-frame.
            effectiveDtcLogId = (
                dtcLogId if dtcLogId is not None else self._latestDtcLogId(conn)
            )
            vin = self._resolveActiveVehicleVin(conn)
            cursor = conn.execute(
                f"INSERT INTO {DTC_FREEZE_FRAME_TABLE} "
                "(dtc_log_id, pid_responses_json, vehicle_info_vin, notes) "
                "VALUES (?, ?, ?, ?)",
                (effectiveDtcLogId, json.dumps(snapshot), vin, notes),
            )
            rowId = int(cursor.lastrowid)

        logger.info(
            "Freeze-frame captured | dtc_log_id=%s | pids=%d | vin=%s | degraded=%s",
            effectiveDtcLogId, len(snapshot), vin, degraded,
        )
        return FreezeFrameResult(
            rowId=rowId,
            pidCount=len(snapshot),
            vehicleInfoVin=vin,
            degraded=degraded,
        )

    @staticmethod
    def _latestDtcLogId(conn: Any) -> int | None:
        """Return the most-recent dtc_log row id, or ``None`` if there are none.

        Tolerant of a missing dtc_log table (returns ``None``) so a freeze-frame
        still lands keyed by captured_at alone.
        """
        try:
            row = conn.execute("SELECT MAX(id) FROM dtc_log").fetchone()
        except Exception as exc:  # noqa: BLE001 -- best-effort linkage
            logger.debug("dtc_log id resolution failed: %s", exc)
            return None
        if row is None or row[0] is None:
            return None
        return int(row[0])

    @staticmethod
    def _resolveActiveVehicleVin(conn: Any) -> str | None:
        """Return the active vehicle_info VIN, or ``None`` if no row exists.

        The Pi tracks a single vehicle (vehicle_info PK is ``vin``); the most
        recently updated row is the currently-active vehicle.  The server's
        ECU-lineage notion of "active" (NULL removal timestamp) is server-only
        (US-365) and resolved at sync time (US-369), not here.
        """
        row = conn.execute(
            "SELECT vin FROM vehicle_info "
            "ORDER BY updated_at DESC, created_at DESC LIMIT 1",
        ).fetchone()
        return None if row is None else row[0]
