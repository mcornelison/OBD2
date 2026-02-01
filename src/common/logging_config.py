################################################################################
# File Name: logging_config.py
# Purpose/Description: Structured logging configuration and utilities
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
Logging configuration module.

Provides structured logging with:
- Configurable log levels
- Console and file output
- PII masking utilities
- Consistent formatting

Usage:
    from common.logging_config import setupLogging, getLogger

    setupLogging(level='INFO')
    logger = getLogger(__name__)
    logger.info("Operation completed", extra={"count": 42})
"""

import logging
import re
import sys
from pathlib import Path
from typing import Any

# Default log format
DEFAULT_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s | %(message)s'
DEFAULT_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# PII patterns for masking
PII_PATTERNS = {
    'email': re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
    'phone': re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),
    'ssn': re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
}


class PIIMaskingFilter(logging.Filter):
    """
    Logging filter that masks PII in log messages.

    Detects and masks:
    - Email addresses
    - Phone numbers
    - Social Security Numbers
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Filter and mask PII in log record.

        Args:
            record: Log record to filter

        Returns:
            True (always allows record, but modifies it)
        """
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            record.msg = self._maskPII(record.msg)

        return True

    def _maskPII(self, message: str) -> str:
        """
        Mask PII patterns in message.

        Args:
            message: Log message to mask

        Returns:
            Message with PII masked
        """
        for name, pattern in PII_PATTERNS.items():
            message = pattern.sub(f'[{name.upper()}_MASKED]', message)

        return message


class StructuredFormatter(logging.Formatter):
    """
    Custom formatter for structured logging.

    Adds support for extra fields in log output.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record with extra fields.

        Args:
            record: Log record to format

        Returns:
            Formatted log string
        """
        # Get base formatted message
        message = super().format(record)

        # Add extra fields if present
        extra = getattr(record, 'extra', None)
        if extra and isinstance(extra, dict):
            extraStr = ' | ' + ' '.join(f'{k}={v}' for k, v in extra.items())
            message += extraStr

        return message


def setupLogging(
    level: str = 'INFO',
    logFormat: str | None = None,
    logFile: str | None = None,
    enablePIIMasking: bool = True
) -> logging.Logger:
    """
    Configure application logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        logFormat: Custom format string
        logFile: Optional file path for log output
        enablePIIMasking: Whether to mask PII in logs

    Returns:
        Root logger instance
    """
    # Get root logger
    rootLogger = logging.getLogger()
    rootLogger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    rootLogger.handlers.clear()

    # Create formatter
    formatter = StructuredFormatter(
        fmt=logFormat or DEFAULT_FORMAT,
        datefmt=DEFAULT_DATE_FORMAT
    )

    # Console handler
    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(formatter)
    if enablePIIMasking:
        consoleHandler.addFilter(PIIMaskingFilter())
    rootLogger.addHandler(consoleHandler)

    # File handler (optional)
    if logFile:
        logPath = Path(logFile)
        logPath.parent.mkdir(parents=True, exist_ok=True)

        fileHandler = logging.FileHandler(logFile, encoding='utf-8')
        fileHandler.setFormatter(formatter)
        if enablePIIMasking:
            fileHandler.addFilter(PIIMaskingFilter())
        rootLogger.addHandler(fileHandler)

    rootLogger.info(f"Logging configured | level={level}")

    return rootLogger


def getLogger(name: str) -> logging.Logger:
    """
    Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def logWithContext(
    logger: logging.Logger,
    level: str,
    message: str,
    **context: Any
) -> None:
    """
    Log a message with structured context.

    Args:
        logger: Logger instance
        level: Log level
        message: Log message
        **context: Additional context fields
    """
    logFunc = getattr(logger, level.lower(), logger.info)

    if context:
        contextStr = ' | ' + ' '.join(f'{k}={v}' for k, v in context.items())
        logFunc(message + contextStr)
    else:
        logFunc(message)


class LogContext:
    """
    Context manager for adding context to all log messages.

    Usage:
        with LogContext(requestId='abc123'):
            logger.info("Processing request")  # Includes requestId
    """

    def __init__(self, **context: Any):
        """
        Initialize log context.

        Args:
            **context: Context fields to add to logs
        """
        self.context = context
        self._oldFactory = None

    def __enter__(self) -> 'LogContext':
        """Enter context and add fields to log records."""
        self._oldFactory = logging.getLogRecordFactory()

        context = self.context

        def recordFactory(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = self._oldFactory(*args, **kwargs)
            record.extra = context
            return record

        logging.setLogRecordFactory(recordFactory)
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit context and restore original factory."""
        if self._oldFactory:
            logging.setLogRecordFactory(self._oldFactory)
