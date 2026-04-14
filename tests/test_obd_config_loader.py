################################################################################
# File Name: test_obd_config_loader.py
# Purpose/Description: Tests for OBD-II configuration loader
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-001
# ================================================================================
################################################################################

"""
Tests for the OBD configuration loader module.

Run with:
    pytest tests/test_obd_config_loader.py -v
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from pi.obd.config import (
    getActiveProfile,
    getConfigSection,
    getLoggedParameters,
)
from pi.obd.config.loader import (
    OBD_DEFAULTS,
    OBD_REQUIRED_FIELDS,
    VALID_DISPLAY_MODES,
    ObdConfigError,
    _loadConfigFile,
    _validateDisplayMode,
    _validateProfilesConfig,
    _validateRealtimeParameters,
    loadObdConfig,
)

# ================================================================================
# Fixtures
# ================================================================================

@pytest.fixture
def validObdConfig() -> dict[str, Any]:
    """Provide valid OBD configuration for tests (tier-aware shape)."""
    return {
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'test-device',
        'logging': {'level': 'DEBUG'},
        'pi': {
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
                        'pollingIntervalMs': 1000
                    }
                ]
            },
            'analysis': {
                'triggerAfterDrive': True
            },
            'calibration': {
                'mode': False
            }
        },
        'server': {
            'ai': {'enabled': False},
            'database': {},
            'api': {}
        }
    }


@pytest.fixture
def minimalObdConfig() -> dict[str, Any]:
    """Provide minimal valid OBD configuration (tier-aware shape)."""
    return {
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'test-device',
        'logging': {'level': 'DEBUG'},
        'pi': {
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
        },
        'server': {
            'ai': {},
            'database': {},
            'api': {}
        }
    }


@pytest.fixture
def tempObdConfigFile(tmp_path: Path, validObdConfig: dict[str, Any]) -> Path:
    """Create temporary OBD config file."""
    configFile = tmp_path / 'obd_config.json'
    with open(configFile, 'w', encoding='utf-8') as f:
        json.dump(validObdConfig, f)
    return configFile


# ================================================================================
# ObdConfigError Tests
# ================================================================================

class TestObdConfigError:
    """Tests for ObdConfigError exception."""

    def test_init_withMessage_storesMessage(self):
        """
        Given: Error message
        When: ObdConfigError is created
        Then: Message is accessible
        """
        error = ObdConfigError("Test error")
        assert str(error) == "Test error"

    def test_init_withMissingFields_storesFields(self):
        """
        Given: Error with missing fields
        When: ObdConfigError is created
        Then: Missing fields are accessible
        """
        error = ObdConfigError("Test", missingFields=['field1', 'field2'])
        assert error.missingFields == ['field1', 'field2']

    def test_init_withInvalidFields_storesFields(self):
        """
        Given: Error with invalid fields
        When: ObdConfigError is created
        Then: Invalid fields are accessible
        """
        error = ObdConfigError("Test", invalidFields=['field1'])
        assert error.invalidFields == ['field1']

    def test_init_noFields_defaultsToEmptyLists(self):
        """
        Given: Error without field lists
        When: ObdConfigError is created
        Then: Fields default to empty lists
        """
        error = ObdConfigError("Test")
        assert error.missingFields == []
        assert error.invalidFields == []


# ================================================================================
# loadObdConfig Tests
# ================================================================================

class TestLoadObdConfig:
    """Tests for loadObdConfig function."""

    def test_loadObdConfig_validFile_returnsConfig(
        self,
        tempObdConfigFile: Path,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Valid OBD configuration file
        When: loadObdConfig is called
        Then: Returns validated configuration
        """
        result = loadObdConfig(str(tempObdConfigFile))

        assert result is not None
        assert result['pi']['database']['path'] == validObdConfig['pi']['database']['path']
        assert result['pi']['bluetooth']['macAddress'] == validObdConfig['pi']['bluetooth']['macAddress']

    def test_loadObdConfig_missingFile_raisesError(self, tmp_path: Path):
        """
        Given: Non-existent configuration file
        When: loadObdConfig is called
        Then: Raises ObdConfigError
        """
        fakePath = tmp_path / 'nonexistent.json'

        with pytest.raises(ObdConfigError) as excInfo:
            loadObdConfig(str(fakePath))

        assert 'not found' in str(excInfo.value).lower()

    def test_loadObdConfig_invalidJson_raisesError(self, tmp_path: Path):
        """
        Given: File with invalid JSON
        When: loadObdConfig is called
        Then: Raises ObdConfigError with parse error
        """
        invalidFile = tmp_path / 'invalid.json'
        with open(invalidFile, 'w') as f:
            f.write('{invalid json}')

        with pytest.raises(ObdConfigError) as excInfo:
            loadObdConfig(str(invalidFile))

        assert 'invalid json' in str(excInfo.value).lower()

    def test_loadObdConfig_withEnvFile_resolvesSecrets(
        self,
        tmp_path: Path
    ):
        """
        Given: Config with placeholders and .env file
        When: loadObdConfig is called
        Then: Placeholders are resolved
        """
        # Create config with placeholder
        config = {
            'pi': {
                'database': {'path': '${TEST_DB_PATH}'},
                'bluetooth': {'macAddress': '00:11:22:33:44:55'},
                'display': {'mode': 'headless'},
                'realtimeData': {'parameters': [{'name': 'RPM', 'logData': True}]}
            },
            'server': {'ai': {}, 'database': {}, 'api': {}}
        }
        configFile = tmp_path / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(config, f)

        # Create .env file
        envFile = tmp_path / '.env'
        with open(envFile, 'w') as f:
            f.write('TEST_DB_PATH=./resolved/path.db\n')

        result = loadObdConfig(str(configFile), str(envFile))

        assert result['pi']['database']['path'] == './resolved/path.db'

    def test_loadObdConfig_appliesDefaults(
        self,
        tmp_path: Path,
        minimalObdConfig: dict[str, Any]
    ):
        """
        Given: Minimal configuration without optional fields
        When: loadObdConfig is called
        Then: Defaults are applied
        """
        configFile = tmp_path / 'minimal.json'
        with open(configFile, 'w') as f:
            json.dump(minimalObdConfig, f)

        result = loadObdConfig(str(configFile))

        # Check defaults were applied
        assert result['pi']['bluetooth']['maxRetries'] == OBD_DEFAULTS['pi.bluetooth.maxRetries']
        assert result['pi']['display']['refreshRateMs'] == OBD_DEFAULTS['pi.display.refreshRateMs']
        assert result['pi']['alerts']['cooldownSeconds'] == OBD_DEFAULTS['pi.alerts.cooldownSeconds']


