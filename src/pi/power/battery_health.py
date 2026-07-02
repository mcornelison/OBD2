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
# 2026-05-09    | Rex (US-309) | BL-013 Option A Step 1: added optional
#                               startSocPct / endSocPct kwargs to
#                               startDrainEvent + endDrainEvent.  When set,
#                               the SOC% value (0-100) lands in start_soc /
#                               end_soc; start_vcell_v / end_vcell_v keep
#                               VCELL voltage from startSoc / endSoc.  When
#                               omitted (current production callers), legacy
#                               dual-write VCELL behavior is preserved bit-
#                               for-bit so US-289 lock-down tests stay GREEN.
#                               Step 2 (B-060) wires UpsMonitor.getBattery
#                               Percentage() through the orchestrator.  Step
#                               3 (B-061) drops the legacy columns.
# 2026-07-01    | Rex (US-426) | BL-015 (F-061): DROP the legacy start_soc /
#                               end_soc columns (held VCELL volts, redundant
#                               with *_vcell_v) + ADD dedicated start_soc_pct /
#                               end_soc_pct REAL-nullable columns -- the durable
#                               home for MAX17048 register SoC%.  One forward-
#                               only rebuild migration (ensureBatteryHealthLog
#                               SocPctColumns, CREATE-SELECT-DROP-RENAME) with a
#                               COALESCE(vcell,soc) voltage-preserving backfill.
#                               Recorder stops dual-writing the dropped columns:
#                               startSoc/endSoc -> *_vcell_v only; the optional
#                               startSocPct/endSocPct kwargs now land in
#                               *_soc_pct (NULL when omitted).  US-427 wires the
#                               real register read; this story is schema-only.
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

Schema shape (US-289 vcell rename; US-426 legacy-soc drop + soc_pct add):

* ``drain_event_id``      INTEGER PK AUTOINCREMENT -- monotonic event id
* ``start_timestamp``     TEXT NOT NULL (canonical ISO-8601 UTC default)
* ``end_timestamp``       TEXT NULL (written at close)
* ``start_vcell_v``       REAL NULL -- LiPo cell volts at event open
* ``end_vcell_v``         REAL NULL -- LiPo cell volts at close
* ``start_soc_pct``       REAL NULL -- MAX17048 SoC%% (0-100) at open (US-426).
                          NULL until US-427 wires the register read + NULL in
                          the ~3-min cold-start calibration window.  Replaces
                          the misnamed legacy start_soc (VCELL volts), dropped.
* ``end_soc_pct``         REAL NULL -- MAX17048 SoC%% at close (US-426).
                          Replaces legacy end_soc, dropped.
* ``runtime_seconds``     INTEGER NULL (computed at close)
* ``ambient_temp_c``      REAL NULL (optional)
* ``load_class``          TEXT NOT NULL DEFAULT 'production'
                          CHECK IN ('production','test','sim')
* ``notes``               TEXT NULL
* ``data_source``         TEXT NOT NULL DEFAULT 'real'
                          CHECK IN ('real','replay','physics_sim','fixture','foreign')

US-426 (BL-015): the legacy ``start_soc`` / ``end_soc`` columns held VCELL
volts despite the name (redundant with ``*_vcell_v``) and are DROPPED.  The
recorder writes VCELL volts to ``*_vcell_v`` (their sole home) and the
optional register SoC%% to the new ``*_soc_pct`` columns.  The rebuild
migration COALESCEs any voltage stranded in legacy pre-US-289 rows into
``*_vcell_v`` before dropping, so no data is lost.

Invariants:

* ``start_vcell_v`` + ``start_timestamp`` are authoritative once written; the
  UPDATE path in :meth:`BatteryHealthRecorder.endDrainEvent` only touches
  the end-of-event columns (end_timestamp, end_vcell_v, end_soc_pct,
  runtime_seconds, ambient_temp_c).
* ``drain_event_id`` is auto-incremented + monotonic (per-event, not a
  singleton like ``drive_counter``).
