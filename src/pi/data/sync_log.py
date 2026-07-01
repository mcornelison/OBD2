################################################################################
# File Name: sync_log.py
# Purpose/Description: sync_log table + delta query helpers for Pi -> server
#                      HTTP sync (US-148).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-148
# 2026-04-19    | Rex (US-202) | Route _utcIsoTimestamp through shared
#                               src.common.time.helper.utcIsoNow (TD-027 fix)
# 2026-04-19    | Rex (US-194) | TD-025 + TD-026 fix: per-table PK registry
#                               (PK_COLUMN) + split into DELTA_SYNC_TABLES
#                               vs SNAPSHOT_TABLES; getDeltaRows routes through
#                               pkColumn and rejects snapshot tables cleanly
# 2026-04-21    | Rex (US-217) | Register battery_health_log (PK drain_event_id)
#                               in PK_COLUMN so UPS drain events sync Pi->server.
# 2026-04-23    | Rex (US-223) | TD-031 close: updated module docstring +
#                               IN_SCOPE_TABLES comment to drop battery_log
#                               from the "Pi-only excluded" list.  The table
#                               is now deleted entirely (see database_schema
#                               mod-history); no sync-scope behaviour changes.
# 2026-05-10    | Rex (US-315) | B-065 close: parallel modified_at cursor for
#                               UPDATE propagation alongside existing pk-only
#                               INSERT delta.  Adds SYNC_UPDATE_TABLES_PK
#                               opt-in registry, _sync_modified_at column +
#                               AFTER UPDATE trigger per opt-in table,
#                               last_synced_modified_at column on sync_log,
#                               combined-cursor query in getDeltaRows, and
#                               ensureSyncModifiedAtSchema migration helper.
#                               INSERT-side semantics unchanged for non-opt-in
#                               tables (back-compat preserved).
# 2026-06-28    | Rex (US-391) | F-076 queue-level quarantine: two new sync_log
#                               columns (consecutive_failures, quarantined_at)
#                               + ensureQuarantineSchema migration +
#                               recordPushFailure / getQuarantineState /
#                               clearQuarantine.  A record whose cross-tier
#                               push keeps being rejected by the server is
#                               quarantined after N consecutive failures so the
#                               SyncClient throttles re-attempts (stop the
#                               silent 27x/day retry) instead of hammering it
#                               every cycle.  HWM advance semantics unchanged
#                               (failures never advance last_synced_id), so the
#                               raw record is preserved + re-drainable.
# 2026-07-01    | Rex (US-412) | F-101: register power_log (PK 'id') in
#                               PK_COLUMN so power-event history syncs
#                               Pi->server.  Append-only integer-PK delta
#                               like every other capture table; formerly
#                               Pi-only.  (startup_log is NOT added here --
#                               its TEXT boot_id PK does not fit the delta
#                               cursor; see BL-013.)
# 2026-07-01    | Rex (US-416) | F-101/F-115: the GENERAL natural-key snapshot
#                               path for append-only TEXT-PK tables (the shape
#                               BL-013 blocked on).  Adds last_snapshot_cursor
#                               to sync_log + ensureSnapshotSyncSchema migration
#                               + getSnapshotRows / getSnapshotCursor /
#                               updateSnapshotCursor, parameterised by the
#                               cross-tier src.common.sync.snapshot_registry
#                               (A-4 define-once).  Deltas by an explicit
#                               cursorCol (e.g. recorded_at), NOT rowid (TEXT-PK
#                               tables have no stable rowid; VACUUM renumbers).
#                               Registry ships empty; startup_log registers in
#                               US-417.  Distinct from SNAPSHOT_TABLES (the
#                               profiles/vehicle_info reject-list) -- opposite
#                               role, see that constant's docstring.
# ================================================================================
################################################################################