# ================================================================================
# _loadConfigFile Tests
# ================================================================================

class TestLoadConfigFile:
    """Tests for _loadConfigFile internal function."""

    def test_loadConfigFile_validFile_returnsDict(self, tempObdConfigFile: Path):
        """
        Given: Valid JSON config file
        When: _loadConfigFile is called
        Then: Returns configuration dict
        """
        result = _loadConfigFile(str(tempObdConfigFile))
        assert isinstance(result, dict)

    def test_loadConfigFile_emptyFile_raisesError(self, tmp_path: Path):
        """
        Given: Empty file
        When: _loadConfigFile is called
        Then: Raises ObdConfigError
        """
        emptyFile = tmp_path / 'empty.json'
        emptyFile.touch()

        with pytest.raises(ObdConfigError):
            _loadConfigFile(str(emptyFile))


# ================================================================================
# _validateDisplayMode Tests
# ================================================================================

class TestValidateDisplayMode:
    """Tests for display mode validation."""

    def test_validateDisplayMode_headless_passes(self, validObdConfig: dict[str, Any]):
        """
        Given: Config with 'headless' display mode
        When: _validateDisplayMode is called
        Then: No error is raised
        """
        validObdConfig['pi']['display']['mode'] = 'headless'
        _validateDisplayMode(validObdConfig)  # Should not raise

    def test_validateDisplayMode_minimal_passes(self, validObdConfig: dict[str, Any]):
        """
        Given: Config with 'minimal' display mode
        When: _validateDisplayMode is called
        Then: No error is raised
        """
        validObdConfig['pi']['display']['mode'] = 'minimal'
        _validateDisplayMode(validObdConfig)  # Should not raise

    def test_validateDisplayMode_developer_passes(self, validObdConfig: dict[str, Any]):
        """
        Given: Config with 'developer' display mode
        When: _validateDisplayMode is called
        Then: No error is raised
        """
        validObdConfig['pi']['display']['mode'] = 'developer'
        _validateDisplayMode(validObdConfig)  # Should not raise

    def test_validateDisplayMode_invalid_raisesError(self, validObdConfig: dict[str, Any]):
        """
        Given: Config with invalid display mode
        When: _validateDisplayMode is called
        Then: Raises ObdConfigError
        """
        validObdConfig['pi']['display']['mode'] = 'invalid_mode'

        with pytest.raises(ObdConfigError) as excInfo:
            _validateDisplayMode(validObdConfig)

        assert 'display.mode' in excInfo.value.invalidFields


# ================================================================================
# _validateProfilesConfig Tests
# ================================================================================

