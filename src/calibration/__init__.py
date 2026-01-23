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
    from obd.calibration import (
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
from .types import (
    # Enums
    CalibrationState,
    # Dataclasses
    CalibrationSession,
    CalibrationReading,
    CalibrationStats,
    CalibrationExportResult,
    # Comparator types
    ParameterSessionStats,
    SessionComparisonResult,
    CalibrationSessionComparison,
    ComparisonExportResult,
    # Constants
    SIGNIFICANCE_THRESHOLD,
    SCHEMA_CALIBRATION_DATA,
    INDEX_CALIBRATION_DATA_SESSION,
    INDEX_CALIBRATION_DATA_TIMESTAMP,
)

# Exceptions
from .exceptions import (
    CalibrationError,
    CalibrationNotEnabledError,
    CalibrationSessionError,
    CalibrationComparisonError,
)

# Session lifecycle functions
from .session import (
    createSession,
    endSession,
    getSession,
    listSessions,
    deleteSession,
    sessionExists,
)

# Reading collection functions
from .collector import (
    logReading,
    getSessionReadings,
    getReadingCount,
    getParameterNames,
    logMultipleReadings,
)

# Export functions
from .export import (
    exportSession,
)

# Manager class
from .manager import CalibrationManager

# Comparator class
from .comparator import CalibrationComparator

# Helper functions
from .helpers import (
    createCalibrationManagerFromConfig,
    isCalibrationModeEnabled,
    getCalibrationConfig,
    exportCalibrationSession,
    createCalibrationComparatorFromConfig,
    compareCalibrationSessions,
    exportComparisonReport,
    getDefaultCalibrationConfig,
    validateCalibrationConfig,
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
