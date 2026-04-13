################################################################################
# File Name: test_simulate_db_validation.py
# Purpose/Description: Integration test that runs the application in simulate
#                       mode and validates the database output is correct.
#                       Reference implementation for the Definition of Done
#                       pattern: run orchestrator, query DB, assert rows.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-11    | Ralph Agent  | US-101: Initial implementation
# 2026-04-11    | Ralph Agent  | US-102: Parameter completeness and data quality
# 2026-04-11    | Ralph Agent  | US-103: Expanded module docstring as reference doc
# ================================================================================
################################################################################

"""
Simulate DB Validation Integration Test — Reference Implementation.

This test file is the **reference implementation** for the Database Output
Validation pattern required by specs/methodology.md Section 3 ("Definition of
Done"). Any user story that writes to the database MUST include a test that
validates the data was actually written correctly (see methodology.md for the
full policy). This file demonstrates the canonical approach.

**The Pattern (run orchestrator → query DB → assert rows):**

    1. Create a temp database via ``tmp_path`` fixture (no side effects on real
       data).
    2. Build a config dict pointing at the temp DB path (see
       ``getSimValidationConfig``).
    3. Run the ``ApplicationOrchestrator`` in simulate mode via the
       ``runOrchestratorWithTimer`` helper. This starts the orchestrator, lets
       it run for a fixed duration, then triggers graceful shutdown.
    4. Query the database with ``queryRealtimeData`` / ``queryConnectionLog``
       and assert the expected rows exist.

**Available helpers (importable from this module):**

    ``runOrchestratorWithTimer(config, durationSeconds)``
        Run orchestrator in simulate mode for a fixed duration with automatic
        graceful shutdown. Returns ``{exitCode, exception, elapsed}``.

    ``queryRealtimeData(dbPath)``
        Query all rows from ``realtime_data``. Returns list of dicts with
        keys: id, timestamp, parameter_name, value, unit, profile_id.

    ``queryConnectionLog(dbPath)``
        Query all rows from ``connection_log``. Returns list of dicts with
        keys: id, timestamp, event_type, mac_address, success, error_message,
        retry_count.

    ``assertParameterInRange(rows, paramName, minVal, maxVal)``
        Filter ``rows`` to the given ``paramName`` and assert every value
        falls within ``[minVal, maxVal]``. Raises ``AssertionError`` with a
        descriptive message if out of range or if no rows match.

    ``groupRowsByParameter(rows)``
        Group a list of realtime_data row dicts by ``parameter_name``.
        Returns ``dict[str, list[dict]]``.

    ``getSimValidationConfig(dbPath)``
        Build a complete orchestrator config dict for simulate mode, pointed
        at the given temp DB path. Includes all 13 logged parameters, fast
        polling, short drive detection windows, and headless display.

**Adding a new parameter range check:**

    To verify a newly-added parameter stays within physics-model bounds, add a
    call to ``assertParameterInRange`` inside an existing or new test::

        def test_simulateMode_boostInRange(self, simRunResult):
            rows = simRunResult["rows"]
            # Boost pressure: 0-25 psi for stock 4G63 turbo
            assertParameterInRange(rows, "BOOST_PRESSURE", 0.0, 25.0)

    If the parameter isn't in ``LOGGED_PARAMETERS`` yet, add it to both the
    constant list and the config's ``realtimeData.parameters`` (with
    ``logData: True``).

**Origin:** B-026 (Simulate DB Validation PRD)
**See also:** specs/methodology.md Section 3 — Definition of Done
"""

import sqlite3
import threading
import time
from datetime import datetime
from typing import Any

import pytest

from obd.orchestrator import ApplicationOrchestrator, ShutdownState

# ================================================================================
# Constants
# ================================================================================

# The 13 parameters configured with logData: true in the test config
LOGGED_PARAMETERS = [
    "RPM",
    "SPEED",
    "COOLANT_TEMP",
    "ENGINE_LOAD",
    "THROTTLE_POS",
    "INTAKE_TEMP",
    "MAF",
    "FUEL_PRESSURE",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "TIMING_ADVANCE",
    "INTAKE_PRESSURE",
    "O2_B1S1",
]

