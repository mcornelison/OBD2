################################################################################
# File Name: test_secrets_loader.py
# Purpose/Description: Tests for secrets loading and resolution
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
Tests for the secrets_loader module.

Run with:
    pytest tests/test_secrets_loader.py -v
"""

import os
import sys
from pathlib import Path

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from common.secrets_loader import (
    getSecret,
    loadConfigWithSecrets,
    loadEnvFile,
    maskSecret,
    resolveSecrets,
)


class TestLoadEnvFile:
    """Tests for loadEnvFile function."""

    def test_loadEnvFile_validFile_loadsVariables(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: Valid .env file
        When: loadEnvFile() is called
        Then: Variables are loaded into environment
        """
        envFile = tmp_path / '.env'
        envFile.write_text('TEST_VAR=test_value\n')

        loadEnvFile(str(envFile))

        assert os.environ.get('TEST_VAR') == 'test_value'

        # Cleanup
        del os.environ['TEST_VAR']

    def test_loadEnvFile_missingFile_returnsEmpty(self, cleanEnv):
        """
        Given: Non-existent .env file
        When: loadEnvFile() is called
        Then: Returns empty dict, no error
        """
        result = loadEnvFile('/nonexistent/.env')

        assert result == {}

    def test_loadEnvFile_quotedValues_stripsQuotes(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: .env file with quoted values
        When: loadEnvFile() is called
        Then: Quotes are stripped from values
        """
        envFile = tmp_path / '.env'
        envFile.write_text('QUOTED_VAR="quoted value"\n')

        loadEnvFile(str(envFile))

        assert os.environ.get('QUOTED_VAR') == 'quoted value'

        # Cleanup
        del os.environ['QUOTED_VAR']

    def test_loadEnvFile_comments_areIgnored(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: .env file with comments
        When: loadEnvFile() is called
        Then: Comments are ignored
        """
        envFile = tmp_path / '.env'
        envFile.write_text('# This is a comment\nACTUAL_VAR=value\n')

        loadEnvFile(str(envFile))

        assert 'ACTUAL_VAR' in os.environ
        assert os.environ.get('ACTUAL_VAR') == 'value'

        # Cleanup
        del os.environ['ACTUAL_VAR']


class TestResolveSecrets:
    """Tests for resolveSecrets function."""

    def test_resolveSecrets_stringWithPlaceholder_resolvesFromEnv(self, envVars):
        """
        Given: String with ${VAR} placeholder
        When: resolveSecrets() is called
        Then: Placeholder is replaced with env value
        """
        result = resolveSecrets('${APP_ENVIRONMENT}')

        assert result == 'test'

    def test_resolveSecrets_stringWithDefault_usesDefaultWhenMissing(self, cleanEnv):
        """
        Given: String with ${VAR:default} placeholder
        When: Variable is not set
        Then: Default value is used
        """
        result = resolveSecrets('${MISSING_VAR:default_value}')

        assert result == 'default_value'

    def test_resolveSecrets_nestedDict_resolvesRecursively(self, envVars):
        """
        Given: Nested dictionary with placeholders
        When: resolveSecrets() is called
        Then: All placeholders are resolved recursively
        """
        config = {
            'level1': {
                'level2': '${APP_ENVIRONMENT}'
            }
        }

        result = resolveSecrets(config)

        assert result['level1']['level2'] == 'test'

    def test_resolveSecrets_list_resolvesAllItems(self, envVars):
        """
        Given: List with placeholders
        When: resolveSecrets() is called
        Then: All items are resolved
        """
        config = ['${APP_ENVIRONMENT}', '${DB_SERVER}']

        result = resolveSecrets(config)

        assert result == ['test', 'test-server']

    def test_resolveSecrets_nonString_returnsUnchanged(self):
        """
        Given: Non-string value (int, bool, etc.)
        When: resolveSecrets() is called
        Then: Value is returned unchanged
        """
        assert resolveSecrets(42) == 42
        assert resolveSecrets(True) is True
        assert resolveSecrets(None) is None


class TestLoadConfigWithSecrets:
    """Tests for loadConfigWithSecrets function."""

    def test_loadConfigWithSecrets_validFile_loadsAndResolves(
        self,
        tempConfigFile: Path,
        envVars
    ):
        """
        Given: Valid config file and environment
        When: loadConfigWithSecrets() is called
        Then: Config is loaded with secrets resolved
        """
        result = loadConfigWithSecrets(str(tempConfigFile))

        assert result is not None
        assert 'application' in result

    def test_loadConfigWithSecrets_missingFile_raisesError(self):
        """
        Given: Non-existent config file
        When: loadConfigWithSecrets() is called
        Then: Raises FileNotFoundError
        """
        with pytest.raises(FileNotFoundError):
            loadConfigWithSecrets('/nonexistent/config.json')


class TestGetSecret:
    """Tests for getSecret function."""

    def test_getSecret_existingVar_returnsValue(self, envVars):
        """
        Given: Environment variable exists
        When: getSecret() is called
        Then: Returns the value
        """
        result = getSecret('APP_ENVIRONMENT')

        assert result == 'test'

    def test_getSecret_missingVar_returnsDefault(self, cleanEnv):
        """
        Given: Environment variable doesn't exist
        When: getSecret() is called with default
        Then: Returns the default value
        """
        result = getSecret('MISSING_VAR', default='default')

        assert result == 'default'

    def test_getSecret_missingNoDefault_returnsNone(self, cleanEnv):
        """
        Given: Environment variable doesn't exist
        When: getSecret() is called without default
        Then: Returns None
        """
        result = getSecret('MISSING_VAR')

        assert result is None


class TestMaskSecret:
    """Tests for maskSecret function."""

    def test_maskSecret_normalValue_masksAfterShowChars(self):
        """
        Given: Secret value
        When: maskSecret() is called
        Then: Value is masked after showChars
        """
        result = maskSecret('my_secret_password', showChars=4)

        assert result == 'my_s**************'

    def test_maskSecret_shortValue_fullyMasked(self):
        """
        Given: Short secret value
        When: maskSecret() is called
        Then: Value is fully masked
        """
        result = maskSecret('abc', showChars=4)

        assert result == '***'

    def test_maskSecret_emptyValue_returnsEmpty(self):
        """
        Given: Empty value
        When: maskSecret() is called
        Then: Returns [EMPTY]
        """
        result = maskSecret('')

        assert result == '[EMPTY]'


class TestEdgeCases:
    """Edge case tests for secrets_loader module."""

    def test_loadEnvFile_existingVar_doesNotOverride(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: Environment variable already exists
        When: loadEnvFile() is called with same variable
        Then: Original value is preserved
        """
        # Arrange
        os.environ['EXISTING_VAR'] = 'original_value'
        envFile = tmp_path / '.env'
        envFile.write_text('EXISTING_VAR=new_value\n')

        # Act
        loadEnvFile(str(envFile))

        # Assert
        assert os.environ.get('EXISTING_VAR') == 'original_value'

        # Cleanup
        del os.environ['EXISTING_VAR']

    def test_loadEnvFile_singleQuotedValues_stripsQuotes(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: .env file with single-quoted values
        When: loadEnvFile() is called
        Then: Single quotes are stripped from values
        """
        envFile = tmp_path / '.env'
        envFile.write_text("SINGLE_QUOTED='single quoted value'\n")

        loadEnvFile(str(envFile))

        assert os.environ.get('SINGLE_QUOTED') == 'single quoted value'

        # Cleanup
        del os.environ['SINGLE_QUOTED']

    def test_loadEnvFile_emptyLines_areIgnored(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: .env file with empty lines
        When: loadEnvFile() is called
        Then: Empty lines are ignored, valid lines are processed
        """
        envFile = tmp_path / '.env'
        envFile.write_text('\n\nEMPTY_LINE_VAR=value\n\n')

        loadEnvFile(str(envFile))

        assert os.environ.get('EMPTY_LINE_VAR') == 'value'

        # Cleanup
        del os.environ['EMPTY_LINE_VAR']

    def test_loadEnvFile_invalidLine_continuesProcessing(
        self,
        tmp_path: Path,
        cleanEnv
    ):
        """
        Given: .env file with invalid line (no equals sign)
        When: loadEnvFile() is called
        Then: Invalid line is skipped, valid lines are processed
        """
        envFile = tmp_path / '.env'
        envFile.write_text('invalid_line_no_equals\nVALID_VAR=value\n')

        loadEnvFile(str(envFile))

        assert os.environ.get('VALID_VAR') == 'value'

        # Cleanup
        del os.environ['VALID_VAR']

    def test_resolveSecrets_unresolvedPlaceholder_remainsUnchanged(
        self,
        cleanEnv
    ):
        """
        Given: String with placeholder for undefined variable (no default)
        When: resolveSecrets() is called
        Then: Placeholder remains unchanged
        """
        result = resolveSecrets('${UNSET_VAR_NO_DEFAULT}')

        assert result == '${UNSET_VAR_NO_DEFAULT}'

    def test_resolveSecrets_mixedTextAndPlaceholder_resolvesCorrectly(
        self,
        cleanEnv
    ):
        """
        Given: String with text and placeholder mixed
        When: resolveSecrets() is called
        Then: Placeholder is resolved, text preserved
        """
        os.environ['MIX_VAR'] = 'world'

        result = resolveSecrets('Hello ${MIX_VAR}!')

        assert result == 'Hello world!'

        # Cleanup
        del os.environ['MIX_VAR']

    def test_resolveSecrets_multiplePlaceholders_resolvesAll(
        self,
        cleanEnv
    ):
        """
        Given: String with multiple placeholders
        When: resolveSecrets() is called
        Then: All placeholders are resolved
        """
        os.environ['MULTI_VAR_1'] = 'foo'
        os.environ['MULTI_VAR_2'] = 'bar'

        result = resolveSecrets('${MULTI_VAR_1}-${MULTI_VAR_2}')

        assert result == 'foo-bar'

        # Cleanup
        del os.environ['MULTI_VAR_1']
        del os.environ['MULTI_VAR_2']

    def test_resolveSecrets_emptyDefault_usesEmptyString(
        self,
        cleanEnv
    ):
        """
        Given: Placeholder with empty default value
        When: Variable is not set
        Then: Empty string is used
        """
        result = resolveSecrets('${EMPTY_DEFAULT_VAR:}')

        assert result == ''

    def test_resolveSecrets_floatValue_returnsUnchanged(self):
        """
        Given: Float value
        When: resolveSecrets() is called
        Then: Value is returned unchanged
        """
        assert resolveSecrets(3.14) == 3.14

    def test_resolveSecrets_deeplyNestedConfig_resolvesAll(
        self,
        cleanEnv
    ):
        """
        Given: Deeply nested configuration with placeholders
        When: resolveSecrets() is called
        Then: All levels are resolved
        """
        os.environ['DEEP_VAR'] = 'deep_value'
        config = {
            'level1': {
                'level2': {
                    'level3': {
                        'value': '${DEEP_VAR}'
                    }
                }
            }
        }

        result = resolveSecrets(config)

        assert result['level1']['level2']['level3']['value'] == 'deep_value'

        # Cleanup
        del os.environ['DEEP_VAR']

    def test_loadConfigWithSecrets_invalidJson_raisesError(
        self,
        tmp_path: Path
    ):
        """
        Given: Config file with invalid JSON
        When: loadConfigWithSecrets() is called
        Then: Raises JSONDecodeError
        """
        import json
        configFile = tmp_path / 'invalid.json'
        configFile.write_text('{ invalid json }')

        with pytest.raises(json.JSONDecodeError):
            loadConfigWithSecrets(str(configFile))
