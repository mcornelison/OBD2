################################################################################
# File Name: cli_types.py
# Purpose/Description: Shared types and constants for the simulator CLI
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-043
# 2026-04-14    | Sweep 5       | Extracted from simulator_cli.py (task 4 split)
# ================================================================================
################################################################################

"""
Shared types and constants for the simulator CLI.

Provides:
- Command key constants + VALID_COMMANDS set
- FAILURE_TYPE_SHORTCUTS mapping for the failure menu
- CliState enum
- CommandType enum
- CommandResult dataclass
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

# ================================================================================
# Constants
# ================================================================================

# Command keys
COMMAND_PAUSE = 'p'
COMMAND_FAILURE = 'f'
COMMAND_CLEAR = 'c'
COMMAND_STATUS = 's'
COMMAND_QUIT = 'q'
COMMAND_HELP = 'h'

# Valid commands
VALID_COMMANDS = {
    COMMAND_PAUSE,
    COMMAND_FAILURE,
    COMMAND_CLEAR,
    COMMAND_STATUS,
    COMMAND_QUIT,
    COMMAND_HELP,
}

# Failure type shortcuts for the failure injection menu
FAILURE_TYPE_SHORTCUTS = {
    '1': 'connectionDrop',
    '2': 'sensorFailure',
    '3': 'intermittentSensor',
    '4': 'outOfRange',
    '5': 'dtcCodes',
}


# ================================================================================
# Enums
# ================================================================================

class CliState(Enum):
    """State of the CLI handler."""

    STOPPED = "stopped"
    RUNNING = "running"
    AWAITING_FAILURE_TYPE = "awaiting_failure_type"
    PAUSED = "paused"


class CommandType(Enum):
    """Type of CLI command."""

    PAUSE = "pause"
    RESUME = "resume"
    INJECT_FAILURE = "inject_failure"
    CLEAR_FAILURES = "clear_failures"
    STATUS = "status"
    QUIT = "quit"
    HELP = "help"
    UNKNOWN = "unknown"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class CommandResult:
    """
    Result of executing a CLI command.

    Attributes:
        command: The command type that was executed
        success: Whether the command executed successfully
        message: Human-readable result message
        details: Additional details about the result
    """

    command: CommandType
    success: bool
    message: str
    details: dict[str, Any] = None

    def __post_init__(self) -> None:
        """Initialize details if not provided."""
        if self.details is None:
            self.details = {}

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "command": self.command.value,
            "success": self.success,
            "message": self.message,
            "details": self.details,
        }