"""
sync_log bookkeeping for the Walk-phase Pi -> server HTTP sync pipeline.

Introduces a single SQLite table, ``sync_log``, that tracks the per-table
high-water mark (``last_synced_id``) for delta sync.  US-149's ``SyncClient``
reads the mark, fetches rows ``id > last_synced_id`` via :func:`getDeltaRows`,
POSTs them to Chi-Srv-01, and calls :func:`updateHighWaterMark` on success.
A failed push must NEVER advance ``last_synced_id`` -- that invariant lives
in US-149's client; this module does not model the failure path.

The module is deliberately decoupled from :mod:`src.pi.obdii.database` so the
sync contract evolves without dragging OBD schema changes through the same
module (per the PM scope on US-148; sync bookkeeping lives next to, not
inside, the OBD DB).  Callers pass in a ``sqlite3.Connection``; this module
does no connection management.

Scope tables (per docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md
section 2.1):

- Included: ``realtime_data``, ``statistics``, ``profiles``, ``vehicle_info``,
  ``ai_recommendations``, ``connection_log``, ``alert_log``,
  ``calibration_sessions``, ``power_log`` (US-412).
- Formerly Pi-only, now synced: ``power_log`` was local-only health
  telemetry until US-412 (F-101) mirrored it to the server so power/boot
  history is queryable server-side.  (``battery_log`` was also excluded
  historically but was deleted in US-223 when its sole writer
  :class:`BatteryMonitor` was removed.)

Any call that references a table outside :data:`IN_SCOPE_TABLES` raises
:class:`ValueError`.  This doubles as the SQL-injection guard: the table
name is interpolated into SQL (it is an identifier, not a value, so the
driver cannot parameterize it), and the whitelist is the only defense.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.common.sync.snapshot_registry import (
    SNAPSHOT_SYNC,
    getSnapshotSpec,
    isSnapshotSyncTable,
    snapshotSyncTables,
)
from src.common.time.helper import utcIsoNow

__all__ = [
    'DELTA_SYNC_TABLES',
    'IN_SCOPE_TABLES',
    'PK_COLUMN',
    'SNAPSHOT_SYNC',
    'SNAPSHOT_SYNC_CURSOR_COLUMN',
    'SNAPSHOT_TABLES',
    'SYNC_LOG_SCHEMA',
    'SYNC_MODIFIED_AT_COLUMN',
    'SYNC_UPDATE_TABLES_PK',
    'VALID_STATUSES',
    'clearQuarantine',
    'ensureQuarantineSchema',
    'ensureSnapshotSyncSchema',
    'ensureSyncModifiedAtSchema',
    'getDeltaRows',
    'getHighWaterMark',
    'getModifiedHighWaterMark',
    'getQuarantineState',
    'getSnapshotCursor',
    'getSnapshotRows',
    'initDb',
    'recordPushFailure',
    'updateHighWaterMark',
    'updateSnapshotCursor',
]


# ================================================================================
# Configuration
# ================================================================================

# Per-table primary-key column for delta-eligible (append-only) tables.
# Every value MUST be an INTEGER PK column (the delta cursor is monotonic,
# which only holds for AUTOINCREMENT rowids).  calibration_sessions uses a
# non-standard PK name (``session_id``) -- that is the ONLY reason it needs
# an entry distinct from the ``id`` default.
#
# This registry is authoritative -- there is NO runtime schema introspection.
# Adding a new append-only table to the sync set means adding its row here;
# a missing entry is a hard ValueError at getDeltaRows time (see
# :func:`_validateDeltaTable`).
PK_COLUMN: dict[str, str] = {
    'realtime_data':        'id',
    'statistics':           'id',
    'ai_recommendations':   'id',
    'connection_log':       'id',
    'alert_log':            'id',
    'calibration_sessions': 'session_id',
    # US-204: DTC capture table.  Append-only -- new MIL events insert
    # fresh rows in new drives; same-drive duplicates UPDATE last_seen
    # but the integer PK never moves.
    'dtc_log':              'id',
    # US-206: drive_summary carries per-drive metadata (ambient IAT,
    # starting battery, baro).  drive_id IS the PK, making it the
    # natural monotonic sync cursor.  The sync client's _renamePkToId
    # path will rename drive_id -> id on the outbound payload so the
    # server-side source_id mapping stays uniform with the other
    # capture tables (see US-194).
    'drive_summary':        'drive_id',
    # US-217: battery_health_log carries one row per UPS drain event.
    # drain_event_id is the monotonic PK + sync cursor; renamed to 'id'
    # on the outbound payload for server-side source_id mapping.
    'battery_health_log':   'drain_event_id',
    # US-369 (F-109): dtc_freeze_frame -- one row per Mode 02 freeze-frame
    # captured on a MIL_ON rising edge.  Append-only with an integer 'id'
    # PK, so it delta-syncs exactly like dtc_log.  US-368 created the table
    # but left it out of this registry; US-369 wires it into the sync set
    # (the cross-tier vehicle_info_vin -> server vehicle_info_id resolution
    # happens server-side in src/server/api/sync.py).
    'dtc_freeze_frame':     'id',
    # US-412 (F-101): power_log -- one row per power-source / shutdown-stage
    # transition (NOT per poll), append-only with an integer 'id' PK, so it
    # delta-syncs exactly like the other capture tables.  Local-only Pi
    # health telemetry until US-412 mirrored it to the server so power/boot
    # history is queryable server-side.  Volume is naturally bounded by real
    # power events (raw-every-event; no sampling needed).
    'power_log':            'id',
}

# Append-only (event-stream) tables eligible for delta-by-PK sync.
# Identical to PK_COLUMN.keys(); made a frozenset so callers can pass it to
# ``sorted()`` / set-ops without coupling to the dict.
DELTA_SYNC_TABLES: frozenset[str] = frozenset(PK_COLUMN.keys())

# Snapshot / upsert-style tables whose PK is a natural TEXT key
# (``profiles.id`` is 'daily'/'performance'; ``vehicle_info.vin`` is an
# actual VIN).  Delta-by-PK is semantically meaningless here -- lexicographic
# ordering of strings is not a monotonic event cursor.  These are explicitly
# excluded from :meth:`SyncClient.pushDelta`'s delta path.  A future story
# (post-US-194) will add an upsert path; for Sprint 14 they are skipped.
SNAPSHOT_TABLES: frozenset[str] = frozenset({
    'profiles',
    'vehicle_info',
})

# Union of delta + snapshot tables -- preserved for BC.  Used by the server
# payload whitelist (``_validateTable``), ``scripts/seed_pi_fixture.py``,
# and ``tests/scripts/test_seed_pi_fixture.py``.  power_log joined the delta
# set in US-412 (F-101) so power/boot history mirrors to the server.
# (battery_log was absent historically but the table was removed in US-223
# when BatteryMonitor was deleted.)
# See specs/architecture.md "Sync Log Table".
IN_SCOPE_TABLES: frozenset[str] = DELTA_SYNC_TABLES | SNAPSHOT_TABLES

# status column CHECK constraint domain.  'pending' is the boot-time state
# before any push has been attempted; 'ok' after a successful push;
# 'failed' after all retries are exhausted on a push (US-149).
VALID_STATUSES: frozenset[str] = frozenset({'ok', 'pending', 'failed'})

# DDL for the sync_log table.  IF NOT EXISTS makes initDb() idempotent.
# US-315 / B-065: ``last_synced_modified_at`` carries the high-water mark
# for the parallel modified_at cursor used by SYNC_UPDATE_TABLES_PK.
# Older DBs from before US-315 will pick the column up via the idempotent
# ALTER TABLE branch in :func:`ensureSyncModifiedAtSchema`.
#
# US-391 / F-076: ``consecutive_failures`` + ``quarantined_at`` carry the
# queue-level quarantine state.  Fresh DBs land with the columns; older DBs
# pick them up via the idempotent ALTER in :func:`ensureQuarantineSchema`.
#
# US-416 / F-101: ``last_snapshot_cursor`` (TEXT) carries the per-table
# high-water mark for the natural-key SNAPSHOT_SYNC path -- an ISO-8601 value of
# the table's ``cursorCol`` (e.g. recorded_at), PARALLEL to the integer
# ``last_synced_id`` delta cursor.  Snapshot-sync tables (TEXT-PK, insert-once)
# have no integer delta cursor, so they track progress here instead.  Older DBs
# pick it up via the idempotent ALTER in :func:`ensureSnapshotSyncSchema`.
SYNC_LOG_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS sync_log (
    table_name              TEXT    PRIMARY KEY,
    last_synced_id          INTEGER NOT NULL DEFAULT 0,
    last_synced_at          TEXT,
    last_batch_id           TEXT,
    status                  TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('ok','pending','failed')),
    last_synced_modified_at TEXT,
    consecutive_failures    INTEGER NOT NULL DEFAULT 0,
    quarantined_at          TEXT,
    last_snapshot_cursor    TEXT
)
"""

