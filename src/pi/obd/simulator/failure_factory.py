################################################################################
# File Name: failure_factory.py
# Purpose/Description: Factory helpers for building FailureInjector from config
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-038
# 2026-04-14    | Sweep 5       | Extracted from failure_injector.py (task 4 split)
# ================================================================================
################################################################################

"""
Factory functions for constructing FailureInjector instances from application config.
"""

import logging
from typing import Any

from .failure_injector import FailureInjector
from .failure_types import (
    DEFAULT_INTERMITTENT_PROBABILITY,
    DEFAULT_OUT_OF_RANGE_FACTOR,
    FailureConfig,
    FailureType,
)

logger = logging.getLogger(__name__)


def createFailureInjectorFromConfig(
    config: dict[str, Any]
) -> FailureInjector:
    """
    Create a FailureInjector from configuration.

    Config may contain a 'pi.simulator.failures' section with pre-configured
    failures to inject on startup.

    Args:
        config: Configuration dictionary

    Returns:
        Configured FailureInjector instance

    Example:
        config = {
            "pi": {
                "simulator": {
                    "failures": {
                        "connectionDrop": False,
                        "sensorFailure": {
                            "enabled": True,
                            "sensors": ["COOLANT_TEMP"]
                        }
                    }
                }
            }
        }
        injector = createFailureInjectorFromConfig(config)
    """
    injector = FailureInjector()

    # Get failures config
    failuresConfig = config.get("pi", {}).get("simulator", {}).get("failures", {})

    # Process each failure type
    for failureTypeStr, failureData in failuresConfig.items():
        failureType = FailureType.fromString(failureTypeStr)
        if failureType is None:
            logger.warning(f"Unknown failure type in config: {failureTypeStr}")
            continue

        # Handle boolean or dict config
        if isinstance(failureData, bool):
            if failureData:
                injector.injectFailure(failureType)
        elif isinstance(failureData, dict):
            enabled = failureData.get("enabled", True)
            if enabled:
                failureConfig = FailureConfig(
                    sensorNames=failureData.get("sensors", []),
                    probability=failureData.get(
                        "probability",
                        DEFAULT_INTERMITTENT_PROBABILITY,
                    ),
                    outOfRangeFactor=failureData.get(
                        "outOfRangeFactor",
                        DEFAULT_OUT_OF_RANGE_FACTOR,
                    ),
                    outOfRangeDirection=failureData.get(
                        "outOfRangeDirection",
                        "random",
                    ),
                    dtcCodes=failureData.get("dtcCodes", []),
                    affectsAllSensors=failureData.get("affectsAllSensors", False),
                )
                injector.injectFailure(failureType, failureConfig)

    return injector


def getDefaultFailureInjector() -> FailureInjector:
    """
    Get a default FailureInjector ready for use.

    Returns:
        FailureInjector with no active failures
    """
    return FailureInjector()
