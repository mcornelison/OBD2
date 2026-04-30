################################################################################
# File Name: drive_summary.py
# Purpose/Description: Per-drive metadata capture table (ambient IAT,
#                      starting battery, barometric pressure) written by
#                      DriveDetector at _startDrive.  Spool Data v2
#                      Story 4 (US-206).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-206) | Initial -- drive_summary schema + recorder.
# 2026-04-23    | Rex (US-228) | Add backfillFromSnapshot -- COALESCE-semantics
#                               UPDATE for the cold-start NULL bug (Drive 3
#                               shipped drive_summary with all three sensor
#                               columns NULL because drive_start fired before
#                               first IAT / BATT / BARO reading).
# 2026-04-29    | Rex (US-236) | Switch captureDriveStart from Option (b)
#                               INSERT-immediately to Option (a) defer-INSERT.
#                               Sprint 18's UPDATE-backfill empirically failed
#                               on drives 3, 4, 5 (every row all-NULL).  New
#                               semantics: empty/IAT-only-on-warm-restart
#                               snapshot returns deferred=True without
#                               INSERTing; the row only appears when the first
#                               IAT/BATTERY_V/BARO arrives, OR when the
#                               detector calls forceInsert=True at the 60s
#                               timeout (writes whatever's available + tags
#                               result.reason='no_readings_within_timeout' for
#                               operator visibility).  Existing UPSERT replay
#                               + warm-restart NULL-ambient invariants
#                               preserved.  backfillFromSnapshot unchanged.
# ================================================================================
################################################################################

