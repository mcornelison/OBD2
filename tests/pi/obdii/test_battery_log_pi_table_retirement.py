################################################################################
# File Name: test_battery_log_pi_table_retirement.py
# Purpose/Description: US-437 (N-4) retirement test -- asserts the legacy Pi-side
#                      ``battery_log`` table is:
#                        (a) NOT in ALL_SCHEMAS (fresh DB never creates it),
#                        (b) DROPPED on the next ObdDatabase.initialize() for a
#                            legacy DB that still carries it,
#                        (c) the ensureBatteryLogRetired migration is idempotent
#                            (first call drops + returns True, later calls no-op
#                            + return False).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-437) | Initial -- N-4 Pi-side schema-drift cleanup.
#               |              | Server dropped battery_log in US-223 (v0003);
#               |              | the Pi kept an empty copy.  Mirrors the US-351
#               |              | drive_statistics retirement test.
# ================================================================================
################################################################################

"""Pi-side ``battery_log`` table retirement regression test (US-437 / N-4).

Why this exists
---------------

Argus's 2026-05-12 data-profile finding (N-4) observed that server migration
``v0003_us223`` dropped the dead ``battery_log`` table (superseded by
``battery_health_log``), but the Pi never dropped its copy -- an empty
``battery_log`` lingered on the Pi obd.db as schema-drift residue (re-confirmed
present live 2026-07-02, 0 rows).  US-437 adds :func:`ensureBatteryLogRetired`,
an idempotent boot-time DROP that converges any Pi still carrying the legacy
table.  This test pins the retirement so a future accidental resurrection
(someone re-adds a ``battery_log`` schema constant + ALL_SCHEMAS entry) trips
RED before it ships.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.pi.obdii.database import ObdDatabase
from src.pi.obdii.database_schema import (
    ALL_SCHEMAS,
    ensureBatteryLogRetired,
)

BATTERY_LOG_TABLE = "battery_log"


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    """An initialized, empty ObdDatabase backed by a new file."""
    db = ObdDatabase(str(tmp_path / "test_batterylog_retired.db"), walMode=False)
    db.initialize()
    return db


class TestSchemaConstantRetired:
    """The Pi never creates ``battery_log`` on a fresh DB."""

    def test_notInAllSchemas(self) -> None:
        """``battery_log`` does not appear in ALL_SCHEMAS."""
        names = [name for name, _ in ALL_SCHEMAS]
        assert BATTERY_LOG_TABLE not in names

    def test_freshDbHasNoBatteryLogTable(self, freshDb: ObdDatabase) -> None:
        """A fresh Pi DB initialize() does NOT create the table."""
        assert BATTERY_LOG_TABLE not in freshDb.getTableNames()


class TestRetirementMigration:
    """``ensureBatteryLogRetired`` is idempotent."""

    def test_legacyDbLosesTableOnNextBoot(self, tmp_path: Path) -> None:
        """Pre-cleanup DB with the table -> next ``initialize()`` drops it."""
        path = tmp_path / "legacy.db"
        legacyConn = sqlite3.connect(str(path))
        # The legacy Pi ``battery_log`` schema (pre-US-223 BatteryMonitor table).
        legacyConn.execute(
            "CREATE TABLE battery_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp DATETIME, "
            "event_type TEXT, "
            "voltage REAL, "
            "warning_threshold REAL, "
            "critical_threshold REAL"
            ")"
        )
        legacyConn.commit()

        # Confirm pre-state.
        probeConn = sqlite3.connect(str(path))
        present = probeConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'battery_log'"
        ).fetchone()
        probeConn.close()
        assert present is not None

        # Next boot.
        ObdDatabase(str(path), walMode=False).initialize()

        # Confirm post-state.
        afterConn = sqlite3.connect(str(path))
        absent = afterConn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name = 'battery_log'"
        ).fetchone()
        afterConn.close()
        assert absent is None, "battery_log table must be retired on next boot"

    def test_secondInitializeIsNoOp(self, freshDb: ObdDatabase) -> None:
        """``initialize()`` twice on the same DB is safe and idempotent."""
        with freshDb.connect() as conn:
            assert ensureBatteryLogRetired(conn) is False  # absent on fresh
        freshDb.initialize()  # second initialize must not raise
        assert BATTERY_LOG_TABLE not in freshDb.getTableNames()

    def test_ensureBatteryLogRetired_returnsTrueOnFirstDrop_falseOnAbsent(
        self, tmp_path: Path,
    ) -> None:
        """Return value pins idempotency: True iff drop occurred."""
        path = tmp_path / "rv.db"
        legacyConn = sqlite3.connect(str(path))
        legacyConn.execute(
            "CREATE TABLE battery_log (id INTEGER PRIMARY KEY)"
        )
        legacyConn.commit()
        legacyConn.close()

        with sqlite3.connect(str(path)) as conn:
            assert ensureBatteryLogRetired(conn) is True
            assert ensureBatteryLogRetired(conn) is False
