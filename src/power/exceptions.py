################################################################################
# File Name: exceptions.py
# Purpose/Description: Power and battery monitoring exceptions
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-012
# ================================================================================
################################################################################
"""
Power and battery monitoring exceptions.

This module contains all exception classes for power monitoring:
- PowerError: Base exception for power-related errors
- PowerConfigurationError: Error in power monitoring configuration
- BatteryError: Base exception for battery-related errors
- BatteryConfigurationError: Error in battery monitoring configuration

Exception hierarchy:
    Exception
    └── PowerError
        └── PowerConfigurationError
    └── BatteryError
        └── BatteryConfigurationError
"""

from typing import Any, Dict, Optional


# ================================================================================
# Power Exceptions
# ================================================================================

class PowerError(Exception):
    """
    Base exception for power-related errors.

    Attributes:
        message: Human-readable error message
        details: Additional error context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize the exception.

        Args:
            message: Human-readable error message
            details: Additional error context
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message


class PowerConfigurationError(PowerError):
    """
    Error in power monitoring configuration.

    Raised when power monitoring configuration is invalid or missing
    required settings (e.g., GPIO pin not configured, invalid intervals).
    """
    pass


class PowerMonitorError(PowerError):
    """
    Error during power monitoring operation.

    Raised when an error occurs during power monitoring operations
    (e.g., failed to read power status, display update failed).
    """
    pass


# ================================================================================
# Battery Exceptions
# ================================================================================

class BatteryError(Exception):
    """
    Base exception for battery-related errors.

    Attributes:
        message: Human-readable error message
        details: Additional error context as a dictionary
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize the exception.

        Args:
            message: Human-readable error message
            details: Additional error context
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        """Return string representation."""
        if self.details:
            return f"{self.message} | details={self.details}"
        return self.message


class BatteryConfigurationError(BatteryError):
    """
    Error in battery monitoring configuration.

    Raised when battery monitoring configuration is invalid or missing
    required settings (e.g., ADC channel not configured, invalid thresholds).
    """
    pass


class BatteryMonitorError(BatteryError):
    """
    Error during battery monitoring operation.

    Raised when an error occurs during battery monitoring operations
    (e.g., failed to read voltage, threshold check failed).
    """
    pass