# Simulation duration in seconds (enough for multiple logging cycles and
# drive detection to trigger)
SIMULATION_DURATION_SECONDS = 15

# RPM idle range for the default vehicle profile (idleRpm=800, +/- noise)
RPM_IDLE_MIN = 600
RPM_IDLE_MAX = 1200


# ================================================================================
# Test Configuration
# ================================================================================


def getSimValidationConfig(dbPath: str) -> dict[str, Any]:
    """
    Create test configuration for simulate DB validation.

    Configures all 13 logged parameters, short drive detection windows,
    and fast polling for quicker data accumulation.

    Args:
        dbPath: Path to temporary database file

    Returns:
        Configuration dictionary for orchestrator
    """
    return {
        "application": {
            "name": "Simulate DB Validation Test",
            "version": "1.0.0",
            "environment": "test",
        },
        "database": {
            "path": dbPath,
            "walMode": True,
            "vacuumOnStartup": False,
            "backupOnShutdown": False,
        },
        "bluetooth": {
            "macAddress": "SIMULATED",
            "retryDelays": [0.1],
            "maxRetries": 1,
            "connectionTimeoutSeconds": 5,
        },
        "vinDecoder": {
            "enabled": False,
            "apiBaseUrl": "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues",
            "apiTimeoutSeconds": 5,
            "cacheVinData": False,
        },
        "display": {
            "mode": "headless",
            "width": 240,
            "height": 240,
            "refreshRateMs": 1000,
            "brightness": 100,
            "showOnStartup": False,
        },
        "staticData": {
            "parameters": ["VIN"],
            "queryOnFirstConnection": False,
        },
        "realtimeData": {
            "pollingIntervalMs": 500,  # 2 Hz polling for reasonable data volume
            "parameters": [
                {"name": "RPM", "logData": True, "displayOnDashboard": True},
                {"name": "SPEED", "logData": True, "displayOnDashboard": True},
                {"name": "COOLANT_TEMP", "logData": True, "displayOnDashboard": True},
                {"name": "ENGINE_LOAD", "logData": True, "displayOnDashboard": False},
                {"name": "THROTTLE_POS", "logData": True, "displayOnDashboard": False},
                {"name": "INTAKE_TEMP", "logData": True, "displayOnDashboard": False},
                {"name": "MAF", "logData": True, "displayOnDashboard": False},
                {"name": "FUEL_PRESSURE", "logData": True, "displayOnDashboard": False},
                {"name": "SHORT_FUEL_TRIM_1", "logData": True, "displayOnDashboard": False},
                {"name": "LONG_FUEL_TRIM_1", "logData": True, "displayOnDashboard": False},
                {"name": "TIMING_ADVANCE", "logData": True, "displayOnDashboard": False},
                {"name": "INTAKE_PRESSURE", "logData": True, "displayOnDashboard": False},
                {"name": "O2_B1S1", "logData": True, "displayOnDashboard": False},
                {"name": "COMMANDED_EGR", "logData": False, "displayOnDashboard": False},
                {"name": "BAROMETRIC_PRESSURE", "logData": False, "displayOnDashboard": False},
            ],
        },
        "analysis": {
            "triggerAfterDrive": False,  # Don't trigger post-drive analysis in test
            "driveStartRpmThreshold": 500,
            "driveStartDurationSeconds": 3,  # Short for test — drive detected after 3s
            "driveEndRpmThreshold": 100,
            "driveEndDurationSeconds": 5,
            "calculateStatistics": ["max", "min", "avg"],
        },
        "aiAnalysis": {"enabled": False},
        "profiles": {
            "activeProfile": "test",
            "availableProfiles": [
                {
                    "id": "test",
                    "name": "Test Profile",
                    "description": "Profile for DB validation tests",
                    "pollingIntervalMs": 500,
                }
            ],
        },
        "tieredThresholds": {
            "rpm": {"unit": "rpm", "dangerMin": 7000},
            "coolantTemp": {"unit": "fahrenheit", "dangerMin": 220},
        },
        "alerts": {
            "enabled": False,  # Alerts not needed for DB validation
            "cooldownSeconds": 60,
            "visualAlerts": False,
            "audioAlerts": False,
            "logAlerts": False,
        },
        "monitoring": {
            "healthCheckIntervalSeconds": 60,
            "dataRateLogIntervalSeconds": 60,
        },
        "shutdown": {"componentTimeout": 5},
        "simulator": {
            "enabled": True,
            "connectionDelaySeconds": 0,
            "updateIntervalMs": 100,
        },
        "logging": {"level": "WARNING", "maskPII": False},
    }


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def simDbPath(tmp_path):
    """
    Create a temporary database path for the simulation test.

    Uses pytest's tmp_path fixture for automatic cleanup.

    Returns:
        Path string to temporary database file
    """
    return str(tmp_path / "sim_validation.db")


