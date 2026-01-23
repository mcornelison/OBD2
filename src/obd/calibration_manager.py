################################################################################
# File Name: calibration_manager.py
# Purpose/Description: Calibration mode management for OBD-II system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-030
# 2026-01-22    | Ralph Agent  | Refactored to re-export from calibration subpackage (US-014)
# ================================================================================
################################################################################
"""
Calibration mode management module.

This module now re-exports from obd.calibration subpackage for backward compatibility.
New code should import directly from obd.calibration.

Usage:
    # Legacy import (still works)
    from obd.calibration_manager import CalibrationManager

    # New import (preferred)
    from obd.calibration import CalibrationManager
"""

# Re-export everything from calibration subpackage for backward compatibility
from obd.calibration import (
    # Enums
    CalibrationState,
    # Dataclasses
    CalibrationSession,
    CalibrationReading,
    CalibrationStats,
    CalibrationExportResult,
    # Constants
    SCHEMA_CALIBRATION_DATA,
    INDEX_CALIBRATION_DATA_SESSION,
    INDEX_CALIBRATION_DATA_TIMESTAMP,
    # Exceptions
    CalibrationError,
    CalibrationNotEnabledError,
    CalibrationSessionError,
    # Manager class
    CalibrationManager,
    # Helper functions
    createCalibrationManagerFromConfig,
    isCalibrationModeEnabled,
    getCalibrationConfig,
    exportCalibrationSession,
)


__all__ = [
    # Enums
    'CalibrationState',
    # Dataclasses
    'CalibrationSession',
    'CalibrationReading',
    'CalibrationStats',
    'CalibrationExportResult',
    # Constants
    'SCHEMA_CALIBRATION_DATA',
    'INDEX_CALIBRATION_DATA_SESSION',
    'INDEX_CALIBRATION_DATA_TIMESTAMP',
    # Exceptions
    'CalibrationError',
    'CalibrationNotEnabledError',
    'CalibrationSessionError',
    # Manager class
    'CalibrationManager',
    # Helper functions
    'createCalibrationManagerFromConfig',
    'isCalibrationModeEnabled',
    'getCalibrationConfig',
    'exportCalibrationSession',
]
