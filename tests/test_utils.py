################################################################################
# File Name: test_utils.py
# Purpose/Description: Test utilities and helper functions for test suites
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
Test utilities and helper functions.

This module provides reusable test utilities that complement the pytest fixtures
in conftest.py. Use these utilities for common test operations like creating
test data, asserting complex conditions, and mocking external services.

Usage:
    from tests.test_utils import createTestConfig, assertDictSubset, captureTime
"""

import contextlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import MagicMock

T = TypeVar('T')


# ================================================================================
# Test Data Factories
# ================================================================================

def createTestConfig(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Create a test configuration with optional overrides.

    Args:
        overrides: Dictionary of values to override in the base config

    Returns:
        Test configuration dictionary

    Example:
        >>> config = createTestConfig({'database': {'port': 5432}})
        >>> config['database']['port']
        5432
    """
    baseConfig = {
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
            'port': 1433,
            'timeout': 30
        },
        'api': {
            'baseUrl': 'https://api.test.com',
            'timeout': 30,
            'retry': {
                'maxRetries': 3,
                'retryDelayMs': 100
            }
        },
        'logging': {
            'level': 'DEBUG',
            'maskPII': True
        }
    }

    if overrides:
        _deepMerge(baseConfig, overrides)

    return baseConfig


def _deepMerge(base: dict[str, Any], overrides: dict[str, Any]) -> None:
    """
    Recursively merge overrides into base dictionary.

    Args:
        base: Base dictionary to merge into (modified in place)
        overrides: Dictionary of values to merge
    """
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deepMerge(base[key], value)
        else:
            base[key] = value


def createTestRecord(
    recordId: int = 1,
    name: str = "Test Record",
    **kwargs: Any
) -> dict[str, Any]:
    """
    Create a test record dictionary.

    Args:
        recordId: Record identifier
        name: Record name
        **kwargs: Additional fields to include

    Returns:
        Test record dictionary
    """
    record = {
        'id': recordId,
        'name': name,
        'createdAt': '2026-01-21T00:00:00Z',
        'updatedAt': None,
        'isActive': True
    }
    record.update(kwargs)
    return record


def createTestRecords(count: int, namePrefix: str = "Record") -> list[dict[str, Any]]:
    """
    Create multiple test records.

    Args:
        count: Number of records to create
        namePrefix: Prefix for record names

    Returns:
        List of test record dictionaries
    """
    return [
        createTestRecord(recordId=i + 1, name=f"{namePrefix} {i + 1}")
        for i in range(count)
    ]


# ================================================================================
# Assertion Helpers
# ================================================================================

def assertDictSubset(subset: dict[str, Any], superset: dict[str, Any]) -> None:
    """
    Assert that all keys/values in subset exist in superset.

    Args:
        subset: Dictionary that should be a subset
        superset: Dictionary that should contain all subset keys

    Raises:
        AssertionError: If subset is not contained in superset
    """
    for key, value in subset.items():
        assert key in superset, f"Key '{key}' not found in superset"
        if isinstance(value, dict) and isinstance(superset[key], dict):
            assertDictSubset(value, superset[key])
        else:
            assert superset[key] == value, (
                f"Value mismatch for key '{key}': "
                f"expected {value!r}, got {superset[key]!r}"
            )


def assertRaisesWithMessage(
    exceptionType: type,
    messageContains: str,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any
) -> None:
    """
    Assert that a function raises an exception with specific message content.

    Args:
        exceptionType: Expected exception type
        messageContains: Substring that should be in error message
        func: Function to call
        *args: Arguments to pass to function
        **kwargs: Keyword arguments to pass to function

    Raises:
        AssertionError: If exception not raised or message doesn't match
    """
    try:
        func(*args, **kwargs)
        raise AssertionError(f"Expected {exceptionType.__name__} was not raised")
    except exceptionType as e:
        assert messageContains in str(e), (
            f"Expected message to contain '{messageContains}', "
            f"got: {str(e)}"
        )


def assertWithinRange(
    value: float,
    minimum: float,
    maximum: float,
    message: str = ""
) -> None:
    """
    Assert that a value is within a specified range.

    Args:
        value: Value to check
        minimum: Minimum allowed value (inclusive)
        maximum: Maximum allowed value (inclusive)
        message: Optional custom message
    """
    assert minimum <= value <= maximum, (
        message or f"Value {value} not in range [{minimum}, {maximum}]"
    )


# ================================================================================
# Context Managers
# ================================================================================

@contextlib.contextmanager
def temporaryEnvVars(**envVars: str) -> Generator[None, None, None]:
    """
    Temporarily set environment variables for test scope.

    Args:
        **envVars: Environment variables to set

    Yields:
        None

    Example:
        >>> with temporaryEnvVars(DB_HOST='localhost', DB_PORT='5432'):
        ...     # Environment variables are set here
        ...     pass
        >>> # Variables are restored/removed after context
    """
    original: dict[str, str | None] = {}

    # Save and set
    for key, value in envVars.items():
        original[key] = os.environ.get(key)
        os.environ[key] = value

    try:
        yield
    finally:
        # Restore
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def temporaryFile(
    content: str,
    suffix: str = ".txt",
    encoding: str = "utf-8"
) -> Generator[Path, None, None]:
    """
    Create a temporary file with specified content.

    Args:
        content: Content to write to file
        suffix: File suffix (extension)
        encoding: File encoding

    Yields:
        Path to temporary file

    Example:
        >>> with temporaryFile('{"key": "value"}', suffix='.json') as path:
        ...     # File exists with content at this path
        ...     pass
        >>> # File is deleted after context
    """
    fd, tmpPath = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(content)
        yield Path(tmpPath)
    finally:
        if os.path.exists(tmpPath):
            os.unlink(tmpPath)


