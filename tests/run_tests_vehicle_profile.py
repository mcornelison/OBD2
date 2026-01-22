#!/usr/bin/env python3
################################################################################
# File Name: run_tests_vehicle_profile.py
# Purpose/Description: Manual test runner for vehicle profile module tests
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
Manual test runner for vehicle profile module tests.

Run with:
    python tests/run_tests_vehicle_profile.py
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.simulator.vehicle_profile import (
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
    DEFAULT_VIN,
    DEFAULT_MAKE,
    DEFAULT_MODEL,
    DEFAULT_YEAR,
)


class TestRunner:
    """Simple test runner for manual execution."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def runTest(self, testName: str, testFunc):
        """Run a single test and track results."""
        try:
            testFunc()
            self.passed += 1
            print(f"  [PASS] {testName}")
        except AssertionError as e:
            self.failed += 1
            self.errors.append((testName, str(e)))
            print(f"  [FAIL] {testName}: {e}")
        except Exception as e:
            self.failed += 1
            self.errors.append((testName, f"Error: {e}"))
            print(f"  [ERROR] {testName}: {e}")
            traceback.print_exc()

    def report(self):
        """Print final test report."""
        total = self.passed + self.failed
        print(f"\n{'=' * 60}")
        print(f"Results: {self.passed} passed, {self.failed} failed, {total} total")
        if self.errors:
            print("\nFailures:")
            for name, error in self.errors:
                print(f"  - {name}: {error}")
        return self.failed == 0


def getTempFilePath(suffix=".json"):
    """Get a temporary file path."""
    return tempfile.mktemp(suffix=suffix)


def createTempProfileFile(data: dict) -> str:
    """Create a temporary profile file with given data."""
    path = getTempFilePath()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def cleanupTempFile(path: str) -> None:
    """Remove a temporary file if it exists."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# ================================================================================
# VehicleProfile Dataclass Tests
# ================================================================================

def test_vehicleProfile_defaultValues_createsValidProfile():
    """
    Given: No arguments
    When: Creating a VehicleProfile
    Then: Uses default values and creates valid profile
    """
    profile = VehicleProfile()
    assert profile.vin == DEFAULT_VIN
    assert profile.make == DEFAULT_MAKE
    assert profile.model == DEFAULT_MODEL
    assert profile.year == DEFAULT_YEAR
    assert profile.engineDisplacementL == 2.0
    assert profile.cylinders == 4
    assert profile.fuelType == "Gasoline"
    assert profile.maxRpm == 7000
    assert profile.redlineRpm == 6500
    assert profile.idleRpm == 800
    assert profile.maxSpeedKph == 240
    assert profile.normalCoolantTempC == 90
    assert profile.maxCoolantTempC == 120


def test_vehicleProfile_customValues_createsProfile():
    """
    Given: Custom values
    When: Creating a VehicleProfile
    Then: Uses provided values
    """
    profile = VehicleProfile(
        vin="4A3AK44Y4WE068213",
        make="Mitsubishi",
        model="Eclipse GST",
        year=1998,
        engineDisplacementL=2.0,
        cylinders=4,
        fuelType="Gasoline",
        maxRpm=7500,
        redlineRpm=7000,
        idleRpm=850,
        maxSpeedKph=230,
        normalCoolantTempC=88,
        maxCoolantTempC=115,
    )
    assert profile.make == "Mitsubishi"
    assert profile.model == "Eclipse GST"
    assert profile.year == 1998
    assert profile.redlineRpm == 7000


def test_vehicleProfile_invalidVin_raisesError():
    """
    Given: Invalid VIN (too short)
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(vin="ABC123")
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "vin" in e.invalidFields


def test_vehicleProfile_vinWithExcludedChars_raisesError():
    """
    Given: VIN containing I, O, or Q
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        # VIN with 'I' (excluded character)
        VehicleProfile(vin="1HGBH41IXMN109186")
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "vin" in e.invalidFields


def test_vehicleProfile_invalidYear_raisesError():
    """
    Given: Year outside valid range
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(year=1800)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "year" in e.invalidFields


def test_vehicleProfile_negativeDisplacement_raisesError():
    """
    Given: Negative engine displacement
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(engineDisplacementL=-2.0)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "engineDisplacementL" in e.invalidFields


