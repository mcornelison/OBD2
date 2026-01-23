################################################################################
# File Name: exceptions.py
# Purpose/Description: Exception classes for calibration module
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
Calibration exception definitions.

Contains exception classes for calibration-related errors.
This module has no project dependencies (only stdlib).
"""

from typing import Any, Dict, Optional


class CalibrationError(Exception):
    """
    Base exception for calibration errors.

    Attributes:
        message: Error message
        details: Optional dictionary with additional error details
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class CalibrationNotEnabledError(CalibrationError):
    """
    Raised when calibration operation attempted while mode disabled.

    Example:
        raise CalibrationNotEnabledError(
            "Cannot start session - calibration mode not enabled"
        )
    """
    pass


class CalibrationSessionError(CalibrationError):
    """
    Raised when session operation fails.

    Example:
        raise CalibrationSessionError(
            "Cannot start new session - a session is already active"
        )
    """
    pass


class CalibrationComparisonError(Exception):
    """
    Base exception for calibration comparison errors.

    Attributes:
        message: Error message
        details: Optional dictionary with additional error details
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
