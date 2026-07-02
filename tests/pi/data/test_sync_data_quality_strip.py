################################################################################
# File Name: test_sync_data_quality_strip.py
# Purpose/Description: US-419 -- the Pi-local ``data_quality`` clock-drift flag
#                      must be stripped from the sync wire payload.  The server
#                      rejects unknown columns (SQLAlchemy bulk insert) and
#                      computes its own data_quality at ingest (Pi = emitter,
#                      server = authority), so a Pi data_quality value is never
#                      sent upstream -- for both the delta and snapshot readers.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-07-01    | Rex     | Initial -- US-419 data_quality wire-strip.
# ================================================================================
################################################################################
"""US-419 data_quality wire-strip tests (delta + snapshot readers)."""
import sqlite3

from src.pi.data import sync_log


def test_getDeltaRows_stripsDataQualityFromWire() -> None:
    """
    Given: a power_log row carrying a Pi-local data_quality flag
    When: the delta reader builds the wire payload
    Then: data_quality is stripped (server rejects it) but the real capture
          columns survive
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE power_log ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  timestamp TEXT, event_type TEXT, power_source TEXT,"
        "  on_ac_power INTEGER, vcell REAL, data_quality TEXT)"
    )
    conn.execute(
        "INSERT INTO power_log "
        "(timestamp, event_type, power_source, on_ac_power, data_quality) "
        "VALUES ('2026-07-01T00:00:00Z','ac_power','ac',1,'clock_unsynced')"
    )

    rows = sync_log.getDeltaRows(conn, "power_log", 0, 100)

    assert len(rows) == 1
    assert "data_quality" not in rows[0]
    assert rows[0]["event_type"] == "ac_power"
    assert rows[0]["timestamp"] == "2026-07-01T00:00:00Z"


def test_getSnapshotRows_stripsDataQualityFromWire() -> None:
    """The snapshot reader (startup_log path) also strips data_quality."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE startup_log ("
        "  boot_id TEXT PRIMARY KEY,"
        "  recorded_at TEXT NOT NULL,"
        "  data_quality TEXT)"
    )
    conn.execute(
        "INSERT INTO startup_log (boot_id, recorded_at, data_quality) "
        "VALUES ('b1','2026-07-01T00:00:00Z','clock_unsynced')"
    )

    rows = sync_log.getSnapshotRows(conn, "startup_log", None, 100)

    assert len(rows) == 1
    assert "data_quality" not in rows[0]
    assert rows[0]["boot_id"] == "b1"
    assert rows[0]["recorded_at"] == "2026-07-01T00:00:00Z"
