################################################################################
# File Name: exceptions.py
# Purpose/Description: Exception classes for alert management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-011
# ================================================================================
################################################################################
"""
Exception classes for alert management.

Provides a hierarchy of exception classes for alert-related errors:
- AlertError: Base exception for all alert errors
- AlertConfigurationError: Errors in alert configuration
- AlertDatabaseError: Errors logging alerts to database
"""

from typing import Any


class AlertError(Exception):
    """Base exception for alert-related errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AlertConfigurationError(AlertError):
    """Error in alert configuration."""
    pass


class AlertDatabaseError(AlertError):
    """Error logging alert to database."""
    pass
