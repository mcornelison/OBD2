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
# 2026-05-15    | Plan (T7)     | Add bootProgress defaults + non-positive
#                                 poweroffTimeoutSeconds rejection tests.
# 2026-05-18    | Plan (SS-T2)  | Add smoothingSec/smoothingPollSec defaults +
#                                 non-positive smoothingSec rejection test;
#                                 assert confirm* deprecated alias still
#                                 resolves (additive, no broken intermediate).
# 2026-05-19    | Plan (SS-T5)  | T2 alias DEATH: assertion flipped to assert
#                                 confirm* are GONE from cfg (the stated
#                                 death date arrived; rename completed).
# 2026-09-22    | Rex (US-801)  | IMU rate pins assert against the single
#                                 definition, not a second literal.
# 2026-10-03    | Atlas (ARCH-065a) | ARCH-065 T3: joinWaitSec/stallSec defaults + validation replace shutdownSyncCeilingSec.
# 2026-10-03    | Atlas (ARCH-065a) | Ruling 19 (M8): drainFloorDwellReads must be an integer >= 1.
# 2026-10-13    | Atlas (ARCH-068) | joinWaitSec default 120 -> 30 (CIO 2026-10-12).
# 2026-10-14    | Rex (US-882-a) | pi.imu.peaks.smoothingSec default + positivity.
# 2026-10-14    | Rex (US-882-b) | pi.display.gradeHistory.{intervalSec,windowSec}.
# 2026-10-14    | Rex (US-880-a) | pi.trip.gapSec default 300 + positivity.
# 2026-10-14    | Rex (US-882-c) | pi.display.stale.imuSec default 2.0 + positivity.
# 2026-10-14    | Rex (US-881-b) | pi.fuel.* defaults (Spool, sourced) + range checks.
# 2026-10-14    | Rex (US-881-c) | pi.fuel.persistSec default 60 + positivity.
# 2026-10-14    | Rex (US-881-d) | pi.fuel.resetTimeoutSec default 5 + positivity.
# 2026-10-15    | Rex (US-889-a) | pi.display.engineHistory.{intervalSec,maxPoints}.
# 2026-10-15    | Rex (US-890-b) | pi.display.scale.mafMaxGs default 160 + positivity.
# 2026-10-15    | Rex (US-890-e) | pi.fuel.recent* defaults (Spool) + positivity.
# 2026-10-18    | Rex (US-890-f) | pi.display.stale.fuelResetConfirmSec default 6 +
#                                positivity.
# 2026-10-18    | Rex (US-896-a) | pi.display.stale.imuSec default pin 2.0 -> 3.0.
# 2026-10-20    | Rex (US-897-c) | pi.warnings.ackTimeoutSec 5 + finite > 0;
#                                pi.warnings.ackStorePath default + non-empty.
# 2026-10-20    | Rex (US-899-a1)| pi.display.stale.alertsAckConfirmSec 6 /
#                                alertsAckNoticeSec 3 + finite > 0.
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

from common.config.validator import (
    DEFAULT_GRADE_HISTORY_INTERVAL_SEC,
    DEFAULT_GRADE_HISTORY_WINDOW_SEC,
    DEFAULT_IMU_PEAKS_SMOOTHING_SEC,
    DEFAULT_IMU_PERSIST_HZ,
    DEFAULT_IMU_SAMPLE_HZ,
    ConfigValidationError,
    ConfigValidator,
    validateConfig,
)


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


