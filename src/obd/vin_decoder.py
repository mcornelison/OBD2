################################################################################
# File Name: vin_decoder.py
# Purpose/Description: VIN decoding via NHTSA API with database caching
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-013
# 2026-01-22    | Ralph Agent  | Refactored - now re-exports from vehicle subpackage (US-008)
# ================================================================================
################################################################################

"""
VIN decoding module for the Eclipse OBD-II system.

This module re-exports all functionality from the obd.vehicle subpackage
for backward compatibility. New code should import directly from obd.vehicle.

Provides:
- NHTSA API integration for VIN decoding
- Database caching to avoid duplicate API calls
- Automatic vehicle_info table population
- Graceful failure handling with retry logic

The NHTSA vPIC (Vehicle Product Information Catalog) API provides free
vehicle information decoding based on the 17-character VIN.

API Documentation:
    https://vpic.nhtsa.dot.gov/api/

Usage:
    from obd.vin_decoder import VinDecoder  # Legacy - still works
    # OR preferred:
    from obd.vehicle import VinDecoder

    # Create decoder with config and database
    decoder = VinDecoder(config, database)

    # Decode VIN (uses cache if available)
    result = decoder.decodeVin('1G1YY22G965104378')

    # Check if decoded data exists
    if result.success:
        print(f"Vehicle: {result.year} {result.make} {result.model}")
"""

# Re-export everything from the vehicle subpackage for backward compatibility
from obd.vehicle import (
    # Types
    VinDecodeResult,
    ApiCallResult,
    # Exceptions
    VinDecoderError,
    VinValidationError,
    VinApiError,
    VinApiTimeoutError,
    VinStorageError,
    # Classes
    VinDecoder,
    # Constants
    NHTSA_API_BASE_URL,
    DEFAULT_API_TIMEOUT,
    NHTSA_FIELD_MAPPING,
    NHTSA_EXTRA_FIELDS,
    # Helpers
    createVinDecoderFromConfig,
    decodeVinOnFirstConnection,
    isVinDecoderEnabled,
    getVehicleInfo,
    validateVinFormat,
)

__all__ = [
    # Types
    'VinDecodeResult',
    'ApiCallResult',
    # Exceptions
    'VinDecoderError',
    'VinValidationError',
    'VinApiError',
    'VinApiTimeoutError',
    'VinStorageError',
    # Classes
    'VinDecoder',
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
]
