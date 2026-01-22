#!/usr/bin/env python
################################################################################
# File Name: run_tests_obd_parameters.py
# Purpose/Description: Run OBD parameter definitions tests
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
################################################################################

"""
Test runner for OBD parameter definitions module.

Run with:
    python run_tests_obd_parameters.py
"""

import sys
import traceback
from pathlib import Path

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.obd_parameters import (
    ParameterInfo,
    STATIC_PARAMETERS,
    REALTIME_PARAMETERS,
    ALL_PARAMETERS,
    getParameterInfo,
    getAllParameterNames,
    getStaticParameterNames,
    getRealtimeParameterNames,
    isValidParameter,
    isStaticParameter,
    isRealtimeParameter,
    getParametersByCategory,
    getCategories,
    getDefaultRealtimeConfig,
    getDefaultStaticConfig,
)


class TestRunner:
    """Simple test runner for environments without pytest."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def runTest(self, testName, testFunc):
        """Run a single test and record result."""
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
            self.errors.append((testName, traceback.format_exc()))
            print(f"  [ERROR] {testName}: {e}")

    def printSummary(self):
        """Print test summary."""
        total = self.passed + self.failed
        print(f"\n{self.passed} passed, {self.failed} failed out of {total} tests")
        if self.errors:
            print("\nErrors:")
            for name, error in self.errors:
                print(f"\n  {name}:")
                for line in error.split('\n')[:5]:
                    print(f"    {line}")


def runTests():
    """Run all OBD parameter tests."""
    runner = TestRunner()

    # =========================================================================
    # ParameterInfo Tests
    # =========================================================================
    print("\nParameterInfo Tests:")

    def test_ParameterInfo_init_storesAllFields():
        info = ParameterInfo(
            name='TEST',
            description='Test parameter',
            unit='unit',
            category='test',
            isStatic=False,
            defaultLogData=True
        )
        assert info.name == 'TEST'
        assert info.description == 'Test parameter'
        assert info.unit == 'unit'
        assert info.category == 'test'
        assert info.isStatic is False
        assert info.defaultLogData is True

    runner.runTest("ParameterInfo_init_storesAllFields", test_ParameterInfo_init_storesAllFields)

    def test_ParameterInfo_toDict_returnsDict():
        info = ParameterInfo(
            name='RPM',
            description='Engine RPM',
            unit='rpm',
            category='engine',
            isStatic=False,
            defaultLogData=True
        )
        result = info.toDict()
        assert isinstance(result, dict)
        assert result['name'] == 'RPM'
        assert result['description'] == 'Engine RPM'
        assert result['unit'] == 'rpm'
        assert result['category'] == 'engine'
        assert result['isStatic'] is False
        assert result['defaultLogData'] is True

    runner.runTest("ParameterInfo_toDict_returnsDict", test_ParameterInfo_toDict_returnsDict)

    def test_ParameterInfo_defaultLogData_defaultsFalse():
        info = ParameterInfo(
            name='TEST',
            description='Test',
            unit=None,
            category='test',
            isStatic=True
        )
        assert info.defaultLogData is False

    runner.runTest("ParameterInfo_defaultLogData_defaultsFalse", test_ParameterInfo_defaultLogData_defaultsFalse)

    # =========================================================================
    # Static Parameters Tests
    # =========================================================================
    print("\nStatic Parameters Tests:")

    def test_STATIC_PARAMETERS_containsVIN():
        assert 'VIN' in STATIC_PARAMETERS
        info = STATIC_PARAMETERS['VIN']
        assert info.isStatic is True
        assert info.description == 'Vehicle Identification Number'

    runner.runTest("STATIC_PARAMETERS_containsVIN", test_STATIC_PARAMETERS_containsVIN)

    def test_STATIC_PARAMETERS_containsFUEL_TYPE():
        assert 'FUEL_TYPE' in STATIC_PARAMETERS
        info = STATIC_PARAMETERS['FUEL_TYPE']
        assert info.isStatic is True
        assert 'fuel' in info.category.lower()

    runner.runTest("STATIC_PARAMETERS_containsFUEL_TYPE", test_STATIC_PARAMETERS_containsFUEL_TYPE)

    def test_STATIC_PARAMETERS_containsOBD_COMPLIANCE():
        assert 'OBD_COMPLIANCE' in STATIC_PARAMETERS
        info = STATIC_PARAMETERS['OBD_COMPLIANCE']
        assert info.isStatic is True

    runner.runTest("STATIC_PARAMETERS_containsOBD_COMPLIANCE", test_STATIC_PARAMETERS_containsOBD_COMPLIANCE)

    def test_STATIC_PARAMETERS_allAreStatic():
        for name, info in STATIC_PARAMETERS.items():
            assert info.isStatic is True, f"{name} should be static"

    runner.runTest("STATIC_PARAMETERS_allAreStatic", test_STATIC_PARAMETERS_allAreStatic)

    # =========================================================================
    # Realtime Parameters Tests
    # =========================================================================
    print("\nRealtime Parameters Tests:")

    def test_REALTIME_PARAMETERS_containsRPM():
        assert 'RPM' in REALTIME_PARAMETERS
        info = REALTIME_PARAMETERS['RPM']
        assert info.isStatic is False
        assert info.unit == 'rpm'
        assert info.category == 'engine'

    runner.runTest("REALTIME_PARAMETERS_containsRPM", test_REALTIME_PARAMETERS_containsRPM)

    def test_REALTIME_PARAMETERS_containsSPEED():
        assert 'SPEED' in REALTIME_PARAMETERS
        info = REALTIME_PARAMETERS['SPEED']
        assert info.isStatic is False
        assert info.unit == 'km/h'

    runner.runTest("REALTIME_PARAMETERS_containsSPEED", test_REALTIME_PARAMETERS_containsSPEED)

    def test_REALTIME_PARAMETERS_containsCOOLANT_TEMP():
        assert 'COOLANT_TEMP' in REALTIME_PARAMETERS
        info = REALTIME_PARAMETERS['COOLANT_TEMP']
        assert info.isStatic is False
        assert info.category == 'temperature'

    runner.runTest("REALTIME_PARAMETERS_containsCOOLANT_TEMP", test_REALTIME_PARAMETERS_containsCOOLANT_TEMP)

    def test_REALTIME_PARAMETERS_containsMAF():
        assert 'MAF' in REALTIME_PARAMETERS
        info = REALTIME_PARAMETERS['MAF']
        assert info.category == 'airfuel'
        assert info.unit == 'g/s'

    runner.runTest("REALTIME_PARAMETERS_containsMAF", test_REALTIME_PARAMETERS_containsMAF)

    def test_REALTIME_PARAMETERS_containsO2Sensors():
        assert 'O2_B1S1' in REALTIME_PARAMETERS
        info = REALTIME_PARAMETERS['O2_B1S1']
        assert info.category == 'oxygen'
        assert info.unit == 'V'

    runner.runTest("REALTIME_PARAMETERS_containsO2Sensors", test_REALTIME_PARAMETERS_containsO2Sensors)

    def test_REALTIME_PARAMETERS_allAreNotStatic():
        for name, info in REALTIME_PARAMETERS.items():
            assert info.isStatic is False, f"{name} should not be static"

    runner.runTest("REALTIME_PARAMETERS_allAreNotStatic", test_REALTIME_PARAMETERS_allAreNotStatic)

    # =========================================================================
    # ALL_PARAMETERS Tests
    # =========================================================================
    print("\nALL_PARAMETERS Tests:")

    def test_ALL_PARAMETERS_combinesBoth():
        assert len(ALL_PARAMETERS) == len(STATIC_PARAMETERS) + len(REALTIME_PARAMETERS)

    runner.runTest("ALL_PARAMETERS_combinesBoth", test_ALL_PARAMETERS_combinesBoth)

    def test_ALL_PARAMETERS_containsStatic():
        for name in STATIC_PARAMETERS:
            assert name in ALL_PARAMETERS

    runner.runTest("ALL_PARAMETERS_containsStatic", test_ALL_PARAMETERS_containsStatic)

    def test_ALL_PARAMETERS_containsRealtime():
        for name in REALTIME_PARAMETERS:
            assert name in ALL_PARAMETERS

    runner.runTest("ALL_PARAMETERS_containsRealtime", test_ALL_PARAMETERS_containsRealtime)

    # =========================================================================
    # getParameterInfo Tests
    # =========================================================================
    print("\ngetParameterInfo Tests:")

    def test_getParameterInfo_existingParam_returnsInfo():
        info = getParameterInfo('RPM')
        assert info is not None
        assert info.name == 'RPM'

    runner.runTest("getParameterInfo_existingParam_returnsInfo", test_getParameterInfo_existingParam_returnsInfo)

    def test_getParameterInfo_caseInsensitive():
        info = getParameterInfo('rpm')
        assert info is not None
        assert info.name == 'RPM'

    runner.runTest("getParameterInfo_caseInsensitive", test_getParameterInfo_caseInsensitive)

    def test_getParameterInfo_nonexistent_returnsNone():
        info = getParameterInfo('NONEXISTENT')
        assert info is None

    runner.runTest("getParameterInfo_nonexistent_returnsNone", test_getParameterInfo_nonexistent_returnsNone)

    # =========================================================================
    # getAllParameterNames Tests
    # =========================================================================
    print("\ngetAllParameterNames Tests:")

    def test_getAllParameterNames_returnsSortedList():
        names = getAllParameterNames()
        assert isinstance(names, list)
        assert names == sorted(names)

    runner.runTest("getAllParameterNames_returnsSortedList", test_getAllParameterNames_returnsSortedList)

    def test_getAllParameterNames_includesCommonParams():
        names = getAllParameterNames()
        assert 'RPM' in names
        assert 'SPEED' in names
        assert 'VIN' in names

    runner.runTest("getAllParameterNames_includesCommonParams", test_getAllParameterNames_includesCommonParams)

    # =========================================================================
    # getStaticParameterNames Tests
    # =========================================================================
    print("\ngetStaticParameterNames Tests:")

    def test_getStaticParameterNames_returnsStaticOnly():
        names = getStaticParameterNames()
        for name in names:
            assert name in STATIC_PARAMETERS

    runner.runTest("getStaticParameterNames_returnsStaticOnly", test_getStaticParameterNames_returnsStaticOnly)

    def test_getStaticParameterNames_includesVIN():
        names = getStaticParameterNames()
        assert 'VIN' in names

    runner.runTest("getStaticParameterNames_includesVIN", test_getStaticParameterNames_includesVIN)

    # =========================================================================
    # getRealtimeParameterNames Tests
    # =========================================================================
    print("\ngetRealtimeParameterNames Tests:")

    def test_getRealtimeParameterNames_returnsRealtimeOnly():
        names = getRealtimeParameterNames()
        for name in names:
            assert name in REALTIME_PARAMETERS

    runner.runTest("getRealtimeParameterNames_returnsRealtimeOnly", test_getRealtimeParameterNames_returnsRealtimeOnly)

    def test_getRealtimeParameterNames_includesRPM():
        names = getRealtimeParameterNames()
        assert 'RPM' in names

    runner.runTest("getRealtimeParameterNames_includesRPM", test_getRealtimeParameterNames_includesRPM)

    # =========================================================================
    # isValidParameter Tests
    # =========================================================================
    print("\nisValidParameter Tests:")

    def test_isValidParameter_validParam_returnsTrue():
        assert isValidParameter('RPM') is True
        assert isValidParameter('VIN') is True

    runner.runTest("isValidParameter_validParam_returnsTrue", test_isValidParameter_validParam_returnsTrue)

    def test_isValidParameter_invalidParam_returnsFalse():
        assert isValidParameter('NONEXISTENT') is False

    runner.runTest("isValidParameter_invalidParam_returnsFalse", test_isValidParameter_invalidParam_returnsFalse)

    def test_isValidParameter_caseInsensitive():
        assert isValidParameter('rpm') is True
        assert isValidParameter('Rpm') is True

    runner.runTest("isValidParameter_caseInsensitive", test_isValidParameter_caseInsensitive)

    # =========================================================================
    # isStaticParameter Tests
    # =========================================================================
    print("\nisStaticParameter Tests:")

    def test_isStaticParameter_staticParam_returnsTrue():
        assert isStaticParameter('VIN') is True
        assert isStaticParameter('FUEL_TYPE') is True

    runner.runTest("isStaticParameter_staticParam_returnsTrue", test_isStaticParameter_staticParam_returnsTrue)

    def test_isStaticParameter_realtimeParam_returnsFalse():
        assert isStaticParameter('RPM') is False

    runner.runTest("isStaticParameter_realtimeParam_returnsFalse", test_isStaticParameter_realtimeParam_returnsFalse)

    # =========================================================================
    # isRealtimeParameter Tests
    # =========================================================================
    print("\nisRealtimeParameter Tests:")

    def test_isRealtimeParameter_realtimeParam_returnsTrue():
        assert isRealtimeParameter('RPM') is True
        assert isRealtimeParameter('COOLANT_TEMP') is True

    runner.runTest("isRealtimeParameter_realtimeParam_returnsTrue", test_isRealtimeParameter_realtimeParam_returnsTrue)

    def test_isRealtimeParameter_staticParam_returnsFalse():
        assert isRealtimeParameter('VIN') is False

    runner.runTest("isRealtimeParameter_staticParam_returnsFalse", test_isRealtimeParameter_staticParam_returnsFalse)

    # =========================================================================
    # getParametersByCategory Tests
    # =========================================================================
    print("\ngetParametersByCategory Tests:")

    def test_getParametersByCategory_engine_includesRPM():
        params = getParametersByCategory('engine')
        assert 'RPM' in params
        assert 'SPEED' in params

    runner.runTest("getParametersByCategory_engine_includesRPM", test_getParametersByCategory_engine_includesRPM)

    def test_getParametersByCategory_temperature_includesCOOLANT_TEMP():
        params = getParametersByCategory('temperature')
        assert 'COOLANT_TEMP' in params
        assert 'INTAKE_TEMP' in params

    runner.runTest("getParametersByCategory_temperature_includesCOOLANT_TEMP", test_getParametersByCategory_temperature_includesCOOLANT_TEMP)

    def test_getParametersByCategory_returnsSorted():
        params = getParametersByCategory('engine')
        assert params == sorted(params)

    runner.runTest("getParametersByCategory_returnsSorted", test_getParametersByCategory_returnsSorted)

    def test_getParametersByCategory_unknownCategory_returnsEmpty():
        params = getParametersByCategory('unknown_category')
        assert params == []

    runner.runTest("getParametersByCategory_unknownCategory_returnsEmpty", test_getParametersByCategory_unknownCategory_returnsEmpty)

    # =========================================================================
    # getCategories Tests
    # =========================================================================
    print("\ngetCategories Tests:")

    def test_getCategories_returnsSortedList():
        categories = getCategories()
        assert isinstance(categories, list)
        assert categories == sorted(categories)

    runner.runTest("getCategories_returnsSortedList", test_getCategories_returnsSortedList)

    def test_getCategories_includesCommon():
        categories = getCategories()
        assert 'engine' in categories
        assert 'temperature' in categories
        assert 'pressure' in categories

    runner.runTest("getCategories_includesCommon", test_getCategories_includesCommon)

    # =========================================================================
    # getDefaultRealtimeConfig Tests
    # =========================================================================
    print("\ngetDefaultRealtimeConfig Tests:")

    def test_getDefaultRealtimeConfig_returnsList():
        config = getDefaultRealtimeConfig()
        assert isinstance(config, list)

    runner.runTest("getDefaultRealtimeConfig_returnsList", test_getDefaultRealtimeConfig_returnsList)

    def test_getDefaultRealtimeConfig_includesRPM():
        config = getDefaultRealtimeConfig()
        names = [p['name'] for p in config]
        assert 'RPM' in names

    runner.runTest("getDefaultRealtimeConfig_includesRPM", test_getDefaultRealtimeConfig_includesRPM)

    def test_getDefaultRealtimeConfig_hasLogDataTrue():
        config = getDefaultRealtimeConfig()
        for param in config:
            assert param.get('logData', False) is True

    runner.runTest("getDefaultRealtimeConfig_hasLogDataTrue", test_getDefaultRealtimeConfig_hasLogDataTrue)

    def test_getDefaultRealtimeConfig_dashboardParamsSet():
        config = getDefaultRealtimeConfig()
        rpmConfig = next((p for p in config if p['name'] == 'RPM'), None)
        assert rpmConfig is not None
        assert rpmConfig['displayOnDashboard'] is True

    runner.runTest("getDefaultRealtimeConfig_dashboardParamsSet", test_getDefaultRealtimeConfig_dashboardParamsSet)

    # =========================================================================
    # getDefaultStaticConfig Tests
    # =========================================================================
    print("\ngetDefaultStaticConfig Tests:")

    def test_getDefaultStaticConfig_returnsList():
        config = getDefaultStaticConfig()
        assert isinstance(config, list)

    runner.runTest("getDefaultStaticConfig_returnsList", test_getDefaultStaticConfig_returnsList)

    def test_getDefaultStaticConfig_includesVIN():
        config = getDefaultStaticConfig()
        assert 'VIN' in config

    runner.runTest("getDefaultStaticConfig_includesVIN", test_getDefaultStaticConfig_includesVIN)

    def test_getDefaultStaticConfig_allAreStatic():
        config = getDefaultStaticConfig()
        for name in config:
            assert isStaticParameter(name), f"{name} should be a static parameter"

    runner.runTest("getDefaultStaticConfig_allAreStatic", test_getDefaultStaticConfig_allAreStatic)

    # =========================================================================
    # Edge Cases
    # =========================================================================
    print("\nEdge Case Tests:")

    def test_allParameters_haveDescription():
        for name, info in ALL_PARAMETERS.items():
            assert info.description, f"{name} should have a description"

    runner.runTest("allParameters_haveDescription", test_allParameters_haveDescription)

    def test_allParameters_haveCategory():
        for name, info in ALL_PARAMETERS.items():
            assert info.category, f"{name} should have a category"

    runner.runTest("allParameters_haveCategory", test_allParameters_haveCategory)

    def test_realtimeParameters_haveUnit():
        for name, info in REALTIME_PARAMETERS.items():
            # Most realtime parameters should have units
            if name not in ['STATUS', 'FREEZE_DTC']:
                assert info.unit is not None, f"{name} should have a unit"

    runner.runTest("realtimeParameters_haveUnit", test_realtimeParameters_haveUnit)

    def test_fuelTrimParams_arePercentage():
        info = getParameterInfo('SHORT_FUEL_TRIM_1')
        assert info.unit == '%'
        info2 = getParameterInfo('LONG_FUEL_TRIM_1')
        assert info2.unit == '%'

    runner.runTest("fuelTrimParams_arePercentage", test_fuelTrimParams_arePercentage)

    def test_temperatureParams_areCelsius():
        tempParams = getParametersByCategory('temperature')
        for name in tempParams:
            info = getParameterInfo(name)
            assert '°C' in info.unit or info.unit == '°C', f"{name} should be in Celsius"

    runner.runTest("temperatureParams_areCelsius", test_temperatureParams_areCelsius)

    # Print summary
    runner.printSummary()

    return 0 if runner.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(runTests())
