################################################################################
# File Name: exceptions.py
# Purpose/Description: Exception classes for OBD-II data logging
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-007 (data module refactor)
# ================================================================================
################################################################################
"""
Exception classes for OBD-II data logging.

This module provides a hierarchy of exceptions for data logging operations:
- DataLoggerError: Base exception for all data logger errors
- ParameterNotSupportedError: Parameter is not supported by the vehicle
- ParameterReadError: Error reading a parameter from the OBD-II interface

Usage:
    from src.obd.data.exceptions import (
        DataLoggerError,
        ParameterNotSupportedError,
        ParameterReadError
    )

    try:
        reading = logger.queryParameter('RPM')
    except ParameterNotSupportedError:
        print("RPM not supported by this vehicle")
    except ParameterReadError as e:
        print(f"Failed to read: {e.details}")
"""

from typing import Any


class DataLoggerError(Exception):
    """
    Base exception for data logger errors.

    Provides a structured way to include error details for debugging
    and logging purposes.

    Attributes:
        message: Human-readable error message
        details: Additional context as key-value pairs

    Example:
        raise DataLoggerError(
            "Failed to connect",
            details={'port': '/dev/ttyUSB0', 'error': 'timeout'}
        )
    """

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """
        Initialize the exception.

        Args:
            message: Human-readable error message
            details: Optional dictionary of additional context
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ParameterNotSupportedError(DataLoggerError):
    """
    Parameter is not supported by the vehicle.

    Raised when attempting to query a parameter that the vehicle's
    ECU does not support or does not report.

    Example:
        if not vehicle_supports(parameterName):
            raise ParameterNotSupportedError(
                f"Parameter '{parameterName}' not supported",
                details={'parameter': parameterName, 'protocol': 'CAN'}
            )
    """
    pass


class ParameterReadError(DataLoggerError):
    """
    Error reading a parameter from the OBD-II interface.

    Raised when a parameter query fails due to communication errors,
    null responses, or other transient issues.

    Example:
        if response.is_null():
            raise ParameterReadError(
                f"Parameter '{parameterName}' returned null response",
                details={'parameter': parameterName}
            )
    """
    pass
