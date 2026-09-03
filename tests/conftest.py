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
import shutil
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Add src to path for imports
srcPath = Path(__file__).parent.parent / 'src'
if str(srcPath) not in sys.path:
    sys.path.insert(0, str(srcPath))


# ================================================================================
# Configuration Fixtures
# ================================================================================

@pytest.fixture
def sampleConfig() -> dict[str, Any]:
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
def minimalConfig() -> dict[str, Any]:
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
def invalidConfig() -> dict[str, Any]:
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
def envVars() -> Generator[dict[str, str], None, None]:
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
def mockApiResponse() -> dict[str, Any]:
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
def tempConfigFile(tmp_path: Path, sampleConfig: dict[str, Any]) -> Path:
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
def tempEnvFile(tmp_path: Path, envVars: dict[str, str]) -> Path:
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
    config.addinivalue_line(
        "markers",
        "pi_only: test requires Pi hardware (I2C/GPIO/BT/Linux-ARM); "
        "auto-skipped off-Pi unless ECLIPSE_PI_HOST=1",
    )


def _isRunningOnPi() -> bool:
    """
    Decide whether the current pytest invocation is allowed to run @pi_only tests.

    Pi hardware tests (I2C probes, GPIO wiring, BT dongle pairing) need real
    hardware. They live under @pytest.mark.pi_only and are auto-skipped unless
    EITHER the opt-in env var ECLIPSE_PI_HOST=1 is set, OR we detect we're
    actually on aarch64 Linux (the Pi). Windows and x86_64 Linux dev boxes
    always skip.

    Returns:
        True when pi_only tests should be collected and run.
    """
    import platform

    if os.environ.get('ECLIPSE_PI_HOST') == '1':
        return True
    if sys.platform == 'linux' and platform.machine() == 'aarch64':
        return True
    return False


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip @pi_only tests on non-Pi platforms unless opted in."""
    if _isRunningOnPi():
        return
    skipMarker = pytest.mark.skip(
        reason='pi_only: requires Pi hardware; set ECLIPSE_PI_HOST=1 to run'
    )
    for item in items:
        if 'pi_only' in item.keywords:
            item.add_marker(skipMarker)


# ==============================================================================
# Deterministic `bash` (2026-08-27; made effective 2026-09-03)
# ==============================================================================
#
# THIS RUNS AT IMPORT, NOT AS A FIXTURE, AND THAT IS THE WHOLE POINT.
#
# The original was a session-scoped autouse fixture. A session fixture runs at the
# first test's SETUP -- which is after pytest has imported every test module. The
# 27 modules this protects resolve bash at MODULE level:
#
#     _BASH_PATH = shutil.which("bash")      # tests/scripts/test_*_sh.py
#
# so they had already captured whichever bash PATH offered before the fixture ever
# ran. Prepending PATH afterwards changed nothing they would ever look at.
#
# It LOOKED like it worked, because it was only ever exercised from shells whose
# PATH already had git-bash first -- in which case the ambient PATH did the job and
# the fixture was inert. Launched from a shell with System32 first (a detached
# pwsh, a scheduled task, CI) the 22 shell-out tests failed on the WSL stub's
# Microsoft Store advert, exactly as before the fix.
#
# Found 2026-09-03 while capturing the Phase H baseline: a clean-looking capture
# reported 49 failures against a recorded baseline of 26, and 22 of the excess were
# this. A fix that only works when it is not needed is worse than none -- it closes
# the ticket.
#
# conftest.py is imported before any test module is collected, so doing the work
# here is early enough for a module-level shutil.which() to see it.

_BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(r"C:\Program Files (x86)\Git\bin\bash.exe"),
]


def _prependRealBashToPath() -> None:
    """Put a real bash ahead of the WSL stub, at import time."""
    if sys.platform != "win32":
        return
    real = next((c for c in _BASH_CANDIDATES if c.is_file()), None)
    if real is None:
        raise pytest.UsageError(
            "No git-bash found. Bare 'bash' resolves to the WSL stub, which exits 1 "
            "with a Microsoft Store advert and fails ~22 shell-out tests for reasons "
            "that have nothing to do with the code. Install Git for Windows or fix PATH."
        )
    parent = str(real.parent)
    current = os.environ.get("PATH", "")
    # Idempotent: pytest may import this conftest more than once.
    if current.lower().startswith(parent.lower() + os.pathsep):
        return
    os.environ["PATH"] = f"{parent}{os.pathsep}{current}"


_prependRealBashToPath()


@pytest.fixture(scope="session", autouse=True)
def _deterministicBash() -> Generator[None, None, None]:
    r"""Make bare ``bash`` resolve to a REAL bash for the whole session.

    27 test files shell out to ``['bash', ...]`` with no shared helper, so which
    binary answers is decided by PATH order. On this machine PATH carries two:

        C:\Program Files\Git\usr\bin\bash.exe   -- git-bash, works
        C:\Windows\System32\bash.exe              -- WSL launcher

    With no WSL distribution installed the second is a STUB: it prints "Windows
    Subsystem for Linux has no installed distributions... visit the Microsoft
    Store" and exits 1. Every test that shelled out then failed on
    ``assert returncode == 0`` with a store advert in stdout.

    That is what 54 of this repo's "known baseline failures" actually were --
    an environment accident, not defects. They passed or failed depending on
    which shell launched pytest, and were recorded as permanent.

    This prepends a working bash so the answer is the same every run. If none is
    found we FAIL LOUDLY rather than let the suite quietly re-enter that state:
    a silent 54-test regression is exactly what took weeks to notice.
    """
    # The PATH work already happened at import (see above). This fixture now
    # ASSERTS the invariant rather than establishing it -- if bare `bash` is still
    # the WSL stub at run time, fail loudly instead of producing 22 failures that
    # look like code defects.
    if sys.platform != "win32":
        yield
        return

    resolved = shutil.which("bash")
    if resolved and "system32" in resolved.lower():
        pytest.exit(
            f"Bare 'bash' still resolves to {resolved} -- the WSL stub. The "
            f"import-time PATH fix did not take. ~22 shell-out tests would fail "
            f"with a Microsoft Store advert and look like real defects.",
            returncode=1,
        )
    yield
