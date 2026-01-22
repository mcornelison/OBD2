#!/usr/bin/env python
################################################################################
# File Name: run_tests_logging.py
# Purpose/Description: Manual test runner for logging_config tests
# Author: Michael Cornelison
# Creation Date: 2026-01-21
# Copyright: (c) 2026 Michael Cornelison. All rights reserved.
################################################################################

"""
Manual test runner for logging_config module tests.

Run with:
    python run_tests_logging.py
"""

import logging
import sys
import traceback
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

# Add src to path
srcPath = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(srcPath))

from common.logging_config import (
    DEFAULT_DATE_FORMAT,
    DEFAULT_FORMAT,
    LogContext,
    PIIMaskingFilter,
    PII_PATTERNS,
    StructuredFormatter,
    getLogger,
    logWithContext,
    setupLogging,
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


def createLogRecord(msg, level=logging.INFO):
    """Helper to create log records for testing."""
    return logging.LogRecord(
        name='test',
        level=level,
        pathname='test.py',
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None
    )


# =============================================================================
# PIIMaskingFilter Tests
# =============================================================================

print("\n--- PIIMaskingFilter Tests ---")


def test_filter_emailInMessage_masksEmail():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('User email is test@example.com')
    piiFilter.filter(record)
    assert '[EMAIL_MASKED]' in record.msg
    assert 'test@example.com' not in record.msg


runTest("filter_emailInMessage_masksEmail", test_filter_emailInMessage_masksEmail)


def test_filter_multipleEmails_masksAll():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('From user@one.com to admin@two.com')
    piiFilter.filter(record)
    assert record.msg.count('[EMAIL_MASKED]') == 2


runTest("filter_multipleEmails_masksAll", test_filter_multipleEmails_masksAll)


def test_filter_phoneWithDashes_masksPhone():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('Call 555-123-4567 for support')
    piiFilter.filter(record)
    assert '[PHONE_MASKED]' in record.msg
    assert '555-123-4567' not in record.msg


runTest("filter_phoneWithDashes_masksPhone", test_filter_phoneWithDashes_masksPhone)


def test_filter_phoneWithDots_masksPhone():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('Contact 555.123.4567')
    piiFilter.filter(record)
    assert '[PHONE_MASKED]' in record.msg


runTest("filter_phoneWithDots_masksPhone", test_filter_phoneWithDots_masksPhone)


def test_filter_phoneNoDashes_masksPhone():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('Number: 5551234567')
    piiFilter.filter(record)
    assert '[PHONE_MASKED]' in record.msg


runTest("filter_phoneNoDashes_masksPhone", test_filter_phoneNoDashes_masksPhone)


def test_filter_ssn_masksSSN():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('SSN is 123-45-6789')
    piiFilter.filter(record)
    assert '[SSN_MASKED]' in record.msg
    assert '123-45-6789' not in record.msg


runTest("filter_ssn_masksSSN", test_filter_ssn_masksSSN)


def test_filter_mixedPII_masksAll():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('User test@email.com phone 555-123-4567 ssn 123-45-6789')
    piiFilter.filter(record)
    assert '[EMAIL_MASKED]' in record.msg
    assert '[PHONE_MASKED]' in record.msg
    assert '[SSN_MASKED]' in record.msg


runTest("filter_mixedPII_masksAll", test_filter_mixedPII_masksAll)


def test_filter_noPII_returnsUnchanged():
    piiFilter = PIIMaskingFilter()
    originalMsg = 'Processing batch | batchId=123 | count=50'
    record = createLogRecord(originalMsg)
    piiFilter.filter(record)
    assert record.msg == originalMsg


runTest("filter_noPII_returnsUnchanged", test_filter_noPII_returnsUnchanged)


def test_filter_alwaysReturnsTrue():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord('Any message')
    result = piiFilter.filter(record)
    assert result is True


runTest("filter_alwaysReturnsTrue", test_filter_alwaysReturnsTrue)


# =============================================================================
# StructuredFormatter Tests
# =============================================================================

print("\n--- StructuredFormatter Tests ---")


def test_format_basicMessage_formatsCorrectly():
    formatter = StructuredFormatter(fmt='%(levelname)s | %(message)s')
    record = createLogRecord('Test message')
    result = formatter.format(record)
    assert 'INFO' in result
    assert 'Test message' in result


runTest("format_basicMessage_formatsCorrectly", test_format_basicMessage_formatsCorrectly)


def test_format_withExtraDict_appendsFields():
    formatter = StructuredFormatter(fmt='%(levelname)s | %(message)s')
    record = createLogRecord('Test message')
    record.extra = {'batchId': 123, 'count': 50}
    result = formatter.format(record)
    assert 'batchId=123' in result
    assert 'count=50' in result


runTest("format_withExtraDict_appendsFields", test_format_withExtraDict_appendsFields)


def test_format_noExtra_noAppendedFields():
    formatter = StructuredFormatter(fmt='%(levelname)s | %(message)s')
    record = createLogRecord('Test message')
    result = formatter.format(record)
    assert result == 'INFO | Test message'


runTest("format_noExtra_noAppendedFields", test_format_noExtra_noAppendedFields)


# =============================================================================
# setupLogging Tests
# =============================================================================

print("\n--- setupLogging Tests ---")


def test_setupLogging_defaultLevel_setsInfoLevel():
    logger = setupLogging(level='INFO')
    assert logger.level == logging.INFO


runTest("setupLogging_defaultLevel_setsInfoLevel", test_setupLogging_defaultLevel_setsInfoLevel)


def test_setupLogging_debugLevel_setsDebugLevel():
    logger = setupLogging(level='DEBUG')
    assert logger.level == logging.DEBUG


runTest("setupLogging_debugLevel_setsDebugLevel", test_setupLogging_debugLevel_setsDebugLevel)


def test_setupLogging_warningLevel_setsWarningLevel():
    logger = setupLogging(level='WARNING')
    assert logger.level == logging.WARNING


runTest("setupLogging_warningLevel_setsWarningLevel", test_setupLogging_warningLevel_setsWarningLevel)


def test_setupLogging_errorLevel_setsErrorLevel():
    logger = setupLogging(level='ERROR')
    assert logger.level == logging.ERROR


runTest("setupLogging_errorLevel_setsErrorLevel", test_setupLogging_errorLevel_setsErrorLevel)


def test_setupLogging_invalidLevel_defaultsToInfo():
    logger = setupLogging(level='INVALID')
    assert logger.level == logging.INFO


runTest("setupLogging_invalidLevel_defaultsToInfo", test_setupLogging_invalidLevel_defaultsToInfo)


def test_setupLogging_addsConsoleHandler():
    logger = setupLogging()
    assert len(logger.handlers) >= 1
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)


