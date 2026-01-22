#!/usr/bin/env python
################################################################################
# File Name: run_tests_error_handler.py
# Purpose/Description: Manual test runner for error_handler tests
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
################################################################################

"""
Manual test runner for error_handler module tests.

Run with:
    python run_tests_error_handler.py
"""

import sys
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from common.error_handler import (
    ErrorCategory,
    BaseError,
    RetryableError,
    AuthenticationError,
    ConfigurationError,
    DataError,
    SystemError,
    classifyError,
    retry,
    handleError,
    formatError,
    ErrorCollector
)

# Test counters
passedTests = 0
failedTests = 0
failedTestNames = []


def runTest(testName, testFunc):
    """Run a test and track results."""
    global passedTests, failedTests, failedTestNames
    try:
        testFunc()
        print(f"  PASS: {testName}")
        passedTests += 1
    except AssertionError as e:
        print(f"  FAIL: {testName}: {e}")
        failedTests += 1
        failedTestNames.append(testName)
    except Exception as e:
        print(f"  FAIL: {testName}: EXCEPTION - {e}")
        traceback.print_exc()
        failedTests += 1
        failedTestNames.append(testName)


# =============================================================================
# ErrorCategory Tests
# =============================================================================

print("\n--- ErrorCategory Tests ---")


def test_errorCategory_hasAllCategories():
    """Verify all error categories exist."""
    assert ErrorCategory.RETRYABLE.value == 'retryable'
    assert ErrorCategory.AUTHENTICATION.value == 'auth'
    assert ErrorCategory.CONFIGURATION.value == 'config'
    assert ErrorCategory.DATA.value == 'data'
    assert ErrorCategory.SYSTEM.value == 'system'


runTest("errorCategory_hasAllCategories", test_errorCategory_hasAllCategories)


# =============================================================================
# Custom Exception Tests
# =============================================================================

print("\n--- Custom Exception Tests ---")


def test_baseError_storesMessage():
    """Given: BaseError with message, When: created, Then: stores message."""
    error = BaseError("Test message")
    assert error.message == "Test message"
    assert str(error) == "Test message"


runTest("baseError_storesMessage", test_baseError_storesMessage)


def test_baseError_storesDetails():
    """Given: BaseError with details, When: created, Then: stores details."""
    details = {'key': 'value', 'count': 42}
    error = BaseError("Test", details=details)
    assert error.details == details


runTest("baseError_storesDetails", test_baseError_storesDetails)


def test_baseError_defaultsEmptyDetails():
    """Given: BaseError without details, When: created, Then: defaults to empty dict."""
    error = BaseError("Test")
    assert error.details == {}


runTest("baseError_defaultsEmptyDetails", test_baseError_defaultsEmptyDetails)


def test_baseError_toDict_returnsCorrectStructure():
    """Given: BaseError, When: toDict(), Then: returns correct structure."""
    error = BaseError("Error message", details={'endpoint': '/api'})
    result = error.toDict()

    assert result['type'] == 'BaseError'
    assert result['category'] == 'system'
    assert result['message'] == 'Error message'
    assert result['details']['endpoint'] == '/api'


runTest("baseError_toDict_returnsCorrectStructure", test_baseError_toDict_returnsCorrectStructure)


def test_retryableError_hasCorrectCategory():
    """Given: RetryableError, When: created, Then: has RETRYABLE category."""
    error = RetryableError("Timeout")
    assert error.category == ErrorCategory.RETRYABLE


runTest("retryableError_hasCorrectCategory", test_retryableError_hasCorrectCategory)


def test_authenticationError_hasCorrectCategory():
    """Given: AuthenticationError, When: created, Then: has AUTHENTICATION category."""
    error = AuthenticationError("Invalid token")
    assert error.category == ErrorCategory.AUTHENTICATION


runTest("authenticationError_hasCorrectCategory", test_authenticationError_hasCorrectCategory)


def test_configurationError_hasCorrectCategory():
    """Given: ConfigurationError, When: created, Then: has CONFIGURATION category."""
    error = ConfigurationError("Missing field")
    assert error.category == ErrorCategory.CONFIGURATION


