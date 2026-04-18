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

The module is deliberately decoupled from :mod:`src.pi.obd.database` so the
sync contract evolves without dragging OBD schema changes through the same
module (per the PM scope on US-148; sync bookkeeping lives next to, not
inside, the OBD DB).  Callers pass in a ``sqlite3.Connection``; this module
does no connection management.

Scope tables (per docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md
section 2.1):

- Included: ``realtime_data``, ``statistics``, ``profiles``, ``vehicle_info``,
  ``ai_recommendations``, ``connection_log``, ``alert_log``,
  ``calibration_sessions``.
- Excluded (Pi-only -- never uploaded): ``battery_log``, ``power_log``.

Any call that references a table outside :data:`IN_SCOPE_TABLES` raises
:class:`ValueError`.  This doubles as the SQL-injection guard: the table
name is interpolated into SQL (it is an identifier, not a value, so the
driver cannot parameterize it), and the whitelist is the only defense.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

__all__ = [
    'IN_SCOPE_TABLES',
    'VALID_STATUSES',
    'SYNC_LOG_SCHEMA',
    'initDb',
    'getDeltaRows',
    'updateHighWaterMark',
    'getHighWaterMark',
]


# ================================================================================
# Configuration
# ================================================================================

# Tables eligible for Pi -> server delta sync.  battery_log and power_log are
# intentionally absent: those are local-only health telemetry that the server
# does not want.  See specs/architecture.md "Sync Log Table" section.
IN_SCOPE_TABLES: frozenset[str] = frozenset({
    'realtime_data',
    'statistics',
    'profiles',
    'vehicle_info',
    'ai_recommendations',
    'connection_log',
    'alert_log',
    'calibration_sessions',
})

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

    Matches the timestamp format used elsewhere in Pi logs (e.g. connection_log).
    """
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


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
    """Return rows from ``tableName`` with ``id > lastId``, ordered ascending.

    Args:
        conn: An open sqlite3 connection.  ``row_factory`` does not need to
            be configured -- this function builds dicts itself so callers get
            the same shape regardless of upstream connection settings.
        tableName: Must be a member of :data:`IN_SCOPE_TABLES`.
        lastId: Last successfully-synced id (from :func:`getHighWaterMark`).
            ``0`` means "start from the beginning".
        limit: Max rows to return.  Use the configured batch size.

    Returns:
        List of dict rows ordered by ``id`` ASC.  Empty if there are no rows
        with ``id > lastId``.

    Raises:
        ValueError: If ``tableName`` is not in :data:`IN_SCOPE_TABLES`.
    """
    _validateTable(tableName)

    # ``tableName`` is an identifier and cannot be parameterized; the
    # whitelist above is what keeps this call safe.  ``lastId`` / ``limit``
    # flow through as ordinary parameters.
    cursor = conn.execute(
        f"SELECT * FROM {tableName} WHERE id > ? ORDER BY id ASC LIMIT ?",
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
