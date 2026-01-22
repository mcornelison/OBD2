#!/usr/bin/env python
################################################################################
# File Name: run_tests_obd_config.py
# Purpose/Description: Run OBD configuration loader tests
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
################################################################################

"""
Test runner for OBD configuration loader module.

Run with:
    python run_tests_obd_config.py
"""

import sys
import traceback
import json
import tempfile
import os
from pathlib import Path

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from obd.obd_config_loader import (
    ObdConfigError,
    loadObdConfig,
    getConfigSection,
    getActiveProfile,
    getLoggedParameters,
    getStaticParameters,
    getRealtimeParameters,
    getPollingInterval,
    shouldQueryStaticOnFirstConnection,
    getSimulatorConfig,
    isSimulatorEnabled,
    getSimulatorProfilePath,
    getSimulatorScenarioPath,
    getSimulatorConnectionDelay,
    getSimulatorUpdateInterval,
    getSimulatorFailures,
    OBD_REQUIRED_FIELDS,
    OBD_DEFAULTS,
    VALID_DISPLAY_MODES,
    _loadConfigFile,
    _validateObdConfig,
    _validateDisplayMode,
    _validateProfilesConfig,
    _validateRealtimeParameters,
    _validateAlertThresholds,
    _validateSimulatorConfig,
)


def createValidObdConfig():
    """Create a valid OBD configuration for testing."""
    return {
        'application': {
            'name': 'Test OBD Monitor',
            'version': '1.0.0'
        },
        'database': {
            'path': './test/obd.db',
            'walMode': True
        },
        'bluetooth': {
            'macAddress': '00:11:22:33:44:55',
            'maxRetries': 3
        },
        'display': {
            'mode': 'headless',
            'width': 240,
            'height': 240
        },
        'realtimeData': {
            'pollingIntervalMs': 500,
            'parameters': [
                {'name': 'RPM', 'logData': True, 'displayOnDashboard': True},
                {'name': 'SPEED', 'logData': True, 'displayOnDashboard': True},
                {'name': 'COOLANT_TEMP', 'logData': False, 'displayOnDashboard': False}
            ]
        },
        'profiles': {
            'activeProfile': 'daily',
            'availableProfiles': [
                {
                    'id': 'daily',
                    'name': 'Daily',
                    'description': 'Test profile',
                    'alertThresholds': {
                        'rpmRedline': 6500,
                        'coolantTempCritical': 110
                    },
                    'pollingIntervalMs': 1000
                }
            ]
        },
        'analysis': {
            'triggerAfterDrive': True
        },
        'aiAnalysis': {
            'enabled': False
        },
        'calibration': {
            'mode': False
        }
    }


