################################################################################
# File Name: __init__.py
# Purpose/Description: Calibration subpackage for sensor calibration management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added all calibration module exports (US-014)
# ================================================================================
################################################################################
"""
Calibration Subpackage.

This subpackage contains calibration components:
- Calibration session management
- Reading collection and storage
- Session export (CSV/JSON)
- Calibration comparison algorithms

Usage:
    from calibration import (
        CalibrationManager,
        CalibrationComparator,
        CalibrationSession,
        CalibrationReading,
        CalibrationState,
    )

    # Create manager
    manager = CalibrationManager(database=db, config=config)

    # Enable and start session
    manager.enable()
    session = manager.startSession(notes="Test run #1")

    # Log readings
    manager.logCalibrationReading("RPM", 2500, "rpm")

    # End and export
    manager.endSession()
    result = manager.exportSession(session.sessionId, format='csv')
"""

# Types
# Reading collection functions
from .collector import (
    getParameterNames,
    getReadingCount,
    getSessionReadings,
    logMultipleReadings,
    logReading,
)

# Comparator class
from .comparator import CalibrationComparator

# Exceptions
from .exceptions import (
    CalibrationComparisonError,
    CalibrationError,
    CalibrationNotEnabledError,
    CalibrationSessionError,
)

# Export functions
from .export import (
    exportSession,
)

# Helper functions
from .helpers import (
    compareCalibrationSessions,
    createCalibrationComparatorFromConfig,
    createCalibrationManagerFromConfig,
    exportCalibrationSession,
    exportComparisonReport,
    getCalibrationConfig,
    getDefaultCalibrationConfig,
    isCalibrationModeEnabled,
    validateCalibrationConfig,
)

# Manager class
from .manager import CalibrationManager

# Session lifecycle functions
from .session import (
    createSession,
    deleteSession,
    endSession,
    getSession,
    listSessions,
    sessionExists,
)
from .types import (
    INDEX_CALIBRATION_DATA_SESSION,
    INDEX_CALIBRATION_DATA_TIMESTAMP,
    SCHEMA_CALIBRATION_DATA,
    # Constants
    SIGNIFICANCE_THRESHOLD,
    CalibrationExportResult,
    CalibrationReading,
    # Dataclasses
    CalibrationSession,
    CalibrationSessionComparison,
    # Enums
    CalibrationState,
    CalibrationStats,
    ComparisonExportResult,
    # Comparator types
    ParameterSessionStats,
    SessionComparisonResult,
)

__all__ = [
    # Enums
    'CalibrationState',
    # Dataclasses
    'CalibrationSession',
    'CalibrationReading',
    'CalibrationStats',
    'CalibrationExportResult',
    'ParameterSessionStats',
    'SessionComparisonResult',
    'CalibrationSessionComparison',
    'ComparisonExportResult',
    # Constants
    'SIGNIFICANCE_THRESHOLD',
    'SCHEMA_CALIBRATION_DATA',
    'INDEX_CALIBRATION_DATA_SESSION',
    'INDEX_CALIBRATION_DATA_TIMESTAMP',
    # Exceptions
    'CalibrationError',
    'CalibrationNotEnabledError',
    'CalibrationSessionError',
    'CalibrationComparisonError',
    # Session functions
    'createSession',
    'endSession',
    'getSession',
    'listSessions',
    'deleteSession',
    'sessionExists',
    # Collector functions
    'logReading',
    'getSessionReadings',
    'getReadingCount',
    'getParameterNames',
    'logMultipleReadings',
    # Export functions
    'exportSession',
    # Manager class
    'CalibrationManager',
    # Comparator class
    'CalibrationComparator',
    # Helpers
    'createCalibrationManagerFromConfig',
    'isCalibrationModeEnabled',
    'getCalibrationConfig',
    'exportCalibrationSession',
    'createCalibrationComparatorFromConfig',
    'compareCalibrationSessions',
    'exportComparisonReport',
    'getDefaultCalibrationConfig',
    'validateCalibrationConfig',
]
