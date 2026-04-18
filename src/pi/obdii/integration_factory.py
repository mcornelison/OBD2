################################################################################
# File Name: integration_factory.py
# Purpose/Description: Factory/helper functions for building simulator integration components
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
Factory/helper functions for simulator integration.

Provides module-level factories that pick a real or simulated connection
based on config, and a helper to probe whether simulation mode is active.
The SimulatorIntegration class itself lives in simulator_integration.py.
"""

import logging
from typing import Any

from .config import getSimulatorConfig, isSimulatorEnabled
from .obd_connection import ObdConnection
from .obd_connection import createConnectionFromConfig as createRealConnection
from .simulator import SimulatedObdConnection, loadProfile

logger = logging.getLogger(__name__)


def createIntegratedConnection(
    config: dict[str, Any],
    database: Any | None = None,
    simulateFlag: bool = False
) -> ObdConnection | SimulatedObdConnection:
    """
    Create an OBD connection based on configuration and simulation flag.

    This is the primary factory function for creating connections. When simulation
    mode is enabled (either via config or --simulate flag), returns a
    SimulatedObdConnection. Otherwise returns a real ObdConnection.

    Args:
        config: Application configuration dictionary
        database: Optional ObdDatabase instance for logging
        simulateFlag: True if --simulate CLI flag was passed

    Returns:
        ObdConnection or SimulatedObdConnection based on simulation mode

    Example:
        # In main.py
        conn = createIntegratedConnection(config, db, args.simulate)
        conn.connect()

        # Works the same regardless of connection type
        response = conn.obd.query("RPM")
        print(f"RPM: {response.value}")
    """
    # Check if simulation mode is enabled
    if isSimulatorEnabled(config, simulateFlag):
        logger.info("Creating SimulatedObdConnection (simulation mode enabled)")
        return _createSimulatedConnection(config, database)
    else:
        logger.info("Creating real ObdConnection")
        return createRealConnection(config, database)


def _createSimulatedConnection(
    config: dict[str, Any],
    database: Any | None = None
) -> SimulatedObdConnection:
    """
    Create a SimulatedObdConnection from configuration.

    Loads vehicle profile and configures the simulator based on config settings.

    Args:
        config: Application configuration dictionary
        database: Optional database instance (for compatibility)

    Returns:
        Configured SimulatedObdConnection instance
    """
    simConfig = getSimulatorConfig(config)

    # Load vehicle profile if specified
    profile = None
    profilePath = simConfig.get('profilePath', '')
    if profilePath:
        try:
            profile = loadProfile(profilePath)
            logger.info(f"Loaded vehicle profile: {profilePath}")
        except Exception as e:
            logger.warning(f"Failed to load vehicle profile '{profilePath}': {e}")
            logger.info("Using default vehicle profile")

    # Create connection with configuration
    connection = SimulatedObdConnection(
        profile=profile,
        connectionDelaySeconds=simConfig.get('connectionDelaySeconds', 2.0),
        config=config,
        database=database
    )

    return connection


def isSimulationModeActive(config: dict[str, Any], simulateFlag: bool = False) -> bool:
    """
    Check if simulation mode should be active.

    Args:
        config: Configuration dictionary
        simulateFlag: True if --simulate CLI flag was passed

    Returns:
        True if simulation mode should be used
    """
    return isSimulatorEnabled(config, simulateFlag)
