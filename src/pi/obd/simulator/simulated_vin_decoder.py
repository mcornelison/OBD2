################################################################################
# File Name: simulated_vin_decoder.py
# Purpose/Description: Simulated VIN decoding using vehicle profile data
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-042
# ================================================================================
################################################################################

"""
Simulated VIN decoding module for the Eclipse OBD-II simulator.

Provides:
- SimulatedVinDecoder class that bypasses NHTSA API
- Uses vehicle profile data directly for VIN information
- Supports database caching for compatibility with real VIN decoder
- Seamless integration with StaticDataCollector

This module enables VIN decoding in simulation mode without requiring
network access to the NHTSA API. All vehicle information comes from
the configured vehicle profile.

Usage:
    from obd.simulator.simulated_vin_decoder import SimulatedVinDecoder

    # Create decoder with profile and database
    profile = loadProfile('eclipse_gst.json')
    decoder = SimulatedVinDecoder(profile, config, database)

    # Decode VIN (uses profile data directly)
    result = decoder.decodeVin()

    if result.success:
        print(f"Vehicle: {result.getVehicleSummary()}")
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .vehicle_profile import VehicleProfile, getDefaultProfile

logger = logging.getLogger(__name__)


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class SimulatedVinDecodeResult:
    """
    Result of a simulated VIN decode operation.

    Matches the interface of VinDecodeResult from vin_decoder.py.

    Attributes:
        vin: The VIN that was decoded
        success: Whether the decode was successful
        make: Vehicle manufacturer
        model: Vehicle model
        year: Model year
        engine: Engine model/type
        fuelType: Primary fuel type
        transmission: Transmission style (simulated as "Manual" or "Automatic")
        driveType: Drive type (simulated)
        bodyClass: Body class (simulated)
        plantCity: Manufacturing plant city (simulated)
        plantCountry: Manufacturing plant country (simulated)
        rawResponse: Raw profile data as JSON string
        fromCache: True if result came from database cache
        fromSimulator: True indicating this is simulated data
        errorMessage: Error message if decode failed
    """
    vin: str
    success: bool = False
    make: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    fuelType: str | None = None
    transmission: str | None = None
    driveType: str | None = None
    bodyClass: str | None = None
    plantCity: str | None = None
    plantCountry: str | None = None
    rawResponse: str | None = None
    fromCache: bool = False
    fromSimulator: bool = True
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            'vin': self.vin,
            'success': self.success,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'engine': self.engine,
            'fuelType': self.fuelType,
            'transmission': self.transmission,
            'driveType': self.driveType,
            'bodyClass': self.bodyClass,
            'plantCity': self.plantCity,
            'plantCountry': self.plantCountry,
            'fromCache': self.fromCache,
            'fromSimulator': self.fromSimulator,
            'errorMessage': self.errorMessage,
        }

    def getVehicleSummary(self) -> str:
        """Get a human-readable vehicle summary."""
        if not self.success:
            return f"Unknown vehicle (VIN: {self.vin})"

        parts = []
        if self.year:
            parts.append(str(self.year))
        if self.make:
            parts.append(self.make)
        if self.model:
            parts.append(self.model)

        if parts:
            return ' '.join(parts)
        return f"Vehicle (VIN: {self.vin})"


# ================================================================================
# Custom Exceptions
# ================================================================================

class SimulatedVinDecoderError(Exception):
    """Base exception for simulated VIN decoder errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SimulatedVinStorageError(SimulatedVinDecoderError):
    """Error storing simulated VIN data in database."""
    pass


# ================================================================================
# SimulatedVinDecoder Class
# ================================================================================

