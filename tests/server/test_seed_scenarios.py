################################################################################
# File Name: test_seed_scenarios.py
# Purpose/Description: Tests for scripts/seed_scenarios.py — simulator data to SQLite export
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial TDD tests for US-156
# ================================================================================
################################################################################

"""
Tests for seed_scenarios.py.

Validates that the seed script generates portable SQLite databases matching
the Pi's schema with realistic simulator data across all 4 scenario types.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def outputDb():
    """Provide a temporary file path for SQLite output, cleaned up after test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    # Remove the empty file so the script creates it fresh
    os.unlink(path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ---------------------------------------------------------------------------
# Import Tests
# ---------------------------------------------------------------------------

class TestSeedScenariosImport:
    """Verify the module can be imported and exposes expected API."""

    def test_importModule(self):
        """Module should be importable."""
        from scripts.seed_scenarios import SCENARIO_MAP  # noqa: F401

    def test_scenarioMapContainsFourScenarios(self):
        """SCENARIO_MAP should contain the 4 scenarios from spec §1.6."""
        from scripts.seed_scenarios import SCENARIO_MAP

        expected = {"city_driving", "highway_cruise", "cold_start", "full_cycle"}
        assert set(SCENARIO_MAP.keys()) == expected

    def test_runScenarioFunctionExists(self):
        """runScenario() should be importable."""
        from scripts.seed_scenarios import runScenario  # noqa: F401

    def test_parseArgumentsFunctionExists(self):
        """parseArguments() should be importable."""
        from scripts.seed_scenarios import parseArguments  # noqa: F401


# ---------------------------------------------------------------------------
# Single Scenario Tests
# ---------------------------------------------------------------------------

class TestSingleScenario:
    """Test running a single scenario and validating the SQLite output."""

    def test_cityDrivingCreatesValidDb(self, outputDb):
        """
        Given: --scenario city_driving --output <path>
        When: runScenario is called
        Then: a valid SQLite file is created with the required tables
        """
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="city_driving", outputPath=outputDb)

        assert os.path.exists(outputDb)
        conn = sqlite3.connect(outputDb)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert "realtime_data" in tables
            assert "connection_log" in tables
            assert "statistics" in tables
        finally:
            conn.close()

    def test_realtimeDataHasCorrectColumns(self, outputDb):
        """
        Given: a generated SQLite from city_driving
        When: we inspect realtime_data columns
        Then: they match the Pi schema (id, timestamp, parameter_name, value, unit, profile_id)
        """
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="city_driving", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            cursor = conn.execute("PRAGMA table_info(realtime_data)")
            columns = {row[1] for row in cursor.fetchall()}
            expected = {
                "id", "timestamp", "parameter_name", "value", "unit",
                "profile_id",
                "data_source",  # US-195 / Spool CR #4
                "drive_id",  # US-200 / Spool Data v2 Story 2
            }
            assert expected == columns
        finally:
            conn.close()

    def test_realtimeDataContainsRows(self, outputDb):
        """
        Given: a generated SQLite from city_driving
        When: we count realtime_data rows
        Then: there should be a meaningful number of rows (> 100)
        """
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="city_driving", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            count = conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0]
            assert count > 100, f"Expected > 100 rows, got {count}"
        finally:
            conn.close()

    def test_connectionLogHasDriveEvents(self, outputDb):
        """
        Given: a generated SQLite from city_driving
        When: we check connection_log
        Then: it should have drive_start and drive_end events
        """
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="city_driving", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            events = {
                row[0]
                for row in conn.execute(
                    "SELECT DISTINCT event_type FROM connection_log"
                ).fetchall()
            }
            assert "drive_start" in events
            assert "drive_end" in events
        finally:
            conn.close()

    def test_statisticsTablePopulated(self, outputDb):
        """
        Given: a generated SQLite from city_driving
        When: we check statistics table
        Then: it should contain per-parameter statistical summaries
        """
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="city_driving", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            count = conn.execute("SELECT COUNT(*) FROM statistics").fetchone()[0]
            assert count > 0, "statistics table should have rows"
            # Verify key columns have values
            row = conn.execute(
                "SELECT parameter_name, max_value, min_value, avg_value, "
                "std_1, outlier_min, outlier_max, sample_count "
                "FROM statistics LIMIT 1"
            ).fetchone()
            assert row is not None
            assert row[0] is not None  # parameter_name
            assert row[7] > 0  # sample_count > 0
        finally:
            conn.close()

    def test_realtimeDataHasMultipleParameters(self, outputDb):
        """
        Given: a generated SQLite from city_driving
        When: we check distinct parameter names in realtime_data
        Then: there should be multiple OBD-II parameters
        """
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="city_driving", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            params = conn.execute(
                "SELECT DISTINCT parameter_name FROM realtime_data"
            ).fetchall()
            paramNames = {row[0] for row in params}
            # At minimum: RPM, SPEED, COOLANT_TEMP, ENGINE_LOAD
            assert "RPM" in paramNames
            assert "SPEED" in paramNames
            assert "COOLANT_TEMP" in paramNames
            assert "ENGINE_LOAD" in paramNames
            assert len(paramNames) >= 8, f"Expected >= 8 parameters, got {len(paramNames)}"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# All Scenarios Tests
# ---------------------------------------------------------------------------