# US-416: sync_log column holding the SNAPSHOT_SYNC path's per-table time-cursor
# high-water mark (the max cursorCol value successfully pushed so far).
SNAPSHOT_SYNC_CURSOR_COLUMN: str = 'last_snapshot_cursor'

# US-315 / B-065: opt-in registry for tables that issue UPDATE on existing
# rows (close-event UPDATEs, last_seen bumps, NULL-backfill writes).  The
# PK column is used by the AFTER UPDATE trigger's WHERE clause + by the
# combined cursor query in :func:`getDeltaRows`.
#
# Audit reference (Rex 2026-05-10 pre-flight): src/pi/power/battery_health.py:539
# (close-event UPDATE), src/pi/obdii/drive_summary.py:634 + 741 (UPSERT
# replay + NULL backfill), src/pi/obdii/dtc_logger.py:541 + 548 (last_seen
# bump on repeat sightings).  connection_log + realtime_data + statistics +
# alert_log + ai_recommendations were verified INSERT-only in production
# code paths (no UPDATE statement targets them).  calibration_sessions
# UPDATEs end_time on close but is intentionally out of B-065 scope --
# Spool's spec narrowed to the three production-impact tables.
SYNC_UPDATE_TABLES_PK: dict[str, str] = {
    'battery_health_log': 'drain_event_id',
    'drive_summary':      'drive_id',
    'dtc_log':            'id',
}

# Bookkeeping column added to every opt-in table.  TEXT (ISO-8601 with
# millisecond resolution) so lexicographic ordering matches time order.
# Stays NULL for rows that have never been UPDATEd (pre-migration rows
# AND newly-INSERTed rows -- only the AFTER UPDATE trigger writes here).
SYNC_MODIFIED_AT_COLUMN: str = '_sync_modified_at'


# ================================================================================
# Internal helpers
# ================================================================================

def _validateTable(tableName: str) -> None:
    """Raise ValueError unless ``tableName`` is in :data:`IN_SCOPE_TABLES`.

    This is the SQL-injection guard for every function that interpolates a
    table name into SQL.  Callers with an untrusted table name must always
    route through here first.
    """
    if tableName not in IN_SCOPE_TABLES:
        raise ValueError(
            f"table {tableName!r} is not in sync scope; "
            f"expected one of {sorted(IN_SCOPE_TABLES)}"
        )


def _validateDeltaTable(tableName: str) -> None:
    """Raise ValueError unless ``tableName`` is delta-syncable (US-194).

    Narrower than :func:`_validateTable`: a table may be in ``IN_SCOPE_TABLES``
    (and therefore acceptable to the server payload whitelist) without being
    delta-syncable.  ``profiles`` and ``vehicle_info`` are such tables --
    they are snapshot/upsert style and do not fit the delta-by-PK model.

    The error message distinguishes these two shapes of rejection:

    - Unknown table -> "not in sync scope" (from :func:`_validateTable`)
    - Known snapshot table -> "not delta-syncable"  (this function)
    """
    if tableName in SNAPSHOT_TABLES:
        raise ValueError(
            f"table {tableName!r} is not delta-syncable -- it is a "
            f"snapshot/upsert table (see sync_log.SNAPSHOT_TABLES). "
            f"Use the upsert sync path instead (post-US-194)."
        )
    if tableName not in DELTA_SYNC_TABLES:
        raise ValueError(
            f"table {tableName!r} is not in delta-sync scope; "
            f"expected one of {sorted(DELTA_SYNC_TABLES)}"
        )


def _validateSnapshotTable(tableName: str) -> None:
    """Raise ValueError unless ``tableName`` is a registered snapshot-sync table.

    The whitelist is :data:`SNAPSHOT_SYNC` (from the shared cross-tier registry).
    Like :func:`_validateTable` for the delta path, this is the SQL-injection
    guard for every snapshot function that interpolates ``tableName`` (and its
    ``cursorCol``) into SQL as an identifier -- an unregistered table must fail
    loudly, never fall through to a raw interpolation.
    """
    if not isSnapshotSyncTable(tableName):
        raise ValueError(
            f"table {tableName!r} is not registered for snapshot sync; "
            f"expected one of {sorted(snapshotSyncTables())}",
        )


def _validateStatus(status: str) -> None:
    """Raise ValueError unless ``status`` is in :data:`VALID_STATUSES`.

    Mirrors the CHECK constraint; raising in Python produces a cleaner error
    than the ``sqlite3.IntegrityError`` the driver would otherwise throw.
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"status {status!r} is not valid; "
            f"expected one of {sorted(VALID_STATUSES)}"
        )


def _utcIsoTimestamp() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing 'Z'.

    Thin wrapper preserved for local readability; the canonical source of
    this format lives in :func:`src.common.time.helper.utcIsoNow` (TD-027 /
    US-202).  All capture-table writers across the Pi tree now route
    through that helper; this module's public API stays stable.
    """
    return utcIsoNow()