def test_vehicleProfile_invalidCylinders_raisesError():
    """
    Given: Invalid cylinder count (0 or > 16)
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(cylinders=0)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "cylinders" in e.invalidFields


def test_vehicleProfile_invalidFuelType_raisesError():
    """
    Given: Invalid fuel type
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(fuelType="Nuclear")
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "fuelType" in e.invalidFields


def test_vehicleProfile_redlineGreaterThanMaxRpm_raisesError():
    """
    Given: Redline RPM greater than max RPM
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(maxRpm=6000, redlineRpm=7000)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "maxRpm" in e.invalidFields


def test_vehicleProfile_idleGreaterThanRedline_raisesError():
    """
    Given: Idle RPM greater than or equal to redline
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(idleRpm=7000, redlineRpm=6500)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "redlineRpm" in e.invalidFields


def test_vehicleProfile_invalidTemperatureOrder_raisesError():
    """
    Given: Max coolant temp <= normal coolant temp
    When: Creating a VehicleProfile
    Then: Raises VehicleProfileValidationError
    """
    try:
        VehicleProfile(normalCoolantTempC=100, maxCoolantTempC=90)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "maxCoolantTempC" in e.invalidFields


def test_vehicleProfile_toDict_returnsCorrectKeys():
    """
    Given: A VehicleProfile
    When: Converting to dictionary
    Then: Contains all expected keys
    """
    profile = VehicleProfile()
    data = profile.toDict()
    expectedKeys = {
        "vin", "make", "model", "year", "engineDisplacementL",
        "cylinders", "fuelType", "maxRpm", "redlineRpm", "idleRpm",
        "maxSpeedKph", "normalCoolantTempC", "maxCoolantTempC"
    }
    assert set(data.keys()) == expectedKeys


def test_vehicleProfile_fromDict_createsValidProfile():
    """
    Given: A valid dictionary
    When: Creating profile from dict
    Then: Creates profile with correct values
    """
    data = {
        "vin": "4A3AK44Y4WE068213",
        "make": "Mitsubishi",
        "model": "Eclipse",
        "year": 1998,
    }
    profile = VehicleProfile.fromDict(data)
    assert profile.make == "Mitsubishi"
    assert profile.year == 1998
    # Uses defaults for missing fields
    assert profile.cylinders == 4


def test_vehicleProfile_fromDict_emptyDict_usesDefaults():
    """
    Given: An empty dictionary
    When: Creating profile from dict
    Then: Uses all default values
    """
    profile = VehicleProfile.fromDict({})
    assert profile.make == DEFAULT_MAKE
    assert profile.model == DEFAULT_MODEL


def test_vehicleProfile_str_returnsReadableString():
    """
    Given: A VehicleProfile
    When: Converting to string
    Then: Returns human-readable format
    """
    profile = VehicleProfile(
        make="Toyota",
        model="Camry",
        year=2022,
        engineDisplacementL=2.5,
        cylinders=4,
        fuelType="Gasoline",
    )
    result = str(profile)
    assert "Toyota" in result
    assert "Camry" in result
    assert "2022" in result
    assert "2.5L" in result
    assert "4-cyl" in result


def test_vehicleProfile_validFuelTypes():
    """
    Given: Each valid fuel type
    When: Creating profiles
    Then: All are accepted
    """
    for fuelType in VALID_FUEL_TYPES:
        profile = VehicleProfile(fuelType=fuelType)
        assert profile.fuelType == fuelType


def test_vehicleProfile_multipleInvalidFields_reportsAll():
    """
    Given: Multiple invalid fields
    When: Creating a VehicleProfile
    Then: Reports all invalid fields in error
    """
    try:
        VehicleProfile(
            vin="INVALID",
            year=1800,
            cylinders=0,
            fuelType="Water",
        )
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError as e:
        assert "vin" in e.invalidFields
        assert "year" in e.invalidFields
        assert "cylinders" in e.invalidFields
        assert "fuelType" in e.invalidFields


# ================================================================================
# loadProfile Tests
# ================================================================================

