################################################################################
# File Name: drive_detector.py
# Purpose/Description: Drive start/end detection for triggering post-drive analysis
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-015
# 2026-01-22    | Ralph Agent  | Refactored to use drive subpackage (US-009)
# ================================================================================
################################################################################

"""
Drive start/end detection for the Eclipse OBD-II Performance Monitoring System.

This module re-exports from the obd.drive subpackage for backward compatibility.
New code should import directly from obd.drive:

    from obd.drive import DriveDetector, DriveState

Legacy imports continue to work:

    from obd.drive_detector import DriveDetector, DriveState

Provides:
- Detection of when the car is running vs idle
- Configurable thresholds for drive start/end detection
- Integration with StatisticsEngine for post-drive analysis triggers
- Drive session tracking and logging

Usage:
    from obd.drive_detector import DriveDetector, DriveState

    # Create detector with config and statistics engine
    detector = DriveDetector(config, statisticsEngine, database)

    # Register callbacks for drive events
    detector.registerCallbacks(
        onDriveStart=lambda ds: print(f"Drive started: {ds}"),
        onDriveEnd=lambda ds: print(f"Drive ended: {ds}")
    )

    # In data acquisition loop, feed values to detector
    detector.processValue('RPM', 2500)
    detector.processValue('SPEED', 45)
"""

# Re-export all public symbols from drive subpackage for backward compatibility
from obd.drive import (
    # Types - Enums
    DriveState,
    DetectorState,
    # Types - Dataclasses
    DriveSession,
    DetectorConfig,
    DetectorStats,
    # Types - Constants
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DRIVE_DETECTION_PARAMETERS,
    MIN_INTER_DRIVE_SECONDS,
    # Exceptions
    DriveDetectorError,
    DriveDetectorConfigError,
    DriveDetectorStateError,
    # Detector
    DriveDetector,
    # Helpers
    createDriveDetectorFromConfig,
    isDriveDetectionEnabled,
    getDriveDetectionConfig,
    getDefaultDriveDetectionConfig,
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
]