@pytest.fixture
def simConfig(simDbPath: str) -> dict[str, Any]:
    """
    Create simulation validation test configuration.

    Args:
        simDbPath: Temporary database path

    Returns:
        Test configuration dictionary
    """
    return getSimValidationConfig(simDbPath)


# ================================================================================
# Helpers
# ================================================================================


def runOrchestratorWithTimer(
    config: dict[str, Any],
    durationSeconds: float,
) -> dict[str, Any]:
    """
    Run the orchestrator in simulate mode for a fixed duration.

    Starts the orchestrator, runs the main loop in a background thread,
    then uses a threading.Timer to trigger graceful shutdown after the
    specified duration.

    Args:
        config: Orchestrator configuration dictionary
        durationSeconds: How long to run before triggering shutdown

    Returns:
        Dict with keys:
            - exitCode: int from orchestrator.stop()
            - exception: Exception or None if an error occurred
            - elapsed: float seconds the simulation ran
    """
    orchestrator = ApplicationOrchestrator(config=config, simulate=True)
    result: dict[str, Any] = {"exitCode": -1, "exception": None, "elapsed": 0.0}

    def triggerShutdown() -> None:
        """Timer callback to request graceful shutdown."""
        orchestrator._shutdownState = ShutdownState.SHUTDOWN_REQUESTED

    # Start orchestrator
    orchestrator.start()
    startTime = time.time()

    # Schedule shutdown
    shutdownTimer = threading.Timer(durationSeconds, triggerShutdown)
    shutdownTimer.daemon = True
    shutdownTimer.start()

    # Run main loop in current thread context via a background thread
    loopException: list[Exception] = []

    def runLoop() -> None:
        try:
            orchestrator.runLoop()
        except Exception as e:
            loopException.append(e)

    loopThread = threading.Thread(target=runLoop, daemon=True)
    loopThread.start()

    # Wait for loop to finish (timer will trigger shutdown)
    loopThread.join(timeout=durationSeconds + 10)

    result["elapsed"] = time.time() - startTime

    # Stop orchestrator (cleans up remaining components)
    try:
        result["exitCode"] = orchestrator.stop()
    except Exception as e:
        result["exception"] = e

    # Cancel timer if it hasn't fired yet
    shutdownTimer.cancel()

    if loopException:
        result["exception"] = loopException[0]

    return result


def queryRealtimeData(dbPath: str) -> list[dict[str, Any]]:
    """
    Query all rows from the realtime_data table.

    Args:
        dbPath: Path to the database file

    Returns:
        List of dicts with keys: id, timestamp, parameter_name, value, unit,
        profile_id
    """
    with sqlite3.connect(dbPath) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, parameter_name, value, unit, profile_id "
            "FROM realtime_data ORDER BY timestamp"
        )
        return [dict(row) for row in cursor.fetchall()]


def queryConnectionLog(dbPath: str) -> list[dict[str, Any]]:
    """
    Query all rows from the connection_log table.

    Args:
        dbPath: Path to the database file

    Returns:
        List of dicts with keys: id, timestamp, event_type, mac_address,
        success, error_message, retry_count
    """
    with sqlite3.connect(dbPath) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, event_type, mac_address, success, "
            "error_message, retry_count FROM connection_log ORDER BY timestamp"
        )
        return [dict(row) for row in cursor.fetchall()]