runTest("configurationError_hasCorrectCategory", test_configurationError_hasCorrectCategory)


def test_dataError_hasCorrectCategory():
    """Given: DataError, When: created, Then: has DATA category."""
    error = DataError("Invalid format")
    assert error.category == ErrorCategory.DATA


runTest("dataError_hasCorrectCategory", test_dataError_hasCorrectCategory)


def test_systemError_hasCorrectCategory():
    """Given: SystemError, When: created, Then: has SYSTEM category."""
    error = SystemError("Unexpected error")
    assert error.category == ErrorCategory.SYSTEM


runTest("systemError_hasCorrectCategory", test_systemError_hasCorrectCategory)


# =============================================================================
# classifyError Tests
# =============================================================================

print("\n--- classifyError Tests ---")


def test_classifyError_retryableError_returnsRetryable():
    """Given: RetryableError, When: classifyError(), Then: returns RETRYABLE."""
    error = RetryableError("Network timeout")
    result = classifyError(error)
    assert result == ErrorCategory.RETRYABLE


runTest("classifyError_retryableError_returnsRetryable", test_classifyError_retryableError_returnsRetryable)


def test_classifyError_authError_returnsAuth():
    """Given: AuthenticationError, When: classifyError(), Then: returns AUTHENTICATION."""
    error = AuthenticationError("Invalid token")
    result = classifyError(error)
    assert result == ErrorCategory.AUTHENTICATION


runTest("classifyError_authError_returnsAuth", test_classifyError_authError_returnsAuth)


def test_classifyError_configError_returnsConfig():
    """Given: ConfigurationError, When: classifyError(), Then: returns CONFIGURATION."""
    error = ConfigurationError("Missing field")
    result = classifyError(error)
    assert result == ErrorCategory.CONFIGURATION


runTest("classifyError_configError_returnsConfig", test_classifyError_configError_returnsConfig)


def test_classifyError_dataError_returnsData():
    """Given: DataError, When: classifyError(), Then: returns DATA."""
    error = DataError("Invalid data")
    result = classifyError(error)
    assert result == ErrorCategory.DATA


runTest("classifyError_dataError_returnsData", test_classifyError_dataError_returnsData)


def test_classifyError_timeoutError_returnsRetryable():
    """Given: TimeoutError, When: classifyError(), Then: returns RETRYABLE."""
    error = TimeoutError("Connection timed out")
    result = classifyError(error)
    assert result == ErrorCategory.RETRYABLE


runTest("classifyError_timeoutError_returnsRetryable", test_classifyError_timeoutError_returnsRetryable)


def test_classifyError_connectionError_returnsRetryable():
    """Given: ConnectionError, When: classifyError(), Then: returns RETRYABLE."""
    error = ConnectionError("Connection refused")
    result = classifyError(error)
    assert result == ErrorCategory.RETRYABLE


runTest("classifyError_connectionError_returnsRetryable", test_classifyError_connectionError_returnsRetryable)


def test_classifyError_401InMessage_returnsAuth():
    """Given: Error with 401 in message, When: classifyError(), Then: returns AUTHENTICATION."""
    error = Exception("HTTP Error 401: Unauthorized")
    result = classifyError(error)
    assert result == ErrorCategory.AUTHENTICATION


runTest("classifyError_401InMessage_returnsAuth", test_classifyError_401InMessage_returnsAuth)


def test_classifyError_403InMessage_returnsAuth():
    """Given: Error with 403 in message, When: classifyError(), Then: returns AUTHENTICATION."""
    error = Exception("HTTP Error 403: Forbidden")
    result = classifyError(error)
    assert result == ErrorCategory.AUTHENTICATION


runTest("classifyError_403InMessage_returnsAuth", test_classifyError_403InMessage_returnsAuth)


def test_classifyError_rateLimitInMessage_returnsRetryable():
    """Given: Error with rate limit, When: classifyError(), Then: returns RETRYABLE."""
    error = Exception("API rate limit exceeded")
    result = classifyError(error)
    assert result == ErrorCategory.RETRYABLE


