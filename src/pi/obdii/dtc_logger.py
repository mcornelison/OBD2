################################################################################
# File Name: dtc_logger.py
# Purpose/Description: DtcLogger -- orchestration layer that combines DtcClient,
#                      drive_id context (US-200), and dtc_log database writes
#                      (US-204).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- session-start + MIL-event DTC writes.
# ================================================================================
################################################################################

"""DTC persistence layer (US-204 / Spool Data v2 Story 3).

Combines :class:`~src.pi.obdii.dtc_client.DtcClient` (Mode 03 / Mode 07
fetch) with the Pi-side ``dtc_log`` capture table.  Two entry points:

* :meth:`DtcLogger.logSessionStartDtcs` -- called from
  :meth:`DriveDetector._startDrive` immediately after a fresh
  ``drive_id`` is minted.  Runs both Mode 03 and Mode 07 (probe-first)
  and writes one row per DTC.

* :meth:`DtcLogger.logMilEventDtcs` -- called from the orchestrator's
  reading dispatcher when MIL_ON observes a 0->1 rising edge.  Runs
  Mode 03 only.  Codes that already exist for the same drive bump
  ``last_seen_timestamp`` via UPDATE; new codes INSERT.

Honored invariants (US-204 spec):

* Every row carries a ``drive_id`` -- explicit argument or fallback to
  :func:`~src.pi.obdii.drive_id.getCurrentDriveId`.  NULL is allowed
  only when no drive context exists at all (defensive; in practice
  the orchestrator should not dispatch MIL events outside of RUNNING).
* ``data_source`` is left to the schema DEFAULT ('real') -- writers do
  not pass an override on the live path.
* Timestamps come from the schema DEFAULT (canonical ISO-8601 UTC via
  ``strftime('%Y-%m-%dT%H:%M:%SZ', 'now')``).  No naive Python clock
  in this module.
* Duplicate detection is scoped to ``(drive_id, dtc_code)`` -- a code
  observed in a previous drive does NOT update an old row; new drives
  always emit fresh rows.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

from .drive_id import getCurrentDriveId
from .dtc_client import (
    DiagnosticCode,
    DtcClient,
    Mode07ProbeResult,
    ObdConnectionLike,
)
from .dtc_log_schema import DTC_LOG_TABLE

__all__ = [
    'DatabaseLike',
    'DtcLogger',
    'MilEventResult',
    'SessionStartResult',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Database protocol -- matches ObdDatabase
# ================================================================================


class DatabaseLike(Protocol):
    """Structural interface satisfied by
    :class:`src.pi.obdii.database.ObdDatabase` and test stand-ins.
    """

    def connect(self) -> Any: ...  # context manager yielding sqlite3.Connection


# ================================================================================
# Result objects
# ================================================================================


@dataclass(frozen=True)
class SessionStartResult:
    """Per-call summary returned from :meth:`DtcLogger.logSessionStartDtcs`.

    Attributes:
        storedCount: Number of Mode 03 rows persisted.
        pendingCount: Number of Mode 07 rows persisted (zero when
            ``mode07Probe.supported`` is False).
        mode07Probe: Probe result so the caller can cache "don't try
            Mode 07 again on this connection" without re-fetching.
    """

    storedCount: int
    pendingCount: int
    mode07Probe: Mode07ProbeResult


@dataclass(frozen=True)
class MilEventResult:
    """Per-call summary returned from :meth:`DtcLogger.logMilEventDtcs`.

    Attributes:
        inserted: Codes new to this drive (INSERT).
        updated: Codes already seen this drive whose ``last_seen``
            timestamp was bumped (UPDATE).
    """

    inserted: int
    updated: int


# ================================================================================
# DtcLogger
# ================================================================================


class DtcLogger:
    """Persists DTCs into the ``dtc_log`` capture table.

    Stateless between calls; the only "memory" of past DTCs lives in
    the database itself (via the ``(drive_id, dtc_code)`` lookup in
    the MIL-event upsert).
    """

    def __init__(
        self,
        *,
        database: DatabaseLike,
        dtcClient: DtcClient,
    ) -> None:
        self._database = database
        self._client = dtcClient

    # ------------------------------------------------------------------
    # Session-start path
    # ------------------------------------------------------------------

    def logSessionStartDtcs(
        self,
        *,
        driveId: int | None,
        connection: ObdConnectionLike,
    ) -> SessionStartResult:
        """Run Mode 03 + Mode 07 (probe-first) and persist all returned DTCs.

        Args:
            driveId: The drive_id minted by DriveDetector for this
                session.  ``None`` falls back to
                :func:`getCurrentDriveId` (which the orchestrator may
                have set already), then to NULL in the row.
            connection: Live OBD connection.

        Returns:
            :class:`SessionStartResult` with per-mode counts + the
            Mode 07 probe verdict.

        Raises:
            DtcClientError: Re-raised if the connection is not open.
        """
        effectiveDriveId = driveId if driveId is not None else getCurrentDriveId()

        stored: list[DiagnosticCode] = self._client.readStoredDtcs(connection)
        pending, probe = self._client.readPendingDtcs(connection)

        with self._database.connect() as conn:
            self._insertCodes(conn, stored, effectiveDriveId)
            self._insertCodes(conn, pending, effectiveDriveId)

        if not probe.supported:
            logger.info(
                "Mode 07 unsupported on this connection -- caching probe"
            )

        return SessionStartResult(
            storedCount=len(stored),
            pendingCount=len(pending),
            mode07Probe=probe,
        )

    # ------------------------------------------------------------------
    # MIL rising-edge path
    # ------------------------------------------------------------------

    def logMilEventDtcs(
        self,
        *,
        driveId: int | None,
        connection: ObdConnectionLike,
    ) -> MilEventResult:
        """Re-fetch Mode 03 and upsert by (drive_id, dtc_code).

        Codes already present for this drive get a fresh
        ``last_seen_timestamp`` via UPDATE; new codes INSERT.  Codes
        seen in a *different* drive always INSERT a fresh row.

        Args:
            driveId: Same fallback rule as :meth:`logSessionStartDtcs`.
            connection: Live OBD connection.

        Returns:
            :class:`MilEventResult` with insert / update counts.
        """
        effectiveDriveId = driveId if driveId is not None else getCurrentDriveId()
        stored = self._client.readStoredDtcs(connection)

        inserted = 0
        updated = 0
        with self._database.connect() as conn:
            for code in stored:
                if self._existingRowId(conn, effectiveDriveId, code.code) is not None:
                    self._updateLastSeen(conn, effectiveDriveId, code.code)
                    updated += 1
                else:
                    self._insertOne(conn, code, effectiveDriveId)
                    inserted += 1
        return MilEventResult(inserted=inserted, updated=updated)

    # ------------------------------------------------------------------
    # Internal SQL helpers
    # ------------------------------------------------------------------

    def _insertCodes(
        self,
        conn: sqlite3.Connection,
        codes: list[DiagnosticCode],
        driveId: int | None,
    ) -> None:
        for code in codes:
            self._insertOne(conn, code, driveId)

    def _insertOne(
        self,
        conn: sqlite3.Connection,
        code: DiagnosticCode,
        driveId: int | None,
    ) -> None:
        # data_source + first_seen_timestamp + last_seen_timestamp all
        # picked up from the schema DEFAULTs -- we do not pass them
        # here so US-202 canonical timestamps stay authoritative at
        # the DB boundary.
        conn.execute(
            f"INSERT INTO {DTC_LOG_TABLE} "
            "(dtc_code, description, status, drive_id) "
            "VALUES (?, ?, ?, ?)",
            (code.code, code.description, code.status, driveId),
        )

    def _existingRowId(
        self,
        conn: sqlite3.Connection,
        driveId: int | None,
        dtcCode: str,
    ) -> int | None:
        """Return the dtc_log row id for (driveId, dtcCode), if any.

        IS NULL semantics: when ``driveId`` is None we still match rows
        whose ``drive_id`` is NULL so the duplicate test under "no
        drive context" still upserts cleanly.
        """
        if driveId is None:
            row = conn.execute(
                f"SELECT id FROM {DTC_LOG_TABLE} "
                f"WHERE drive_id IS NULL AND dtc_code = ? LIMIT 1",
                (dtcCode,),
            ).fetchone()
        else:
            row = conn.execute(
                f"SELECT id FROM {DTC_LOG_TABLE} "
                f"WHERE drive_id = ? AND dtc_code = ? LIMIT 1",
                (int(driveId), dtcCode),
            ).fetchone()
        return None if row is None else int(row[0])

    @staticmethod
    def _updateLastSeen(
        conn: sqlite3.Connection,
        driveId: int | None,
        dtcCode: str,
    ) -> None:
        # Re-evaluate the canonical timestamp at the DB layer so the
        # bump survives clock drift in the calling Python process.
        if driveId is None:
            conn.execute(
                f"UPDATE {DTC_LOG_TABLE} "
                f"SET last_seen_timestamp = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                f"WHERE drive_id IS NULL AND dtc_code = ?",
                (dtcCode,),
            )
        else:
            conn.execute(
                f"UPDATE {DTC_LOG_TABLE} "
                f"SET last_seen_timestamp = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') "
                f"WHERE drive_id = ? AND dtc_code = ?",
                (int(driveId), dtcCode),
            )