class TestCompanionServiceConfig:
    """
    Tests for the pi.companionService config surface (US-151).

    Covers: defaults applied, explicit values accepted, malformed values
    rejected with ConfigValidationError.
    """

    def _minimalTierConfig(self) -> dict[str, Any]:
        """Bare-minimum tier-aware config the validator will accept."""
        return {
            'protocolVersion': '1.0.0',
            'schemaVersion': '1.0.0',
            'deviceId': 'test-device',
            'pi': {},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

    def test_companionService_missing_defaultsApplied(self):
        """
        Given: Config without a pi.companionService section
        When: validate() is called
        Then: All seven companionService keys are populated with spec defaults
        """
        validator = ConfigValidator(requiredKeys=[])

        result = validator.validate(self._minimalTierConfig())

        cs = result['pi']['companionService']
        assert cs['enabled'] is True
        assert cs['baseUrl'] == 'http://10.27.27.120:8000'
        assert cs['apiKeyEnv'] == 'COMPANION_API_KEY'
        assert cs['syncTimeoutSeconds'] == 30
        assert cs['batchSize'] == 500
        assert cs['retryMaxAttempts'] == 3
        assert cs['retryBackoffSeconds'] == [1, 2, 4, 8, 16]
        # US-391: queue-level quarantine defaults.
        assert cs['quarantineThreshold'] == 5
        assert cs['quarantineThrottleSeconds'] == 3600

    def test_companionService_quarantineThreshold_belowOne_raises(self):
        """US-391: a quarantineThreshold < 1 is rejected at load time."""
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'quarantineThreshold': 0}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.companionService.quarantineThreshold' in excInfo.value.missingFields

    def test_companionService_quarantineThrottle_nonPositive_raises(self):
        """US-391: a non-positive quarantineThrottleSeconds is rejected."""
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'quarantineThrottleSeconds': 0}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert (
            'pi.companionService.quarantineThrottleSeconds'
            in excInfo.value.missingFields
        )

    def test_companionService_fullyPopulated_roundTripPreserved(self):
        """
        Given: Config with an explicit pi.companionService section
        When: validate() is called
        Then: All explicit values are preserved (defaults don't overwrite)
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {
            'enabled': False,
            'baseUrl': 'http://192.168.1.50:9000',
            'apiKeyEnv': 'ALT_API_KEY',
            'syncTimeoutSeconds': 45,
            'batchSize': 250,
            'retryMaxAttempts': 5,
            'retryBackoffSeconds': [2, 4, 8],
        }

        result = validator.validate(config)

        cs = result['pi']['companionService']
        assert cs['enabled'] is False
        assert cs['baseUrl'] == 'http://192.168.1.50:9000'
        assert cs['apiKeyEnv'] == 'ALT_API_KEY'
        assert cs['syncTimeoutSeconds'] == 45
        assert cs['batchSize'] == 250
        assert cs['retryMaxAttempts'] == 5
        assert cs['retryBackoffSeconds'] == [2, 4, 8]

    def test_companionService_negativeTimeout_raises(self):
        """
        Given: syncTimeoutSeconds < 0
        When: validate() is called
        Then: ConfigValidationError names the offending field
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'syncTimeoutSeconds': -1}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'syncTimeoutSeconds' in str(excInfo.value)
        assert 'pi.companionService.syncTimeoutSeconds' in excInfo.value.missingFields

    def test_companionService_zeroTimeout_raises(self):
        """
        Given: syncTimeoutSeconds == 0
        When: validate() is called
        Then: Rejected — a zero-second timeout would fail every request instantly
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'syncTimeoutSeconds': 0}

        with pytest.raises(ConfigValidationError):
            validator.validate(config)

    def test_companionService_zeroBatchSize_raises(self):
        """
        Given: batchSize < 1
        When: validate() is called
        Then: Rejected — batch of 0 rows is meaningless
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'batchSize': 0}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'batchSize' in str(excInfo.value)

    def test_companionService_negativeBatchSize_raises(self):
        """
        Given: batchSize < 0
        When: validate() is called
        Then: Rejected
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'batchSize': -5}

        with pytest.raises(ConfigValidationError):
            validator.validate(config)

    def test_companionService_nonListBackoff_raises(self):
        """
        Given: retryBackoffSeconds is a string (not a list)
        When: validate() is called
        Then: ConfigValidationError names the offending field
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'retryBackoffSeconds': '1,2,4'}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'retryBackoffSeconds' in str(excInfo.value)
        assert 'pi.companionService.retryBackoffSeconds' in excInfo.value.missingFields

    def test_companionService_dictBackoff_raises(self):
        """
        Given: retryBackoffSeconds is a dict (not a list)
        When: validate() is called
        Then: Rejected
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {
            'retryBackoffSeconds': {'first': 1, 'second': 2},
        }

        with pytest.raises(ConfigValidationError):
            validator.validate(config)

    def test_companionService_negativeRetryMax_raises(self):
        """
        Given: retryMaxAttempts is negative
        When: validate() is called
        Then: Rejected
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'retryMaxAttempts': -1}

        with pytest.raises(ConfigValidationError):
            validator.validate(config)

    def test_companionService_boolTimeout_raises(self):
        """
        Given: syncTimeoutSeconds is bool (True or False)
        When: validate() is called
        Then: Rejected — bool subclasses int in Python but must not sneak
              through numeric checks as 1/0 seconds
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['companionService'] = {'syncTimeoutSeconds': True}

        with pytest.raises(ConfigValidationError):
            validator.validate(config)

    def test_validateConfig_withCompanionService_liveConfigJsonShape(self):
        """
        Given: The shape of pi.companionService that lives in config.json
        When: validateConfig() is called
        Then: The section round-trips cleanly (guard against config.json
              drift vs. validator defaults)
        """
        config = {
            'protocolVersion': '1.0.0',
            'schemaVersion': '1.0.0',
            'deviceId': 'chi-eclipse-01',
            'pi': {
                'companionService': {
                    'enabled': True,
                    'baseUrl': 'http://10.27.27.120:8000',
                    'apiKeyEnv': 'COMPANION_API_KEY',
                    'syncTimeoutSeconds': 30,
                    'batchSize': 500,
                    'retryMaxAttempts': 3,
                    'retryBackoffSeconds': [1, 2, 4, 8, 16],
                },
            },
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

        result = validateConfig(config)

        cs = result['pi']['companionService']
        assert cs['baseUrl'] == 'http://10.27.27.120:8000'
        assert cs['retryBackoffSeconds'] == [1, 2, 4, 8, 16]

    # ------------------------------------------------------------------
    # US-392 (A-15 de-dup): base URLs derive from serverHost:serverPort.
    # ------------------------------------------------------------------
    def test_companionService_baseUrl_derivedFromServerHostPort_whenAbsent(self):
        """
        Given: a config with an explicit server.network.serverHost/serverPort
               but NO pi.companionService.baseUrl
        When: validate() is called
        Then: pi.companionService.baseUrl is DERIVED as http://{host}:{port}
              (single-source de-dup -- the host literal is not duplicated)
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['server']['network'] = {'serverHost': '10.0.0.5', 'serverPort': 9999}

        result = validator.validate(config)

        assert result['pi']['companionService']['baseUrl'] == 'http://10.0.0.5:9999'

    def test_serverBaseUrl_derivedFromServerHostPort_whenAbsent(self):
        """
        Given: a config with server.network.serverHost/serverPort but no
               server.network.serverBaseUrl
        When: validate() is called
        Then: server.network.serverBaseUrl is DERIVED as http://{host}:{port}
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['server']['network'] = {'serverHost': '10.0.0.5', 'serverPort': 9999}

        result = validator.validate(config)

        assert result['server']['network']['serverBaseUrl'] == 'http://10.0.0.5:9999'

    def test_baseUrl_explicitValue_notOverriddenByDerivation(self):
        """
        Given: an explicit companionService.baseUrl AND a different serverHost
        When: validate() is called
        Then: the explicit baseUrl wins (derivation only fills an ABSENT URL --
              addresses.sh ``:-`` fallback semantics; behavior-preserving)
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['server']['network'] = {'serverHost': '10.0.0.5', 'serverPort': 9999}
        config['pi']['companionService'] = {'baseUrl': 'http://192.168.1.50:9000'}

        result = validator.validate(config)

        assert result['pi']['companionService']['baseUrl'] == 'http://192.168.1.50:9000'

    def test_companionService_baseUrl_derivedFromDefaultServerHost(self):
        """
        Given: a config with no server.network section at all
        When: validate() is called
        Then: serverHost/serverPort DEFAULTS supply the single source and the
              companion baseUrl derives to the production address (the literal
              lives only in the validator DEFAULTS registry + config.json)
        """
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()  # server has no network section

        result = validator.validate(config)

        assert result['pi']['companionService']['baseUrl'] == 'http://10.27.27.120:8000'
        assert result['server']['network']['serverHost'] == '10.27.27.120'
        assert result['server']['network']['serverPort'] == 8000


