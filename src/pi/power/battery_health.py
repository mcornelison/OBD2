################################################################################
# File Name: battery_health.py
# Purpose/Description: battery_health_log table DDL + idempotent migration
#                      helper + BatteryHealthRecorder (start/close a drain
#                      event row).  Spool Session 6 Story 3 design -- one row
#                      per UPS drain event for monthly drain-test cadence
#                      (CIO directive 3).  US-216 (Power-Down Orchestrator)
#                      will consume this table when it wires the staged
#                      shutdown ladder; US-217 lands the schema + writer
#                      surface first so CIO can manually record drain tests
#                      immediately.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-217) | Initial -- battery_health_log schema + recorder.
# 2026-05-07    | Rex (US-289) | Spool Sprint 26 Story 6: column rename to
#                               start_vcell_v / end_vcell_v.  The legacy
#                               start_soc / end_soc columns hold VCELL volts
#                               (3.4-4.2V) while the schema comment claimed
#                               SOC % (0..100) -- a four-sprint-old documentation
#                               lie.  Added new vcell_v columns + idempotent
#                               ensureBatteryHealthLogVcellColumns migration
#                               helper.  Recorder writes BOTH old and new
#                               columns during the deprecation phase
#                               (stopCondition[1]: existing analytics readers
#                               must not break mid-rename).  Old columns are
#                               kept with a deprecated comment; a future sprint
#                               drops them after backfill.
# ================================================================================
################################################################################

