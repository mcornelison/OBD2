################################################################################
# File Name: __init__.py
# Purpose/Description: Config subpackage for configuration loading and management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | Add types, exceptions, parameters exports (US-002)
# ================================================================================
################################################################################
"""
Config Subpackage.

This subpackage contains configuration components:
- OBD configuration loading and validation
- Parameter type definitions
- Parameter lookup helpers
- Simulator configuration helpers

Usage:
    from src.obd.config import ParameterInfo, ObdConfigError
    from src.obd.config import STATIC_PARAMETERS, REALTIME_PARAMETERS
"""

# Types
from .types import (
    ParameterInfo,
    PARAMETER_CATEGORIES,
    CATEGORY_IDENTIFICATION,
    CATEGORY_FUEL,
    CATEGORY_SYSTEM,
    CATEGORY_DIAGNOSTICS,
    CATEGORY_ENGINE,
    CATEGORY_TEMPERATURE,
    CATEGORY_PRESSURE,
    CATEGORY_AIRFUEL,
    CATEGORY_OXYGEN,
    CATEGORY_TIMING,
    CATEGORY_EGR,
    CATEGORY_EVAP,
    CATEGORY_DISTANCE,
    CATEGORY_TIME,
    CATEGORY_ELECTRICAL,
)

# Exceptions
from .exceptions import ObdConfigError

# Parameters
from .parameters import (
    STATIC_PARAMETERS,
    REALTIME_PARAMETERS,
    ALL_PARAMETERS,
)

__all__ = [
    # Types
    'ParameterInfo',
    'PARAMETER_CATEGORIES',
    'CATEGORY_IDENTIFICATION',
    'CATEGORY_FUEL',
    'CATEGORY_SYSTEM',
    'CATEGORY_DIAGNOSTICS',
    'CATEGORY_ENGINE',
    'CATEGORY_TEMPERATURE',
    'CATEGORY_PRESSURE',
    'CATEGORY_AIRFUEL',
    'CATEGORY_OXYGEN',
    'CATEGORY_TIMING',
    'CATEGORY_EGR',
    'CATEGORY_EVAP',
    'CATEGORY_DISTANCE',
    'CATEGORY_TIME',
    'CATEGORY_ELECTRICAL',
    # Exceptions
    'ObdConfigError',
    # Parameters
    'STATIC_PARAMETERS',
    'REALTIME_PARAMETERS',
    'ALL_PARAMETERS',
]