class TestHomeNetworkConfig:
    """
    Tests for the pi.homeNetwork config surface (US-188, B-043 building block).

    Covers: defaults applied, explicit values accepted, malformed values
    rejected with ConfigValidationError.
    """

    def _minimalTierConfig(self) -> dict[str, Any]:
        return {
            'protocolVersion': '1.0.0',
            'schemaVersion': '1.0.0',
            'deviceId': 'test-device',
            'pi': {},
            'server': {'ai': {}, 'database': {}, 'api': {}},
        }

    def test_homeNetwork_missing_defaultsApplied(self):
        """
        Given: Config without a pi.homeNetwork section
        When: validate() is called
        Then: All four keys populated with spec defaults
        """
        validator = ConfigValidator(requiredKeys=[])

        result = validator.validate(self._minimalTierConfig())

        hn = result['pi']['homeNetwork']
        assert hn['ssid'] == 'DeathStarWiFi'
        assert hn['subnet'] == '10.27.27.0/24'
        assert hn['pingTimeoutSeconds'] == 3
        assert hn['serverPingPath'] == '/api/v1/health'

    def test_homeNetwork_fullyPopulated_roundTripPreserved(self):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {
            'ssid': 'AlternateWiFi',
            'subnet': '192.168.50.0/24',
            'pingTimeoutSeconds': 5,
            'serverPingPath': '/custom/health',
        }

        result = validator.validate(config)

        hn = result['pi']['homeNetwork']
        assert hn['ssid'] == 'AlternateWiFi'
        assert hn['subnet'] == '192.168.50.0/24'
        assert hn['pingTimeoutSeconds'] == 5
        assert hn['serverPingPath'] == '/custom/health'

    def test_homeNetwork_emptySsid_raises(self):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'ssid': '   '}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.ssid' in excInfo.value.missingFields

    def test_homeNetwork_invalidCidr_raises(self):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'subnet': 'not-a-cidr'}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.subnet' in excInfo.value.missingFields

    def test_homeNetwork_zeroPingTimeout_raises(self):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'pingTimeoutSeconds': 0}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.pingTimeoutSeconds' in excInfo.value.missingFields

    def test_homeNetwork_boolPingTimeout_raises(self):
        """bool subclasses int; must be explicitly rejected like the
        companion-service guard."""
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'pingTimeoutSeconds': True}

        with pytest.raises(ConfigValidationError):
            validator.validate(config)

    def test_homeNetwork_relativePingPath_raises(self):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'serverPingPath': 'api/v1/ping'}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.serverPingPath' in excInfo.value.missingFields

    def test_homeNetwork_syncWaits_defaults(self):
        """ARCH-065: join wait 30 s (CIO 2026-10-12), stall 60 s; the retired ceiling is gone."""
        validator = ConfigValidator(requiredKeys=[])

        result = validator.validate(self._minimalTierConfig())

        assert result['pi']['homeNetwork']['joinWaitSec'] == 30
        assert result['pi']['homeNetwork']['stallSec'] == 60
        assert 'shutdownSyncCeilingSec' not in result['pi']['homeNetwork']

    @pytest.mark.parametrize('key', ['joinWaitSec', 'stallSec'])
    @pytest.mark.parametrize('badValue', [0, -5, -0.5, True, '60', [60]])
    def test_homeNetwork_badSyncWait_raises(self, key, badValue):
        """ARCH-065: a non-positive or non-numeric join/stall wait is rejected."""
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {key: badValue}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert f'pi.homeNetwork.{key}' in excInfo.value.missingFields

    def test_homeNetwork_sweepTimeout_defaultsBelowSmoothing(self):
        """US-776-j1: a config with no powerWatch section validates with the
        sweep bound 6 s and smoothingSec 7 -> accepted (6 < 7)."""
        validator = ConfigValidator(requiredKeys=[])

        result = validator.validate(self._minimalTierConfig())

        assert result['pi']['homeNetwork']['sweepTimeoutSec'] == 6
        assert result['pi']['powerWatch']['smoothingSec'] == 7

    def test_homeNetwork_sweepTimeoutNotBelowSmoothing_raises(self):
        """US-776-j1: the sweep must fit inside the loss window, so a sweep
        bound equal to smoothingSec (7 vs 7) is refused."""
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'sweepTimeoutSec': 7}
        config['pi']['powerWatch'] = {'smoothingSec': 7}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.sweepTimeoutSec' in excInfo.value.missingFields
        assert 'smoothingSec' in str(excInfo.value)

    def test_homeNetwork_sweepTimeoutAboveSmoothing_raises(self):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'sweepTimeoutSec': 5}
        config['pi']['powerWatch'] = {'smoothingSec': 4}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.sweepTimeoutSec' in excInfo.value.missingFields

    @pytest.mark.parametrize('badValue', [0, -1, -0.5, True, '6', [6]])
    def test_homeNetwork_badSweepTimeout_raises(self, badValue):
        validator = ConfigValidator(requiredKeys=[])
        config = self._minimalTierConfig()
        config['pi']['homeNetwork'] = {'sweepTimeoutSec': badValue}

        with pytest.raises(ConfigValidationError) as excInfo:
            validator.validate(config)

        assert 'pi.homeNetwork.sweepTimeoutSec' in excInfo.value.missingFields


def test_configJson_sweepTimeout_equalsTheValidatorDefault_andValidates():
    """US-776-j1: config.json carries the sweep bound as a key, equal to the
    validator default, and the live file's pair is accepted (6 < 7)."""
    import json

    from common.config.validator import DEFAULTS

    live = json.loads(_CONFIG_JSON.read_text(encoding='utf-8'))
    assert (
        live['pi']['homeNetwork']['sweepTimeoutSec']
        == DEFAULTS['pi.homeNetwork.sweepTimeoutSec']
    )
    assert live['pi']['homeNetwork']['sweepTimeoutSec'] < live['pi']['powerWatch']['smoothingSec']


_CONFIG_JSON = Path(__file__).parent.parent / 'config.json'


def _baseCfg():
    return {"protocolVersion": "1", "schemaVersion": "1", "deviceId": "d",
            "pi": {}, "server": {}}


def test_bootProgress_defaultsApplied():
    cfg = ConfigValidator().validate(_baseCfg())
    bp = cfg["pi"]["bootProgress"]
    assert bp["filePath"] == "data/boot_progress"
    # The Pi is standalone (CIO 2026-08-26): it reaches only the OBD2 server, at
    # sync. This assertion used to read `is True`, pinning an archive that
    # defaulted ON and wrote to a NAS path -- so the unsafe default was not
    # merely unguarded, it was LOCKED IN by this line.
    assert bp["nasArchiveEnabled"] is False
    # The path was never asserted here at all, which is how it stayed
    # /mnt/projects/O/OBD2v2/boot-progress. Relative = resolves on the Pi.
    assert bp["nasArchiveDir"] == "data/boot_progress_archive"
    assert bp["maxTrailBytes"] == 65536
    assert cfg["pi"]["shutdown"]["poweroffTimeoutSeconds"] == 30