def createMinimalObdConfig():
    """Create minimal valid OBD configuration."""
    return {
        'database': {
            'path': './test/obd.db'
        },
        'bluetooth': {
            'macAddress': 'AA:BB:CC:DD:EE:FF'
        },
        'display': {
            'mode': 'headless'
        },
        'realtimeData': {
            'parameters': [
                {'name': 'RPM', 'logData': True}
            ]
        }
    }


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
    """Run all OBD config loader tests."""
    runner = TestRunner()

    # =========================================================================
    # ObdConfigError Tests
    # =========================================================================
    print("\nObdConfigError Tests:")

    def test_ObdConfigError_init_withMessage_storesMessage():
        error = ObdConfigError("Test error")
        assert str(error) == "Test error"

    runner.runTest("ObdConfigError_init_withMessage", test_ObdConfigError_init_withMessage_storesMessage)

    def test_ObdConfigError_init_withMissingFields():
        error = ObdConfigError("Test", missingFields=['field1', 'field2'])
        assert error.missingFields == ['field1', 'field2']

    runner.runTest("ObdConfigError_init_withMissingFields", test_ObdConfigError_init_withMissingFields)

    def test_ObdConfigError_init_withInvalidFields():
        error = ObdConfigError("Test", invalidFields=['field1'])
        assert error.invalidFields == ['field1']

    runner.runTest("ObdConfigError_init_withInvalidFields", test_ObdConfigError_init_withInvalidFields)

    def test_ObdConfigError_init_noFields_defaultsEmpty():
        error = ObdConfigError("Test")
        assert error.missingFields == []
        assert error.invalidFields == []

    runner.runTest("ObdConfigError_init_noFields_defaultsEmpty", test_ObdConfigError_init_noFields_defaultsEmpty)

    # =========================================================================
    # loadObdConfig Tests
    # =========================================================================
    print("\nloadObdConfig Tests:")

    def test_loadObdConfig_validFile_returnsConfig():
        with tempfile.TemporaryDirectory() as tmpDir:
            configFile = Path(tmpDir) / 'obd_config.json'
            config = createValidObdConfig()
            with open(configFile, 'w') as f:
                json.dump(config, f)

            result = loadObdConfig(str(configFile))
            assert result is not None
            assert result['database']['path'] == config['database']['path']

    runner.runTest("loadObdConfig_validFile_returnsConfig", test_loadObdConfig_validFile_returnsConfig)

    def test_loadObdConfig_missingFile_raisesError():
        try:
            loadObdConfig('/nonexistent/path/config.json')
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'not found' in str(e).lower()

    runner.runTest("loadObdConfig_missingFile_raisesError", test_loadObdConfig_missingFile_raisesError)

    def test_loadObdConfig_invalidJson_raisesError():
        with tempfile.TemporaryDirectory() as tmpDir:
            invalidFile = Path(tmpDir) / 'invalid.json'
            with open(invalidFile, 'w') as f:
                f.write('{invalid json}')

            try:
                loadObdConfig(str(invalidFile))
                assert False, "Should have raised ObdConfigError"
            except ObdConfigError as e:
                assert 'invalid json' in str(e).lower()

    runner.runTest("loadObdConfig_invalidJson_raisesError", test_loadObdConfig_invalidJson_raisesError)

    def test_loadObdConfig_appliesDefaults():
        with tempfile.TemporaryDirectory() as tmpDir:
            configFile = Path(tmpDir) / 'minimal.json'
            config = createMinimalObdConfig()
            with open(configFile, 'w') as f:
                json.dump(config, f)

            result = loadObdConfig(str(configFile))
            assert result['bluetooth']['maxRetries'] == OBD_DEFAULTS['bluetooth.maxRetries']
            assert result['display']['refreshRateMs'] == OBD_DEFAULTS['display.refreshRateMs']

    runner.runTest("loadObdConfig_appliesDefaults", test_loadObdConfig_appliesDefaults)

    def test_loadObdConfig_withEnvFile_resolvesSecrets():
        with tempfile.TemporaryDirectory() as tmpDir:
            config = {
                'database': {'path': '${TEST_DB_PATH}'},
                'bluetooth': {'macAddress': '00:11:22:33:44:55'},
                'display': {'mode': 'headless'},
                'realtimeData': {'parameters': [{'name': 'RPM', 'logData': True}]}
            }
            configFile = Path(tmpDir) / 'config.json'
            with open(configFile, 'w') as f:
                json.dump(config, f)

            envFile = Path(tmpDir) / '.env'
            with open(envFile, 'w') as f:
                f.write('TEST_DB_PATH=./resolved/path.db\n')

            result = loadObdConfig(str(configFile), str(envFile))
            assert result['database']['path'] == './resolved/path.db'

    runner.runTest("loadObdConfig_withEnvFile_resolvesSecrets", test_loadObdConfig_withEnvFile_resolvesSecrets)

    # =========================================================================
    # _loadConfigFile Tests
    # =========================================================================
    print("\n_loadConfigFile Tests:")

    def test_loadConfigFile_validFile_returnsDict():
        with tempfile.TemporaryDirectory() as tmpDir:
            configFile = Path(tmpDir) / 'test.json'
            with open(configFile, 'w') as f:
                json.dump({'test': 'value'}, f)

            result = _loadConfigFile(str(configFile))
            assert isinstance(result, dict)
            assert result['test'] == 'value'

    runner.runTest("loadConfigFile_validFile_returnsDict", test_loadConfigFile_validFile_returnsDict)

    def test_loadConfigFile_emptyFile_raisesError():
        with tempfile.TemporaryDirectory() as tmpDir:
            emptyFile = Path(tmpDir) / 'empty.json'
            emptyFile.touch()

            try:
                _loadConfigFile(str(emptyFile))
                assert False, "Should have raised ObdConfigError"
            except ObdConfigError:
                pass

    runner.runTest("loadConfigFile_emptyFile_raisesError", test_loadConfigFile_emptyFile_raisesError)

    # =========================================================================
    # _validateDisplayMode Tests
    # =========================================================================
    print("\n_validateDisplayMode Tests:")

    def test_validateDisplayMode_headless_passes():
        config = createValidObdConfig()
        config['display']['mode'] = 'headless'
        _validateDisplayMode(config)  # Should not raise

    runner.runTest("validateDisplayMode_headless_passes", test_validateDisplayMode_headless_passes)

    def test_validateDisplayMode_minimal_passes():
        config = createValidObdConfig()
        config['display']['mode'] = 'minimal'
        _validateDisplayMode(config)  # Should not raise

    runner.runTest("validateDisplayMode_minimal_passes", test_validateDisplayMode_minimal_passes)

    def test_validateDisplayMode_developer_passes():
        config = createValidObdConfig()
        config['display']['mode'] = 'developer'
        _validateDisplayMode(config)  # Should not raise

    runner.runTest("validateDisplayMode_developer_passes", test_validateDisplayMode_developer_passes)

    def test_validateDisplayMode_invalid_raisesError():
        config = createValidObdConfig()
        config['display']['mode'] = 'invalid_mode'

        try:
            _validateDisplayMode(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'display.mode' in e.invalidFields

    runner.runTest("validateDisplayMode_invalid_raisesError", test_validateDisplayMode_invalid_raisesError)

    # =========================================================================
    # _validateProfilesConfig Tests
    # =========================================================================
    print("\n_validateProfilesConfig Tests:")

    def test_validateProfilesConfig_validProfiles_passes():
        config = createValidObdConfig()
        _validateProfilesConfig(config)  # Should not raise

    runner.runTest("validateProfilesConfig_validProfiles_passes", test_validateProfilesConfig_validProfiles_passes)

    def test_validateProfilesConfig_emptyProfiles_createsDefault():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'] = []
        config['profiles']['activeProfile'] = ''

        _validateProfilesConfig(config)

        assert len(config['profiles']['availableProfiles']) == 1
        assert config['profiles']['availableProfiles'][0]['id'] == 'daily'

    runner.runTest("validateProfilesConfig_emptyProfiles_createsDefault", test_validateProfilesConfig_emptyProfiles_createsDefault)

    def test_validateProfilesConfig_invalidActiveProfile_raisesError():
        config = createValidObdConfig()
        config['profiles']['activeProfile'] = 'nonexistent'

        try:
            _validateProfilesConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'profiles.activeProfile' in e.invalidFields

    runner.runTest("validateProfilesConfig_invalidActiveProfile_raisesError", test_validateProfilesConfig_invalidActiveProfile_raisesError)

    def test_validateProfilesConfig_missingProfileId_raisesError():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'] = [{'name': 'No ID Profile'}]
        config['profiles']['activeProfile'] = ''

        try:
            _validateProfilesConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'id' in str(e.missingFields[0])

    runner.runTest("validateProfilesConfig_missingProfileId_raisesError", test_validateProfilesConfig_missingProfileId_raisesError)

    def test_validateProfilesConfig_missingProfileName_raisesError():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'] = [{'id': 'test'}]
        config['profiles']['activeProfile'] = 'test'

        try:
            _validateProfilesConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'name' in str(e.missingFields[0])

    runner.runTest("validateProfilesConfig_missingProfileName_raisesError", test_validateProfilesConfig_missingProfileName_raisesError)

    # =========================================================================
    # _validateRealtimeParameters Tests
    # =========================================================================
    print("\n_validateRealtimeParameters Tests:")

    def test_validateRealtimeParameters_validParams_passes():
        config = createValidObdConfig()
        _validateRealtimeParameters(config)  # Should not raise

    runner.runTest("validateRealtimeParameters_validParams_passes", test_validateRealtimeParameters_validParams_passes)

    def test_validateRealtimeParameters_emptyParams_raisesError():
        config = createValidObdConfig()
        config['realtimeData']['parameters'] = []

        try:
            _validateRealtimeParameters(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'No realtime data parameters' in str(e)

    runner.runTest("validateRealtimeParameters_emptyParams_raisesError", test_validateRealtimeParameters_emptyParams_raisesError)

    def test_validateRealtimeParameters_stringParams_convertsToDict():
        config = createValidObdConfig()
        config['realtimeData']['parameters'] = ['RPM', 'SPEED']

        _validateRealtimeParameters(config)

        params = config['realtimeData']['parameters']
        assert isinstance(params[0], dict)
        assert params[0]['name'] == 'RPM'
        assert params[0]['logData'] is True

    runner.runTest("validateRealtimeParameters_stringParams_convertsToDict", test_validateRealtimeParameters_stringParams_convertsToDict)

    def test_validateRealtimeParameters_missingName_raisesError():
        config = createValidObdConfig()
        config['realtimeData']['parameters'] = [{'logData': True}]

        try:
            _validateRealtimeParameters(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'Invalid realtime parameter' in str(e)

    runner.runTest("validateRealtimeParameters_missingName_raisesError", test_validateRealtimeParameters_missingName_raisesError)

    # =========================================================================
    # _validateAlertThresholds Tests
    # =========================================================================
    print("\n_validateAlertThresholds Tests:")

    def test_validateAlertThresholds_validThresholds_passes():
        config = createValidObdConfig()
        _validateAlertThresholds(config)  # Should not raise

    runner.runTest("validateAlertThresholds_validThresholds_passes", test_validateAlertThresholds_validThresholds_passes)

    def test_validateAlertThresholds_negativeRpm_raisesError():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'][0]['alertThresholds']['rpmRedline'] = -100

        try:
            _validateAlertThresholds(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'rpmRedline' in str(e)

    runner.runTest("validateAlertThresholds_negativeRpm_raisesError", test_validateAlertThresholds_negativeRpm_raisesError)

    def test_validateAlertThresholds_invalidCoolantTemp_raisesError():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'][0]['alertThresholds']['coolantTempCritical'] = 'hot'

        try:
            _validateAlertThresholds(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'coolantTempCritical' in str(e)

    runner.runTest("validateAlertThresholds_invalidCoolantTemp_raisesError", test_validateAlertThresholds_invalidCoolantTemp_raisesError)

    # =========================================================================
    # Helper Functions Tests
    # =========================================================================
    print("\nHelper Functions Tests:")

    def test_getConfigSection_existingSection_returnsSection():
        config = createValidObdConfig()
        result = getConfigSection(config, 'database')
        assert result['path'] == config['database']['path']

    runner.runTest("getConfigSection_existingSection_returnsSection", test_getConfigSection_existingSection_returnsSection)

    def test_getConfigSection_missingSection_returnsEmptyDict():
        config = createValidObdConfig()
        result = getConfigSection(config, 'nonexistent')
        assert result == {}

    runner.runTest("getConfigSection_missingSection_returnsEmptyDict", test_getConfigSection_missingSection_returnsEmptyDict)

    def test_getActiveProfile_existingProfile_returnsProfile():
        config = createValidObdConfig()
        result = getActiveProfile(config)
        assert result is not None
        assert result['id'] == 'daily'

    runner.runTest("getActiveProfile_existingProfile_returnsProfile", test_getActiveProfile_existingProfile_returnsProfile)

    def test_getActiveProfile_noProfiles_returnsNone():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'] = []
        result = getActiveProfile(config)
        assert result is None

    runner.runTest("getActiveProfile_noProfiles_returnsNone", test_getActiveProfile_noProfiles_returnsNone)

    def test_getLoggedParameters_mixedLogData_returnsOnlyLogged():
        config = createValidObdConfig()
        result = getLoggedParameters(config)
        assert 'RPM' in result
        assert 'SPEED' in result
        assert 'COOLANT_TEMP' not in result

    runner.runTest("getLoggedParameters_mixedLogData_returnsOnlyLogged", test_getLoggedParameters_mixedLogData_returnsOnlyLogged)

    def test_getLoggedParameters_emptyParams_returnsEmptyList():
        config = createValidObdConfig()
        config['realtimeData']['parameters'] = []
        result = getLoggedParameters(config)
        assert result == []

    runner.runTest("getLoggedParameters_emptyParams_returnsEmptyList", test_getLoggedParameters_emptyParams_returnsEmptyList)

    def test_getStaticParameters_withParams_returnsList():
        config = createValidObdConfig()
        config['staticData'] = {'parameters': ['VIN', 'FUEL_TYPE', 'OBD_COMPLIANCE']}
        result = getStaticParameters(config)
        assert 'VIN' in result
        assert 'FUEL_TYPE' in result
        assert len(result) == 3

    runner.runTest("getStaticParameters_withParams_returnsList", test_getStaticParameters_withParams_returnsList)

    def test_getStaticParameters_emptyConfig_returnsEmptyList():
        config = createValidObdConfig()
        config['staticData'] = {}
        result = getStaticParameters(config)
        assert result == []

    runner.runTest("getStaticParameters_emptyConfig_returnsEmptyList", test_getStaticParameters_emptyConfig_returnsEmptyList)

    def test_getStaticParameters_missingSection_returnsEmptyList():
        config = createValidObdConfig()
        if 'staticData' in config:
            del config['staticData']
        result = getStaticParameters(config)
        assert result == []

    runner.runTest("getStaticParameters_missingSection_returnsEmptyList", test_getStaticParameters_missingSection_returnsEmptyList)

    def test_getRealtimeParameters_dictParams_returnsList():
        config = createValidObdConfig()
        result = getRealtimeParameters(config)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]['name'] == 'RPM'

    runner.runTest("getRealtimeParameters_dictParams_returnsList", test_getRealtimeParameters_dictParams_returnsList)

    def test_getRealtimeParameters_stringParams_convertsToDict():
        config = createValidObdConfig()
        config['realtimeData']['parameters'] = ['RPM', 'SPEED']
        result = getRealtimeParameters(config)
        assert isinstance(result[0], dict)
        assert result[0]['name'] == 'RPM'
        assert result[0]['logData'] is True

    runner.runTest("getRealtimeParameters_stringParams_convertsToDict", test_getRealtimeParameters_stringParams_convertsToDict)

    def test_getPollingInterval_fromProfile_returnsProfileInterval():
        config = createValidObdConfig()
        config['profiles']['availableProfiles'][0]['pollingIntervalMs'] = 500
        result = getPollingInterval(config)
        assert result == 500

    runner.runTest("getPollingInterval_fromProfile_returnsProfileInterval", test_getPollingInterval_fromProfile_returnsProfileInterval)

    def test_getPollingInterval_noProfileInterval_returnsGlobal():
        config = createValidObdConfig()
        del config['profiles']['availableProfiles'][0]['pollingIntervalMs']
        config['realtimeData']['pollingIntervalMs'] = 2000
        result = getPollingInterval(config)
        assert result == 2000

    runner.runTest("getPollingInterval_noProfileInterval_returnsGlobal", test_getPollingInterval_noProfileInterval_returnsGlobal)

    def test_shouldQueryStaticOnFirstConnection_true_returnsTrue():
        config = createValidObdConfig()
        config['staticData'] = {'queryOnFirstConnection': True}
        result = shouldQueryStaticOnFirstConnection(config)
        assert result is True

    runner.runTest("shouldQueryStaticOnFirstConnection_true_returnsTrue", test_shouldQueryStaticOnFirstConnection_true_returnsTrue)

    def test_shouldQueryStaticOnFirstConnection_false_returnsFalse():
        config = createValidObdConfig()
        config['staticData'] = {'queryOnFirstConnection': False}
        result = shouldQueryStaticOnFirstConnection(config)
        assert result is False

    runner.runTest("shouldQueryStaticOnFirstConnection_false_returnsFalse", test_shouldQueryStaticOnFirstConnection_false_returnsFalse)

    def test_shouldQueryStaticOnFirstConnection_missing_defaultsTrue():
        config = createValidObdConfig()
        config['staticData'] = {}
        result = shouldQueryStaticOnFirstConnection(config)
        assert result is True

    runner.runTest("shouldQueryStaticOnFirstConnection_missing_defaultsTrue", test_shouldQueryStaticOnFirstConnection_missing_defaultsTrue)

    # =========================================================================
    # Edge Cases Tests
    # =========================================================================
    print("\nEdge Cases Tests:")

    def test_allDisplayModes_areValid():
        assert 'headless' in VALID_DISPLAY_MODES
        assert 'minimal' in VALID_DISPLAY_MODES
        assert 'developer' in VALID_DISPLAY_MODES

    runner.runTest("allDisplayModes_areValid", test_allDisplayModes_areValid)

    def test_requiredFields_areComplete():
        assert 'database.path' in OBD_REQUIRED_FIELDS
        assert 'bluetooth.macAddress' in OBD_REQUIRED_FIELDS
        assert 'display.mode' in OBD_REQUIRED_FIELDS
        assert 'realtimeData.parameters' in OBD_REQUIRED_FIELDS

    runner.runTest("requiredFields_areComplete", test_requiredFields_areComplete)

    def test_defaults_coverAllSections():
        sections = set()
        for key in OBD_DEFAULTS.keys():
            sections.add(key.split('.')[0])

        assert 'application' in sections
        assert 'database' in sections
        assert 'bluetooth' in sections
        assert 'display' in sections
        assert 'analysis' in sections
        assert 'alerts' in sections

    runner.runTest("defaults_coverAllSections", test_defaults_coverAllSections)

    def test_loadObdConfig_missingRequiredField_clearsErrorMessage():
        with tempfile.TemporaryDirectory() as tmpDir:
            config = {
                'database': {'path': './test.db'},
                'bluetooth': {},  # Missing macAddress
                'display': {'mode': 'headless'},
                'realtimeData': {'parameters': [{'name': 'RPM', 'logData': True}]}
            }
            configFile = Path(tmpDir) / 'incomplete.json'
            with open(configFile, 'w') as f:
                json.dump(config, f)

            try:
                loadObdConfig(str(configFile))
                assert False, "Should have raised ObdConfigError"
            except ObdConfigError as e:
                assert 'bluetooth.macAddress' in e.missingFields

    runner.runTest("loadObdConfig_missingRequiredField_clearsErrorMessage", test_loadObdConfig_missingRequiredField_clearsErrorMessage)

    def test_loadObdConfig_multipleProfiles_validatesAll():
        with tempfile.TemporaryDirectory() as tmpDir:
            config = {
                'database': {'path': './test.db'},
                'bluetooth': {'macAddress': '00:11:22:33:44:55'},
                'display': {'mode': 'headless'},
                'realtimeData': {'parameters': [{'name': 'RPM', 'logData': True}]},
                'profiles': {
                    'activeProfile': 'performance',
                    'availableProfiles': [
                        {
                            'id': 'daily',
                            'name': 'Daily',
                            'alertThresholds': {'rpmRedline': 6500}
                        },
                        {
                            'id': 'performance',
                            'name': 'Performance',
                            'alertThresholds': {'rpmRedline': 7500}
                        }
                    ]
                }
            }
            configFile = Path(tmpDir) / 'multiprofile.json'
            with open(configFile, 'w') as f:
                json.dump(config, f)

            result = loadObdConfig(str(configFile))
            assert len(result['profiles']['availableProfiles']) == 2
            assert result['profiles']['activeProfile'] == 'performance'

    runner.runTest("loadObdConfig_multipleProfiles_validatesAll", test_loadObdConfig_multipleProfiles_validatesAll)

    # =========================================================================
    # Simulator Config Validation Tests
    # =========================================================================
    print("\n_validateSimulatorConfig Tests:")

    def test_validateSimulatorConfig_validConfig_passes():
        config = createValidObdConfig()
        config['simulator'] = {
            'enabled': False,
            'profilePath': './profiles/default.json',
            'connectionDelaySeconds': 2,
            'updateIntervalMs': 100
        }
        _validateSimulatorConfig(config)  # Should not raise

    runner.runTest("validateSimulatorConfig_validConfig_passes", test_validateSimulatorConfig_validConfig_passes)

    def test_validateSimulatorConfig_noSimulator_passes():
        config = createValidObdConfig()
        if 'simulator' in config:
            del config['simulator']
        _validateSimulatorConfig(config)  # Should not raise

    runner.runTest("validateSimulatorConfig_noSimulator_passes", test_validateSimulatorConfig_noSimulator_passes)

    def test_validateSimulatorConfig_emptySimulator_passes():
        config = createValidObdConfig()
        config['simulator'] = {}
        _validateSimulatorConfig(config)  # Should not raise (empty means defaults apply)

    runner.runTest("validateSimulatorConfig_emptySimulator_passes", test_validateSimulatorConfig_emptySimulator_passes)

    def test_validateSimulatorConfig_invalidEnabled_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {'enabled': 'yes'}  # Should be boolean

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.enabled' in e.invalidFields

    runner.runTest("validateSimulatorConfig_invalidEnabled_raisesError", test_validateSimulatorConfig_invalidEnabled_raisesError)

    def test_validateSimulatorConfig_negativeConnectionDelay_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {'connectionDelaySeconds': -1}

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.connectionDelaySeconds' in e.invalidFields

    runner.runTest("validateSimulatorConfig_negativeConnectionDelay_raisesError", test_validateSimulatorConfig_negativeConnectionDelay_raisesError)

    def test_validateSimulatorConfig_zeroUpdateInterval_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {'updateIntervalMs': 0}

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.updateIntervalMs' in e.invalidFields

    runner.runTest("validateSimulatorConfig_zeroUpdateInterval_raisesError", test_validateSimulatorConfig_zeroUpdateInterval_raisesError)

    def test_validateSimulatorConfig_invalidConnectionDropProbability_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {
            'failures': {
                'connectionDrop': {
                    'enabled': True,
                    'probability': 1.5  # Must be 0.0 - 1.0
                }
            }
        }

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.failures.connectionDrop.probability' in e.invalidFields

    runner.runTest("validateSimulatorConfig_invalidConnectionDropProbability_raisesError", test_validateSimulatorConfig_invalidConnectionDropProbability_raisesError)

    def test_validateSimulatorConfig_invalidSensorFailureSensors_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {
            'failures': {
                'sensorFailure': {
                    'enabled': True,
                    'sensors': 'RPM'  # Should be a list
                }
            }
        }

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.failures.sensorFailure.sensors' in e.invalidFields

    runner.runTest("validateSimulatorConfig_invalidSensorFailureSensors_raisesError", test_validateSimulatorConfig_invalidSensorFailureSensors_raisesError)

    def test_validateSimulatorConfig_invalidOutOfRangeMultiplier_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {
            'failures': {
                'outOfRange': {
                    'enabled': True,
                    'multiplier': -2.0  # Must be positive
                }
            }
        }

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.failures.outOfRange.multiplier' in e.invalidFields

    runner.runTest("validateSimulatorConfig_invalidOutOfRangeMultiplier_raisesError", test_validateSimulatorConfig_invalidOutOfRangeMultiplier_raisesError)

    def test_validateSimulatorConfig_invalidDtcCodesList_raisesError():
        config = createValidObdConfig()
        config['simulator'] = {
            'failures': {
                'dtcCodes': {
                    'enabled': True,
                    'codes': 'P0420'  # Should be a list
                }
            }
        }

        try:
            _validateSimulatorConfig(config)
            assert False, "Should have raised ObdConfigError"
        except ObdConfigError as e:
            assert 'simulator.failures.dtcCodes.codes' in e.invalidFields

    runner.runTest("validateSimulatorConfig_invalidDtcCodesList_raisesError", test_validateSimulatorConfig_invalidDtcCodesList_raisesError)

    def test_validateSimulatorConfig_validFailures_passes():
        config = createValidObdConfig()
        config['simulator'] = {
            'enabled': True,
            'failures': {
                'connectionDrop': {
                    'enabled': True,
                    'probability': 0.1,
                    'durationSeconds': 5
                },
                'sensorFailure': {
                    'enabled': True,
                    'sensors': ['RPM', 'SPEED'],
                    'probability': 0.05
                },
                'intermittentSensor': {
                    'enabled': False,
                    'sensors': [],
                    'probability': 0.1
                },
                'outOfRange': {
                    'enabled': False,
                    'sensors': ['COOLANT_TEMP'],
                    'multiplier': 1.5
                },
                'dtcCodes': {
                    'enabled': True,
                    'codes': ['P0420', 'P0171']
                }
            }
        }
        _validateSimulatorConfig(config)  # Should not raise

    runner.runTest("validateSimulatorConfig_validFailures_passes", test_validateSimulatorConfig_validFailures_passes)

    # =========================================================================
    # Simulator Helper Functions Tests
    # =========================================================================
    print("\nSimulator Helper Functions Tests:")

    def test_getSimulatorConfig_withSimulator_returnsConfig():
        config = createValidObdConfig()
        config['simulator'] = {
            'enabled': True,
            'profilePath': './custom/profile.json',
            'connectionDelaySeconds': 5,
            'updateIntervalMs': 200
        }
        result = getSimulatorConfig(config)
        assert result['enabled'] is True
        assert result['profilePath'] == './custom/profile.json'
        assert result['connectionDelaySeconds'] == 5
        assert result['updateIntervalMs'] == 200

    runner.runTest("getSimulatorConfig_withSimulator_returnsConfig", test_getSimulatorConfig_withSimulator_returnsConfig)

    def test_getSimulatorConfig_noSimulator_returnsDefaults():
        config = createValidObdConfig()
        if 'simulator' in config:
            del config['simulator']
        result = getSimulatorConfig(config)
        assert result['enabled'] is False
        assert result['connectionDelaySeconds'] == 2
        assert result['updateIntervalMs'] == 100

    runner.runTest("getSimulatorConfig_noSimulator_returnsDefaults", test_getSimulatorConfig_noSimulator_returnsDefaults)

    def test_isSimulatorEnabled_enabledInConfig_returnsTrue():
        config = createValidObdConfig()
        config['simulator'] = {'enabled': True}
        result = isSimulatorEnabled(config)
        assert result is True

    runner.runTest("isSimulatorEnabled_enabledInConfig_returnsTrue", test_isSimulatorEnabled_enabledInConfig_returnsTrue)

    def test_isSimulatorEnabled_disabledInConfig_returnsFalse():
        config = createValidObdConfig()
        config['simulator'] = {'enabled': False}
        result = isSimulatorEnabled(config)
        assert result is False

    runner.runTest("isSimulatorEnabled_disabledInConfig_returnsFalse", test_isSimulatorEnabled_disabledInConfig_returnsFalse)

    def test_isSimulatorEnabled_simulateFlagOverrides_returnsTrue():
        config = createValidObdConfig()
        config['simulator'] = {'enabled': False}
        result = isSimulatorEnabled(config, simulateFlag=True)
        assert result is True

    runner.runTest("isSimulatorEnabled_simulateFlagOverrides_returnsTrue", test_isSimulatorEnabled_simulateFlagOverrides_returnsTrue)

    def test_isSimulatorEnabled_noSimulatorSection_returnsFalse():
        config = createValidObdConfig()
        if 'simulator' in config:
            del config['simulator']
        result = isSimulatorEnabled(config)
        assert result is False

    runner.runTest("isSimulatorEnabled_noSimulatorSection_returnsFalse", test_isSimulatorEnabled_noSimulatorSection_returnsFalse)

    def test_getSimulatorProfilePath_customPath_returnsPath():
        config = createValidObdConfig()
        config['simulator'] = {'profilePath': './my/custom/profile.json'}
        result = getSimulatorProfilePath(config)
        assert result == './my/custom/profile.json'

    runner.runTest("getSimulatorProfilePath_customPath_returnsPath", test_getSimulatorProfilePath_customPath_returnsPath)

    def test_getSimulatorProfilePath_noPath_returnsDefault():
        config = createValidObdConfig()
        config['simulator'] = {}
        result = getSimulatorProfilePath(config)
        assert 'default.json' in result

    runner.runTest("getSimulatorProfilePath_noPath_returnsDefault", test_getSimulatorProfilePath_noPath_returnsDefault)

    def test_getSimulatorScenarioPath_withPath_returnsPath():
        config = createValidObdConfig()
        config['simulator'] = {'scenarioPath': './scenarios/city_driving.json'}
        result = getSimulatorScenarioPath(config)
        assert result == './scenarios/city_driving.json'

    runner.runTest("getSimulatorScenarioPath_withPath_returnsPath", test_getSimulatorScenarioPath_withPath_returnsPath)

    def test_getSimulatorScenarioPath_emptyPath_returnsNone():
        config = createValidObdConfig()
        config['simulator'] = {'scenarioPath': ''}
        result = getSimulatorScenarioPath(config)
        assert result is None

    runner.runTest("getSimulatorScenarioPath_emptyPath_returnsNone", test_getSimulatorScenarioPath_emptyPath_returnsNone)

    def test_getSimulatorScenarioPath_noPath_returnsNone():
        config = createValidObdConfig()
        config['simulator'] = {}
        result = getSimulatorScenarioPath(config)
        assert result is None

    runner.runTest("getSimulatorScenarioPath_noPath_returnsNone", test_getSimulatorScenarioPath_noPath_returnsNone)

    def test_getSimulatorConnectionDelay_customValue_returnsValue():
        config = createValidObdConfig()
        config['simulator'] = {'connectionDelaySeconds': 10}
        result = getSimulatorConnectionDelay(config)
        assert result == 10

    runner.runTest("getSimulatorConnectionDelay_customValue_returnsValue", test_getSimulatorConnectionDelay_customValue_returnsValue)

    def test_getSimulatorConnectionDelay_noValue_returnsDefault():
        config = createValidObdConfig()
        config['simulator'] = {}
        result = getSimulatorConnectionDelay(config)
        assert result == 2

    runner.runTest("getSimulatorConnectionDelay_noValue_returnsDefault", test_getSimulatorConnectionDelay_noValue_returnsDefault)

    def test_getSimulatorUpdateInterval_customValue_returnsValue():
        config = createValidObdConfig()
        config['simulator'] = {'updateIntervalMs': 500}
        result = getSimulatorUpdateInterval(config)
        assert result == 500

    runner.runTest("getSimulatorUpdateInterval_customValue_returnsValue", test_getSimulatorUpdateInterval_customValue_returnsValue)

    def test_getSimulatorUpdateInterval_noValue_returnsDefault():
        config = createValidObdConfig()
        config['simulator'] = {}
        result = getSimulatorUpdateInterval(config)
        assert result == 100

    runner.runTest("getSimulatorUpdateInterval_noValue_returnsDefault", test_getSimulatorUpdateInterval_noValue_returnsDefault)

    def test_getSimulatorFailures_withFailures_returnsDict():
        config = createValidObdConfig()
        config['simulator'] = {
            'failures': {
                'connectionDrop': {'enabled': True, 'probability': 0.1}
            }
        }
        result = getSimulatorFailures(config)
        assert 'connectionDrop' in result
        assert result['connectionDrop']['enabled'] is True

    runner.runTest("getSimulatorFailures_withFailures_returnsDict", test_getSimulatorFailures_withFailures_returnsDict)

    def test_getSimulatorFailures_noFailures_returnsEmptyDict():
        config = createValidObdConfig()
        config['simulator'] = {}
        result = getSimulatorFailures(config)
        assert result == {}

    runner.runTest("getSimulatorFailures_noFailures_returnsEmptyDict", test_getSimulatorFailures_noFailures_returnsEmptyDict)

    def test_loadObdConfig_withSimulator_validatesSimulator():
        with tempfile.TemporaryDirectory() as tmpDir:
            config = createMinimalObdConfig()
            config['simulator'] = {
                'enabled': True,
                'connectionDelaySeconds': 3,
                'updateIntervalMs': 150
            }
            configFile = Path(tmpDir) / 'with_sim.json'
            with open(configFile, 'w') as f:
                json.dump(config, f)

            result = loadObdConfig(str(configFile))
            assert 'simulator' in result
            assert result['simulator']['enabled'] is True

    runner.runTest("loadObdConfig_withSimulator_validatesSimulator", test_loadObdConfig_withSimulator_validatesSimulator)

    def test_defaults_includeSimulatorSection():
        sections = set()
        for key in OBD_DEFAULTS.keys():
            sections.add(key.split('.')[0])
        assert 'simulator' in sections

    runner.runTest("defaults_includeSimulatorSection", test_defaults_includeSimulatorSection)

    # Print summary
    runner.printSummary()

    return 0 if runner.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(runTests())