def assertParameterInRange(
    rows: list[dict[str, Any]],
    paramName: str,
    minVal: float,
    maxVal: float,
) -> None:
    """
    Assert that all values for a given parameter fall within [minVal, maxVal].

    Filters the provided rows to only those matching paramName, then checks
    each value. Useful for validating simulated sensor values stay within
    physics-model bounds.

    Args:
        rows: List of realtime_data row dicts (must have 'parameter_name',
              'value' keys)
        paramName: The parameter name to filter on
        minVal: Minimum acceptable value (inclusive)
        maxVal: Maximum acceptable value (inclusive)

    Raises:
        AssertionError: If any value is outside the range, or no rows found
    """
    paramRows = [r for r in rows if r["parameter_name"] == paramName]
    assert len(paramRows) > 0, f"No rows found for parameter '{paramName}'"

    for row in paramRows:
        value = row["value"]
        assert minVal <= value <= maxVal, (
            f"{paramName} value {value} outside range [{minVal}, {maxVal}] "
            f"at timestamp {row['timestamp']}"
        )


# ================================================================================
# Tests
# ================================================================================


@pytest.mark.slow
@pytest.mark.integration
class TestSimulateDbValidation:
    """
    Integration test: run orchestrator in simulate mode, validate DB output.

    This is the reference implementation of the Definition of Done pattern
    from specs/methodology.md. Future DB validation tests can follow this
    structure.
    """

    def test_simulateMode_logsDataForAll13Parameters(
        self, simConfig: dict[str, Any], simDbPath: str
    ):
        """
        Given: Orchestrator configured with 13 logged parameters in simulate mode
        When: Orchestrator runs for ~15 seconds
        Then: realtime_data contains rows for all 13 parameters
        """
        # Act
        result = runOrchestratorWithTimer(simConfig, SIMULATION_DURATION_SECONDS)

        # Assert — no unhandled exceptions
        assert result["exception"] is None, (
            f"Orchestrator raised exception: {result['exception']}"
        )

        # Assert — query database
        rows = queryRealtimeData(simDbPath)
        assert len(rows) > 0, "No rows in realtime_data after simulation"

        # Verify all 13 parameters have at least one row
        loggedParamNames = {r["parameter_name"] for r in rows}
        for param in LOGGED_PARAMETERS:
            assert param in loggedParamNames, (
                f"Parameter '{param}' not found in realtime_data. "
                f"Found: {sorted(loggedParamNames)}"
            )

    def test_simulateMode_validatesTimestampValueUnit(
        self, simConfig: dict[str, Any], simDbPath: str
    ):
        """
        Given: Orchestrator ran in simulate mode with data logged
        When: Each row in realtime_data is inspected
        Then: timestamp is valid datetime, value is numeric, unit is non-empty
        """
        # Act
        result = runOrchestratorWithTimer(simConfig, SIMULATION_DURATION_SECONDS)
        assert result["exception"] is None

        rows = queryRealtimeData(simDbPath)
        assert len(rows) > 0

        for row in rows:
            # Timestamp is valid datetime (parseable)
            ts = row["timestamp"]
            assert ts is not None, "timestamp is None"
            # SQLite stores timestamps as strings; verify they parse
            if isinstance(ts, str):
                try:
                    datetime.fromisoformat(ts)
                except ValueError:
                    # Try common SQLite format
                    datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")

            # Value is numeric (not None, not NaN)
            value = row["value"]
            assert value is not None, (
                f"value is None for {row['parameter_name']}"
            )
            assert isinstance(value, (int, float)), (
                f"value is not numeric for {row['parameter_name']}: "
                f"{type(value)} = {value}"
            )

            # Unit is set (non-empty string)
            unit = row["unit"]
            assert unit is not None and unit != "", (
                f"unit is empty/None for {row['parameter_name']}"
            )

    def test_simulateMode_rpmInIdleRange(
        self, simConfig: dict[str, Any], simDbPath: str
    ):
        """
        Given: Orchestrator ran in simulate mode (engine at idle, no throttle)
        When: RPM values are inspected
        Then: All RPM values are within realistic idle range (600-1200)
        """
        # Act
        result = runOrchestratorWithTimer(simConfig, SIMULATION_DURATION_SECONDS)
        assert result["exception"] is None

        rows = queryRealtimeData(simDbPath)
        assertParameterInRange(rows, "RPM", RPM_IDLE_MIN, RPM_IDLE_MAX)

    def test_simulateMode_connectionLogHasDriveStart(
        self, simConfig: dict[str, Any], simDbPath: str
    ):
        """
        Given: Orchestrator ran for ~15 seconds (idle RPM 800 > threshold 500)
        When: connection_log is queried
        Then: At least one drive_start event exists
        """
        # Act
        result = runOrchestratorWithTimer(simConfig, SIMULATION_DURATION_SECONDS)
        assert result["exception"] is None

        # Assert
        connectionLogs = queryConnectionLog(simDbPath)
        driveStartEvents = [
            e for e in connectionLogs if e["event_type"] == "drive_start"
        ]
        assert len(driveStartEvents) >= 1, (
            f"Expected at least 1 drive_start event, found {len(driveStartEvents)}. "
            f"All events: {[e['event_type'] for e in connectionLogs]}"
        )

    def test_simulateMode_gracefulShutdown_noExceptions(
        self, simConfig: dict[str, Any], simDbPath: str
    ):
        """
        Given: Orchestrator running in simulate mode
        When: Graceful shutdown is triggered via Timer
        Then: Shutdown completes with exit code 0 and no unhandled exceptions
        """
        # Act
        result = runOrchestratorWithTimer(simConfig, SIMULATION_DURATION_SECONDS)

        # Assert
        assert result["exception"] is None, (
            f"Unhandled exception during simulation: {result['exception']}"
        )
        assert result["exitCode"] == 0, (
            f"Expected exit code 0, got {result['exitCode']}"
        )


