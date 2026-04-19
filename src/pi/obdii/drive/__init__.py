################################################################################
# File Name: __init__.py
# Purpose/Description: Drive subpackage for drive detection and session tracking
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added exports for types, exceptions, detector, helpers (US-009)
# ================================================================================
################################################################################
"""
Drive Subpackage.

This subpackage contains drive detection components:
- Drive state machine (DriveState, DetectorState enums)
- Drive detector (DriveDetector class)
- Drive session management (DriveSession dataclass)
- Configuration (DetectorConfig, DetectorStats dataclasses)
- Exception classes (DriveDetectorError and subclasses)
- Helper functions (factory and config utilities)

Usage:
    from obd.drive import DriveDetector, DriveState, createDriveDetectorFromConfig

    # Create detector from config
    detector = createDriveDetectorFromConfig(config)
    detector.start()

    # Process values
    detector.processValue('RPM', 2500)
    detector.processValue('SPEED', 65)

    # Check state
    if detector.isDriving():
        session = detector.getCurrentSession()
        print(f"Driving since {session.startTime}")
"""

# Types
# Detector
from .detector import DriveDetector

# Exceptions
from .exceptions import (
    DriveDetectorConfigError,
    DriveDetectorError,
    DriveDetectorStateError,
)

# Helpers
from .helpers import (
    createDetectorWithCallbacks,
    createDriveDetectorFromConfig,
    getDefaultDriveDetectionConfig,
    getDriveDetectionConfig,
    isDriveDetectionEnabled,
    validateDriveDetectionConfig,
)
from .types import (
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
    DRIVE_DETECTION_PARAMETERS,
    MIN_INTER_DRIVE_SECONDS,
    DetectorConfig,
    DetectorState,
    DetectorStats,
    DriveSession,
    DriveState,
)

__all__ = [
    # Types - Enums
    'DriveState',
    'DetectorState',
    # Types - Dataclasses
    'DriveSession',
    'DetectorConfig',
    'DetectorStats',
    # Types - Constants
    'DEFAULT_DRIVE_START_RPM_THRESHOLD',
    'DEFAULT_DRIVE_START_DURATION_SECONDS',
    'DEFAULT_DRIVE_END_RPM_THRESHOLD',
    'DEFAULT_DRIVE_END_DURATION_SECONDS',
    'DRIVE_DETECTION_PARAMETERS',
    'MIN_INTER_DRIVE_SECONDS',
    # Exceptions
    'DriveDetectorError',
    'DriveDetectorConfigError',
    'DriveDetectorStateError',
    # Detector
    'DriveDetector',
    # Helpers
    'createDriveDetectorFromConfig',
    'isDriveDetectionEnabled',
    'getDriveDetectionConfig',
    'getDefaultDriveDetectionConfig',
    'validateDriveDetectionConfig',
    'createDetectorWithCallbacks',
]
