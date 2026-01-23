################################################################################
# File Name: exceptions.py
# Purpose/Description: Vehicle-related exceptions
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation (US-008)
# ================================================================================
################################################################################

"""
Vehicle exceptions module.

Contains exceptions for VIN decoding and static data collection:
- VinDecoderError: Base exception for VIN decoder errors
- VinValidationError: VIN format is invalid
- VinApiError: Error calling NHTSA API
- VinApiTimeoutError: NHTSA API request timed out
- VinStorageError: Error storing VIN data in database
- StaticDataError: Base exception for static data collection errors
- VinNotAvailableError: VIN could not be read from the vehicle
- StaticDataStorageError: Error storing static data in database
"""

from typing import Any, Dict, Optional


# ================================================================================
# VIN Decoder Exceptions
# ================================================================================

class VinDecoderError(Exception):
    """Base exception for VIN decoder errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class VinValidationError(VinDecoderError):
    """VIN format is invalid."""
    pass


class VinApiError(VinDecoderError):
    """Error calling NHTSA API."""
    pass


class VinApiTimeoutError(VinApiError):
    """NHTSA API request timed out."""
    pass


class VinStorageError(VinDecoderError):
    """Error storing VIN data in database."""
    pass


# ================================================================================
# Static Data Collector Exceptions
# ================================================================================

class StaticDataError(Exception):
    """Base exception for static data collection errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class VinNotAvailableError(StaticDataError):
    """VIN could not be read from the vehicle."""
    pass


class StaticDataStorageError(StaticDataError):
    """Error storing static data in database."""
    pass
