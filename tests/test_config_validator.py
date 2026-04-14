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

import sys
from pathlib import Path
from typing import Any

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from common.config.validator import ConfigValidationError, ConfigValidator, validateConfig


@pytest.fixture
def sampleConfig() -> dict[str, Any]:
    """
    Provide tier-aware sample configuration for validator tests.

    Overrides the flat-shape conftest.sampleConfig so these tests can
    exercise the sweep-4 validator, which requires pi: and server: top-level
    sections.
    """
    return {
        'protocolVersion': '1.0.0',
        'schemaVersion': '1.0.0',
        'deviceId': 'test-device',
        'logging': {
            'level': 'DEBUG',
            'maskPII': True
        },
        'pi': {
            'application': {
                'name': 'TestApp',
                'version': '1.0.0',
                'environment': 'test'
            },
            'database': {
                'server': 'localhost',
                'database': 'test_db',
                'user': 'test_user',
                'password': 'test_password',
                'port': 1433
            },
            'api': {
                'baseUrl': 'https://api.test.com',
                'auth': {
                    'type': 'oauth2',
                    'clientId': 'test_client',
                    'clientSecret': 'test_secret'
                },
                'timeouts': {
                    'connectTimeoutMs': 5000,
                    'readTimeoutMs': 10000
                },
                'retry': {
                    'maxRetries': 2,
                    'retryDelayMs': 100
                }
            },
        },
        'server': {
            'ai': {},
            'database': {},
            'api': {}
        }
    }


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

    def test_validate_validConfig_returnsConfig(self, sampleConfig: dict[str, Any]):
        """
        Given: Valid configuration
        When: validate() is called
        Then: Returns configuration with defaults applied
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate(sampleConfig)

        assert result is not None
        assert result['pi']['application']['name'] == 'TestApp'

    def test_validate_missingRequired_raisesError(self):
        """
        Given: Configuration missing required fields (with pi/server shape)
        When: validate() is called
        Then: Raises ConfigValidationError with missing fields
        """
        validator = ConfigValidator(requiredKeys=['pi.database.server'])
        config = {
            'pi': {'application': {'name': 'Test'}},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.database.server' in str(excInfo.value)
        assert 'pi.database.server' in excInfo.value.missingFields

    def test_validate_emptyConfig_appliesDefaults(self):
        """
        Given: Minimal tier-aware configuration
        When: validate() is called
        Then: Applies default values
        """
        validator = ConfigValidator(requiredKeys=[])
        result = validator.validate({
            'protocolVersion': '1.0.0',
            'schemaVersion': '1.0.0',
            'deviceId': 'test-device',
            'pi': {},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        })

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
        config: dict[str, Any] = {}

        validator._setNestedValue(config, 'database.server', 'localhost')

        assert config['database']['server'] == 'localhost'

    # =========================================================================
    # Field Validation Tests
    # =========================================================================

    def test_validateField_correctType_returnsTrue(self, sampleConfig: dict[str, Any]):
        """
        Given: Field with correct type
        When: validateField() is called
        Then: Returns True
        """
        validator = ConfigValidator()

        result = validator.validateField(
            sampleConfig,
            'pi.application.name',
            str
        )

        assert result is True

    def test_validateField_wrongType_returnsFalse(self, sampleConfig: dict[str, Any]):
        """
        Given: Field with wrong type
        When: validateField() is called
        Then: Returns False
        """
        validator = ConfigValidator()

        result = validator.validateField(
            sampleConfig,
            'pi.application.name',
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
        config: dict[str, Any] = {}

        result = validator.validateField(
            config,
            'missing.field',
            str,
            allowNone=True
        )

        assert result is True


class TestValidateConfigFunction:
    """Tests for the validateConfig convenience function."""

    def test_validateConfig_validInput_returnsConfig(self, sampleConfig: dict[str, Any]):
        """
        Given: Valid configuration
        When: validateConfig() is called
        Then: Returns validated configuration
        """
        result = validateConfig(sampleConfig)

        assert result is not None
        assert 'pi' in result
        assert 'application' in result['pi']


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
            'pi.database.server',
            'pi.database.name',
            'pi.api.baseUrl'
        ])
        config = {
            'pi': {'application': {'name': 'Test'}},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.database.server' in excInfo.value.missingFields
        assert 'pi.database.name' in excInfo.value.missingFields
        assert 'pi.api.baseUrl' in excInfo.value.missingFields
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
                'pi.level1.level2.level3.value': 'deep_default'
            }
        )
        config: dict[str, Any] = {
            'protocolVersion': '1.0.0',
            'schemaVersion': '1.0.0',
            'deviceId': 'test-device',
            'pi': {},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

        result = validator.validate(config)

        assert result['pi']['level1']['level2']['level3']['value'] == 'deep_default'

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
        config: dict[str, Any] = {}

        result = validator.validateField(
            config,
            'missing.field',
            str,
            allowNone=False
        )

        assert result is False

    def test_validate_existingValue_notOverwrittenByDefault(
        self,
        sampleConfig: dict[str, Any]
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
        # sampleConfig has logging.level = 'DEBUG' at the top level

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
        config: dict[str, Any] = {'database': {'host': 'localhost'}}

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
        config = {
            'pi': {'other': 'value'},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'name' in excInfo.value.missingFields

