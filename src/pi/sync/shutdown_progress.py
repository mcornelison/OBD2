################################################################################
# File Name: shutdown_progress.py
# Purpose/Description: US-883-b -- the shutdown sync's progress for the S114
#                      sync bar: rows still owed at key-off (waitingAtKeyOff)
#                      and how many of THOSE rows the server has since acked
#                      (confirmed), read from the acked sync marks. Read-only,
#                      never raises -- it runs between drain passes.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-23    | Rex (US-883-b) | Initial -- key-off snapshot + confirmed from
#                                  the acked marks (Atlas O3, E1, Rule 13 gaps 2-3).
# ================================================================================
################################################################################
"""Shutdown sync progress: ``{waitingAtKeyOff, confirmed}`` from the acked marks.

At the start of the shutdown sync (after smoothing) the rows each counted table
still owes are SNAPSHOTTED: the marks at that moment, plus ``MAX(pk)`` and
``MAX(_sync_modified_at)`` as upper bounds. ``waitingAtKeyOff`` is the COUNT of
that set (ids gap, so never an id span). After each drain pass, ``remaining`` is
the part of the set that the same delta predicate still selects under the marks
NOW, and ``confirmed = waitingAtKeyOff - remaining``. The marks advance only on
the server's post-commit stored ack, so a re-sent batch never moves
``confirmed`` (Atlas O3) and per-push stored counts are never summed.

Accepted bias (Atlas): a snapshot row UPDATEd again during the drain is
re-stamped past ``keyOffModified``, leaves the bounded set and reads as
confirmed early. No OBD read runs during a key-off drain, so the dtc_log
``last_seen`` bump that would cause it does not occur.

Built on stdlib ``sqlite3`` and :mod:`src.pi.data.sync_log` only, like
:mod:`src.pi.sync.backlog`, so the powerwatch import graph stays small.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.common.edr.sync_contract import SHUTDOWN_DRAIN_EXCLUDED_TABLES
from src.pi.data import sync_log

logger = logging.getLogger(__name__)

__all__ = [
    "KeyOffSnapshot",
    "ShutdownSyncProgress",
    "TableKeyOff",
    "countRemaining",
    "countedTables",
    "takeKeyOffSnapshot",
]


def countedTables() -> tuple[str, ...]:
    """The tables the sync bar counts (Atlas Rule 13 gap 3). No new list.

    Every delta-sync table (integer cursor; the update tables INCLUDED --
    drive_summary and dtc_log carry inserts) minus what ``readSyncHealth``
    names ``notCounted`` (the snapshot tables) minus the drain's EDR
    exclusion (``SHUTDOWN_DRAIN_EXCLUDED_TABLES``).

    Returns:
        The table names, sorted.
    """
    notCounted = sync_log.SNAPSHOT_TABLES | sync_log.snapshotSyncTables()
    return tuple(
        sorted(sync_log.DELTA_SYNC_TABLES - notCounted - SHUTDOWN_DRAIN_EXCLUDED_TABLES)
    )


@dataclass(frozen=True, slots=True)
class TableKeyOff:
    """One counted table at key-off.

    Attributes:
        table: The delta table.
        lastId: Its id mark at the snapshot.
        lastModifiedAt: Its modified_at mark at the snapshot (update tables).
        keyOffId: ``MAX(pk)`` at the snapshot.
        keyOffModified: ``MAX(_sync_modified_at)`` at the snapshot, or None.
        waiting: Rows in this table's snapshot set.
    """

    table: str
    lastId: int
    lastModifiedAt: str | None
    keyOffId: int
    keyOffModified: str | None
    waiting: int


@dataclass(frozen=True, slots=True)
class KeyOffSnapshot:
    """The rows still owed at key-off, per counted table."""

    tables: tuple[TableKeyOff, ...] = ()

    @property
    def waitingAtKeyOff(self) -> int:
        """Rows owed at key-off, summed over the counted tables."""
        return sum(t.waiting for t in self.tables)


def _openReadOnly(dbPath: str, busyTimeoutSec: float) -> sqlite3.Connection:
    """Open the Pi database read-only; an absent file raises, never creates."""
    return sqlite3.connect(f"file:{dbPath}?mode=ro", uri=True, timeout=busyTimeoutSec)


def _existingTables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _marks(conn: sqlite3.Connection, tableName: str) -> tuple[int, str | None]:
    """The table's acked marks now: (id mark, modified_at mark or None)."""
    lastId, _, _, _ = sync_log.getHighWaterMark(conn, tableName)
    lastModifiedAt = None
    if tableName in sync_log.SYNC_UPDATE_TABLES_PK:
        lastModifiedAt = sync_log.getModifiedHighWaterMark(conn, tableName)
    return lastId, lastModifiedAt


