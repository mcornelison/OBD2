#!/usr/bin/env python
################################################################################
# File Name: run_tests_main.py
# Purpose/Description: Manual test runner for main.py tests
# Author: Ralph Agent
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Ralph Agent. All rights reserved.
################################################################################

"""
Manual test runner for main module tests.

Run with:
    python run_tests_main.py
"""

import json
import os
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from main import (
    EXIT_CONFIG_ERROR,
    EXIT_RUNTIME_ERROR,
    EXIT_SUCCESS,
    EXIT_UNKNOWN_ERROR,
    loadConfiguration,
    main,
    parseArgs,
    runWorkflow,
)
from common.error_handler import ConfigurationError

# Test counters
passedTests = 0
failedTests = 0
failedTestNames = []


def runTest(testName, testFunc):
    """Run a test and track results."""
    global passedTests, failedTests, failedTestNames
    try:
        testFunc()
        passedTests += 1
        print(f"  [PASS] {testName}")
    except AssertionError as e:
        failedTests += 1
        failedTestNames.append(testName)
        print(f"  [FAIL] {testName}: {e}")
    except Exception as e:
        failedTests += 1
        failedTestNames.append(testName)
        print(f"  [ERROR] {testName}: {e}")
        traceback.print_exc()


def getSampleConfig():
    """Return sample configuration for tests."""
    return {
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
        'logging': {
            'level': 'DEBUG',
            'maskPII': True
        }
    }


# ================================================================================
# CLI Argument Parsing Tests
# ================================================================================

def test_parseArgs_noArgs_usesDefaults():
    """Test default argument values."""
    with patch('sys.argv', ['main.py']):
        args = parseArgs()
    assert args.config == 'src/config.json', f"Expected 'src/config.json', got '{args.config}'"
    assert args.env_file == '.env', f"Expected '.env', got '{args.env_file}'"
    assert args.dry_run is False, "Expected dry_run=False"
    assert args.verbose is False, "Expected verbose=False"


def test_parseArgs_customConfig_setsConfigPath():
    """Test custom config path."""
    with patch('sys.argv', ['main.py', '--config', 'custom/config.json']):
        args = parseArgs()
    assert args.config == 'custom/config.json'


def test_parseArgs_shortConfigFlag_setsConfigPath():
    """Test -c shorthand."""
    with patch('sys.argv', ['main.py', '-c', 'custom.json']):
        args = parseArgs()
    assert args.config == 'custom.json'


def test_parseArgs_envFile_setsEnvPath():
    """Test --env-file flag."""
    with patch('sys.argv', ['main.py', '--env-file', '.env.production']):
        args = parseArgs()
    assert args.env_file == '.env.production'


def test_parseArgs_shortEnvFlag_setsEnvPath():
    """Test -e shorthand."""
    with patch('sys.argv', ['main.py', '-e', '.env.test']):
        args = parseArgs()
    assert args.env_file == '.env.test'


def test_parseArgs_dryRun_setsDryRunTrue():
    """Test --dry-run flag."""
    with patch('sys.argv', ['main.py', '--dry-run']):
        args = parseArgs()
    assert args.dry_run is True


def test_parseArgs_verbose_setsVerboseTrue():
    """Test --verbose flag."""
    with patch('sys.argv', ['main.py', '--verbose']):
        args = parseArgs()
    assert args.verbose is True


def test_parseArgs_shortVerboseFlag_setsVerboseTrue():
    """Test -v shorthand."""
    with patch('sys.argv', ['main.py', '-v']):
        args = parseArgs()
    assert args.verbose is True


def test_parseArgs_multipleFlags_setsAllOptions():
    """Test multiple flags combined."""
    with patch('sys.argv', ['main.py', '-c', 'my.json', '-e', '.env.test',
                             '--dry-run', '--verbose']):
        args = parseArgs()
    assert args.config == 'my.json'
    assert args.env_file == '.env.test'
    assert args.dry_run is True
    assert args.verbose is True


def test_parseArgs_helpFlag_exitsWithZero():
    """Test --help exits with 0."""
    with patch('sys.argv', ['main.py', '--help']):
        try:
            parseArgs()
            assert False, "Should have raised SystemExit"
        except SystemExit as e:
            assert e.code == 0, f"Expected exit code 0, got {e.code}"


def test_parseArgs_versionFlag_exitsWithZero():
    """Test --version exits with 0."""
    with patch('sys.argv', ['main.py', '--version']):
        try:
            parseArgs()
            assert False, "Should have raised SystemExit"
        except SystemExit as e:
            assert e.code == 0, f"Expected exit code 0, got {e.code}"


# ================================================================================
# Configuration Loading Tests
# ================================================================================