def _hasModifiedAtColumn(
    conn: sqlite3.Connection,
    tableName: str,
) -> bool:
    """Return True iff ``tableName`` has the US-315 modified_at column.

    Used by :func:`getDeltaRows` to detect a pre-migration table and
    fall through to the legacy pk-only query rather than tripping
    "no such column".  Tests that call ``getDeltaRows`` directly via
    fixture seeding (without going through SyncClient.pushDelta, which
    runs the migration) rely on this fallback.

    Cheap on every call -- PRAGMA table_info reads from sqlite's
    in-memory schema cache, no disk I/O.
    """
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({tableName})")}
    return SYNC_MODIFIED_AT_COLUMN in cols


# ================================================================================
# Public API
# ================================================================================

def initDb(conn: sqlite3.Connection) -> None:
    """Create the sync_log table if it does not already exist.

    Safe to call on every boot.  Calling twice on the same connection is a
    no-op (the CREATE TABLE IF NOT EXISTS + single-transaction commit do not
    disturb existing rows).

    Args:
        conn: An open sqlite3 connection.  The caller owns it.
    """
    conn.execute(SYNC_LOG_SCHEMA)
    conn.commit()


def getDeltaRows(
    conn: sqlite3.Connection,
    tableName: str,
    lastId: int,
    limit: int,
    lastModifiedAt: str | None = None,
) -> list[dict[str, Any]]:
    """Return delta rows from ``tableName`` for the next sync push.

    For non-opt-in tables (:data:`DELTA_SYNC_TABLES` minus
    :data:`SYNC_UPDATE_TABLES_PK`), behavior is unchanged: rows where
    ``pk > lastId``, ordered ASC, capped at ``limit``.  ``lastModifiedAt``
    is ignored (back-compat for legacy callers).

    For opt-in tables (:data:`SYNC_UPDATE_TABLES_PK`), the query uses
    BOTH cursors (US-315 / B-065): rows where
    ``pk > lastId OR _sync_modified_at > lastModifiedAt``, ordered by PK
    ASC.  This catches rows that were UPDATEd after their initial INSERT
    push -- the bug filed as B-065 (Pi-side close-event UPDATE never
    propagating).  The bookkeeping column :data:`SYNC_MODIFIED_AT_COLUMN`
    is stripped from the returned dicts so it does not flow onto the
    wire (server has no analogue column; sending it would 422 the
    SQLAlchemy bulk insert).

    Snapshot tables (``profiles``, ``vehicle_info``) raise ValueError --
    they do not fit the delta-by-PK model (see :data:`SNAPSHOT_TABLES`).

    Args:
        conn: An open sqlite3 connection.  ``row_factory`` does not need to
            be configured -- this function builds dicts itself so callers get
            the same shape regardless of upstream connection settings.
        tableName: Must be a member of :data:`DELTA_SYNC_TABLES`.
        lastId: Last successfully-synced PK value (from
            :func:`getHighWaterMark`).  Always integer -- every entry in
            :data:`PK_COLUMN` points at an INTEGER PK column.  ``0`` means
            "start from the beginning".
        limit: Max rows to return.  Use the configured batch size.
        lastModifiedAt: Last successfully-synced modified_at timestamp for
            opt-in tables (from :func:`getHighWaterMark`'s 5-tuple form).
            ``None`` means "include every modified row" (also the legacy
            default, which keeps non-opt-in calls untouched).

    Returns:
        List of dict rows ordered by the PK column ASC.  Empty if no rows
        match either branch of the cursor.

    Raises:
        ValueError: If ``tableName`` is not in :data:`DELTA_SYNC_TABLES`
            (including the SNAPSHOT_TABLES case, which raises a more
            specific message).
    """
    _validateDeltaTable(tableName)
    pkColumn = PK_COLUMN[tableName]

    # US-315: only run the combined cursor when (a) the table is opt-in
    # AND (b) the _sync_modified_at column actually exists.  Pre-migration
    # callers (e.g., tests that seed dtc_log via ObdDatabase.initialize
    # WITHOUT first running ensureSyncModifiedAtSchema) fall through to
    # the legacy pk-only query so they don't trip "no such column".  The
    # SyncClient always runs the migration before calling this helper, so
    # production paths get the combined-cursor branch.
    useCombinedCursor = (
        tableName in SYNC_UPDATE_TABLES_PK
        and _hasModifiedAtColumn(conn, tableName)
    )
    if useCombinedCursor:
        # Combined cursor for opt-in tables: pk > lastId catches new
        # INSERTs; _sync_modified_at > lastModifiedAt catches UPDATEs to
        # already-pushed rows.  ``or ''`` on lastModifiedAt makes the
        # "no prior modified-at sync" case (NULL high-water mark) compare
        # cleanly without a Python-side branch.
        modifiedFloor = lastModifiedAt or ''
        cursor = conn.execute(
            f"SELECT * FROM {tableName} "  # noqa: S608 -- whitelisted identifiers
            f"WHERE {pkColumn} > ? "
            f"   OR ({SYNC_MODIFIED_AT_COLUMN} IS NOT NULL "
            f"       AND {SYNC_MODIFIED_AT_COLUMN} > ?) "
            f"ORDER BY {pkColumn} ASC LIMIT ?",
            (int(lastId), modifiedFloor, int(limit)),
        )
    else:
        # Legacy pk-only path (unchanged for back-compat per US-315
        # doNotTouch on INSERT-side delta logic).
        cursor = conn.execute(
            f"SELECT * FROM {tableName} "  # noqa: S608 -- whitelisted identifiers
            f"WHERE {pkColumn} > ? ORDER BY {pkColumn} ASC LIMIT ?",
            (int(lastId), int(limit)),
        )
    columns = [desc[0] for desc in cursor.description]
    rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    # Strip the Pi-only bookkeeping column from the wire payload.  Server
    # models have no _sync_modified_at column; leaving it in would fail the
    # SQLAlchemy bulk insert with an unknown-column error.
    for row in rows:
        row.pop(SYNC_MODIFIED_AT_COLUMN, None)
    return rows