runTest("classifyError_rateLimitInMessage_returnsRetryable", test_classifyError_rateLimitInMessage_returnsRetryable)


def test_classifyError_429InMessage_returnsRetryable():
    """Given: Error with 429, When: classifyError(), Then: returns RETRYABLE."""
    error = Exception("HTTP Error 429: Too Many Requests")
    result = classifyError(error)
    assert result == ErrorCategory.RETRYABLE


runTest("classifyError_429InMessage_returnsRetryable", test_classifyError_429InMessage_returnsRetryable)


def test_classifyError_configInMessage_returnsConfig():
    """Given: Error with 'config' in message, When: classifyError(), Then: returns CONFIGURATION."""
    error = Exception("Config error: invalid settings")
    result = classifyError(error)
    assert result == ErrorCategory.CONFIGURATION


runTest("classifyError_configInMessage_returnsConfig", test_classifyError_configInMessage_returnsConfig)


def test_classifyError_missingInMessage_returnsConfig():
    """Given: Error with 'missing' in message, When: classifyError(), Then: returns CONFIGURATION."""
    error = Exception("Missing required field: database.server")
    result = classifyError(error)
    assert result == ErrorCategory.CONFIGURATION


runTest("classifyError_missingInMessage_returnsConfig", test_classifyError_missingInMessage_returnsConfig)


def test_classifyError_validationInMessage_returnsData():
    """Given: Error with 'validation' in message, When: classifyError(), Then: returns DATA."""
    error = Exception("Data validation failed")
    result = classifyError(error)
    assert result == ErrorCategory.DATA


runTest("classifyError_validationInMessage_returnsData", test_classifyError_validationInMessage_returnsData)


def test_classifyError_parseInMessage_returnsData():
    """Given: Error with 'parse' in message, When: classifyError(), Then: returns DATA."""
    error = Exception("Failed to parse JSON")
    result = classifyError(error)
    assert result == ErrorCategory.DATA


runTest("classifyError_parseInMessage_returnsData", test_classifyError_parseInMessage_returnsData)


def test_classifyError_unknownError_returnsSystem():
    """Given: Unknown error, When: classifyError(), Then: returns SYSTEM."""
    error = RuntimeError("Something unexpected happened")
    result = classifyError(error)
    assert result == ErrorCategory.SYSTEM


runTest("classifyError_unknownError_returnsSystem", test_classifyError_unknownError_returnsSystem)


# =============================================================================
# retry Decorator Tests
# =============================================================================

print("\n--- retry Decorator Tests ---")


def test_retry_successOnFirstTry_noRetries():
    """Given: Func that succeeds, When: called, Then: no retries occur."""
    callCount = 0

    @retry(maxRetries=3, initialDelay=0.01)
    def successfulFunc():
        nonlocal callCount
        callCount += 1
        return "success"

    result = successfulFunc()
    assert result == "success"
    assert callCount == 1


runTest("retry_successOnFirstTry_noRetries", test_retry_successOnFirstTry_noRetries)


def test_retry_failsThenSucceeds_retriesUntilSuccess():
    """Given: Func that fails twice then succeeds, When: called, Then: retries until success."""
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


runTest("retry_failsThenSucceeds_retriesUntilSuccess", test_retry_failsThenSucceeds_retriesUntilSuccess)


def test_retry_exceedsMaxRetries_raisesError():
    """Given: Func that always fails, When: called, Then: raises after max retries."""
    callCount = 0

    @retry(maxRetries=2, initialDelay=0.01)
    def alwaysFails():
        nonlocal callCount
        callCount += 1
        raise RetryableError("Always fails")

    try:
        alwaysFails()
        assert False, "Should have raised"
    except RetryableError:
        pass

    assert callCount == 3  # Initial + 2 retries


runTest("retry_exceedsMaxRetries_raisesError", test_retry_exceedsMaxRetries_raisesError)