def takeKeyOffSnapshot(dbPath: str, *, busyTimeoutSec: float) -> KeyOffSnapshot | None:
    """Snapshot what every counted table owes now. READ-ONLY. NEVER raises.

    Args:
        dbPath: The Pi database.
        busyTimeoutSec: SQLite busy timeout for the read-only open.

    Returns:
        The snapshot, or None when any counted table could not be read -- a
        partial count would be a confident wrong total.
    """
    if not dbPath:
        return None
    conn: sqlite3.Connection | None = None
    try:
        conn = _openReadOnly(dbPath, busyTimeoutSec)
        existing = _existingTables(conn)
        tables: list[TableKeyOff] = []
        for tableName in countedTables():
            if tableName not in existing:
                continue  # never created here, so it owes nothing
            keyOffId, keyOffModified = sync_log.getKeyOffBounds(conn, tableName)
            if keyOffId is None:
                continue  # empty table
            lastId, lastModifiedAt = _marks(conn, tableName)
            waiting = sync_log.countKeyOffDeltaRows(
                conn,
                tableName,
                keyOffLastId=lastId,
                keyOffLastModifiedAt=lastModifiedAt,
                keyOffId=keyOffId,
                keyOffModified=keyOffModified,
            )
            tables.append(
                TableKeyOff(tableName, lastId, lastModifiedAt, keyOffId, keyOffModified, waiting)
            )
        return KeyOffSnapshot(tuple(tables))
    except Exception as exc:  # noqa: BLE001 -- runs on the shutdown path; never raise
        logger.warning("shutdown sync progress: key-off snapshot unreadable (%s)", exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110 -- closing must not raise here
                pass


def countRemaining(
    dbPath: str, snapshot: KeyOffSnapshot, *, busyTimeoutSec: float
) -> int | None:
    """Snapshot rows the acked marks still say are owed. READ-ONLY. NEVER raises.

    Args:
        dbPath: The Pi database.
        snapshot: The key-off snapshot.
        busyTimeoutSec: SQLite busy timeout for the read-only open.

    Returns:
        The count, or None when it could not be read.
    """
    conn: sqlite3.Connection | None = None
    try:
        conn = _openReadOnly(dbPath, busyTimeoutSec)
        remaining = 0
        for t in snapshot.tables:
            lastId, lastModifiedAt = _marks(conn, t.table)
            remaining += sync_log.countKeyOffDeltaRows(
                conn,
                t.table,
                keyOffLastId=t.lastId,
                keyOffLastModifiedAt=t.lastModifiedAt,
                keyOffId=t.keyOffId,
                keyOffModified=t.keyOffModified,
                lastId=lastId,
                lastModifiedAt=lastModifiedAt,
            )
        return remaining
    except Exception as exc:  # noqa: BLE001 -- runs between drain passes; never raise
        logger.warning("shutdown sync progress: remaining rows unreadable (%s)", exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110 -- closing must not raise here
                pass


class ShutdownSyncProgress:
    """The shutdown sync's progress, snapshotted at run start, published per pass.

    ``snapshot`` is called once at the start of each shutdown sync run (after
    smoothing, so a blip never snapshots); ``publish`` after each drain pass
    hands ``{waitingAtKeyOff, confirmed}`` to ``publishFn``. Away from home no
    pass runs, so nothing is published and the shutdown-state keeps sync null.
    Neither method raises.
    """

    def __init__(
        self,
        dbPath: str,
        *,
        busyTimeoutSec: float,
        publishFn: Callable[[dict[str, Any]], None],
    ) -> None:
        """Args:
        dbPath: The Pi database (``pi.database.path``).
        busyTimeoutSec: SQLite busy timeout for each read-only open.
        publishFn: Receives each ``{waitingAtKeyOff, confirmed}``; production
            passes ``ShutdownSequencer.publishSync`` (the one shutdown-state
            writer).
        """
        self._dbPath = dbPath
        self._busyTimeoutSec = busyTimeoutSec
        self._publishFn = publishFn
        self._snapshot: KeyOffSnapshot | None = None

    def snapshot(self) -> None:
        """Take this run's key-off snapshot (a failed read leaves none)."""
        self._snapshot = takeKeyOffSnapshot(self._dbPath, busyTimeoutSec=self._busyTimeoutSec)
        if self._snapshot is not None:
            logger.info(
                "shutdown sync progress: %d row(s) waiting at key-off",
                self._snapshot.waitingAtKeyOff,
            )

    def publish(self) -> None:
        """Publish ``{waitingAtKeyOff, confirmed}`` for this pass. Never raises.

        Nothing is published without a snapshot or when the marks cannot be
        read: an unread count is never sent as 0.
        """
        snapshot = self._snapshot
        if snapshot is None:
            return
        remaining = countRemaining(self._dbPath, snapshot, busyTimeoutSec=self._busyTimeoutSec)
        if remaining is None:
            return
        waiting = snapshot.waitingAtKeyOff
        sync = {"waitingAtKeyOff": waiting, "confirmed": max(0, waiting - remaining)}
        try:
            self._publishFn(sync)
        except Exception as exc:  # noqa: BLE001 -- progress is never worth a stalled drain
            logger.error("shutdown sync progress: publish failed (%s) -- ignored", exc)
