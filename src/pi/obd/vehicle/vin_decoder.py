################################################################################
# File Name: vin_decoder.py
# Purpose/Description: VIN decoding via NHTSA API with database caching
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Refactored from obd/vin_decoder.py (US-008)
# ================================================================================
################################################################################

"""
VIN decoding module for the Eclipse OBD-II system.

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
    from obd.vehicle import VinDecoder

    # Create decoder with config and database
    decoder = VinDecoder(config, database)

    # Decode VIN (uses cache if available)
    result = decoder.decodeVin('1G1YY22G965104378')

    # Check if decoded data exists
    if result.success:
        print(f"Vehicle: {result.year} {result.make} {result.model}")
"""

import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .exceptions import VinApiTimeoutError, VinStorageError
from .types import ApiCallResult, VinDecodeResult

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# NHTSA API base URL for VIN decoding
NHTSA_API_BASE_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues"

# Default timeout for API requests (seconds)
DEFAULT_API_TIMEOUT = 30

# Fields to extract from NHTSA response and store in vehicle_info
NHTSA_FIELD_MAPPING = {
    'Make': 'make',
    'Model': 'model',
    'ModelYear': 'year',
    'EngineModel': 'engine',
    'FuelTypePrimary': 'fuel_type',
    'TransmissionStyle': 'transmission',
    'DriveType': 'drive_type',
    'BodyClass': 'body_class',
    'PlantCity': 'plant_city',
    'PlantCountry': 'plant_country',
}

# Additional fields to log but not necessarily store
NHTSA_EXTRA_FIELDS = [
    'VehicleType',
    'Manufacturer',
    'Series',
    'Trim',
    'DisplacementL',
    'EngineCylinders',
    'EngineHP',
    'ErrorCode',
    'ErrorText',
]


# ================================================================================
# VIN Decoder Class
# ================================================================================

