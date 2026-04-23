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
    'VALID_STATUSES',
    'getDeltaRows',
    'getHighWaterMark',
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
SYNC_LOG_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS sync_log (
    table_name      TEXT    PRIMARY KEY,
    last_synced_id  INTEGER NOT NULL DEFAULT 0,
    last_synced_at  TEXT,
    last_batch_id   TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('ok','pending','failed'))
)
"""


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
) -> list[dict[str, Any]]:
    """Return rows from ``tableName`` with ``pk > lastId``, ordered ascending.

    The PK column used for the cursor is :data:`PK_COLUMN[tableName]` -- so
    ``calibration_sessions`` queries ``session_id``, not ``id`` (US-194 fix
    for TD-025).  Snapshot tables (``profiles``, ``vehicle_info``) raise
    ValueError -- they do not fit the delta-by-PK model (see
    :data:`SNAPSHOT_TABLES`).

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

    Returns:
        List of dict rows ordered by the PK column ASC.  Empty if there are
        no rows with ``pk > lastId``.

    Raises:
        ValueError: If ``tableName`` is not in :data:`DELTA_SYNC_TABLES`
            (including the SNAPSHOT_TABLES case, which raises a more
            specific message).
    """
    _validateDeltaTable(tableName)
    pkColumn = PK_COLUMN[tableName]

    # ``tableName`` and ``pkColumn`` are identifiers and cannot be
    # parameterized; the whitelists above are what keep this call safe.
    # ``lastId`` / ``limit`` flow through as ordinary parameters.
    cursor = conn.execute(
        f"SELECT * FROM {tableName} "  # noqa: S608 -- whitelisted identifiers
        f"WHERE {pkColumn} > ? ORDER BY {pkColumn} ASC LIMIT ?",
        (int(lastId), int(limit)),
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def updateHighWaterMark(
    conn: sqlite3.Connection,
    tableName: str,
    lastId: int,
    batchId: str,
    status: str = 'ok',
) -> None:
    """UPSERT the sync_log row for ``tableName``, advancing the high-water mark.

    Inserts if missing, updates if present.  All four mutable columns
    (``last_synced_id``, ``last_synced_at``, ``last_batch_id``, ``status``)
    advance together in a single transaction.

    US-149 note: this function ALWAYS advances ``last_synced_id``.  Callers
    that need to record a failed-push event without advancing the mark must
    use a distinct write path -- never pass the delta-max id with
    ``status='failed'`` expecting the id to be held back.

    Args:
        conn: Open sqlite3 connection.
        tableName: Must be in :data:`IN_SCOPE_TABLES`.
        lastId: New high-water mark (typically ``max(row.id)`` of the batch).
        batchId: Batch identifier for traceability in the server logs.
        status: One of :data:`VALID_STATUSES`.  Defaults to ``'ok'``.

    Raises:
        ValueError: If ``tableName`` or ``status`` is invalid.
    """
    _validateTable(tableName)
    _validateStatus(status)

    now = _utcIsoTimestamp()
    conn.execute(
        """
        INSERT INTO sync_log
            (table_name, last_synced_id, last_synced_at, last_batch_id, status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            last_synced_id = excluded.last_synced_id,
            last_synced_at = excluded.last_synced_at,
            last_batch_id  = excluded.last_batch_id,
            status         = excluded.status
        """,
        (tableName, int(lastId), now, batchId, status),
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