"""Drive-scoped metadata capture (US-206 / Spool Data v2 Story 4).

At the moment the Pi collector promotes a drive from cranking to
``RUNNING``, three values are captured once and stamped against the
drive:

* ``ambient_temp_at_start_c`` -- IAT (PID 0x0F) at drive-start.
  Valid proxy for ambient ONLY on cold starts -- an engine that was
  already warm when the drive began leaves the intake heat-soaked and
  the reading is worthless.  The recorder takes ``fromState`` as an
  input and writes NULL when the transition wasn't from UNKNOWN /
  KEY_OFF (warm restart).
* ``starting_battery_v`` -- ELM_VOLTAGE (ATRV).  Captured pre-cranking
  loads; the cranking current drop is what Spool wants to see
  contextualised against.
* ``barometric_kpa_at_start`` -- PID 0x33.  Doesn't change during a
  drive so one snapshot is enough.

Storage is a single ``drive_summary`` row per drive keyed by
``drive_id`` (the PK).  Subsequent calls with the same ``drive_id``
(idempotent replay, recovery after a partial write) UPSERT rather
than INSERT a second row.

US-236 defer-INSERT semantics (Sprint 19, replaces Sprint 18 US-228):

The first :meth:`SummaryRecorder.captureDriveStart` call for a new
drive_id does NOT INSERT immediately.  Instead, the call returns
``deferred=True`` whenever the post-cold-start-rule payload would be
all-NULL (the production timing that produced Drive 3 / 4 / 5's
empty rows).  The detector keeps re-calling on each
``processValue`` tick; the FIRST call where IAT / BATTERY_V /
BAROMETRIC_KPA actually appears in the snapshot triggers the INSERT.
At the 60s deadline the detector flips ``forceInsert=True`` and the
call writes whatever's available (possibly all-NULL) tagged with
``reason='no_readings_within_timeout'`` on the result for operator
visibility.  The schema is doNotTouch, so ``reason`` is NOT
persisted in the row -- it lives in logs + result objects only.

Cold-start rule (Invariant #2 -- do NOT fabricate):

* ``fromState`` IN (UNKNOWN, KEY_OFF) -> ambient captured from IAT
* ``fromState`` is RUNNING or None      -> ambient NULL

This module is deliberately tiny: no new PID polls, no direct ECU
access, and no Mode 01 decoders.  The caller hands in a pre-built
``snapshot`` dict carrying whatever the collector already cached for
the drive-start tick.

Sync shape (US-194 delta):

* ``drive_id`` is the Pi-side PK -- monotonic, minted by
  :mod:`src.pi.obdii.drive_id`.  ``sync_log.PK_COLUMN['drive_summary']
  = 'drive_id'`` feeds the delta cursor, and the sync client renames
  ``drive_id`` -> ``id`` on the way out so the server's existing
  ``source_id`` mapping stays untouched.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Protocol

from .drive_id import getCurrentDriveId
from .engine_state import EngineState

__all__ = [
    'AMBIENT_COLD_START_STATES',
    'DRIVE_SUMMARY_TABLE',
    'DatabaseLike',
    'DriveSummary',
    'SCHEMA_DRIVE_SUMMARY',
    'SummaryBackfillResult',
    'SummaryRecorder',
    'SummaryCaptureResult',
    'buildSummaryFromSnapshot',
    'ensureDriveSummaryTable',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================


DRIVE_SUMMARY_TABLE: str = 'drive_summary'


# Engine-state transitions that justify using the current IAT as an
# ambient proxy.  UNKNOWN = first drive since Pi boot (engine has been
# off at least as long as the Pi has been up, and probably longer).
# KEY_OFF = clean shutdown of a previous drive with the 30s debounce
# satisfied -- the intake has had at least that long to equilibrate
# (though Spool notes that heat-soak can still dominate -- the caller
# owns the confidence flag).
AMBIENT_COLD_START_STATES: frozenset[EngineState] = frozenset(
    {EngineState.UNKNOWN, EngineState.KEY_OFF}
)


# Parameter-name keys used against the ``snapshot`` dict.  Align with
# :mod:`src.pi.obdii.decoders` PARAMETER_DECODERS keys + the legacy
# name for IAT (still polled by the original tier-1 set).
_PARAM_INTAKE_TEMP: str = 'INTAKE_TEMP'
_PARAM_BATTERY_V: str = 'BATTERY_V'
_PARAM_BAROMETRIC_KPA: str = 'BAROMETRIC_KPA'


# ================================================================================
# DDL
# ================================================================================

SCHEMA_DRIVE_SUMMARY: str = """
CREATE TABLE IF NOT EXISTS drive_summary (
    -- Pi-local drive id, minted by src.pi.obdii.drive_id.nextDriveId.
    -- Also the natural sync cursor -- sync_log.PK_COLUMN maps
    -- 'drive_summary' -> 'drive_id' and the sync client renames
    -- drive_id -> id on the outbound payload (US-194 _renamePkToId).
    drive_id INTEGER PRIMARY KEY,

    -- Drive-start wall time, canonical ISO-8601 UTC (US-202 / TD-027).
    drive_start_timestamp DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    -- Ambient temperature proxy -- IAT at cold-start only.  NULL on
    -- warm restarts is semantically important: Spool analytics treat
    -- NULL as "ambient unknown" and skip the IAT-caution interpretation
    -- that depends on it.
    ambient_temp_at_start_c REAL,

    -- Battery voltage via ELM_VOLTAGE (ATRV) at key-on, pre-cranking.
    -- Nullable because the ELM may return a null response on the
    -- drive-start tick (rare -- ATRV is adapter-level and doesn't
    -- depend on ECU connectivity).
    starting_battery_v REAL,

    -- Barometric pressure PID 0x33.  Pinned once at drive-start since
    -- it doesn't change mid-drive.  Nullable in case the ECU doesn't
    -- respond on the first tick.
    barometric_kpa_at_start REAL,

    -- US-195 origin tag.  Analytics filter real-vs-sim off this.
    data_source TEXT NOT NULL DEFAULT 'real'
        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
);
"""


# ================================================================================
# Database protocol
# ================================================================================


class DatabaseLike(Protocol):
    """Structural interface satisfied by :class:`ObdDatabase` + test doubles."""

    def connect(self) -> Any: ...  # context manager yielding sqlite3.Connection


# ================================================================================
# Dataclasses
# ================================================================================


@dataclass(frozen=True)
class DriveSummary:
    """In-memory view of a drive_summary row.

    Attributes mirror the DB columns.  Immutable to make handoff across
    the captureDriveStart -> upsert path obvious (no one mutates the
    row mid-write).
    """

    driveId: int
    driveStartTimestamp: str | None = None
    ambientTempAtStartC: float | None = None
    startingBatteryV: float | None = None
    barometricKpaAtStart: float | None = None
    dataSource: str = 'real'


@dataclass(frozen=True)
class SummaryCaptureResult:
    """Per-call summary returned from :meth:`SummaryRecorder.captureDriveStart`.

    Attributes:
        driveId: The drive_id that was written (or would have been -- the
            field is set even on a deferred no-op so the caller always
            knows which drive the call referred to).
        inserted: True iff this call performed an INSERT (the row was
            missing before this call).  False on UPSERT-against-existing-
            row (post-INSERT replay path) AND on deferred no-op
            (US-236 -- the row deliberately doesn't exist yet because
            no relevant reading has arrived).  Disambiguate via
            :attr:`deferred`.
        coldStart: True when ``fromState`` matched
            :data:`AMBIENT_COLD_START_STATES` and ambient was captured
            from the snapshot.  False when warm-restart rule zeroed out
            the ambient.
        summary: The :class:`DriveSummary` that was written (post-cold-
            start rule -- ambient is already NULL for warm restarts).
            On deferred no-op, this is the summary that WOULD have been
            written had the call inserted.
        reason: Operator-visible reason string, populated only on the
            forced-INSERT timeout path (US-236).  Default is ``None``.
            Canonical value: ``'no_readings_within_timeout'``.  Logged at
            INFO level alongside the INSERT and surfaced to the detector
            (which can route it into structured logs / monitoring).  Not
            persisted in the drive_summary row (the table schema is
            doNotTouch under the US-236 scope fence).
        deferred: True iff this call was a defer-INSERT no-op (US-236):
            row missing AND the post-cold-start-rule payload would have
            been all-NULL AND ``forceInsert=False``.  False on every
            INSERT (forced or natural) and on every UPSERT.  The detector
            uses this signal to know whether to keep ticking the
            defer-INSERT loop or transition to the backfill-UPDATE phase.
    """

    driveId: int
    inserted: bool
    coldStart: bool
    summary: DriveSummary
    reason: str | None = None
    deferred: bool = False


@dataclass(frozen=True)
class SummaryBackfillResult:
    """Per-call result from :meth:`SummaryRecorder.backfillFromSnapshot`.

    US-228 fix: ``drive_start`` fires before the first IAT / BATT / BARO
    arrives, so the INSERT writes NULLs.  The backfill tick fills those
    NULL columns as readings become available -- without ever clobbering
    an already-set value.

    Attributes:
        driveId: The drive_id targeted.
        filled: Set of short column aliases newly populated by THIS
            call.  Values are drawn from the fixed set
            ``{'ambient', 'battery', 'baro'}``.  Empty set on a no-op
            (missing row, nothing to fill, or backfill target already
            complete).
        complete: True when every applicable sensor column is non-NULL
            after this call.  For a cold start, all three must be non-
            NULL.  For a warm restart, ambient is by design NULL, so
            complete is satisfied when battery + baro are non-NULL.
            The DriveDetector treats ``complete=True`` as the early-exit
            signal -- no further backfill ticks needed.
    """

    driveId: int
    filled: frozenset[str]
    complete: bool


# ================================================================================
# Snapshot -> DriveSummary helper (pure, no DB)
# ================================================================================


def buildSummaryFromSnapshot(
    *,
    driveId: int,
    snapshot: dict[str, Any] | None,
    fromState: EngineState | str | None,
    dataSource: str = 'real',
) -> DriveSummary:
    """Turn a reading snapshot into a :class:`DriveSummary`.

    Applies the cold-start ambient rule (Invariant #2) here so the
    recorder + tests share one authoritative implementation.

    Args:
        driveId: Minted drive_id.
        snapshot: Dict of parameter_name -> latest numeric reading.
            Missing keys are tolerated and produce NULL columns.
            ``None`` treated as empty.
        fromState: Engine state machine's previous state.  Only
            UNKNOWN / KEY_OFF qualify for cold-start ambient.  Accepts
            :class:`EngineState` or its string form, or ``None``
            (treated as a warm restart -- conservative).
        dataSource: US-195 origin tag; defaults to ``'real'``.

    Returns:
        :class:`DriveSummary` populated with the 3 metadata values
        (subject to the cold-start rule for ambient).
    """
    snap = snapshot or {}

    coldStart = _isColdStart(fromState)
    ambient: float | None
    if coldStart:
        ambient = _readFloat(snap, _PARAM_INTAKE_TEMP)
    else:
        ambient = None

    return DriveSummary(
        driveId=driveId,
        driveStartTimestamp=None,  # DB default supplies canonical ISO UTC
        ambientTempAtStartC=ambient,
        startingBatteryV=_readFloat(snap, _PARAM_BATTERY_V),
        barometricKpaAtStart=_readFloat(snap, _PARAM_BAROMETRIC_KPA),
        dataSource=dataSource,
    )


def _isColdStart(fromState: EngineState | str | None) -> bool:
    """Return True when ``fromState`` qualifies for cold-start ambient capture."""
    if fromState is None:
        return False
    if isinstance(fromState, EngineState):
        return fromState in AMBIENT_COLD_START_STATES
    # String form (value from StrEnum or human-entered) -- normalize.
    try:
        coerced = EngineState(str(fromState).lower())
    except ValueError:
        return False
    return coerced in AMBIENT_COLD_START_STATES


def _readFloat(snap: dict[str, Any], key: str) -> float | None:
    """Best-effort float coercion; None / NaN-ish -> None."""
    if key not in snap:
        return None
    raw = snap[key]
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # Reject NaN explicitly -- downstream analytics can't tell it apart
    # from a real zero otherwise.
    if value != value:  # noqa: PLR0124 -- NaN check
        return None
    return value


def _hasRelevantPayload(summary: DriveSummary) -> bool:
    """True iff at least one of the 3 metadata columns is non-NULL.

    Used by :meth:`SummaryRecorder.captureDriveStart` to decide
    whether a missing-row case warrants an INSERT (US-236 defer-INSERT
    discriminator).  Operates on the post-cold-start-rule payload, so
    a warm restart with IAT-only is correctly treated as no-payload
    (the IAT gets filtered out in :func:`buildSummaryFromSnapshot`).
    """
    return (
        summary.ambientTempAtStartC is not None
        or summary.startingBatteryV is not None
        or summary.barometricKpaAtStart is not None
    )


# ================================================================================
# Migration helper
# ================================================================================


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


def ensureDriveSummaryTable(conn: sqlite3.Connection) -> bool:
    """Create the ``drive_summary`` table if missing.

    Idempotent -- returns ``False`` if the table already existed.
    Always re-issues the CREATE TABLE IF NOT EXISTS, which is a no-op
    on a live table.  Caller owns commit.
    """
    created = not _tableExists(conn, DRIVE_SUMMARY_TABLE)
    conn.execute(SCHEMA_DRIVE_SUMMARY)
    return created


# ================================================================================
# SummaryRecorder
# ================================================================================


class SummaryRecorder:
    """Persists drive-start metadata into the ``drive_summary`` table.

    Stateless aside from the injected database handle -- each
    :meth:`captureDriveStart` call opens its own connection via the
    protocol's ``connect()`` context manager.

    Designed to be called from :meth:`DriveDetector._startDrive` with
    the freshly-minted drive_id + a read-only snapshot of the latest
    cached readings from :class:`ObdDataLogger.getLatestReadings`.
    """

    def __init__(self, *, database: DatabaseLike) -> None:
        self._database = database

    def captureDriveStart(
        self,
        *,
        driveId: int | None = None,
        snapshot: dict[str, Any] | None = None,
        fromState: EngineState | str | None = None,
        dataSource: str = 'real',
        forceInsert: bool = False,
        reason: str | None = None,
    ) -> SummaryCaptureResult:
        """Defer-INSERT-aware writer for one drive_summary row (US-236).

        **Option (a) defer-INSERT semantics** (Sprint 19 fix for
        Sprint 18 US-228's empirically dead UPDATE-backfill):

        * **Row missing** + post-cold-start-rule payload is all-NULL
          + ``forceInsert=False`` -> **deferred no-op**.  No DB
          write.  ``inserted=False, deferred=True``.  The detector
          keeps ticking until the first IAT / BATTERY_V / BARO
          arrives or the 60s deadline triggers ``forceInsert=True``.
        * **Row missing** + post-cold-start-rule payload has at least
          one non-NULL field -> **INSERT** with available data.
          ``inserted=True, deferred=False``.
        * **Row missing** + ``forceInsert=True`` -> **INSERT** with
          whatever's in the snapshot (may be all-NULL).  ``reason``
          (if provided) propagates onto the result for operator
          visibility but is NOT persisted in the row -- the table
          schema is doNotTouch under the US-236 scope fence.
          ``inserted=True, deferred=False``.
        * **Row exists** -> **UPDATE** with the post-cold-start
          payload (existing UPSERT replay path -- preserved for
          backwards compatibility with US-206 idempotency tests).
          ``inserted=False, deferred=False``.

        The cold-start rule runs BEFORE the write decision so the
        stored ambient already honors Invariant #2 (warm restart =
        ambient NULL forever).  A warm restart with IAT-only in the
        snapshot is therefore a deferred no-op: the IAT gets filtered
        out, no other field is present, INSERT defers.

        Args:
            driveId: Minted drive_id.  Falls back to
                :func:`getCurrentDriveId` so a caller that has already
                published the id on the process context doesn't need
                to re-thread it.
            snapshot: Parameter-name -> numeric value dict.
                ``None`` or empty produces deferred no-op (or forced
                NULL row when ``forceInsert=True``).
            fromState: Engine state machine's previous state.  See
                :func:`buildSummaryFromSnapshot`.
            dataSource: US-195 origin tag.
            forceInsert: When True, INSERT even on an all-NULL payload.
                The detector sets this at the 60s deadline.  No-op
                when the row already exists (UPDATE path runs as
                normal).  Default False.
            reason: Operator-visible reason string surfaced on
                :attr:`SummaryCaptureResult.reason`.  Canonical value
                on the timeout path: ``'no_readings_within_timeout'``.
                Default ``None``.

        Returns:
            :class:`SummaryCaptureResult`.

        Raises:
            ValueError: If ``driveId`` and :func:`getCurrentDriveId`
                both return ``None`` -- a drive_summary row with
                drive_id=NULL would violate PRIMARY KEY NOT NULL.
        """
        effectiveDriveId = driveId if driveId is not None else getCurrentDriveId()
        if effectiveDriveId is None:
            raise ValueError(
                "captureDriveStart requires a drive_id (caller None + "
                "getCurrentDriveId() None)"
            )

        summary = buildSummaryFromSnapshot(
            driveId=effectiveDriveId,
            snapshot=snapshot,
            fromState=fromState,
            dataSource=dataSource,
        )
        coldStart = summary.ambientTempAtStartC is not None or _isColdStart(
            fromState
        )

        with self._database.connect() as conn:
            existing = conn.execute(
                f"SELECT 1 FROM {DRIVE_SUMMARY_TABLE} WHERE drive_id = ?",
                (int(summary.driveId),),
            ).fetchone()

            if existing is None and not forceInsert and not _hasRelevantPayload(
                summary
            ):
                # Defer-INSERT no-op: nothing to write yet.  Caller
                # (detector) keeps the per-drive deferred state armed
                # and re-calls on each tick until a relevant reading
                # arrives OR forceInsert=True flips at the deadline.
                logger.debug(
                    "drive_summary deferred (no relevant payload) | "
                    "drive_id=%s | cold_start=%s",
                    summary.driveId,
                    coldStart,
                )
                return SummaryCaptureResult(
                    driveId=summary.driveId,
                    inserted=False,
                    coldStart=coldStart,
                    summary=summary,
                    reason=reason,
                    deferred=True,
                )

            if existing is None:
                self._insertNew(conn, summary)
                logger.info(
                    "drive_summary INSERT | drive_id=%s | cold_start=%s | "
                    "ambient=%s | battery=%s | baro=%s | reason=%s",
                    summary.driveId,
                    coldStart,
                    summary.ambientTempAtStartC,
                    summary.startingBatteryV,
                    summary.barometricKpaAtStart,
                    reason,
                )
                return SummaryCaptureResult(
                    driveId=summary.driveId,
                    inserted=True,
                    coldStart=coldStart,
                    summary=summary,
                    reason=reason,
                    deferred=False,
                )

            self._updateExisting(conn, summary)
            logger.info(
                "drive_summary UPSERT | drive_id=%s | cold_start=%s | "
                "ambient=%s | battery=%s | baro=%s",
                summary.driveId,
                coldStart,
                summary.ambientTempAtStartC,
                summary.startingBatteryV,
                summary.barometricKpaAtStart,
            )
            return SummaryCaptureResult(
                driveId=summary.driveId,
                inserted=False,
                coldStart=coldStart,
                summary=summary,
                reason=reason,
                deferred=False,
            )

    def _insertNew(
        self,
        conn: sqlite3.Connection,
        summary: DriveSummary,
    ) -> None:
        """INSERT a fresh drive_summary row.

        The DB-side DEFAULT on drive_start_timestamp is honored by
        omitting the column from the INSERT column list -- writers
        never pass a Python-side timestamp for this column so the
        canonical ISO-8601 UTC stamp is always authoritative (US-202).
        """
        conn.execute(
            f"INSERT INTO {DRIVE_SUMMARY_TABLE} "
            "(drive_id, ambient_temp_at_start_c, starting_battery_v, "
            " barometric_kpa_at_start, data_source) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                int(summary.driveId),
                summary.ambientTempAtStartC,
                summary.startingBatteryV,
                summary.barometricKpaAtStart,
                summary.dataSource,
            ),
        )

    def _updateExisting(
        self,
        conn: sqlite3.Connection,
        summary: DriveSummary,
    ) -> None:
        """UPDATE an existing drive_summary row (UPSERT replay path).

        Clobbers the existing values with the post-cold-start-rule
        payload from ``summary``.  This preserves the US-206 replay
        semantics (re-calling captureDriveStart with the same drive_id
        is idempotent against the same snapshot, and the latest call
        wins on a divergent snapshot).  Distinct from
        :meth:`backfillFromSnapshot`'s never-clobber-non-NULL UPDATE.
        """
        conn.execute(
            f"UPDATE {DRIVE_SUMMARY_TABLE} SET "
            "ambient_temp_at_start_c = ?, "
            "starting_battery_v = ?, "
            "barometric_kpa_at_start = ?, "
            "data_source = ? "
            "WHERE drive_id = ?",
            (
                summary.ambientTempAtStartC,
                summary.startingBatteryV,
                summary.barometricKpaAtStart,
                summary.dataSource,
                int(summary.driveId),
            ),
        )

    # --------------------------------------------------------------
    # US-228 backfill
    # --------------------------------------------------------------

    def backfillFromSnapshot(
        self,
        *,
        driveId: int,
        snapshot: dict[str, Any] | None,
        fromState: EngineState | str | None,
    ) -> SummaryBackfillResult:
        """UPDATE NULL sensor columns in an existing drive_summary row.

        US-228 fix for the Drive-3 cold-start NULL bug.  When
        ``_startDrive`` fires before the first IAT / BATTERY_V /
        BAROMETRIC_KPA reading is cached, the initial INSERT writes
        NULLs.  As readings arrive on subsequent ticks, the detector
        calls this method to fill the NULL columns -- one column at a
        time if that's how the ECU responds -- without clobbering any
        value that's already been captured (the "never overwrite
        non-NULL with NULL" invariant).

        Warm-restart semantics are inherited from
        :func:`buildSummaryFromSnapshot`: when ``fromState`` is not in
        :data:`AMBIENT_COLD_START_STATES`, the candidate ``ambient`` is
        ``None`` and the ambient column will never be written, even if
        IAT arrives later.  ``complete=True`` on a warm restart
        requires only battery + baro to be non-NULL.

        Args:
            driveId: The drive whose row is being backfilled.  Must
                match an existing row (from a prior
                :meth:`captureDriveStart` INSERT) -- a missing row is a
                no-op (``filled=empty, complete=False``) because
                writing a partial row without a drive-start timestamp
                violates the invariant "every drive has exactly one
                drive_summary row written by captureDriveStart".
            snapshot: Parameter-name -> numeric value dict.  Missing
                keys and ``None`` values are tolerated (they just don't
                fill the corresponding column this tick).
            fromState: Same rule as :meth:`captureDriveStart`.  Used to
                decide whether IAT qualifies as ambient.

        Returns:
            :class:`SummaryBackfillResult` describing which columns
            were filled this call + whether the row is now complete
            (signals early-exit to the detector's backfill loop).
        """
        candidate = buildSummaryFromSnapshot(
            driveId=driveId,
            snapshot=snapshot,
            fromState=fromState,
        )
        coldStart = _isColdStart(fromState)

        with self._database.connect() as conn:
            row = conn.execute(
                f"SELECT ambient_temp_at_start_c, starting_battery_v, "
                f"barometric_kpa_at_start FROM {DRIVE_SUMMARY_TABLE} "
                f"WHERE drive_id = ?",
                (int(driveId),),
            ).fetchone()
            if row is None:
                # No INSERT has happened yet -- this method only backfills,
                # it does not create the row.  Detector calls
                # captureDriveStart first.
                return SummaryBackfillResult(
                    driveId=int(driveId),
                    filled=frozenset(),
                    complete=False,
                )

            storedAmbient, storedBattery, storedBaro = row[0], row[1], row[2]
            filled: set[str] = set()

            newAmbient = storedAmbient
            if storedAmbient is None and candidate.ambientTempAtStartC is not None:
                newAmbient = candidate.ambientTempAtStartC
                filled.add('ambient')

            newBattery = storedBattery
            if storedBattery is None and candidate.startingBatteryV is not None:
                newBattery = candidate.startingBatteryV
                filled.add('battery')

            newBaro = storedBaro
            if storedBaro is None and candidate.barometricKpaAtStart is not None:
                newBaro = candidate.barometricKpaAtStart
                filled.add('baro')

            if filled:
                conn.execute(
                    f"UPDATE {DRIVE_SUMMARY_TABLE} SET "
                    "ambient_temp_at_start_c = ?, "
                    "starting_battery_v = ?, "
                    "barometric_kpa_at_start = ? "
                    "WHERE drive_id = ?",
                    (newAmbient, newBattery, newBaro, int(driveId)),
                )

        # ambient is "effectively complete" when either it's non-NULL
        # OR the cold-start rule says it's not applicable (warm restart).
        ambientComplete = newAmbient is not None or not coldStart
        complete = (
            ambientComplete
            and newBattery is not None
            and newBaro is not None
        )

        if filled:
            logger.info(
                "drive_summary backfill | drive_id=%s | filled=%s | "
                "complete=%s | ambient=%s | battery=%s | baro=%s",
                driveId,
                sorted(filled),
                complete,
                newAmbient,
                newBattery,
                newBaro,
            )

        return SummaryBackfillResult(
            driveId=int(driveId),
            filled=frozenset(filled),
            complete=complete,
        )