def test_loadProfile_validFile_returnsProfile():
    """
    Given: A valid JSON profile file
    When: Loading the profile
    Then: Returns VehicleProfile with correct values
    """
    data = {
        "vin": "4A3AK44Y4WE068213",
        "make": "Mitsubishi",
        "model": "Eclipse",
        "year": 1998,
    }
    path = createTempProfileFile(data)
    try:
        profile = loadProfile(path)
        assert profile.make == "Mitsubishi"
        assert profile.year == 1998
    finally:
        cleanupTempFile(path)


def test_loadProfile_fileNotFound_raisesError():
    """
    Given: A non-existent file path
    When: Loading the profile
    Then: Raises VehicleProfileLoadError
    """
    try:
        loadProfile("/nonexistent/path/profile.json")
        assert False, "Should have raised VehicleProfileLoadError"
    except VehicleProfileLoadError as e:
        assert "not found" in e.message.lower()


def test_loadProfile_invalidJson_raisesError():
    """
    Given: A file with invalid JSON
    When: Loading the profile
    Then: Raises VehicleProfileLoadError
    """
    path = getTempFilePath()
    try:
        with open(path, "w") as f:
            f.write("{ invalid json }")
        loadProfile(path)
        assert False, "Should have raised VehicleProfileLoadError"
    except VehicleProfileLoadError as e:
        assert "invalid json" in e.message.lower()
    finally:
        cleanupTempFile(path)


def test_loadProfile_invalidData_raisesValidationError():
    """
    Given: Valid JSON with invalid profile data
    When: Loading the profile
    Then: Raises VehicleProfileValidationError
    """
    data = {"vin": "INVALID", "year": 1000}
    path = createTempProfileFile(data)
    try:
        loadProfile(path)
        assert False, "Should have raised VehicleProfileValidationError"
    except VehicleProfileValidationError:
        pass  # Expected
    finally:
        cleanupTempFile(path)


def test_loadProfile_notObject_raisesError():
    """
    Given: JSON that is not an object (e.g., array)
    When: Loading the profile
    Then: Raises VehicleProfileLoadError
    """
    path = getTempFilePath()
    try:
        with open(path, "w") as f:
            f.write("[1, 2, 3]")
        loadProfile(path)
        assert False, "Should have raised VehicleProfileLoadError"
    except VehicleProfileLoadError as e:
        assert "object" in e.message.lower()
    finally:
        cleanupTempFile(path)


# ================================================================================
# getDefaultProfile Tests
# ================================================================================

def test_getDefaultProfile_returnsValidProfile():
    """
    Given: No arguments
    When: Getting default profile
    Then: Returns a valid VehicleProfile with default values
    """
    profile = getDefaultProfile()
    assert isinstance(profile, VehicleProfile)
    assert profile.make == "Generic"
    assert profile.model == "Sedan"
    assert profile.cylinders == 4
    assert profile.fuelType == "Gasoline"


def test_getDefaultProfile_isRepeatable():
    """
    Given: Multiple calls
    When: Getting default profile
    Then: Returns identical values each time
    """
    profile1 = getDefaultProfile()
    profile2 = getDefaultProfile()
    assert profile1.toDict() == profile2.toDict()


# ================================================================================
# saveProfile Tests
# ================================================================================

def test_saveProfile_validProfile_savesFile():
    """
    Given: A valid VehicleProfile
    When: Saving to file
    Then: Creates valid JSON file
    """
    profile = VehicleProfile(
        vin="4A3AK44Y4WE068213",
        make="Mitsubishi",
        model="Eclipse",
        year=1998,
    )
    path = getTempFilePath()
    try:
        saveProfile(profile, path)
        assert os.path.exists(path)

        # Verify file content
        with open(path, "r") as f:
            data = json.load(f)
        assert data["make"] == "Mitsubishi"
        assert data["year"] == 1998
    finally:
        cleanupTempFile(path)


def test_saveProfile_createsDirectory():
    """
    Given: A path with non-existent directory
    When: Saving profile
    Then: Creates directory and saves file
    """
    tempDir = tempfile.mkdtemp()
    path = os.path.join(tempDir, "subdir", "profile.json")
    try:
        profile = VehicleProfile()
        saveProfile(profile, path)
        assert os.path.exists(path)
    finally:
        cleanupTempFile(path)
        try:
            os.rmdir(os.path.dirname(path))
            os.rmdir(tempDir)
        except Exception:
            pass


