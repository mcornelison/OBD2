################################################################################
# File Name: __init__.py
# Purpose/Description: Alert subpackage for threshold monitoring and alerting
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Added all exports (US-011)
# ================================================================================
################################################################################
"""
Alert Subpackage.

This subpackage contains alert management components:
- Alert thresholds and configuration
- Alert state tracking
- Alert event generation and handling

Usage:
    from alert import AlertManager, createAlertManagerFromConfig

    # Create from config
    manager = createAlertManagerFromConfig(config, database, displayManager)
    manager.start()

    # Check value against thresholds
    manager.checkValue('RPM', 7500)
"""

# Types - enums and dataclasses
# Exceptions
from .exceptions import (
    AlertConfigurationError,
    AlertDatabaseError,
    AlertError,
)

# Helper functions
from .helpers import (
    createAlertManagerFromConfig,
    getAlertConfig,
    getAlertThresholdsForProfile,
    getDefaultAlertConfig,
    isAlertingEnabled,
    validateAlertConfig,
)

# Manager class
from .manager import AlertManager

# Threshold checking
from .thresholds import (
    checkThresholdValue,
    convertThresholds,
    getDefaultThresholds,
    validateThresholds,
)
from .types import (
    # Constants
    ALERT_PRIORITIES,
    ALERT_TYPE_BOOST_PRESSURE_MAX,
    ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    ALERT_TYPE_OIL_PRESSURE_LOW,
    ALERT_TYPE_RPM_REDLINE,
    DEFAULT_COOLDOWN_SECONDS,
    MIN_COOLDOWN_SECONDS,
    PARAMETER_ALERT_TYPES,
    THRESHOLD_KEY_TO_PARAMETER,
    AlertDirection,
    AlertEvent,
    AlertState,
    AlertStats,
    AlertThreshold,
)

__all__ = [
    # Types - enums
    'AlertDirection',
    'AlertState',
    # Types - dataclasses
    'AlertThreshold',
    'AlertEvent',
    'AlertStats',
    # Types - constants
    'DEFAULT_COOLDOWN_SECONDS',
    'MIN_COOLDOWN_SECONDS',
    'ALERT_TYPE_RPM_REDLINE',
    'ALERT_TYPE_COOLANT_TEMP_CRITICAL',
    'ALERT_TYPE_BOOST_PRESSURE_MAX',
    'ALERT_TYPE_OIL_PRESSURE_LOW',
    'PARAMETER_ALERT_TYPES',
    'THRESHOLD_KEY_TO_PARAMETER',
    'ALERT_PRIORITIES',
    # Exceptions
    'AlertError',
    'AlertConfigurationError',
    'AlertDatabaseError',
    # Threshold functions
    'convertThresholds',
    'checkThresholdValue',
    'getDefaultThresholds',
    'validateThresholds',
    # Manager class
    'AlertManager',
    # Helper functions
    'createAlertManagerFromConfig',
    'getAlertThresholdsForProfile',
    'isAlertingEnabled',
    'getAlertConfig',
    'getDefaultAlertConfig',
    'validateAlertConfig',
]
