################################################################################
# File Name: exceptions.py
# Purpose/Description: Exception definitions for the analysis subpackage
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation for US-010 refactoring
# ================================================================================
################################################################################

"""
Exception definitions for the analysis subpackage.

Provides:
- StatisticsError: Base exception for statistics-related errors
- StatisticsCalculationError: Error during statistics calculation
- StatisticsStorageError: Error storing statistics in database
- InsufficientDataError: Not enough data points to calculate statistics

These exceptions have minimal dependencies (only stdlib).
"""

from typing import Any

# ================================================================================
# Custom Exceptions
# ================================================================================

class StatisticsError(Exception):
    """Base exception for statistics-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class StatisticsCalculationError(StatisticsError):
    """Error during statistics calculation."""
    pass


class StatisticsStorageError(StatisticsError):
    """Error storing statistics in database."""
    pass


class InsufficientDataError(StatisticsError):
    """Not enough data points to calculate statistics."""
    pass