def test_retry_nonRetryableError_raisesImmediately():
    """Given: Func that raises non-retryable error, When: called, Then: raises immediately."""
    callCount = 0

    @retry(maxRetries=3, initialDelay=0.01)
    def raisesConfigError():
        nonlocal callCount
        callCount += 1
        raise ConfigurationError("Config invalid")

    try:
        raisesConfigError()
        assert False, "Should have raised"
    except ConfigurationError:
        pass

    assert callCount == 1  # No retries


runTest("retry_nonRetryableError_raisesImmediately", test_retry_nonRetryableError_raisesImmediately)


def test_retry_customRetryableExceptions_usesCustomList():
    """Given: Custom retryable exceptions, When: error matches, Then: retries."""
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


runTest("retry_customRetryableExceptions_usesCustomList", test_retry_customRetryableExceptions_usesCustomList)


def test_retry_preservesFunctionName():
    """Given: Decorated function, When: checked, Then: preserves name."""
    @retry(maxRetries=1, initialDelay=0.01)
    def myFunction():
        pass

    assert myFunction.__name__ == "myFunction"


runTest("retry_preservesFunctionName", test_retry_preservesFunctionName)


def test_retry_preservesFunctionDocstring():
    """Given: Decorated function with docstring, When: checked, Then: preserves docstring."""
    @retry(maxRetries=1, initialDelay=0.01)
    def myFunction():
        """My docstring."""
        pass

    assert myFunction.__doc__ == "My docstring."


runTest("retry_preservesFunctionDocstring", test_retry_preservesFunctionDocstring)


def test_retry_exponentialBackoff_increasesDelay():
    """Given: Function with retries, When: retrying, Then: uses exponential backoff."""
    delays = []
    callCount = 0

    @retry(maxRetries=3, initialDelay=0.1, backoffMultiplier=2.0)
    def trackDelays():
        nonlocal callCount
        callCount += 1
        if callCount < 3:
            raise RetryableError("Fail")
        return "done"

    startTime = time.time()
    result = trackDelays()
    totalTime = time.time() - startTime

    # Should have waited approx 0.1 + 0.2 = 0.3 seconds
    assert totalTime >= 0.25  # Allow some tolerance
    assert result == "done"


runTest("retry_exponentialBackoff_increasesDelay", test_retry_exponentialBackoff_increasesDelay)


def test_retry_zeroMaxRetries_callsOnce():
    """Given: maxRetries=0, When: called, Then: calls once (no retries)."""
    callCount = 0

    @retry(maxRetries=0, initialDelay=0.01)
    def singleCall():
        nonlocal callCount
        callCount += 1
        raise RetryableError("Fail")

    try:
        singleCall()
    except RetryableError:
        pass

    assert callCount == 1


runTest("retry_zeroMaxRetries_callsOnce", test_retry_zeroMaxRetries_callsOnce)


# =============================================================================
# handleError Tests
# =============================================================================

print("\n--- handleError Tests ---")


def test_handleError_withReraise_raisesError():
    """Given: Error and reraise=True, When: handleError(), Then: error is re-raised."""
    error = ConfigurationError("Test error")

    try:
        handleError(error, reraise=True)
        assert False, "Should have raised"
    except ConfigurationError:
        pass


runTest("handleError_withReraise_raisesError", test_handleError_withReraise_raisesError)


def test_handleError_withoutReraise_returnsDetails():
    """Given: Error and reraise=False, When: handleError(), Then: returns error details."""
    error = DataError("Invalid data")

    result = handleError(error, reraise=False)

    assert result['type'] == 'DataError'
    assert result['category'] == 'data'
    assert 'Invalid data' in result['message']
    assert 'traceback' in result


runTest("handleError_withoutReraise_returnsDetails", test_handleError_withoutReraise_returnsDetails)


def test_handleError_withContext_includesContext():
    """Given: Error with context, When: handleError(), Then: includes context in details."""
    error = DataError("Failed")
    context = {'recordId': 123, 'file': 'data.csv'}

    result = handleError(error, context=context, reraise=False)

    assert result['context']['recordId'] == 123
    assert result['context']['file'] == 'data.csv'


