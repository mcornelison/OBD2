################################################################################
# File Name: helpers.py
# Purpose/Description: Helper functions for calibration module
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
Calibration helper functions.

Factory functions and convenience wrappers for calibration operations.
"""

from typing import Any

from .comparator import CalibrationComparator
from .export import exportSession
from .manager import CalibrationManager
from .types import (
    CalibrationExportResult,
    CalibrationSessionComparison,
    ComparisonExportResult,
)


def createCalibrationManagerFromConfig(
    database: Any,
    config: dict[str, Any],
    displayManager: Any | None = None
) -> CalibrationManager:
    """
    Create a CalibrationManager from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary
        displayManager: Optional DisplayManager for indicator

    Returns:
        Configured CalibrationManager instance
    """
    return CalibrationManager(
        database=database,
        config=config,
        displayManager=displayManager
    )


def isCalibrationModeEnabled(config: dict[str, Any]) -> bool:
    """
    Check if calibration mode is enabled in config.

    Args:
        config: Configuration dictionary

    Returns:
        True if calibration mode is enabled
    """
    return config.get('calibration', {}).get('mode', False)


def getCalibrationConfig(config: dict[str, Any]) -> dict[str, Any]:
    """
    Get calibration configuration section.

    Args:
        config: Configuration dictionary

    Returns:
        Calibration config section with defaults
    """
    calibConfig = config.get('calibration', {})
    return {
        'mode': calibConfig.get('mode', False),
        'logAllParameters': calibConfig.get('logAllParameters', True),
        'sessionNotesRequired': calibConfig.get('sessionNotesRequired', False)
    }


def exportCalibrationSession(
    database: Any,
    sessionId: int,
    format: str = 'csv',
    exportDirectory: str = './exports/',
    filename: str | None = None
) -> CalibrationExportResult:
    """
    Export a calibration session to file (convenience function).

    Creates a temporary CalibrationManager to perform the export.
    This is useful when you need to export without maintaining
    a full CalibrationManager instance.

    Args:
        database: ObdDatabase instance
        sessionId: ID of the session to export
        format: Export format ('csv' or 'json')
        exportDirectory: Directory to save export file
        filename: Optional custom filename

    Returns:
        CalibrationExportResult with export details

    Example:
        from calibration import exportCalibrationSession

        result = exportCalibrationSession(
            database=db,
            sessionId=1,
            format='csv',
            exportDirectory='./exports/'
        )
    """
    return exportSession(
        database=database,
        sessionId=sessionId,
        format=format,
        exportDirectory=exportDirectory,
        filename=filename
    )


def createCalibrationComparatorFromConfig(
    database: Any,
    config: dict[str, Any]
) -> CalibrationComparator:
    """
    Create a CalibrationComparator from configuration.

    Args:
        database: ObdDatabase instance
        config: Configuration dictionary

    Returns:
        Configured CalibrationComparator instance
    """
    return CalibrationComparator(database=database, config=config)


def compareCalibrationSessions(
    database: Any,
    sessionIds: list[int],
    config: dict[str, Any] | None = None
) -> CalibrationSessionComparison:
    """
    Compare calibration sessions (convenience function).

    Creates a temporary CalibrationComparator to perform the comparison.

    Args:
        database: ObdDatabase instance
        sessionIds: List of session IDs to compare
        config: Optional configuration dictionary

    Returns:
        CalibrationSessionComparison with detailed comparison results
    """
    comparator = CalibrationComparator(database=database, config=config)
    return comparator.compareSessions(sessionIds)


def exportComparisonReport(
    database: Any,
    sessionIds: list[int],
    format: str = 'csv',
    exportDirectory: str = './exports/',
    filename: str | None = None,
    config: dict[str, Any] | None = None
) -> ComparisonExportResult:
    """
    Export a calibration session comparison report (convenience function).

    Args:
        database: ObdDatabase instance
        sessionIds: List of session IDs to compare
        format: Export format ('csv' or 'json')
        exportDirectory: Directory to save export file
        filename: Optional custom filename
        config: Optional configuration dictionary

    Returns:
        ComparisonExportResult with export details
    """
    comparator = CalibrationComparator(database=database, config=config)
    return comparator.exportComparison(
        sessionIds=sessionIds,
        format=format,
        exportDirectory=exportDirectory,
        filename=filename
    )


def getDefaultCalibrationConfig() -> dict[str, Any]:
    """
    Get default calibration configuration.

    Returns:
        Dictionary with default calibration settings
    """
    return {
        'mode': False,
        'logAllParameters': True,
        'sessionNotesRequired': False,
        'significanceThreshold': 10.0
    }


def validateCalibrationConfig(config: dict[str, Any]) -> list[str]:
    """
    Validate calibration configuration.

    Args:
        config: Configuration dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    calibConfig = config.get('calibration', {})

    # Validate mode
    mode = calibConfig.get('mode')
    if mode is not None and not isinstance(mode, bool):
        errors.append("calibration.mode must be a boolean")

    # Validate logAllParameters
    logAll = calibConfig.get('logAllParameters')
    if logAll is not None and not isinstance(logAll, bool):
        errors.append("calibration.logAllParameters must be a boolean")

    # Validate sessionNotesRequired
    notesReq = calibConfig.get('sessionNotesRequired')
    if notesReq is not None and not isinstance(notesReq, bool):
        errors.append("calibration.sessionNotesRequired must be a boolean")

    # Validate significanceThreshold
    threshold = calibConfig.get('significanceThreshold')
    if threshold is not None:
        if not isinstance(threshold, (int, float)):
            errors.append("calibration.significanceThreshold must be a number")
        elif threshold <= 0 or threshold > 100:
            errors.append("calibration.significanceThreshold must be between 0 and 100")

    return errors