def test_bootProgress_rejectsNonPositiveTimeout():
    cfg = _baseCfg()
    cfg["pi"] = {"shutdown": {"poweroffTimeoutSeconds": 0}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(cfg)


def test_powerWatch_defaults_applied():
    cfg = ConfigValidator().validate(_baseCfg())
    pw = cfg["pi"]["powerWatch"]
    assert pw["perTaskTimeoutSec"] == 20
    assert pw["totalWindowCapSec"] == 45
    assert pw["vcellFloorVolts"] == 3.50
    assert pw["poweroffTimeoutSec"] == 30


def test_display_staleObdLiveSec_defaultsToFive():
    """US-874: the states/obd-live stale window is a validated key, default 5 s
    (Atlas 2026-10-13: 1.7x the measured per-PID p99 gap), and it matches the
    producer's mirror constant."""
    from pi.obdii.obd_live_emitter import DEFAULT_OBD_LIVE_STALE_S

    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["display"]["stale"]["obdLiveSec"] == 5
    assert DEFAULT_OBD_LIVE_STALE_S == 5


def test_bands_defaults_areSpoolsAndTheCiosNumbers():
    """US-875: every pi.bands.* default, as the story and its sources name them."""
    cfg = ConfigValidator().validate(_baseCfg())
    bands = cfg["pi"]["bands"]
    assert bands["coolant"] == {
        "amberC": 104, "amberDwellSec": 30, "redC": 110,
        "redDwellSec": 120, "clearBelowC": 102, "clearHoldSec": 10,
        # US-897-b1 (Spool 2026-10-14): red run-up guard and red's own clear.
        "redGuardPrevMinC": 100, "redClearBelowC": 101, "redClearHoldSec": 60,
    }
    assert bands["battery"] == {
        "rpmMaxAgeSec": 3.0, "runningRpmMin": 500, "crankGuardSec": 3,
        "greenMinV": 13.5, "greenMaxV": 14.5, "redBelowV": 12.0, "redAboveV": 15.0,
    }
    assert bands["rpm"] == {"amberRpm": 5500, "redRpm": 7000}


def test_bands_noBatteryAmberKey():
    """US-875 / CIO R38: RED and GREEN only this sprint -- no amber key exists."""
    from common.config.validator import DEFAULTS

    assert not [k for k in DEFAULTS if k.startswith("pi.bands.battery.") and "amber" in k]


def test_bands_eachDefaultCitesItsSource():
    """US-875: each band default carries a comment with its source."""
    import inspect

    import common.config.validator as v

    source = inspect.getsource(v)
    for needle in (
        "grounded-knowledge :75, Spool 2026-10-13",
        "grounded-knowledge :368-374",
        "32,241 RPM samples",
        "gear staleness rule",
        "measured N=1 (drive 87 restart 2026-09-26",
        "not proven",
        "RPM row (:84)",
    ):
        assert needle in source, needle
    # US-897-b1: each red guard / red clear key cites Spool 2026-10-14 ON ITS OWN
    # line (the date alone already appears elsewhere in the module).
    for key in ("redGuardPrevMinC", "redClearBelowC", "redClearHoldSec"):
        lines = [ln for ln in source.splitlines() if f"'pi.bands.coolant.{key}':" in ln]
        assert len(lines) == 1, key
        assert "Spool 2026-10-14" in lines[0], key


@pytest.mark.parametrize(
    ("section", "key", "badValue"),
    [
        ("coolant", "amberC", 0),
        ("coolant", "amberDwellSec", -1),
        ("battery", "rpmMaxAgeSec", "3"),
        ("battery", "crankGuardSec", True),
        ("rpm", "redRpm", -7000),
    ],
)
def test_bands_rejectsANonPositiveOrNonNumericValue(section, key, badValue):
    bad = _baseCfg()
    bad["pi"] = {"bands": {section: {key: badValue}}}
    with pytest.raises(ConfigValidationError, match=f"pi.bands.{section}.{key}"):
        ConfigValidator().validate(bad)


@pytest.mark.parametrize(
    ("section", "overrides"),
    [
        ("coolant", {"clearBelowC": 104}),
        ("coolant", {"redC": 103}),
        ("coolant", {"redDwellSec": 30}),
        # US-897-b1 (Spool 2026-10-19): redGuardPrevMinC < redC, redClearBelowC
        # < redC, redClearBelowC < amberC.
        ("coolant", {"redGuardPrevMinC": 110}),
        ("coolant", {"redClearBelowC": 110}),
        ("coolant", {"redClearBelowC": 104}),
        ("battery", {"redBelowV": 13.5}),
        ("battery", {"greenMinV": 14.6}),
        ("battery", {"redAboveV": 14.5}),
        ("rpm", {"amberRpm": 7000}),
    ],
)
def test_bands_rejectsMisorderedEdges(section, overrides):
    bad = _baseCfg()
    bad["pi"] = {"bands": {section: overrides}}
    with pytest.raises(ConfigValidationError, match="must be"):
        ConfigValidator().validate(bad)


def test_warnings_coolantRedTier_defaultsToStop_underPiWarningsNeverPiAlerts():
    """US-897-b2: the coolant STOP tier is pi.warnings.engine.COOLANT_TEMP.redTier
    'stop' in validator DEFAULTS -- never pi.alerts.* (the legacy AlertManager's)."""
    from common.config.validator import DEFAULTS

    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["warnings"]["engine"]["COOLANT_TEMP"]["redTier"] == "stop"
    assert DEFAULTS["pi.warnings.engine.COOLANT_TEMP.redTier"] == "stop"
    assert not [k for k in DEFAULTS if k.startswith("pi.alerts.")]


@pytest.mark.parametrize("tier", ["stop", "watch"])
def test_warnings_coolantRedTier_acceptsStopOrWatch(tier):
    ok = _baseCfg()
    ok["pi"] = {"warnings": {"engine": {"COOLANT_TEMP": {"redTier": tier}}}}
    cfg = ConfigValidator().validate(ok)
    assert cfg["pi"]["warnings"]["engine"]["COOLANT_TEMP"]["redTier"] == tier


@pytest.mark.parametrize("pid", ["BATTERY_V", "RPM"])
def test_warnings_rejectsStopForAnyPidButCoolant(pid):
    """US-897-b2: only COOLANT_TEMP may be a STOP (Spool: battery and RPM are WATCH)."""
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"engine": {pid: {"redTier": "stop"}}}}
    with pytest.raises(ConfigValidationError, match=f"pi.warnings.engine.{pid}.redTier"):
        ConfigValidator().validate(bad)


@pytest.mark.parametrize("tier", ["minor", "unrated", "STOP", "", 1])
def test_warnings_rejectsATierOutsideStopWatch(tier):
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"engine": {"COOLANT_TEMP": {"redTier": tier}}}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.engine.COOLANT_TEMP.redTier"):
        ConfigValidator().validate(bad)


def test_warnings_rejectsANonMappingEngineRule():
    # MOVED PIN (US-897-b4): RPM now has a default, so the rule is a PID with
    # none -- the shape reaches _validateWarnings untouched.
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"engine": {"SPEED": "watch"}}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.engine.SPEED"):
        ConfigValidator().validate(bad)


def test_warnings_battery_defaults_watchTier_clearGreenHold10s():
    """US-897-b3 (Spool 2026-10-14): battery red is a WATCH that ends after the
    band has been green for 10 s."""
    from common.config.validator import DEFAULTS

    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["warnings"]["engine"]["BATTERY_V"]["redTier"] == "watch"
    assert cfg["pi"]["warnings"]["battery"]["clearGreenHoldSec"] == 10
    assert DEFAULTS["pi.warnings.engine.BATTERY_V.redTier"] == "watch"
    assert DEFAULTS["pi.warnings.battery.clearGreenHoldSec"] == 10


def test_warnings_battery_defaultsCiteSpool():
    """Each new key's OWN DEFAULTS line cites its source."""
    import inspect

    import common.config.validator as validatorModule

    lines = inspect.getsource(validatorModule).splitlines()
    for key in ("pi.warnings.engine.BATTERY_V.redTier", "pi.warnings.battery.clearGreenHoldSec"):
        line = next(text for text in lines if f"'{key}':" in text)
        assert "Spool 2026-10-14" in line


