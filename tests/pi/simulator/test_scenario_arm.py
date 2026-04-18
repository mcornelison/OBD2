################################################################################
# File Name: test_scenario_arm.py
# Purpose/Description: ARM-validation tests for the built-in drive scenarios
#                      used by src/pi/main.py --simulate. Runs each scenario to
#                      completion against SensorSimulator + DriveScenarioRunner,
#                      and exercises the full_cycle scenario through
#                      DriveDetector + StatisticsEngine to confirm drive_start
#                      / drive_end / statistics rows are produced.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation for US-177 (Pi Crawl)
# ================================================================================
################################################################################

"""
ARM/Pi validation tests for the four built-in drive scenarios.

These tests were added for Sprint 10 / US-177 (Pi Crawl) to prove that the
simulator + scenario pipeline that runs under ``python src/pi/main.py
--simulate`` works end-to-end on aarch64 Raspberry Pi OS.  The same tests run
on Windows as part of the fast suite and serve as a regression gate for any
future changes to the scenario JSON, the runner, or the detector/statistics
plumbing.

Tests:
    test_builtInScenario_loadsAndRunsToCompletion[scenarioName]
        Each of cold_start / city_driving / highway_cruise / full_cycle loads
        from JSON, runs through all phases on a fast-forwarded clock, and
        reaches ScenarioState.COMPLETED without raising.

    test_fullCycle_driveDetector_producesStartEndAndStatistics
        The full_cycle scenario drives a live SensorSimulator whose RPM is
        fed to a real DriveDetector backed by a temp SQLite database.  After
        the scenario completes, the engine is stopped (RPM -> 0) so the
        end-of-drive threshold fires; statistics are then calculated
        synchronously via StatisticsEngine.calculateStatistics().  Verifies
        that connection_log contains drive_start + drive_end events and the
        statistics table contains at least one row for the test profile.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

# tests/conftest.py puts src/ on sys.path; these imports resolve from there.
from pi.analysis import createStatisticsEngineFromConfig
from pi.obd.database import ObdDatabase
from pi.obd.drive import DriveDetector
from pi.obd.simulator import (
    DriveScenarioRunner,
    ScenarioState,
    SensorSimulator,
    getBuiltInScenario,
    loadScenario,
)

# ================================================================================
# Constants
# ================================================================================

# Scenario JSON files live next to the simulator package.
SCENARIOS_DIR = (
    Path(__file__).resolve().parents[3]
    / "src" / "pi" / "obd" / "simulator" / "scenarios"
)

BUILT_IN_SCENARIO_NAMES = [
    "cold_start",
    "city_driving",
    "highway_cruise",
    "full_cycle",
]

# Parameter values we feed into realtime_data so StatisticsEngine has something
# to aggregate after the scenario finishes.
LOGGED_PARAMS = ("RPM", "SPEED", "COOLANT_TEMP", "THROTTLE_POS", "ENGINE_LOAD")


# ================================================================================
# Helpers
# ================================================================================


def _driveScenarioFastForward(
    runner: DriveScenarioRunner,
    simulator: SensorSimulator,
    *,
    deltaSeconds: float = 2.0,
    maxRealSeconds: float = 120.0,
    realSleep: float = 0.01,
    onTick: Any | None = None,
) -> int:
    """
    Advance a scenario as fast as practical while leaving real wall-clock
    time for the DriveDetector's duration thresholds to accumulate.

    Args:
        runner: the DriveScenarioRunner to advance.
        simulator: the SensorSimulator the runner controls — updated each tick.
        deltaSeconds: sim-seconds to feed runner.update() per iteration.
        maxRealSeconds: hard real-time cap so a broken scenario can't hang CI.
        realSleep: seconds of real sleep between ticks (lets wall-clock advance).
        onTick: optional callable invoked with (simulator) each tick.

    Returns:
        Number of ticks taken to reach a non-RUNNING state.
    """
    wallStart = time.time()
    ticks = 0
    while runner.state == ScenarioState.RUNNING:
        runner.update(deltaSeconds)
        if onTick is not None:
            onTick(simulator)
        ticks += 1
        if time.time() - wallStart > maxRealSeconds:
            pytest.fail(
                f"Scenario did not complete within {maxRealSeconds}s wall-clock "
                f"(ticks={ticks}, state={runner.state})"
            )
        time.sleep(realSleep)
    return ticks


def _insertProfile(database: ObdDatabase, profileId: str) -> None:
    """Insert a minimal profile row so FK constraints on statistics pass."""
    with database.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR IGNORE INTO profiles (id, name, description)
            VALUES (?, ?, ?)
            """,
            (profileId, "ARM test profile", "Created by test_scenario_arm.py"),
        )


