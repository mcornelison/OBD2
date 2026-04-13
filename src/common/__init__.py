################################################################################
# File Name: __init__.py
# Purpose/Description: Common utilities package initialization
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
Common utilities package.

This package provides shared functionality used across the application:
- Configuration validation and loading
- Secrets management
- Logging configuration
- Error handling

Usage:
    from common.config.validator import ConfigValidator
    from common.config.secrets_loader import loadConfigWithSecrets
    from common.logging.setup import getLogger
    from common.errors.handler import RetryableError
"""

from .config.validator import ConfigValidator
from .errors.handler import ConfigurationError, DataError, RetryableError, handleError
from .logging.setup import getLogger, setupLogging
from .config.secrets_loader import loadConfigWithSecrets

__all__ = [
    'ConfigValidator',
    'loadConfigWithSecrets',
    'getLogger',
    'setupLogging',
    'RetryableError',
    'ConfigurationError',
    'DataError',
    'handleError'
]
