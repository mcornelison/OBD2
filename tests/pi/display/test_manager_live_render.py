################################################################################
# File Name: test_manager_live_render.py
# Purpose/Description: Live-render readings polling from realtime_data SQLite
#                      (US-192 acceptance #6 -- mocked gauge updates via
#                      realtime_data row inserts).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Rex          | Initial implementation for US-192 (Sprint 14)
# ================================================================================
################################################################################
"""
Live HDMI render data path tests.

The HDMI primary-screen render harness pulls its readings out of the Pi's
local ``data/obd.db`` realtime_data table at poll time.  These tests prove
the poll-and-map layer:

    buildReadingsFromDb(dbPath, parameterNames)
        -> dict[parameterName -> latestValue]

Alongside, ``PARAMETER_ALIASES`` maps the collector-side
``BATTERY_V`` parameter_name (US-199) to the display-side ``BATTERY_VOLTAGE``
gauge slot so that the Volts gauge updates from the real US-199 source.

Why this test exists (US-192 acceptance #6): the CIO eyeballs the HDMI for
the final pass, but an automated assertion that ``gauge values change as
mocked realtime_data rows are inserted`` is the CI-path correctness gate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pi.display.live_readings import (
    PARAMETER_ALIASES,
    buildReadingsFromDb,
    resolveGaugeName,
)
from pi.display.screens.primary_screen import BASIC_TIER_DISPLAY_ORDER

# ================================================================================
# Fixtures
# ================================================================================


def _createRealtimeDataSchema(conn: sqlite3.Connection) -> None:
    """Create a minimal realtime_data schema matching production shape."""
    conn.execute("""
        CREATE TABLE realtime_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT,
            profile_id TEXT,
            data_source TEXT NOT NULL DEFAULT 'real',
            drive_id INTEGER
        )
    """)
    conn.commit()


def _insertReading(
    conn: sqlite3.Connection,
    parameterName: str,
    value: float,
    timestamp: str = "2026-04-19T10:00:00Z",
    dataSource: str = "real",
) -> None:
    """Insert a realtime_data row for the given parameter."""
    conn.execute(
        "INSERT INTO realtime_data (timestamp, parameter_name, value, data_source) "
        "VALUES (?, ?, ?, ?)",
        (timestamp, parameterName, value, dataSource),
    )
    conn.commit()


@pytest.fixture
def liveDb(tmp_path: Path) -> Path:
    """Create an empty realtime_data SQLite at tmp_path/obd.db."""
    dbPath = tmp_path / "obd.db"
    with sqlite3.connect(str(dbPath)) as conn:
        _createRealtimeDataSchema(conn)
    return dbPath


# ================================================================================
# Tests
# ================================================================================


class TestParameterAliases:
    """PARAMETER_ALIASES must map US-199 BATTERY_V to display BATTERY_VOLTAGE."""

    def test_battery_v_alias_to_battery_voltage(self) -> None:
        assert PARAMETER_ALIASES["BATTERY_V"] == "BATTERY_VOLTAGE"

    def test_resolveGaugeName_maps_alias(self) -> None:
        assert resolveGaugeName("BATTERY_V") == "BATTERY_VOLTAGE"

    def test_resolveGaugeName_passthrough_when_no_alias(self) -> None:
        assert resolveGaugeName("RPM") == "RPM"
        assert resolveGaugeName("COOLANT_TEMP") == "COOLANT_TEMP"
        assert resolveGaugeName("SPEED") == "SPEED"

    def test_resolveGaugeName_preserves_unknown_names(self) -> None:
        assert resolveGaugeName("NOT_A_REAL_PARAM") == "NOT_A_REAL_PARAM"


class TestBuildReadingsFromDbBasics:
    """buildReadingsFromDb handles empty, single, and multi-parameter cases."""

    def test_emptyDbReturnsEmptyDict(self, liveDb: Path) -> None:
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings == {}

    def test_singleReadingSurfaces(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0)
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings == {"RPM": 2500.0}

    def test_multipleReadingsAllSurface(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0)
            _insertReading(conn, "COOLANT_TEMP", 180.0)
            _insertReading(conn, "SPEED", 35.0)
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings["RPM"] == 2500.0
        assert readings["COOLANT_TEMP"] == 180.0
        assert readings["SPEED"] == 35.0

    def test_onlyRequestedParametersSurface(self, liveDb: Path) -> None:
        """Parameters outside BASIC_TIER_DISPLAY_ORDER are not returned."""
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0)
            _insertReading(conn, "THROTTLE_POS", 12.5)  # not in display order
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert "RPM" in readings
        assert "THROTTLE_POS" not in readings


class TestBuildReadingsFromDbFreshness:
    """Latest value per parameter is the one returned (not the first)."""

    def test_latestValueWinsWhenParameterInsertedTwice(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0, timestamp="2026-04-19T10:00:00Z")
            _insertReading(conn, "RPM", 3200.0, timestamp="2026-04-19T10:00:01Z")
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings["RPM"] == 3200.0

    def test_secondPollPicksUpNewerInsert(self, liveDb: Path) -> None:
        """Simulate the live-render loop: poll, then new row arrives, poll again."""
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0, timestamp="2026-04-19T10:00:00Z")

        firstPoll = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert firstPoll["RPM"] == 2500.0

        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 3500.0, timestamp="2026-04-19T10:00:05Z")

        secondPoll = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert secondPoll["RPM"] == 3500.0


class TestBuildReadingsFromDbBatteryAlias:
    """BATTERY_V rows (US-199 collector-side) surface under BATTERY_VOLTAGE key."""

    def test_battery_v_mapped_to_battery_voltage_gauge(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "BATTERY_V", 14.1)
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert "BATTERY_VOLTAGE" in readings
        assert readings["BATTERY_VOLTAGE"] == 14.1
        # BATTERY_V key itself is not exposed; the alias resolution owns it
        assert "BATTERY_V" not in readings

    def test_battery_voltage_direct_still_works(self, liveDb: Path) -> None:
        """Legacy BATTERY_VOLTAGE parameter_name (non-US-199) still surfaces."""
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "BATTERY_VOLTAGE", 13.8)
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings["BATTERY_VOLTAGE"] == 13.8

    def test_battery_v_newer_than_battery_voltage_wins(self, liveDb: Path) -> None:
        """Most recent row wins regardless of which alias produced it."""
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(
                conn,
                "BATTERY_VOLTAGE",
                12.2,
                timestamp="2026-04-19T10:00:00Z",
            )
            _insertReading(
                conn,
                "BATTERY_V",
                14.1,
                timestamp="2026-04-19T10:00:05Z",
            )
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings["BATTERY_VOLTAGE"] == 14.1


class TestBuildReadingsFromDbDataSource:
    """Only real / NULL-BC rows surface; replay / physics_sim excluded."""

    def test_replay_rows_excluded(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 1234.0, dataSource="replay")
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings == {}

    def test_physics_sim_rows_excluded(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 999.0, dataSource="physics_sim")
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings == {}

    def test_real_rows_included(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0, dataSource="real")
        readings = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings["RPM"] == 2500.0


class TestBuildReadingsFromDbRobustness:
    """Graceful degradation: missing db / missing table / corrupt db."""

    def test_missing_db_file_returns_empty(self, tmp_path: Path) -> None:
        missingDb = tmp_path / "nonexistent.db"
        readings = buildReadingsFromDb(missingDb, BASIC_TIER_DISPLAY_ORDER)
        assert readings == {}

    def test_db_without_realtime_data_table_returns_empty(
        self, tmp_path: Path
    ) -> None:
        dbPath = tmp_path / "no_table.db"
        with sqlite3.connect(str(dbPath)) as conn:
            conn.execute("CREATE TABLE unrelated (id INTEGER)")
            conn.commit()
        readings = buildReadingsFromDb(dbPath, BASIC_TIER_DISPLAY_ORDER)
        assert readings == {}

    def test_empty_parameter_list_returns_empty(self, liveDb: Path) -> None:
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 2500.0)
        readings = buildReadingsFromDb(liveDb, [])
        assert readings == {}


class TestGaugeValuesUpdateAsRowsArrive:
    """Acceptance #6: gauge values change as mocked realtime_data rows
    are inserted -- this is the single critical assertion."""

    def test_six_gauges_update_across_polling_cycles(self, liveDb: Path) -> None:
        # Phase 1: warm-idle snapshot
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 800.0, timestamp="2026-04-19T10:00:00Z")
            _insertReading(
                conn, "COOLANT_TEMP", 75.0, timestamp="2026-04-19T10:00:00Z"
            )
            _insertReading(conn, "SPEED", 0.0, timestamp="2026-04-19T10:00:00Z")
            _insertReading(
                conn, "BATTERY_V", 12.8, timestamp="2026-04-19T10:00:00Z"
            )

        phase1 = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert phase1["RPM"] == 800.0
        assert phase1["COOLANT_TEMP"] == 75.0
        assert phase1["SPEED"] == 0.0
        assert phase1["BATTERY_VOLTAGE"] == 12.8

        # Phase 2: simulate a drive -- RPM up, speed up, coolant up, volts up
        with sqlite3.connect(str(liveDb)) as conn:
            _insertReading(conn, "RPM", 3200.0, timestamp="2026-04-19T10:01:00Z")
            _insertReading(
                conn, "COOLANT_TEMP", 90.0, timestamp="2026-04-19T10:01:00Z"
            )
            _insertReading(conn, "SPEED", 45.0, timestamp="2026-04-19T10:01:00Z")
            _insertReading(
                conn, "BATTERY_V", 14.1, timestamp="2026-04-19T10:01:00Z"
            )

        phase2 = buildReadingsFromDb(liveDb, BASIC_TIER_DISPLAY_ORDER)
        assert phase2["RPM"] == 3200.0
        assert phase2["COOLANT_TEMP"] == 90.0
        assert phase2["SPEED"] == 45.0
        assert phase2["BATTERY_VOLTAGE"] == 14.1

        # Every gauge changed phase 1 -> phase 2
        for param in ("RPM", "COOLANT_TEMP", "SPEED", "BATTERY_VOLTAGE"):
            assert phase1[param] != phase2[param], (
                f"Gauge {param} did not update between polling cycles"
            )