def updateHighWaterMark(
    conn: sqlite3.Connection,
    tableName: str,
    lastId: int,
    batchId: str,
    status: str = 'ok',
    lastModifiedAt: str | None = None,
) -> None:
    """UPSERT the sync_log row for ``tableName``, advancing the high-water mark.

    Inserts if missing, updates if present.  Mutable columns
    (``last_synced_id``, ``last_synced_at``, ``last_batch_id``, ``status``,
    and -- when supplied -- ``last_synced_modified_at``) advance together
    in a single transaction.

    US-149 note: this function ALWAYS advances ``last_synced_id``.  Callers
    that need to record a failed-push event without advancing the mark must
    use a distinct write path -- never pass the delta-max id with
    ``status='failed'`` expecting the id to be held back.

    US-315: ``lastModifiedAt`` is the new high-water mark for the parallel
    modified_at cursor.  Pass ``None`` (default) for non-opt-in tables or
    when no row in the pushed batch had a non-NULL ``_sync_modified_at`` --
    the existing column value is preserved in that case (no rewinds).

    Args:
        conn: Open sqlite3 connection.
        tableName: Must be in :data:`IN_SCOPE_TABLES`.
        lastId: New high-water mark (typically ``max(row.id)`` of the batch).
        batchId: Batch identifier for traceability in the server logs.
        status: One of :data:`VALID_STATUSES`.  Defaults to ``'ok'``.
        lastModifiedAt: New modified_at high-water mark.  ``None`` preserves
            the existing value (cursor never rewinds on a partial-update push).

    Raises:
        ValueError: If ``tableName`` or ``status`` is invalid.
    """
    _validateTable(tableName)
    _validateStatus(status)

    now = _utcIsoTimestamp()
    if lastModifiedAt is None:
        # COALESCE preserves the existing modified_at cursor when the caller
        # didn't compute a new one (non-opt-in table, or all pushed rows
        # had NULL _sync_modified_at).
        conn.execute(
            """
            INSERT INTO sync_log
                (table_name, last_synced_id, last_synced_at,
                 last_batch_id, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(table_name) DO UPDATE SET
                last_synced_id = excluded.last_synced_id,
                last_synced_at = excluded.last_synced_at,
                last_batch_id  = excluded.last_batch_id,
                status         = excluded.status
            """,
            (tableName, int(lastId), now, batchId, status),
        )
    else:
        conn.execute(
            """
            INSERT INTO sync_log
                (table_name, last_synced_id, last_synced_at,
                 last_batch_id, status, last_synced_modified_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(table_name) DO UPDATE SET
                last_synced_id          = excluded.last_synced_id,
                last_synced_at          = excluded.last_synced_at,
                last_batch_id           = excluded.last_batch_id,
                status                  = excluded.status,
                last_synced_modified_at = excluded.last_synced_modified_at
            """,
            (tableName, int(lastId), now, batchId, status, lastModifiedAt),
        )
    conn.commit()


def getHighWaterMark(
    conn: sqlite3.Connection,
    tableName: str,
) -> tuple[int, str | None, str | None, str]:
    """Return the high-water mark tuple for ``tableName``.

    Args:
        conn: Open sqlite3 connection.
        tableName: Must be in :data:`IN_SCOPE_TABLES`.

    Returns:
        ``(last_synced_id, last_synced_at, last_batch_id, status)``.
        If no row exists yet, returns ``(0, None, None, 'pending')``.

        US-315 (B-065) note: the modified_at high-water mark is exposed
        through :func:`getModifiedHighWaterMark`, NOT this function, so
        the 4-tuple shape stays compatible with every existing caller.

    Raises:
        ValueError: If ``tableName`` is not in :data:`IN_SCOPE_TABLES`.
    """
    _validateTable(tableName)
    row = conn.execute(
        "SELECT last_synced_id, last_synced_at, last_batch_id, status "
        "FROM sync_log WHERE table_name = ?",
        (tableName,),
    ).fetchone()
    if row is None:
        return (0, None, None, 'pending')
    # sqlite3.Row and plain tuple both indexable; normalize to tuple.
    return (int(row[0]), row[1], row[2], row[3])


