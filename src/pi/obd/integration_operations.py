################################################################################
# File Name: integration_operations.py
# Purpose/Description: Operation helpers for SimulatorIntegration (scenarios, failures, value feed)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-039
# 2026-04-14    | Sweep 5       | Extracted from simulator_integration.py (task 4 split)
# ================================================================================
################################################################################

"""
Operation helpers for SimulatorIntegration.

Module-level functions that implement scenario-management, failure-injection,
and value-feed flows. The SimulatorIntegration class keeps the state; these
helpers do the stateless work.
"""

import logging
from typing import Any

from .simulator import (
    DriveScenarioRunner,
    FailureInjector,
    FailureType,
    SimulatedObdConnection,
    loadScenario,
)

logger = logging.getLogger(__name__)


# Key parameters for drive detection and alerts
CURRENT_VALUE_PARAM_NAMES = [
    'RPM', 'SPEED', 'COOLANT_TEMP', 'THROTTLE_POS', 'ENGINE_LOAD',
    'MAF', 'INTAKE_TEMP', 'OIL_TEMP', 'INTAKE_PRESSURE',
    'CONTROL_MODULE_VOLTAGE', 'FUEL_LEVEL',
]


# ================================================================================
# Value Feed Helpers
# ================================================================================

def getCurrentValues(
    connection: SimulatedObdConnection | None,
) -> dict[str, float]:
    """
    Get current simulated sensor values from a connection.

    Args:
        connection: Simulated OBD connection (or None)

    Returns:
        Dictionary of parameter names to values (empty if no connection)
    """
    if not connection:
        return {}

    simulator = connection.simulator
    values: dict[str, float] = {}

    for paramName in CURRENT_VALUE_PARAM_NAMES:
        value = simulator.getValue(paramName)
        if value is not None:
            values[paramName] = value

    return values


def updateDisplay(displayManager: Any | None, values: dict[str, float]) -> None:
    """
    Update display with current simulated values.

    Args:
        displayManager: DisplayManager instance (or None)
        values: Dictionary of parameter names to values
    """
    if not displayManager:
        return

    try:
        # Build status info
        statusDetails = {
            'rpm': values.get('RPM', 0),
            'coolantTemp': values.get('COOLANT_TEMP', 0),
            'speed': values.get('SPEED', 0),
            'throttle': values.get('THROTTLE_POS', 0),
        }

        # Check for SIM indicator in developer mode
        if hasattr(displayManager, 'showStatus'):
            # Add SIM indicator to status
            displayManager.showStatus(
                "SIMULATION",
                details=statusDetails
            )
    except Exception as e:
        logger.debug(f"Display update error: {e}")


# ================================================================================
# Scenario Helpers
# ================================================================================

def loadBuiltInScenario(scenarioName: str) -> Any | None:
    """
    Load a built-in drive scenario by name.

    Args:
        scenarioName: Name of built-in scenario (e.g., 'city_driving')

    Returns:
        DriveScenario instance or None on failure
    """
    try:
        from .simulator import getBuiltInScenario
        return getBuiltInScenario(scenarioName)
    except Exception as e:
        logger.error(f"Failed to load scenario '{scenarioName}': {e}")
        return None


def loadScenarioFromPath(scenarioPath: str) -> Any | None:
    """
    Load a drive scenario from a JSON file.

    Args:
        scenarioPath: Path to scenario JSON file

    Returns:
        DriveScenario instance or None on failure
    """
    try:
        return loadScenario(scenarioPath)
    except Exception as e:
        logger.error(f"Failed to load scenario from '{scenarioPath}': {e}")
        return None


def createScenarioRunner(
    scenario: Any,
    connection: SimulatedObdConnection,
    onScenarioComplete: Any,
) -> DriveScenarioRunner:
    """
    Build and start a DriveScenarioRunner for the given scenario.

    Args:
        scenario: DriveScenario to run
        connection: SimulatedObdConnection providing the simulator
        onScenarioComplete: Callback fired when the scenario completes

    Returns:
        Started DriveScenarioRunner
    """
    runner = DriveScenarioRunner(
        scenario=scenario,
        simulator=connection.simulator,
    )
    runner.registerCallbacks(
        onPhaseStart=lambda phase: logger.info(f"Scenario phase: {phase.name}"),
        onScenarioComplete=onScenarioComplete,
    )
    runner.start()
    return runner


def isScenarioRunnerActive(runner: DriveScenarioRunner | None) -> bool:
    """
    Check whether a scenario runner is currently in the RUNNING state.

    Args:
        runner: DriveScenarioRunner instance (or None)

    Returns:
        True if the runner exists and is running
    """
    if runner is None:
        return False
    from .simulator import ScenarioState
    return runner.getState() == ScenarioState.RUNNING


# ================================================================================
# Failure Injection Helpers
# ================================================================================

def injectFailureIntoInjector(
    injector: FailureInjector | None,
    failureType: FailureType,
    **config: Any,
) -> bool:
    """
    Inject a failure into the failure injector.

    Args:
        injector: FailureInjector instance (or None)
        failureType: Type of failure to inject
        **config: Failure-specific configuration

    Returns:
        True if failure was injected
    """
    if not injector:
        logger.warning("No failure injector configured")
        return False

    from .simulator import FailureConfig
    failureConfig = FailureConfig(**config)
    injector.injectFailure(failureType, failureConfig)
    logger.info(f"Injected failure: {failureType.value}")
    return True


def clearFailureInInjector(
    injector: FailureInjector | None,
    failureType: FailureType,
) -> bool:
    """
    Clear a specific failure.

    Args:
        injector: FailureInjector instance (or None)
        failureType: Type of failure to clear

    Returns:
        True if failure was cleared
    """
    if not injector:
        return False

    injector.clearFailure(failureType)
    logger.info(f"Cleared failure: {failureType.value}")
    return True


def scheduleFailureInInjector(
    injector: FailureInjector | None,
    failureType: FailureType,
    startSeconds: float,
    durationSeconds: float,
    **config: Any,
) -> bool:
    """
    Schedule a failure to occur after a delay.

    Args:
        injector: FailureInjector instance (or None)
        failureType: Type of failure
        startSeconds: Seconds until failure starts
        durationSeconds: How long failure lasts
        **config: Failure-specific configuration

    Returns:
        True if scheduled successfully
    """
    if not injector:
        return False

    from .simulator import FailureConfig
    failureConfig = FailureConfig(**config)
    injector.scheduleFailure(
        failureType, failureConfig, startSeconds, durationSeconds
    )
    logger.info(
        f"Scheduled failure: {failureType.value} in {startSeconds}s "
        f"for {durationSeconds}s"
    )
    return True
