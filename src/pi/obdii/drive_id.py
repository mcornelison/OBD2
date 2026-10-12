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
# 2026-08-29    | Rex (US-625) | A-9 Root 2: bounded-idle NULL-latch on the
#                               current-drive context.  The context had no idle
#                               bound, so a drive that was over kept claiming
#                               whatever arrived next (drive 51 took 24 rows
#                               ~52 min after its last real sample).
#                               getCurrentDriveId() is now the ATTRIBUTION view
#                               and resolves a stale context to None; the new
#                               getRawCurrentDriveId() is the OWNER view used by
#                               DriveDetector for its own bookkeeping.
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

import logging
import sqlite3
import threading
import time
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
    'getRawCurrentDriveId',
    'clearCurrentDriveId',
    'armDriveIdleBound',
    'noteDriveActivity',
    'isDriveIdStale',
]

logger = logging.getLogger(__name__)


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

# US-625 (A-9 Root 2): the context also carries a BOUNDED IDLE.  Without one
# a drive that is over keeps claiming whatever arrives next -- measured on
# drive 51 (2026-08-28), whose real leg ended 22:49:48 UTC and which then took
# 24 more rows ~52 minutes later, still stamped drive_id=51.  That is
# mis-attribution, and it drags the drive's apparent rate from 438 rows/min
# down to 189 because the late rows stretch its window.
#
# Two views, deliberately asymmetric:
#
# * :func:`getCurrentDriveId` is the ATTRIBUTION view.  Writers use it, and it
#   resolves a stale context to ``None`` -- the same "no active drive" sentinel
#   a pre-crank row already carries.  Rows are still written (US-625 AC-2: the
#   defect is mis-attribution, NOT data loss); they simply stop naming a
#   finished drive.
# * :func:`getRawCurrentDriveId` is the OWNER view.  Only the DriveDetector
#   uses it, because the detector must keep seeing the truth: its own
#   ``drive_end`` row fires exactly AT the idle bound, and a latched read there
#   would stamp NULL and break the drive_start/drive_end pair-up.
#
# The bound is opt-in: an unarmed context behaves exactly as it did pre-US-625,
# so no existing caller changes shape.  Arming happens in ``_startDrive``,
# which is the only place a drive_id can come into existence, so the protection
# is nonetheless complete for every real drive.
#
# THE IDLE CLOCK IS MONOTONIC, NOT WALL-CLOCK, AND THAT IS LOAD-BEARING ON THIS
# DEVICE.  US-620 (same sprint) measured chi-eclipse-01 booting at
# 1970-01-01 and stepping hours forward the moment NTP lands.  A wall-clock
# delta would read that step as hours of sample silence and NULL the remainder
# of a perfectly healthy drive -- turning a fix for mis-attribution into a
# cause of NON-attribution.  time.monotonic() cannot be stepped, so the bound
# measures elapsed time and nothing else.

_currentDriveId: int | None = None
_currentDriveIdLock: threading.RLock = threading.RLock()

# Monotonic reading at the last sample attributed to the live drive, and the
# idle bound in seconds.  ``None`` bound == unarmed == never stale.
_driveActivityMono: float | None = None
_driveIdleBoundSeconds: float | None = None
# One WARNING per stale drive, not one per row -- a stale drive at 438 rows/min
# would otherwise bury the journal in duplicates of a single fact.
_staleReported: bool = False


def setCurrentDriveId(value: int | None) -> None:
    """Set the process-wide current drive_id.

    Intended caller: :class:`src.pi.obdii.drive.detector.DriveDetector`
    on ``_startDrive`` (with the freshly-minted id) and ``_endDrive``
    (with ``None``).

    US-625: also DISARMS any idle bound left over from the previous drive.
    A fresh drive must never inherit its predecessor's staleness -- that would
    make a brand-new drive read as expired the instant it started.  The
    detector re-arms via :func:`armDriveIdleBound` immediately afterwards.

    Args:
        value: New drive_id, or ``None`` to indicate no active drive.
    """
    global _currentDriveId, _driveActivityMono, _driveIdleBoundSeconds
    global _staleReported
    with _currentDriveIdLock:
        _currentDriveId = value
        _driveActivityMono = None
        _driveIdleBoundSeconds = None
        _staleReported = False


