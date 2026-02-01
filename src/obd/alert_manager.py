################################################################################
# File Name: alert_manager.py
# Purpose/Description: Threshold-based alert system for OBD-II monitoring
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-017
# 2026-01-22    | Ralph Agent   | Refactored to use alert subpackage (US-011)
# ================================================================================
################################################################################
"""
Threshold-based alert system for OBD-II monitoring.

This module now re-exports from the alert subpackage for backward
compatibility. All functionality is implemented in the subpackage modules:
- alert.types: Enums, dataclasses, and constants
- alert.exceptions: Exception classes
- alert.thresholds: Threshold checking logic
- alert.manager: AlertManager class
- alert.helpers: Factory and config helpers

Usage:
    from obd.alert_manager import AlertManager, createAlertManagerFromConfig

    # Create from config
    manager = createAlertManagerFromConfig(config, database, displayManager)
    manager.start()

    # Check value against thresholds
    manager.checkValue('RPM', 7500)  # Triggers alert if above threshold

    # Shutdown
    manager.stop()
"""

# Re-export everything from the alert subpackage for backward compatibility
from alert import (
    ALERT_PRIORITIES,
    ALERT_TYPE_BOOST_PRESSURE_MAX,
    ALERT_TYPE_COOLANT_TEMP_CRITICAL,
    ALERT_TYPE_OIL_PRESSURE_LOW,
    ALERT_TYPE_RPM_REDLINE,
    # Types - constants
    DEFAULT_COOLDOWN_SECONDS,
    MIN_COOLDOWN_SECONDS,
    PARAMETER_ALERT_TYPES,
    THRESHOLD_KEY_TO_PARAMETER,
    AlertConfigurationError,
    AlertDatabaseError,
    # Types - enums
    AlertDirection,
    # Exceptions
    AlertError,
    AlertEvent,
    # Manager class
    AlertManager,
    AlertState,
    AlertStats,
    # Types - dataclasses
    AlertThreshold,
    # Threshold functions
    checkThresholdValue,
    # Helper functions
    createAlertManagerFromConfig,
    getAlertThresholdsForProfile,
    getDefaultThresholds,
    isAlertingEnabled,
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
    'checkThresholdValue',
    'getDefaultThresholds',
    # Manager class
    'AlertManager',
    # Helper functions
    'createAlertManagerFromConfig',
    'getAlertThresholdsForProfile',
    'isAlertingEnabled',
]