* Close-once semantic: calling ``endDrainEvent`` a second time on an
  already-closed row is a no-op -- the original end_timestamp / end_vcell_v
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
    'ensureBatteryHealthLogSocPctColumns',
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

    -- LiPo cell volts at event open (US-289 rename; US-426 makes this the
    -- sole voltage home after the legacy start_soc/end_soc drop).  REAL
    -- nullable.  Populated by the recorder from ``startSoc``.
    start_vcell_v REAL,

    -- LiPo cell volts at event close.  NULL until endDrainEvent lands.
    end_vcell_v REAL,

    -- MAX17048 State-of-Charge percent (0-100) at event open (US-426, the
    -- BL-015 durable home for SoC%).  REAL nullable -- NULL until US-427
    -- wires UpsMonitor.getBatteryPercentage() into the recording path, and
    -- NULL whenever the register is read inside its ~3-min cold-start
    -- calibration window (honest-instrument: never a garbage percent).  This
    -- REPLACES the misnamed legacy start_soc column (which held VCELL volts,
    -- not SoC%) dropped in US-426.
    start_soc_pct REAL,

    -- MAX17048 SoC% at event close (US-426).  NULL until endDrainEvent lands
    -- (and NULL when the register is uncalibrated).  Replaces legacy end_soc.
    end_soc_pct REAL,

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
        CHECK (data_source IN ('real','replay','physics_sim','fixture','foreign'))
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


def ensureBatteryHealthLogSocPctColumns(conn: sqlite3.Connection) -> bool:
    """Rebuild ``battery_health_log`` to the US-426 SoC%% shape (BL-015).

    ONE forward-only migration that RETIRES the misnamed legacy
    ``start_soc`` / ``end_soc`` columns (they held VCELL volts, not SoC%%,
    redundant with ``*_vcell_v``) and ADDS the dedicated ``start_soc_pct`` /
    ``end_soc_pct`` REAL-nullable columns -- the durable home for the
    MAX17048 register State-of-Charge percent (Atlas BL-015 ruling
    2026-07-01, CIO-ratified).  SQLite cannot drop a column in place on the
    versions we target, so this uses the CREATE-new / INSERT-SELECT /
    DROP-old / RENAME idiom.

    Data preservation: pre-US-289 legacy rows carry their VCELL voltage ONLY
    in ``start_soc`` / ``end_soc`` (``start_vcell_v`` / ``end_vcell_v`` are
    NULL on those rows).  The SELECT therefore COALESCEs
    ``start_vcell_v`` <- ``start_soc`` (and end) so no voltage is lost when
    the legacy columns are dropped.  ``start_soc_pct`` / ``end_soc_pct`` are
    seeded NULL for every existing row -- SoC%% is NOT derivable from volts
    (that misnaming is exactly what this migration retires); US-427 wires the
    real register read for rows recorded going forward.

    Must run AFTER :func:`ensureBatteryHealthLogVcellColumns` (which
    guarantees ``start_vcell_v`` / ``end_vcell_v`` exist so the COALESCE
    SELECT is valid) -- :meth:`src.pi.obdii.database.ObdDatabase.initialize`
    calls the two in that order.  Caller owns the commit (mirrors the sibling
    ``ensureBatteryHealthLog*`` helpers).

    Idempotent: returns ``False`` (no-op) when the table is absent, or when
    ``start_soc_pct`` is already present AND the legacy ``start_soc`` is
    already gone (fresh DBs land in the target shape via
    :data:`SCHEMA_BATTERY_HEALTH_LOG`; a re-run sees nothing to do).

    Args:
        conn: Open sqlite3 connection.

    Returns:
        ``True`` if the table was rebuilt on this call, ``False`` otherwise.
    """
    if not _tableExists(conn, BATTERY_HEALTH_LOG_TABLE):
        return False

    columns = {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({BATTERY_HEALTH_LOG_TABLE})"
        ).fetchall()
    }
    # Already migrated: soc_pct present + legacy soc gone -> no-op.
    if 'start_soc_pct' in columns and 'start_soc' not in columns:
        return False

    newTable = f"{BATTERY_HEALTH_LOG_TABLE}__us426_new"
    # Explicit target schema (mirrors the post-US-426 SCHEMA_BATTERY_HEALTH_LOG
    # column set) under a temp name for the rebuild.
    conn.execute(
        f"CREATE TABLE {newTable} ("
        "    drain_event_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "    start_timestamp TEXT NOT NULL"
        "        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),"
        "    end_timestamp TEXT,"
        "    start_vcell_v REAL,"
        "    end_vcell_v REAL,"
        "    start_soc_pct REAL,"
        "    end_soc_pct REAL,"
        "    runtime_seconds INTEGER,"
        "    ambient_temp_c REAL,"
        "    load_class TEXT NOT NULL DEFAULT 'production'"
        "        CHECK (load_class IN ('production','test','sim')),"
        "    notes TEXT,"
        "    data_source TEXT NOT NULL DEFAULT 'real'"
        "        CHECK (data_source IN ('real','replay','physics_sim','fixture','foreign'))"
        ")"
    )
    # COALESCE preserves the VCELL voltage of pre-US-289 rows (whose only
    # voltage copy is the legacy start_soc/end_soc); start_soc_pct/end_soc_pct
    # seed NULL (SoC%% is never derived from volts).
    conn.execute(
        f"INSERT INTO {newTable} "
        "(drain_event_id, start_timestamp, end_timestamp, start_vcell_v, "
        " end_vcell_v, start_soc_pct, end_soc_pct, runtime_seconds, "
        " ambient_temp_c, load_class, notes, data_source) "
        "SELECT drain_event_id, start_timestamp, end_timestamp, "
        "       COALESCE(start_vcell_v, start_soc), "
        "       COALESCE(end_vcell_v, end_soc), "
        "       NULL, NULL, runtime_seconds, ambient_temp_c, load_class, "
        "       notes, data_source "
        f"FROM {BATTERY_HEALTH_LOG_TABLE}"
    )
    conn.execute(f"DROP TABLE {BATTERY_HEALTH_LOG_TABLE}")
    conn.execute(
        f"ALTER TABLE {newTable} RENAME TO {BATTERY_HEALTH_LOG_TABLE}"
    )
    # Recreate the start_timestamp index dropped with the old table.
    conn.execute(INDEX_BATTERY_HEALTH_LOG_START)
    return True


