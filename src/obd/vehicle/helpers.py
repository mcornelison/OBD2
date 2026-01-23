################################################################################
# File Name: helpers.py
# Purpose/Description: Vehicle-related factory and helper functions
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
Vehicle helper functions module.

Provides factory functions and convenience helpers for:
- VIN decoder creation
- Static data collector creation
- VIN validation and lookup
- Static data verification
"""

import logging
from typing import Any, Dict, Optional

from .types import VinDecodeResult, CollectionResult
from .vin_decoder import VinDecoder
from .static_collector import StaticDataCollector

logger = logging.getLogger(__name__)


# ================================================================================
# VIN Decoder Helpers
# ================================================================================

def createVinDecoderFromConfig(
    config: Dict[str, Any],
    database: Any
) -> VinDecoder:
    """
    Create a VinDecoder from configuration.

    Args:
        config: Configuration dictionary with 'vinDecoder' section
        database: ObdDatabase instance

    Returns:
        Configured VinDecoder instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        decoder = createVinDecoderFromConfig(config, db)
    """
    return VinDecoder(config, database)


def decodeVinOnFirstConnection(
    vin: str,
    config: Dict[str, Any],
    database: Any
) -> VinDecodeResult:
    """
    Convenience function to decode VIN on first connection.

    Creates a VinDecoder and decodes the given VIN. Uses cache
    if available.

    Args:
        vin: Vehicle Identification Number
        config: Configuration dictionary
        database: ObdDatabase instance

    Returns:
        VinDecodeResult with vehicle information

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)

        result = decodeVinOnFirstConnection('1G1YY22G965104378', config, db)
        if result.success:
            print(f"Vehicle: {result.getVehicleSummary()}")
    """
    decoder = VinDecoder(config, database)
    return decoder.decodeVin(vin)


def isVinDecoderEnabled(config: Dict[str, Any]) -> bool:
    """
    Check if VIN decoder is enabled in configuration.

    Args:
        config: Configuration dictionary

    Returns:
        True if VIN decoder is enabled
    """
    vinConfig = config.get('vinDecoder', {})
    return vinConfig.get('enabled', True)


def getVehicleInfo(database: Any, vin: str) -> Optional[Dict[str, Any]]:
    """
    Get stored vehicle information from database.

    Args:
        database: ObdDatabase instance
        vin: Vehicle Identification Number

    Returns:
        Dictionary with vehicle info or None if not found
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT vin, make, model, year, engine, fuel_type,
                       transmission, drive_type, body_class,
                       plant_city, plant_country, created_at, updated_at
                FROM vehicle_info
                WHERE vin = ?
                """,
                (vin.strip().upper(),)
            )
            row = cursor.fetchone()

            if row:
                return {
                    'vin': row[0],
                    'make': row[1],
                    'model': row[2],
                    'year': row[3],
                    'engine': row[4],
                    'fuelType': row[5],
                    'transmission': row[6],
                    'driveType': row[7],
                    'bodyClass': row[8],
                    'plantCity': row[9],
                    'plantCountry': row[10],
                    'createdAt': row[11],
                    'updatedAt': row[12],
                }

            return None

    except Exception as e:
        logger.error(f"Error getting vehicle info: {e}")
        return None


def validateVinFormat(vin: str) -> bool:
    """
    Validate VIN format.

    Args:
        vin: Vehicle Identification Number

    Returns:
        True if VIN format is valid (17 characters, valid chars)
    """
    normalizedVin = vin.strip().upper().replace(' ', '').replace('-', '')

    if len(normalizedVin) != 17:
        return False

    # VINs can only contain specific characters (no I, O, Q)
    validChars = set('ABCDEFGHJKLMNPRSTUVWXYZ0123456789')
    return all(c in validChars for c in normalizedVin)


# ================================================================================
# Static Data Collector Helpers
# ================================================================================

def createStaticDataCollectorFromConfig(
    config: Dict[str, Any],
    connection: Any,
    database: Any
) -> StaticDataCollector:
    """
    Create a StaticDataCollector from configuration.

    Args:
        config: Configuration dictionary with 'staticData' section
        connection: ObdConnection instance
        database: ObdDatabase instance

    Returns:
        Configured StaticDataCollector instance

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)

        collector = createStaticDataCollectorFromConfig(config, conn, db)
    """
    return StaticDataCollector(config, connection, database)


def collectStaticDataOnFirstConnection(
    config: Dict[str, Any],
    connection: Any,
    database: Any
) -> CollectionResult:
    """
    Convenience function to collect static data on first connection.

    Creates a StaticDataCollector and collects static data if needed.

    Args:
        config: Configuration dictionary
        connection: ObdConnection instance
        database: ObdDatabase instance

    Returns:
        CollectionResult with collection details

    Example:
        config = loadObdConfig('obd_config.json')
        db = initializeDatabase(config)
        conn = createConnectionFromConfig(config, db)
        conn.connect()

        result = collectStaticDataOnFirstConnection(config, conn, db)
        if result.success:
            print(f"Collected {result.parametersCollected} parameters")
    """
    collector = StaticDataCollector(config, connection, database)

    if collector.shouldCollectStaticData():
        return collector.collectStaticData()
    else:
        result = CollectionResult()
        result.success = True
        result.wasSkipped = True
        return result


def verifyStaticDataExists(database: Any, vin: str) -> bool:
    """
    Verify that static data exists for a VIN.

    Args:
        database: ObdDatabase instance
        vin: Vehicle Identification Number

    Returns:
        True if static data exists for the VIN
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM static_data WHERE vin = ?",
                (vin,)
            )
            count = cursor.fetchone()[0]
            return count > 0
    except Exception as e:
        logger.error(f"Error verifying static data: {e}")
        return False


def getStaticDataCount(database: Any, vin: str) -> int:
    """
    Get the count of static data records for a VIN.

    Args:
        database: ObdDatabase instance
        vin: Vehicle Identification Number

    Returns:
        Number of static data records
    """
    try:
        with database.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM static_data WHERE vin = ?",
                (vin,)
            )
            return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"Error getting static data count: {e}")
        return 0
