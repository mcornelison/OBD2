################################################################################
# File Name: calibration_comparator.py
# Purpose/Description: Calibration session comparison tool for sensor validation
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-032
# 2026-01-22    | Ralph Agent  | Refactored to re-export from calibration subpackage (US-014)
# ================================================================================
################################################################################
"""
Calibration session comparison module.

This module now re-exports from calibration subpackage for backward compatibility.
New code should import directly from calibration.

Usage:
    # Legacy import (still works)
    from obd.calibration_comparator import CalibrationComparator

    # New import (preferred)
    from calibration import CalibrationComparator
"""

# Re-export everything from calibration subpackage for backward compatibility
from calibration import (
    # Constants
    SIGNIFICANCE_THRESHOLD,
    # Exceptions
    CalibrationComparisonError,
    # Dataclasses
    ParameterSessionStats,
    SessionComparisonResult,
    CalibrationSessionComparison,
    ComparisonExportResult,
    # Comparator class
    CalibrationComparator,
    # Helper functions
    createCalibrationComparatorFromConfig,
    compareCalibrationSessions,
    exportComparisonReport,
)


__all__ = [
    # Constants
    'SIGNIFICANCE_THRESHOLD',
    # Exceptions
    'CalibrationComparisonError',
    # Dataclasses
    'ParameterSessionStats',
    'SessionComparisonResult',
    'CalibrationSessionComparison',
    'ComparisonExportResult',
    # Comparator class
    'CalibrationComparator',
    # Helper functions
    'createCalibrationComparatorFromConfig',
    'compareCalibrationSessions',
    'exportComparisonReport',
]
