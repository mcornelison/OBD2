################################################################################
# File Name: __init__.py
# Purpose/Description: Data subpackage for data logging and management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added exports for US-007 (data module refactor)
# ================================================================================
################################################################################
"""
Data Subpackage.

This subpackage contains data logging components:
- OBD data logger
- Realtime data logger
- Logging state and statistics
- Helper functions for data operations

Usage:
    from src.obd.data import (
        # Types
        LoggingState,
        LoggedReading,
        LoggingStats,
        # Exceptions
        DataLoggerError,
        ParameterNotSupportedError,
        ParameterReadError,
        # Classes
        ObdDataLogger,
        RealtimeDataLogger,
        # Helper functions
        queryParameter,
        logReading,
        verifyDataPersistence,
        createDataLoggerFromConfig,
        createRealtimeLoggerFromConfig,
    )
"""

# Types
from .types import (
    LoggingState,
    LoggedReading,
    LoggingStats,
)

# Exceptions
from .exceptions import (
    DataLoggerError,
    ParameterNotSupportedError,
    ParameterReadError,
)

# Classes
from .logger import ObdDataLogger
from .realtime import RealtimeDataLogger

# Helper functions
from .helpers import (
    queryParameter,
    logReading,
    verifyDataPersistence,
    createDataLoggerFromConfig,
    createRealtimeLoggerFromConfig,
)

__all__: list[str] = [
    # Types
    'LoggingState',
    'LoggedReading',
    'LoggingStats',
    # Exceptions
    'DataLoggerError',
    'ParameterNotSupportedError',
    'ParameterReadError',
    # Classes
    'ObdDataLogger',
    'RealtimeDataLogger',
    # Helper functions
    'queryParameter',
    'logReading',
    'verifyDataPersistence',
    'createDataLoggerFromConfig',
    'createRealtimeLoggerFromConfig',
]
