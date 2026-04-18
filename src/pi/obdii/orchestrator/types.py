################################################################################
# File Name: types.py
# Purpose/Description: Shared exceptions, enums, dataclasses, and constants for
#                      the orchestrator package
# Author: Ralph Agent
# Creation Date: 2026-04-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-14    | Ralph Agent  | Sweep 5 Task 2: extracted from orchestrator.py
#               |              | as part of monolith → package refactor (TD-003)
# ================================================================================
################################################################################

"""
Shared types for the orchestrator package.

Contains exception classes, state enums, dataclasses, and module-level
constants used across the orchestrator mixins and core class. These
symbols have zero behavior and zero dependencies on orchestrator state,
so they live here without circular import risk.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

# ================================================================================
# Enums
# ================================================================================

class ShutdownState(Enum):
    """States for shutdown handling."""
    RUNNING = "running"
    SHUTDOWN_REQUESTED = "shutdown_requested"
    FORCE_EXIT = "force_exit"


# ================================================================================
# Dataclasses
# ================================================================================

@dataclass
class HealthCheckStats:
    """Statistics for health check reporting."""

    connectionConnected: bool = False
    connectionStatus: str = "unknown"
    dataRatePerMinute: float = 0.0
    totalReadings: int = 0
    totalErrors: int = 0
    drivesDetected: int = 0
    alertsTriggered: int = 0
    lastHealthCheck: datetime | None = None
    uptimeSeconds: float = 0.0

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'connectionConnected': self.connectionConnected,
            'connectionStatus': self.connectionStatus,
            'dataRatePerMinute': round(self.dataRatePerMinute, 2),
            'totalReadings': self.totalReadings,
            'totalErrors': self.totalErrors,
            'drivesDetected': self.drivesDetected,
            'alertsTriggered': self.alertsTriggered,
            'lastHealthCheck': (
                self.lastHealthCheck.isoformat()
                if self.lastHealthCheck else None
            ),
            'uptimeSeconds': round(self.uptimeSeconds, 1),
        }


# ================================================================================
# Constants
# ================================================================================

# Default component shutdown timeout in seconds
DEFAULT_SHUTDOWN_TIMEOUT = 5.0

# Default health check interval in seconds
DEFAULT_HEALTH_CHECK_INTERVAL = 60.0

# Default data logging rate log interval in seconds (5 minutes)
DEFAULT_DATA_RATE_LOG_INTERVAL = 300.0

# Connection recovery constants
DEFAULT_CONNECTION_CHECK_INTERVAL = 5.0  # Check connection every 5 seconds
DEFAULT_RECONNECT_DELAYS = [1, 2, 4, 8, 16]  # Exponential backoff delays in seconds
DEFAULT_MAX_RECONNECT_ATTEMPTS = 5  # Maximum reconnection attempts

# Exit codes
EXIT_CODE_CLEAN = 0
EXIT_CODE_FORCED = 1
EXIT_CODE_ERROR = 2


# ================================================================================
# Exceptions
# ================================================================================

class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    def __init__(self, message: str, component: str | None = None):
        """
        Initialize orchestrator error.

        Args:
            message: Error description
            component: Name of component that caused the error (optional)
        """
        super().__init__(message)
        self.component = component


class ComponentInitializationError(OrchestratorError):
    """Raised when a component fails to initialize."""
    pass


class ComponentStartError(OrchestratorError):
    """Raised when a component fails to start."""
    pass


class ComponentStopError(OrchestratorError):
    """Raised when a component fails to stop gracefully."""
    pass


__all__ = [
    'ShutdownState',
    'HealthCheckStats',
    'DEFAULT_SHUTDOWN_TIMEOUT',
    'DEFAULT_HEALTH_CHECK_INTERVAL',
    'DEFAULT_DATA_RATE_LOG_INTERVAL',
    'DEFAULT_CONNECTION_CHECK_INTERVAL',
    'DEFAULT_RECONNECT_DELAYS',
    'DEFAULT_MAX_RECONNECT_ATTEMPTS',
    'EXIT_CODE_CLEAN',
    'EXIT_CODE_FORCED',
    'EXIT_CODE_ERROR',
    'OrchestratorError',
    'ComponentInitializationError',
    'ComponentStartError',
    'ComponentStopError',
]
