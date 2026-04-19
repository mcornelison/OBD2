################################################################################
# File Name: types.py
# Purpose/Description: Vehicle-related types and dataclasses
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
Vehicle types module.

Contains dataclasses and types for vehicle information handling:
- VinDecodeResult: Result of VIN decoding operations
- ApiCallResult: Result of NHTSA API calls
- StaticReading: Individual static parameter reading
- CollectionResult: Result of static data collection
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ================================================================================
# VIN Decoder Types
# ================================================================================

@dataclass
class VinDecodeResult:
    """
    Result of a VIN decode operation.

    Attributes:
        vin: The VIN that was decoded
        success: Whether the decode was successful
        make: Vehicle manufacturer
        model: Vehicle model
        year: Model year
        engine: Engine model/type
        fuelType: Primary fuel type
        transmission: Transmission style
        driveType: Drive type (FWD, RWD, AWD, etc.)
        bodyClass: Body class (Sedan, SUV, etc.)
        plantCity: Manufacturing plant city
        plantCountry: Manufacturing plant country
        rawResponse: Raw API response (JSON string)
        fromCache: True if result came from database cache
        errorMessage: Error message if decode failed
        errorCode: NHTSA error code if applicable
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
    errorMessage: str | None = None
    errorCode: str | None = None

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
            'errorMessage': self.errorMessage,
            'errorCode': self.errorCode,
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


@dataclass
class ApiCallResult:
    """
    Result of a NHTSA API call.

    Attributes:
        success: Whether the API call succeeded
        data: Parsed JSON response data
        statusCode: HTTP status code
        errorMessage: Error message if call failed
    """
    success: bool = False
    data: dict[str, Any] | None = None
    statusCode: int | None = None
    errorMessage: str | None = None


# ================================================================================
# Static Data Collector Types
# ================================================================================

@dataclass
class StaticReading:
    """
    Represents a static OBD-II parameter reading.

    Attributes:
        parameterName: Name of the OBD-II parameter (e.g., 'VIN', 'FUEL_TYPE')
        value: String value of the reading (or None if unavailable)
        queriedAt: When the reading was taken
        unit: Unit of measurement (optional)
    """
    parameterName: str
    value: str | None
    queriedAt: datetime
    unit: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert reading to dictionary for serialization."""
        return {
            'parameterName': self.parameterName,
            'value': self.value,
            'unit': self.unit,
            'queriedAt': self.queriedAt.isoformat() if self.queriedAt else None
        }


@dataclass
class CollectionResult:
    """
    Result of a static data collection operation.

    Attributes:
        vin: The vehicle VIN that was collected for
        success: Whether the collection was successful
        parametersCollected: Number of parameters successfully collected
        parametersUnavailable: Number of parameters that were unavailable
        readings: List of StaticReading objects
        errorMessage: Error message if collection failed
        wasSkipped: True if collection was skipped (VIN already exists)
    """
    vin: str | None = None
    success: bool = False
    parametersCollected: int = 0
    parametersUnavailable: int = 0
    readings: list[StaticReading] = field(default_factory=list)
    errorMessage: str | None = None
    wasSkipped: bool = False

    def toDict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            'vin': self.vin,
            'success': self.success,
            'parametersCollected': self.parametersCollected,
            'parametersUnavailable': self.parametersUnavailable,
            'readings': [r.toDict() for r in self.readings],
            'errorMessage': self.errorMessage,
            'wasSkipped': self.wasSkipped
        }
