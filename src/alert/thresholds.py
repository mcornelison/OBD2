################################################################################
# File Name: thresholds.py
# Purpose/Description: Threshold checking logic for alert management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial implementation for US-011
# ================================================================================
################################################################################
"""
Threshold checking logic for alert management.

Provides functions for threshold conversion and checking without
requiring a full AlertManager instance.
"""

import logging
from typing import Any, Dict, List, Optional

from .types import (
    AlertDirection,
    AlertThreshold,
    ALERT_TYPE_OIL_PRESSURE_LOW,
    ALERT_TYPE_RPM_REDLINE,
    ALERT_PRIORITIES,
    PARAMETER_ALERT_TYPES,
    THRESHOLD_KEY_TO_PARAMETER,
)

logger = logging.getLogger(__name__)


def convertThresholds(thresholds: Dict[str, float]) -> List[AlertThreshold]:
    """
    Convert threshold config dict to AlertThreshold objects.

    Args:
        thresholds: Threshold config dictionary with keys like 'rpmRedline'

    Returns:
        List of AlertThreshold objects
    """
    result = []

    for key, value in thresholds.items():
        if key not in THRESHOLD_KEY_TO_PARAMETER:
            logger.warning(f"Unknown threshold key: {key}")
            continue

        parameterName = THRESHOLD_KEY_TO_PARAMETER[key]
        alertType = PARAMETER_ALERT_TYPES.get(parameterName, key)
        priority = ALERT_PRIORITIES.get(alertType, 3)

        # Determine direction based on threshold type
        if key in ('oilPressureLow',):
            direction = AlertDirection.BELOW
        else:
            direction = AlertDirection.ABOVE

        # Create message
        if key == 'rpmRedline':
            message = f"RPM REDLINE! ({value})"
        elif key == 'coolantTempCritical':
            message = f"COOLANT CRITICAL! ({value}C)"
        elif key == 'boostPressureMax':
            message = f"MAX BOOST! ({value} psi)"
        elif key == 'oilPressureLow':
            message = f"LOW OIL PRESSURE! (<{value} psi)"
        else:
            message = f"{parameterName} alert ({value})"

        threshold = AlertThreshold(
            parameterName=parameterName,
            alertType=alertType,
            threshold=value,
            direction=direction,
            priority=priority,
            message=message,
        )
        result.append(threshold)

    return result


def checkThresholdValue(
    parameterName: str,
    value: float,
    thresholds: Dict[str, float]
) -> Optional[str]:
    """
    Check a single value against thresholds without AlertManager.

    Args:
        parameterName: Parameter name (e.g., 'RPM')
        value: Value to check
        thresholds: Threshold dictionary with keys like 'rpmRedline'

    Returns:
        Alert type string if threshold exceeded, None otherwise
    """
    # Map parameter name to threshold key
    paramToKey = {
        'RPM': 'rpmRedline',
        'COOLANT_TEMP': 'coolantTempCritical',
        'INTAKE_PRESSURE': 'boostPressureMax',
        'BOOST_PRESSURE': 'boostPressureMax',
        'OIL_PRESSURE': 'oilPressureLow',
    }

    thresholdKey = paramToKey.get(parameterName)
    if not thresholdKey or thresholdKey not in thresholds:
        return None

    threshold = thresholds[thresholdKey]

    # Oil pressure is "below" threshold, others are "above"
    if thresholdKey == 'oilPressureLow':
        if value < threshold:
            return ALERT_TYPE_OIL_PRESSURE_LOW
    else:
        if value > threshold:
            return PARAMETER_ALERT_TYPES.get(parameterName)

    return None


def getDefaultThresholds() -> Dict[str, float]:
    """
    Get default threshold values.

    Returns:
        Dictionary of default thresholds
    """
    return {
        'rpmRedline': 6500,
        'coolantTempCritical': 110,
        'boostPressureMax': 18,
        'oilPressureLow': 20,
    }


def validateThresholds(thresholds: Dict[str, float]) -> List[str]:
    """
    Validate threshold configuration.

    Args:
        thresholds: Threshold dictionary to validate

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    for key, value in thresholds.items():
        if key not in THRESHOLD_KEY_TO_PARAMETER:
            errors.append(f"Unknown threshold key: {key}")
            continue

        if not isinstance(value, (int, float)):
            errors.append(f"Invalid value for {key}: must be numeric")
            continue

        if value < 0:
            errors.append(f"Invalid value for {key}: must be non-negative")

    return errors