def _insertRealtimeRow(
    database: ObdDatabase,
    profileId: str,
    parameterName: str,
    value: float,
) -> None:
    with database.connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO realtime_data (timestamp, parameter_name, value, unit, profile_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (datetime.now(), parameterName, float(value), "", profileId),
        )


# ================================================================================
# Tests — per-scenario completion (AC: all 4 scenarios run individually)
# ================================================================================


@pytest.mark.parametrize("scenarioName", BUILT_IN_SCENARIO_NAMES)
def test_builtInScenario_loadsAndRunsToCompletion(scenarioName: str) -> None:
    """
    Given: one of the four built-in scenario JSON files
    When: loaded via loadScenario() and driven by DriveScenarioRunner using
          fast-forward ticks
    Then: reaches ScenarioState.COMPLETED without any phase callback raising.
    """
    scenarioPath = SCENARIOS_DIR / f"{scenarioName}.json"
    scenario = loadScenario(str(scenarioPath))
    assert scenario.name == scenarioName
    assert scenario.phases, f"Scenario {scenarioName} has no phases"

    # Confirm JSON copy matches the python built-in factory — protects against
    # drift between scenarios/*.json and scenario_builtins.py.
    builtIn = getBuiltInScenario(scenarioName)
    assert len(scenario.phases) == len(builtIn.phases), (
        f"Phase count drift between {scenarioPath.name} and the built-in "
        f"factory for {scenarioName}: json={len(scenario.phases)} "
        f"factory={len(builtIn.phases)}"
    )

    simulator = SensorSimulator()
    simulator.startEngine()
    runner = DriveScenarioRunner(simulator=simulator, scenario=scenario)

    startedOk = runner.start()
    assert startedOk is True

    # Fast-forward: feed 10 sim-seconds per tick, no real sleep — we don't
    # need wall-clock to accumulate for this test.
    _driveScenarioFastForward(
        runner, simulator,
        deltaSeconds=10.0, maxRealSeconds=30.0, realSleep=0.0,
    )

    assert runner.state == ScenarioState.COMPLETED, (
        f"Scenario {scenarioName} ended in {runner.state}, expected COMPLETED"
    )
    expectedLoops = max(1, scenario.loopCount) if scenario.loopCount > 0 else 1
    assert runner.loopsCompleted >= expectedLoops, (
        f"Scenario {scenarioName}: loopsCompleted={runner.loopsCompleted} "
        f"expected at least {expectedLoops}"
    )


# ================================================================================
# Test — full_cycle drives detector + statistics (AC #3, #4)
# ================================================================================


