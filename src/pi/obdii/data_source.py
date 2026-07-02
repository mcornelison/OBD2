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
# 2026-07-01    | Rex (US-424) | F-116 foreign-vehicle marker: add 'foreign' to
#                               DATA_SOURCE_VALUES; derive DATA_SOURCE_CHECK_CLAUSE
#                               + DATA_SOURCE_COLUMN_DDL from the SSOT tuple so a
#                               new value propagates to every capture-table CHECK
#                               (A-4, define-once); add ensureDataSourceCheckWidened
#                               forward-only SQLite CHECK-widen (table-rebuild)
#                               migration for existing DBs.
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

import re
import sqlite3

__all__ = [
    'DATA_SOURCE_VALUES',
    'DATA_SOURCE_DEFAULT',
    'CAPTURE_TABLES',
    'DATA_SOURCE_CHECK_CLAUSE',
    'DATA_SOURCE_COLUMN_DDL',
    'ensureDataSourceColumn',
    'ensureAllCaptureTables',
    'ensureDataSourceCheckWidened',
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
    # US-424 / F-116: foreign-vehicle contamination marker.  A drive captured
    # from a vehicle that is NOT the Eclipse (e.g. the Ford Explorer on drive
    # 33) is tagged 'foreign' so every ``WHERE data_source='real'`` analytics
    # query auto-excludes it with zero consumer changes.  Deliberately NOT
    # 'fixture' -- foreign rows are real captures of a real (wrong) vehicle and
    # must be preserved as evidence, never mistaken for synthetic test data.
    'foreign',
)

# Default value on the live-OBD path.  Matches Spool CR #4 directive:
# "Default to real for the Pi collector live-OBD path so un-tagged rows
# don't silently flip meaning."
DATA_SOURCE_DEFAULT: str = 'real'

# Tables that can receive non-real data and therefore need the column.
# vehicle_info, sync_log, ai_recommendations, alert_log and power_log are
# excluded because they cannot receive sim/replay/fixture data (per sprint
# contract doNotTouch list).  (battery_log was also excluded until US-223
# deleted the table with its sole writer BatteryMonitor.)
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

# Reusable CHECK-clause fragment, DERIVED from :data:`DATA_SOURCE_VALUES` so a
# new enum value (US-424 'foreign') propagates to every consumer without
# hand-editing each schema literal (A-4 define-once).  The per-schema CHECK
# literals in database_schema.py / drive_summary.py / dtc_*_schema.py /
# battery_health.py are pinned equal to this by
# ``tests/pi/data/test_data_source_foreign_marker.py`` so they cannot drift.
DATA_SOURCE_CHECK_CLAUSE: str = (
    "data_source IN (" + ",".join(f"'{v}'" for v in DATA_SOURCE_VALUES) + ")"
)

# Reusable column-definition fragment.  Both the fresh-schema DEFAULT in
# database_schema.py and the migration ALTER TABLE in
# :func:`ensureDataSourceColumn` produce the same physical column.  The CHECK
# constraint enforces the enum at insert time so wrong values fail loudly
# instead of contaminating analytics downstream.
DATA_SOURCE_COLUMN_DDL: str = (
    f"data_source TEXT NOT NULL DEFAULT '{DATA_SOURCE_DEFAULT}' "
    f"CHECK ({DATA_SOURCE_CHECK_CLAUSE})"
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


# ================================================================================
# US-424 / F-116: forward-only SQLite CHECK-widen (table rebuild)
# ================================================================================
#
# SQLite has no ``ALTER TABLE ... MODIFY CHECK`` -- a CHECK constraint can only
# be changed by rebuilding the table (CREATE new / copy rows / DROP old / RENAME
# + recreate indexes).  Adding the ``'foreign'`` value is a pure *widen*: every
# existing row already satisfies the wider constraint, so the rebuild is
# non-destructive (row data is copied verbatim).  Fresh databases never need
# this -- their tables are CREATEd from the already-widened schema DDL; this
# migration only catches Pi databases deployed before US-424.


def _renameCreateTarget(sql: str, oldName: str, newName: str) -> str:
    """Rewrite the ``CREATE TABLE [IF NOT EXISTS] <oldName>`` target to newName.

    Only the create target is renamed; FK clauses that reference *other* tables
    (e.g. realtime_data -> profiles) are left untouched.  ``IF NOT EXISTS`` is
    dropped in the process, which is correct -- the caller DROPs the temp table
    first so the rebuilt table must be created unconditionally.
    """
    return re.sub(
        r"(CREATE\s+TABLE\s+)(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(oldName) + r"\b",
        r"\g<1>" + newName,
        sql,
        count=1,
        flags=re.IGNORECASE,
    )


def ensureDataSourceCheckWidened(
    conn: sqlite3.Connection, tableName: str,
) -> bool:
    """Idempotently widen ``tableName``'s ``data_source`` CHECK to the SSOT enum.

    Rebuilds the table so its ``data_source`` CHECK lists the current
    :data:`DATA_SOURCE_VALUES` (i.e. gains ``'foreign'`` on a pre-US-424 DB).
    The rebuild preserves every row (``INSERT ... SELECT *`` -- identical column
    order, only the CHECK text changes) and recreates the table's named indexes.

    Idempotent + safe:

    * A table whose stored SQL already contains ``'foreign'`` (fresh schema, or a
      prior run) is a **no-op**.
    * A missing table, or a table with no ``data_source`` column, is a no-op.
    * Only tables with **no inbound foreign keys** are safe to rebuild this way;
      ``realtime_data`` (the only table the US-424 ingest guard tags ``'foreign'``)
      qualifies -- nothing FK-references it.

    Args:
        conn: Open sqlite3 Connection.  The caller owns commit semantics.
        tableName: Capture-table name to widen.

    Returns:
        ``True`` iff a rebuild actually ran (the CHECK was previously narrow),
        ``False`` on the no-op paths.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    if row is None or row[0] is None:
        return False
    oldSql: str = row[0]
    if "data_source" not in oldSql:
        return False
    if "'foreign'" in oldSql:
        # Already widened (fresh schema DDL or a prior migration run).
        return False

    # Widen just the data_source CHECK value-list to the current SSOT; every
    # other column / FK / default in the stored DDL is preserved verbatim.
    newTableSql = re.sub(
        r"data_source\s+IN\s*\([^)]*\)",
        DATA_SOURCE_CHECK_CLAUSE,
        oldSql,
        count=1,
    )
    if "'foreign'" not in newTableSql:
        # Defensive: the stored DDL did not match the expected CHECK shape --
        # refuse to rebuild rather than silently produce an unchanged table.
        return False

    tmpName = f"{tableName}__ds_widen_new"
    newTableSql = _renameCreateTarget(newTableSql, tableName, tmpName)

    # Capture the table's named-index DDL so it can be recreated after the
    # rename (dropping the table drops its indexes).  Auto-indexes carry a
    # NULL ``sql`` and are recreated by SQLite from the rebuilt constraints.
    indexRows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name = ? "
        "AND sql IS NOT NULL",
        (tableName,),
    ).fetchall()

    conn.execute(f"DROP TABLE IF EXISTS {tmpName}")
    conn.execute(newTableSql)
    conn.execute(f"INSERT INTO {tmpName} SELECT * FROM {tableName}")
    conn.execute(f"DROP TABLE {tableName}")
    conn.execute(f"ALTER TABLE {tmpName} RENAME TO {tableName}")
    for (indexSql,) in indexRows:
        conn.execute(indexSql)
    return True