class TestAllScenarios:
    """Test running all 4 scenarios into one database."""

    def test_allScenariosCreatesDb(self, outputDb):
        """
        Given: --all --output <path>
        When: runAllScenarios is called
        Then: a valid SQLite file is created
        """
        from scripts.seed_scenarios import runAllScenarios

        runAllScenarios(outputPath=outputDb)

        assert os.path.exists(outputDb)
        conn = sqlite3.connect(outputDb)
        try:
            count = conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0]
            assert count > 0
        finally:
            conn.close()

    def test_allScenariosHasMultipleDriveSessions(self, outputDb):
        """
        Given: --all output
        When: we check connection_log
        Then: there should be at least 4 drive_start events (one per scenario)
        """
        from scripts.seed_scenarios import runAllScenarios

        runAllScenarios(outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            startCount = conn.execute(
                "SELECT COUNT(*) FROM connection_log WHERE event_type = 'drive_start'"
            ).fetchone()[0]
            assert startCount >= 4, f"Expected >= 4 drive sessions, got {startCount}"
        finally:
            conn.close()

    def test_allScenariosHasMoreDataThanSingle(self, outputDb):
        """
        Given: --all output
        When: we compare row counts
        Then: all-scenarios DB should have significantly more rows than a single scenario
        """
        from scripts.seed_scenarios import runAllScenarios, runScenario

        runAllScenarios(outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            allCount = conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0]
        finally:
            conn.close()

        # Run a single scenario for comparison
        fd, singlePath = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(singlePath)
        try:
            runScenario(scenario="cold_start", outputPath=singlePath)
            conn2 = sqlite3.connect(singlePath)
            try:
                singleCount = conn2.execute(
                    "SELECT COUNT(*) FROM realtime_data"
                ).fetchone()[0]
            finally:
                conn2.close()
            assert allCount > singleCount, (
                f"All scenarios ({allCount}) should have more data "
                f"than single ({singleCount})"
            )
        finally:
            if os.path.exists(singlePath):
                os.unlink(singlePath)


# ---------------------------------------------------------------------------
# Performance Tests
# ---------------------------------------------------------------------------

class TestPerformance:
    """Time-scaled execution: scenarios must run fast."""

    def test_fullCycleCompletesUnder10Seconds(self, outputDb):
        """
        Given: the full_cycle scenario (~413 seconds of simulation)
        When: we run it with time-scaling
        Then: wall-clock execution should be under 10 seconds
        """
        from scripts.seed_scenarios import runScenario

        start = time.monotonic()
        runScenario(scenario="full_cycle", outputPath=outputDb)
        elapsed = time.monotonic() - start

        assert elapsed < 10.0, f"full_cycle took {elapsed:.1f}s, expected < 10s"

    def test_allScenariosCompletesUnder30Seconds(self, outputDb):
        """
        Given: all 4 scenarios
        When: run together
        Then: total wall-clock should be under 30 seconds
        """
        from scripts.seed_scenarios import runAllScenarios

        start = time.monotonic()
        runAllScenarios(outputPath=outputDb)
        elapsed = time.monotonic() - start

        assert elapsed < 30.0, f"All scenarios took {elapsed:.1f}s, expected < 30s"


# ---------------------------------------------------------------------------
# CLI Tests
# ---------------------------------------------------------------------------

class TestCli:
    """Test argparse-based CLI interface."""

    def test_parseScenarioArgument(self):
        """parseArguments should handle --scenario and --output."""
        from scripts.seed_scenarios import parseArguments

        args = parseArguments(["--scenario", "city_driving", "--output", "test.db"])
        assert args.scenario == "city_driving"
        assert args.output == "test.db"
        assert args.all is False

    def test_parseAllArgument(self):
        """parseArguments should handle --all and --output."""
        from scripts.seed_scenarios import parseArguments

        args = parseArguments(["--all", "--output", "test.db"])
        assert args.all is True
        assert args.output == "test.db"

    def test_helpDoesNotCrash(self, capsys):
        """--help should print usage and exit cleanly."""
        from scripts.seed_scenarios import parseArguments

        with pytest.raises(SystemExit) as exc:
            parseArguments(["--help"])
        assert exc.value.code == 0

    def test_invalidScenarioName(self):
        """Invalid scenario name should be rejected by argparse choices."""
        from scripts.seed_scenarios import parseArguments

        with pytest.raises(SystemExit) as exc:
            parseArguments(["--scenario", "nonexistent", "--output", "test.db"])
        assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Schema Compatibility Tests
# ---------------------------------------------------------------------------

class TestSchemaCompatibility:
    """Verify output matches Pi database schema exactly."""

    def test_connectionLogColumns(self, outputDb):
        """connection_log columns should match Pi schema."""
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="cold_start", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            cursor = conn.execute("PRAGMA table_info(connection_log)")
            columns = {row[1] for row in cursor.fetchall()}
            expected = {
                "id", "timestamp", "event_type", "mac_address",
                "success", "error_message", "retry_count",
                "data_source",  # US-195 / Spool CR #4
                "drive_id",  # US-200 / Spool Data v2 Story 2
            }
            assert expected == columns
        finally:
            conn.close()

    def test_statisticsColumns(self, outputDb):
        """statistics columns should match Pi schema."""
        from scripts.seed_scenarios import runScenario

        runScenario(scenario="cold_start", outputPath=outputDb)

        conn = sqlite3.connect(outputDb)
        try:
            cursor = conn.execute("PRAGMA table_info(statistics)")
            columns = {row[1] for row in cursor.fetchall()}
            expected = {
                "id", "parameter_name", "analysis_date", "profile_id",
                "max_value", "min_value", "avg_value", "mode_value",
                "std_1", "std_2", "outlier_min", "outlier_max",
                "sample_count", "created_at",
                "data_source",  # US-195 / Spool CR #4
                "drive_id",  # US-200 / Spool Data v2 Story 2
            }
            assert expected == columns
        finally:
            conn.close()
