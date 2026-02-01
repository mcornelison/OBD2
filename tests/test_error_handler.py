################################################################################
# File Name: test_error_handler.py
# Purpose/Description: Tests for error handling and retry logic
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
Tests for the error_handler module.

Run with:
    pytest tests/test_error_handler.py -v
"""

import sys
from pathlib import Path

import pytest

srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from common.error_handler import (
    AuthenticationError,
    ConfigurationError,
    DataError,
    ErrorCategory,
    ErrorCollector,
    RetryableError,
    classifyError,
    formatError,
    handleError,
    retry,
)


class TestErrorCategories:
    """Tests for error classification."""

    def test_classifyError_retryableError_returnsRetryable(self):
        """
        Given: RetryableError instance
        When: classifyError() is called
        Then: Returns RETRYABLE category
        """
        error = RetryableError("Network timeout")

        result = classifyError(error)

        assert result == ErrorCategory.RETRYABLE

    def test_classifyError_authError_returnsAuth(self):
        """
        Given: AuthenticationError instance
        When: classifyError() is called
        Then: Returns AUTHENTICATION category
        """
        error = AuthenticationError("Invalid token")

        result = classifyError(error)

        assert result == ErrorCategory.AUTHENTICATION

    def test_classifyError_configError_returnsConfig(self):
        """
        Given: ConfigurationError instance
        When: classifyError() is called
        Then: Returns CONFIGURATION category
        """
        error = ConfigurationError("Missing field")

        result = classifyError(error)

        assert result == ErrorCategory.CONFIGURATION

    def test_classifyError_standardTimeoutError_returnsRetryable(self):
        """
        Given: Standard timeout exception
        When: classifyError() is called
        Then: Returns RETRYABLE category
        """
        error = TimeoutError("Connection timed out")

        result = classifyError(error)

        assert result == ErrorCategory.RETRYABLE

    def test_classifyError_unknownError_returnsSystem(self):
        """
        Given: Unknown exception type
        When: classifyError() is called
        Then: Returns SYSTEM category
        """
        error = RuntimeError("Something unexpected")

        result = classifyError(error)

        assert result == ErrorCategory.SYSTEM


class TestRetryDecorator:
    """Tests for the retry decorator."""

    def test_retry_successOnFirstTry_noRetries(self):
        """
        Given: Function that succeeds
        When: Called with retry decorator
        Then: No retries occur
        """
        callCount = 0

        @retry(maxRetries=3, initialDelay=0.01)
        def successfulFunc():
            nonlocal callCount
            callCount += 1
            return "success"

        result = successfulFunc()

        assert result == "success"
        assert callCount == 1

    def test_retry_failsThenSucceeds_retriesUntilSuccess(self):
        """
        Given: Function that fails twice then succeeds
        When: Called with retry decorator
        Then: Retries until success
        """
        callCount = 0

        @retry(maxRetries=3, initialDelay=0.01)
        def eventuallySucceeds():
            nonlocal callCount
            callCount += 1
            if callCount < 3:
                raise RetryableError("Temporary failure")
            return "success"

        result = eventuallySucceeds()

        assert result == "success"
        assert callCount == 3

    def test_retry_exceedsMaxRetries_raisesError(self):
        """
        Given: Function that always fails
        When: Called with retry decorator
        Then: Raises after max retries
        """
        @retry(maxRetries=2, initialDelay=0.01)
        def alwaysFails():
            raise RetryableError("Always fails")

        with pytest.raises(RetryableError):
            alwaysFails()

    def test_retry_nonRetryableError_raisesImmediately(self):
        """
        Given: Function that raises non-retryable error
        When: Called with retry decorator
        Then: Raises immediately without retry
        """
        callCount = 0

        @retry(maxRetries=3, initialDelay=0.01)
        def raisesConfigError():
            nonlocal callCount
            callCount += 1
            raise ConfigurationError("Config invalid")

        with pytest.raises(ConfigurationError):
            raisesConfigError()

        assert callCount == 1


class TestHandleError:
    """Tests for handleError function."""

    def test_handleError_withReraise_raisesError(self):
        """
        Given: Error and reraise=True
        When: handleError() is called
        Then: Error is re-raised
        """
        error = ConfigurationError("Test error")

        with pytest.raises(ConfigurationError):
            handleError(error, reraise=True)

    def test_handleError_withoutReraise_returnsDetails(self):
        """
        Given: Error and reraise=False
        When: handleError() is called
        Then: Returns error details
        """
        error = DataError("Invalid data")

        result = handleError(error, reraise=False)

        assert result['type'] == 'DataError'
        assert result['category'] == 'data'
        assert 'Invalid data' in result['message']


class TestFormatError:
    """Tests for formatError function."""

    def test_formatError_customError_formatsWithCategory(self):
        """
        Given: Custom error instance
        When: formatError() is called
        Then: Formats with category and message
        """
        error = RetryableError("Network timeout", details={'endpoint': '/api'})

        result = formatError(error)

        assert 'RETRYABLE' in result
        assert 'Network timeout' in result
        assert 'endpoint' in result

    def test_formatError_standardError_formatsCorrectly(self):
        """
        Given: Standard exception
        When: formatError() is called
        Then: Formats correctly
        """
        error = ValueError("Invalid value")

        result = formatError(error)

        assert 'ValueError' in result
        assert 'Invalid value' in result


class TestErrorCollector:
    """Tests for ErrorCollector class."""

    def test_errorCollector_addErrors_collectsAll(self):
        """
        Given: Multiple errors
        When: Added to collector
        Then: All errors are collected
        """
        collector = ErrorCollector()

        collector.add(ValueError("Error 1"), item='a')
        collector.add(ValueError("Error 2"), item='b')

        assert collector.count() == 2

    def test_errorCollector_hasErrors_returnsTrueWhenErrors(self):
        """
        Given: Collector with errors
        When: hasErrors() is called
        Then: Returns True
        """
        collector = ErrorCollector()
        collector.add(ValueError("Error"))

        assert collector.hasErrors() is True

    def test_errorCollector_hasErrors_returnsFalseWhenEmpty(self):
        """
        Given: Empty collector
        When: hasErrors() is called
        Then: Returns False
        """
        collector = ErrorCollector()

        assert collector.hasErrors() is False

    def test_errorCollector_clear_removesAllErrors(self):
        """
        Given: Collector with errors
        When: clear() is called
        Then: All errors are removed
        """
        collector = ErrorCollector()
        collector.add(ValueError("Error"))

        collector.clear()

        assert collector.count() == 0


class TestCustomExceptions:
    """Tests for custom exception classes."""

    def test_retryableError_toDict_returnsCorrectStructure(self):
        """
        Given: RetryableError with details
        When: toDict() is called
        Then: Returns correct structure
        """
        error = RetryableError(
            "Connection timeout",
            details={'host': 'example.com'}
        )

        result = error.toDict()

        assert result['type'] == 'RetryableError'
        assert result['category'] == 'retryable'
        assert result['message'] == 'Connection timeout'
        assert result['details']['host'] == 'example.com'


class TestEdgeCases:
    """Edge case tests for error handling."""

    def test_classifyError_connectionError_returnsRetryable(self):
        """
        Given: ConnectionError
        When: classifyError() is called
        Then: Returns RETRYABLE category
        """
        error = ConnectionError("Connection refused")

        result = classifyError(error)

        assert result == ErrorCategory.RETRYABLE

    def test_classifyError_rateLimitInMessage_returnsRetryable(self):
        """
        Given: Error with rate limit in message
        When: classifyError() is called
        Then: Returns RETRYABLE category
        """
        error = Exception("API rate limit exceeded")

        result = classifyError(error)

        assert result == ErrorCategory.RETRYABLE

    def test_classifyError_429InMessage_returnsRetryable(self):
        """
        Given: Error with 429 in message
        When: classifyError() is called
        Then: Returns RETRYABLE category
        """
        error = Exception("HTTP Error 429: Too Many Requests")

        result = classifyError(error)

        assert result == ErrorCategory.RETRYABLE

    def test_classifyError_emptyMessage_returnsSystem(self):
        """
        Given: Error with empty message
        When: classifyError() is called
        Then: Returns SYSTEM category
        """
        error = Exception("")

        result = classifyError(error)

        assert result == ErrorCategory.SYSTEM

    def test_retry_customRetryableExceptions_usesCustomList(self):
        """
        Given: Custom retryable exceptions
        When: Error matches custom list
        Then: Retries occur
        """
        callCount = 0

        @retry(maxRetries=2, initialDelay=0.01, retryableExceptions=[ValueError])
        def failsWithValueError():
            nonlocal callCount
            callCount += 1
            if callCount < 3:
                raise ValueError("Temporary")
            return "success"

        result = failsWithValueError()

        assert result == "success"
        assert callCount == 3

    def test_retry_preservesFunctionMetadata(self):
        """
        Given: Decorated function
        When: Checked
        Then: Preserves function name and docstring
        """
        @retry(maxRetries=1, initialDelay=0.01)
        def myFunction():
            """My docstring."""
            pass

        assert myFunction.__name__ == "myFunction"
        assert myFunction.__doc__ == "My docstring."

    def test_retry_withArgsAndKwargs_passesCorrectly(self):
        """
        Given: Decorated function with args and kwargs
        When: Called
        Then: Passes args and kwargs correctly
        """
        @retry(maxRetries=1, initialDelay=0.01)
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = greet("World", greeting="Hi")

        assert result == "Hi, World!"

    def test_handleError_withContext_includesContext(self):
        """
        Given: Error with context
        When: handleError() is called
        Then: Includes context in details
        """
        error = DataError("Failed")
        context = {'recordId': 123, 'file': 'data.csv'}

        result = handleError(error, context=context, reraise=False)

        assert result['context']['recordId'] == 123
        assert result['context']['file'] == 'data.csv'

    def test_errorCollector_storesCategory(self):
        """
        Given: Errors of different categories
        When: Added to collector
        Then: Stores category correctly
        """
        collector = ErrorCollector()
        collector.add(RetryableError("Network fail"))
        collector.add(ConfigurationError("Config fail"))

        assert collector.errors[0]['category'] == 'retryable'
        assert collector.errors[1]['category'] == 'config'

    def test_errorCollector_storesContext(self):
        """
        Given: Error with context
        When: Added to collector
        Then: Stores context
        """
        collector = ErrorCollector()
        collector.add(ValueError("Error"), recordId=123, file='data.csv')

        assert collector.errors[0]['context']['recordId'] == 123
        assert collector.errors[0]['context']['file'] == 'data.csv'

    def test_formatError_errorWithoutDetails_noDetailsInOutput(self):
        """
        Given: Error without details
        When: formatError() is called
        Then: No details in output
        """
        error = RetryableError("Timeout")

        result = formatError(error)

        assert 'RETRYABLE' in result
        assert 'Timeout' in result
        assert 'details' not in result