class SimulatedVinDecoder:
    """
    Simulated VIN decoder that uses vehicle profile data.

    Bypasses the NHTSA API and uses data directly from the vehicle profile.
    Provides the same interface as the real VinDecoder for seamless integration.

    Features:
    - Uses VehicleProfile data instead of API calls
    - Optional database caching for compatibility
    - Generates realistic vehicle info from profile
    - No network calls required

    Attributes:
        profile: VehicleProfile with vehicle information
        config: Configuration dictionary
        database: Optional ObdDatabase instance for caching

    Example:
        profile = loadProfile('eclipse_gst.json')
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        decoder = SimulatedVinDecoder(profile, config, db)

        # Decode using profile data
        result = decoder.decodeVin()

        if result.success:
            print(f"Vehicle: {result.getVehicleSummary()}")
    """

    def __init__(
        self,
        profile: VehicleProfile | None = None,
        config: dict[str, Any] | None = None,
        database: Any | None = None
    ):
        """
        Initialize the simulated VIN decoder.

        Args:
            profile: VehicleProfile with vehicle data (uses default if None)
            config: Configuration dictionary
            database: ObdDatabase instance for caching decoded data
        """
        self.profile = profile if profile is not None else getDefaultProfile()
        self.config = config or {}
        self.database = database

        # Extract VIN decoder configuration
        vinConfig = self.config.get('vinDecoder', {})
        self._cacheVinData = vinConfig.get('cacheVinData', True)

        # Statistics
        self._totalDecodes = 0
        self._cacheHits = 0

    def decodeVin(
        self,
        vin: str | None = None,
        forceRefresh: bool = False
    ) -> SimulatedVinDecodeResult:
        """
        Decode a VIN using the vehicle profile data.

        If no VIN is provided, uses the VIN from the vehicle profile.

        Args:
            vin: VIN to decode (optional, uses profile VIN if not provided)
            forceRefresh: If True, bypass cache and refresh from profile

        Returns:
            SimulatedVinDecodeResult with vehicle information
        """
        self._totalDecodes += 1

        # Use profile VIN if not specified
        targetVin = vin if vin else self.profile.vin

        logger.info(f"Simulated VIN decode: {targetVin}")

        # Check cache first (unless forcing refresh)
        if not forceRefresh and self._cacheVinData and self.database:
            cachedResult = self._getFromCache(targetVin)
            if cachedResult:
                self._cacheHits += 1
                logger.debug(f"VIN {targetVin} found in cache (simulated)")
                return cachedResult

        # Generate result from profile
        result = self._decodeFromProfile(targetVin)

        # Store in cache if enabled
        if result.success and self._cacheVinData and self.database:
            try:
                self._storeInCache(result)
            except Exception as e:
                logger.warning(f"Failed to cache simulated VIN decode result: {e}")

        return result

    def _decodeFromProfile(self, vin: str) -> SimulatedVinDecodeResult:
        """
        Generate VIN decode result from vehicle profile.

        Args:
            vin: VIN to decode

        Returns:
            SimulatedVinDecodeResult populated from profile
        """
        # Build engine description from profile
        engineDesc = self._buildEngineDescription()

        # Generate simulated transmission and body class
        transmission = self._inferTransmission()
        bodyClass = self._inferBodyClass()

        # Create result from profile data
        result = SimulatedVinDecodeResult(
            vin=vin,
            success=True,
            make=self.profile.make,
            model=self.profile.model,
            year=self.profile.year,
            engine=engineDesc,
            fuelType=self.profile.fuelType,
            transmission=transmission,
            driveType="FWD",  # Could be inferred from profile in future
            bodyClass=bodyClass,
            plantCity="Simulated",
            plantCountry="Simulation",
            rawResponse=json.dumps(self.profile.toDict()),
            fromSimulator=True,
        )

        logger.info(
            f"Simulated VIN decoded | vin={vin} | "
            f"vehicle={result.getVehicleSummary()}"
        )

        return result

    def _buildEngineDescription(self) -> str:
        """
        Build engine description string from profile.

        Returns:
            Engine description like "2.0L 4-cylinder"
        """
        return (
            f"{self.profile.engineDisplacementL}L "
            f"{self.profile.cylinders}-cylinder"
        )

    def _inferTransmission(self) -> str:
        """
        Infer transmission type from profile characteristics.

        Returns:
            "Manual" or "Automatic"
        """
        # Higher redline vehicles more likely to be manual sports cars
        if self.profile.redlineRpm >= 7000:
            return "Manual"
        return "Automatic"

    def _inferBodyClass(self) -> str:
        """
        Infer body class from profile model name.

        Returns:
            Body class string
        """
        modelLower = self.profile.model.lower()

        if any(term in modelLower for term in ['truck', 'pickup']):
            return "Truck"
        elif any(term in modelLower for term in ['suv', 'crossover']):
            return "SUV"
        elif any(term in modelLower for term in ['van', 'minivan']):
            return "Van"
        elif any(term in modelLower for term in ['coupe', 'convertible', 'gst', 'gsx']):
            return "Coupe"
        elif any(term in modelLower for term in ['hatchback', 'hatch']):
            return "Hatchback"
        else:
            return "Sedan"

    def getDecodedVin(self, vin: str) -> SimulatedVinDecodeResult | None:
        """
        Get previously decoded VIN data from cache.

        Does not regenerate from profile, only checks database cache.

        Args:
            vin: Vehicle Identification Number

        Returns:
            SimulatedVinDecodeResult if found in cache, None otherwise
        """
        return self._getFromCache(vin)

    def isVinCached(self, vin: str) -> bool:
        """
        Check if a VIN is already cached in the database.

        Args:
            vin: Vehicle Identification Number

        Returns:
            True if VIN is in the cache
        """
        if not self.database:
            return False

        try:
            with self.database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM vehicle_info WHERE vin = ?",
                    (vin,)
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
            'apiCalls': 0,  # No API calls in simulation
            'apiErrors': 0,
            'cacheHitRate': (
                self._cacheHits / self._totalDecodes
                if self._totalDecodes > 0 else 0.0
            ),
            'isSimulated': True,
        }

    def _getFromCache(self, vin: str) -> SimulatedVinDecodeResult | None:
        """
        Get decoded VIN data from database cache.

        Args:
            vin: VIN string

        Returns:
            SimulatedVinDecodeResult if found, None otherwise
        """
        if not self.database:
            return None

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
                    return SimulatedVinDecodeResult(
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
                        fromCache=True,
                        fromSimulator=True
                    )

                return None

        except Exception as e:
            logger.warning(f"Error reading from VIN cache: {e}")
            return None

    def _storeInCache(self, result: SimulatedVinDecodeResult) -> None:
        """
        Store decoded VIN data in database cache.

        Uses INSERT OR REPLACE to update existing records.

        Args:
            result: SimulatedVinDecodeResult to store

        Raises:
            SimulatedVinStorageError: If storage fails
        """
        if not self.database:
            return

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
                logger.debug(f"Cached simulated VIN decode result for: {result.vin}")

        except Exception as e:
            raise SimulatedVinStorageError(
                f"Failed to store simulated VIN data: {e}",
                details={'vin': result.vin, 'error': str(e)}
            ) from e