def test_saveProfile_roundTrip_preservesData():
    """
    Given: A VehicleProfile
    When: Saving and loading
    Then: Data is preserved
    """
    original = VehicleProfile(
        vin="4A3AK44Y4WE068213",
        make="Mitsubishi",
        model="Eclipse GST",
        year=1998,
        engineDisplacementL=2.0,
        cylinders=4,
        fuelType="Gasoline",
        maxRpm=7500,
        redlineRpm=7000,
        idleRpm=850,
    )
    path = getTempFilePath()
    try:
        saveProfile(original, path)
        loaded = loadProfile(path)
        assert original.toDict() == loaded.toDict()
    finally:
        cleanupTempFile(path)


# ================================================================================
# Helper Function Tests
# ================================================================================

def test_getProfilesDirectory_returnsPath():
    """
    Given: No arguments
    When: Getting profiles directory
    Then: Returns valid path ending with 'profiles'
    """
    path = getProfilesDirectory()
    assert path.endswith("profiles")


def test_getDefaultProfilePath_returnsPath():
    """
    Given: No arguments
    When: Getting default profile path
    Then: Returns path to default.json
    """
    path = getDefaultProfilePath()
    assert path.endswith("default.json")


def test_loadDefaultProfileFromFile_returnsProfile():
    """
    Given: The default.json file exists
    When: Loading default profile from file
    Then: Returns valid VehicleProfile
    """
    profile = loadDefaultProfileFromFile()
    assert isinstance(profile, VehicleProfile)


def test_listAvailableProfiles_returnsProfileList():
    """
    Given: The profiles directory
    When: Listing available profiles
    Then: Returns list containing default.json
    """
    profiles = listAvailableProfiles()
    assert isinstance(profiles, list)
    assert "default.json" in profiles


def test_createProfileFromConfig_nestedProfile_createsProfile():
    """
    Given: Config with profile under simulator.profile
    When: Creating profile from config
    Then: Extracts and creates profile
    """
    config = {
        "simulator": {
            "profile": {
                "make": "Ford",
                "model": "Mustang",
                "year": 2023,
            }
        }
    }
    profile = createProfileFromConfig(config)
    assert profile.make == "Ford"
    assert profile.model == "Mustang"


def test_createProfileFromConfig_directProfile_createsProfile():
    """
    Given: Config with profile at top level
    When: Creating profile from config
    Then: Creates profile from top-level data
    """
    config = {
        "make": "Honda",
        "model": "Civic",
        "year": 2022,
    }
    profile = createProfileFromConfig(config)
    assert profile.make == "Honda"


def test_createProfileFromConfig_profileKey_createsProfile():
    """
    Given: Config with profile under 'profile' key
    When: Creating profile from config
    Then: Extracts and creates profile
    """
    config = {
        "profile": {
            "make": "Chevrolet",
            "model": "Corvette",
            "year": 2024,
        }
    }
    profile = createProfileFromConfig(config)
    assert profile.make == "Chevrolet"


# ================================================================================
# Edge Cases
# ================================================================================

def test_vehicleProfile_vinWithDashes_isValid():
    """
    Given: VIN with dashes
    When: Validating
    Then: Accepts after normalization
    """
    # Note: Dashes are stripped during validation
    profile = VehicleProfile(vin="1HGBH-41JX-MN109186")
    assert profile.vin == "1HGBH-41JX-MN109186"  # Stored as-is


def test_vehicleProfile_maxBoundaryValues_accepted():
    """
    Given: Values at boundary limits
    When: Creating profile
    Then: Accepts valid boundary values
    """
    profile = VehicleProfile(
        year=2100,  # Max valid year
        cylinders=16,  # Max cylinders
    )
    assert profile.year == 2100
    assert profile.cylinders == 16


def test_vehicleProfile_minBoundaryValues_accepted():
    """
    Given: Values at minimum limits
    When: Creating profile
    Then: Accepts valid minimum values
    """
    profile = VehicleProfile(
        year=1900,  # Min valid year
        cylinders=1,  # Min cylinders
    )
    assert profile.year == 1900
    assert profile.cylinders == 1