def test_loadConfiguration_validConfig_returnsConfig():
    """Test loading valid configuration."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        with patch('main.setupLogging'), patch('main.getLogger'):
            config = loadConfiguration(str(configFile))

        assert config is not None, "Config should not be None"
        assert 'application' in config, "Config should have 'application' key"


def test_loadConfiguration_withEnvFile_resolvesSecrets():
    """Test secret resolution from env file."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configWithPlaceholders = {
            'application': {'name': 'TestApp'},
            'database': {'server': '${DB_SERVER}'}
        }
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(configWithPlaceholders, f)

        envFile = Path(tmpDir) / '.env'
        with open(envFile, 'w') as f:
            f.write('DB_SERVER=test-server\n')

        with patch('main.setupLogging'), patch('main.getLogger'):
            config = loadConfiguration(str(configFile), str(envFile))

        assert config['database']['server'] == 'test-server', \
            f"Expected 'test-server', got '{config['database']['server']}'"


def test_loadConfiguration_missingFile_raisesConfigError():
    """Test missing config file raises error."""
    with patch('main.setupLogging'), patch('main.getLogger'):
        try:
            loadConfiguration('/nonexistent/config.json')
            assert False, "Should have raised ConfigurationError"
        except ConfigurationError as e:
            assert 'not found' in str(e).lower(), f"Error should mention 'not found': {e}"


def test_loadConfiguration_invalidJson_raisesError():
    """Test invalid JSON raises error."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'invalid.json'
        with open(configFile, 'w') as f:
            f.write('{ invalid json }')

        with patch('main.setupLogging'), patch('main.getLogger'):
            try:
                loadConfiguration(str(configFile))
                assert False, "Should have raised an exception"
            except Exception:
                pass  # Expected


# ================================================================================
# Workflow Tests
# ================================================================================

def test_runWorkflow_normalMode_returnsTrue():
    """Test normal workflow execution."""
    with patch('main.getLogger'):
        result = runWorkflow(getSampleConfig())
    assert result is True, "Workflow should return True"


def test_runWorkflow_dryRunMode_returnsTrue():
    """Test dry run mode."""
    mockLogger = MagicMock()
    with patch('main.getLogger', return_value=mockLogger):
        result = runWorkflow(getSampleConfig(), dryRun=True)
    assert result is True, "Dry run should return True"
    dryRunLogged = any(
        'DRY RUN' in str(call) for call in mockLogger.info.call_args_list
    )
    assert dryRunLogged, "Should log DRY RUN message"


# ================================================================================
# Main Function Tests
# ================================================================================

def test_main_successfulRun_returnsExitSuccess():
    """Test successful main execution."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                result = main()

        assert result == EXIT_SUCCESS, f"Expected {EXIT_SUCCESS}, got {result}"


def test_main_configError_returnsExitConfigError():
    """Test config error exit code."""
    with patch('sys.argv', ['main.py', '--config', '/nonexistent.json']):
        with patch('main.setupLogging'), patch('main.getLogger'):
            result = main()

    assert result == EXIT_CONFIG_ERROR, f"Expected {EXIT_CONFIG_ERROR}, got {result}"


def test_main_workflowFails_returnsExitRuntimeError():
    """Test workflow failure exit code."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', return_value=False):
                    result = main()

        assert result == EXIT_RUNTIME_ERROR, f"Expected {EXIT_RUNTIME_ERROR}, got {result}"


def test_main_unexpectedException_returnsExitUnknownError():
    """Test unexpected exception exit code."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', side_effect=RuntimeError("Unexpected")):
                    result = main()

        assert result == EXIT_UNKNOWN_ERROR, f"Expected {EXIT_UNKNOWN_ERROR}, got {result}"


def test_main_verboseFlag_setsDebugLevel():
    """Test verbose sets DEBUG log level."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        mockSetupLogging = MagicMock()
        with patch('sys.argv', ['main.py', '--config', str(configFile), '-v']):
            with patch('main.setupLogging', mockSetupLogging):
                with patch('main.getLogger'):
                    main()

        mockSetupLogging.assert_called_once_with(level='DEBUG')


def test_main_normalMode_setsInfoLevel():
    """Test normal mode sets INFO log level."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        mockSetupLogging = MagicMock()
        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging', mockSetupLogging):
                with patch('main.getLogger'):
                    main()

        mockSetupLogging.assert_called_once_with(level='INFO')


