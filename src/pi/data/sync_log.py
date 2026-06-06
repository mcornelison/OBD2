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
  ``calibration_sessions``.
- Excluded (Pi-only -- never uploaded): ``power_log``.
  (``battery_log`` was also excluded historically but was deleted in US-223
  when its sole writer :class:`BatteryMonitor` was removed.)

Any call that references a table outside :data:`IN_SCOPE_TABLES` raises
:class:`ValueError`.  This doubles as the SQL-injection guard: the table
name is interpolated into SQL (it is an identifier, not a value, so the
driver cannot parameterize it), and the whitelist is the only defense.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from src.common.time.helper import utcIsoNow

__all__ = [
    'DELTA_SYNC_TABLES',
    'IN_SCOPE_TABLES',
    'PK_COLUMN',
    'SNAPSHOT_TABLES',
    'SYNC_LOG_SCHEMA',
    'SYNC_MODIFIED_AT_COLUMN',
    'SYNC_UPDATE_TABLES_PK',
    'VALID_STATUSES',
    'ensureSyncModifiedAtSchema',
    'getDeltaRows',
    'getHighWaterMark',
    'getModifiedHighWaterMark',
    'initDb',
    'updateHighWaterMark',
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
# and ``tests/scripts/test_seed_pi_fixture.py``.  power_log is intentionally
# absent: it is local-only Pi health telemetry that the server does not want.
# (battery_log was also absent historically but the table was removed in
# US-223 when BatteryMonitor was deleted.)
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
SYNC_LOG_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS sync_log (
    table_name              TEXT    PRIMARY KEY,
    last_synced_id          INTEGER NOT NULL DEFAULT 0,
    last_synced_at          TEXT,
    last_batch_id           TEXT,
    status                  TEXT    NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('ok','pending','failed')),
    last_synced_modified_at TEXT
)
"""

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