def armDriveIdleBound(
    idleBoundSeconds: float, nowMono: float | None = None,
) -> None:
    """Arm the bounded idle for the drive currently held in the context.

    US-625.  Called by :meth:`DriveDetector._startDrive` right after the id is
    minted or re-attached, with the detector's own ``driveEndDurationSeconds``.
    Reusing that value rather than inventing a second idle number is
    deliberate (Rule 2): the number that already decides "this drive is over"
    is the same one that decides "stop attributing rows to it", so the close
    and the latch can never disagree about the same instant.

    No-op when no drive is live -- arming must never conjure an attribution.

    Args:
        idleBoundSeconds: Seconds of sample silence after which the drive_id
            stops being handed to writers.  Non-positive disarms -- which is
            how the existing ``driveEndDurationSeconds <= 0`` test knob keeps
            behaving as it always has (US-229 documents 0 as the
            silence-check-disabled sentinel).
        nowMono: ``time.monotonic()`` reading to anchor the bound at; defaults
            to reading it now.  Injectable so tests are deterministic.
    """
    global _driveActivityMono, _driveIdleBoundSeconds, _staleReported
    with _currentDriveIdLock:
        if _currentDriveId is None:
            return
        if idleBoundSeconds <= 0:
            _driveIdleBoundSeconds = None
            _driveActivityMono = None
            return
        _driveIdleBoundSeconds = float(idleBoundSeconds)
        _driveActivityMono = (
            nowMono if nowMono is not None else time.monotonic()
        )
        _staleReported = False


def noteDriveActivity(nowMono: float | None = None) -> None:
    """Record that a sample was just attributed to the live drive.

    US-625.  Extends the idle window; it never MINTS one.  With no live drive
    this is a no-op, so a late writer cannot resurrect a closed drive.

    The bound measures IDLE, not drive length -- a two-hour leg stays attributed
    for all two hours as long as samples keep arriving.

    Args:
        nowMono: ``time.monotonic()`` reading of the sample; defaults to
            reading it now.
    """
    global _driveActivityMono, _staleReported
    with _currentDriveIdLock:
        if _currentDriveId is None or _driveIdleBoundSeconds is None:
            return
        _driveActivityMono = (
            nowMono if nowMono is not None else time.monotonic()
        )
        _staleReported = False


def isDriveIdStale(nowMono: float | None = None) -> bool:
    """Whether the live drive_id has exceeded its bounded idle.

    US-625.  This is the SINGLE predicate behind both halves of the fix: the
    detector's bounded-idle close asks it, and the attribution view asks it.
    One predicate means "the drive is over" and "stop attributing to it" cannot
    drift apart -- the same discipline US-621 applied to the sync delta.

    Uses ``>=`` so it agrees exactly with the detector's ECU-silence close,
    which fires at ``elapsed >= driveEndDurationSeconds``.

    Returns:
        ``False`` when no drive is live or no bound is armed -- absence of a
        bound is not expiry.
    """
    with _currentDriveIdLock:
        if _currentDriveId is None:
            return False
        if _driveIdleBoundSeconds is None or _driveActivityMono is None:
            return False
        evalMono = nowMono if nowMono is not None else time.monotonic()
        return (evalMono - _driveActivityMono) >= _driveIdleBoundSeconds


def getCurrentDriveId(nowMono: float | None = None) -> int | None:
    """Read the drive_id to ATTRIBUTE a row to, or ``None`` if none applies.

    Intended caller: capture-table writers.  Returned value is passed
    as-is into the INSERT; NULL in the DB is the correct "no drive
    active" sentinel.

    US-625: a drive past its bounded idle resolves to ``None`` rather than to
    the stale id.  The write still happens -- the row is simply unattributed
    instead of wrongly attributed.  This is the load-bearing half of the fix,
    because the bounded-idle CLOSE runs on the orchestrator loop and a starved
    loop is exactly what let drive 51 keep claiming rows; attribution therefore
    has to be safe by construction rather than by the close being timely.

    Args:
        nowMono: ``time.monotonic()`` reading to evaluate staleness at;
            defaults to reading it now.  Injectable so callers and tests can
            be deterministic.
    """
    global _staleReported
    with _currentDriveIdLock:
        if _currentDriveId is None:
            return None
        if not isDriveIdStale(nowMono):
            return _currentDriveId
        if not _staleReported:
            _staleReported = True
            logger.warning(
                "STALE DRIVE ATTRIBUTION SUPPRESSED | drive_id=%s had no ECU "
                "sample for >= %.1fs | rows now written with drive_id=NULL "
                "until a new drive starts",
                _currentDriveId, _driveIdleBoundSeconds,
            )
        return None


def getRawCurrentDriveId() -> int | None:
    """Read the live drive_id WITHOUT the staleness latch (owner view).

    US-625.  Only :class:`~src.pi.obdii.drive.detector.DriveDetector` should
    use this.  The detector owns the context and needs the truth: its
    ``drive_end`` write fires exactly at the idle bound, so a latched read
    there would stamp NULL and break the drive_start/drive_end pair-up that
    server-side analytics group on.  It is also how the close path knows there
    is a stale id to release at all.
    """
    with _currentDriveIdLock:
        return _currentDriveId


def clearCurrentDriveId() -> None:
    """Reset the context to ``None``.  Test-fixture convenience."""
    setCurrentDriveId(None)