# ================================================================================
# Dataclasses
# ================================================================================


@dataclass(frozen=True)
class DrainEventCloseResult:
    """Per-call close result returned from :meth:`endDrainEvent`.

    Attributes:
        drainEventId: The row's ``drain_event_id``.
        closed: True if this call wrote end_timestamp / end_vcell_v; False
            when the row was already closed (close-once semantic).
        endTimestamp: The end_timestamp actually stored on the row
            after this call (may be the pre-existing value on re-close).
        endSoc: The VCELL voltage actually stored (``end_vcell_v``).  Kept
            named ``endSoc`` for API back-compat with the ``endSoc`` close
            argument; US-426 dropped the legacy ``end_soc`` column, so this
            now reflects ``end_vcell_v``.
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
        startSocPct: int | None = None,
    ) -> int:
        """Open a new drain-event row.

        Args:
            startSoc: VCELL voltage at event start (3.4-4.2V).  Despite
                the historical "soc" name, this value is treated as
                LiPo cell voltage and lands in ``start_vcell_v``.  When
                ``startSocPct`` is omitted, the same value is also
                written to the legacy ``start_soc`` column (US-289
                dual-write contract).
            loadClass: One of :data:`LOAD_CLASS_VALUES`.  Defaults to
                ``'production'`` -- the real drain case.
            notes: Free-form text (drill context, weather, hardware
                notes).  Optional.
            dataSource: US-195 origin tag.  Defaults to ``'real'``.
            startSocPct: BL-013 Option A Step 1 (US-309): optional
                actual SOC % (0-100) at event start.  When provided,
                this value lands in the legacy ``start_soc`` column
                (overriding the dual-write VCELL fallback) so the
                column finally carries a real SOC%; ``start_vcell_v``
                continues to hold the VCELL voltage from ``startSoc``.
                When ``None`` (current production callers), legacy
                dual-write VCELL behavior is preserved.  Step 2
                (B-060) wires :meth:`UpsMonitor.getBatteryPercentage`
                through the orchestrator.

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

        # US-426 (BL-015): the legacy start_soc column is dropped.  The VCELL
        # voltage from ``startSoc`` lands in start_vcell_v (its sole home); the
        # optional ``startSocPct`` register SoC% lands in the new start_soc_pct
        # column (NULL when omitted -- US-427 wires the real register read).
        startVcell = float(startSoc)
        startSocPctColumn: float | None = (
            float(startSocPct) if startSocPct is not None else None
        )
        with self._database.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO {BATTERY_HEALTH_LOG_TABLE} "
                "(start_timestamp, start_vcell_v, start_soc_pct, "
                " load_class, notes, data_source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (startTs, startVcell, startSocPctColumn, loadClass, notes,
                 dataSource),
            )
            drainEventId = int(cursor.lastrowid or 0)

        logger.info(
            "drain event opened | id=%d | start_vcell_v=%.3f | "
            "start_soc_pct=%s | load_class=%s",
            drainEventId, startVcell, startSocPctColumn, loadClass,
        )
        return drainEventId

    def endDrainEvent(
        self,
        *,
        drainEventId: int,
        endSoc: float,
        ambientTempC: float | None = None,
        endSocPct: int | None = None,
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
            endSoc: VCELL voltage at event end.  Mirrors the
                :meth:`startDrainEvent` ``startSoc`` semantic -- lands
                in ``end_vcell_v`` and (when ``endSocPct`` is omitted)
                also in the legacy ``end_soc`` column.
            ambientTempC: Optional ambient temperature (Celsius).
            endSocPct: BL-013 Option A Step 1 (US-309): optional actual
                SOC % (0-100) at event end.  When provided, lands in
                the legacy ``end_soc`` column; ``end_vcell_v`` keeps
                the VCELL voltage from ``endSoc``.  When ``None``,
                legacy dual-write VCELL behavior is preserved.

        Returns:
            :class:`DrainEventCloseResult` describing whether this call
            actually closed the row, plus the final stored values.

        Raises:
            ValueError: If no row exists with ``drainEventId``.
        """
        endTs = utcIsoNow()

        with self._database.connect() as conn:
            existing = conn.execute(
                f"SELECT start_timestamp, end_timestamp, end_vcell_v, "
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

            # US-426 (BL-015): legacy end_soc is dropped.  The VCELL voltage
            # from ``endSoc`` lands in end_vcell_v (its sole home); the optional
            # ``endSocPct`` register SoC% lands in the new end_soc_pct column
            # (NULL when omitted -- US-427 wires the real register read).
            endVcell = float(endSoc)
            endSocPctColumn: float | None = (
                float(endSocPct) if endSocPct is not None else None
            )
            conn.execute(
                f"UPDATE {BATTERY_HEALTH_LOG_TABLE} SET "
                "end_timestamp = ?, "
                "end_vcell_v = ?, "
                "end_soc_pct = ?, "
                "runtime_seconds = ?, "
                "ambient_temp_c = ? "
                "WHERE drain_event_id = ?",
                (endTs, endVcell, endSocPctColumn, runtimeSeconds, ambientTempC,
                 int(drainEventId)),
            )

        logger.info(
            "drain event closed | id=%d | end_vcell_v=%.3f | "
            "end_soc_pct=%s | runtime_s=%s",
            int(drainEventId), endVcell, endSocPctColumn, runtimeSeconds,
        )
        return DrainEventCloseResult(
            drainEventId=int(drainEventId),
            closed=True,
            endTimestamp=endTs,
            endSoc=endVcell,
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
