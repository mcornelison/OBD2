################################################################################
# File Name: test_config_validator.py
# Purpose/Description: Tests for configuration validation
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-21    | M. Cornelison | Initial implementation
# ================================================================================
################################################################################

"""
Tests for the ConfigValidator class.

Run with:
    pytest tests/test_config_validator.py -v
"""

import pytest
from typing import Any, Dict

import sys
from pathlib import Path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from common.config_validator import (
    ConfigValidator,
    ConfigValidationError,
    validateConfig
)


class TestConfigValidator:
    """Tests for ConfigValidator class."""

    # =========================================================================
    # Initialization Tests
    # =========================================================================

    def test_init_defaultValues_usesModuleDefaults(self):
        """
        Given: No constructor arguments
        When: ConfigValidator is instantiated
        Then: Uses default required keys and defaults
        """
        validator = ConfigValidator()

        assert validator.requiredKeys is not None
        assert validator.defaults is not None

    def test_init_customValues_usesProvidedValues(self):
        """
        Given: Custom required keys and defaults
        When: ConfigValidator is instantiated
        Then: Uses provided values
        """
        customKeys = ['custom.field']
        customDefaults = {'custom.field': 'default_value'}

        validator = ConfigValidator(
            requiredKeys=customKeys,
            defaults=customDefaults
        )

        assert validator.requiredKeys == customKeys
        assert validator.defaults == customDefaults

    # =========================================================================
    # Validation Tests
    # =========================================================================

    def test_validate_validConfig_returnsConfig(self, sampleConfig: Dict[str, Any]):
        """
        Given: Valid configuration
        When: validate() is called
        Then: Returns configuration with defaults applied
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate(sampleConfig)

        assert result is not None
        assert result['application']['name'] == 'TestApp'

    def test_validate_missingRequired_raisesError(self):
        """
        Given: Configuration missing required fields
        When: validate() is called
        Then: Raises ConfigValidationError with missing fields
        """
        validator = ConfigValidator(requiredKeys=['database.server'])
        config = {'application': {'name': 'Test'}}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'database.server' in str(excInfo.value)
        assert 'database.server' in excInfo.value.missingFields

    def test_validate_emptyConfig_appliesDefaults(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: Applies default values
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        # Should have defaults applied
        assert result.get('logging', {}).get('level') == 'INFO'

    # =========================================================================
    # Nested Value Tests
    # =========================================================================

    def test_getNestedValue_existingKey_returnsValue(self):
        """
        Given: Config with nested structure
        When: _getNestedValue() is called with valid path
        Then: Returns the value
        """
        validator = ConfigValidator()
        config = {'database': {'server': 'localhost'}}

        result = validator._getNestedValue(config, 'database.server')

        assert result == 'localhost'

    def test_getNestedValue_missingKey_returnsNone(self):
        """
        Given: Config without requested path
        When: _getNestedValue() is called
        Then: Returns None
        """
        validator = ConfigValidator()
        config = {'database': {}}

        result = validator._getNestedValue(config, 'database.server')

        assert result is None

    def test_setNestedValue_newPath_createsStructure(self):
        """
        Given: Empty config
        When: _setNestedValue() is called
        Then: Creates nested structure and sets value
        """
        validator = ConfigValidator()
        config: Dict[str, Any] = {}

        validator._setNestedValue(config, 'database.server', 'localhost')

        assert config['database']['server'] == 'localhost'

    # =========================================================================
    # Field Validation Tests
    # =========================================================================

    def test_validateField_correctType_returnsTrue(self, sampleConfig: Dict[str, Any]):
        """
        Given: Field with correct type
        When: validateField() is called
        Then: Returns True
        """
        validator = ConfigValidator()

        result = validator.validateField(
            sampleConfig,
            'application.name',
            str
        )

        assert result is True

    def test_validateField_wrongType_returnsFalse(self, sampleConfig: Dict[str, Any]):
        """
        Given: Field with wrong type
        When: validateField() is called
        Then: Returns False
        """
        validator = ConfigValidator()

        result = validator.validateField(
            sampleConfig,
            'application.name',
            int
        )

        assert result is False

    def test_validateField_missingAllowNone_returnsTrue(self):
        """
        Given: Missing field with allowNone=True
        When: validateField() is called
        Then: Returns True
        """
        validator = ConfigValidator()
        config: Dict[str, Any] = {}

        result = validator.validateField(
            config,
            'missing.field',
            str,
            allowNone=True
        )

        assert result is True


class TestValidateConfigFunction:
    """Tests for the validateConfig convenience function."""

    def test_validateConfig_validInput_returnsConfig(self, sampleConfig: Dict[str, Any]):
        """
        Given: Valid configuration
        When: validateConfig() is called
        Then: Returns validated configuration
        """
        result = validateConfig(sampleConfig)

        assert result is not None
        assert 'application' in result


class TestConfigValidationError:
    """Tests for ConfigValidationError exception."""

    def test_init_withMessage_storesMessage(self):
        """
        Given: Error message
        When: ConfigValidationError is created
        Then: Message is accessible
        """
        error = ConfigValidationError("Test error message")

        assert str(error) == "Test error message"

    def test_init_withMissingFields_storesFields(self):
        """
        Given: Error with missing fields list
        When: ConfigValidationError is created
        Then: Missing fields are accessible
        """
        missingFields = ['field1', 'field2']
        error = ConfigValidationError("Test error", missingFields=missingFields)

        assert error.missingFields == missingFields

    def test_init_noMissingFields_defaultsToEmptyList(self):
        """
        Given: Error without missing fields
        When: ConfigValidationError is created
        Then: missingFields defaults to empty list
        """
        error = ConfigValidationError("Test error")

        assert error.missingFields == []


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_validate_multipleRequiredFieldsMissing_listsAllMissing(self):
        """
        Given: Configuration missing multiple required fields
        When: validate() is called
        Then: All missing fields are listed in error
        """
        validator = ConfigValidator(requiredKeys=[
            'database.server',
            'database.name',
            'api.baseUrl'
        ])
        config = {'application': {'name': 'Test'}}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'database.server' in excInfo.value.missingFields
        assert 'database.name' in excInfo.value.missingFields
        assert 'api.baseUrl' in excInfo.value.missingFields
        assert len(excInfo.value.missingFields) == 3

    def test_validate_deeplyNestedConfig_handlesCorrectly(self):
        """
        Given: Configuration with deeply nested structure
        When: validate() is called
        Then: Defaults are applied at all nesting levels
        """
        validator = ConfigValidator(
            requiredKeys=[],
            defaults={
                'level1.level2.level3.value': 'deep_default'
            }
        )
        config: Dict[str, Any] = {}

        result = validator.validate(config)

        assert result['level1']['level2']['level3']['value'] == 'deep_default'

    def test_getNestedValue_emptyString_returnsEmptyString(self):
        """
        Given: Config with empty string value
        When: _getNestedValue() is called
        Then: Returns empty string (not None)
        """
        validator = ConfigValidator()
        config = {'field': {'name': ''}}

        result = validator._getNestedValue(config, 'field.name')

        assert result == ''

    def test_validateField_noneValue_allowNoneFalse_returnsFalse(self):
        """
        Given: Missing field with allowNone=False
        When: validateField() is called
        Then: Returns False
        """
        validator = ConfigValidator()
        config: Dict[str, Any] = {}

        result = validator.validateField(
            config,
            'missing.field',
            str,
            allowNone=False
        )

        assert result is False

    def test_validate_existingValue_notOverwrittenByDefault(
        self,
        sampleConfig: Dict[str, Any]
    ):
        """
        Given: Config with existing value for a default key
        When: validate() is called
        Then: Existing value is preserved, not overwritten
        """
        validator = ConfigValidator(
            requiredKeys=[],
            defaults={'logging.level': 'INFO'}
        )
        # sampleConfig has logging.level = 'DEBUG'

        result = validator.validate(sampleConfig)

        # Should keep DEBUG, not overwrite with INFO default
        assert result['logging']['level'] == 'DEBUG'

    def test_setNestedValue_existingPartialPath_extendsCorrectly(self):
        """
        Given: Config with partial path existing
        When: _setNestedValue() is called
        Then: Extends existing structure without overwriting
        """
        validator = ConfigValidator()
        config: Dict[str, Any] = {'database': {'host': 'localhost'}}

        validator._setNestedValue(config, 'database.port', 5432)

        assert config['database']['host'] == 'localhost'
        assert config['database']['port'] == 5432

    def test_validate_singleLevelKey_worksCorrectly(self):
        """
        Given: Required key at root level (no dots)
        When: validate() is called with missing root key
        Then: Raises error with correct missing field
        """
        validator = ConfigValidator(requiredKeys=['name'])
        config = {'other': 'value'}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'name' in excInfo.value.missingFields


class TestHardwareConfigDefaults:
    """Tests for hardware configuration defaults."""

    # =========================================================================
    # Hardware Enabled Tests
    # =========================================================================

    def test_validate_emptyConfig_appliesHardwareEnabled(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.enabled defaults to True
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['enabled'] is True

    # =========================================================================
    # I2C Configuration Tests
    # =========================================================================

    def test_validate_emptyConfig_appliesI2cBusDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.i2c.bus defaults to 1
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['i2c']['bus'] == 1

    def test_validate_emptyConfig_appliesI2cUpsAddressDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.i2c.upsAddress defaults to 0x36
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['i2c']['upsAddress'] == 0x36

    def test_validate_customI2cAddress_preservesValue(self):
        """
        Given: Configuration with custom I2C UPS address
        When: validate() is called
        Then: Custom value is preserved
        """
        validator = ConfigValidator(requiredKeys=[])
        config = {'hardware': {'i2c': {'upsAddress': 0x57}}}
        result = validator.validate(config)

        assert result['hardware']['i2c']['upsAddress'] == 0x57

    # =========================================================================
    # GPIO Configuration Tests
    # =========================================================================

    def test_validate_emptyConfig_appliesGpioShutdownButtonDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.gpio.shutdownButton defaults to 17
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['gpio']['shutdownButton'] == 17

    def test_validate_emptyConfig_appliesGpioStatusLedDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.gpio.statusLed defaults to 27
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['gpio']['statusLed'] == 27

    def test_validate_customGpioPins_preservesValues(self):
        """
        Given: Configuration with custom GPIO pins
        When: validate() is called
        Then: Custom values are preserved
        """
        validator = ConfigValidator(requiredKeys=[])
        config = {
            'hardware': {
                'gpio': {
                    'shutdownButton': 22,
                    'statusLed': 23
                }
            }
        }
        result = validator.validate(config)

        assert result['hardware']['gpio']['shutdownButton'] == 22
        assert result['hardware']['gpio']['statusLed'] == 23

    # =========================================================================
    # UPS Configuration Tests
    # =========================================================================

    def test_validate_emptyConfig_appliesUpsPollIntervalDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.ups.pollInterval defaults to 5
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['ups']['pollInterval'] == 5

    def test_validate_emptyConfig_appliesUpsShutdownDelayDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.ups.shutdownDelay defaults to 30
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['ups']['shutdownDelay'] == 30

    def test_validate_emptyConfig_appliesUpsLowBatteryThresholdDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.ups.lowBatteryThreshold defaults to 10
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['ups']['lowBatteryThreshold'] == 10

    def test_validate_customUpsSettings_preservesValues(self):
        """
        Given: Configuration with custom UPS settings
        When: validate() is called
        Then: Custom values are preserved
        """
        validator = ConfigValidator(requiredKeys=[])
        config = {
            'hardware': {
                'ups': {
                    'pollInterval': 10,
                    'shutdownDelay': 60,
                    'lowBatteryThreshold': 15
                }
            }
        }
        result = validator.validate(config)

        assert result['hardware']['ups']['pollInterval'] == 10
        assert result['hardware']['ups']['shutdownDelay'] == 60
        assert result['hardware']['ups']['lowBatteryThreshold'] == 15

    # =========================================================================
    # Display Configuration Tests
    # =========================================================================

    def test_validate_emptyConfig_appliesDisplayEnabledDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.display.enabled defaults to True
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['display']['enabled'] is True

    def test_validate_emptyConfig_appliesDisplayRefreshRateDefault(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: hardware.display.refreshRate defaults to 2
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        assert result['hardware']['display']['refreshRate'] == 2

    def test_validate_customDisplaySettings_preservesValues(self):
        """
        Given: Configuration with custom display settings
        When: validate() is called
        Then: Custom values are preserved
        """
        validator = ConfigValidator(requiredKeys=[])
        config = {
            'hardware': {
                'display': {
                    'enabled': False,
                    'refreshRate': 5
                }
            }
        }
        result = validator.validate(config)

        assert result['hardware']['display']['enabled'] is False
        assert result['hardware']['display']['refreshRate'] == 5

    # =========================================================================
    # Full Hardware Section Tests
    # =========================================================================

    def test_validate_emptyConfig_appliesAllHardwareDefaults(self):
        """
        Given: Empty configuration
        When: validate() is called
        Then: All hardware defaults are applied
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({})

        # Verify all hardware defaults are present
        assert result['hardware']['enabled'] is True
        assert result['hardware']['i2c']['bus'] == 1
        assert result['hardware']['i2c']['upsAddress'] == 0x36
        assert result['hardware']['gpio']['shutdownButton'] == 17
        assert result['hardware']['gpio']['statusLed'] == 27
        assert result['hardware']['ups']['pollInterval'] == 5
        assert result['hardware']['ups']['shutdownDelay'] == 30
        assert result['hardware']['ups']['lowBatteryThreshold'] == 10
        assert result['hardware']['display']['enabled'] is True
        assert result['hardware']['display']['refreshRate'] == 2

    def test_validate_partialHardwareConfig_mergesWithDefaults(self):
        """
        Given: Configuration with partial hardware settings
        When: validate() is called
        Then: Missing values are filled from defaults
        """
        validator = ConfigValidator(requiredKeys=[])
        config = {
            'hardware': {
                'enabled': False,
                'ups': {
                    'shutdownDelay': 45
                }
            }
        }
        result = validator.validate(config)

        # Custom values preserved
        assert result['hardware']['enabled'] is False
        assert result['hardware']['ups']['shutdownDelay'] == 45

        # Defaults applied for missing values
        assert result['hardware']['i2c']['bus'] == 1
        assert result['hardware']['gpio']['shutdownButton'] == 17
        assert result['hardware']['display']['refreshRate'] == 2
