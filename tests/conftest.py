################################################################################
# File Name: conftest.py
# Purpose/Description: Pytest fixtures and configuration
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
Pytest configuration and shared fixtures.

Fixtures defined here are available to all test files automatically.

Usage:
    def test_something(sampleConfig, mockLogger):
        # sampleConfig and mockLogger are automatically injected
        pass
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
srcPath = Path(__file__).parent.parent / 'src'
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))


# ================================================================================
# Configuration Fixtures
# ================================================================================

@pytest.fixture
def sampleConfig() -> Dict[str, Any]:
    """
    Provide sample configuration for tests.

    Returns:
        Dictionary with test configuration values
    """
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


@pytest.fixture
def minimalConfig() -> Dict[str, Any]:
    """
    Provide minimal configuration for testing defaults.

    Returns:
        Dictionary with minimal configuration
    """
    return {
        'application': {
            'name': 'MinimalApp'
        }
    }


@pytest.fixture
def invalidConfig() -> Dict[str, Any]:
    """
    Provide invalid configuration for error testing.

    Returns:
        Dictionary with invalid/missing configuration
    """
    return {
        'application': {
            # Missing required fields
        }
    }


# ================================================================================
# Environment Fixtures
# ================================================================================

@pytest.fixture
def envVars() -> Generator[Dict[str, str], None, None]:
    """
    Set up test environment variables.

    Yields:
        Dictionary of environment variables that were set

    Automatically cleans up after test.
    """
    testVars = {
        'APP_ENVIRONMENT': 'test',
        'DB_SERVER': 'test-server',
        'DB_NAME': 'test-db',
        'DB_USER': 'test-user',
        'DB_PASSWORD': 'test-password',
        'API_BASE_URL': 'https://api.test.com',
        'API_CLIENT_ID': 'test-client',
        'API_CLIENT_SECRET': 'test-secret',
    }

    # Save original values
    originalVars = {}
    for key in testVars:
        originalVars[key] = os.environ.get(key)
        os.environ[key] = testVars[key]

    yield testVars

    # Restore original values
    for key, value in originalVars.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture
def cleanEnv() -> Generator[None, None, None]:
    """
    Ensure clean environment with no test variables.

    Removes common test variables before test, restores after.
    """
    varsToRemove = [
        'APP_ENVIRONMENT', 'DB_SERVER', 'DB_NAME', 'DB_USER',
        'DB_PASSWORD', 'API_BASE_URL', 'API_CLIENT_ID', 'API_CLIENT_SECRET',
        'TEST_VAR'  # Used by test_secrets_loader and test_main
    ]

    # Save and remove
    saved = {}
    for var in varsToRemove:
        saved[var] = os.environ.pop(var, None)

    yield

    # Restore
    for var, value in saved.items():
        if value is not None:
            os.environ[var] = value


# ================================================================================
# Mock Fixtures
# ================================================================================

@pytest.fixture
def mockLogger() -> MagicMock:
    """
    Provide mock logger for testing log calls.

    Returns:
        MagicMock logger instance
    """
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def mockApiResponse() -> Dict[str, Any]:
    """
    Provide mock API response data.

    Returns:
        Dictionary simulating API response
    """
    return {
        'data': [
            {'id': 1, 'name': 'Item 1'},
            {'id': 2, 'name': 'Item 2'},
            {'id': 3, 'name': 'Item 3'}
        ],
        'meta': {
            'total': 3,
            'page': 1,
            'pageSize': 10
        }
    }


@pytest.fixture
def mockDbConnection() -> MagicMock:
    """
    Provide mock database connection.

    Returns:
        MagicMock database connection
    """
    connection = MagicMock()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = None
    cursor.rowcount = 0
    connection.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    connection.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return connection


# ================================================================================
# File System Fixtures
# ================================================================================

@pytest.fixture
def tempConfigFile(tmp_path: Path, sampleConfig: Dict[str, Any]) -> Path:
    """
    Create temporary config file for testing.

    Args:
        tmp_path: Pytest temp directory fixture
        sampleConfig: Sample configuration fixture

    Returns:
        Path to temporary config file
    """
    import json

    configFile = tmp_path / 'config.json'
    with open(configFile, 'w') as f:
        json.dump(sampleConfig, f)

    return configFile


@pytest.fixture
def tempEnvFile(tmp_path: Path, envVars: Dict[str, str]) -> Path:
    """
    Create temporary .env file for testing.

    Args:
        tmp_path: Pytest temp directory fixture
        envVars: Environment variables fixture

    Returns:
        Path to temporary .env file
    """
    envFile = tmp_path / '.env'
    with open(envFile, 'w') as f:
        for key, value in envVars.items():
            f.write(f'{key}={value}\n')

    return envFile


# ================================================================================
# Utility Fixtures
# ================================================================================

@pytest.fixture
def assertNoLogs(caplog: pytest.LogCaptureFixture) -> Generator[None, None, None]:
    """
    Assert that no error logs were emitted during test.

    Usage:
        def test_something(assertNoLogs):
            # Test code here
            # Will fail if any ERROR logs are emitted
    """
    yield

    errors = [r for r in caplog.records if r.levelname == 'ERROR']
    assert len(errors) == 0, f"Unexpected error logs: {[r.message for r in errors]}"


# ================================================================================
# Pytest Configuration
# ================================================================================

def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests"
    )