@pytest.mark.parametrize("badValue", [0, -1, "10", True])
def test_warnings_battery_clearGreenHoldSec_rejectsANonPositiveNumber(badValue):
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"battery": {"clearGreenHoldSec": badValue}}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.battery.clearGreenHoldSec"):
        ConfigValidator().validate(bad)


def test_warnings_battery_clearGreenHoldSec_acceptsAPositiveNumber():
    ok = _baseCfg()
    ok["pi"] = {"warnings": {"battery": {"clearGreenHoldSec": 2.5}}}
    cfg = ConfigValidator().validate(ok)
    assert cfg["pi"]["warnings"]["battery"]["clearGreenHoldSec"] == 2.5


def test_warnings_rpm_defaults_watchTier_ownClearGreenHold10s():
    """US-897-b4 (Atlas Q13): RPM red is a WATCH; its no-drive green hold is its
    OWN key, separate from the battery's."""
    from common.config.validator import DEFAULTS

    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["warnings"]["engine"]["RPM"]["redTier"] == "watch"
    assert cfg["pi"]["warnings"]["rpm"]["clearGreenHoldSec"] == 10
    assert DEFAULTS["pi.warnings.engine.RPM.redTier"] == "watch"
    assert DEFAULTS["pi.warnings.rpm.clearGreenHoldSec"] == 10


def test_warnings_rpm_clearGreenHoldSec_defaultCitesAtlasQ13():
    import inspect

    import common.config.validator as validatorModule

    lines = inspect.getsource(validatorModule).splitlines()
    line = next(text for text in lines if "'pi.warnings.rpm.clearGreenHoldSec':" in text)
    assert "Atlas Q13" in line


@pytest.mark.parametrize("badValue", [0, -1, "10", True])
def test_warnings_rpm_clearGreenHoldSec_rejectsANonPositiveNumber(badValue):
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"rpm": {"clearGreenHoldSec": badValue}}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.rpm.clearGreenHoldSec"):
        ConfigValidator().validate(bad)


def test_warnings_rpm_rejectsAStopTier():
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"engine": {"RPM": {"redTier": "stop"}}}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.engine.RPM"):
        ConfigValidator().validate(bad)


def test_warnings_ack_defaults_5sWait_storeUnderVarLib():
    """US-897-c (Atlas Q22 + s3): the POST /alerts-ack wait and the ack store."""
    from common.config.validator import DEFAULTS

    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["warnings"]["ackTimeoutSec"] == 5
    assert cfg["pi"]["warnings"]["ackStorePath"] == "/var/lib/eclipse-obd/alerts-ack.json"
    assert DEFAULTS["pi.warnings.ackTimeoutSec"] == 5
    assert DEFAULTS["pi.warnings.ackStorePath"] == "/var/lib/eclipse-obd/alerts-ack.json"


def test_warnings_ack_defaultsCiteAtlas():
    import inspect

    import common.config.validator as validatorModule

    lines = inspect.getsource(validatorModule).splitlines()
    for key, source in (
        ("pi.warnings.ackTimeoutSec", "Atlas Q22"),
        ("pi.warnings.ackStorePath", "Atlas s3"),
    ):
        line = next(text for text in lines if f"'{key}':" in text)
        assert source in line


@pytest.mark.parametrize("badValue", [0, -1, "5", True, float("nan"), float("inf")])
def test_warnings_ackTimeoutSec_rejectsAnythingButAFiniteNumberAboveZero(badValue):
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"ackTimeoutSec": badValue}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.ackTimeoutSec"):
        ConfigValidator().validate(bad)


def test_warnings_ackTimeoutSec_acceptsAPositiveNumber():
    ok = _baseCfg()
    ok["pi"] = {"warnings": {"ackTimeoutSec": 2.5}}
    assert ConfigValidator().validate(ok)["pi"]["warnings"]["ackTimeoutSec"] == 2.5


@pytest.mark.parametrize("badValue", ["", "   ", 7, True, ["/a"]])
def test_warnings_ackStorePath_rejectsAnythingButANonEmptyString(badValue):
    bad = _baseCfg()
    bad["pi"] = {"warnings": {"ackStorePath": badValue}}
    with pytest.raises(ConfigValidationError, match="pi.warnings.ackStorePath"):
        ConfigValidator().validate(bad)


def test_warnings_ack_absentKeys_areSkipped_underACustomDefaultsSet():
    """Codebase pattern: a custom defaults set may not supply the new keys."""
    cfg = ConfigValidator(defaults={"pi.unrelated": 1}).validate(_baseCfg())
    assert "warnings" not in cfg["pi"]