runTest("setupLogging_addsConsoleHandler", test_setupLogging_addsConsoleHandler)


def test_setupLogging_piiMaskingEnabled_addsPIIFilter():
    logger = setupLogging(enablePIIMasking=True)
    for handler in logger.handlers:
        hasFilter = any(isinstance(f, PIIMaskingFilter) for f in handler.filters)
        assert hasFilter, "Expected PIIMaskingFilter on handler"


runTest("setupLogging_piiMaskingEnabled_addsPIIFilter", test_setupLogging_piiMaskingEnabled_addsPIIFilter)


def test_setupLogging_piiMaskingDisabled_noPIIFilter():
    logger = setupLogging(enablePIIMasking=False)
    for handler in logger.handlers:
        hasFilter = any(isinstance(f, PIIMaskingFilter) for f in handler.filters)
        assert not hasFilter, "Expected no PIIMaskingFilter on handler"


runTest("setupLogging_piiMaskingDisabled_noPIIFilter", test_setupLogging_piiMaskingDisabled_noPIIFilter)


def test_setupLogging_customFormat_usesCustomFormat():
    customFormat = '%(message)s'
    logger = setupLogging(logFormat=customFormat)
    for handler in logger.handlers:
        assert handler.formatter._fmt == customFormat


runTest("setupLogging_customFormat_usesCustomFormat", test_setupLogging_customFormat_usesCustomFormat)


# =============================================================================
# getLogger Tests
# =============================================================================

print("\n--- getLogger Tests ---")


def test_getLogger_validName_returnsLogger():
    logger = getLogger('test.module')
    assert isinstance(logger, logging.Logger)
    assert logger.name == 'test.module'


runTest("getLogger_validName_returnsLogger", test_getLogger_validName_returnsLogger)


def test_getLogger_sameName_returnsSameLogger():
    logger1 = getLogger('test.same')
    logger2 = getLogger('test.same')
    assert logger1 is logger2


runTest("getLogger_sameName_returnsSameLogger", test_getLogger_sameName_returnsSameLogger)


# =============================================================================
# logWithContext Tests
# =============================================================================

print("\n--- logWithContext Tests ---")


def test_logWithContext_withContext_appendsContext():
    mockLogger = MagicMock()
    logWithContext(mockLogger, 'info', 'Processing batch', batchId=123, count=50)
    mockLogger.info.assert_called_once()
    callArgs = mockLogger.info.call_args[0][0]
    assert 'Processing batch' in callArgs
    assert 'batchId=123' in callArgs
    assert 'count=50' in callArgs


runTest("logWithContext_withContext_appendsContext", test_logWithContext_withContext_appendsContext)


def test_logWithContext_noContext_logsPlainMessage():
    mockLogger = MagicMock()
    logWithContext(mockLogger, 'info', 'Plain message')
    mockLogger.info.assert_called_once_with('Plain message')


runTest("logWithContext_noContext_logsPlainMessage", test_logWithContext_noContext_logsPlainMessage)


def test_logWithContext_debugLevel_callsDebug():
    mockLogger = MagicMock()
    logWithContext(mockLogger, 'debug', 'Debug message')
    mockLogger.debug.assert_called_once()


runTest("logWithContext_debugLevel_callsDebug", test_logWithContext_debugLevel_callsDebug)


def test_logWithContext_errorLevel_callsError():
    mockLogger = MagicMock()
    logWithContext(mockLogger, 'error', 'Error message')
    mockLogger.error.assert_called_once()


