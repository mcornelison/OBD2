################################################################################
# File Name: drive_id.py
# Purpose/Description: Shared constants + idempotent migration helper for the
#                      drive_id column added to Pi capture tables in US-200
#                      (Spool Data v2 Story 2).  Also hosts the Pi-local
#                      drive_counter sequence -- monotonic drive_id
#                      generator backed by a single-row SQLite table.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex (US-200) | Initial -- drive_id schema + counter sequence.
#                               Mirrors the data_source.py migration template
#                               shipped in US-195.
# ================================================================================
################################################################################

"""Per-drive row scoping via a ``drive_id`` column (Spool Priority 3 / US-200).

Problem: Pi capture rows are time-stamped but have no grouping -- multiple
drives + replays + fixtures interleave in ``realtime_data`` with no way to
ask "give me the warmup curve of drive N".

Fix: add a nullable ``drive_id INTEGER`` column to 4 capture tables and
have :class:`src.pi.obdii.engine_state.EngineStateMachine` assign a fresh
monotonic id on each CRANKING transition.  Writers read the current
drive_id from an injected context (see the collector wiring) and stamp
it into every new row.

The id generator is a single-row ``drive_counter`` table.  This choice
is deliberate:

* No wall-clock dependency -- NTP resync could skew time backwards and
  break monotonicity (Invariant #3 in US-200).
* No UUIDs -- integer ids are cheap in analytics queries and play well
  with SQLAlchemy's BigInteger mapping on the server side.
* No in-memory counter -- survives crashes, process restarts, and Pi
  reboots.  The next drive after a crash gets the next free id, not
  id=1 (which would collide with the very first drive).
* Single-row with CHECK(id=1) -- prevents accidental multi-row
  proliferation and lets us use the row's ``last_drive_id`` as the
  lone canonical counter.

The migration helper :func:`ensureDriveIdColumn` is idempotent -- called
from :meth:`src.pi.obdii.database.ObdDatabase.initialize` on every boot
so pre-US-200 databases catch up.  SQLite's ``ALTER TABLE ADD COLUMN``
leaves existing rows with NULL (which US-200 Invariant #4 requires for
the Session 23 149 rows -- they must not be retroactively tagged).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

__all__ = [
    'DRIVE_ID_COLUMN',
    'DRIVE_ID_COLUMN_DDL',
    'DRIVE_ID_TABLES',
    'DRIVE_COUNTER_TABLE',
    'DRIVE_COUNTER_DDL',
    'ensureDriveIdColumn',
    'ensureAllDriveIdColumns',
    'ensureDriveCounter',
    'nextDriveId',
    'makeDriveIdGenerator',
    'setCurrentDriveId',
    'getCurrentDriveId',
    'clearCurrentDriveId',
]


# ================================================================================
# Column + table constants
# ================================================================================

DRIVE_ID_COLUMN: str = 'drive_id'

# Fragment used in both the fresh-schema DDL (database_schema.py) and the
# ALTER TABLE migration below.  Nullable INTEGER -- NULL = "no active
# drive when this row was written" OR "pre-US-200 row; not retagged".
DRIVE_ID_COLUMN_DDL: str = 'drive_id INTEGER'

# Spool Priority 3 enumeration of Pi-side tables that receive per-row
# drive_id tagging.  Server-side additions (drive_statistics, drive_summary,
# analysis_history) are handled in src/server/db/models.py -- server-only
# tables don't sync back.  profiles / vehicle_info / calibration_sessions
# / ai_recommendations / power_log are deliberately omitted: they are
# per-install or per-device, not per-drive.  (battery_log was in this
# list until US-223 deleted the table with its writer BatteryMonitor.)
DRIVE_ID_TABLES: tuple[str, ...] = (
    'realtime_data',
    'connection_log',
    'statistics',
    'alert_log',
)

DRIVE_COUNTER_TABLE: str = 'drive_counter'

# Single-row counter table.  CHECK(id=1) prevents multi-row accidents;
# last_drive_id starts at 0 so the first call to nextDriveId() returns 1.
DRIVE_COUNTER_DDL: str = (
    f"CREATE TABLE IF NOT EXISTS {DRIVE_COUNTER_TABLE} ("
    "    id INTEGER PRIMARY KEY CHECK (id = 1),"
    "    last_drive_id INTEGER NOT NULL DEFAULT 0"
    ")"
)


# ================================================================================
# Private helpers
# ================================================================================

def _hasColumn(
    conn: sqlite3.Connection, tableName: str, columnName: str,
) -> bool:
    rows = conn.execute(f"PRAGMA table_info({tableName})").fetchall()
    return any(row[1] == columnName for row in rows)


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


# ================================================================================
# Schema migration
# ================================================================================

def ensureDriveIdColumn(
    conn: sqlite3.Connection, tableName: str,
) -> bool:
    """Add ``drive_id`` to ``tableName`` if not already present.

    Idempotent: column exists -> no-op.  Table does not exist -> no-op
    (the fresh schema DDL will create it with the column already baked
    in the first time ``ObdDatabase.initialize`` runs).

    Also creates an index ``IX_<table>_drive_id`` if missing.  The
    index matters for per-drive analytics queries
    (``WHERE drive_id = ?``) that otherwise scan the entire table.

    Args:
        conn: Open sqlite3 connection.  Commit is caller's responsibility.
        tableName: Capture-table name.  Expected to be in
            :data:`DRIVE_ID_TABLES` but this function does not enforce
            that -- callers own the whitelist.

    Returns:
        True if ALTER TABLE ran, False otherwise.
    """
    if not _tableExists(conn, tableName):
        return False
    ran = False
    if not _hasColumn(conn, tableName, DRIVE_ID_COLUMN):
        # SQLite leaves existing rows with NULL for the new column.
        # Invariant #4: that's the correct behavior for Session 23's
        # 149 rows -- they remain untagged rather than being
        # retroactively assigned a fabricated drive_id.
        conn.execute(
            f"ALTER TABLE {tableName} ADD COLUMN {DRIVE_ID_COLUMN_DDL}"
        )
        ran = True
    indexName = f"IX_{tableName}_{DRIVE_ID_COLUMN}"
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {indexName} "
        f"ON {tableName}({DRIVE_ID_COLUMN})"
    )
    return ran


def ensureAllDriveIdColumns(conn: sqlite3.Connection) -> list[str]:
    """Run :func:`ensureDriveIdColumn` across every in-scope capture table.

    Returns the list of tables that actually had the column added (the
    indexes are always created/verified regardless -- they're
    idempotent).
    """
    migrated: list[str] = []
    for tableName in DRIVE_ID_TABLES:
        if ensureDriveIdColumn(conn, tableName):
            migrated.append(tableName)
    return migrated


# ================================================================================
# Counter sequence
# ================================================================================

def ensureDriveCounter(conn: sqlite3.Connection) -> None:
    """Create the ``drive_counter`` singleton row if missing.

    Safe to call on every boot; re-creation is a no-op and the INSERT
    OR IGNORE preserves any existing counter value.
    """
    conn.execute(DRIVE_COUNTER_DDL)
    conn.execute(
        f"INSERT OR IGNORE INTO {DRIVE_COUNTER_TABLE} "
        f"(id, last_drive_id) VALUES (1, 0)"
    )


def nextDriveId(conn: sqlite3.Connection) -> int:
    """Atomically increment + return the next drive_id.

    Uses SQLite's transactional UPDATE -- the read-after-write is safe
    on a single connection because SQLite serializes writes.  For
    multi-connection setups the caller should wrap in an explicit
    BEGIN IMMEDIATE.
    """
    conn.execute(
        f"UPDATE {DRIVE_COUNTER_TABLE} "
        f"SET last_drive_id = last_drive_id + 1 WHERE id = 1"
    )
    row = conn.execute(
        f"SELECT last_drive_id FROM {DRIVE_COUNTER_TABLE} WHERE id = 1"
    ).fetchone()
    if row is None:
        raise RuntimeError(
            f"{DRIVE_COUNTER_TABLE} singleton missing; call "
            "ensureDriveCounter() before nextDriveId()"
        )
    return int(row[0])


def makeDriveIdGenerator(
    conn: sqlite3.Connection,
) -> Callable[[], int]:
    """Bind a ``conn`` into a zero-arg generator for EngineStateMachine.

    The state machine only needs ``Callable[[], int]``; this wrapper
    supplies the connection so the machine itself stays DB-agnostic.
    """

    def _gen() -> int:
        return nextDriveId(conn)

    return _gen


# ================================================================================
# Current-drive context (module-level)
# ================================================================================
#
# Writers (logReading, analysis engine, alert manager, drive-event log)
# pull the currently-active drive_id from this module at INSERT time.
# The DriveDetector updates it on _startDrive / _endDrive so that every
# row written during the drive carries the matching id without each
# writer needing a reference back to the detector.
#
# Threading note: the Pi collector is single-threaded at the poll loop;
# the DriveDetector runs on the same thread that calls queryAndLogParameter
# so writers always see a consistent view.  The lock is defensive --
# a future multi-threaded refactor will not silently split drive_id
# across readers and writers.

_currentDriveId: int | None = None
_currentDriveIdLock: threading.Lock = threading.Lock()


def setCurrentDriveId(value: int | None) -> None:
    """Set the process-wide current drive_id.

    Intended caller: :class:`src.pi.obdii.drive.detector.DriveDetector`
    on ``_startDrive`` (with the freshly-minted id) and ``_endDrive``
    (with ``None``).

    Args:
        value: New drive_id, or ``None`` to indicate no active drive.
    """
    global _currentDriveId
    with _currentDriveIdLock:
        _currentDriveId = value


def getCurrentDriveId() -> int | None:
    """Read the current drive_id, or ``None`` if no drive is active.

    Intended caller: capture-table writers.  Returned value is passed
    as-is into the INSERT; NULL in the DB is the correct "no drive
    active" sentinel.
    """
    with _currentDriveIdLock:
        return _currentDriveId


def clearCurrentDriveId() -> None:
    """Reset the context to ``None``.  Test-fixture convenience."""
    setCurrentDriveId(None)