def getModifiedHighWaterMark(
    conn: sqlite3.Connection,
    tableName: str,
) -> str | None:
    """Return ``last_synced_modified_at`` for ``tableName`` (US-315).

    The modified_at cursor is opt-in per :data:`SYNC_UPDATE_TABLES_PK`;
    callers should only consult it for those tables.  Returns ``None``
    when:

    * The sync_log table predates US-315 (column not yet added) -- the
      caller's next push will run :func:`ensureSyncModifiedAtSchema`
      which adds the column idempotently.
    * No sync_log row exists for ``tableName`` yet (first push).
    * A row exists but ``last_synced_modified_at`` was never set
      (rows pushed before any UPDATE-eligible row existed).

    All three "no value" cases collapse to ``None`` so callers don't
    have to distinguish them; the cursor query treats ``None`` as
    "include any non-NULL ``_sync_modified_at``".

    Args:
        conn: Open sqlite3 connection.
        tableName: Must be in :data:`IN_SCOPE_TABLES` (validated for
            symmetry with :func:`getHighWaterMark`; returning ``None``
            for unknown tables would be a quieter footgun).

    Raises:
        ValueError: If ``tableName`` is not in :data:`IN_SCOPE_TABLES`.
    """
    _validateTable(tableName)
    # Defensive against pre-US-315 schema (sync_log without
    # last_synced_modified_at column): probe once and degrade cleanly so
    # a stale DB on a fresh client install does not crash.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    if 'last_synced_modified_at' not in columns:
        return None
    row = conn.execute(
        "SELECT last_synced_modified_at FROM sync_log WHERE table_name = ?",
        (tableName,),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def ensureSyncModifiedAtSchema(conn: sqlite3.Connection) -> bool:
    """Idempotently set up the B-065 modified_at cursor support (US-315).

    Three things happen here, all guarded so re-running on an already-
    migrated DB is a no-op:

    1. ``sync_log`` gains the ``last_synced_modified_at`` TEXT column if
       missing (older DBs predate US-315).  ``initDb`` is also called
       first so a fresh DB lands in a known shape before the ALTER.
    2. Each table in :data:`SYNC_UPDATE_TABLES_PK` gains the
       :data:`SYNC_MODIFIED_AT_COLUMN` TEXT column if missing.  Existing
       rows are NOT backfilled -- they stay NULL until the next UPDATE
       fires the trigger.  This keeps the modified_at cursor from
       re-pushing every pre-migration row on first sync.
    3. Each opt-in table gains an AFTER UPDATE trigger that sets the
       column to the current UTC ISO-8601 stamp on every application
       UPDATE.  The ``WHEN NEW IS OLD`` guard means the trigger does
       NOT fire on its own self-UPDATE (NULL-safe ``IS`` comparison),
       so recursion is impossible regardless of the
       ``recursive_triggers`` PRAGMA state.

    A table named in :data:`SYNC_UPDATE_TABLES_PK` that doesn't yet exist
    in the database is silently skipped -- the migration runs again at
    next call once the table has been created (matches the lazy-init
    pattern in :func:`SyncClient.pushDelta`).

    Args:
        conn: Open sqlite3 connection.  Caller owns commit -- this
            function commits after the schema mutations so subsequent
            reads in the same transaction see the new shape.

    Returns:
        ``True`` if any ALTER TABLE or CREATE TRIGGER statement actually
        ran on this call (i.e., the DB was previously un-migrated for at
        least one of the steps).  ``False`` when every step was already
        in place.  The bool is informational; the migration is always
        safe to re-run.
    """
    initDb(conn)
    didWork = False

    # 1. sync_log column.
    syncLogCols = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    if 'last_synced_modified_at' not in syncLogCols:
        conn.execute(
            "ALTER TABLE sync_log ADD COLUMN last_synced_modified_at TEXT",
        )
        didWork = True

    # 2 + 3. Per-table column + AFTER UPDATE trigger.
    for tableName, pkColumn in SYNC_UPDATE_TABLES_PK.items():
        # Skip if the target table doesn't exist yet (lazy-init pattern;
        # ObdDatabase.initialize creates capture tables, sync migration
        # may run before that on a fresh DB).
        tableExists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (tableName,),
        ).fetchone()
        if tableExists is None:
            continue

        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({tableName})")}
        if SYNC_MODIFIED_AT_COLUMN not in cols:
            conn.execute(
                f"ALTER TABLE {tableName} "  # noqa: S608 -- whitelisted identifier
                f"ADD COLUMN {SYNC_MODIFIED_AT_COLUMN} TEXT",
            )
            didWork = True

        triggerName = f"trg_{tableName}_sync_modified_at"
        triggerExists = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='trigger' AND name = ?",
            (triggerName,),
        ).fetchone()
        if triggerExists is None:
            # CREATE TRIGGER IF NOT EXISTS would do, but checking
            # sqlite_master first lets us track whether the migration
            # actually ran (via didWork) for the caller's logging.
            conn.execute(
                f"CREATE TRIGGER {triggerName} "  # noqa: S608 -- whitelisted
                f"AFTER UPDATE ON {tableName} "
                f"FOR EACH ROW "
                f"WHEN NEW.{SYNC_MODIFIED_AT_COLUMN} "
                f"     IS OLD.{SYNC_MODIFIED_AT_COLUMN} "
                f"BEGIN "
                f"    UPDATE {tableName} "
                f"    SET {SYNC_MODIFIED_AT_COLUMN} = "
                f"        strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                f"    WHERE {pkColumn} = NEW.{pkColumn}; "
                f"END",
            )
            didWork = True

    conn.commit()
    return didWork


# ================================================================================
# Queue-level quarantine (US-391 / F-076)
# ================================================================================
#
# A record whose cross-tier resolution keeps failing server-side (e.g. a
# dtc_freeze_frame row whose ``vehicle_info_vin`` has no ECU era yet) makes the
# server reject the whole push every cycle.  "Fail loudly, no silent re-resolve"
# is correct per-attempt, but at the QUEUE level it becomes a silent infinite
# loop (27x/day for 3+ weeks) that masks a real sync failure in the noise.
#
# The quarantine is per-table bookkeeping on sync_log: ``consecutive_failures``
# counts server-rejection failures (not transient network failures), and once it
# reaches the threshold ``quarantined_at`` is stamped ONCE.  The SyncClient reads
# this state to throttle re-attempts.  Crucially this NEVER advances
# ``last_synced_id`` -- the raw record stays on the Pi, preserved and
# re-drainable: a successful push (e.g. after US-367 backfills the ECU era)
# calls :func:`clearQuarantine` and the record flows normally again.


