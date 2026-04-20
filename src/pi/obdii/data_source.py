################################################################################
# File Name: data_source.py
# Purpose/Description: Shared constants + idempotent migration helper for the
#                      data_source column added to Pi capture tables in US-195
#                      (Spool CR #4).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex (US-195) | Initial -- data_source enum + migration helper
# ================================================================================
################################################################################

"""Data-source tagging for Pi capture tables (Spool CR #4 / US-195).

Every row written into a Pi capture table carries a ``data_source`` tag
identifying its origin. Analytics and AI prompting on the server filter
to ``'real'`` so baselines are not contaminated by replay, physics_sim,
or fixture data.

The Pi SQLite schema declares the column with a DEFAULT of ``'real'``
and a CHECK constraint matching :data:`DATA_SOURCE_VALUES`, so the
live-OBD path inherits the right tag without a per-writer edit. Only
non-real writers (flat-file replay, fixture loaders) need to pass an
explicit value.

:func:`ensureDataSourceColumn` handles idempotent in-place migration of
pre-US-195 databases. It is called from
:meth:`src.pi.obdii.database.ObdDatabase.initialize` on every boot, so a
Pi that was running pre-US-195 code catches up the next time the service
starts. SQLite's ``ALTER TABLE ADD COLUMN`` applies the DEFAULT to every
existing row in place -- no backfill UPDATE needed.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    'DATA_SOURCE_VALUES',
    'DATA_SOURCE_DEFAULT',
    'CAPTURE_TABLES',
    'DATA_SOURCE_COLUMN_DDL',
    'ensureDataSourceColumn',
    'ensureAllCaptureTables',
]


# ================================================================================
# Enum + scope
# ================================================================================

# Closed set of valid data_source values (Spool CR #4 line 140).  Ordering is
# deliberate: live -> replay -> deprecated-simulator -> test-fixture, so the
# tuple reads left-to-right from the production path to the synthetic path.
DATA_SOURCE_VALUES: tuple[str, ...] = (
    'real',
    'replay',
    'physics_sim',
    'fixture',
)

# Default value on the live-OBD path.  Matches Spool CR #4 directive:
# "Default to real for the Pi collector live-OBD path so un-tagged rows
# don't silently flip meaning."
DATA_SOURCE_DEFAULT: str = 'real'

# Tables that can receive non-real data and therefore need the column.
# vehicle_info, sync_log, ai_recommendations, alert_log, battery_log and
# power_log are excluded because they cannot receive sim/replay/fixture
# data (per sprint contract doNotTouch list).
CAPTURE_TABLES: tuple[str, ...] = (
    'realtime_data',
    'connection_log',
    'statistics',
    'calibration_sessions',
    'profiles',
)


# ================================================================================
# DDL fragment
# ================================================================================

# Reusable column-definition fragment.  Both the fresh-schema DEFAULT in
# database_schema.py and the migration ALTER TABLE in
# :func:`ensureDataSourceColumn` produce the same physical column.  The CHECK
# constraint enforces the enum at insert time so wrong values fail loudly
# instead of contaminating analytics downstream.
DATA_SOURCE_COLUMN_DDL: str = (
    "data_source TEXT NOT NULL DEFAULT 'real' "
    "CHECK (data_source IN ('real','replay','physics_sim','fixture'))"
)


# ================================================================================
# Migration helpers
# ================================================================================

def _hasColumn(
    conn: sqlite3.Connection, tableName: str, columnName: str,
) -> bool:
    """Return True if ``tableName`` already has ``columnName``.

    Uses ``PRAGMA table_info`` because SQLite has no INFORMATION_SCHEMA.
    """
    rows = conn.execute(f"PRAGMA table_info({tableName})").fetchall()
    return any(row[1] == columnName for row in rows)


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    """Return True if ``tableName`` exists in the sqlite_master catalog."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


def ensureDataSourceColumn(
    conn: sqlite3.Connection, tableName: str,
) -> bool:
    """Add ``data_source`` to ``tableName`` if not already present.

    Idempotent: if the column already exists, this is a no-op. If the
    table itself doesn't exist yet (first-boot ordering), also a no-op --
    the schema will create it with the column via the fresh-table DDL.

    Args:
        conn: Open sqlite3 connection.  The caller owns commit semantics;
            this function issues the ALTER TABLE statement but does not
            commit, matching the surrounding ``initialize()`` transaction
            scope.
        tableName: Capture-table name.  Expected to be in
            :data:`CAPTURE_TABLES` but this function does not enforce
            that -- callers own the whitelist.

    Returns:
        True if an ALTER TABLE ran, False if the column was already
        present or the table did not exist.
    """
    if not _tableExists(conn, tableName):
        return False
    if _hasColumn(conn, tableName, 'data_source'):
        return False
    # SQLite applies the DEFAULT to every existing row as part of the
    # ALTER TABLE, so no backfill UPDATE is needed.  The CHECK on the new
    # column only applies to subsequent INSERT/UPDATE per SQLite semantics.
    conn.execute(
        f"ALTER TABLE {tableName} ADD COLUMN {DATA_SOURCE_COLUMN_DDL}"
    )
    return True


def ensureAllCaptureTables(conn: sqlite3.Connection) -> list[str]:
    """Run :func:`ensureDataSourceColumn` across every capture table.

    Args:
        conn: Open sqlite3 connection.

    Returns:
        List of table names that actually had the column added (useful
        for logging).  Empty on fully-migrated databases.
    """
    migrated: list[str] = []
    for tableName in CAPTURE_TABLES:
        if ensureDataSourceColumn(conn, tableName):
            migrated.append(tableName)
    return migrated
