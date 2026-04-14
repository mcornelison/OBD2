################################################################################
# File Name: vehicle_profile.py
# Purpose/Description: Vehicle profile dataclass for OBD-II simulator
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-035
# ================================================================================
################################################################################

"""
Vehicle profile module for the Eclipse OBD-II simulator.

Provides:
- VehicleProfile dataclass representing vehicle configuration
- loadProfile() function for loading profiles from JSON files
- getDefaultProfile() function for a generic 4-cylinder vehicle

Vehicle profiles define vehicle-specific characteristics used by the simulator
to generate realistic OBD-II sensor values including:
- Engine specs (displacement, cylinders, RPM ranges)
- Fuel type configuration
- Sensor limits and operating ranges

Usage:
    from obd.simulator.vehicle_profile import (
        VehicleProfile, loadProfile, getDefaultProfile
    )

    # Load custom profile
    profile = loadProfile('path/to/eclipse.json')

    # Or use default
    profile = getDefaultProfile()

    # Access properties
    print(f"Vehicle: {profile.year} {profile.make} {profile.model}")
    print(f"Redline: {profile.redlineRpm} RPM")
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Default values for a generic 4-cylinder gasoline vehicle
DEFAULT_VIN = "1HGBH41JXMN109186"
DEFAULT_MAKE = "Generic"
DEFAULT_MODEL = "Sedan"
DEFAULT_YEAR = 2020
DEFAULT_ENGINE_DISPLACEMENT_L = 2.0
DEFAULT_CYLINDERS = 4
DEFAULT_FUEL_TYPE = "Gasoline"
DEFAULT_MAX_RPM = 7000
DEFAULT_REDLINE_RPM = 6500
DEFAULT_IDLE_RPM = 800
DEFAULT_MAX_SPEED_KPH = 240
DEFAULT_NORMAL_COOLANT_TEMP_C = 90
DEFAULT_MAX_COOLANT_TEMP_C = 120

# Supported fuel types
VALID_FUEL_TYPES = frozenset([
    "Gasoline",
    "Diesel",
    "Electric",
    "Hybrid",
    "E85",
    "CNG",
    "LPG",
])


# ================================================================================
# Custom Exceptions
# ================================================================================

class VehicleProfileError(Exception):
    """Base exception for vehicle profile errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class VehicleProfileLoadError(VehicleProfileError):
    """Error loading vehicle profile from file."""

    def __init__(self, message: str, filePath: str,
                 details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.filePath = filePath


class VehicleProfileValidationError(VehicleProfileError):
    """Error validating vehicle profile data."""

    def __init__(self, message: str, invalidFields: list | None = None,
                 details: dict[str, Any] | None = None):
        super().__init__(message, details)
        self.invalidFields = invalidFields or []


# ================================================================================
# VehicleProfile Dataclass
# ================================================================================

@dataclass
class VehicleProfile:
    """
    Dataclass representing a vehicle configuration for simulation.

    This profile defines vehicle-specific characteristics used to generate
    realistic OBD-II sensor values during simulation.

    Attributes:
        vin: Vehicle Identification Number (17 characters)
        make: Vehicle manufacturer (e.g., "Toyota", "Ford")
        model: Vehicle model name (e.g., "Camry", "Mustang")
        year: Model year (e.g., 2020)
        engineDisplacementL: Engine displacement in liters (e.g., 2.0)
        cylinders: Number of engine cylinders (e.g., 4, 6, 8)
        fuelType: Fuel type (e.g., "Gasoline", "Diesel")
        maxRpm: Maximum safe RPM before engine damage
        redlineRpm: RPM redline (start of danger zone)
        idleRpm: Normal idle RPM when engine is warm
        maxSpeedKph: Maximum vehicle speed in km/h
        normalCoolantTempC: Normal operating coolant temperature in Celsius
        maxCoolantTempC: Maximum safe coolant temperature in Celsius
    """

    vin: str = DEFAULT_VIN
    make: str = DEFAULT_MAKE
    model: str = DEFAULT_MODEL
    year: int = DEFAULT_YEAR
    engineDisplacementL: float = DEFAULT_ENGINE_DISPLACEMENT_L
    cylinders: int = DEFAULT_CYLINDERS
    fuelType: str = DEFAULT_FUEL_TYPE
    maxRpm: int = DEFAULT_MAX_RPM
    redlineRpm: int = DEFAULT_REDLINE_RPM
    idleRpm: int = DEFAULT_IDLE_RPM
    maxSpeedKph: int = DEFAULT_MAX_SPEED_KPH
    normalCoolantTempC: int = DEFAULT_NORMAL_COOLANT_TEMP_C
    maxCoolantTempC: int = DEFAULT_MAX_COOLANT_TEMP_C

    def __post_init__(self) -> None:
        """Validate profile data after initialization."""
        self._validate()

    def _validate(self) -> None:
        """
        Validate all profile fields.

        Raises:
            VehicleProfileValidationError: If any field is invalid
        """
        invalidFields = []

        # Validate VIN (17 alphanumeric characters, no I, O, Q)
        if not self._validateVin(self.vin):
            invalidFields.append("vin")

        # Validate year (reasonable range)
        if not (1900 <= self.year <= 2100):
            invalidFields.append("year")

        # Validate engine displacement (positive)
        if self.engineDisplacementL <= 0:
            invalidFields.append("engineDisplacementL")

        # Validate cylinders (positive, reasonable range)
        if not (1 <= self.cylinders <= 16):
            invalidFields.append("cylinders")

        # Validate fuel type
        if self.fuelType not in VALID_FUEL_TYPES:
            invalidFields.append("fuelType")

        # Validate RPM values (positive, logical ordering)
        if self.idleRpm < 0:
            invalidFields.append("idleRpm")
        if self.redlineRpm <= self.idleRpm:
            invalidFields.append("redlineRpm")
        if self.maxRpm < self.redlineRpm:
            invalidFields.append("maxRpm")

        # Validate speed (positive)
        if self.maxSpeedKph <= 0:
            invalidFields.append("maxSpeedKph")

        # Validate temperatures (logical ordering)
        if self.normalCoolantTempC <= 0:
            invalidFields.append("normalCoolantTempC")
        if self.maxCoolantTempC <= self.normalCoolantTempC:
            invalidFields.append("maxCoolantTempC")

        if invalidFields:
            raise VehicleProfileValidationError(
                f"Invalid vehicle profile fields: {', '.join(invalidFields)}",
                invalidFields=invalidFields
            )

    @staticmethod
    def _validateVin(vin: str) -> bool:
        """
        Validate a VIN string.

        Args:
            vin: Vehicle Identification Number to validate

        Returns:
            True if VIN is valid, False otherwise
        """
        if not isinstance(vin, str):
            return False

        # Clean and normalize VIN
        cleanedVin = vin.upper().strip().replace("-", "").replace(" ", "")

        # Check length
        if len(cleanedVin) != 17:
            return False

        # Check alphanumeric
        if not cleanedVin.isalnum():
            return False

        # Check excluded characters (I, O, Q)
        excludedChars = set("IOQ")
        if any(c in excludedChars for c in cleanedVin):
            return False

        return True

    def toDict(self) -> dict[str, Any]:
        """
        Convert profile to dictionary.

        Returns:
            Dictionary representation of the profile
        """
        return {
            "vin": self.vin,
            "make": self.make,
            "model": self.model,
            "year": self.year,
            "engineDisplacementL": self.engineDisplacementL,
            "cylinders": self.cylinders,
            "fuelType": self.fuelType,
            "maxRpm": self.maxRpm,
            "redlineRpm": self.redlineRpm,
            "idleRpm": self.idleRpm,
            "maxSpeedKph": self.maxSpeedKph,
            "normalCoolantTempC": self.normalCoolantTempC,
            "maxCoolantTempC": self.maxCoolantTempC,
        }

    @classmethod
    def fromDict(cls, data: dict[str, Any]) -> "VehicleProfile":
        """
        Create a VehicleProfile from a dictionary.

        Args:
            data: Dictionary containing profile fields

        Returns:
            New VehicleProfile instance

        Raises:
            VehicleProfileValidationError: If data is invalid
        """
        try:
            return cls(
                vin=data.get("vin", DEFAULT_VIN),
                make=data.get("make", DEFAULT_MAKE),
                model=data.get("model", DEFAULT_MODEL),
                year=data.get("year", DEFAULT_YEAR),
                engineDisplacementL=data.get(
                    "engineDisplacementL", DEFAULT_ENGINE_DISPLACEMENT_L
                ),
                cylinders=data.get("cylinders", DEFAULT_CYLINDERS),
                fuelType=data.get("fuelType", DEFAULT_FUEL_TYPE),
                maxRpm=data.get("maxRpm", DEFAULT_MAX_RPM),
                redlineRpm=data.get("redlineRpm", DEFAULT_REDLINE_RPM),
                idleRpm=data.get("idleRpm", DEFAULT_IDLE_RPM),
                maxSpeedKph=data.get("maxSpeedKph", DEFAULT_MAX_SPEED_KPH),
                normalCoolantTempC=data.get(
                    "normalCoolantTempC", DEFAULT_NORMAL_COOLANT_TEMP_C
                ),
                maxCoolantTempC=data.get(
                    "maxCoolantTempC", DEFAULT_MAX_COOLANT_TEMP_C
                ),
            )
        except VehicleProfileValidationError:
            raise
        except Exception as e:
            raise VehicleProfileValidationError(
                f"Failed to create profile from dictionary: {e}"
            ) from e

    def __str__(self) -> str:
        """Return human-readable string representation."""
        return (
            f"{self.year} {self.make} {self.model} "
            f"({self.engineDisplacementL}L {self.cylinders}-cyl {self.fuelType})"
        )


# ================================================================================
# Profile Loading Functions
# ================================================================================

def loadProfile(path: str) -> VehicleProfile:
    """
    Load a vehicle profile from a JSON file.

    Args:
        path: Path to the JSON profile file

    Returns:
        VehicleProfile instance loaded from file

    Raises:
        VehicleProfileLoadError: If file cannot be read or parsed
        VehicleProfileValidationError: If profile data is invalid
    """
    logger.debug(f"Loading vehicle profile from: {path}")

    # Check file exists
    if not os.path.isfile(path):
        raise VehicleProfileLoadError(
            f"Profile file not found: {path}",
            filePath=path
        )

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise VehicleProfileLoadError(
            f"Invalid JSON in profile file: {e}",
            filePath=path,
            details={"error": str(e)}
        ) from e
    except OSError as e:
        raise VehicleProfileLoadError(
            f"Failed to read profile file: {e}",
            filePath=path,
            details={"error": str(e)}
        ) from e

    if not isinstance(data, dict):
        raise VehicleProfileLoadError(
            "Profile file must contain a JSON object",
            filePath=path
        )

    profile = VehicleProfile.fromDict(data)
    logger.info(f"Loaded vehicle profile: {profile}")
    return profile


def getDefaultProfile() -> VehicleProfile:
    """
    Get a default vehicle profile for a generic 4-cylinder gasoline vehicle.

    This profile represents a typical modern sedan with conservative
    specifications suitable for general simulation.

    Returns:
        VehicleProfile with default values
    """
    return VehicleProfile()


def getProfilesDirectory() -> str:
    """
    Get the path to the profiles directory.

    Returns:
        Absolute path to the profiles directory
    """
    moduleDir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(moduleDir, "profiles")


def getDefaultProfilePath() -> str:
    """
    Get the path to the default.json profile file.

    Returns:
        Absolute path to default.json
    """
    return os.path.join(getProfilesDirectory(), "default.json")


def loadDefaultProfileFromFile() -> VehicleProfile:
    """
    Load the default profile from the default.json file.

    Falls back to getDefaultProfile() if file doesn't exist.

    Returns:
        VehicleProfile from default.json or default values
    """
    defaultPath = getDefaultProfilePath()

    try:
        return loadProfile(defaultPath)
    except VehicleProfileLoadError as e:
        logger.warning(
            f"Could not load default.json, using built-in defaults: {e.message}"
        )
        return getDefaultProfile()


def listAvailableProfiles() -> list:
    """
    List all available profile files in the profiles directory.

    Returns:
        List of profile filenames (without path)
    """
    profilesDir = getProfilesDirectory()

    if not os.path.isdir(profilesDir):
        return []

    profiles = []
    for filename in os.listdir(profilesDir):
        if filename.endswith(".json"):
            profiles.append(filename)

    return sorted(profiles)


def saveProfile(profile: VehicleProfile, path: str) -> None:
    """
    Save a vehicle profile to a JSON file.

    Args:
        profile: VehicleProfile to save
        path: Destination file path

    Raises:
        VehicleProfileError: If file cannot be written
    """
    logger.debug(f"Saving vehicle profile to: {path}")

    try:
        # Ensure directory exists
        directory = os.path.dirname(path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile.toDict(), f, indent=2)
            f.write("\n")

        logger.info(f"Saved vehicle profile: {profile} to {path}")
    except OSError as e:
        raise VehicleProfileError(
            f"Failed to save profile: {e}",
            details={"path": path, "error": str(e)}
        ) from e


# ================================================================================
# Helper Functions
# ================================================================================

def createProfileFromConfig(config: dict[str, Any]) -> VehicleProfile:
    """
    Create a VehicleProfile from a config dictionary.

    This helper is useful when profile data is embedded in
    a larger configuration structure.

    Args:
        config: Dictionary containing profile data (may be nested under
                'simulator.profile' or 'profile')

    Returns:
        VehicleProfile instance
    """
    # Try nested paths first
    profileData = config.get("simulator", {}).get("profile", {})
    if not profileData:
        profileData = config.get("profile", {})
    if not profileData:
        profileData = config

    return VehicleProfile.fromDict(profileData)
