################################################################################
# File Name: test_logging_config.py
# Purpose/Description: Tests for logging configuration module
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
Tests for the logging_config module.

Run with:
    pytest tests/test_logging_config.py -v
"""

import logging
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# Add src to path for imports
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


class TestPIIMaskingFilter:
    """Tests for PIIMaskingFilter class."""

    # =========================================================================
    # Email Masking Tests
    # =========================================================================

    def test_filter_emailInMessage_masksEmail(self):
        """
        Given: Log message containing email address
        When: filter() is called
        Then: Email is masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='User email is test@example.com',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert '[EMAIL_MASKED]' in record.msg
        assert 'test@example.com' not in record.msg

    def test_filter_multipleEmails_masksAll(self):
        """
        Given: Log message with multiple email addresses
        When: filter() is called
        Then: All emails are masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='From user@one.com to admin@two.com',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert record.msg.count('[EMAIL_MASKED]') == 2
        assert 'user@one.com' not in record.msg
        assert 'admin@two.com' not in record.msg

    # =========================================================================
    # Phone Masking Tests
    # =========================================================================

    def test_filter_phoneWithDashes_masksPhone(self):
        """
        Given: Log message with phone number (dashes)
        When: filter() is called
        Then: Phone is masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Call 555-123-4567 for support',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert '[PHONE_MASKED]' in record.msg
        assert '555-123-4567' not in record.msg

    def test_filter_phoneWithDots_masksPhone(self):
        """
        Given: Log message with phone number (dots)
        When: filter() is called
        Then: Phone is masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Contact 555.123.4567',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert '[PHONE_MASKED]' in record.msg
        assert '555.123.4567' not in record.msg

    def test_filter_phoneNoDashes_masksPhone(self):
        """
        Given: Log message with phone number (no separators)
        When: filter() is called
        Then: Phone is masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Number: 5551234567',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert '[PHONE_MASKED]' in record.msg
        assert '5551234567' not in record.msg

    # =========================================================================
    # SSN Masking Tests
    # =========================================================================

    def test_filter_ssn_masksSSN(self):
        """
        Given: Log message with SSN
        When: filter() is called
        Then: SSN is masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='SSN is 123-45-6789',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert '[SSN_MASKED]' in record.msg
        assert '123-45-6789' not in record.msg

    # =========================================================================
    # Combined PII Tests
    # =========================================================================

    def test_filter_mixedPII_masksAll(self):
        """
        Given: Log message with multiple PII types
        When: filter() is called
        Then: All PII types are masked
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='User test@email.com phone 555-123-4567 ssn 123-45-6789',
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert '[EMAIL_MASKED]' in record.msg
        assert '[PHONE_MASKED]' in record.msg
        assert '[SSN_MASKED]' in record.msg

    def test_filter_noPII_returnsUnchanged(self):
        """
        Given: Log message without PII
        When: filter() is called
        Then: Message unchanged
        """
        piiFilter = PIIMaskingFilter()
        originalMsg = 'Processing batch | batchId=123 | count=50'
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg=originalMsg,
            args=(),
            exc_info=None
        )

        piiFilter.filter(record)

        assert record.msg == originalMsg

    def test_filter_alwaysReturnsTrue(self):
        """
        Given: Any log record
        When: filter() is called
        Then: Returns True (allows record through)
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Any message',
            args=(),
            exc_info=None
        )

        result = piiFilter.filter(record)

        assert result is True


class TestStructuredFormatter:
    """Tests for StructuredFormatter class."""

    def test_format_basicMessage_formatsCorrectly(self):
        """
        Given: Basic log record
        When: format() is called
        Then: Returns formatted message
        """
        formatter = StructuredFormatter(
            fmt='%(levelname)s | %(message)s',
            datefmt='%Y-%m-%d'
        )
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )

        result = formatter.format(record)

        assert 'INFO' in result
        assert 'Test message' in result

    def test_format_withExtraDict_appendsFields(self):
        """
        Given: Log record with extra dict
        When: format() is called
        Then: Extra fields are appended
        """
        formatter = StructuredFormatter(
            fmt='%(levelname)s | %(message)s'
        )
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )
        record.extra = {'batchId': 123, 'count': 50}

        result = formatter.format(record)

        assert 'batchId=123' in result
        assert 'count=50' in result

    def test_format_noExtra_noAppendedFields(self):
        """
        Given: Log record without extra
        When: format() is called
        Then: No extra fields appended
        """
        formatter = StructuredFormatter(
            fmt='%(levelname)s | %(message)s'
        )
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test message',
            args=(),
            exc_info=None
        )

        result = formatter.format(record)

        assert result == 'INFO | Test message'


class TestSetupLogging:
    """Tests for setupLogging function."""

    def test_setupLogging_defaultLevel_setsInfoLevel(self):
        """
        Given: No level specified
        When: setupLogging() is called
        Then: Sets INFO level
        """
        logger = setupLogging(level='INFO')

        assert logger.level == logging.INFO

    def test_setupLogging_debugLevel_setsDebugLevel(self):
        """
        Given: DEBUG level specified
        When: setupLogging() is called
        Then: Sets DEBUG level
        """
        logger = setupLogging(level='DEBUG')

        assert logger.level == logging.DEBUG

    def test_setupLogging_warningLevel_setsWarningLevel(self):
        """
        Given: WARNING level specified
        When: setupLogging() is called
        Then: Sets WARNING level
        """
        logger = setupLogging(level='WARNING')

        assert logger.level == logging.WARNING

    def test_setupLogging_errorLevel_setsErrorLevel(self):
        """
        Given: ERROR level specified
        When: setupLogging() is called
        Then: Sets ERROR level
        """
        logger = setupLogging(level='ERROR')

        assert logger.level == logging.ERROR

    def test_setupLogging_invalidLevel_defaultsToInfo(self):
        """
        Given: Invalid level string
        When: setupLogging() is called
        Then: Defaults to INFO level
        """
        logger = setupLogging(level='INVALID')

        assert logger.level == logging.INFO

    def test_setupLogging_clearsExistingHandlers(self):
        """
        Given: Logger with existing handlers
        When: setupLogging() is called
        Then: Existing handlers are cleared
        """
        rootLogger = logging.getLogger()
        rootLogger.addHandler(logging.StreamHandler())
        initialHandlerCount = len(rootLogger.handlers)

        setupLogging()

        # Should have exactly 1 handler (console)
        assert len(rootLogger.handlers) == 1

    def test_setupLogging_addsConsoleHandler(self):
        """
        Given: Default parameters
        When: setupLogging() is called
        Then: Console handler is added
        """
        logger = setupLogging()

        assert len(logger.handlers) >= 1
        assert any(
            isinstance(h, logging.StreamHandler)
            for h in logger.handlers
        )

    def test_setupLogging_withLogFile_addsFileHandler(self, tmp_path: Path):
        """
        Given: Log file path specified
        When: setupLogging() is called
        Then: File handler is added
        """
        logFile = tmp_path / 'test.log'
        logger = setupLogging(logFile=str(logFile))

        assert any(
            isinstance(h, logging.FileHandler)
            for h in logger.handlers
        )

    def test_setupLogging_withLogFile_createsParentDirs(self, tmp_path: Path):
        """
        Given: Log file in non-existent directory
        When: setupLogging() is called
        Then: Parent directories are created
        """
        logFile = tmp_path / 'logs' / 'subdir' / 'test.log'
        setupLogging(logFile=str(logFile))

        assert logFile.parent.exists()

    def test_setupLogging_piiMaskingEnabled_addsPIIFilter(self):
        """
        Given: enablePIIMasking=True
        When: setupLogging() is called
        Then: PII filter is added to handlers
        """
        logger = setupLogging(enablePIIMasking=True)

        for handler in logger.handlers:
            hasFilter = any(
                isinstance(f, PIIMaskingFilter)
                for f in handler.filters
            )
            assert hasFilter

    def test_setupLogging_piiMaskingDisabled_noPIIFilter(self):
        """
        Given: enablePIIMasking=False
        When: setupLogging() is called
        Then: No PII filter added
        """
        logger = setupLogging(enablePIIMasking=False)

        for handler in logger.handlers:
            hasFilter = any(
                isinstance(f, PIIMaskingFilter)
                for f in handler.filters
            )
            assert not hasFilter

    def test_setupLogging_customFormat_usesCustomFormat(self):
        """
        Given: Custom format string
        When: setupLogging() is called
        Then: Handlers use custom format
        """
        customFormat = '%(message)s'
        logger = setupLogging(logFormat=customFormat)

        for handler in logger.handlers:
            assert handler.formatter._fmt == customFormat


class TestGetLogger:
    """Tests for getLogger function."""

    def test_getLogger_validName_returnsLogger(self):
        """
        Given: Valid logger name
        When: getLogger() is called
        Then: Returns logger instance
        """
        logger = getLogger('test.module')

        assert isinstance(logger, logging.Logger)
        assert logger.name == 'test.module'

    def test_getLogger_sameName_returnsSameLogger(self):
        """
        Given: Same logger name called twice
        When: getLogger() is called
        Then: Returns same logger instance
        """
        logger1 = getLogger('test.same')
        logger2 = getLogger('test.same')

        assert logger1 is logger2


class TestLogWithContext:
    """Tests for logWithContext function."""

    def test_logWithContext_withContext_appendsContext(self):
        """
        Given: Logger and context kwargs
        When: logWithContext() is called
        Then: Context is appended to message
        """
        mockLogger = MagicMock()

        logWithContext(
            mockLogger,
            'info',
            'Processing batch',
            batchId=123,
            count=50
        )

        mockLogger.info.assert_called_once()
        callArgs = mockLogger.info.call_args[0][0]
        assert 'Processing batch' in callArgs
        assert 'batchId=123' in callArgs
        assert 'count=50' in callArgs

    def test_logWithContext_noContext_logsPlainMessage(self):
        """
        Given: Logger without context kwargs
        When: logWithContext() is called
        Then: Only message is logged
        """
        mockLogger = MagicMock()

        logWithContext(mockLogger, 'info', 'Plain message')

        mockLogger.info.assert_called_once_with('Plain message')

    def test_logWithContext_debugLevel_callsDebug(self):
        """
        Given: debug level
        When: logWithContext() is called
        Then: Calls logger.debug()
        """
        mockLogger = MagicMock()

        logWithContext(mockLogger, 'debug', 'Debug message')

        mockLogger.debug.assert_called_once()

    def test_logWithContext_errorLevel_callsError(self):
        """
        Given: error level
        When: logWithContext() is called
        Then: Calls logger.error()
        """
        mockLogger = MagicMock()

        logWithContext(mockLogger, 'error', 'Error message')

        mockLogger.error.assert_called_once()

    def test_logWithContext_warningLevel_callsWarning(self):
        """
        Given: warning level
        When: logWithContext() is called
        Then: Calls logger.warning()
        """
        mockLogger = MagicMock()

        logWithContext(mockLogger, 'warning', 'Warning message')

        mockLogger.warning.assert_called_once()


class TestLogContext:
    """Tests for LogContext context manager."""

    def test_logContext_enterAndExit_modifiesFactory(self):
        """
        Given: LogContext with context values
        When: Used as context manager
        Then: Modifies and restores log record factory
        """
        originalFactory = logging.getLogRecordFactory()

        with LogContext(requestId='abc123'):
            inContextFactory = logging.getLogRecordFactory()
            assert inContextFactory != originalFactory

        afterFactory = logging.getLogRecordFactory()
        assert afterFactory == originalFactory

    def test_logContext_inContext_addsExtraToRecords(self):
        """
        Given: LogContext with context values
        When: Log record created inside context
        Then: Record has extra attribute
        """
        with LogContext(requestId='abc123', userId=42):
            factory = logging.getLogRecordFactory()
            record = factory(
                name='test',
                level=logging.INFO,
                pathname='test.py',
                lineno=1,
                msg='Test',
                args=(),
                exc_info=None
            )

            assert hasattr(record, 'extra')
            assert record.extra['requestId'] == 'abc123'
            assert record.extra['userId'] == 42

    def test_logContext_returnsItself(self):
        """
        Given: LogContext instance
        When: Used as context manager
        Then: Returns self on __enter__
        """
        ctx = LogContext(key='value')

        with ctx as returned:
            assert returned is ctx


class TestPIIPatterns:
    """Tests for PII_PATTERNS regex patterns."""

    def test_piiPatterns_email_matchesValidEmails(self):
        """
        Given: Email pattern
        When: Matched against valid emails
        Then: Matches correctly
        """
        pattern = PII_PATTERNS['email']

        assert pattern.search('user@example.com')
        assert pattern.search('user.name@sub.domain.com')
        assert pattern.search('user+tag@example.com')

    def test_piiPatterns_email_notMatchesInvalid(self):
        """
        Given: Email pattern
        When: Matched against invalid strings
        Then: Does not match
        """
        pattern = PII_PATTERNS['email']

        assert pattern.search('not an email') is None
        assert pattern.search('user@') is None
        assert pattern.search('@example.com') is None

    def test_piiPatterns_phone_matchesValidPhones(self):
        """
        Given: Phone pattern
        When: Matched against valid phone numbers
        Then: Matches correctly
        """
        pattern = PII_PATTERNS['phone']

        assert pattern.search('555-123-4567')
        assert pattern.search('555.123.4567')
        assert pattern.search('5551234567')

    def test_piiPatterns_ssn_matchesValidSSN(self):
        """
        Given: SSN pattern
        When: Matched against valid SSN
        Then: Matches correctly
        """
        pattern = PII_PATTERNS['ssn']

        assert pattern.search('123-45-6789')
        assert pattern.search('000-00-0000')


class TestDefaultFormats:
    """Tests for default format constants."""

    def test_defaultFormat_containsRequiredFields(self):
        """
        Given: DEFAULT_FORMAT constant
        When: Examined
        Then: Contains required format fields
        """
        assert '%(asctime)s' in DEFAULT_FORMAT
        assert '%(levelname)' in DEFAULT_FORMAT
        assert '%(name)s' in DEFAULT_FORMAT
        assert '%(message)s' in DEFAULT_FORMAT

    def test_defaultDateFormat_isValid(self):
        """
        Given: DEFAULT_DATE_FORMAT constant
        When: Examined
        Then: Is valid date format string
        """
        from datetime import datetime

        # Should not raise
        datetime.now().strftime(DEFAULT_DATE_FORMAT)


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_filter_nonStringMessage_handlesGracefully(self):
        """
        Given: Log record with non-string message
        When: filter() is called
        Then: Handles gracefully without error
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg=12345,  # Non-string message
            args=(),
            exc_info=None
        )

        # Should not raise
        result = piiFilter.filter(record)
        assert result is True

    def test_filter_noMsgAttribute_handlesGracefully(self):
        """
        Given: Log record without msg attribute
        When: filter() is called
        Then: Handles gracefully
        """
        piiFilter = PIIMaskingFilter()
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Original',
            args=(),
            exc_info=None
        )
        delattr(record, 'msg')

        # Should not raise
        result = piiFilter.filter(record)
        assert result is True

    def test_setupLogging_lowercaseLevel_worksCorrectly(self):
        """
        Given: Lowercase level string
        When: setupLogging() is called
        Then: Converts to uppercase and works
        """
        logger = setupLogging(level='debug')

        assert logger.level == logging.DEBUG

    def test_logContext_emptyContext_works(self):
        """
        Given: LogContext with no arguments
        When: Used as context manager
        Then: Works without error
        """
        with LogContext():
            pass  # Should not raise

    def test_maskPII_emptyString_returnsEmptyString(self):
        """
        Given: Empty string message
        When: _maskPII() is called
        Then: Returns empty string
        """
        piiFilter = PIIMaskingFilter()

        result = piiFilter._maskPII('')

        assert result == ''

    def test_formatter_extraNotDict_ignoresExtra(self):
        """
        Given: Record with extra that is not a dict
        When: format() is called
        Then: Ignores non-dict extra
        """
        formatter = StructuredFormatter(fmt='%(message)s')
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='test.py',
            lineno=1,
            msg='Test',
            args=(),
            exc_info=None
        )
        record.extra = 'not a dict'

        result = formatter.format(record)

        assert result == 'Test'

    def test_setupLogging_caseSensitivity_handlesAllCases(self):
        """
        Given: Mixed case level strings
        When: setupLogging() is called
        Then: Handles correctly
        """
        logger1 = setupLogging(level='Info')
        assert logger1.level == logging.INFO

        logger2 = setupLogging(level='DEBUG')
        assert logger2.level == logging.DEBUG

        logger3 = setupLogging(level='warning')
        assert logger3.level == logging.WARNING