def test_replay_active_defaultsToFalse_andAnExplicitTrueIsKept():
    """US-901-a: pi.replay.active exists with validator default false (production
    unchanged), and a replay config's true survives validation."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["replay"]["active"] is False

    replay = _baseCfg()
    replay["pi"] = {"replay": {"active": True}}
    assert ConfigValidator().validate(replay)["pi"]["replay"]["active"] is True


def test_replay_sourcePathIsTheRunDatabase_refused(tmp_path):
    """US-857: a replay cannot read and write one file -- pi.replay.sourcePath equal
    to pi.database.path (also through a '..' spelling) fails validation."""
    dbPath = tmp_path / "obd.db"
    for sourcePath in (str(dbPath), str(tmp_path / "sub" / ".." / "obd.db")):
        bad = _baseCfg()
        bad["pi"] = {
            "database": {"path": str(dbPath)},
            "replay": {"active": True, "sourcePath": sourcePath, "driveId": 117},
        }
        with pytest.raises(ConfigValidationError, match="pi.replay.sourcePath"):
            ConfigValidator().validate(bad)


def test_replay_sourcePathDistinctFromTheRunDatabase_validates(tmp_path):
    ok = _baseCfg()
    ok["pi"] = {
        "database": {"path": str(tmp_path / "run.db")},
        "replay": {
            "active": True,
            "sourcePath": str(tmp_path / "copy.db"),
            "driveId": 117,
        },
    }
    assert ConfigValidator().validate(ok)["pi"]["replay"]["driveId"] == 117


def test_replay_inactive_sameSourcePathIsNotChecked(tmp_path):
    """Production behaviour with replay off is unchanged: a leftover sourcePath is
    not read and not refused."""
    dbPath = str(tmp_path / "obd.db")
    cfg = _baseCfg()
    cfg["pi"] = {
        "database": {"path": dbPath},
        "replay": {"active": False, "sourcePath": dbPath},
    }
    ConfigValidator().validate(cfg)


@pytest.mark.parametrize("badDriveId", [0, -1, "117", True, 1.5])
def test_replay_active_rejectsANonPositiveIntegerDriveId(tmp_path, badDriveId):
    bad = _baseCfg()
    bad["pi"] = {
        "replay": {
            "active": True,
            "sourcePath": str(tmp_path / "copy.db"),
            "driveId": badDriveId,
        },
    }
    with pytest.raises(ConfigValidationError, match="pi.replay.driveId"):
        ConfigValidator().validate(bad)


def test_powerWatch_rejectsNonPositiveTimeout():
    cfg = _baseCfg()
    cfg["pi"] = {"powerWatch": {"perTaskTimeoutSec": 0}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(cfg)


def test_powerWatch_drainFloorDwellReads_defaultsToFive_andRejectsNonPositive():
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["powerWatch"]["drainFloorDwellReads"] == 5
    bad = _baseCfg()
    bad["pi"] = {"powerWatch": {"drainFloorDwellReads": 0}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(bad)


@pytest.mark.parametrize("badValue", [True, False, 2.5, 5.0, "5", 0, -1])
def test_powerWatch_drainFloorDwellReads_mustBeAnIntegerAtLeastOne(badValue):
    """Ruling 19 (M8): a COUNT of consecutive reads -- no bool, float or string."""
    bad = _baseCfg()
    bad["pi"] = {"powerWatch": {"drainFloorDwellReads": badValue}}
    with pytest.raises(ConfigValidationError, match="drainFloorDwellReads"):
        ConfigValidator().validate(bad)


def test_powerWatch_drainFloorDwellReads_acceptsOne():
    cfg = _baseCfg()
    cfg["pi"] = {"powerWatch": {"drainFloorDwellReads": 1}}
    assert ConfigValidator().validate(cfg)["pi"]["powerWatch"]["drainFloorDwellReads"] == 1


def test_batteryHealth_monthlyIntervalDays_defaultsTo30_andRejectsNonInteger():
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["batteryHealth"]["monthlyIntervalDays"] == 30
    assert "testHoldSec" not in cfg["pi"]["batteryHealth"]
    for bad_value in (0, -1, True, 30.5, 30.0, "30"):
        bad = _baseCfg()
        bad["pi"] = {"batteryHealth": {"monthlyIntervalDays": bad_value}}
        with pytest.raises(ConfigValidationError):
            ConfigValidator().validate(bad)


def test_powerWatch_rejectsVcellFloorOutOfRange():
    cfg = _baseCfg()
    cfg["pi"] = {"powerWatch": {"vcellFloorVolts": 2.5}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(cfg)


def test_validate_powerWatch_appliesSmoothingDefaults_andRejectsNonPositive():
    """SS-T2/T5: canonical smoothingSec / smoothingPollSec=1 are the live
    config (smoothingSec is the in-V1 safety property, spec sec 3 -- a
    power-LOST reading must hold continuously this long before the shutdown
    window opens). The T2 confirm* deprecated alias DIED at SS-T5 (its
    stated death date) now that __main__.py / controller consume the
    canonical names; the keys are GONE from DEFAULTS + validation.
    Non-positive smoothingSec is rejected like the other powerWatch time
    bounds."""
    import json

    from common.config.validator import DEFAULTS

    cfg = ConfigValidator().validate(_baseCfg())
    pw = cfg["pi"]["powerWatch"]
    # CIO ruling 2026-10-12 (US-776-j1, option A; Atlas ratifying): the default
    # was 5 while config.json said 7. Pin the default to config.json's value,
    # not to a literal, so the two copies cannot drift apart again.
    live = json.loads(_CONFIG_JSON.read_text(encoding="utf-8"))
    assert DEFAULTS["pi.powerWatch.smoothingSec"] == live["pi"]["powerWatch"]["smoothingSec"]
    assert pw["smoothingSec"] == DEFAULTS["pi.powerWatch.smoothingSec"]
    assert pw["smoothingPollSec"] == 1
    # T2 alias is DEAD as of SS-T5 -- confirm* must NOT resolve anymore
    # (the rename completed; one name per fact, SSOT after the migration).
    assert "confirmWindowSec" not in pw
    assert "confirmPollSec" not in pw

    bad = _baseCfg()
    bad["pi"] = {"powerWatch": {"smoothingSec": 0}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(bad)


def test_validate_powerWatch_uiPollSec_defaultAndRejectsNonPositive():
    """SS-T4 B1: the UI power-source poll cadence (the PowerSourceProvider ->
    PowerMonitor bridge thread in lifecycle) is a validated config param, never
    a literal -- zero magic numbers. Default 2s; non-positive rejected like the
    other powerWatch time bounds."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["powerWatch"]["uiPollSec"] == 2

    bad = _baseCfg()
    bad["pi"] = {"powerWatch": {"uiPollSec": 0}}
    with pytest.raises(ConfigValidationError):
        ConfigValidator().validate(bad)


def test_validate_busDefault_disabled():
    """US-384 (EDR bus slice 1): pi.bus.enabled defaults False so the bus ships
    dark -- the in-process pub/sub seam is wired but dormant until a separate
    PM/CIO deploy flips the flag on the Pi."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["bus"]["enabled"] is False


def test_validate_busEnabled_explicitValuePreserved():
    """An explicit pi.bus.enabled is preserved (default does not overwrite)."""
    cfg = _baseCfg()
    cfg["pi"] = {"bus": {"enabled": True}}
    result = ConfigValidator().validate(cfg)
    assert result["pi"]["bus"]["enabled"] is True


def test_validate_sensorFlags_defaultDarkWithDefaultRates():
    """US-409 (EDR sensor readers): both per-sensor enable flags default False
    (ships dark) with their bus publish rates -- imu at the single definition
    (US-801; its equality with config.json is pinned in
    tests/pi/sensors/test_imu_rate_single_source.py), light 1 Hz."""
    cfg = ConfigValidator().validate(_baseCfg())
    sensors = cfg["pi"]["sensors"]
    assert sensors["imu"]["enabled"] is False
    assert sensors["imu"]["sampleHz"] == DEFAULT_IMU_SAMPLE_HZ
    assert sensors["light"]["enabled"] is False
    assert sensors["light"]["sampleHz"] == 1


def test_validate_sensorEnabled_explicitValuePreserved():
    """An explicit per-sensor flag is preserved (default does not overwrite)."""
    cfg = _baseCfg()
    cfg["pi"] = {"sensors": {"imu": {"enabled": True}}}
    result = ConfigValidator().validate(cfg)
    assert result["pi"]["sensors"]["imu"]["enabled"] is True
    # The unspecified sibling still fills from defaults.
    assert result["pi"]["sensors"]["light"]["enabled"] is False


def test_validate_sensorPersistenceKeys_defaults():
    """US-410 (EDR persistence): imu.persistHz decimates the bus to a baseline
    persist cadence (the single definition, US-801); retentionDays bounds the
    Pi-local rolling window at 7 days."""
    cfg = ConfigValidator().validate(_baseCfg())
    sensors = cfg["pi"]["sensors"]
    assert sensors["imu"]["persistHz"] == DEFAULT_IMU_PERSIST_HZ
    assert sensors["retentionDays"] == 7



def test_validate_imuPeaksSmoothingSec_defaultsToTheSingleDefinition():
    """US-882-a: states/imu peaks smooth over pi.imu.peaks.smoothingSec, 0.5 s
    by default (design default, unvalidated until the LIVE FEEDS drive)."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["imu"]["peaks"]["smoothingSec"] == DEFAULT_IMU_PEAKS_SMOOTHING_SEC
    assert DEFAULT_IMU_PEAKS_SMOOTHING_SEC == 0.5


