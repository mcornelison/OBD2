################################################################################
# File Name: exceptions.py
# Purpose/Description: Display-related exception classes
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-004
# ================================================================================
################################################################################
"""
Display exceptions module.

Provides exception classes for display-related errors:
- DisplayError: Base exception for all display errors
- DisplayInitializationError: Raised when display initialization fails
- DisplayOutputError: Raised when display output operations fail
"""

from typing import Any, Dict, Optional


class DisplayError(Exception):
    """Base exception for display-related errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        """
        Initialize DisplayError.

        Args:
            message: Error message
            details: Optional dictionary with additional error details
        """
        super().__init__(message)
        self.details = details or {}


class DisplayInitializationError(DisplayError):
    """Raised when display initialization fails."""
    pass


class DisplayOutputError(DisplayError):
    """Raised when display output fails."""
    pass