"""Battery drain-event tracking (US-217 / Spool Session 6 Story 3).

One row per UPS drain event.  A drain event is the window from when the
Pi first notices wall power was lost (WARNING stage at 30% SOC in US-216,
or CIO manually initiating a drill) to when the Pi either recovers power
or reaches the TRIGGER stage and initiates ``systemctl poweroff``.

The row is opened on :meth:`BatteryHealthRecorder.startDrainEvent` with
the starting SOC and the ``load_class`` tag (production / test / sim).
It is closed on :meth:`BatteryHealthRecorder.endDrainEvent` with the
ending SOC + optional ambient temperature.  ``runtime_seconds`` is
computed at close time from the two canonical ISO-8601 UTC timestamps.

Schema shape (frozen by Spool Session 6 grounding refs; US-289 column rename):

* ``drain_event_id``      INTEGER PK AUTOINCREMENT -- monotonic event id
* ``start_timestamp``     TEXT NOT NULL (canonical ISO-8601 UTC default)
* ``end_timestamp``       TEXT NULL (written at close)
* ``start_vcell_v``       REAL NULL -- LiPo cell volts at event open (US-289)
* ``end_vcell_v``         REAL NULL -- LiPo cell volts at close (US-289)
* ``start_soc``           REAL NOT NULL -- DEPRECATED (US-289): named "soc"
                          but holds VCELL volts (3.4-4.2V).  Kept during the
                          rename deprecation phase; remove in a future sprint
                          after analytics consumers migrate to start_vcell_v.
* ``end_soc``             REAL NULL -- DEPRECATED (US-289), see start_soc.
* ``runtime_seconds``     INTEGER NULL (computed at close)
* ``ambient_temp_c``      REAL NULL (optional)
* ``load_class``          TEXT NOT NULL DEFAULT 'production'
                          CHECK IN ('production','test','sim')
* ``notes``               TEXT NULL
* ``data_source``         TEXT NOT NULL DEFAULT 'real'
                          CHECK IN ('real','replay','physics_sim','fixture')

US-289 deprecation contract (stopCondition[1]): the recorder writes the
same VCELL value to BOTH the new ``*_vcell_v`` columns AND the legacy
``*_soc`` columns so existing analytics consumers reading the old columns
keep working through the rename window.  A future sprint drops the
legacy columns after backfill + reader migration.

Invariants:

* ``start_soc`` + ``start_timestamp`` are authoritative once written; the
  UPDATE path in :meth:`BatteryHealthRecorder.endDrainEvent` only touches
  the end-of-event columns (end_timestamp, end_soc, runtime_seconds,
  ambient_temp_c).
* ``drain_event_id`` is auto-incremented + monotonic (per-event, not a
  singleton like ``drive_counter``).
* Close-once semantic: calling ``endDrainEvent`` a second time on an
  already-closed row is a no-op -- the original end_timestamp / end_soc
  are preserved (first-close-wins).
* Timestamps route through :func:`src.common.time.helper.utcIsoNow` so the
  canonical ISO-8601 UTC format (TD-027 / US-202) is enforced.

Sync shape (US-194 delta):

* ``drain_event_id`` is the Pi-side PK; ``sync_log.PK_COLUMN
  ['battery_health_log'] = 'drain_event_id'`` feeds the delta cursor, and
  the sync client renames ``drain_event_id`` -> ``id`` on the outbound
  payload so the server's ``source_id`` mapping stays uniform with the
  other capture tables.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from src.common.time.helper import CANONICAL_ISO_FORMAT, utcIsoNow

__all__ = [
    'BATTERY_HEALTH_LOG_TABLE',
    'DatabaseLike',
    'BatteryHealthRecorder',
    'DrainEventCloseResult',
    'LOAD_CLASS_DEFAULT',
    'LOAD_CLASS_VALUES',
    'SCHEMA_BATTERY_HEALTH_LOG',
    'INDEX_BATTERY_HEALTH_LOG_START',
    'ensureBatteryHealthLogTable',
    'ensureBatteryHealthLogVcellColumns',
]

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

BATTERY_HEALTH_LOG_TABLE: str = 'battery_health_log'

# load_class enum.  'production' is the real-world drain (wall power lost,
# Pi runs to trigger); 'test' is CIO's scheduled monthly drill; 'sim' is
# developer / CI synthetic drain.  Mirrors Spool's Session 6 Story 3 +
# Marcus grooming alignment with CIO directive 3 cadence.
LOAD_CLASS_VALUES: tuple[str, ...] = ('production', 'test', 'sim')
LOAD_CLASS_DEFAULT: str = 'production'


# ================================================================================
# DDL
# ================================================================================

SCHEMA_BATTERY_HEALTH_LOG: str = """
CREATE TABLE IF NOT EXISTS battery_health_log (
    -- Monotonic event id.  Pi-side PK + sync delta cursor.
    drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Event-open wall time, canonical ISO-8601 UTC (US-202 / TD-027).
    -- DEFAULT means startDrainEvent can omit the column; explicit writers
    -- (tests, scripts/record_drain_test.py) may also pass a tz-aware
    -- datetime via toCanonicalIso(...).
    start_timestamp TEXT NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    -- Event-close wall time.  NULL until endDrainEvent lands.
    end_timestamp TEXT,

    -- DEPRECATED by US-289.  Despite the name + the original "0..100
    -- (MAX17048 integer % scale)" comment, this column actually stores
    -- LiPo cell VCELL volts (3.4-4.2V) -- the recorder takes whatever
    -- the caller passes as ``startSoc`` and the orchestrator's caller
    -- (PowerDownOrchestrator) passes a VCELL value.  start_vcell_v is
    -- the renamed, correctly-named replacement; both columns receive
    -- the same value during the deprecation window.  Drop in a future
    -- sprint after analytics readers migrate.
    start_soc REAL NOT NULL,

    -- DEPRECATED by US-289 (see start_soc).  end_vcell_v is the renamed
    -- replacement.  NULL until endDrainEvent lands.
    end_soc REAL,

    -- LiPo cell volts at event open (US-289 rename).  REAL nullable
    -- because pre-US-289 rows do not carry this column; the migration
    -- helper backfills neither legacy nor new column for old rows.
    -- Post-US-289 rows always have this populated by the recorder.
    start_vcell_v REAL,

    -- LiPo cell volts at event close (US-289 rename).  NULL until
    -- endDrainEvent lands.  Mirrors end_soc value during deprecation.
    end_vcell_v REAL,

    -- Wall-clock duration between start_timestamp and end_timestamp.
    -- Computed at close so queries don't have to strftime-parse every
    -- row.  NULL when end_timestamp is NULL.
    runtime_seconds INTEGER,

    -- Optional ambient temperature (Celsius) captured at close.  CIO
    -- may not have a thermometer handy on every drill -- this is
    -- best-effort context for cold-weather vs warm-weather drain
    -- comparisons.  NULL is valid.
    ambient_temp_c REAL,

    -- Load class at drain time.  'production' = real drain (wall
    -- power lost while Pi was running normally); 'test' = CIO's
    -- scheduled drill (battery aging baseline); 'sim' = developer
    -- / CI synthetic drain (never touches real hardware).  Analytics
    -- filter 'production' + 'test' for runtime-trend baselines.
    load_class TEXT NOT NULL DEFAULT 'production'
        CHECK (load_class IN ('production','test','sim')),

    -- Free-form notes (drill observations, hardware swaps, weather).
    notes TEXT,

    -- US-195 origin tag.  Drain events written by real hardware =
    -- 'real'; test-fixture rows in unit tests may pass 'fixture'.
    data_source TEXT NOT NULL DEFAULT 'real'
        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
);
"""

# Index on start_timestamp for time-range queries (e.g. "give me all
# drain events in April 2026").
INDEX_BATTERY_HEALTH_LOG_START: str = (
    "CREATE INDEX IF NOT EXISTS IX_battery_health_log_start "
    f"ON {BATTERY_HEALTH_LOG_TABLE}(start_timestamp)"
)


# ================================================================================
# Database protocol
# ================================================================================


class DatabaseLike(Protocol):
    """Structural interface satisfied by :class:`ObdDatabase` + test doubles."""

    def connect(self) -> Any: ...  # context manager yielding sqlite3.Connection


# ================================================================================
# Migration helper
# ================================================================================


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


def ensureBatteryHealthLogTable(conn: sqlite3.Connection) -> bool:
    """Create the ``battery_health_log`` table + index if missing.

    Idempotent: returns ``False`` if the table already existed.  Always
    re-issues the CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS
    (both no-ops on a live schema).  Caller owns commit.

    Args:
        conn: Open sqlite3 connection.

    Returns:
        True if ``battery_health_log`` was created on this call, False
        if it already existed.
    """
    created = not _tableExists(conn, BATTERY_HEALTH_LOG_TABLE)
    conn.execute(SCHEMA_BATTERY_HEALTH_LOG)
    conn.execute(INDEX_BATTERY_HEALTH_LOG_START)
    return created


def ensureBatteryHealthLogVcellColumns(conn: sqlite3.Connection) -> bool:
    """Add ``start_vcell_v`` + ``end_vcell_v`` columns if missing (US-289).

    Idempotent: PRAGMA table_info probe before each ALTER.  Both new
    columns are nullable so legacy rows (pre-US-289 drains carrying
    only start_soc / end_soc) remain valid; the migration does not
    backfill -- a future sprint may run a one-shot UPDATE to copy
    start_soc -> start_vcell_v on closed legacy rows once analytics
    consumers are confirmed migrated.

    Mirrors the :func:`src.pi.power.power_db.ensurePowerLogVcellColumn`
    pattern (US-252): table-exists probe, column-presence probe, ALTER
    only when missing, caller owns commit semantics.

    Args:
        conn: Open sqlite3 connection.

    Returns:
        True if at least one ALTER TABLE ran on this call.  False if
        both columns were already present, or if the table itself does
        not exist (caller should run ensureBatteryHealthLogTable first).
    """
    if not _tableExists(conn, BATTERY_HEALTH_LOG_TABLE):
        return False

    columns = {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({BATTERY_HEALTH_LOG_TABLE})"
        ).fetchall()
    }
    altered = False
    if 'start_vcell_v' not in columns:
        conn.execute(
            f"ALTER TABLE {BATTERY_HEALTH_LOG_TABLE} "
            "ADD COLUMN start_vcell_v REAL"
        )
        altered = True
    if 'end_vcell_v' not in columns:
        conn.execute(
            f"ALTER TABLE {BATTERY_HEALTH_LOG_TABLE} "
            "ADD COLUMN end_vcell_v REAL"
        )
        altered = True
    return altered


# ================================================================================
# Dataclasses
# ================================================================================


@dataclass(frozen=True)
class DrainEventCloseResult:
    """Per-call close result returned from :meth:`endDrainEvent`.

    Attributes:
        drainEventId: The row's ``drain_event_id``.
        closed: True if this call wrote end_timestamp / end_soc; False
            when the row was already closed (close-once semantic).
        endTimestamp: The end_timestamp actually stored on the row
            after this call (may be the pre-existing value on re-close).
        endSoc: The end_soc actually stored.
        runtimeSeconds: Computed runtime_seconds (may be the pre-
            existing value on re-close).
    """

    drainEventId: int
    closed: bool
    endTimestamp: str | None
    endSoc: float | None
    runtimeSeconds: int | None


# ================================================================================
# Recorder
# ================================================================================


class BatteryHealthRecorder:
    """Write drain-event rows into ``battery_health_log``.

    Stateless aside from the injected database handle -- each method call
    opens its own connection via the protocol's ``connect()`` context
    manager so the writer interleaves safely with other Pi-side writers.

    Intended callers:

    * :mod:`scripts.record_drain_test` -- CIO manual drill recorder.
    * US-216 staged shutdown orchestrator -- open event at WARNING stage,
      close at TRIGGER stage just before ``systemctl poweroff``.
    """

    def __init__(self, *, database: DatabaseLike) -> None:
        self._database = database

    def startDrainEvent(
        self,
        *,
        startSoc: float,
        loadClass: str = LOAD_CLASS_DEFAULT,
        notes: str | None = None,
        dataSource: str = 'real',
    ) -> int:
        """Open a new drain-event row.

        Args:
            startSoc: SOC % at event start.  Typically 100 for a full-
                battery drill or whatever SOC the Pi was at when wall
                power dropped in a production event.
            loadClass: One of :data:`LOAD_CLASS_VALUES`.  Defaults to
                ``'production'`` -- the real drain case.
            notes: Free-form text (drill context, weather, hardware
                notes).  Optional.
            dataSource: US-195 origin tag.  Defaults to ``'real'``.

        Returns:
            The auto-incremented ``drain_event_id`` for the new row.

        Raises:
            ValueError: If ``loadClass`` is not in
                :data:`LOAD_CLASS_VALUES`.
        """
        if loadClass not in LOAD_CLASS_VALUES:
            raise ValueError(
                f"loadClass {loadClass!r} is not valid; "
                f"expected one of {LOAD_CLASS_VALUES}"
            )

        # Route the start_timestamp through the canonical helper so the
        # returned drain_event_id has a matching wall-clock anchor that
        # endDrainEvent can subtract for runtime_seconds.  Relying on the
        # DB DEFAULT would require a post-INSERT SELECT to read it back.
        startTs = utcIsoNow()

        # US-289 deprecation phase: write the same VCELL value to BOTH
        # legacy start_soc (DEPRECATED) AND the new start_vcell_v column
        # so existing analytics consumers reading the old column keep
        # working through the rename window.  See module docstring +
        # stopCondition[1] for the deprecation contract.
        startVcell = float(startSoc)
        with self._database.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                "(start_timestamp, start_soc, start_vcell_v, "
                " load_class, notes, data_source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (startTs, startVcell, startVcell, loadClass, notes,
                 dataSource),
            )
            drainEventId = int(cursor.lastrowid or 0)

        logger.info(
            "drain event opened | id=%d | start_soc=%.1f | load_class=%s",
            drainEventId, float(startSoc), loadClass,
        )
        return drainEventId

    def endDrainEvent(
        self,
        *,
        drainEventId: int,
        endSoc: float,
        ambientTempC: float | None = None,
    ) -> DrainEventCloseResult:
        """Close a drain-event row.

        Idempotent close-once semantic: if the row already has
        ``end_timestamp`` populated (i.e. was previously closed), this
        call returns the stored values unchanged.  Rationale: a crashed
        orchestrator that retries on next boot must not overwrite the
        original close data.

        Args:
            drainEventId: The row's PK, returned by
                :meth:`startDrainEvent`.
            endSoc: SOC % at event end.
            ambientTempC: Optional ambient temperature (Celsius).

        Returns:
            :class:`DrainEventCloseResult` describing whether this call
            actually closed the row, plus the final stored values.

        Raises:
            ValueError: If no row exists with ``drainEventId``.
        """
        endTs = utcIsoNow()

        with self._database.connect() as conn:
            existing = conn.execute(
                f"SELECT start_timestamp, end_timestamp, end_soc, "
                f"       runtime_seconds "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (int(drainEventId),),
            ).fetchone()

            if existing is None:
                raise ValueError(
                    f"drain_event_id={drainEventId} not found -- call "
                    "startDrainEvent first or check the id."
                )

            startTsStored, endTsStored, endSocStored, runtimeStored = existing

            # Close-once: preserve the original close on re-call.
            if endTsStored is not None:
                return DrainEventCloseResult(
                    drainEventId=int(drainEventId),
                    closed=False,
                    endTimestamp=str(endTsStored),
                    endSoc=(
                        float(endSocStored)
                        if endSocStored is not None else None
                    ),
                    runtimeSeconds=(
                        int(runtimeStored)
                        if runtimeStored is not None else None
                    ),
                )

            runtimeSeconds = _computeRuntimeSeconds(
                str(startTsStored), endTs,
            )

            # US-289 deprecation phase: UPDATE both legacy end_soc
            # (DEPRECATED) and the new end_vcell_v column with the same
            # VCELL value.  See startDrainEvent for the deprecation
            # contract rationale.
            endVcell = float(endSoc)
            conn.execute(
                f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET "
                "end_timestamp = ?, "
                "end_soc = ?, "
                "end_vcell_v = ?, "
                "runtime_seconds = ?, "
                "ambient_temp_c = ? "
                "WHERE drain_event_id = ?",
                (endTs, endVcell, endVcell, runtimeSeconds, ambientTempC,
                 int(drainEventId)),
            )

        logger.info(
            "drain event closed | id=%d | end_soc=%.1f | runtime_s=%s",
            int(drainEventId), float(endSoc), runtimeSeconds,
        )
        return DrainEventCloseResult(
            drainEventId=int(drainEventId),
            closed=True,
            endTimestamp=endTs,
            endSoc=float(endSoc),
            runtimeSeconds=runtimeSeconds,
        )


# ================================================================================
# Internal helpers
# ================================================================================


def _computeRuntimeSeconds(startTs: str, endTs: str) -> int | None:
    """Return the integer second-count between two canonical ISO-8601 UTC strings.

    Returns ``None`` if either string is not parseable -- defensive
    fallback so a corrupted start_timestamp (pre-US-202 row, manual
    edit) does not crash the close path.  The row is still closed;
    runtime_seconds just stays NULL.
    """
    try:
        start = datetime.strptime(startTs, CANONICAL_ISO_FORMAT)
        end = datetime.strptime(endTs, CANONICAL_ISO_FORMAT)
    except (TypeError, ValueError):
        return None
    delta = end - start
    return int(delta.total_seconds())
