################################################################################
# File Name: backlog.py
# Purpose/Description: US-621 -- read-only sync-backlog reader for the shutdown
#                      custody record: "how many captured rows has the server
#                      still not got?". Answers with one of three verdicts
#                      (delivered / outstanding / unknown) which are never
#                      conflated, opens its own stdlib sqlite3 connection, and
#                      NEVER raises -- it runs immediately before poweroff.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- outstanding-row reader behind the
#                                pre-poweroff sync custody record. Counts route
#                                through sync_log.countDeltaRows so the number
#                                reported is the number a push would send.
# 2026-09-17    | Rex (US-789) | ROW-level exclusion (RowExclusion): one primary
#                                key leaves the count and is reported in
#                                SyncBacklog.excludedRows -- never a table.
# ================================================================================
################################################################################
"""Read-only outstanding-row (sync backlog) reader for the poweroff path.

Deliberately built on stdlib ``sqlite3`` and :mod:`src.pi.data.sync_log` only.
Importing ``pi.obdii`` for a ``connect()`` would drag that whole package
(display imports included) into a shutdown-critical graph -- the V0.27.12-DOA
import class that :func:`src.pi.power.power_watch.__main__.buildDrainCloseHook`
already refuses for the same reason.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from src.pi.data import sync_log

logger = logging.getLogger(__name__)

__all__ = [
    "BACKLOG_DELIVERED",
    "BACKLOG_OUTSTANDING",
    "BACKLOG_UNKNOWN",
    "RowExclusion",
    "SyncBacklog",
    "countOutstandingRows",
]

# The three verdicts. They are distinct STRINGS rather than a bool + a count
# because the whole point of US-621 is that "shut down with an empty queue" and
# "shut down without being able to tell" must never render the same way.
BACKLOG_DELIVERED = "DELIVERED"
BACKLOG_OUTSTANDING = "OUTSTANDING"
BACKLOG_UNKNOWN = "UNKNOWN"

# Busy timeout used when no bound is supplied. The caller normally passes the
# shutdown path's own per-task bound so a locked database can never delay a
# poweroff; this default only covers direct/diagnostic use.
DEFAULT_BUSY_TIMEOUT_SEC = 5.0


@dataclass(frozen=True, slots=True)
class RowExclusion:
    """ONE row, named by primary key, left out of an outstanding count (US-789).

    Deliberately a single primary key and never a table. Excluding a whole
    table is ``excludeTables``' job and is a different claim ("this table is
    not custody's business"); this type says "this ONE row is known and is
    reported elsewhere". A table-wide exclusion would be a blind spot a
    genuinely stranded row could hide in.

    Attributes:
        table: A delta-sync table name.
        pk: The row's primary-key value in that table's ``PK_COLUMN``.
        reason: Why the row is excluded, for the operator reading the record.
    """

    table: str
    pk: int
    reason: str


@dataclass(frozen=True, slots=True)
class SyncBacklog:
    """What the Pi still owes the server, as measured at a point in time.

    Attributes:
        perTable: Outstanding row count per table that could be READ. A table
            absent from this DB contributes nothing and does not appear -- it
            cannot be holding unsynced rows.
        unreadableTables: Tables whose delta could not be resolved. Their rows
            are neither counted nor assumed absent, which is what makes
            ``total`` a LOWER bound whenever this is non-empty.
        error: Free-text cause when the database could not be opened at all.
        excludedRows: US-789 -- the requested :class:`RowExclusion` rows that
            WERE outstanding and so were taken out of ``perTable``. A requested
            exclusion whose row was not outstanding changed nothing and is not
            listed, so this never claims a row was hidden that was not.
    """

    perTable: dict[str, int] = field(default_factory=dict)
    unreadableTables: tuple[str, ...] = ()
    error: str | None = None
    excludedRows: tuple[RowExclusion, ...] = ()

    @property
    def total(self) -> int:
        """Outstanding rows across every table that could be read.

        A LOWER BOUND when :attr:`isComplete` is False -- consult that before
        quoting this as "the" backlog.
        """
        return sum(self.perTable.values())

    @property
    def isComplete(self) -> bool:
        """True when every in-scope table was successfully read."""
        return not self.unreadableTables

    @property
    def verdict(self) -> str:
        """One of DELIVERED / OUTSTANDING / UNKNOWN.

        Precedence is deliberate: **outstanding beats unknown beats
        delivered.**

        * Any measured outstanding row makes the verdict OUTSTANDING even if
          something else was unreadable -- a real, actionable count must not be
          buried under "unknown".
        * Otherwise, an unreadable table -- or a database that could not be
          opened at all (``error``) -- makes it UNKNOWN. Not looking is not the
          same as looking and finding nothing; claiming DELIVERED here is
          exactly the false-healthy report this story exists to end. The
          ``error`` arm is load-bearing: a failed open leaves ``perTable``
          empty, which without it sums to 0 and renders as a clean bill of
          health for a Pi whose database could not even be read.
        * Only a fully-read, fully-empty queue is DELIVERED.
        """
        if self.total > 0:
            return BACKLOG_OUTSTANDING
        if self.unreadableTables or self.error is not None:
            return BACKLOG_UNKNOWN
        return BACKLOG_DELIVERED

    def describe(self) -> str:
        """One operator-readable line stating the verdict and its evidence.

        Always names the verdict, so a log scrape can classify the shutdown
        without parsing numbers, and always carries the evidence, so a bare
        verdict is never an unexplainable assertion.
        """
        if self.verdict == BACKLOG_DELIVERED:
            return (
                f"{BACKLOG_DELIVERED} -- every captured row is on the server "
                f"({len(self.perTable)} table(s) checked, 0 outstanding)"
            )
        if self.verdict == BACKLOG_UNKNOWN:
            cause = f" ({self.error})" if self.error else ""
            unread = ", ".join(self.unreadableTables) or "none readable"
            return (
                f"{BACKLOG_UNKNOWN} -- could not determine what is outstanding"
                f"{cause}; unreadable: {unread}"
            )
        detail = ", ".join(
            f"{name}={count}"
            for name, count in sorted(
                self.perTable.items(), key=lambda kv: (-kv[1], kv[0])
            )
            if count
        )
        bound = "at least " if not self.isComplete else ""
        suffix = ""
        if self.unreadableTables:
            suffix = f"; unreadable: {', '.join(self.unreadableTables)}"
        return (
            f"{BACKLOG_OUTSTANDING} -- {bound}{self.total} row(s) never left "
            f"the Pi [{detail}]{suffix}"
        )


def _existingTables(conn: sqlite3.Connection) -> set[str]:
    """Names of tables that actually exist in this database."""
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _countOneTable(conn: sqlite3.Connection, tableName: str) -> int:
    """Outstanding rows for one delta table, using its live sync cursors."""
    lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
    lastModifiedAt = None
    if tableName in sync_log.SYNC_UPDATE_TABLES_PK:
        lastModifiedAt = sync_log.getModifiedHighWaterMark(conn, tableName)
    return sync_log.countDeltaRows(
        conn, tableName, lastId, lastModifiedAt=lastModifiedAt
    )


def _countExcludedOutstanding(
    conn: sqlite3.Connection,
    tableName: str,
    pks: Collection[int],
) -> set[int]:
    """Which of ``pks`` are outstanding in ``tableName`` right now (US-789).

    Uses the SAME delta predicate :func:`sync_log.countDeltaRows` and
    :func:`sync_log.getDeltaRows` use -- the one US-621 extracted so that a
    count can never disagree with what a push would send. A second,
    hand-written "is this row outstanding?" test is exactly the kind of second
    opinion that predicate exists to prevent.
    """
    lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
    lastModifiedAt = None
    if tableName in sync_log.SYNC_UPDATE_TABLES_PK:
        lastModifiedAt = sync_log.getModifiedHighWaterMark(conn, tableName)
    pkColumn = sync_log.PK_COLUMN[tableName]
    whereSql, whereParams = sync_log._deltaPredicate(  # noqa: SLF001 -- the one shared predicate
        conn, tableName, lastId, lastModifiedAt,
    )
    placeholders = ", ".join("?" for _ in pks)
    rows = conn.execute(
        f"SELECT {pkColumn} FROM {tableName} "  # noqa: S608 -- whitelisted identifiers
        f"WHERE ({whereSql}) AND {pkColumn} IN ({placeholders})",
        (*whereParams, *(int(pk) for pk in pks)),
    ).fetchall()
    return {int(row[0]) for row in rows}


def _tablesInScope(
    excludeTables: Collection[str],
    onlyTables: Collection[str] | None,
) -> list[str]:
    """Resolve which delta tables this count covers, in deterministic order.

    ``onlyTables`` narrows first, ``excludeTables`` removes after -- so an
    explicit exclusion always wins, and asking for a table in both is answered
    the safe way (it is left out) rather than the surprising way.

    Args:
        excludeTables: Tables to leave out entirely.
        onlyTables: When not None, restrict to these tables.

    Returns:
        Sorted table names.
    """
    scope = set(sync_log.DELTA_SYNC_TABLES)
    if onlyTables is not None:
        scope &= set(onlyTables)
    scope -= set(excludeTables)
    return sorted(scope)


def countOutstandingRows(
    dbPath: str,
    *,
    busyTimeoutSec: float = DEFAULT_BUSY_TIMEOUT_SEC,
    excludeTables: Collection[str] = (),
    onlyTables: Collection[str] | None = None,
    excludeRows: Iterable[RowExclusion] = (),
) -> SyncBacklog:
    """Measure what the Pi still owes the server. READ-ONLY. NEVER raises.

    Opens the database, walks every delta-sync table that exists, and counts
    the rows past each table's high-water mark. Snapshot tables are excluded:
    they have no monotonic cursor, so "behind by N" is not defined for them
    (the same exclusion :func:`sync_log.getDeltaRows` makes).

    This function performs NO writes -- not even the idempotent
    ``sync_log.initDb`` that most readers in this codebase are happy to call.
    A database missing its ``sync_log`` reports UNKNOWN rather than being
    repaired: the poweroff path was asked to look, not to change anything, and
    a Pi that is losing power is the worst possible moment to start writing
    schema.

    Args:
        dbPath: Path to the Pi SQLite database. An empty path is not guessed;
            it resolves to UNKNOWN.
        busyTimeoutSec: SQLite busy timeout. Callers on the shutdown path pass
            the bound that path already owns, so a locked database can never
            delay a poweroff.
        excludeTables: Tables to leave out of the count entirely (US-766).
            An EXCLUDED table is not an UNREADABLE one: it contributes nothing
            to ``perTable`` and nothing to ``unreadableTables``, so excluding it
            cannot flip the verdict to UNKNOWN. The shutdown drain passes
            ``SHUTDOWN_DRAIN_EXCLUDED_TABLES`` here, because a multi-million-row
            EDR archive must never make a clean poweroff report OUTSTANDING.
        onlyTables: When not None, count ONLY these tables. Used to report the
            EDR backlog beside the verdict rather than inside it.
        excludeRows: US-789 -- individual rows, by primary key, to leave out
            of the count. Each one that was actually outstanding is subtracted
            from its table's count and listed in ``excludedRows``; every OTHER
            row in that table still counts. A table whose count fails leaves
            its exclusions unapplied rather than guessed.

    Returns:
        A :class:`SyncBacklog`. On any failure to open or read the database the
        result is UNKNOWN with ``error`` set -- never an empty-looking
        DELIVERED.
    """
    if not dbPath:
        return SyncBacklog(error="no pi.database.path configured")

    conn: sqlite3.Connection | None = None
    try:
        # uri=False + a plain connect() would CREATE a missing file, which
        # would then read as an empty (DELIVERED) queue -- a fabricated clean
        # bill of health for a Pi whose database has gone missing. Open
        # read-only through the URI form so an absent file fails loudly here.
        conn = sqlite3.connect(
            f"file:{dbPath}?mode=ro",
            uri=True,
            timeout=busyTimeoutSec,
        )
        existing = _existingTables(conn)
        perTable: dict[str, int] = {}
        unreadable: list[str] = []
        excludedByTable: dict[str, list[RowExclusion]] = {}
        for exclusion in excludeRows:
            excludedByTable.setdefault(exclusion.table, []).append(exclusion)
        applied: list[RowExclusion] = []
        for tableName in _tablesInScope(excludeTables, onlyTables):
            if tableName not in existing:
                # A table this DB has never created cannot hold unsynced rows.
                # Counting it as unreadable would make every healthy Pi report
                # UNKNOWN forever and the signal would be worthless.
                continue
            try:
                count = _countOneTable(conn, tableName)
                wanted = excludedByTable.get(tableName, [])
                if wanted and count:
                    hit = _countExcludedOutstanding(
                        conn, tableName, {e.pk for e in wanted},
                    )
                    matched = [e for e in wanted if e.pk in hit]
                    count -= len(hit)
                    applied.extend(matched)
                perTable[tableName] = count
            except Exception as exc:  # noqa: BLE001 -- one bad table must not blind the rest
                logger.warning(
                    "sync backlog: %s unreadable (%s) -- counted as UNKNOWN, "
                    "not as zero",
                    tableName,
                    exc,
                )
                unreadable.append(tableName)
        return SyncBacklog(
            perTable=perTable,
            unreadableTables=tuple(unreadable),
            excludedRows=tuple(applied),
        )
    except Exception as exc:  # noqa: BLE001 -- runs before poweroff; never raise
        logger.warning("sync backlog: database unreadable (%s)", exc)
        return SyncBacklog(error=str(exc))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110 -- closing must not raise here
                pass