runTest("handleError_withContext_includesContext", test_handleError_withContext_includesContext)


def test_handleError_noContext_defaultsEmptyContext():
    """Given: Error without context, When: handleError(), Then: context is empty."""
    error = DataError("Failed")

    result = handleError(error, reraise=False)

    assert result['context'] == {}


runTest("handleError_noContext_defaultsEmptyContext", test_handleError_noContext_defaultsEmptyContext)


# =============================================================================
# formatError Tests
# =============================================================================

print("\n--- formatError Tests ---")


def test_formatError_customError_formatsWithCategory():
    """Given: Custom error, When: formatError(), Then: formats with category and message."""
    error = RetryableError("Network timeout", details={'endpoint': '/api'})

    result = formatError(error)

    assert 'RETRYABLE' in result
    assert 'Network timeout' in result
    assert 'endpoint' in result


runTest("formatError_customError_formatsWithCategory", test_formatError_customError_formatsWithCategory)


def test_formatError_standardError_formatsCorrectly():
    """Given: Standard exception, When: formatError(), Then: formats correctly."""
    error = ValueError("Invalid value")

    result = formatError(error)

    assert 'ValueError' in result
    assert 'Invalid value' in result


runTest("formatError_standardError_formatsCorrectly", test_formatError_standardError_formatsCorrectly)


def test_formatError_errorWithoutDetails_noDetailsInOutput():
    """Given: Error without details, When: formatError(), Then: no details in output."""
    error = RetryableError("Timeout")

    result = formatError(error)

    assert 'RETRYABLE' in result
    assert 'Timeout' in result
    assert 'details' not in result


runTest("formatError_errorWithoutDetails_noDetailsInOutput", test_formatError_errorWithoutDetails_noDetailsInOutput)


# =============================================================================
# ErrorCollector Tests
# =============================================================================

print("\n--- ErrorCollector Tests ---")


def test_errorCollector_addErrors_collectsAll():
    """Given: Multiple errors, When: added to collector, Then: all errors collected."""
    collector = ErrorCollector()

    collector.add(ValueError("Error 1"), item='a')
    collector.add(ValueError("Error 2"), item='b')

    assert collector.count() == 2


runTest("errorCollector_addErrors_collectsAll", test_errorCollector_addErrors_collectsAll)


def test_errorCollector_hasErrors_returnsTrueWhenErrors():
    """Given: Collector with errors, When: hasErrors(), Then: returns True."""
    collector = ErrorCollector()
    collector.add(ValueError("Error"))

    assert collector.hasErrors() is True


runTest("errorCollector_hasErrors_returnsTrueWhenErrors", test_errorCollector_hasErrors_returnsTrueWhenErrors)


def test_errorCollector_hasErrors_returnsFalseWhenEmpty():
    """Given: Empty collector, When: hasErrors(), Then: returns False."""
    collector = ErrorCollector()

    assert collector.hasErrors() is False


runTest("errorCollector_hasErrors_returnsFalseWhenEmpty", test_errorCollector_hasErrors_returnsFalseWhenEmpty)


def test_errorCollector_clear_removesAllErrors():
    """Given: Collector with errors, When: clear(), Then: all errors removed."""
    collector = ErrorCollector()
    collector.add(ValueError("Error"))

    collector.clear()

    assert collector.count() == 0


runTest("errorCollector_clear_removesAllErrors", test_errorCollector_clear_removesAllErrors)


def test_errorCollector_storesCategory():
    """Given: Errors of different categories, When: added, Then: stores category."""
    collector = ErrorCollector()
    collector.add(RetryableError("Network fail"))
    collector.add(ConfigurationError("Config fail"))

    assert collector.errors[0]['category'] == 'retryable'
    assert collector.errors[1]['category'] == 'config'


runTest("errorCollector_storesCategory", test_errorCollector_storesCategory)


def test_errorCollector_storesContext():
    """Given: Error with context, When: added, Then: stores context."""
    collector = ErrorCollector()
    collector.add(ValueError("Error"), recordId=123, file='data.csv')

    assert collector.errors[0]['context']['recordId'] == 123
    assert collector.errors[0]['context']['file'] == 'data.csv'


