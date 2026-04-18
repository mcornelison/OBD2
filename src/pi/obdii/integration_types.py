################################################################################
# File Name: integration_types.py
# Purpose/Description: Shared types for simulator integration (enums, configs, stats, exceptions)
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
Shared types for the simulator integration module.

Provides:
- IntegrationState enum
- IntegrationConfig dataclass (tunable settings)
- IntegrationStats dataclass (runtime counters)
- SimulatorIntegrationError + subclasses
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .config import getSimulatorConfig, isSimulatorEnabled

# ================================================================================
# Enums
# ================================================================================

class IntegrationState(Enum):
    """State of the simulator integration."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class IntegrationConfig:
    """
    Configuration for simulator integration.

    Attributes:
        enabled: Whether simulation is enabled
        profilePath: Path to vehicle profile JSON
        scenarioPath: Path to drive scenario JSON (optional)
        connectionDelaySeconds: Simulated connection delay
        updateIntervalMs: Simulator update interval
        autoStartScenario: Auto-start scenario on connection
        failureConfig: Failure injection configuration
    """
    enabled: bool = False
    profilePath: str = ""
    scenarioPath: str = ""
    connectionDelaySeconds: float = 2.0
    updateIntervalMs: int = 100
    autoStartScenario: bool = False
    failureConfig: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def fromConfig(
        cls,
        config: dict[str, Any],
        simulateFlag: bool = False
    ) -> "IntegrationConfig":
        """
        Create IntegrationConfig from application config.

        Args:
            config: Application configuration dictionary
            simulateFlag: True if --simulate CLI flag was passed

        Returns:
            IntegrationConfig instance
        """
        simConfig = getSimulatorConfig(config)

        return cls(
            enabled=isSimulatorEnabled(config, simulateFlag),
            profilePath=simConfig.get('profilePath', ''),
            scenarioPath=simConfig.get('scenarioPath', ''),
            connectionDelaySeconds=simConfig.get('connectionDelaySeconds', 2.0),
            updateIntervalMs=simConfig.get('updateIntervalMs', 100),
            autoStartScenario=simConfig.get('autoStartScenario', False),
            failureConfig=simConfig.get('failures', {}),
        )


@dataclass
class IntegrationStats:
    """
    Statistics for simulator integration.

    Attributes:
        startTime: When integration started
        connectionTime: When connected
        updateCount: Number of simulator updates
        readingsGenerated: Number of simulated readings
        alertsTriggered: Number of alerts triggered
        drivesDetected: Number of drives detected
        scenariosRun: Number of scenarios executed
    """
    startTime: datetime | None = None
    connectionTime: datetime | None = None
    updateCount: int = 0
    readingsGenerated: int = 0
    alertsTriggered: int = 0
    drivesDetected: int = 0
    scenariosRun: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'startTime': self.startTime.isoformat() if self.startTime else None,
            'connectionTime': self.connectionTime.isoformat() if self.connectionTime else None,
            'updateCount': self.updateCount,
            'readingsGenerated': self.readingsGenerated,
            'alertsTriggered': self.alertsTriggered,
            'drivesDetected': self.drivesDetected,
            'scenariosRun': self.scenariosRun,
        }


# ================================================================================
# Exceptions
# ================================================================================

class SimulatorIntegrationError(Exception):
    """Base exception for simulator integration errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SimulatorConfigurationError(SimulatorIntegrationError):
    """Error in simulator configuration."""
    pass


class SimulatorConnectionError(SimulatorIntegrationError):
    """Error connecting to simulator."""
    pass
