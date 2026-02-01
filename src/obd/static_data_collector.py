################################################################################
# File Name: static_data_collector.py
# Purpose/Description: Static data collection and storage on first connection
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-011
# 2026-01-22    | Ralph Agent  | Refactored - now re-exports from vehicle subpackage (US-008)
# ================================================================================
################################################################################

"""
Static data collection module for the Eclipse OBD-II system.

This module re-exports all functionality from the obd.vehicle subpackage
for backward compatibility. New code should import directly from obd.vehicle.

Provides:
- Static parameter querying on first connection
- VIN-based existence checking to avoid duplicate queries
- Storage in static_data table with VIN as foreign key
- Graceful handling of unavailable parameters (stored as NULL)

Usage:
    from obd.static_data_collector import StaticDataCollector  # Legacy - still works
    # OR preferred:
    from obd.vehicle import StaticDataCollector

    # Create collector with connection and database
    collector = StaticDataCollector(config, connection, database)

    # Collect static data (checks VIN first)
    result = collector.collectStaticData()

    # Or check and collect only if new
    if collector.shouldCollectStaticData():
        collector.collectStaticData()
"""

# Re-export everything from the vehicle subpackage for backward compatibility
from obd.vehicle import (
    # Types
    StaticReading,
    CollectionResult,
    # Exceptions
    StaticDataError,
    VinNotAvailableError,
    StaticDataStorageError,
    # Classes
    StaticDataCollector,
    # Helpers
    createStaticDataCollectorFromConfig,
    collectStaticDataOnFirstConnection,
    verifyStaticDataExists,
    getStaticDataCount,
)

__all__ = [
    # Types
    'StaticReading',
    'CollectionResult',
    # Exceptions
    'StaticDataError',
    'VinNotAvailableError',
    'StaticDataStorageError',
    # Classes
    'StaticDataCollector',
    # Helpers
    'createStaticDataCollectorFromConfig',
    'collectStaticDataOnFirstConnection',
    'verifyStaticDataExists',
    'getStaticDataCount',
]