def _hasQuarantineColumns(conn: sqlite3.Connection) -> bool:
    """Return True iff sync_log carries the US-391 quarantine columns."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    return {'consecutive_failures', 'quarantined_at'} <= cols


def ensureQuarantineSchema(conn: sqlite3.Connection) -> bool:
    """Idempotently add the US-391 quarantine columns to sync_log.

    Fresh DBs already have them (they are in :data:`SYNC_LOG_SCHEMA`); this
    handles pre-US-391 DBs via ``ALTER TABLE ... ADD COLUMN``.  Safe to call on
    every boot / every push (matches :func:`ensureSyncModifiedAtSchema`).

    Args:
        conn: Open sqlite3 connection.  ``initDb`` is called first so a fresh
            DB lands in a known shape before the ALTER probes run.

    Returns:
        ``True`` if any ALTER actually ran (DB was previously un-migrated);
        ``False`` when both columns were already present.
    """
    initDb(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    didWork = False
    if 'consecutive_failures' not in cols:
        conn.execute(
            "ALTER TABLE sync_log "
            "ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0",
        )
        didWork = True
    if 'quarantined_at' not in cols:
        conn.execute("ALTER TABLE sync_log ADD COLUMN quarantined_at TEXT")
        didWork = True
    conn.commit()
    return didWork


def recordPushFailure(
    conn: sqlite3.Connection,
    tableName: str,
    batchId: str,
    *,
    quarantineThreshold: int,
    nowIso: str,
) -> bool:
    """Record a server-rejection push failure; quarantine after N in a row.

    Increments ``consecutive_failures`` and writes ``status='failed'`` +
    diagnostics WITHOUT advancing ``last_synced_id`` (the US-149 failed-push
    invariant -- the raw record must stay re-sendable).  When the counter
    reaches ``quarantineThreshold`` for the first time, ``quarantined_at`` is
    stamped with ``nowIso`` and this function returns ``True`` exactly once so
    the caller can surface the event a single time (not per-cycle).

    Only call this for failures where the server REJECTED the push (an HTTP
    error response).  Transient network failures (DNS/refused/timeout) must NOT
    flow here -- they are not an "identical resolution failure" and would
    wrongly quarantine a table during an outage.

    Args:
        conn: Open sqlite3 connection.
        tableName: Must be in :data:`IN_SCOPE_TABLES`.
        batchId: Batch identifier for the diagnostic trail (``last_batch_id``).
        quarantineThreshold: Consecutive-failure count at which the record is
            quarantined.  ``<= 0`` disables quarantine (always returns False).
        nowIso: Caller-supplied ISO-8601 timestamp stamped as ``quarantined_at``
            on the transition (the caller owns the clock so throttle math in
            :class:`SyncClient` stays consistent + testable).

    Returns:
        ``True`` iff THIS call transitioned the table into quarantine (stamp a
        fresh ``quarantined_at``); ``False`` otherwise (below threshold, or
        already quarantined).

    Raises:
        ValueError: If ``tableName`` is not in :data:`IN_SCOPE_TABLES`.
    """
    _validateTable(tableName)
    ensureQuarantineSchema(conn)

    row = conn.execute(
        "SELECT last_synced_id, consecutive_failures, quarantined_at "
        "FROM sync_log WHERE table_name = ?",
        (tableName,),
    ).fetchone()
    lastId = int(row[0]) if row is not None else 0
    priorCount = int(row[1]) if row is not None else 0
    priorQuarantinedAt = row[2] if row is not None else None

    newCount = priorCount + 1
    justQuarantined = (
        quarantineThreshold > 0
        and newCount >= quarantineThreshold
        and priorQuarantinedAt is None
    )
    newQuarantinedAt = nowIso if justQuarantined else priorQuarantinedAt

    now = _utcIsoTimestamp()
    conn.execute(
        """
        INSERT INTO sync_log
            (table_name, last_synced_id, last_synced_at, last_batch_id,
             status, consecutive_failures, quarantined_at)
        VALUES (?, ?, ?, ?, 'failed', ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            last_synced_at       = excluded.last_synced_at,
            last_batch_id        = excluded.last_batch_id,
            status               = 'failed',
            consecutive_failures = excluded.consecutive_failures,
            quarantined_at       = excluded.quarantined_at
        """,
        (tableName, lastId, now, batchId, newCount, newQuarantinedAt),
    )
    conn.commit()
    return justQuarantined


def getQuarantineState(
    conn: sqlite3.Connection,
    tableName: str,
) -> tuple[int, str | None]:
    """Return ``(consecutive_failures, quarantined_at)`` for ``tableName``.

    ``quarantined_at`` is ``None`` when the table is not quarantined.  On a
    pre-US-391 sync_log (columns absent) returns ``(0, None)`` so a stale DB on
    a fresh client install degrades cleanly instead of crashing.

    Raises:
        ValueError: If ``tableName`` is not in :data:`IN_SCOPE_TABLES`.
    """
    _validateTable(tableName)
    if not _hasQuarantineColumns(conn):
        return (0, None)
    row = conn.execute(
        "SELECT consecutive_failures, quarantined_at "
        "FROM sync_log WHERE table_name = ?",
        (tableName,),
    ).fetchone()
    if row is None:
        return (0, None)
    return (int(row[0]), row[1])


def clearQuarantine(conn: sqlite3.Connection, tableName: str) -> None:
    """Reset the failure counter + quarantine flag for ``tableName``.

    Call after a successful push so a previously-quarantined record becomes
    re-drainable / un-throttled (US-391 invariant 4).  A no-op when no sync_log
    row exists yet or the quarantine columns are absent (pre-US-391 DB).

    Raises:
        ValueError: If ``tableName`` is not in :data:`IN_SCOPE_TABLES`.
    """
    _validateTable(tableName)
    if not _hasQuarantineColumns(conn):
        return
    conn.execute(
        "UPDATE sync_log SET consecutive_failures = 0, quarantined_at = NULL "
        "WHERE table_name = ?",
        (tableName,),
    )
    conn.commit()


# ================================================================================
# Natural-key snapshot sync (US-416 / F-101)
# ================================================================================
#
# The GENERAL path for append-only, immutable, TEXT-PK tables that do NOT fit the
# integer-delta cursor (startup_log.boot_id is the motivating case; the F-115 EDR
# event-vault reuses it).  The per-table shape -- naturalKeyCols + cursorCol --
# lives ONCE in :mod:`src.common.sync.snapshot_registry` (A-4), imported by both
# this Pi reader and the server upsert.
#
# The Pi deltas by ``cursorCol > last_snapshot_cursor`` (an explicit
# insertion-timestamp column, e.g. recorded_at) and advances the cursor to the
# max cursorCol value it pushed.  Per the Atlas ruling: because the server
# upserts on the natural key, cursor precision is not safety-critical -- an
# over-reading cursor just harmlessly re-pushes; the cursor bounds VOLUME, the
# natural key guarantees CORRECTNESS.  This is why we never touch ``rowid`` (a
# TEXT-PK table has no INTEGER-PK alias, so VACUUM can renumber it and desync).


def ensureSnapshotSyncSchema(conn: sqlite3.Connection) -> bool:
    """Idempotently add the US-416 ``last_snapshot_cursor`` column to sync_log.

    Fresh DBs already have it (it is in :data:`SYNC_LOG_SCHEMA`); this handles
    pre-US-416 DBs via ``ALTER TABLE ... ADD COLUMN``.  Safe to call on every
    boot / every push (matches :func:`ensureQuarantineSchema`).

    Args:
        conn: Open sqlite3 connection.  ``initDb`` is called first so a fresh
            DB lands in a known shape before the ALTER probe runs.

    Returns:
        ``True`` if the ALTER actually ran (DB was previously un-migrated);
        ``False`` when the column was already present.
    """
    initDb(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    if SNAPSHOT_SYNC_CURSOR_COLUMN not in cols:
        conn.execute(
            f"ALTER TABLE sync_log ADD COLUMN {SNAPSHOT_SYNC_CURSOR_COLUMN} TEXT",
        )
        conn.commit()
        return True
    return False


def getSnapshotCursor(
    conn: sqlite3.Connection,
    tableName: str,
) -> str | None:
    """Return the snapshot-sync high-water cursor for ``tableName`` (US-416).

    The cursor is the max ``cursorCol`` value successfully pushed so far.
    Returns ``None`` -- meaning "start from the beginning" -- when the sync_log
    predates US-416 (column absent), when no sync_log row exists yet (first
    push), or when the row exists but the cursor was never set.  All three
    "no value" cases collapse to ``None`` so callers do not have to distinguish
    them; :func:`getSnapshotRows` treats ``None`` as "include every row".

    Raises:
        ValueError: If ``tableName`` is not registered in :data:`SNAPSHOT_SYNC`.
    """
    _validateSnapshotTable(tableName)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sync_log)")}
    if SNAPSHOT_SYNC_CURSOR_COLUMN not in columns:
        return None
    row = conn.execute(
        f"SELECT {SNAPSHOT_SYNC_CURSOR_COLUMN} FROM sync_log "  # noqa: S608 -- const identifier
        "WHERE table_name = ?",
        (tableName,),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def getSnapshotRows(
    conn: sqlite3.Connection,
    tableName: str,
    lastCursor: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Return the next batch of snapshot rows to push for ``tableName`` (US-416).

    Selects rows where ``cursorCol > lastCursor`` (strictly greater, so an
    already-synced boundary row is not re-fetched), ordered by ``cursorCol``
    ASC, capped at ``limit``.  ``lastCursor=None`` (or empty string) means
    "from the beginning" -- the empty string sorts before every ISO-8601
    timestamp, so no row is skipped.

    Args:
        conn: Open sqlite3 connection.  ``row_factory`` need not be configured;
            this builds dicts itself so callers get a stable shape.
        tableName: Must be registered in :data:`SNAPSHOT_SYNC`.
        lastCursor: The high-water cursor from :func:`getSnapshotCursor`.
        limit: Max rows to return -- bounds the push volume per cycle.

    Returns:
        List of dict rows ordered by ``cursorCol`` ASC.  Empty if none match.

    Raises:
        ValueError: If ``tableName`` is not registered in :data:`SNAPSHOT_SYNC`.
    """
    _validateSnapshotTable(tableName)
    spec = getSnapshotSpec(tableName)
    cursorFloor = lastCursor or ''
    cursor = conn.execute(
        f"SELECT * FROM {tableName} "  # noqa: S608 -- whitelisted identifiers
        f"WHERE {spec.cursorCol} > ? "
        f"ORDER BY {spec.cursorCol} ASC LIMIT ?",
        (cursorFloor, int(limit)),
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def updateSnapshotCursor(
    conn: sqlite3.Connection,
    tableName: str,
    newCursor: str,
    batchId: str,
    status: str = 'ok',
) -> None:
    """UPSERT the sync_log row for ``tableName``, advancing the snapshot cursor.

    Writes ``last_snapshot_cursor`` (+ ``last_synced_at`` / ``last_batch_id`` /
    ``status``) for the table.  The integer ``last_synced_id`` column is left at
    its default -- snapshot-sync tables have no integer delta cursor.

    The cursor NEVER rewinds: if ``newCursor`` is not strictly greater than the
    stored value (a stale/duplicate push, or a partial batch that did not extend
    the frontier) the existing value is preserved via a ``MAX``-style guard.
    Advancing on a successful push mirrors :func:`updateHighWaterMark`.

    Args:
        conn: Open sqlite3 connection.
        tableName: Must be registered in :data:`SNAPSHOT_SYNC`.
        newCursor: New high-water cursor (typically ``max(row[cursorCol])`` of
            the pushed batch).
        batchId: Batch identifier for the diagnostic trail.
        status: One of :data:`VALID_STATUSES`.  Defaults to ``'ok'``.

    Raises:
        ValueError: If ``tableName`` is not registered, or ``status`` invalid.
    """
    _validateSnapshotTable(tableName)
    _validateStatus(status)
    ensureSnapshotSyncSchema(conn)

    now = _utcIsoTimestamp()
    # COALESCE + comparison keeps the cursor monotonic: if a prior cursor is
    # already >= newCursor, keep it (never rewind on a stale/partial push).
    conn.execute(
        f"""
        INSERT INTO sync_log
            (table_name, last_synced_at, last_batch_id, status,
             {SNAPSHOT_SYNC_CURSOR_COLUMN})
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            last_synced_at = excluded.last_synced_at,
            last_batch_id  = excluded.last_batch_id,
            status         = excluded.status,
            {SNAPSHOT_SYNC_CURSOR_COLUMN} = CASE
                WHEN sync_log.{SNAPSHOT_SYNC_CURSOR_COLUMN} IS NULL
                    THEN excluded.{SNAPSHOT_SYNC_CURSOR_COLUMN}
                WHEN excluded.{SNAPSHOT_SYNC_CURSOR_COLUMN}
                     > sync_log.{SNAPSHOT_SYNC_CURSOR_COLUMN}
                    THEN excluded.{SNAPSHOT_SYNC_CURSOR_COLUMN}
                ELSE sync_log.{SNAPSHOT_SYNC_CURSOR_COLUMN}
            END
        """,  # noqa: S608 -- const identifier interpolation only
        (tableName, now, batchId, status, newCursor),
    )
    conn.commit()
