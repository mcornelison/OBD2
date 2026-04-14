################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for calibration module
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-014
# ================================================================================
################################################################################
"""
Calibration type definitions.

Contains enums, dataclasses, and constants for calibration functionality.
This module has no project dependencies (only stdlib).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

# =============================================================================
# Enums
# =============================================================================

class CalibrationState(Enum):
    """Calibration mode state."""

    DISABLED = "disabled"
    ENABLED = "enabled"
    SESSION_ACTIVE = "session_active"


# =============================================================================
# Dataclasses
# =============================================================================

@dataclass
class CalibrationSession:
    """
    Represents a calibration session.

    Attributes:
        sessionId: Unique session identifier
        startTime: When the session started
        endTime: When the session ended (None if active)
        notes: Optional notes for this session
        profileId: Optional profile ID associated with session
        readingCount: Number of readings in this session
    """

    sessionId: int
    startTime: datetime
    endTime: datetime | None = None
    notes: str | None = None
    profileId: str | None = None
    readingCount: int = 0

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'sessionId': self.sessionId,
            'startTime': self.startTime.isoformat(),
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'notes': self.notes,
            'profileId': self.profileId,
            'readingCount': self.readingCount,
            'durationSeconds': self.durationSeconds
        }

    @property
    def durationSeconds(self) -> float | None:
        """Get session duration in seconds."""
        if self.endTime is None:
            # Session still active - calculate from now
            return (datetime.now() - self.startTime).total_seconds()
        return (self.endTime - self.startTime).total_seconds()

    @property
    def isActive(self) -> bool:
        """Check if session is still active (not ended)."""
        return self.endTime is None


@dataclass
class CalibrationReading:
    """
    A single calibration reading.

    Attributes:
        parameterName: Name of the OBD-II parameter
        value: Numeric value (may be None for non-numeric)
        unit: Unit of measurement
        timestamp: When the reading was taken
        sessionId: ID of the calibration session
        rawValue: Raw string value for non-numeric data
    """

    parameterName: str
    value: float | None
    unit: str | None
    timestamp: datetime
    sessionId: int
    rawValue: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'value': self.value,
            'unit': self.unit,
            'timestamp': self.timestamp.isoformat(),
            'sessionId': self.sessionId,
            'rawValue': self.rawValue
        }


@dataclass
class CalibrationStats:
    """
    Statistics for calibration manager.

    Attributes:
        totalSessions: Total number of sessions
        activeSessions: Number of currently active sessions
        totalReadings: Total number of readings across all sessions
        state: Current calibration state
        currentSessionId: ID of current session (if any)
    """

    totalSessions: int = 0
    activeSessions: int = 0
    totalReadings: int = 0
    state: CalibrationState = CalibrationState.DISABLED
    currentSessionId: int | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'totalSessions': self.totalSessions,
            'activeSessions': self.activeSessions,
            'totalReadings': self.totalReadings,
            'state': self.state.value,
            'currentSessionId': self.currentSessionId
        }


@dataclass
class CalibrationExportResult:
    """
    Result of a calibration session export operation.

    Attributes:
        success: Whether export completed successfully
        filePath: Path to exported file (if successful)
        recordCount: Number of readings exported
        format: Export format used ('csv' or 'json')
        sessionId: ID of the exported session
        executionTimeMs: Time taken in milliseconds
        errorMessage: Error message (if failed)
    """

    success: bool
    recordCount: int = 0
    filePath: str | None = None
    format: str | None = None
    sessionId: int | None = None
    executionTimeMs: int = 0
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'filePath': self.filePath,
            'recordCount': self.recordCount,
            'format': self.format,
            'sessionId': self.sessionId,
            'executionTimeMs': self.executionTimeMs,
            'errorMessage': self.errorMessage
        }


# =============================================================================
# Comparator Types
# =============================================================================

@dataclass
class ParameterSessionStats:
    """
    Statistics for a single parameter within a single session.

    Attributes:
        parameterName: Name of the OBD-II parameter
        sessionId: ID of the calibration session
        count: Number of readings
        min: Minimum value
        max: Maximum value
        avg: Average value
        stdDev: Standard deviation
    """

    parameterName: str
    sessionId: int
    count: int = 0
    min: float | None = None
    max: float | None = None
    avg: float | None = None
    stdDev: float | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'sessionId': self.sessionId,
            'count': self.count,
            'min': self.min,
            'max': self.max,
            'avg': self.avg,
            'stdDev': self.stdDev,
        }


@dataclass
class SessionComparisonResult:
    """
    Comparison result for a single parameter across multiple sessions.

    Attributes:
        parameterName: Name of the compared parameter
        sessionStats: Dictionary mapping session ID to statistics
        variancePercent: Maximum variance percentage across sessions
        isSignificant: Whether variance exceeds significance threshold (>10%)
        description: Human-readable description of the difference
    """

    parameterName: str
    sessionStats: dict[int, ParameterSessionStats] = field(default_factory=dict)
    variancePercent: float = 0.0
    isSignificant: bool = False
    description: str = ''

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'sessionStats': {
                str(sessionId): stats.toDict()
                for sessionId, stats in self.sessionStats.items()
            },
            'variancePercent': self.variancePercent,
            'isSignificant': self.isSignificant,
            'description': self.description,
        }


@dataclass
class CalibrationSessionComparison:
    """
    Complete comparison result for multiple calibration sessions.

    Attributes:
        sessionIds: List of compared session IDs
        comparisonDate: When the comparison was performed
        parameterResults: Dictionary of parameter name to comparison result
        significantCount: Number of parameters with significant variance
        totalParameters: Total number of parameters compared
        commonParameters: List of parameters common to all sessions
    """

    sessionIds: list[int]
    comparisonDate: datetime
    parameterResults: dict[str, SessionComparisonResult] = field(default_factory=dict)
    significantCount: int = 0
    totalParameters: int = 0
    commonParameters: list[str] = field(default_factory=list)

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'sessionIds': self.sessionIds,
            'comparisonDate': self.comparisonDate.isoformat() if self.comparisonDate else None,
            'parameterResults': {
                name: result.toDict()
                for name, result in self.parameterResults.items()
            },
            'significantCount': self.significantCount,
            'totalParameters': self.totalParameters,
            'commonParameters': self.commonParameters,
        }


@dataclass
class ComparisonExportResult:
    """
    Result of a comparison export operation.

    Attributes:
        success: Whether export completed successfully
        filePath: Path to exported file (if successful)
        format: Export format used ('csv' or 'json')
        sessionIds: IDs of compared sessions
        executionTimeMs: Time taken in milliseconds
        errorMessage: Error message (if failed)
    """

    success: bool
    filePath: str | None = None
    format: str | None = None
    sessionIds: list[int] = field(default_factory=list)
    executionTimeMs: int = 0
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'filePath': self.filePath,
            'format': self.format,
            'sessionIds': self.sessionIds,
            'executionTimeMs': self.executionTimeMs,
            'errorMessage': self.errorMessage,
        }


# =============================================================================
# Constants
# =============================================================================

# Significance threshold for variance detection (10%)
SIGNIFICANCE_THRESHOLD = 10.0

# Schema for calibration data table (separate from realtime_data)
SCHEMA_CALIBRATION_DATA = """
CREATE TABLE IF NOT EXISTS calibration_data (
    -- Primary key
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Session association
    session_id INTEGER NOT NULL,

    -- Timestamp with millisecond precision
    timestamp DATETIME NOT NULL,

    -- Parameter data
    parameter_name TEXT NOT NULL,
    value REAL,
    unit TEXT,

    -- Raw string value for non-numeric data
    raw_value TEXT,

    -- Audit column
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT FK_calibration_data_session FOREIGN KEY (session_id)
        REFERENCES calibration_sessions(session_id)
        ON DELETE CASCADE
);
"""

# Index for efficient session queries
INDEX_CALIBRATION_DATA_SESSION = """
CREATE INDEX IF NOT EXISTS IX_calibration_data_session
    ON calibration_data(session_id);
"""

# Index for timestamp-based queries
INDEX_CALIBRATION_DATA_TIMESTAMP = """
CREATE INDEX IF NOT EXISTS IX_calibration_data_timestamp
    ON calibration_data(timestamp);
"""