runTest("logWithContext_errorLevel_callsError", test_logWithContext_errorLevel_callsError)


# =============================================================================
# LogContext Tests
# =============================================================================

print("\n--- LogContext Tests ---")


def test_logContext_enterAndExit_modifiesFactory():
    originalFactory = logging.getLogRecordFactory()
    with LogContext(requestId='abc123'):
        inContextFactory = logging.getLogRecordFactory()
        assert inContextFactory != originalFactory
    afterFactory = logging.getLogRecordFactory()
    assert afterFactory == originalFactory


runTest("logContext_enterAndExit_modifiesFactory", test_logContext_enterAndExit_modifiesFactory)


def test_logContext_inContext_addsExtraToRecords():
    with LogContext(requestId='abc123', userId=42):
        factory = logging.getLogRecordFactory()
        record = factory(
            name='test', level=logging.INFO, pathname='test.py',
            lineno=1, msg='Test', args=(), exc_info=None
        )
        assert hasattr(record, 'extra')
        assert record.extra['requestId'] == 'abc123'
        assert record.extra['userId'] == 42


runTest("logContext_inContext_addsExtraToRecords", test_logContext_inContext_addsExtraToRecords)


def test_logContext_returnsItself():
    ctx = LogContext(key='value')
    with ctx as returned:
        assert returned is ctx


runTest("logContext_returnsItself", test_logContext_returnsItself)


# =============================================================================
# PII Patterns Tests
# =============================================================================

print("\n--- PII Patterns Tests ---")


def test_piiPatterns_email_matchesValidEmails():
    pattern = PII_PATTERNS['email']
    assert pattern.search('user@example.com')
    assert pattern.search('user.name@sub.domain.com')
    assert pattern.search('user+tag@example.com')


runTest("piiPatterns_email_matchesValidEmails", test_piiPatterns_email_matchesValidEmails)


def test_piiPatterns_email_notMatchesInvalid():
    pattern = PII_PATTERNS['email']
    assert pattern.search('not an email') is None
    assert pattern.search('user@') is None


runTest("piiPatterns_email_notMatchesInvalid", test_piiPatterns_email_notMatchesInvalid)


def test_piiPatterns_phone_matchesValidPhones():
    pattern = PII_PATTERNS['phone']
    assert pattern.search('555-123-4567')
    assert pattern.search('555.123.4567')
    assert pattern.search('5551234567')


runTest("piiPatterns_phone_matchesValidPhones", test_piiPatterns_phone_matchesValidPhones)


def test_piiPatterns_ssn_matchesValidSSN():
    pattern = PII_PATTERNS['ssn']
    assert pattern.search('123-45-6789')
    assert pattern.search('000-00-0000')


runTest("piiPatterns_ssn_matchesValidSSN", test_piiPatterns_ssn_matchesValidSSN)


# =============================================================================
# Default Formats Tests
# =============================================================================

print("\n--- Default Formats Tests ---")


def test_defaultFormat_containsRequiredFields():
    assert '%(asctime)s' in DEFAULT_FORMAT
    assert '%(levelname)' in DEFAULT_FORMAT
    assert '%(name)s' in DEFAULT_FORMAT
    assert '%(message)s' in DEFAULT_FORMAT


runTest("defaultFormat_containsRequiredFields", test_defaultFormat_containsRequiredFields)


def test_defaultDateFormat_isValid():
    from datetime import datetime
    datetime.now().strftime(DEFAULT_DATE_FORMAT)  # Should not raise


runTest("defaultDateFormat_isValid", test_defaultDateFormat_isValid)


# =============================================================================
# Edge Cases Tests
# =============================================================================

print("\n--- Edge Cases Tests ---")


def test_filter_nonStringMessage_handlesGracefully():
    piiFilter = PIIMaskingFilter()
    record = createLogRecord(12345)  # Non-string
    result = piiFilter.filter(record)
    assert result is True


runTest("filter_nonStringMessage_handlesGracefully", test_filter_nonStringMessage_handlesGracefully)


def test_setupLogging_lowercaseLevel_worksCorrectly():
    logger = setupLogging(level='debug')
    assert logger.level == logging.DEBUG


runTest("setupLogging_lowercaseLevel_worksCorrectly", test_setupLogging_lowercaseLevel_worksCorrectly)


def test_logContext_emptyContext_works():
    with LogContext():
        pass  # Should not raise


runTest("logContext_emptyContext_works", test_logContext_emptyContext_works)


def test_maskPII_emptyString_returnsEmptyString():
    piiFilter = PIIMaskingFilter()
    result = piiFilter._maskPII('')
    assert result == ''


runTest("maskPII_emptyString_returnsEmptyString", test_maskPII_emptyString_returnsEmptyString)


def test_formatter_extraNotDict_ignoresExtra():
    formatter = StructuredFormatter(fmt='%(message)s')
    record = createLogRecord('Test')
    record.extra = 'not a dict'
    result = formatter.format(record)
    assert result == 'Test'


runTest("formatter_extraNotDict_ignoresExtra", test_formatter_extraNotDict_ignoresExtra)


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
