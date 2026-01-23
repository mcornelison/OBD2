################################################################################
# File Name: types.py
# Purpose/Description: Type definitions for drive detection module
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-009)
# ================================================================================
################################################################################
"""
Type definitions for drive detection.

Contains enums and dataclasses used by drive detection components:
- DriveState: State machine states for drive detection
- DetectorState: Operational states of the detector
- DriveSession: Information about a drive session
- DetectorConfig: Configuration for drive detection
- DetectorStats: Statistics about detector operation

These types have no dependencies on other project modules.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


# ================================================================================
# Constants
# ================================================================================

# Default thresholds (from config analysis section)
DEFAULT_DRIVE_START_RPM_THRESHOLD = 500
DEFAULT_DRIVE_START_DURATION_SECONDS = 10
DEFAULT_DRIVE_END_RPM_THRESHOLD = 0
DEFAULT_DRIVE_END_DURATION_SECONDS = 60

# Parameters monitored for drive detection
DRIVE_DETECTION_PARAMETERS = ['RPM', 'SPEED']

# Minimum time between drive end and new drive start (debounce)
MIN_INTER_DRIVE_SECONDS = 5


# ================================================================================
# Enums
# ================================================================================

class DriveState(Enum):
    """
    State of the drive session.

    States:
        UNKNOWN: Initial state, no data yet
        STOPPED: Engine off, vehicle stationary
        STARTING: RPM above threshold, waiting for duration
        RUNNING: Drive confirmed in progress
        STOPPING: RPM at/below threshold, waiting for duration
        ENDED: Drive ended (transitions to STOPPED)
    """
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ENDED = "ended"


class DetectorState(Enum):
    """
    State of the detector itself.

    States:
        IDLE: Detector not monitoring
        MONITORING: Detector actively processing values
        ERROR: Detector encountered an error
    """
    IDLE = "idle"
    MONITORING = "monitoring"
    ERROR = "error"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class DriveSession:
    """
    Information about a drive session.

    Attributes:
        startTime: When the drive started
        endTime: When the drive ended (None if ongoing)
        profileId: Active profile during the drive
        peakRpm: Maximum RPM recorded during drive
        peakSpeed: Maximum speed recorded during drive
        duration: Duration of the drive in seconds
        analysisTriggered: Whether post-drive analysis was triggered
    """
    startTime: datetime
    endTime: Optional[datetime] = None
    profileId: Optional[str] = None
    peakRpm: float = 0.0
    peakSpeed: float = 0.0
    duration: float = 0.0
    analysisTriggered: bool = False

    def isActive(self) -> bool:
        """Check if this drive session is still active."""
        return self.endTime is None

    def getDuration(self) -> float:
        """Get duration in seconds."""
        if self.endTime:
            return (self.endTime - self.startTime).total_seconds()
        return (datetime.now() - self.startTime).total_seconds()

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'startTime': self.startTime.isoformat() if self.startTime else None,
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'profileId': self.profileId,
            'peakRpm': self.peakRpm,
            'peakSpeed': self.peakSpeed,
            'duration': self.getDuration(),
            'analysisTriggered': self.analysisTriggered,
        }


@dataclass
class DetectorConfig:
    """
    Configuration for drive detection.

    Attributes:
        driveStartRpmThreshold: RPM threshold to consider engine running
        driveStartDurationSeconds: Duration RPM must exceed threshold
        driveEndRpmThreshold: RPM threshold to consider engine off
        driveEndDurationSeconds: Duration RPM must be at/below threshold
        triggerAnalysisAfterDrive: Whether to trigger analysis after drive
        profileId: Active profile ID
    """
    driveStartRpmThreshold: float = DEFAULT_DRIVE_START_RPM_THRESHOLD
    driveStartDurationSeconds: float = DEFAULT_DRIVE_START_DURATION_SECONDS
    driveEndRpmThreshold: float = DEFAULT_DRIVE_END_RPM_THRESHOLD
    driveEndDurationSeconds: float = DEFAULT_DRIVE_END_DURATION_SECONDS
    triggerAnalysisAfterDrive: bool = True
    profileId: Optional[str] = None

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'driveStartRpmThreshold': self.driveStartRpmThreshold,
            'driveStartDurationSeconds': self.driveStartDurationSeconds,
            'driveEndRpmThreshold': self.driveEndRpmThreshold,
            'driveEndDurationSeconds': self.driveEndDurationSeconds,
            'triggerAnalysisAfterDrive': self.triggerAnalysisAfterDrive,
            'profileId': self.profileId,
        }


@dataclass
class DetectorStats:
    """
    Statistics about detector operation.

    Attributes:
        valuesProcessed: Total number of values processed
        drivesDetected: Total number of drives detected
        analysesTriggered: Number of analyses triggered
        lastDriveStart: Time of most recent drive start
        lastDriveEnd: Time of most recent drive end
        currentDriveDuration: Duration of current drive (if active)
    """
    valuesProcessed: int = 0
    drivesDetected: int = 0
    analysesTriggered: int = 0
    lastDriveStart: Optional[datetime] = None
    lastDriveEnd: Optional[datetime] = None
    currentDriveDuration: float = 0.0

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            'valuesProcessed': self.valuesProcessed,
            'drivesDetected': self.drivesDetected,
            'analysesTriggered': self.analysesTriggered,
            'lastDriveStart': self.lastDriveStart.isoformat() if self.lastDriveStart else None,
            'lastDriveEnd': self.lastDriveEnd.isoformat() if self.lastDriveEnd else None,
            'currentDriveDuration': self.currentDriveDuration,
        }
