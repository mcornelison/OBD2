################################################################################
# File Name: __init__.py
# Purpose/Description: Vehicle subpackage for VIN decoding and static data
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added all exports for US-008
# ================================================================================
################################################################################
"""
Vehicle Subpackage.

This subpackage contains vehicle information components:
- VIN decoder (NHTSA API integration with caching)
- Static data collector (first-connection parameter collection)
- Vehicle info types and exceptions

Types:
    VinDecodeResult: Result of a VIN decode operation
    ApiCallResult: Result of a NHTSA API call
    StaticReading: Individual static parameter reading
    CollectionResult: Result of static data collection

Exceptions:
    VinDecoderError: Base exception for VIN decoder errors
    VinValidationError: VIN format is invalid
    VinApiError: Error calling NHTSA API
    VinApiTimeoutError: NHTSA API request timed out
    VinStorageError: Error storing VIN data in database
    StaticDataError: Base exception for static data collection errors
    VinNotAvailableError: VIN could not be read from the vehicle
    StaticDataStorageError: Error storing static data in database

Classes:
    VinDecoder: Decodes VINs using the NHTSA vPIC API
    StaticDataCollector: Manages static OBD-II data collection

Helper Functions:
    createVinDecoderFromConfig: Create a VinDecoder from configuration
    decodeVinOnFirstConnection: Convenience function to decode VIN
    isVinDecoderEnabled: Check if VIN decoder is enabled
    getVehicleInfo: Get stored vehicle information from database
    validateVinFormat: Validate VIN format
    createStaticDataCollectorFromConfig: Create a StaticDataCollector from config
    collectStaticDataOnFirstConnection: Collect static data if needed
    verifyStaticDataExists: Verify that static data exists for a VIN
    getStaticDataCount: Get the count of static data records for a VIN

Constants:
    NHTSA_API_BASE_URL: NHTSA API base URL for VIN decoding
    DEFAULT_API_TIMEOUT: Default timeout for API requests
    NHTSA_FIELD_MAPPING: Fields to extract from NHTSA response
    NHTSA_EXTRA_FIELDS: Additional fields to log

Usage:
    from obd.vehicle import VinDecoder, VinDecodeResult
    from obd.vehicle import StaticDataCollector, CollectionResult
    from obd.vehicle import createVinDecoderFromConfig, validateVinFormat
"""

# Types
from .types import (
    VinDecodeResult,
    ApiCallResult,
    StaticReading,
    CollectionResult,
)

# Exceptions
from .exceptions import (
    VinDecoderError,
    VinValidationError,
    VinApiError,
    VinApiTimeoutError,
    VinStorageError,
    StaticDataError,
    VinNotAvailableError,
    StaticDataStorageError,
)

# Classes
from .vin_decoder import (
    VinDecoder,
    NHTSA_API_BASE_URL,
    DEFAULT_API_TIMEOUT,
    NHTSA_FIELD_MAPPING,
    NHTSA_EXTRA_FIELDS,
)

from .static_collector import (
    StaticDataCollector,
)

# Helpers
from .helpers import (
    createVinDecoderFromConfig,
    decodeVinOnFirstConnection,
    isVinDecoderEnabled,
    getVehicleInfo,
    validateVinFormat,
    createStaticDataCollectorFromConfig,
    collectStaticDataOnFirstConnection,
    verifyStaticDataExists,
    getStaticDataCount,
)

__all__ = [
    # Types
    'VinDecodeResult',
    'ApiCallResult',
    'StaticReading',
    'CollectionResult',
    # Exceptions
    'VinDecoderError',
    'VinValidationError',
    'VinApiError',
    'VinApiTimeoutError',
    'VinStorageError',
    'StaticDataError',
    'VinNotAvailableError',
    'StaticDataStorageError',
    # Classes
    'VinDecoder',
    'StaticDataCollector',
    # Constants
    'NHTSA_API_BASE_URL',
    'DEFAULT_API_TIMEOUT',
    'NHTSA_FIELD_MAPPING',
    'NHTSA_EXTRA_FIELDS',
    # Helpers
    'createVinDecoderFromConfig',
    'decodeVinOnFirstConnection',
    'isVinDecoderEnabled',
    'getVehicleInfo',
    'validateVinFormat',
    'createStaticDataCollectorFromConfig',
    'collectStaticDataOnFirstConnection',
    'verifyStaticDataExists',
    'getStaticDataCount',
]
