################################################################################
# File Name: __init__.py
# Purpose/Description: OBD-II Simulator package initialization
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
OBD-II Simulator Package.

This package provides simulation capabilities for testing the Eclipse OBD-II
system without actual vehicle hardware.

Modules:
- vehicle_profile: Vehicle configuration dataclass and loading functions

Usage:
    from obd.simulator import VehicleProfile, loadProfile, getDefaultProfile
"""

from .vehicle_profile import (
    VehicleProfile,
    VehicleProfileError,
    VehicleProfileLoadError,
    VehicleProfileValidationError,
    loadProfile,
    getDefaultProfile,
    getProfilesDirectory,
    getDefaultProfilePath,
    loadDefaultProfileFromFile,
    listAvailableProfiles,
    saveProfile,
    createProfileFromConfig,
    VALID_FUEL_TYPES,
)

__all__ = [
    "VehicleProfile",
    "VehicleProfileError",
    "VehicleProfileLoadError",
    "VehicleProfileValidationError",
    "loadProfile",
    "getDefaultProfile",
    "getProfilesDirectory",
    "getDefaultProfilePath",
    "loadDefaultProfileFromFile",
    "listAvailableProfiles",
    "saveProfile",
    "createProfileFromConfig",
    "VALID_FUEL_TYPES",
]
