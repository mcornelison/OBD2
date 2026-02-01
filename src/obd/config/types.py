################################################################################
# File Name: types.py
# Purpose/Description: OBD-II configuration type definitions
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation (US-002)
# ================================================================================
################################################################################

"""
OBD-II Configuration type definitions.

Provides dataclasses and constants for OBD-II parameter definitions.
These types are used throughout the configuration system for type safety
and consistent data representation.

Usage:
    from src.obd.config.types import ParameterInfo, PARAMETER_CATEGORIES
"""

from dataclasses import dataclass

# =============================================================================
# Category Constants
# =============================================================================

CATEGORY_IDENTIFICATION = 'identification'
CATEGORY_FUEL = 'fuel'
CATEGORY_SYSTEM = 'system'
CATEGORY_DIAGNOSTICS = 'diagnostics'
CATEGORY_ENGINE = 'engine'
CATEGORY_TEMPERATURE = 'temperature'
CATEGORY_PRESSURE = 'pressure'
CATEGORY_AIRFUEL = 'airfuel'
CATEGORY_OXYGEN = 'oxygen'
CATEGORY_TIMING = 'timing'
CATEGORY_EGR = 'egr'
CATEGORY_EVAP = 'evap'
CATEGORY_DISTANCE = 'distance'
CATEGORY_TIME = 'time'
CATEGORY_ELECTRICAL = 'electrical'

# All valid parameter categories
PARAMETER_CATEGORIES = [
    CATEGORY_IDENTIFICATION,
    CATEGORY_FUEL,
    CATEGORY_SYSTEM,
    CATEGORY_DIAGNOSTICS,
    CATEGORY_ENGINE,
    CATEGORY_TEMPERATURE,
    CATEGORY_PRESSURE,
    CATEGORY_AIRFUEL,
    CATEGORY_OXYGEN,
    CATEGORY_TIMING,
    CATEGORY_EGR,
    CATEGORY_EVAP,
    CATEGORY_DISTANCE,
    CATEGORY_TIME,
    CATEGORY_ELECTRICAL,
]


# =============================================================================
# Type Definitions
# =============================================================================

@dataclass
class ParameterInfo:
    """
    Information about an OBD-II parameter.

    Attributes:
        name: Parameter name (e.g., 'RPM', 'COOLANT_TEMP')
        description: Human-readable description
        unit: Unit of measurement (e.g., 'rpm', '°C', '%') or None
        category: Parameter category (e.g., 'engine', 'temperature')
        isStatic: True if queried once per vehicle, False if realtime
        defaultLogData: True if parameter should be logged by default
    """

    name: str
    description: str
    unit: str | None
    category: str
    isStatic: bool
    defaultLogData: bool = False

    def toDict(self) -> dict:
        """
        Convert to dictionary representation.

        Returns:
            Dictionary with all parameter fields
        """
        return {
            'name': self.name,
            'description': self.description,
            'unit': self.unit,
            'category': self.category,
            'isStatic': self.isStatic,
            'defaultLogData': self.defaultLogData
        }
