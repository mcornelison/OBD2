################################################################################
# File Name: helpers.py
# Purpose/Description: Helper functions for drive detection module
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
Helper functions for drive detection.

Provides factory functions and configuration utilities:
- createDriveDetectorFromConfig: Factory function to create DriveDetector
- isDriveDetectionEnabled: Check if drive detection is enabled
- getDriveDetectionConfig: Extract drive detection config values
- getDefaultDriveDetectionConfig: Get default configuration values

These functions simplify the creation and configuration of DriveDetector instances.
"""

from typing import Any

from .detector import DriveDetector
from .types import (
    DEFAULT_DRIVE_END_DURATION_SECONDS,
    DEFAULT_DRIVE_END_RPM_THRESHOLD,
    DEFAULT_DRIVE_START_DURATION_SECONDS,
    DEFAULT_DRIVE_START_RPM_THRESHOLD,
)


def createDriveDetectorFromConfig(
    config: dict[str, Any],
    statisticsEngine: Any | None = None,
    database: Any | None = None
) -> DriveDetector:
    """
    Create a DriveDetector from configuration.

    Args:
        config: Configuration dictionary
        statisticsEngine: StatisticsEngine instance (optional)
        database: ObdDatabase instance (optional)

    Returns:
        Configured DriveDetector instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        engine = createStatisticsEngineFromConfig(db, config)
        detector = createDriveDetectorFromConfig(config, engine, db)
    """
    return DriveDetector(config, statisticsEngine, database)


def isDriveDetectionEnabled(config: dict[str, Any]) -> bool:
    """
    Check if drive detection is enabled in config.

    The drive detection feature is controlled by the 'triggerAfterDrive'
    setting in the analysis configuration section.

    Args:
        config: Configuration dictionary

    Returns:
        True if drive detection/analysis trigger is enabled

    Example:
        if isDriveDetectionEnabled(config):
            detector = createDriveDetectorFromConfig(config)
            detector.start()
    """
    return config.get('analysis', {}).get('triggerAfterDrive', True)


def getDriveDetectionConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Extract drive detection configuration from config.

    Returns a dictionary containing all drive detection settings
    with defaults applied for missing values.

    Args:
        config: Configuration dictionary

    Returns:
        Dictionary with drive detection settings:
        - driveStartRpmThreshold: RPM to trigger drive start
        - driveStartDurationSeconds: Duration to confirm drive start
        - driveEndRpmThreshold: RPM to trigger drive end
        - driveEndDurationSeconds: Duration to confirm drive end
        - triggerAfterDrive: Whether to trigger analysis after drive

    Example:
        detectionConfig = getDriveDetectionConfig(config)
        print(f"Start threshold: {detectionConfig['driveStartRpmThreshold']} RPM")
    """
    analysisConfig = config.get('analysis', {})
    return {
        'driveStartRpmThreshold': analysisConfig.get(
            'driveStartRpmThreshold',
            DEFAULT_DRIVE_START_RPM_THRESHOLD
        ),
        'driveStartDurationSeconds': analysisConfig.get(
            'driveStartDurationSeconds',
            DEFAULT_DRIVE_START_DURATION_SECONDS
        ),
        'driveEndRpmThreshold': analysisConfig.get(
            'driveEndRpmThreshold',
            DEFAULT_DRIVE_END_RPM_THRESHOLD
        ),
        'driveEndDurationSeconds': analysisConfig.get(
            'driveEndDurationSeconds',
            DEFAULT_DRIVE_END_DURATION_SECONDS
        ),
        'triggerAfterDrive': analysisConfig.get('triggerAfterDrive', True),
    }


def getDefaultDriveDetectionConfig() -> dict[str, float]:
    """
    Get default drive detection configuration values.

    Returns a dictionary with the default threshold values used
    when no configuration is provided.

    Returns:
        Dictionary with default thresholds:
        - driveStartRpmThreshold: 500 RPM
        - driveStartDurationSeconds: 10 seconds
        - driveEndRpmThreshold: 0 RPM
        - driveEndDurationSeconds: 60 seconds

    Example:
        defaults = getDefaultDriveDetectionConfig()
        print(f"Default start threshold: {defaults['driveStartRpmThreshold']} RPM")
    """
    return {
        'driveStartRpmThreshold': DEFAULT_DRIVE_START_RPM_THRESHOLD,
        'driveStartDurationSeconds': DEFAULT_DRIVE_START_DURATION_SECONDS,
        'driveEndRpmThreshold': DEFAULT_DRIVE_END_RPM_THRESHOLD,
        'driveEndDurationSeconds': DEFAULT_DRIVE_END_DURATION_SECONDS,
    }


def validateDriveDetectionConfig(config: dict[str, Any]) -> bool:
    """
    Validate drive detection configuration values.

    Checks that threshold values are within acceptable ranges.

    Args:
        config: Configuration dictionary

    Returns:
        True if configuration is valid

    Raises:
        ValueError: If configuration values are invalid

    Example:
        if validateDriveDetectionConfig(config):
            detector = createDriveDetectorFromConfig(config)
    """
    detectionConfig = getDriveDetectionConfig(config)

    # Validate RPM thresholds
    if detectionConfig['driveStartRpmThreshold'] < 0:
        raise ValueError("driveStartRpmThreshold must be non-negative")

    if detectionConfig['driveEndRpmThreshold'] < 0:
        raise ValueError("driveEndRpmThreshold must be non-negative")

    # Validate duration values
    if detectionConfig['driveStartDurationSeconds'] <= 0:
        raise ValueError("driveStartDurationSeconds must be positive")

    if detectionConfig['driveEndDurationSeconds'] <= 0:
        raise ValueError("driveEndDurationSeconds must be positive")

    # Start threshold should typically be greater than end threshold
    if detectionConfig['driveStartRpmThreshold'] < detectionConfig['driveEndRpmThreshold']:
        raise ValueError(
            "driveStartRpmThreshold should be greater than driveEndRpmThreshold"
        )

    return True


def createDetectorWithCallbacks(
    config: dict[str, Any],
    onDriveStart: Any | None = None,
    onDriveEnd: Any | None = None,
    onStateChange: Any | None = None,
    statisticsEngine: Any | None = None,
    database: Any | None = None
) -> DriveDetector:
    """
    Create a DriveDetector with callbacks pre-registered.

    Convenience function that creates a detector and registers
    callbacks in a single call.

    Args:
        config: Configuration dictionary
        onDriveStart: Callback for drive start events
        onDriveEnd: Callback for drive end events
        onStateChange: Callback for state change events
        statisticsEngine: StatisticsEngine instance (optional)
        database: ObdDatabase instance (optional)

    Returns:
        Configured DriveDetector with callbacks registered

    Example:
        detector = createDetectorWithCallbacks(
            config,
            onDriveStart=lambda s: print(f"Started: {s.startTime}"),
            onDriveEnd=lambda s: print(f"Ended: {s.endTime}"),
        )
        detector.start()
    """
    detector = DriveDetector(config, statisticsEngine, database)
    detector.registerCallbacks(
        onDriveStart=onDriveStart,
        onDriveEnd=onDriveEnd,
        onStateChange=onStateChange,
    )
    return detector