@pytest.mark.parametrize("bad", [0, -0.5, "0.5", True])
def test_validate_imuPeaksSmoothingSec_nonPositive_rejected(bad):
    """US-882-a: a zero window is no smoothing at all -- a pothole spike would
    publish as a braking peak -- so a non-positive or non-numeric value fails."""
    cfg = _baseCfg()
    cfg["pi"] = {"imu": {"peaks": {"smoothingSec": bad}}}
    with pytest.raises(ConfigValidationError, match="pi.imu.peaks.smoothingSec"):
        ConfigValidator().validate(cfg)


def test_validate_gradeHistory_defaultsToTheSingleDefinitions():
    """US-882-b: states/grade-history buckets 10 s over a 900 s window by default."""
    cfg = ConfigValidator().validate(_baseCfg())
    gradeHistory = cfg["pi"]["display"]["gradeHistory"]
    assert gradeHistory["intervalSec"] == DEFAULT_GRADE_HISTORY_INTERVAL_SEC
    assert gradeHistory["windowSec"] == DEFAULT_GRADE_HISTORY_WINDOW_SEC
    assert DEFAULT_GRADE_HISTORY_INTERVAL_SEC == 10
    assert DEFAULT_GRADE_HISTORY_WINDOW_SEC == 900


@pytest.mark.parametrize("key", ["intervalSec", "windowSec"])
@pytest.mark.parametrize("bad", [0, -10, float("inf"), float("nan"), "10", True])
def test_validate_gradeHistory_nonPositiveOrNonFinite_rejected(key, bad):
    """US-882-b: each grade-history key must be a finite number > 0."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"gradeHistory": {key: bad}}}
    with pytest.raises(ConfigValidationError, match=f"pi.display.gradeHistory.{key}"):
        ConfigValidator().validate(cfg)


def test_validate_engineHistory_defaultsTo30sAnd240Points():
    """US-889-a: states/engine-history buckets 30 s, 240 points per PID (2 h)
    by default (Atlas S104 ruling 1)."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["display"]["engineHistory"] == {"intervalSec": 30, "maxPoints": 240}


@pytest.mark.parametrize("key", ["intervalSec", "maxPoints"])
@pytest.mark.parametrize("bad", [0, -30, float("inf"), float("nan"), "30", True])
def test_validate_engineHistory_nonPositiveOrNonFinite_rejected(key, bad):
    """US-889-a: each engine-history key must be a finite number > 0; the error
    names the key."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"engineHistory": {key: bad}}}
    with pytest.raises(ConfigValidationError, match=f"pi.display.engineHistory.{key}"):
        ConfigValidator().validate(cfg)


def test_validate_mafMaxGs_defaultsTo160():
    """US-890-b: params.MAF.scale.max defaults to 160 g/s (Spool 2026-10-14: the
    smallest round number above the corpus max 158.69 g/s)."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["display"]["scale"]["mafMaxGs"] == 160


def test_validate_mafMaxGs_acceptsAPositiveNumber():
    """US-890-b: a positive finite override passes unchanged."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"scale": {"mafMaxGs": 150.5}}}
    assert ConfigValidator().validate(cfg)["pi"]["display"]["scale"]["mafMaxGs"] == 150.5


@pytest.mark.parametrize("bad", [0, -160, float("inf"), float("nan"), "160", True])
def test_validate_mafMaxGs_nonPositiveOrNonFinite_rejected(bad):
    """US-890-b: pi.display.scale.mafMaxGs must be a finite number > 0; the error
    names the key."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"scale": {"mafMaxGs": bad}}}
    with pytest.raises(ConfigValidationError, match="pi.display.scale.mafMaxGs"):
        ConfigValidator().validate(cfg)


def test_validate_tripGapSec_defaultsTo300():
    """US-880-a: the speed integrator's gap rule defaults to 300 s (Atlas: one
    gap definition across tiers)."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["trip"]["gapSec"] == 300


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), "300", True])
def test_validate_tripGapSec_nonPositiveOrNonFinite_rejected(bad):
    """US-880-a: pi.trip.gapSec must be a finite number > 0."""
    cfg = _baseCfg()
    cfg["pi"] = {"trip": {"gapSec": bad}}
    with pytest.raises(ConfigValidationError, match="pi.trip.gapSec"):
        ConfigValidator().validate(cfg)


def test_validate_tripGapSec_positiveFloat_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"trip": {"gapSec": 120.5}}
    assert ConfigValidator().validate(cfg)["pi"]["trip"]["gapSec"] == 120.5


def test_validate_staleImuSec_defaultsToThreeSeconds_theMeasuredBasis():
    """US-882-c: pi.display.stale.imuSec is the one IMU stale key.
    MOVED PIN (US-896-a, Atlas S105 Q3/G1): default 2.0 -> 3.0 s -- a healthy
    1 Hz states/imu reads up to 1.94 s old (measured), so 2.0 had ~0.06 s of
    margin; 3.0 is three readings."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["display"]["stale"]["imuSec"] == 3.0


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), "2.0", True])
def test_validate_staleImuSec_nonPositiveOrNonFinite_rejected(bad):
    """US-882-c: pi.display.stale.imuSec must be a finite number > 0."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"stale": {"imuSec": bad}}}
    with pytest.raises(ConfigValidationError, match="pi.display.stale.imuSec"):
        ConfigValidator().validate(cfg)


def test_validate_staleImuSec_positiveFloat_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"stale": {"imuSec": 3.5}}}
    assert ConfigValidator().validate(cfg)["pi"]["display"]["stale"]["imuSec"] == 3.5


def test_validate_staleFuelResetConfirmSec_defaultsToSix():
    """US-890-f (Atlas Q4): the kiosk's wait for the re-read after a 200 from
    POST /fuel-reset defaults to 6 s -- three ~2.03 s fuel-economy publishes."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["display"]["stale"]["fuelResetConfirmSec"] == 6