@pytest.mark.integration
def test_fullCycle_driveDetector_producesStartEndAndStatistics(tmp_path: Path) -> None:
    """
    Given: the full_cycle scenario running against a live SensorSimulator,
           DriveDetector, and StatisticsEngine backed by a temp SQLite DB
    When: the scenario fast-forwards to completion and the engine then stops
    Then: connection_log contains drive_start and drive_end events for the
          test profile, and statistics contains at least one row.

    This is the acceptance gate for US-177 #3 (drive start + end in SQLite)
    and #4 (non-empty drive_statistics row).  The table is named ``statistics``
    in schema — spec wording "drive_statistics" refers to that table.
    """
    profileId = "arm_test"
    dbPath = str(tmp_path / "arm_scenario.db")

    config: dict[str, Any] = {
        "pi": {
            "database": {
                "path": dbPath,
                "walMode": True,
                "vacuumOnStartup": False,
                "backupOnShutdown": False,
            },
            "analysis": {
                # Narrow thresholds so wall-clock compresses comfortably:
                # driveStart fires after 0.3s above 500rpm; driveEnd fires
                # after 0.3s at/below 100rpm once engine stops.
                "triggerAfterDrive": False,
                "driveStartRpmThreshold": 500,
                "driveStartDurationSeconds": 0.3,
                "driveEndRpmThreshold": 100,
                "driveEndDurationSeconds": 0.3,
                "calculateStatistics": ["max", "min", "avg"],
            },
            "profiles": {"activeProfile": profileId},
        },
    }

    database = ObdDatabase(dbPath, walMode=True)
    database.initialize()
    _insertProfile(database, profileId)

    statsEngine = createStatisticsEngineFromConfig(database, config)
    detector = DriveDetector(config, statisticsEngine=statsEngine, database=database)
    assert detector.start() is True

    scenario = loadScenario(str(SCENARIOS_DIR / "full_cycle.json"))
    simulator = SensorSimulator()
    simulator.startEngine()
    runner = DriveScenarioRunner(simulator=simulator, scenario=scenario)
    assert runner.start() is True

    # On each tick, copy the simulator state into realtime_data + feed the
    # detector so it sees RPM/SPEED swings.  Real sleep 10ms per tick keeps
    # wall-clock accumulation above the 0.3s duration thresholds.
    def _tick(sim: SensorSimulator) -> None:
        _insertRealtimeRow(database, profileId, "RPM", sim.state.rpm)
        _insertRealtimeRow(database, profileId, "SPEED", sim.state.speedKph)
        _insertRealtimeRow(database, profileId, "COOLANT_TEMP", sim.state.coolantTempC)
        _insertRealtimeRow(database, profileId, "THROTTLE_POS", sim.state.throttlePercent)
        _insertRealtimeRow(database, profileId, "ENGINE_LOAD", sim.state.engineLoad)
        detector.processValue("RPM", sim.state.rpm)
        detector.processValue("SPEED", sim.state.speedKph)

    _driveScenarioFastForward(
        runner, simulator,
        deltaSeconds=8.0, maxRealSeconds=60.0, realSleep=0.01,
        onTick=_tick,
    )
    assert runner.state == ScenarioState.COMPLETED

    # Drop RPM to 0 so detector's end-of-drive threshold trips.  Without
    # this, full_cycle's "park" phase idles at ~800rpm which is above the
    # 100rpm end threshold.  Keep feeding zero RPM until the session fully
    # ends: DriveDetector transitions RUNNING -> STOPPING on the first
    # zero-RPM value, then emits drive_end once driveEndDurationSeconds of
    # wall-clock accumulates in STOPPING.  So check getCurrentSession(),
    # not isDriving() (which only covers the RUNNING state).
    simulator.stopEngine()
    endDeadline = time.time() + 5.0
    while detector.getCurrentSession() is not None and time.time() < endDeadline:
        detector.processValue("RPM", 0.0)
        detector.processValue("SPEED", 0.0)
        time.sleep(0.05)

    # Belt-and-suspenders: if the detector still holds an active session
    # (e.g. wall-clock slipped), calling stop() mid-RUNNING forces an end.
    detector.stop()

    # Assert: connection_log has both drive_start and drive_end for this profile
    with sqlite3.connect(dbPath) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT event_type FROM connection_log "
            "WHERE event_type IN ('drive_start', 'drive_end') "
            "ORDER BY rowid"
        )
        events = [row["event_type"] for row in cursor.fetchall()]

    assert "drive_start" in events, (
        f"Expected drive_start in connection_log; got events={events}"
    )
    assert "drive_end" in events, (
        f"Expected drive_end in connection_log; got events={events}"
    )

    # Synchronously calculate statistics and assert a row lands in the table.
    statsEngine.calculateStatistics(profileId=profileId, storeResults=True)

    with sqlite3.connect(dbPath) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM statistics WHERE profile_id = ?",
            (profileId,),
        )
        statRowCount = cursor.fetchone()[0]

    assert statRowCount > 0, (
        f"Expected at least one row in statistics for profile {profileId}"
    )


# ================================================================================
# Platform capture — logs the aarch64/Python line required by AC #7.
# Not a correctness assertion; just emits the string into pytest output so the
# Pi run captures it.  Runs cheap everywhere.
# ================================================================================


def test_platformCapture_emitsVersionLine(capsys: pytest.CaptureFixture[str]) -> None:
    """Emit the platform string required by US-177 completion note."""
    import platform

    line = f"{sys.version} {platform.machine()}"
    print(f"PLATFORM_CAPTURE: {line}")
    captured = capsys.readouterr()
    assert "PLATFORM_CAPTURE:" in captured.out