def test_vehicleProfile_electricVehicle_noEngine():
    """
    Given: Electric vehicle profile
    When: Creating profile
    Then: Accepts with minimal engine values
    """
    profile = VehicleProfile(
        make="Tesla",
        model="Model S",
        fuelType="Electric",
        cylinders=1,  # Min required
        engineDisplacementL=0.1,  # Min positive
        idleRpm=100,
        redlineRpm=10000,
        maxRpm=15000,
    )
    assert profile.fuelType == "Electric"


def test_loadProfile_actualDefaultJson_loads():
    """
    Given: The actual default.json in profiles directory
    When: Loading it directly
    Then: Successfully loads profile
    """
    path = getDefaultProfilePath()
    if os.path.exists(path):
        profile = loadProfile(path)
        assert isinstance(profile, VehicleProfile)
    else:
        print("    (skipped - default.json not found)")


def test_loadProfile_actualEclipseJson_loads():
    """
    Given: The actual eclipse_gst.json in profiles directory
    When: Loading it directly
    Then: Successfully loads profile
    """
    profilesDir = getProfilesDirectory()
    path = os.path.join(profilesDir, "eclipse_gst.json")
    if os.path.exists(path):
        profile = loadProfile(path)
        assert profile.make == "Mitsubishi"
        assert profile.model == "Eclipse GST"
    else:
        print("    (skipped - eclipse_gst.json not found)")


def test_vehicleProfile_dieselFuelType_accepted():
    """
    Given: Diesel fuel type
    When: Creating profile
    Then: Accepts diesel configuration
    """
    profile = VehicleProfile(
        fuelType="Diesel",
        redlineRpm=4500,
        maxRpm=5000,
        idleRpm=700,
    )
    assert profile.fuelType == "Diesel"


def test_vehicleProfile_hybridFuelType_accepted():
    """
    Given: Hybrid fuel type
    When: Creating profile
    Then: Accepts hybrid configuration
    """
    profile = VehicleProfile(
        make="Toyota",
        model="Prius",
        fuelType="Hybrid",
    )
    assert profile.fuelType == "Hybrid"


# ================================================================================
# Main Test Runner
# ================================================================================