@contextlib.contextmanager
def temporaryJsonFile(data: dict[str, Any]) -> Generator[Path, None, None]:
    """
    Create a temporary JSON file with specified data.

    Args:
        data: Dictionary to serialize as JSON

    Yields:
        Path to temporary JSON file
    """
    content = json.dumps(data, indent=2)
    with temporaryFile(content, suffix='.json') as path:
        yield path


@contextlib.contextmanager
def captureTime() -> Generator[dict[str, float], None, None]:
    """
    Context manager to measure execution time.

    Yields:
        Dictionary with 'elapsed' key after context exits

    Example:
        >>> with captureTime() as timing:
        ...     # Do something
        ...     pass
        >>> print(f"Elapsed: {timing['elapsed']:.3f}s")
    """
    timing: dict[str, float] = {'elapsed': 0.0}
    start = time.perf_counter()
    try:
        yield timing
    finally:
        timing['elapsed'] = time.perf_counter() - start


# ================================================================================
# Mock Helpers
# ================================================================================

def createMockResponse(
    statusCode: int = 200,
    jsonData: dict[str, Any] | None = None,
    text: str = "",
    raiseForStatus: bool = False
) -> MagicMock:
    """
    Create a mock HTTP response object.

    Args:
        statusCode: HTTP status code
        jsonData: Data to return from .json() method
        text: Response text
        raiseForStatus: If True, raise_for_status raises exception

    Returns:
        MagicMock configured as HTTP response
    """
    mock = MagicMock()
    mock.status_code = statusCode
    mock.text = text
    mock.json.return_value = jsonData if jsonData is not None else {}

    if raiseForStatus and statusCode >= 400:
        mock.raise_for_status.side_effect = Exception(f"HTTP {statusCode}")
    else:
        mock.raise_for_status.return_value = None

    return mock


def createMockCursor(
    fetchallResult: list[Any] | None = None,
    fetchoneResult: Any | None = None,
    rowcount: int = 0
) -> MagicMock:
    """
    Create a mock database cursor.

    Args:
        fetchallResult: Result for fetchall()
        fetchoneResult: Result for fetchone()
        rowcount: Number of affected rows

    Returns:
        MagicMock configured as database cursor
    """
    cursor = MagicMock()
    cursor.fetchall.return_value = fetchallResult or []
    cursor.fetchone.return_value = fetchoneResult
    cursor.rowcount = rowcount
    return cursor


def createMockConnection(cursor: MagicMock | None = None) -> MagicMock:
    """
    Create a mock database connection.

    Args:
        cursor: Optional pre-configured cursor mock

    Returns:
        MagicMock configured as database connection
    """
    connection = MagicMock()
    cursorMock = cursor or createMockCursor()

    # Support both context manager and direct cursor() call
    connection.cursor.return_value = cursorMock
    connection.cursor.return_value.__enter__ = MagicMock(return_value=cursorMock)
    connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

    return connection


# ================================================================================
# Retry and Wait Helpers
# ================================================================================

def waitForCondition(
    condition: Callable[[], bool],
    timeoutSeconds: float = 5.0,
    pollIntervalSeconds: float = 0.1,
    message: str = "Condition not met within timeout"
) -> None:
    """
    Wait for a condition to become true.

    Args:
        condition: Callable that returns True when condition is met
        timeoutSeconds: Maximum time to wait
        pollIntervalSeconds: Time between condition checks
        message: Error message if timeout occurs

    Raises:
        TimeoutError: If condition not met within timeout
    """
    start = time.perf_counter()
    while time.perf_counter() - start < timeoutSeconds:
        if condition():
            return
        time.sleep(pollIntervalSeconds)
    raise TimeoutError(message)


def retry(
    func: Callable[[], T],
    maxAttempts: int = 3,
    delaySeconds: float = 0.1,
    exceptionTypes: tuple = (Exception,)
) -> T:
    """
    Retry a function on failure.

    Args:
        func: Function to retry
        maxAttempts: Maximum number of attempts
        delaySeconds: Delay between attempts
        exceptionTypes: Exception types to catch and retry

    Returns:
        Result of successful function call

    Raises:
        Last exception if all attempts fail
    """
    lastException: Exception | None = None

    for attempt in range(maxAttempts):
        try:
            return func()
        except exceptionTypes as e:
            lastException = e
            if attempt < maxAttempts - 1:
                time.sleep(delaySeconds)

    assert lastException is not None
    raise lastException


# ================================================================================
# Test Data Cleanup
# ================================================================================

class TestDataManager:
    """
    Manager for tracking and cleaning up test data.

    Usage:
        manager = TestDataManager()
        manager.addFile(pathToCleanup)
        manager.addEnvVar('TEST_VAR')
        # ... tests ...
        manager.cleanup()
    """

    def __init__(self) -> None:
        """Initialize empty tracking lists."""
        self._files: list[Path] = []
        self._envVars: dict[str, str | None] = {}

    def addFile(self, path: Path) -> None:
        """Track a file for cleanup."""
        self._files.append(path)

    def addEnvVar(self, key: str) -> None:
        """Track an environment variable for restoration."""
        if key not in self._envVars:
            self._envVars[key] = os.environ.get(key)

    def setEnvVar(self, key: str, value: str) -> None:
        """Set an environment variable and track for restoration."""
        self.addEnvVar(key)
        os.environ[key] = value

    def cleanup(self) -> None:
        """Clean up all tracked resources."""
        # Remove files
        for path in self._files:
            if path.exists():
                path.unlink()
        self._files.clear()

        # Restore environment variables
        for key, original in self._envVars.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        self._envVars.clear()

    def __enter__(self) -> 'TestDataManager':
        """Enter context manager."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context manager and cleanup."""
        self.cleanup()
