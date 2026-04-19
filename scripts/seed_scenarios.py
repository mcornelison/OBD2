################################################################################
# File Name: seed_scenarios.py
# Purpose/Description: Run Pi simulator scenarios and export to portable SQLite
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-156 (Sprint 7)
# ================================================================================
################################################################################

"""
Seed scenario script for the Server Crawl phase.

Runs the existing Pi simulator (SensorSimulator + DriveScenarioRunner) at
accelerated speed and exports the generated data to a standalone SQLite file
matching the Pi's database schema.  The output is consumed by load_data.py
to populate MariaDB on Chi-Srv-01.

Usage:
    # Single scenario
    python scripts/seed_scenarios.py --scenario city_driving --output data/sim_city.db

    # All 4 scenarios into one database (multiple drive sessions)
    python scripts/seed_scenarios.py --all --output data/sim_all.db
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Ensure project root and src/ are on sys.path for absolute imports.
# src/ is needed because pi.obdii.__init__ uses ``from pi.display import ...``
# (relative to src/).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from src.pi.obdii.database_schema import (  # noqa: E402
    SCHEMA_CONNECTION_LOG,
    SCHEMA_REALTIME_DATA,
    SCHEMA_STATISTICS,
)
from src.pi.obdii.simulator.scenario_builtins import (  # noqa: E402
    getCityDrivingScenario,
    getColdStartScenario,
    getFullCycleScenario,
    getHighwayCruiseScenario,
)
from src.pi.obdii.simulator.scenario_runner import DriveScenarioRunner  # noqa: E402
from src.pi.obdii.simulator.scenario_types import DriveScenario  # noqa: E402
from src.pi.obdii.simulator.sensor_simulator import SensorSimulator  # noqa: E402
from src.pi.obdii.simulator.vehicle_profile import getDefaultProfile  # noqa: E402

logger = logging.getLogger(__name__)

# ================================================================================
# Constants
# ================================================================================

# Simulation time step — 1 second per update tick (no wall-clock sleep)
SIM_TIME_STEP = 1.0

# Sample sensor readings every N seconds of simulation time
SAMPLE_INTERVAL = 1.0

# Parameters to capture from the simulator
SAMPLED_PARAMETERS: list[tuple[str, str]] = [
    ("RPM", "rpm"),
    ("SPEED", "km/h"),
    ("COOLANT_TEMP", "°C"),
    ("ENGINE_LOAD", "%"),
    ("MAF", "g/s"),
    ("INTAKE_TEMP", "°C"),
    ("THROTTLE_POS", "%"),
    ("O2_B1S1", "V"),
    ("SHORT_FUEL_TRIM_1", "%"),
    ("LONG_FUEL_TRIM_1", "%"),
    ("TIMING_ADVANCE", "°"),
    ("INTAKE_PRESSURE", "kPa"),
    ("FUEL_PRESSURE", "kPa"),
    ("CONTROL_MODULE_VOLTAGE", "V"),
    ("RUN_TIME", "s"),
]

# Map of scenario name → factory function
SCENARIO_MAP: dict[str, Any] = {
    "city_driving": getCityDrivingScenario,
    "highway_cruise": getHighwayCruiseScenario,
    "cold_start": getColdStartScenario,
    "full_cycle": getFullCycleScenario,
}

# Default profile ID used for seeded data
DEFAULT_PROFILE_ID = "daily"


# ================================================================================
# Database Helpers
# ================================================================================

def _createDatabase(dbPath: str) -> sqlite3.Connection:
    """
    Create a SQLite database with the Pi-compatible schema.

    Args:
        dbPath: Path for the new database file.

    Returns:
        Open sqlite3 connection.
    """
    conn = sqlite3.connect(dbPath)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")

    conn.execute(SCHEMA_REALTIME_DATA)
    conn.execute(SCHEMA_CONNECTION_LOG)
    conn.execute(SCHEMA_STATISTICS)

    conn.commit()
    return conn


def _insertRealtimeRows(
    conn: sqlite3.Connection,
    rows: list[tuple[str, str, float, str, str]],
) -> None:
    """
    Bulk-insert realtime_data rows.

    Args:
        conn: Open SQLite connection.
        rows: List of (timestamp, parameter_name, value, unit, profile_id).
    """
    conn.executemany(
        "INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def _insertConnectionEvent(
    conn: sqlite3.Connection,
    timestamp: str,
    eventType: str,
) -> None:
    """
    Insert a connection_log event.

    Args:
        conn: Open SQLite connection.
        timestamp: ISO-format timestamp.
        eventType: Event type string (e.g. 'drive_start', 'drive_end').
    """
    conn.execute(
        "INSERT INTO connection_log (timestamp, event_type, success) VALUES (?, ?, 1)",
        (timestamp, eventType),
    )


def _computeAndInsertStatistics(
    conn: sqlite3.Connection,
    analysisDate: str,
    profileId: str,
) -> None:
    """
    Compute per-parameter statistics from realtime_data and insert into statistics.

    Computes: min, max, avg, std_dev (as std_1), 2*std (as std_2),
    outlier_min (mean - 2*std), outlier_max (mean + 2*std), sample_count.

    Args:
        conn: Open SQLite connection.
        analysisDate: ISO timestamp for the analysis.
        profileId: Profile ID to associate.
    """
    cursor = conn.execute(
        "SELECT DISTINCT parameter_name FROM realtime_data"
    )
    paramNames = [row[0] for row in cursor.fetchall()]

    for param in paramNames:
        rows = conn.execute(
            "SELECT value FROM realtime_data WHERE parameter_name = ?",
            (param,),
        ).fetchall()

        values = [r[0] for r in rows]
        count = len(values)
        if count == 0:
            continue

        minVal = min(values)
        maxVal = max(values)
        avgVal = sum(values) / count
        variance = sum((v - avgVal) ** 2 for v in values) / count
        stdDev = math.sqrt(variance)
        std2 = 2.0 * stdDev
        outlierMin = avgVal - std2
        outlierMax = avgVal + std2

        conn.execute(
            "INSERT INTO statistics "
            "(parameter_name, analysis_date, profile_id, "
            "max_value, min_value, avg_value, mode_value, "
            "std_1, std_2, outlier_min, outlier_max, sample_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                param, analysisDate, profileId,
                maxVal, minVal, avgVal, None,
                stdDev, std2, outlierMin, outlierMax, count,
            ),
        )


# ================================================================================
# Simulation Engine
# ================================================================================

def _runSimulation(
    scenario: DriveScenario,
    baseTime: datetime,
) -> tuple[list[tuple[str, str, float, str, str]], float]:
    """
    Run a scenario at accelerated speed, collecting sensor readings.

    Args:
        scenario: DriveScenario to execute.
        baseTime: Starting timestamp for the simulation.

    Returns:
        Tuple of (realtimeRows, totalSimSeconds).
        realtimeRows is a list of (timestamp, parameter_name, value, unit, profile_id).
    """
    profile = getDefaultProfile()
    simulator = SensorSimulator(profile=profile, noiseEnabled=True)
    runner = DriveScenarioRunner(simulator, scenario)

    runner.start()

    rows: list[tuple[str, str, float, str, str]] = []
    simElapsed = 0.0
    nextSampleAt = 0.0

    while runner.isRunning():
        runner.update(SIM_TIME_STEP)
        simElapsed += SIM_TIME_STEP

        if simElapsed >= nextSampleAt:
            ts = (baseTime + timedelta(seconds=simElapsed)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            for paramName, unit in SAMPLED_PARAMETERS:
                value = simulator.getValue(paramName)
                if value is not None:
                    rows.append((ts, paramName, value, unit, DEFAULT_PROFILE_ID))
            nextSampleAt += SAMPLE_INTERVAL

    return rows, simElapsed


# ================================================================================
# Public API
# ================================================================================

def runScenario(scenario: str, outputPath: str) -> None:
    """
    Run a single named scenario and write results to SQLite.

    Args:
        scenario: Scenario name (key in SCENARIO_MAP).
        outputPath: Path for the output SQLite file.
    """
    factory = SCENARIO_MAP[scenario]
    scenarioObj = factory()

    conn = _createDatabase(outputPath)
    try:
        baseTime = datetime(2026, 4, 16, 8, 0, 0)
        startTs = baseTime.strftime("%Y-%m-%d %H:%M:%S")

        _insertConnectionEvent(conn, startTs, "drive_start")

        rows, simElapsed = _runSimulation(scenarioObj, baseTime)
        _insertRealtimeRows(conn, rows)

        endTs = (baseTime + timedelta(seconds=simElapsed)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        _insertConnectionEvent(conn, endTs, "drive_end")

        analysisDate = endTs
        _computeAndInsertStatistics(conn, analysisDate, DEFAULT_PROFILE_ID)

        conn.commit()
        logger.info(
            "Scenario %s: %d readings, %.0fs simulated",
            scenario, len(rows), simElapsed,
        )
    finally:
        conn.close()


def runScenarioList(
    scenarios: list[str],
    gaps: list[float],
    outputPath: str,
) -> None:
    """
    Run a user-specified sequence of scenarios into one SQLite database with
    configurable parked-time gaps between drives.

    Mirrors the real-world pattern of a single Pi accumulating multiple drives
    across a day under one device identity, with variable time parked between
    drive sessions (errands, stops, etc.). Rowids are continuous across all
    scenarios so the produced file loads cleanly via load_data.py without
    (source_device, source_id) collisions.

    Args:
        scenarios: Ordered list of scenario names (keys of SCENARIO_MAP).
            Each becomes one drive session in the output.
        gaps: Parked-time seconds between consecutive drives. Length must be
            ``len(scenarios) - 1``; pass an empty list for a single-scenario run.
        outputPath: Path for the output SQLite file.

    Raises:
        ValueError: If a scenario name is unknown or gaps length is wrong.
    """
    expectedGaps = max(0, len(scenarios) - 1)
    if len(gaps) != expectedGaps:
        raise ValueError(
            f"gaps length must be {expectedGaps} "
            f"(one fewer than scenarios), got {len(gaps)}"
        )
    for name in scenarios:
        if name not in SCENARIO_MAP:
            raise ValueError(
                f"Unknown scenario '{name}'. "
                f"Valid: {sorted(SCENARIO_MAP.keys())}"
            )

    conn = _createDatabase(outputPath)
    try:
        baseTime = datetime(2026, 4, 16, 8, 0, 0)
        offset = 0.0

        for i, scenarioName in enumerate(scenarios):
            factory = SCENARIO_MAP[scenarioName]
            scenarioObj = factory()
            driveStart = baseTime + timedelta(seconds=offset)
            startTs = driveStart.strftime("%Y-%m-%d %H:%M:%S")

            _insertConnectionEvent(conn, startTs, "drive_start")

            rows, simElapsed = _runSimulation(scenarioObj, driveStart)
            _insertRealtimeRows(conn, rows)

            endTs = (driveStart + timedelta(seconds=simElapsed)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            _insertConnectionEvent(conn, endTs, "drive_end")

            logger.info(
                "Scenario %s: %d readings, %.0fs simulated",
                scenarioName, len(rows), simElapsed,
            )

            offset += simElapsed
            if i < len(gaps):
                offset += gaps[i]

        analysisDate = (baseTime + timedelta(seconds=offset)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        _computeAndInsertStatistics(conn, analysisDate, DEFAULT_PROFILE_ID)
        conn.commit()
    finally:
        conn.close()


def runAllScenarios(outputPath: str) -> None:
    """
    Run all 4 scenarios into one SQLite database (multiple drive sessions).

    Args:
        outputPath: Path for the output SQLite file.
    """
    conn = _createDatabase(outputPath)
    try:
        baseTime = datetime(2026, 4, 16, 8, 0, 0)
        offset = 0.0

        for scenarioName, factory in SCENARIO_MAP.items():
            scenarioObj = factory()
            driveStart = baseTime + timedelta(seconds=offset)
            startTs = driveStart.strftime("%Y-%m-%d %H:%M:%S")

            _insertConnectionEvent(conn, startTs, "drive_start")

            rows, simElapsed = _runSimulation(scenarioObj, driveStart)
            _insertRealtimeRows(conn, rows)

            endTs = (driveStart + timedelta(seconds=simElapsed)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            _insertConnectionEvent(conn, endTs, "drive_end")

            logger.info(
                "Scenario %s: %d readings, %.0fs simulated",
                scenarioName, len(rows), simElapsed,
            )

            # Gap between drives (5 simulated minutes)
            offset += simElapsed + 300.0

        # Compute statistics across all data
        analysisDate = (baseTime + timedelta(seconds=offset)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        _computeAndInsertStatistics(conn, analysisDate, DEFAULT_PROFILE_ID)

        conn.commit()
    finally:
        conn.close()


# ================================================================================
# CLI
# ================================================================================

def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed argument namespace.
    """
    parser = argparse.ArgumentParser(
        description="Run Pi simulator scenarios and export to portable SQLite.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scenario",
        choices=list(SCENARIO_MAP.keys()),
        help="Run a single scenario by name.",
    )
    group.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Run all 4 scenarios into one database.",
    )
    group.add_argument(
        "--scenarios",
        help=(
            "Comma-separated sequence of scenarios accumulated into one "
            "database (e.g. cold_start,city_driving,highway_cruise,city_driving). "
            "Represents a realistic day of drives under one device id."
        ),
    )
    parser.add_argument(
        "--gaps",
        default="",
        help=(
            "Comma-separated parked-time gap seconds between drives, used "
            "with --scenarios. Length must be N-1 where N is the number of "
            "scenarios. Default: 300s between each drive."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output SQLite file path.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point.

    Args:
        argv: Optional argument list.

    Returns:
        Exit code (0 = success).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    args = parseArguments(argv)

    # Ensure output directory exists
    outputDir = os.path.dirname(args.output)
    if outputDir and not os.path.exists(outputDir):
        os.makedirs(outputDir)

    wallStart = time.monotonic()

    if args.all:
        runAllScenarios(outputPath=args.output)
    elif args.scenarios:
        scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
        if args.gaps:
            gaps = [float(g.strip()) for g in args.gaps.split(",") if g.strip()]
        else:
            gaps = [300.0] * max(0, len(scenarios) - 1)
        runScenarioList(
            scenarios=scenarios, gaps=gaps, outputPath=args.output,
        )
    else:
        runScenario(scenario=args.scenario, outputPath=args.output)

    wallElapsed = time.monotonic() - wallStart
    logger.info("Done in %.2f seconds (wall clock).", wallElapsed)

    # Print summary
    conn = sqlite3.connect(args.output)
    try:
        rtCount = conn.execute("SELECT COUNT(*) FROM realtime_data").fetchone()[0]
        clCount = conn.execute("SELECT COUNT(*) FROM connection_log").fetchone()[0]
        stCount = conn.execute("SELECT COUNT(*) FROM statistics").fetchone()[0]
        print(f"\nOutput: {args.output}")
        print(f"  realtime_data: {rtCount} rows")
        print(f"  connection_log: {clCount} rows")
        print(f"  statistics: {stCount} rows")
        print(f"  Wall clock: {wallElapsed:.2f}s")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