# ================================================================================
# Helper Functions
# ================================================================================

def createSimulatedVinDecoderFromConfig(
    config: dict[str, Any],
    database: Any | None = None,
    profile: VehicleProfile | None = None
) -> SimulatedVinDecoder:
    """
    Create a SimulatedVinDecoder from configuration.

    Args:
        config: Configuration dictionary
        database: ObdDatabase instance
        profile: Optional VehicleProfile (loads from config if not provided)

    Returns:
        Configured SimulatedVinDecoder instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        decoder = createSimulatedVinDecoderFromConfig(config, db)
    """
    # Load profile from config if not provided
    if profile is None:
        simConfig = config.get('simulator', {})
        profilePath = simConfig.get('profilePath', '')
        if profilePath:
            try:
                from .vehicle_profile import loadProfile
                profile = loadProfile(profilePath)
            except Exception as e:
                logger.warning(f"Failed to load profile from config: {e}")
                profile = getDefaultProfile()
        else:
            profile = getDefaultProfile()

    return SimulatedVinDecoder(profile, config, database)


def createVinDecoderForSimulation(
    profile: VehicleProfile,
    config: dict[str, Any] | None = None,
    database: Any | None = None
) -> SimulatedVinDecoder:
    """
    Create a VIN decoder for simulation mode.

    This is a convenience function that creates a SimulatedVinDecoder
    with the given profile.

    Args:
        profile: VehicleProfile with vehicle data
        config: Optional configuration dictionary
        database: Optional database instance

    Returns:
        SimulatedVinDecoder instance

    Example:
        profile = loadProfile('eclipse_gst.json')
        decoder = createVinDecoderForSimulation(profile)
        result = decoder.decodeVin()
    """
    return SimulatedVinDecoder(profile, config, database)


def isSimulatedDecodeResult(result: Any) -> bool:
    """
    Check if a VIN decode result is from the simulator.

    Args:
        result: VinDecodeResult or SimulatedVinDecodeResult

    Returns:
        True if result is from simulation
    """
    return (
        isinstance(result, SimulatedVinDecodeResult) or
        (hasattr(result, 'fromSimulator') and result.fromSimulator)
    )
