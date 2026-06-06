################################################################################
# File Name: dtc_freeze_frame_schema.py
# Purpose/Description: Schema definition + idempotent migration for the Pi-side
#                      ``dtc_freeze_frame`` capture table (US-368 / F-109).
#                      Stores one row per Mode 02 freeze-frame: the 16-PID JSON
#                      snapshot captured when a DTC trips, an FK to the dtc_log
#                      row it belongs to, the active vehicle_info VIN (the Pi's
#                      vehicle_info PK), and a graceful-degradation notes field.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-368) | Initial -- dtc_freeze_frame schema +
#               |              | ensureDtcFreezeFrameTable.
# ================================================================================
################################################################################

"""Schema + migration for Pi-side ``dtc_freeze_frame`` (US-368 / F-109).

A Mode 02 freeze-frame is the 16-PID snapshot of "what the engine was doing"
when a DTC tripped.  The Pi captures it on a MIL_ON rising edge
(:mod:`src.pi.obdii.freeze_frame`) and writes one row here; US-369 syncs the
row to the server, where ``insertDtcFreezeFrame`` resolves the integer
``vehicle_info_id`` FK from this row's ``vehicle_info_vin`` against the ECU era
active at ``captured_at`` (the temporal invariant the Pi cannot enforce -- its
``vehicle_info`` schema has no ECU lineage, server-only per US-365).

Cross-tier note: the Pi ``vehicle_info`` PK is ``vin`` (TEXT), so this table
references the active vehicle by VIN, not by an integer id.  The server table
(:class:`src.server.db.models.DtcFreezeFrame`) uses an integer
``vehicle_info_id``; US-369 sync bridges the two.

Schema columns:

==========================  ==========================================
``id``                      INTEGER PK AUTOINCREMENT (sync delta key).
``dtc_log_id``              INTEGER NULL -- FK to dtc_log.id (the DTC).
``captured_at_timestamp_utc``  DEFAULT canonical ISO-8601 UTC.
``pid_responses_json``      TEXT -- JSON dict of {pid_name: value};
                            ``{}`` when Mode 02 unavailable.
``vehicle_info_vin``        TEXT NULL -- active vehicle_info VIN at
                            capture time (the Pi vehicle_info PK).
``notes``                   TEXT NULL -- gap explanation on degraded
                            captures (Mode 02 unavailable).
``data_source``             TEXT NOT NULL DEFAULT 'real' (US-195).
==========================  ==========================================

Follows the same load-time-pure pattern as :mod:`src.pi.obdii.dtc_log_schema`:
no side effects on import; :func:`ensureDtcFreezeFrameTable` does all the DDL.
"""

from __future__ import annotations

import sqlite3

__all__ = [
    'DTC_FREEZE_FRAME_INDEXES',
    'DTC_FREEZE_FRAME_TABLE',
    'SCHEMA_DTC_FREEZE_FRAME',
    'ensureDtcFreezeFrameTable',
]


DTC_FREEZE_FRAME_TABLE: str = 'dtc_freeze_frame'


SCHEMA_DTC_FREEZE_FRAME: str = """
CREATE TABLE IF NOT EXISTS dtc_freeze_frame (
    -- Primary key (sync delta cursor).
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- FK to the DTC this freeze-frame belongs to (dtc_log.id).  Nullable:
    -- a capture may precede a resolved dtc_log row in degraded cases.
    dtc_log_id INTEGER,

    -- Capture timestamp -- canonical ISO-8601 UTC (US-202 / TD-027).
    captured_at_timestamp_utc DATETIME NOT NULL
        DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    -- 16-PID Mode 02 snapshot serialized as a JSON object; '{}' when the
    -- ECU returned no Mode 02 data (graceful degradation).
    pid_responses_json TEXT NOT NULL DEFAULT '{}',

    -- Active vehicle_info VIN at capture time (the Pi vehicle_info PK).
    -- Nullable: VIN decode may not have landed yet.
    vehicle_info_vin TEXT,

    -- Operator-facing context for degraded captures (Mode 02 unavailable).
    notes TEXT,

    -- US-195 origin tag.
    data_source TEXT NOT NULL DEFAULT 'real'
        CHECK (data_source IN ('real','replay','physics_sim','fixture'))
);
"""


INDEX_DTC_FREEZE_FRAME_DTC_LOG_ID: str = (
    "CREATE INDEX IF NOT EXISTS IX_dtc_freeze_frame_dtc_log_id "
    "ON dtc_freeze_frame(dtc_log_id);"
)

DTC_FREEZE_FRAME_INDEXES: tuple[tuple[str, str], ...] = (
    ('IX_dtc_freeze_frame_dtc_log_id', INDEX_DTC_FREEZE_FRAME_DTC_LOG_ID),
)


def _tableExists(conn: sqlite3.Connection, tableName: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (tableName,),
    ).fetchone()
    return row is not None


def ensureDtcFreezeFrameTable(conn: sqlite3.Connection) -> bool:
    """Create ``dtc_freeze_frame`` + its index if not already present.

    Idempotent: returns ``False`` if the table already existed.  Always
    re-issues the index DDL (CREATE INDEX IF NOT EXISTS -- a no-op when
    present).

    Args:
        conn: Open sqlite3 connection.  Caller owns commit.

    Returns:
        ``True`` if the CREATE TABLE actually ran (table was missing).
    """
    created = not _tableExists(conn, DTC_FREEZE_FRAME_TABLE)
    conn.execute(SCHEMA_DTC_FREEZE_FRAME)
    for _, indexDdl in DTC_FREEZE_FRAME_INDEXES:
        conn.execute(indexDdl)
    return created
