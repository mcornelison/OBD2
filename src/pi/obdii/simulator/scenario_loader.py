################################################################################
# File Name: scenario_loader.py
# Purpose/Description: File I/O and built-in lookup for drive scenarios
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-037
# 2026-04-14    | Sweep 5       | Extracted from drive_scenario.py (task 4 split)
# ================================================================================
################################################################################

"""
Load, save, list, and initialize drive scenarios on disk.

JSON files live in a `scenarios/` directory next to this module. Built-in
scenarios are materialized to disk on demand (initializeBuiltInScenarios).
"""

import json
import logging
import os
from typing import Any

from .scenario_builtins import (
    getCityDrivingScenario,
    getColdStartScenario,
    getDefaultScenario,
    getFullCycleScenario,
    getHighwayCruiseScenario,
)
from .scenario_types import (
    SCENARIOS_DIR_NAME,
    DriveScenario,
    ScenarioLoadError,
    ScenarioValidationError,
)

logger = logging.getLogger(__name__)


def getScenariosDirectory() -> str:
    """
    Get the scenarios directory path.

    Returns:
        Absolute path to scenarios directory
    """
    moduleDir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(moduleDir, SCENARIOS_DIR_NAME)


def loadScenario(path: str) -> DriveScenario:
    """
    Load a scenario from a JSON file.

    Args:
        path: Path to scenario JSON file

    Returns:
        Loaded DriveScenario

    Raises:
        ScenarioLoadError: If file cannot be loaded or parsed
        ScenarioValidationError: If scenario is invalid
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise ScenarioLoadError(f"Scenario file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise ScenarioLoadError(f"Invalid JSON in scenario file: {e}") from e

    try:
        scenario = DriveScenario.fromDict(data)
    except ScenarioValidationError:
        raise
    except Exception as e:
        raise ScenarioLoadError(f"Failed to parse scenario: {e}") from e

    # Validate scenario
    errors = scenario.validate()
    if errors:
        raise ScenarioValidationError(
            f"Scenario validation failed: {errors}",
            invalidFields=errors
        )

    logger.debug(f"Loaded scenario '{scenario.name}' from {path}")
    return scenario


def saveScenario(scenario: DriveScenario, path: str) -> None:
    """
    Save a scenario to a JSON file.

    Args:
        scenario: DriveScenario to save
        path: Path to save to
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenario.toDict(), f, indent=2)
    logger.debug(f"Saved scenario '{scenario.name}' to {path}")


def listAvailableScenarios() -> list[str]:
    """
    List available scenario files in the scenarios directory.

    Returns:
        List of scenario filenames (without .json extension)
    """
    scenariosDir = getScenariosDirectory()
    if not os.path.exists(scenariosDir):
        return []

    scenarios = []
    for filename in os.listdir(scenariosDir):
        if filename.endswith(".json"):
            scenarios.append(filename[:-5])  # Remove .json

    return sorted(scenarios)


def getBuiltInScenario(name: str) -> DriveScenario:
    """
    Get a built-in scenario by name.

    Args:
        name: Scenario name (e.g., 'city_driving', 'highway_cruise')

    Returns:
        DriveScenario instance

    Raises:
        ScenarioLoadError: If scenario not found
    """
    scenariosDir = getScenariosDirectory()
    path = os.path.join(scenariosDir, f"{name}.json")

    if not os.path.exists(path):
        raise ScenarioLoadError(f"Built-in scenario not found: {name}")

    return loadScenario(path)


def createScenarioFromConfig(config: dict[str, Any]) -> DriveScenario:
    """
    Create a scenario from configuration.

    Args:
        config: Configuration dict, may contain 'simulator.scenarioPath'
                or 'scenarioPath' or inline 'scenario' definition

    Returns:
        DriveScenario instance

    Raises:
        ScenarioLoadError: If scenario cannot be loaded
    """
    # Check for inline scenario definition
    if "scenario" in config:
        return DriveScenario.fromDict(config["scenario"])

    # Check for scenario path in simulator config
    simConfig = config.get("pi", {}).get("simulator", {})
    scenarioPath = simConfig.get("scenarioPath") or config.get("scenarioPath")

    if scenarioPath:
        return loadScenario(scenarioPath)

    # Return default scenario
    return getDefaultScenario()


def ensureScenariosDirectory() -> None:
    """Ensure scenarios directory exists."""
    scenariosDir = getScenariosDirectory()
    if not os.path.exists(scenariosDir):
        os.makedirs(scenariosDir)
        logger.debug(f"Created scenarios directory: {scenariosDir}")


def initializeBuiltInScenarios() -> None:
    """
    Initialize built-in scenario JSON files.

    Creates scenario JSON files if they don't exist.
    """
    ensureScenariosDirectory()
    scenariosDir = getScenariosDirectory()

    scenarios = [
        ("cold_start", getColdStartScenario()),
        ("city_driving", getCityDrivingScenario()),
        ("highway_cruise", getHighwayCruiseScenario()),
        ("full_cycle", getFullCycleScenario()),
    ]

    for name, scenario in scenarios:
        path = os.path.join(scenariosDir, f"{name}.json")
        if not os.path.exists(path):
            saveScenario(scenario, path)
            logger.info(f"Created built-in scenario: {name}")