def test_main_dryRunFlag_passesToWorkflow():
    """Test --dry-run is passed to workflow."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        mockWorkflow = MagicMock(return_value=True)
        with patch('sys.argv', ['main.py', '--config', str(configFile), '--dry-run']):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', mockWorkflow):
                    main()

        _, kwargs = mockWorkflow.call_args
        assert kwargs.get('dryRun') is True, "dryRun should be True"


# ================================================================================
# Edge Case Tests
# ================================================================================

def test_main_keyboardInterrupt_returnsRuntimeError():
    """Test KeyboardInterrupt handling."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)

        with patch('sys.argv', ['main.py', '--config', str(configFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                with patch('main.runWorkflow', side_effect=KeyboardInterrupt):
                    result = main()

        assert result == EXIT_RUNTIME_ERROR, f"Expected {EXIT_RUNTIME_ERROR}, got {result}"


def test_loadConfiguration_emptyConfig_appliesDefaults():
    """Test empty config gets defaults applied."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'empty.json'
        with open(configFile, 'w') as f:
            json.dump({}, f)

        with patch('main.setupLogging'), patch('main.getLogger'):
            config = loadConfiguration(str(configFile))

        assert config is not None, "Config should not be None"


def test_runWorkflow_emptyConfig_handlesGracefully():
    """Test workflow handles empty config."""
    with patch('main.getLogger'):
        result = runWorkflow({})
    assert result is True, "Should handle empty config gracefully"


def test_main_configWithEnvFile_loadsCorrectly():
    """Test config loads with env file specified."""
    with tempfile.TemporaryDirectory() as tmpDir:
        configFile = Path(tmpDir) / 'config.json'
        envFile = Path(tmpDir) / '.env.test'

        with open(configFile, 'w') as f:
            json.dump(getSampleConfig(), f)
        with open(envFile, 'w') as f:
            f.write('TEST_VAR=value\n')

        with patch('sys.argv', ['main.py', '-c', str(configFile), '-e', str(envFile)]):
            with patch('main.setupLogging'), patch('main.getLogger'):
                result = main()

        assert result == EXIT_SUCCESS, f"Expected {EXIT_SUCCESS}, got {result}"


# ================================================================================
# Main Test Runner
# ================================================================================

if __name__ == '__main__':
    print("=" * 60)
    print("Running main.py tests")
    print("=" * 60)

    print("\nCLI Argument Parsing Tests:")
    runTest("parseArgs_noArgs_usesDefaults", test_parseArgs_noArgs_usesDefaults)
    runTest("parseArgs_customConfig_setsConfigPath", test_parseArgs_customConfig_setsConfigPath)
    runTest("parseArgs_shortConfigFlag_setsConfigPath", test_parseArgs_shortConfigFlag_setsConfigPath)
    runTest("parseArgs_envFile_setsEnvPath", test_parseArgs_envFile_setsEnvPath)
    runTest("parseArgs_shortEnvFlag_setsEnvPath", test_parseArgs_shortEnvFlag_setsEnvPath)
    runTest("parseArgs_dryRun_setsDryRunTrue", test_parseArgs_dryRun_setsDryRunTrue)
    runTest("parseArgs_verbose_setsVerboseTrue", test_parseArgs_verbose_setsVerboseTrue)
    runTest("parseArgs_shortVerboseFlag_setsVerboseTrue", test_parseArgs_shortVerboseFlag_setsVerboseTrue)
    runTest("parseArgs_multipleFlags_setsAllOptions", test_parseArgs_multipleFlags_setsAllOptions)
    runTest("parseArgs_helpFlag_exitsWithZero", test_parseArgs_helpFlag_exitsWithZero)
    runTest("parseArgs_versionFlag_exitsWithZero", test_parseArgs_versionFlag_exitsWithZero)

    print("\nConfiguration Loading Tests:")
    runTest("loadConfiguration_validConfig_returnsConfig", test_loadConfiguration_validConfig_returnsConfig)
    runTest("loadConfiguration_withEnvFile_resolvesSecrets", test_loadConfiguration_withEnvFile_resolvesSecrets)
    runTest("loadConfiguration_missingFile_raisesConfigError", test_loadConfiguration_missingFile_raisesConfigError)
    runTest("loadConfiguration_invalidJson_raisesError", test_loadConfiguration_invalidJson_raisesError)

    print("\nWorkflow Tests:")
    runTest("runWorkflow_normalMode_returnsTrue", test_runWorkflow_normalMode_returnsTrue)
    runTest("runWorkflow_dryRunMode_returnsTrue", test_runWorkflow_dryRunMode_returnsTrue)

    print("\nMain Function Tests:")
    runTest("main_successfulRun_returnsExitSuccess", test_main_successfulRun_returnsExitSuccess)
    runTest("main_configError_returnsExitConfigError", test_main_configError_returnsExitConfigError)
    runTest("main_workflowFails_returnsExitRuntimeError", test_main_workflowFails_returnsExitRuntimeError)
    runTest("main_unexpectedException_returnsExitUnknownError", test_main_unexpectedException_returnsExitUnknownError)
    runTest("main_verboseFlag_setsDebugLevel", test_main_verboseFlag_setsDebugLevel)
    runTest("main_normalMode_setsInfoLevel", test_main_normalMode_setsInfoLevel)
    runTest("main_dryRunFlag_passesToWorkflow", test_main_dryRunFlag_passesToWorkflow)

    print("\nEdge Case Tests:")
    runTest("main_keyboardInterrupt_returnsRuntimeError", test_main_keyboardInterrupt_returnsRuntimeError)
    runTest("loadConfiguration_emptyConfig_appliesDefaults", test_loadConfiguration_emptyConfig_appliesDefaults)
    runTest("runWorkflow_emptyConfig_handlesGracefully", test_runWorkflow_emptyConfig_handlesGracefully)
    runTest("main_configWithEnvFile_loadsCorrectly", test_main_configWithEnvFile_loadsCorrectly)

    print("\n" + "=" * 60)
    print(f"Results: {passedTests} passed, {failedTests} failed")
    print("=" * 60)

    if failedTestNames:
        print("\nFailed tests:")
        for name in failedTestNames:
            print(f"  - {name}")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)