runTest("errorCollector_storesContext", test_errorCollector_storesContext)


def test_errorCollector_report_noErrors_doesNothing():
    """Given: Empty collector, When: report(), Then: does nothing."""
    collector = ErrorCollector()
    collector.report()  # Should not raise


runTest("errorCollector_report_noErrors_doesNothing", test_errorCollector_report_noErrors_doesNothing)


# =============================================================================
# Edge Cases Tests
# =============================================================================

print("\n--- Edge Cases Tests ---")


def test_baseError_noneDetails_defaultsToEmptyDict():
    """Given: BaseError with None details, When: created, Then: defaults to empty dict."""
    error = BaseError("Test", details=None)
    assert error.details == {}


runTest("baseError_noneDetails_defaultsToEmptyDict", test_baseError_noneDetails_defaultsToEmptyDict)


def test_classifyError_emptyMessage_returnsSystem():
    """Given: Error with empty message, When: classifyError(), Then: returns SYSTEM."""
    error = Exception("")
    result = classifyError(error)
    assert result == ErrorCategory.SYSTEM


runTest("classifyError_emptyMessage_returnsSystem", test_classifyError_emptyMessage_returnsSystem)


def test_classifyError_caseInsensitiveMatching():
    """Given: Error with uppercase keywords, When: classifyError(), Then: matches correctly."""
    error = Exception("RATE LIMIT EXCEEDED")
    result = classifyError(error)
    assert result == ErrorCategory.RETRYABLE


runTest("classifyError_caseInsensitiveMatching", test_classifyError_caseInsensitiveMatching)


def test_retry_withArgs_passesArgsCorrectly():
    """Given: Decorated function with args, When: called, Then: passes args correctly."""
    @retry(maxRetries=1, initialDelay=0.01)
    def addNumbers(a, b):
        return a + b

    result = addNumbers(3, 5)
    assert result == 8


runTest("retry_withArgs_passesArgsCorrectly", test_retry_withArgs_passesArgsCorrectly)


def test_retry_withKwargs_passesKwargsCorrectly():
    """Given: Decorated function with kwargs, When: called, Then: passes kwargs correctly."""
    @retry(maxRetries=1, initialDelay=0.01)
    def greet(name, greeting="Hello"):
        return f"{greeting}, {name}!"

    result = greet("World", greeting="Hi")
    assert result == "Hi, World!"


runTest("retry_withKwargs_passesKwargsCorrectly", test_retry_withKwargs_passesKwargsCorrectly)


def test_formatError_classifiedStandardError_usesClassifiedCategory():
    """Given: Standard error that gets classified, When: formatError(), Then: uses classified category."""
    error = TimeoutError("Connection timed out")
    result = formatError(error)
    assert 'RETRYABLE' in result


runTest("formatError_classifiedStandardError_usesClassifiedCategory", test_formatError_classifiedStandardError_usesClassifiedCategory)


def test_errorCollector_emptyContext_storesEmptyDict():
    """Given: Error with no context, When: added, Then: stores empty dict."""
    collector = ErrorCollector()
    collector.add(ValueError("Error"))

    assert collector.errors[0]['context'] == {}


runTest("errorCollector_emptyContext_storesEmptyDict", test_errorCollector_emptyContext_storesEmptyDict)


def test_handleError_traceback_isPopulated():
    """Given: Error, When: handleError(), Then: traceback is populated."""
    error = ValueError("Test error")
    result = handleError(error, reraise=False)

    assert 'traceback' in result
    assert len(result['traceback']) > 0


runTest("handleError_traceback_isPopulated", test_handleError_traceback_isPopulated)


# =============================================================================
# Summary
# =============================================================================

print("\n" + "=" * 50)
print(f"Test Results: {passedTests} passed, {failedTests} failed")
print("=" * 50)

if failedTestNames:
    print("\nFailed tests:")
    for name in failedTestNames:
        print(f"  - {name}")

sys.exit(0 if failedTests == 0 else 1)