class VinDecoder:
    """
    Decodes Vehicle Identification Numbers using the NHTSA vPIC API.

    Provides VIN decoding with automatic database caching to avoid
    redundant API calls. Stores decoded data in the vehicle_info table.

    Features:
    - NHTSA API integration for VIN decoding
    - Database caching for previously decoded VINs
    - Retry logic for transient API failures
    - Graceful error handling

    Attributes:
        config: Configuration dictionary with 'vinDecoder' section
        database: ObdDatabase instance for caching

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        decoder = VinDecoder(config, db)

        # Decode VIN (checks cache first)
        result = decoder.decodeVin('1G1YY22G965104378')

        if result.success:
            print(f"Vehicle: {result.getVehicleSummary()}")
            print(f"From cache: {result.fromCache}")
    """

    def __init__(self, config: dict[str, Any], database: Any):
        """
        Initialize the VIN decoder.

        Args:
            config: Configuration dictionary with 'vinDecoder' section
            database: ObdDatabase instance for caching decoded data
        """
        self.config = config
        self.database = database

        # Extract VIN decoder configuration
        vinConfig = config.get('vinDecoder', {})
        self._enabled = vinConfig.get('enabled', True)
        self._apiBaseUrl = vinConfig.get('apiBaseUrl', NHTSA_API_BASE_URL)
        self._apiTimeout = vinConfig.get('apiTimeoutSeconds', DEFAULT_API_TIMEOUT)
        self._cacheVinData = vinConfig.get('cacheVinData', True)

        # Statistics
        self._totalDecodes = 0
        self._cacheHits = 0
        self._apiCalls = 0
        self._apiErrors = 0

    def decodeVin(self, vin: str, forceApiCall: bool = False) -> VinDecodeResult:
        """
        Decode a VIN and return vehicle information.

        Checks database cache first. If VIN is not cached or forceApiCall
        is True, calls the NHTSA API to decode the VIN.

        Args:
            vin: 17-character Vehicle Identification Number
            forceApiCall: If True, bypass cache and call API

        Returns:
            VinDecodeResult with vehicle information

        Raises:
            VinValidationError: If VIN format is invalid
        """
        self._totalDecodes += 1

        # Validate VIN format
        normalizedVin = self._normalizeVin(vin)
        if not self._isValidVin(normalizedVin):
            return VinDecodeResult(
                vin=vin,
                success=False,
                errorMessage=f"Invalid VIN format: {vin}"
            )

        # Check if decoder is enabled
        if not self._enabled:
            logger.debug("VIN decoder is disabled in configuration")
            return VinDecodeResult(
                vin=normalizedVin,
                success=False,
                errorMessage="VIN decoder is disabled"
            )

        # Check cache first (unless forcing API call)
        if not forceApiCall and self._cacheVinData:
            cachedResult = self._getFromCache(normalizedVin)
            if cachedResult:
                self._cacheHits += 1
                logger.debug(f"VIN {normalizedVin} found in cache")
                return cachedResult

        # Call NHTSA API
        logger.info(f"Decoding VIN via NHTSA API: {normalizedVin}")
        result = self._decodeViaApi(normalizedVin)

        # Store in cache if successful
        if result.success and self._cacheVinData:
            try:
                self._storeInCache(result)
            except Exception as e:
                logger.warning(f"Failed to cache VIN decode result: {e}")

        return result

    def getDecodedVin(self, vin: str) -> VinDecodeResult | None:
        """
        Get previously decoded VIN data from cache.

        Does not call the API, only checks the database cache.

        Args:
            vin: Vehicle Identification Number

        Returns:
            VinDecodeResult if found in cache, None otherwise
        """
        normalizedVin = self._normalizeVin(vin)
        return self._getFromCache(normalizedVin)

    def isVinCached(self, vin: str) -> bool:
        """
        Check if a VIN is already cached in the database.

        Args:
            vin: Vehicle Identification Number

        Returns:
            True if VIN is in the cache
        """
        normalizedVin = self._normalizeVin(vin)
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM vehicle_info WHERE vin = ?",
                    (normalizedVin,)
                )
                count = cursor.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.warning(f"Error checking VIN cache: {e}")
            return False

    def getStats(self) -> dict[str, Any]:
        """
        Get decoder statistics.

        Returns:
            Dictionary with decode statistics
        """
        return {
            'totalDecodes': self._totalDecodes,
            'cacheHits': self._cacheHits,
            'apiCalls': self._apiCalls,
            'apiErrors': self._apiErrors,
            'cacheHitRate': (
                self._cacheHits / self._totalDecodes
                if self._totalDecodes > 0 else 0.0
            ),
        }

    def _normalizeVin(self, vin: str) -> str:
        """
        Normalize VIN to uppercase without spaces.

        Args:
            vin: Raw VIN string

        Returns:
            Normalized VIN string
        """
        return vin.strip().upper().replace(' ', '').replace('-', '')

    def _isValidVin(self, vin: str) -> bool:
        """
        Validate VIN format.

        A valid VIN is exactly 17 characters and contains only
        alphanumeric characters (no I, O, Q which are not used in VINs).

        Args:
            vin: Normalized VIN string

        Returns:
            True if VIN format is valid
        """
        if len(vin) != 17:
            return False

        # VINs can only contain specific characters (no I, O, Q)
        validChars = set('ABCDEFGHJKLMNPRSTUVWXYZ0123456789')
        return all(c in validChars for c in vin)

    def _getFromCache(self, vin: str) -> VinDecodeResult | None:
        """
        Get decoded VIN data from database cache.

        Args:
            vin: Normalized VIN string

        Returns:
            VinDecodeResult if found, None otherwise
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT vin, make, model, year, engine, fuel_type,
                           transmission, drive_type, body_class,
                           plant_city, plant_country, raw_api_response
                    FROM vehicle_info
                    WHERE vin = ?
                    """,
                    (vin,)
                )
                row = cursor.fetchone()

                if row:
                    return VinDecodeResult(
                        vin=row[0],
                        success=True,
                        make=row[1],
                        model=row[2],
                        year=row[3],
                        engine=row[4],
                        fuelType=row[5],
                        transmission=row[6],
                        driveType=row[7],
                        bodyClass=row[8],
                        plantCity=row[9],
                        plantCountry=row[10],
                        rawResponse=row[11],
                        fromCache=True
                    )

                return None

        except Exception as e:
            logger.warning(f"Error reading from VIN cache: {e}")
            return None

    def _storeInCache(self, result: VinDecodeResult) -> None:
        """
        Store decoded VIN data in database cache.

        Uses INSERT OR REPLACE to update existing records.

        Args:
            result: VinDecodeResult to store

        Raises:
            VinStorageError: If storage fails
        """
        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO vehicle_info (
                        vin, make, model, year, engine, fuel_type,
                        transmission, drive_type, body_class,
                        plant_city, plant_country, raw_api_response,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.vin,
                        result.make,
                        result.model,
                        result.year,
                        result.engine,
                        result.fuelType,
                        result.transmission,
                        result.driveType,
                        result.bodyClass,
                        result.plantCity,
                        result.plantCountry,
                        result.rawResponse,
                        datetime.now(),
                        datetime.now()
                    )
                )
                logger.debug(f"Cached VIN decode result for: {result.vin}")

        except Exception as e:
            raise VinStorageError(
                f"Failed to store VIN data: {e}",
                details={'vin': result.vin, 'error': str(e)}
            ) from e

    def _decodeViaApi(self, vin: str) -> VinDecodeResult:
        """
        Decode VIN via NHTSA API with retry.

        Retries once on transient failures as per acceptance criteria.

        Args:
            vin: Normalized VIN string

        Returns:
            VinDecodeResult with decoded data or error
        """
        maxRetries = 1  # Retry once as per acceptance criteria
        lastError = None

        for attempt in range(maxRetries + 1):
            self._apiCalls += 1

            try:
                apiResult = self._callNhtsaApi(vin)

                if apiResult.success and apiResult.data:
                    return self._parseApiResponse(vin, apiResult.data)
                else:
                    lastError = apiResult.errorMessage
                    logger.warning(
                        f"NHTSA API call failed (attempt {attempt + 1}/{maxRetries + 1}): "
                        f"{apiResult.errorMessage}"
                    )

            except VinApiTimeoutError as e:
                lastError = str(e)
                logger.warning(
                    f"NHTSA API timeout (attempt {attempt + 1}/{maxRetries + 1}): {e}"
                )
            except Exception as e:
                lastError = str(e)
                logger.warning(
                    f"NHTSA API error (attempt {attempt + 1}/{maxRetries + 1}): {e}"
                )

            # Wait before retry (exponential backoff: 1s, 2s, ...)
            if attempt < maxRetries:
                waitTime = 2 ** attempt
                logger.debug(f"Waiting {waitTime}s before retry...")
                time.sleep(waitTime)

        # All retries failed
        self._apiErrors += 1
        logger.error(f"Failed to decode VIN {vin} after {maxRetries + 1} attempts: {lastError}")

        return VinDecodeResult(
            vin=vin,
            success=False,
            errorMessage=f"API call failed: {lastError}"
        )

    def _callNhtsaApi(self, vin: str) -> ApiCallResult:
        """
        Make HTTP call to NHTSA API.

        Args:
            vin: Normalized VIN string

        Returns:
            ApiCallResult with response data or error
        """
        url = f"{self._apiBaseUrl}/{vin}?format=json"

        try:
            request = Request(
                url,
                headers={
                    'User-Agent': 'Eclipse OBD-II Monitor/1.0',
                    'Accept': 'application/json'
                }
            )

            with urlopen(request, timeout=self._apiTimeout) as response:
                statusCode = response.status
                rawData = response.read().decode('utf-8')
                data = json.loads(rawData)

                return ApiCallResult(
                    success=True,
                    data=data,
                    statusCode=statusCode
                )

        except HTTPError as e:
            return ApiCallResult(
                success=False,
                statusCode=e.code,
                errorMessage=f"HTTP error {e.code}: {e.reason}"
            )
        except URLError as e:
            if 'timed out' in str(e.reason).lower():
                raise VinApiTimeoutError(
                    f"API request timed out after {self._apiTimeout}s",
                    details={'vin': vin, 'timeout': self._apiTimeout}
                ) from e
            return ApiCallResult(
                success=False,
                errorMessage=f"URL error: {e.reason}"
            )
        except json.JSONDecodeError as e:
            return ApiCallResult(
                success=False,
                errorMessage=f"Invalid JSON response: {e}"
            )
        except Exception as e:
            return ApiCallResult(
                success=False,
                errorMessage=f"Unexpected error: {e}"
            )

    def _parseApiResponse(self, vin: str, data: dict[str, Any]) -> VinDecodeResult:
        """
        Parse NHTSA API response into VinDecodeResult.

        Args:
            vin: Normalized VIN string
            data: Parsed JSON response from API

        Returns:
            VinDecodeResult with extracted vehicle information
        """
        # NHTSA API returns results in a 'Results' array
        results = data.get('Results', [])

        if not results:
            return VinDecodeResult(
                vin=vin,
                success=False,
                errorMessage="No results returned from API",
                rawResponse=json.dumps(data)
            )

        # Get first result (should be only one for VIN decode)
        vehicleData = results[0]

        # Check for API-level errors
        errorCode = vehicleData.get('ErrorCode', '0')
        errorText = vehicleData.get('ErrorText', '')

        # ErrorCode 0 means success, non-zero indicates issues
        # However, partial matches may still have useful data
        if errorCode and errorCode != '0':
            logger.warning(f"NHTSA API returned error code {errorCode}: {errorText}")

        # Extract fields using mapping
        result = VinDecodeResult(
            vin=vin,
            success=True,
            rawResponse=json.dumps(data),
            errorCode=errorCode if errorCode != '0' else None
        )

        # Map NHTSA fields to result attributes
        result.make = self._extractField(vehicleData, 'Make')
        result.model = self._extractField(vehicleData, 'Model')
        result.engine = self._extractField(vehicleData, 'EngineModel')
        result.fuelType = self._extractField(vehicleData, 'FuelTypePrimary')
        result.transmission = self._extractField(vehicleData, 'TransmissionStyle')
        result.driveType = self._extractField(vehicleData, 'DriveType')
        result.bodyClass = self._extractField(vehicleData, 'BodyClass')
        result.plantCity = self._extractField(vehicleData, 'PlantCity')
        result.plantCountry = self._extractField(vehicleData, 'PlantCountry')

        # Parse year as integer
        yearStr = self._extractField(vehicleData, 'ModelYear')
        if yearStr:
            try:
                result.year = int(yearStr)
            except ValueError:
                logger.warning(f"Invalid year value: {yearStr}")

        # Log extra fields for debugging
        for fieldName in NHTSA_EXTRA_FIELDS:
            value = self._extractField(vehicleData, fieldName)
            if value:
                logger.debug(f"NHTSA {fieldName}: {value}")

        logger.info(
            f"VIN decoded | vin={vin} | "
            f"vehicle={result.getVehicleSummary()}"
        )

        return result

    def _extractField(
        self,
        data: dict[str, Any],
        fieldName: str
    ) -> str | None:
        """
        Extract a field value from API response.

        Handles empty strings and 'Not Applicable' values.

        Args:
            data: Vehicle data dictionary
            fieldName: Field name to extract

        Returns:
            Field value or None if empty/not applicable
        """
        value = data.get(fieldName)

        if value is None:
            return None

        # Convert to string and clean up
        strValue = str(value).strip()

        # Treat empty or "not applicable" as None
        if not strValue or strValue.lower() in ('not applicable', 'n/a', 'na', ''):
            return None

        return strValue
