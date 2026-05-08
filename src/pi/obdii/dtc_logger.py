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
# 2026-05-07    | Rex (US-292) | Spool 2026-05-06 gap closure: maybePeriodicMode03
#               |              | (30s during-drive Mode 03 cadence) +
#               |              | logDriveEndDtcs (Mode 07 at drive_end -- pending
#               |              | codes are the leading indicator).  Cadence state
#               |              | resets on drive boundary.  Pre-existing
#               |              | session-start + MIL-event paths unchanged.
# 2026-05-08    | Rex (US-295) | B-047 D2 safety-precondition audit:
#               |              | isDtcRetrievalActive property + lock-protected
#               |              | counter wrapped around the four entry methods
#               |              | so the Pi UpdateChecker can gate auto-deploy
#               |              | on "no in-flight DTC retrieval".
# ================================================================================
################################################################################

"""DTC persistence layer (US-204 / Spool Data v2 Story 3).

Combines :class:`~src.pi.obdii.dtc_client.DtcClient` (Mode 03 / Mode 07
fetch) with the Pi-side ``dtc_log`` capture table.  Four entry points:

* :meth:`DtcLogger.logSessionStartDtcs` -- called from
  :meth:`DriveDetector._startDrive` immediately after a fresh
  ``drive_id`` is minted.  Runs both Mode 03 and Mode 07 (probe-first)
  and writes one row per DTC.

* :meth:`DtcLogger.logMilEventDtcs` -- called from the orchestrator's
  reading dispatcher when MIL_ON observes a 0->1 rising edge.  Runs
  Mode 03 only.  Codes that already exist for the same drive bump
  ``last_seen_timestamp`` via UPDATE; new codes INSERT.

* :meth:`DtcLogger.maybePeriodicMode03` -- US-292 (Spool 2026-05-06).
  Cheap-to-call helper invoked from the reading-tick loop while a
  drive is active.  Re-fires Mode 03 every ``intervalSeconds`` (30s
  in production) so codes that appear mid-drive without a MIL rising
  edge still land in dtc_log.  Cadence state resets on drive
  boundary.

* :meth:`DtcLogger.logDriveEndDtcs` -- US-292 (Spool 2026-05-06).
  Mode 07 only at drive_end.  Pending codes are the leading indicator
  -- they fire BEFORE the MIL ladder, so the drive-end snapshot is
  the cleanest pre-MIL artifact for post-drive review.

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
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
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
    'DriveEndResult',
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

    Also returned from :meth:`DtcLogger.maybePeriodicMode03` (US-292):
    a periodic poll that finds no codes returns ``MilEventResult(0, 0)``,
    a poll skipped due to the cooldown returns ``MilEventResult(0, 0)``,
    and a poll that finds codes returns the same insert/update split.

    Attributes:
        inserted: Codes new to this drive (INSERT).
        updated: Codes already seen this drive whose ``last_seen``
            timestamp was bumped (UPDATE).
    """

    inserted: int
    updated: int


