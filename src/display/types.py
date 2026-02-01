################################################################################
# File Name: types.py
# Purpose/Description: Display-related types, enums, and dataclasses
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-004
# ================================================================================
################################################################################
"""
Display types module.

Provides type definitions for display management:
- DisplayMode enum for display output modes
- StatusInfo dataclass for status screen information
- AlertInfo dataclass for alert information
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DisplayMode(Enum):
    """Display mode enumeration."""

    HEADLESS = "headless"
    MINIMAL = "minimal"
    DEVELOPER = "developer"

    @classmethod
    def fromString(cls, value: str) -> 'DisplayMode':
        """
        Convert string to DisplayMode enum.

        Args:
            value: String value of display mode

        Returns:
            DisplayMode enum value

        Raises:
            ValueError: If value is not a valid display mode
        """
        valueLower = value.lower().strip()
        for mode in cls:
            if mode.value == valueLower:
                return mode
        validModes = [m.value for m in cls]
        raise ValueError(
            f"Invalid display mode: '{value}'. Must be one of: {', '.join(validModes)}"
        )

    @classmethod
    def isValid(cls, value: str) -> bool:
        """
        Check if a string is a valid display mode.

        Args:
            value: String to check

        Returns:
            True if valid display mode, False otherwise
        """
        try:
            cls.fromString(value)
            return True
        except ValueError:
            return False


@dataclass
class StatusInfo:
    """Information to display on status screen."""

    connectionStatus: str = "Disconnected"
    databaseStatus: str = "Unknown"
    currentRpm: float | None = None
    coolantTemp: float | None = None
    activeAlerts: list[str] = field(default_factory=list)
    profileName: str = "daily"
    timestamp: datetime | None = None
    powerSource: str = "unknown"

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'connectionStatus': self.connectionStatus,
            'databaseStatus': self.databaseStatus,
            'currentRpm': self.currentRpm,
            'coolantTemp': self.coolantTemp,
            'activeAlerts': self.activeAlerts,
            'profileName': self.profileName,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'powerSource': self.powerSource
        }


@dataclass
class AlertInfo:
    """Alert information for display."""

    message: str
    priority: int = 3  # 1-5, 1 is highest
    timestamp: datetime | None = None
    acknowledged: bool = False

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'message': self.message,
            'priority': self.priority,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'acknowledged': self.acknowledged
        }