def main():
    """Run all tests."""
    runner = TestRunner()

    print("\n" + "=" * 60)
    print("VehicleProfile Module Tests")
    print("=" * 60)

    # VehicleProfile Dataclass Tests
    print("\nVehicleProfile Dataclass Tests:")
    runner.runTest(
        "test_vehicleProfile_defaultValues_createsValidProfile",
        test_vehicleProfile_defaultValues_createsValidProfile
    )
    runner.runTest(
        "test_vehicleProfile_customValues_createsProfile",
        test_vehicleProfile_customValues_createsProfile
    )
    runner.runTest(
        "test_vehicleProfile_invalidVin_raisesError",
        test_vehicleProfile_invalidVin_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_vinWithExcludedChars_raisesError",
        test_vehicleProfile_vinWithExcludedChars_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_invalidYear_raisesError",
        test_vehicleProfile_invalidYear_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_negativeDisplacement_raisesError",
        test_vehicleProfile_negativeDisplacement_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_invalidCylinders_raisesError",
        test_vehicleProfile_invalidCylinders_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_invalidFuelType_raisesError",
        test_vehicleProfile_invalidFuelType_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_redlineGreaterThanMaxRpm_raisesError",
        test_vehicleProfile_redlineGreaterThanMaxRpm_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_idleGreaterThanRedline_raisesError",
        test_vehicleProfile_idleGreaterThanRedline_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_invalidTemperatureOrder_raisesError",
        test_vehicleProfile_invalidTemperatureOrder_raisesError
    )
    runner.runTest(
        "test_vehicleProfile_toDict_returnsCorrectKeys",
        test_vehicleProfile_toDict_returnsCorrectKeys
    )
    runner.runTest(
        "test_vehicleProfile_fromDict_createsValidProfile",
        test_vehicleProfile_fromDict_createsValidProfile
    )
    runner.runTest(
        "test_vehicleProfile_fromDict_emptyDict_usesDefaults",
        test_vehicleProfile_fromDict_emptyDict_usesDefaults
    )
    runner.runTest(
        "test_vehicleProfile_str_returnsReadableString",
        test_vehicleProfile_str_returnsReadableString
    )
    runner.runTest(
        "test_vehicleProfile_validFuelTypes",
        test_vehicleProfile_validFuelTypes
    )
    runner.runTest(
        "test_vehicleProfile_multipleInvalidFields_reportsAll",
        test_vehicleProfile_multipleInvalidFields_reportsAll
    )

    # loadProfile Tests
    print("\nloadProfile Tests:")
    runner.runTest(
        "test_loadProfile_validFile_returnsProfile",
        test_loadProfile_validFile_returnsProfile
    )
    runner.runTest(
        "test_loadProfile_fileNotFound_raisesError",
        test_loadProfile_fileNotFound_raisesError
    )
    runner.runTest(
        "test_loadProfile_invalidJson_raisesError",
        test_loadProfile_invalidJson_raisesError
    )
    runner.runTest(
        "test_loadProfile_invalidData_raisesValidationError",
        test_loadProfile_invalidData_raisesValidationError
    )
    runner.runTest(
        "test_loadProfile_notObject_raisesError",
        test_loadProfile_notObject_raisesError
    )

    # getDefaultProfile Tests
    print("\ngetDefaultProfile Tests:")
    runner.runTest(
        "test_getDefaultProfile_returnsValidProfile",
        test_getDefaultProfile_returnsValidProfile
    )
    runner.runTest(
        "test_getDefaultProfile_isRepeatable",
        test_getDefaultProfile_isRepeatable
    )

    # saveProfile Tests
    print("\nsaveProfile Tests:")
    runner.runTest(
        "test_saveProfile_validProfile_savesFile",
        test_saveProfile_validProfile_savesFile
    )
    runner.runTest(
        "test_saveProfile_createsDirectory",
        test_saveProfile_createsDirectory
    )
    runner.runTest(
        "test_saveProfile_roundTrip_preservesData",
        test_saveProfile_roundTrip_preservesData
    )

    # Helper Function Tests
    print("\nHelper Function Tests:")
    runner.runTest(
        "test_getProfilesDirectory_returnsPath",
        test_getProfilesDirectory_returnsPath
    )
    runner.runTest(
        "test_getDefaultProfilePath_returnsPath",
        test_getDefaultProfilePath_returnsPath
    )
    runner.runTest(
        "test_loadDefaultProfileFromFile_returnsProfile",
        test_loadDefaultProfileFromFile_returnsProfile
    )
    runner.runTest(
        "test_listAvailableProfiles_returnsProfileList",
        test_listAvailableProfiles_returnsProfileList
    )
    runner.runTest(
        "test_createProfileFromConfig_nestedProfile_createsProfile",
        test_createProfileFromConfig_nestedProfile_createsProfile
    )
    runner.runTest(
        "test_createProfileFromConfig_directProfile_createsProfile",
        test_createProfileFromConfig_directProfile_createsProfile
    )
    runner.runTest(
        "test_createProfileFromConfig_profileKey_createsProfile",
        test_createProfileFromConfig_profileKey_createsProfile
    )

    # Edge Cases
    print("\nEdge Case Tests:")
    runner.runTest(
        "test_vehicleProfile_vinWithDashes_isValid",
        test_vehicleProfile_vinWithDashes_isValid
    )
    runner.runTest(
        "test_vehicleProfile_maxBoundaryValues_accepted",
        test_vehicleProfile_maxBoundaryValues_accepted
    )
    runner.runTest(
        "test_vehicleProfile_minBoundaryValues_accepted",
        test_vehicleProfile_minBoundaryValues_accepted
    )
    runner.runTest(
        "test_vehicleProfile_electricVehicle_noEngine",
        test_vehicleProfile_electricVehicle_noEngine
    )
    runner.runTest(
        "test_loadProfile_actualDefaultJson_loads",
        test_loadProfile_actualDefaultJson_loads
    )
    runner.runTest(
        "test_loadProfile_actualEclipseJson_loads",
        test_loadProfile_actualEclipseJson_loads
    )
    runner.runTest(
        "test_vehicleProfile_dieselFuelType_accepted",
        test_vehicleProfile_dieselFuelType_accepted
    )
    runner.runTest(
        "test_vehicleProfile_hybridFuelType_accepted",
        test_vehicleProfile_hybridFuelType_accepted
    )

    # Print report
    success = runner.report()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