@dataclass(frozen=True)
class DriveEndResult:
    """Per-call summary returned from :meth:`DtcLogger.logDriveEndDtcs`.

    US-292 (Spool 2026-05-06).  Mode 07 only -- pending codes are the
    leading indicator and fire BEFORE the MIL ladder, so the drive-end
    snapshot is the cleanest pre-MIL artifact for post-drive review.

    Attributes:
        pendingCount: Number of Mode 07 rows persisted (zero when
            ``mode07Probe.supported`` is False).
        mode07Probe: Probe result so the caller can cache "don't try
            Mode 07 again on this connection" without re-fetching.
    """

    pendingCount: int
    mode07Probe: Mode07ProbeResult


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
        # US-292: 30s during-drive Mode 03 cadence state.  Tracks the
        # drive_id for which the last poll was successful so a drive
        # boundary resets the cooldown (a fresh drive gets a poll
        # immediately, not after another 30s).  None on construction
        # -- first call always fires.
        self._periodicMode03DriveId: int | None = None
        self._periodicMode03LastAt: datetime | None = None
        # US-295 / B-047 D2: in-flight retrieval counter.  Read by the
        # Pi UpdateChecker via the isDtcRetrievalActive property to
        # gate auto-deploy on "no DTC retrieval in flight".  Counter
        # (not bool) so nested / concurrent callers compose; the
        # context manager increments on enter, decrements in finally.
        self._retrievalLock = threading.Lock()
        self._activeRetrievalCount = 0

    # ------------------------------------------------------------------
    # US-295 / B-047 D2 -- in-flight retrieval flag
    # ------------------------------------------------------------------

    @property
    def isDtcRetrievalActive(self) -> bool:
        """``True`` while any DTC entry method is mid-execution.

        Read by :class:`src.pi.update.update_checker.UpdateChecker` to
        gate auto-deploy on the third B-047 D2 precondition (no
        in-flight DTC retrieval).  Today's reading-tick path is
        single-threaded, but :meth:`logDriveEndDtcs` is dispatched from
        a :class:`DriveDetector` callback which may fire on a thread
        distinct from the runLoop thread that drives the update-check
        trigger -- the lock-protected counter is the structural
        defense regardless of present-day call topology.
        """
        with self._retrievalLock:
            return self._activeRetrievalCount > 0

    @contextmanager
    def _markRetrievalActive(self) -> Iterator[None]:
        """Increment the in-flight counter for the duration of a retrieval.

        Symmetric increment / decrement under the lock so a raised
        exception in the wrapped block still releases the slot.  Used
        as ``with self._markRetrievalActive(): ...`` at the top of
        each of the four entry methods.
        """
        with self._retrievalLock:
            self._activeRetrievalCount += 1
        try:
            yield
        finally:
            with self._retrievalLock:
                self._activeRetrievalCount -= 1

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
        with self._markRetrievalActive():
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
        with self._markRetrievalActive():
            effectiveDriveId = driveId if driveId is not None else getCurrentDriveId()
            stored = self._client.readStoredDtcs(connection)
            return self._upsertStoredCodes(stored, effectiveDriveId)

    # ------------------------------------------------------------------
    # US-292 -- 30s during-drive Mode 03 cadence
    # ------------------------------------------------------------------

    def maybePeriodicMode03(
        self,
        *,
        driveId: int | None,
        connection: ObdConnectionLike,
        now: datetime | None = None,
        intervalSeconds: float = 30.0,
    ) -> MilEventResult:
        """Re-run Mode 03 if at least ``intervalSeconds`` elapsed since last poll.

        Spool 2026-05-06 ask: 'Mode 03 query at drive_start + every 30s
        during drive'.  Cheap to call from the reading-tick loop -- the
        cooldown gate short-circuits before any OBD round-trip when the
        interval has not elapsed.

        Cadence state is per-drive: a new ``driveId`` resets the timer
        so a fresh drive's first call fires immediately rather than
        inheriting the cooldown from the previous drive.  ``driveId=None``
        is treated as 'no active drive' and short-circuits to a no-op.

        Args:
            driveId: Active drive_id.  ``None`` => skip (cadence is
                during-drive only; resetting state is intentional so
                the next active drive gets an immediate first poll).
            connection: Live OBD connection.
            now: Optional clock injection for tests; production callers
                pass ``None`` and the helper uses :func:`datetime.now`.
            intervalSeconds: Cooldown between successful polls.  30.0
                in production per Spool's ask; tests override.

        Returns:
            :class:`MilEventResult` -- ``(inserted, updated)`` from the
            Mode 03 upsert when a poll fires; ``(0, 0)`` when the
            cooldown is in effect or the helper short-circuits.

        Raises:
            DtcClientError: Re-raised if a poll fires and the
                connection is not open.
        """
        with self._markRetrievalActive():
            if driveId is None:
                self._periodicMode03DriveId = None
                self._periodicMode03LastAt = None
                return MilEventResult(inserted=0, updated=0)

            currentTime = now if now is not None else datetime.now()

            # Drive boundary => reset state and fire immediately.  The
            # explicit reset matters for the case where a poll was
            # successful in drive N-1 less than 30s before drive N
            # started; without the reset, drive N's first poll would
            # be skipped.
            if driveId != self._periodicMode03DriveId:
                self._periodicMode03DriveId = driveId
                self._periodicMode03LastAt = None

            if self._periodicMode03LastAt is not None:
                elapsed = (currentTime - self._periodicMode03LastAt).total_seconds()
                if elapsed < intervalSeconds:
                    return MilEventResult(inserted=0, updated=0)

            stored = self._client.readStoredDtcs(connection)
            result = self._upsertStoredCodes(stored, driveId)
            self._periodicMode03LastAt = currentTime
            return result

    # ------------------------------------------------------------------
    # US-292 -- Mode 07 trigger at drive_end
    # ------------------------------------------------------------------

    def logDriveEndDtcs(
        self,
        *,
        driveId: int | None,
        connection: ObdConnectionLike,
    ) -> DriveEndResult:
        """Run Mode 07 (pending DTCs only) and persist results.

        Spool 2026-05-06 ask: 'Mode 07 query at drive_end (pending codes
        are the leading indicator -- they fire before MIL)'.  Mode 03
        is intentionally NOT re-queried here -- :meth:`maybePeriodicMode03`
        already ran at the most-recent 30s boundary, so the drive-end
        snapshot needs only the Mode-07-pending delta.

        Codes already present for this drive get a fresh
        ``last_seen_timestamp`` via UPDATE; new codes INSERT.  Probe
        verdict is reported so the caller can cache 'Mode 07
        unsupported on this ECU' and skip subsequent calls (US-204
        2G-DSM contract preserved).

        Args:
            driveId: Same fallback rule as
                :meth:`logSessionStartDtcs` -- explicit value or
                :func:`getCurrentDriveId` fallback or NULL.
            connection: Live OBD connection.

        Returns:
            :class:`DriveEndResult` with pending count + probe verdict.

        Raises:
            DtcClientError: Re-raised if the connection is not open.
        """
        with self._markRetrievalActive():
            effectiveDriveId = driveId if driveId is not None else getCurrentDriveId()
            pending, probe = self._client.readPendingDtcs(connection)

            if not pending:
                if not probe.supported:
                    logger.info(
                        "Mode 07 unsupported at drive_end -- caching probe"
                    )
                return DriveEndResult(pendingCount=0, mode07Probe=probe)

            # Pending codes use the same (drive_id, code) upsert semantics
            # as MIL events -- a pending code that re-appears within the
            # same drive bumps last_seen rather than duplicating rows.
            with self._database.connect() as conn:
                for code in pending:
                    if self._existingRowId(conn, effectiveDriveId, code.code) is not None:
                        self._updateLastSeen(conn, effectiveDriveId, code.code)
                    else:
                        self._insertOne(conn, code, effectiveDriveId)

            return DriveEndResult(pendingCount=len(pending), mode07Probe=probe)

    # ------------------------------------------------------------------
    # Internal SQL helpers
    # ------------------------------------------------------------------

    def _upsertStoredCodes(
        self,
        codes: list[DiagnosticCode],
        driveId: int | None,
    ) -> MilEventResult:
        """Apply (drive_id, code) upsert semantics to a Mode 03 result list.

        Shared by :meth:`logMilEventDtcs` and :meth:`maybePeriodicMode03`
        so the cadence path inherits the upsert contract verbatim.
        """
        inserted = 0
        updated = 0
        with self._database.connect() as conn:
            for code in codes:
                if self._existingRowId(conn, driveId, code.code) is not None:
                    self._updateLastSeen(conn, driveId, code.code)
                    updated += 1
                else:
                    self._insertOne(conn, code, driveId)
                    inserted += 1
        return MilEventResult(inserted=inserted, updated=updated)

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
