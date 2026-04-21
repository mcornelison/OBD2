################################################################################
# File Name: dtc_log_schema.py
# Purpose/Description: Schema definition + idempotent migration for the
#                      ``dtc_log`` capture table introduced in US-204
#                      (Spool Data v2 Story 3 -- DTC retrieval).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-204) | Initial -- dtc_log schema + ensureDtcLogTable.
# ================================================================================
################################################################################

"""Schema + migration for ``dtc_log`` (US-204 / Spool Data v2 Story 3).

Stores one row per observed DTC.  The same code reappearing inside the
same drive bumps ``last_seen_timestamp`` via the
:class:`~src.pi.obdii.dtc_logger.DtcLogger` upsert helper; new drives
get fresh rows even for the same code.

Schema columns (Spool spec verbatim):

==========================  ==========================================
Column                      Notes
==========================  ==========================================
``id``                      INTEGER PK AUTOINCREMENT (sync delta key).
``dtc_code``                TEXT NOT NULL -- e.g. ``"P0171"``.
``description``             TEXT -- empty string when DTC_MAP unknown.
``status``                  CHECK in (stored, pending, cleared).
``first_seen_timestamp``    DEFAULT canonical ISO-8601 UTC.
``last_seen_timestamp``     DEFAULT canonical ISO-8601 UTC.
``drive_id``                INTEGER NULL -- US-200 inheritance.
``data_source``             TEXT NOT NULL DEFAULT 'real' -- US-195.
==========================  ==========================================

Indexes: ``IX_dtc_log_drive_id`` (per-drive analytics) and
``IX_dtc_log_dtc_code`` (cross-drive lookup of a specific code).

This module follows the same load-time-pure pattern as
:mod:`src.pi.obdii.data_source` and :mod:`src.pi.obdii.drive_id` --
no side effects on import; the :func:`ensureDtcLogTable` helper does
all the DDL.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    'DTC_LOG_INDEXES',
    'DTC_LOG_STATUS_VALUES',
    'DTC_LOG_TABLE',
    'SCHEMA_DTC_LOG',
    'ensureDtcLogTable',
]


# ================================================================================
# Constants
# ================================================================================


DTC_LOG_TABLE: str = 'dtc_log'

# Closed status enum.  ``cleared`` reserved for future MIL-clear events;
# Sprint 15 only writes ``stored`` (Mode 03) and ``pending`` (Mode 07).
DTC_LOG_STATUS_VALUES: tuple[str, str, str] = ('stored', 'pending', 'cleared')


# ================================================================================
# DDL
# ================================================================================

SCHEMA_DTC_LOG: str = """
CREATE TABLE IF NOT EXISTS dtc_log (
    -- Primary key (sync delta cursor; matches sync_log.PK_COLUMN entry).
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- DTC payload.
    dtc_code TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('stored','pending','cleared')),

    -- Capture timestamps -- canonical ISO-8601 UTC (US-202 / TD-027).
    first_seen_timestamp DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_seen_timestamp DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    -- US-200 drive scoping.  Nullable because a Mode 03 probe may
    -- happen before _startDrive opens a drive_id (rare edge case;
    -- normal session-start probe runs inside _startDrive's hook so
    -- drive_id is already set).
    drive_id INTEGER,

    -- US-195 origin tag.
    data_source TEXT NOT NULL DEFAULT 'real'
        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
);
"""


# Index DDL -- reusing the IF NOT EXISTS pattern so legacy databases
# get the indexes after the table migration runs.
INDEX_DTC_LOG_DRIVE_ID: str = (
    "CREATE INDEX IF NOT EXISTS IX_dtc_log_drive_id "
    "ON dtc_log(drive_id);"
)

INDEX_DTC_LOG_DTC_CODE: str = (
    "CREATE INDEX IF NOT EXISTS IX_dtc_log_dtc_code "
    "ON dtc_log(dtc_code);"
)

DTC_LOG_INDEXES: tuple[tuple[str, str], ...] = (
    ('IX_dtc_log_drive_id', INDEX_DTC_LOG_DRIVE_ID),
    ('IX_dtc_log_dtc_code', INDEX_DTC_LOG_DTC_CODE),
)


# ================================================================================
# Migration helper
# ================================================================================


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


def ensureDtcLogTable(conn: sqlite3.Connection) -> bool:
    """Create ``dtc_log`` + its indexes if not already present.

    Idempotent: returns ``False`` if the table already existed.  Always
    re-issues the index DDL (CREATE INDEX IF NOT EXISTS so this is also
    a no-op when present).

    Args:
        conn: Open sqlite3 connection.  Caller owns commit.

    Returns:
        ``True`` if the CREATE TABLE actually ran (table was missing).
    """
    created = not _tableExists(conn, DTC_LOG_TABLE)
    conn.execute(SCHEMA_DTC_LOG)
    for _, indexDdl in DTC_LOG_INDEXES:
        conn.execute(indexDdl)
    return created