class TestValidateProfilesConfig:
    """Tests for profiles configuration validation."""

    def test_validateProfilesConfig_validProfiles_passes(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with valid profiles
        When: _validateProfilesConfig is called
        Then: No error is raised
        """
        _validateProfilesConfig(validObdConfig)  # Should not raise

    def test_validateProfilesConfig_emptyProfiles_createsDefault(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with no available profiles
        When: _validateProfilesConfig is called
        Then: Default 'daily' profile is created
        """
        validObdConfig['pi']['profiles']['availableProfiles'] = []
        validObdConfig['pi']['profiles']['activeProfile'] = ''

        _validateProfilesConfig(validObdConfig)

        assert len(validObdConfig['pi']['profiles']['availableProfiles']) == 1
        assert validObdConfig['pi']['profiles']['availableProfiles'][0]['id'] == 'daily'

    def test_validateProfilesConfig_invalidActiveProfile_raisesError(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with active profile not in available profiles
        When: _validateProfilesConfig is called
        Then: Raises ObdConfigError
        """
        validObdConfig['pi']['profiles']['activeProfile'] = 'nonexistent'

        with pytest.raises(ObdConfigError) as excInfo:
            _validateProfilesConfig(validObdConfig)

        assert 'profiles.activeProfile' in excInfo.value.invalidFields

    def test_validateProfilesConfig_missingProfileId_raisesError(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Profile missing required 'id' field
        When: _validateProfilesConfig is called
        Then: Raises ObdConfigError
        """
        validObdConfig['pi']['profiles']['availableProfiles'] = [
            {'name': 'No ID Profile'}
        ]
        validObdConfig['pi']['profiles']['activeProfile'] = ''

        with pytest.raises(ObdConfigError) as excInfo:
            _validateProfilesConfig(validObdConfig)

        assert 'id' in str(excInfo.value.missingFields[0])

    def test_validateProfilesConfig_missingProfileName_raisesError(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Profile missing required 'name' field
        When: _validateProfilesConfig is called
        Then: Raises ObdConfigError
        """
        validObdConfig['pi']['profiles']['availableProfiles'] = [
            {'id': 'test'}
        ]
        validObdConfig['pi']['profiles']['activeProfile'] = 'test'

        with pytest.raises(ObdConfigError) as excInfo:
            _validateProfilesConfig(validObdConfig)

        assert 'name' in str(excInfo.value.missingFields[0])


# ================================================================================
# _validateRealtimeParameters Tests
# ================================================================================

class TestValidateRealtimeParameters:
    """Tests for realtime parameters validation."""

    def test_validateRealtimeParameters_validParams_passes(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with valid realtime parameters
        When: _validateRealtimeParameters is called
        Then: No error is raised
        """
        _validateRealtimeParameters(validObdConfig)  # Should not raise

    def test_validateRealtimeParameters_emptyParams_raisesError(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with no realtime parameters
        When: _validateRealtimeParameters is called
        Then: Raises ObdConfigError
        """
        validObdConfig['pi']['realtimeData']['parameters'] = []

        with pytest.raises(ObdConfigError) as excInfo:
            _validateRealtimeParameters(validObdConfig)

        assert 'No realtime data parameters' in str(excInfo.value)

    def test_validateRealtimeParameters_stringParams_convertsToDict(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Parameters as string list
        When: _validateRealtimeParameters is called
        Then: Strings are converted to dict format
        """
        validObdConfig['pi']['realtimeData']['parameters'] = ['RPM', 'SPEED']

        _validateRealtimeParameters(validObdConfig)

        params = validObdConfig['pi']['realtimeData']['parameters']
        assert isinstance(params[0], dict)
        assert params[0]['name'] == 'RPM'
        assert params[0]['logData'] is True

    def test_validateRealtimeParameters_missingName_raisesError(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Parameter dict without 'name' field
        When: _validateRealtimeParameters is called
        Then: Raises ObdConfigError
        """
        validObdConfig['pi']['realtimeData']['parameters'] = [
            {'logData': True}  # Missing 'name'
        ]

        with pytest.raises(ObdConfigError) as excInfo:
            _validateRealtimeParameters(validObdConfig)

        assert 'Invalid realtime parameter' in str(excInfo.value)


# ================================================================================
# Helper Function Tests
# ================================================================================

class TestHelperFunctions:
    """Tests for helper functions."""

    def test_getConfigSection_existingSection_returnsSection(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with pi section (top-level tier-aware)
        When: getConfigSection is called for 'pi'
        Then: Returns the pi section
        """
        result = getConfigSection(validObdConfig, 'pi')
        assert result['database']['path'] == validObdConfig['pi']['database']['path']

    def test_getConfigSection_missingSection_returnsEmptyDict(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config without requested section
        When: getConfigSection is called
        Then: Returns empty dict
        """
        result = getConfigSection(validObdConfig, 'nonexistent')
        assert result == {}

    def test_getActiveProfile_existingProfile_returnsProfile(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with active profile
        When: getActiveProfile is called
        Then: Returns active profile
        """
        result = getActiveProfile(validObdConfig)
        assert result is not None
        assert result['id'] == 'daily'

    def test_getActiveProfile_noProfiles_returnsNone(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with no profiles
        When: getActiveProfile is called
        Then: Returns None
        """
        validObdConfig['pi']['profiles']['availableProfiles'] = []
        result = getActiveProfile(validObdConfig)
        assert result is None

    def test_getLoggedParameters_mixedLogData_returnsOnlyLogged(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with mixed logData settings
        When: getLoggedParameters is called
        Then: Returns only parameters with logData=True
        """
        result = getLoggedParameters(validObdConfig)

        assert 'RPM' in result
        assert 'SPEED' in result
        assert 'COOLANT_TEMP' not in result  # logData is False

    def test_getLoggedParameters_emptyParams_returnsEmptyList(
        self,
        validObdConfig: dict[str, Any]
    ):
        """
        Given: Config with no parameters
        When: getLoggedParameters is called
        Then: Returns empty list
        """
        validObdConfig['pi']['realtimeData']['parameters'] = []
        result = getLoggedParameters(validObdConfig)
        assert result == []


# ================================================================================
# Edge Cases and Integration Tests
# ================================================================================

class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_allDisplayModes_areValid(self):
        """
        Given: VALID_DISPLAY_MODES constant
        When: Checking valid modes
        Then: Contains expected modes
        """
        assert 'headless' in VALID_DISPLAY_MODES
        assert 'minimal' in VALID_DISPLAY_MODES
        assert 'developer' in VALID_DISPLAY_MODES

    def test_requiredFields_areComplete(self):
        """
        Given: OBD_REQUIRED_FIELDS constant
        When: Checking required fields
        Then: Contains essential fields (tier-aware pi.* prefixes)
        """
        assert 'pi.database.path' in OBD_REQUIRED_FIELDS
        assert 'pi.bluetooth.macAddress' in OBD_REQUIRED_FIELDS
        assert 'pi.display.mode' in OBD_REQUIRED_FIELDS
        assert 'pi.realtimeData.parameters' in OBD_REQUIRED_FIELDS

    def test_defaults_coverAllSections(self):
        """
        Given: OBD_DEFAULTS constant
        When: Checking defaults
        Then: All major sections have defaults (tier-aware pi.* prefixes)
        """
        # Collect the second-level section names, since all keys are prefixed with pi./server.
        sections = set()
        for key in OBD_DEFAULTS.keys():
            parts = key.split('.')
            if len(parts) >= 2:
                sections.add(parts[1])

        assert 'application' in sections
        assert 'database' in sections
        assert 'bluetooth' in sections
        assert 'display' in sections
        assert 'analysis' in sections
        assert 'alerts' in sections

    def test_loadObdConfig_missingRequiredField_clearsErrorMessage(
        self,
        tmp_path: Path
    ):
        """
        Given: Config missing required bluetooth.macAddress
        When: loadObdConfig is called
        Then: Error message clearly indicates missing field
        """
        config = {
            'pi': {
                'database': {'path': './test.db'},
                'bluetooth': {},  # Missing macAddress
                'display': {'mode': 'headless'},
                'realtimeData': {'parameters': [{'name': 'RPM', 'logData': True}]}
            },
            'server': {'ai': {}, 'database': {}, 'api': {}}
        }
        configFile = tmp_path / 'incomplete.json'
        with open(configFile, 'w') as f:
            json.dump(config, f)

        with pytest.raises(ObdConfigError) as excInfo:
            loadObdConfig(str(configFile))

        assert 'pi.bluetooth.macAddress' in excInfo.value.missingFields

    def test_loadObdConfig_multipleProfiles_validatesAll(
        self,
        tmp_path: Path
    ):
        """
        Given: Config with multiple profiles
        When: loadObdConfig is called
        Then: All profiles are validated
        """
        config = {
            'pi': {
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
                        },
                        {
                            'id': 'performance',
                            'name': 'Performance',
                        }
                    ]
                }
            },
            'server': {'ai': {}, 'database': {}, 'api': {}}
        }
        configFile = tmp_path / 'multiprofile.json'
        with open(configFile, 'w') as f:
            json.dump(config, f)

        result = loadObdConfig(str(configFile))

        assert len(result['pi']['profiles']['availableProfiles']) == 2
        assert result['pi']['profiles']['activeProfile'] == 'performance'
