################################################################################
# File Name: pi_state.py
# Purpose/Description: Schema + helpers for the ``pi_state`` single-row
#                      key-value table. Persists US-225 operational flags
#                      (no_new_drives, reserved for future) across reboots
#                      so a WARNING-stage power event survives process
#                      restart without dropping the gate.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-23    | Rex (US-225) | Initial -- pi_state singleton + no_new_drives
#                               flag for US-216 WARNING stage.
# ================================================================================
################################################################################

"""Schema + migration + accessors for the ``pi_state`` singleton table.

US-225 / TD-034 close.  The ``pi_state`` row carries flags the Pi needs
to remember across process restart -- today only ``no_new_drives`` for
the US-216 power-down WARNING stage.  Picking a single-row key-value
shape rather than a column-per-flag keeps future additions (operator
maintenance-mode flag, bench-test gate, etc.) cheap: add a new column
and a matching get/set pair, no table migration for existing flags.

Design
------
* One row, enforced by a ``CHECK (id = 1)`` primary key identical to
  the ``drive_counter`` pattern.
* ``no_new_drives`` is an INTEGER 0/1 so SQLite's booleanish semantics
  work without a second adapter layer; Python accessors normalize to
  ``bool``.
* Seeding is idempotent (``INSERT OR IGNORE``) so reboot preserves an
  operator-set value.
* All helpers take an open :class:`sqlite3.Connection`; caller owns
  commit semantics so the callback layer can batch a WARNING-stage
  transition atomically with other writes.

Invariants
----------
1. ``no_new_drives`` only gates NEW drive_id minting at CRANKING; an
   already-open drive is never retroactively closed or unflagged by the
   gate.  :meth:`DriveDetector.forceKeyOff` is the separate tool for
   closing an active drive mid-stage.
2. :func:`clearNoNewDrives` is the only path back to a mintable state --
   the flag never times out on its own.  US-216's AC-restore callback
   is the canonical caller; operators can also clear manually via the
   helper API.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    'PI_STATE_TABLE',
    'SCHEMA_PI_STATE',
    'clearNoNewDrives',
    'ensurePiStateTable',
    'getNoNewDrives',
    'setNoNewDrives',
]


# ================================================================================
# Constants
# ================================================================================


PI_STATE_TABLE: str = 'pi_state'


# ================================================================================
# DDL
# ================================================================================


SCHEMA_PI_STATE: str = """
CREATE TABLE IF NOT EXISTS pi_state (
    -- Singleton row.  id is pinned to 1 so writers always UPDATE/UPSERT
    -- the same row; follows the drive_counter convention.
    id INTEGER PRIMARY KEY CHECK (id = 1),

    -- US-225: set by the US-216 WARNING stage to gate new drive_id
    -- minting during a drain event.  Cleared by AC-restore.  INTEGER
    -- 0/1 so SQLite native booleans work; Python accessors normalize.
    no_new_drives INTEGER NOT NULL DEFAULT 0
);
"""


# ================================================================================
# Migration helpers
# ================================================================================


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


def ensurePiStateTable(conn: sqlite3.Connection) -> bool:
    """Create ``pi_state`` + seed the singleton row if not present.

    Idempotent: safe on every boot.  Returns ``True`` when the CREATE
    TABLE actually ran so the caller can log a migration message.

    Args:
        conn: Open sqlite3 connection.  Caller owns commit.

    Returns:
        ``True`` if the table was newly created on this call.
    """
    created = not _tableExists(conn, PI_STATE_TABLE)
    conn.execute(SCHEMA_PI_STATE)
    # Seed singleton.  INSERT OR IGNORE preserves existing state across
    # reboots -- a WARNING flag set before an unexpected restart survives.
    conn.execute(
        "INSERT OR IGNORE INTO pi_state (id, no_new_drives) VALUES (1, 0)"
    )
    return created


# ================================================================================
# Accessors -- no_new_drives
# ================================================================================


def getNoNewDrives(conn: sqlite3.Connection) -> bool:
    """Return the current ``no_new_drives`` flag.

    A missing row (should never happen after :func:`ensurePiStateTable`)
    is treated as ``False`` -- mintable -- so a half-migrated state does
    NOT silently block drives.  The gate is a graceful-degradation
    safeguard; its default-off posture matches "do not break operation".

    Args:
        conn: Open sqlite3 connection.

    Returns:
        ``True`` when new drive_id minting should be suppressed.
    """
    row = conn.execute(
        "SELECT no_new_drives FROM pi_state WHERE id = 1"
    ).fetchone()
    if row is None:
        return False
    return bool(row[0])


def setNoNewDrives(conn: sqlite3.Connection, value: bool) -> None:
    """Set the ``no_new_drives`` flag.

    UPSERTs the singleton row so a call before :func:`ensurePiStateTable`
    (test seam) still produces a valid state.  Caller owns commit.

    Args:
        conn: Open sqlite3 connection.
        value: ``True`` to suppress new drive_id minting, ``False`` to
            restore normal mint behavior.
    """
    # INSERT OR IGNORE keeps the singleton shape; UPDATE is the
    # authoritative write.  Guards against a pre-ensurePiStateTable call.
    conn.execute(
        "INSERT OR IGNORE INTO pi_state (id, no_new_drives) VALUES (1, 0)"
    )
    conn.execute(
        "UPDATE pi_state SET no_new_drives = ? WHERE id = 1",
        (1 if value else 0,),
    )


def clearNoNewDrives(conn: sqlite3.Connection) -> None:
    """Clear the ``no_new_drives`` flag -- restore normal mint behavior.

    Convenience wrapper over :func:`setNoNewDrives` with ``False`` so
    the US-216 AC-restore callback reads naturally.

    Args:
        conn: Open sqlite3 connection.
    """
    setNoNewDrives(conn, False)
