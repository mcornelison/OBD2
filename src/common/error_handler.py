################################################################################
# File Name: error_handler.py
# Purpose/Description: Centralized error handling with classification and retry
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
Error handling module.

Provides centralized error handling with:
- Custom exception classes by error type
- Error classification (retryable, config, data, system)
- Retry decorator with exponential backoff
- Structured error reporting

Usage:
    from common.error_handler import RetryableError, retry, handleError

    @retry(maxRetries=3)
    def fetchData():
        # Code that might fail transiently
        pass

    try:
        result = operation()
    except Exception as e:
        handleError(e)
"""

import functools
import logging
import time
import traceback
from collections.abc import Callable
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar('T')


class ErrorCategory(Enum):
    """Categories of errors for classification."""
    RETRYABLE = 'retryable'       # Transient, should retry
    AUTHENTICATION = 'auth'       # Auth failures, refresh and retry
    CONFIGURATION = 'config'      # Config errors, fail fast
    DATA = 'data'                 # Data validation, log and skip
    SYSTEM = 'system'             # Unexpected errors


# ================================================================================
# Custom Exception Classes
# ================================================================================

class BaseError(Exception):
    """Base exception for all custom errors."""

    category: ErrorCategory = ErrorCategory.SYSTEM

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def toDict(self) -> dict[str, Any]:
        """Convert error to dictionary for logging/serialization."""
        return {
            'type': self.__class__.__name__,
            'category': self.category.value,
            'message': self.message,
            'details': self.details
        }


class RetryableError(BaseError):
    """Error that should be retried (network timeout, rate limit, etc.)."""
    category = ErrorCategory.RETRYABLE


class AuthenticationError(BaseError):
    """Authentication/authorization failure."""
    category = ErrorCategory.AUTHENTICATION


class ConfigurationError(BaseError):
    """Configuration validation failure."""
    category = ErrorCategory.CONFIGURATION


class DataError(BaseError):
    """Data validation or processing error."""
    category = ErrorCategory.DATA


class SystemError(BaseError):
    """Unexpected system error."""
    category = ErrorCategory.SYSTEM


# ================================================================================
# Error Classification
# ================================================================================

def classifyError(error: Exception) -> ErrorCategory:
    """
    Classify an error into a category.

    Args:
        error: Exception to classify

    Returns:
        ErrorCategory for the error
    """
    # Check if it's already a custom error
    if isinstance(error, BaseError):
        return error.category

    errorType = type(error).__name__
    errorMessage = str(error).lower()

    # Network/transient errors
    if any(term in errorType.lower() for term in ['timeout', 'connection', 'network']):
        return ErrorCategory.RETRYABLE

    # Rate limiting
    if 'rate limit' in errorMessage or '429' in errorMessage:
        return ErrorCategory.RETRYABLE

    # Authentication
    if any(term in errorMessage for term in ['auth', '401', '403', 'unauthorized', 'forbidden']):
        return ErrorCategory.AUTHENTICATION

    # Configuration
    if any(term in errorMessage for term in ['config', 'missing', 'required']):
        return ErrorCategory.CONFIGURATION

    # Data validation
    if any(term in errorMessage for term in ['validation', 'invalid', 'parse']):
        return ErrorCategory.DATA

    return ErrorCategory.SYSTEM


# ================================================================================
# Retry Decorator
# ================================================================================

def retry(
    maxRetries: int = 3,
    initialDelay: float = 1.0,
    backoffMultiplier: float = 2.0,
    retryableExceptions: list[type[Exception]] | None = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that retries a function with exponential backoff.

    Args:
        maxRetries: Maximum number of retry attempts
        initialDelay: Initial delay in seconds
        backoffMultiplier: Multiplier for each retry
        retryableExceptions: Exception types to retry (default: RetryableError)

    Returns:
        Decorated function

    Example:
        @retry(maxRetries=3, initialDelay=1.0)
        def fetchFromApi():
            return requests.get(url)
    """
    if retryableExceptions is None:
        retryableExceptions = [RetryableError]

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            lastError: Exception | None = None
            delay = initialDelay

            for attempt in range(maxRetries + 1):
                try:
                    return func(*args, **kwargs)

                except tuple(retryableExceptions) as e:
                    lastError = e
                    if attempt < maxRetries:
                        logger.warning(
                            f"Retry {attempt + 1}/{maxRetries} for {func.__name__} "
                            f"after {delay}s | error={e}"
                        )
                        time.sleep(delay)
                        delay *= backoffMultiplier
                    else:
                        logger.error(
                            f"Max retries ({maxRetries}) exceeded for {func.__name__}"
                        )

                except Exception as e:
                    # Non-retryable exception, re-raise immediately
                    logger.error(f"Non-retryable error in {func.__name__}: {e}")
                    raise

            # All retries exhausted
            if lastError:
                raise lastError
            raise RuntimeError(f"Unexpected state in retry for {func.__name__}")

        return wrapper
    return decorator


# ================================================================================
# Error Handling
# ================================================================================

def handleError(
    error: Exception,
    context: dict[str, Any] | None = None,
    reraise: bool = True
) -> dict[str, Any]:
    """
    Handle an error with logging and classification.

    Args:
        error: Exception that occurred
        context: Additional context information
        reraise: Whether to re-raise the exception

    Returns:
        Error details dictionary

    Raises:
        The original exception if reraise is True
    """
    category = classifyError(error)
    context = context or {}

    errorDetails = {
        'type': type(error).__name__,
        'category': category.value,
        'message': str(error),
        'context': context,
        'traceback': traceback.format_exc()
    }

    # Log based on category
    if category == ErrorCategory.CONFIGURATION:
        logger.error(f"Configuration error: {error}")
    elif category == ErrorCategory.DATA:
        logger.warning(f"Data error: {error}")
    elif category == ErrorCategory.RETRYABLE:
        logger.warning(f"Retryable error: {error}")
    else:
        logger.error(f"Error: {error}", exc_info=True)

    if reraise:
        raise error

    return errorDetails


def formatError(error: Exception) -> str:
    """
    Format an error for display/logging.

    Args:
        error: Exception to format

    Returns:
        Formatted error string
    """
    category = classifyError(error)

    if isinstance(error, BaseError):
        details = f" | details={error.details}" if error.details else ""
        return f"[{category.value.upper()}] {error.message}{details}"

    return f"[{category.value.upper()}] {type(error).__name__}: {error}"


class ErrorCollector:
    """
    Collects multiple errors during batch processing.

    Useful when you want to continue processing and report all errors at the end.

    Example:
        collector = ErrorCollector()
        for item in items:
            try:
                process(item)
            except Exception as e:
                collector.add(e, item=item)

        if collector.hasErrors():
            collector.report()
    """

    def __init__(self):
        self.errors: list[dict[str, Any]] = []

    def add(self, error: Exception, **context: Any) -> None:
        """Add an error to the collection."""
        self.errors.append({
            'error': error,
            'category': classifyError(error).value,
            'message': str(error),
            'context': context
        })

    def hasErrors(self) -> bool:
        """Check if any errors were collected."""
        return len(self.errors) > 0

    def count(self) -> int:
        """Get number of collected errors."""
        return len(self.errors)

    def report(self) -> None:
        """Log all collected errors."""
        if not self.errors:
            return

        logger.error(f"Collected {len(self.errors)} errors:")
        for i, err in enumerate(self.errors, 1):
            logger.error(f"  {i}. [{err['category']}] {err['message']}")

    def clear(self) -> None:
        """Clear all collected errors."""
        self.errors.clear()
