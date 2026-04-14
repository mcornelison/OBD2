################################################################################
# File Name: command_types.py
# Purpose/Description: Shared types for shutdown command subpackage (enums, exceptions, dataclasses)
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# 2026-04-14    | Sweep 5       | Extracted from command.py (task 4 split)
# ================================================================================
################################################################################

"""
Shared types for the shutdown command subsystem.

Provides:
- ShutdownState enum
- ShutdownCommandError, ProcessNotFoundError, ShutdownTimeoutError,
  GpioNotAvailableError exceptions
- ShutdownResult dataclass (outcome of a shutdown attempt)
- ShutdownConfig dataclass (tunable parameters)
- Default constants (timeouts, GPIO pin, service name, shutdown reasons)
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


# ================================================================================
# Constants
# ================================================================================

DEFAULT_SHUTDOWN_TIMEOUT = 30  # seconds
DEFAULT_GPIO_PIN = 17  # BCM numbering
DEFAULT_PID_FILE = '/var/run/eclipse-obd2.pid'
DEFAULT_SERVICE_NAME = 'eclipse-obd2'

# Shutdown reasons
SHUTDOWN_REASON_USER_REQUEST = 'user_request'
SHUTDOWN_REASON_GPIO_BUTTON = 'gpio_button'
SHUTDOWN_REASON_LOW_BATTERY = 'low_battery'
SHUTDOWN_REASON_MAINTENANCE = 'maintenance'
SHUTDOWN_REASON_SYSTEM = 'system'


class ShutdownState(Enum):
    """State of the shutdown process."""
    IDLE = 'idle'
    INITIATING = 'initiating'
    WAITING = 'waiting'
    COMPLETED = 'completed'
    TIMEOUT = 'timeout'
    FAILED = 'failed'


# ================================================================================
# Exceptions
# ================================================================================

class ShutdownCommandError(Exception):
    """Base exception for shutdown command errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """
        Initialize shutdown command error.

        Args:
            message: Error message
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ProcessNotFoundError(ShutdownCommandError):
    """Error when target process cannot be found."""
    pass


class ShutdownTimeoutError(ShutdownCommandError):
    """Error when shutdown times out."""
    pass


class GpioNotAvailableError(ShutdownCommandError):
    """Error when GPIO is not available."""
    pass


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class ShutdownResult:
    """Result of a shutdown operation."""
    success: bool
    state: ShutdownState
    reason: str
    startTime: datetime
    endTime: datetime | None = None
    durationSeconds: float = 0.0
    processId: int | None = None
    powerOffRequested: bool = False
    powerOffExecuted: bool = False
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'state': self.state.value,
            'reason': self.reason,
            'startTime': self.startTime.isoformat(),
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'durationSeconds': self.durationSeconds,
            'processId': self.processId,
            'powerOffRequested': self.powerOffRequested,
            'powerOffExecuted': self.powerOffExecuted,
            'errorMessage': self.errorMessage
        }


@dataclass
class ShutdownConfig:
    """Configuration for shutdown command."""
    timeoutSeconds: int = DEFAULT_SHUTDOWN_TIMEOUT
    pidFile: str = DEFAULT_PID_FILE
    serviceName: str = DEFAULT_SERVICE_NAME
    gpioPin: int = DEFAULT_GPIO_PIN
    gpioPullUp: bool = True
    gpioDebounceMs: int = 200
    powerOffEnabled: bool = False
    powerOffDelaySeconds: int = 5
    logFile: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timeoutSeconds': self.timeoutSeconds,
            'pidFile': self.pidFile,
            'serviceName': self.serviceName,
            'gpioPin': self.gpioPin,
            'gpioPullUp': self.gpioPullUp,
            'gpioDebounceMs': self.gpioDebounceMs,
            'powerOffEnabled': self.powerOffEnabled,
            'powerOffDelaySeconds': self.powerOffDelaySeconds,
            'logFile': self.logFile
        }