# ================================================================================
# US-102: Parameter Completeness and Data Quality Tests
# ================================================================================


def groupRowsByParameter(
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Group realtime_data rows by parameter_name.

    Args:
        rows: List of realtime_data row dicts

    Returns:
        Dict mapping parameter_name to list of rows for that parameter
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        paramName = row["parameter_name"]
        if paramName not in grouped:
            grouped[paramName] = []
        grouped[paramName].append(row)
    return grouped


@pytest.fixture
def simRunResult(simConfig: dict[str, Any], simDbPath: str):
    """
    Run the orchestrator once and return both the result and DB rows.

    Shared fixture so US-102 tests don't each pay the ~15s simulation cost.
    Returns a dict with keys: result, rows, dbPath.
    """
    result = runOrchestratorWithTimer(simConfig, SIMULATION_DURATION_SECONDS)
    assert result["exception"] is None, (
        f"Orchestrator raised exception: {result['exception']}"
    )
    rows = queryRealtimeData(simDbPath)
    assert len(rows) > 0, "No rows in realtime_data after simulation"
    return {"result": result, "rows": rows, "dbPath": simDbPath}


@pytest.mark.slow
@pytest.mark.integration
class TestParameterCompletenessAndDataQuality:
    """
    US-102: Validate parameter completeness and data quality.

    Builds on US-101 to verify data quality beyond existence: timestamps
    should be sequential, multiple samples per parameter, no NULLs, and
    no duplicates.
    """

    def test_timestampsMonotonicallyIncreasingPerParameter(
        self, simRunResult: dict[str, Any]
    ):
        """
        Given: Orchestrator ran in simulate mode with data logged
        When: Timestamps are inspected per parameter
        Then: Each parameter's timestamps are monotonically increasing
        """
        # Arrange
        rows = simRunResult["rows"]
        grouped = groupRowsByParameter(rows)

        # Assert — each parameter's timestamps are strictly non-decreasing
        for paramName, paramRows in grouped.items():
            timestamps = []
            for row in paramRows:
                ts = row["timestamp"]
                if isinstance(ts, str):
                    try:
                        parsed = datetime.fromisoformat(ts)
                    except ValueError:
                        parsed = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
                else:
                    parsed = ts
                timestamps.append(parsed)

            for i in range(1, len(timestamps)):
                assert timestamps[i] >= timestamps[i - 1], (
                    f"{paramName}: timestamp[{i}] ({timestamps[i]}) < "
                    f"timestamp[{i - 1}] ({timestamps[i - 1]}) — "
                    f"not monotonically increasing"
                )

    def test_atLeastTwoDataPointsPerParameter(
        self, simRunResult: dict[str, Any]
    ):
        """
        Given: Orchestrator ran for ~15 seconds at 2Hz polling
        When: Row counts per parameter are inspected
        Then: Each logged parameter has at least 2 data points
        """
        # Arrange
        rows = simRunResult["rows"]
        grouped = groupRowsByParameter(rows)

        # Assert — all 13 parameters present with >= 2 rows each
        for param in LOGGED_PARAMETERS:
            assert param in grouped, (
                f"Parameter '{param}' not found in realtime_data"
            )
            count = len(grouped[param])
            assert count >= 2, (
                f"Parameter '{param}' has only {count} data point(s), "
                f"expected at least 2 (confirms continuous logging)"
            )

    def test_noNullValuesInRequiredColumns(
        self, simRunResult: dict[str, Any]
    ):
        """
        Given: Orchestrator ran in simulate mode with data logged
        When: Required columns are inspected for each row
        Then: No NULL values in timestamp, parameter_name, value, or unit
        """
        # Arrange
        rows = simRunResult["rows"]

        # Assert
        for i, row in enumerate(rows):
            assert row["timestamp"] is not None, (
                f"Row {i}: timestamp is NULL"
            )
            assert row["parameter_name"] is not None, (
                f"Row {i}: parameter_name is NULL"
            )
            assert row["value"] is not None, (
                f"Row {i}: value is NULL "
                f"(parameter: {row['parameter_name']})"
            )
            assert row["unit"] is not None, (
                f"Row {i}: unit is NULL "
                f"(parameter: {row['parameter_name']})"
            )

    def test_noDuplicateTimestampParameterCombinations(
        self, simRunResult: dict[str, Any]
    ):
        """
        Given: Orchestrator ran in simulate mode with data logged
        When: (timestamp, parameter_name) pairs are inspected
        Then: No duplicate combinations exist
        """
        # Arrange
        rows = simRunResult["rows"]

        # Act — collect all (timestamp, parameter_name) pairs
        seen: set[tuple[str, str]] = set()
        duplicates: list[tuple[str, str]] = []

        for row in rows:
            key = (str(row["timestamp"]), row["parameter_name"])
            if key in seen:
                duplicates.append(key)
            seen.add(key)

        # Assert
        assert len(duplicates) == 0, (
            f"Found {len(duplicates)} duplicate (timestamp, parameter_name) "
            f"combinations: {duplicates[:5]}"  # Show first 5
        )

    def test_assertParameterInRange_reusableHelper(
        self, simRunResult: dict[str, Any]
    ):
        """
        Given: The assertParameterInRange helper exists for reuse
        When: Used to validate multiple parameters from a real simulation run
        Then: All parameters pass their expected ranges

        This test validates that the helper works correctly against real
        simulation data and demonstrates its reuse pattern for future tests.
        """
        # Arrange
        rows = simRunResult["rows"]

        # Act / Assert — validate several parameters with known sim ranges
        # RPM at idle: 600-1200
        assertParameterInRange(rows, "RPM", RPM_IDLE_MIN, RPM_IDLE_MAX)

        # Coolant temp: 0-130°C (simulator starts cold, warms up)
        assertParameterInRange(rows, "COOLANT_TEMP", 0, 130)

        # Engine load: 0-100%
        assertParameterInRange(rows, "ENGINE_LOAD", 0, 100)

        # Throttle position: 0-100%
        assertParameterInRange(rows, "THROTTLE_POS", 0, 100)
