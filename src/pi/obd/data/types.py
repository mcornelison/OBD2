################################################################################
# File Name: types.py
# Purpose/Description: Data types and dataclasses for OBD-II data logging
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-007 (data module refactor)
# ================================================================================
################################################################################
"""
Data types and dataclasses for OBD-II data logging.

This module contains type definitions with no external dependencies:
- LoggingState: Enum for logging states
- LoggedReading: Dataclass for logged OBD-II readings
- LoggingStats: Dataclass for logging session statistics

Usage:
    from src.obd.data.types import LoggingState, LoggedReading, LoggingStats

    # Create a reading
    reading = LoggedReading(
        parameterName='RPM',
        value=3500.0,
        timestamp=datetime.now(),
        unit='rpm'
    )

    # Check logging state
    if state == LoggingState.RUNNING:
        process_data()
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# ================================================================================
# Enums
# ================================================================================

class LoggingState(Enum):
    """
    Logging state enumeration.

    States:
        STOPPED: Logger is not running
        STARTING: Logger is initializing
        RUNNING: Logger is actively collecting data
        STOPPING: Logger is shutting down gracefully
        ERROR: Logger encountered an unrecoverable error
    """
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'
    ERROR = 'error'


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class LoggedReading:
    """
    Represents a logged OBD-II parameter reading.

    Attributes:
        parameterName: Name of the OBD-II parameter (e.g., 'RPM', 'COOLANT_TEMP')
        value: Numeric value of the reading
        timestamp: When the reading was taken
        unit: Unit of measurement (e.g., 'rpm', 'degC')
        profileId: Associated profile ID for data grouping

    Example:
        reading = LoggedReading(
            parameterName='RPM',
            value=3500.0,
            timestamp=datetime.now(),
            unit='rpm',
            profileId='daily'
        )
        print(reading.toDict())
    """
    parameterName: str
    value: float
    timestamp: datetime
    unit: str | None = None
    profileId: str | None = None

    def toDict(self) -> dict[str, Any]:
        """
        Convert reading to dictionary for serialization.

        Returns:
            Dictionary with all reading fields, timestamp as ISO string
        """
        return {
            'parameterName': self.parameterName,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'profileId': self.profileId
        }


@dataclass
class LoggingStats:
    """
    Statistics for realtime logging session.

    Tracks comprehensive metrics about a logging session including
    timing, counts, and per-parameter breakdowns.

    Attributes:
        startTime: When logging started
        endTime: When logging stopped
        totalCycles: Number of complete polling cycles
        totalReadings: Total successful readings
        totalLogged: Total readings logged to database
        totalErrors: Total errors encountered
        parametersLogged: Count per parameter name
        errorsByParameter: Errors by parameter name
        lastCycleTimeMs: Duration of last polling cycle in ms
        averageCycleTimeMs: Average cycle duration in ms

    Example:
        stats = LoggingStats()
        stats.startTime = datetime.now()
        stats.totalCycles = 100
        stats.totalReadings = 500
        print(stats.toDict())
    """
    startTime: datetime | None = None
    endTime: datetime | None = None
    totalCycles: int = 0
    totalReadings: int = 0
    totalLogged: int = 0
    totalErrors: int = 0
    parametersLogged: dict[str, int] = field(default_factory=dict)
    errorsByParameter: dict[str, int] = field(default_factory=dict)
    lastCycleTimeMs: float = 0.0
    averageCycleTimeMs: float = 0.0

    def toDict(self) -> dict[str, Any]:
        """
        Convert stats to dictionary for serialization.

        Returns:
            Dictionary with all stats fields, timestamps as ISO strings
        """
        return {
            'startTime': self.startTime.isoformat() if self.startTime else None,
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'totalCycles': self.totalCycles,
            'totalReadings': self.totalReadings,
            'totalLogged': self.totalLogged,
            'totalErrors': self.totalErrors,
            'parametersLogged': dict(self.parametersLogged),
            'errorsByParameter': dict(self.errorsByParameter),
            'lastCycleTimeMs': self.lastCycleTimeMs,
            'averageCycleTimeMs': self.averageCycleTimeMs
        }