@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), "6", True])
def test_validate_staleFuelResetConfirmSec_nonPositiveOrNonFinite_rejected(bad):
    """US-890-f: pi.display.stale.fuelResetConfirmSec must be a finite number > 0."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"stale": {"fuelResetConfirmSec": bad}}}
    with pytest.raises(ConfigValidationError, match="pi.display.stale.fuelResetConfirmSec"):
        ConfigValidator().validate(cfg)


def test_validate_staleFuelResetConfirmSec_positiveFloat_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"stale": {"fuelResetConfirmSec": 8.5}}}
    stale = ConfigValidator().validate(cfg)["pi"]["display"]["stale"]
    assert stale["fuelResetConfirmSec"] == 8.5


def test_validate_staleAlertsAckWindows_defaultToSixAndThree():
    """US-899-a1: the takeover ack waits 6 s for the acknowledged re-read (Atlas
    Q33, the fuelResetConfirmSec pattern) and its failure notice holds 3 s (Iris)."""
    stale = ConfigValidator().validate(_baseCfg())["pi"]["display"]["stale"]
    assert stale["alertsAckConfirmSec"] == 6
    assert stale["alertsAckNoticeSec"] == 3


@pytest.mark.parametrize("key", ["alertsAckConfirmSec", "alertsAckNoticeSec"])
@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), "6", True])
def test_validate_staleAlertsAckWindows_nonPositiveOrNonFinite_rejected(key, bad):
    """US-899-a1: each ack window must be a finite number > 0."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"stale": {key: bad}}}
    with pytest.raises(ConfigValidationError, match=f"pi.display.stale.{key}"):
        ConfigValidator().validate(cfg)


@pytest.mark.parametrize("key", ["alertsAckConfirmSec", "alertsAckNoticeSec"])
def test_validate_staleAlertsAckWindows_positiveFloat_accepted(key):
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"stale": {key: 4.5}}}
    assert ConfigValidator().validate(cfg)["pi"]["display"]["stale"][key] == 4.5


def test_validate_fuelKeys_defaultsAreSpoolsSourcedValues():
    """US-881-b: E0 stoich 14.7 and density 740 g/L (Spool 2026-10-14, CIO: the
    car's 93 is ethanol-free), MAF trusted, and the three honesty thresholds."""
    fuel = ConfigValidator().validate(_baseCfg())["pi"]["fuel"]
    assert fuel == {
        "stoichAfr": 14.7,
        "densityGPerL": 740,
        "mafTrusted": True,
        "minMiles": 1.0,
        "maxExcludedPct": 10,
        "approximateOpenLoopPct": 10,
        "persistSec": 60,
        "resetTimeoutSec": 5,
        # US-890-e named pin change: Spool 2026-10-14's last-30 s rules.
        "recentWindowSec": 30,
        "recentMinMiles": 0.1,
        "recentMinMafSamples": 10,
    }


@pytest.mark.parametrize(
    "key",
    ["stoichAfr", "densityGPerL", "minMiles", "persistSec", "resetTimeoutSec",
     "recentWindowSec", "recentMinMiles", "recentMinMafSamples"],
)
@pytest.mark.parametrize("bad", [0, -1, float("inf"), float("nan"), "14.7", True])
def test_validate_fuelPositiveKeys_nonPositiveOrNonFinite_rejected(key, bad):
    """US-881-b: stoich, density and the minimum distance are finite numbers > 0;
    US-881-c: so is the since-reset persist cadence; US-881-d: and the POST
    /fuel-reset outcome wait; US-890-e: and the three last-30 s rules."""
    cfg = _baseCfg()
    cfg["pi"] = {"fuel": {key: bad}}
    with pytest.raises(ConfigValidationError, match=f"pi.fuel.{key}"):
        ConfigValidator().validate(cfg)


@pytest.mark.parametrize("key", ["maxExcludedPct", "approximateOpenLoopPct"])
@pytest.mark.parametrize("bad", [-1, 100.5, float("inf"), float("nan"), "10", True])
def test_validate_fuelPercentKeys_outsideZeroToHundred_rejected(key, bad):
    """US-881-b: the two percentage thresholds lie in [0, 100]."""
    cfg = _baseCfg()
    cfg["pi"] = {"fuel": {key: bad}}
    with pytest.raises(ConfigValidationError, match=f"pi.fuel.{key}"):
        ConfigValidator().validate(cfg)


@pytest.mark.parametrize("bad", [0, 1, "false"])
def test_validate_fuelMafTrusted_nonBool_rejected(bad):
    """US-881-b: mafTrusted is a real boolean (flipped false at a speed-density
    install), never a truthy stand-in."""
    cfg = _baseCfg()
    cfg["pi"] = {"fuel": {"mafTrusted": bad}}
    with pytest.raises(ConfigValidationError, match="pi.fuel.mafTrusted"):
        ConfigValidator().validate(cfg)


def test_validate_obdiiConnectDebug_absent_defaultsFalse():
    """US-907: absent = off; the diagnostic window is opt-in per deploy."""
    cfg = ConfigValidator().validate(_baseCfg())
    assert cfg["pi"]["obdii"]["connectDebug"] is False


@pytest.mark.parametrize("bad", ["yes", 1, 0, "true"])
def test_validate_obdiiConnectDebug_nonBool_rejected(bad):
    """US-907: connectDebug is a real boolean, never a truthy stand-in."""
    cfg = _baseCfg()
    cfg["pi"] = {"obdii": {"connectDebug": bad}}
    with pytest.raises(ConfigValidationError, match="pi.obdii.connectDebug"):
        ConfigValidator().validate(cfg)


def test_validate_obdiiConnectDebug_true_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"obdii": {"connectDebug": True}}
    assert ConfigValidator().validate(cfg)["pi"]["obdii"]["connectDebug"] is True


def test_validate_fuelKeys_validOverrides_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"fuel": {"stoichAfr": 14.1, "mafTrusted": False, "maxExcludedPct": 0}}
    fuel = ConfigValidator().validate(cfg)["pi"]["fuel"]
    assert (fuel["stoichAfr"], fuel["mafTrusted"], fuel["maxExcludedPct"]) == (14.1, False, 0)


def test_validate_fuelRecentKeys_validOverrides_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"fuel": {"recentWindowSec": 60, "recentMinMiles": 0.2, "recentMinMafSamples": 8}}
    fuel = ConfigValidator().validate(cfg)["pi"]["fuel"]
    assert (fuel["recentWindowSec"], fuel["recentMinMiles"], fuel["recentMinMafSamples"]) == (
        60, 0.2, 8)


def test_validate_gradeHistory_windowShorterThanInterval_rejected():
    """US-882-b: a window that cannot hold one bucket is refused."""
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"gradeHistory": {"intervalSec": 30, "windowSec": 20}}}
    with pytest.raises(ConfigValidationError, match="pi.display.gradeHistory.windowSec"):
        ConfigValidator().validate(cfg)


def test_validate_gradeHistory_windowEqualToInterval_accepted():
    cfg = _baseCfg()
    cfg["pi"] = {"display": {"gradeHistory": {"intervalSec": 30, "windowSec": 30}}}
    result = ConfigValidator().validate(cfg)
    assert result["pi"]["display"]["gradeHistory"]["windowSec"] == 30
