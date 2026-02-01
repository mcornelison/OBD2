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
# 2026-01-22    | Ralph Agent  | Add loader, helpers, simulator exports (US-003)
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
    from src.obd.config import loadObdConfig, OBD_DEFAULTS
    from src.obd.config import getParameterInfo, isSimulatorEnabled
"""

# Types
# Exceptions
from .exceptions import ObdConfigError

# Helpers - Parameter lookup functions
from .helpers import (
    getActiveProfile,
    getAllParameterNames,
    getCategories,
    # Config section access functions
    getConfigSection,
    getDefaultRealtimeConfig,
    getDefaultStaticConfig,
    getLoggedParameters,
    getParameterInfo,
    getParametersByCategory,
    getPollingInterval,
    getRealtimeParameterNames,
    getRealtimeParameters,
    getStaticParameterNames,
    getStaticParameters,
    isRealtimeParameter,
    isStaticParameter,
    isValidParameter,
    shouldQueryStaticOnFirstConnection,
)

# Loader
from .loader import (
    OBD_DEFAULTS,
    OBD_REQUIRED_FIELDS,
    VALID_DISPLAY_MODES,
    loadObdConfig,
    validateObdConfig,
)

# Parameters
from .parameters import (
    ALL_PARAMETERS,
    REALTIME_PARAMETERS,
    STATIC_PARAMETERS,
)

# Simulator
from .simulator import (
    getSimulatorConfig,
    getSimulatorConnectionDelay,
    getSimulatorFailures,
    getSimulatorProfilePath,
    getSimulatorScenarioPath,
    getSimulatorUpdateInterval,
    isSimulatorEnabled,
)
from .types import (
    CATEGORY_AIRFUEL,
    CATEGORY_DIAGNOSTICS,
    CATEGORY_DISTANCE,
    CATEGORY_EGR,
    CATEGORY_ELECTRICAL,
    CATEGORY_ENGINE,
    CATEGORY_EVAP,
    CATEGORY_FUEL,
    CATEGORY_IDENTIFICATION,
    CATEGORY_OXYGEN,
    CATEGORY_PRESSURE,
    CATEGORY_SYSTEM,
    CATEGORY_TEMPERATURE,
    CATEGORY_TIME,
    CATEGORY_TIMING,
    PARAMETER_CATEGORIES,
    ParameterInfo,
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
    # Loader
    'loadObdConfig',
    'validateObdConfig',
    'OBD_DEFAULTS',
    'OBD_REQUIRED_FIELDS',
    'VALID_DISPLAY_MODES',
    # Helpers - Parameter lookup
    'getParameterInfo',
    'getAllParameterNames',
    'getStaticParameterNames',
    'getRealtimeParameterNames',
    'isValidParameter',
    'isStaticParameter',
    'isRealtimeParameter',
    'getParametersByCategory',
    'getCategories',
    'getDefaultRealtimeConfig',
    'getDefaultStaticConfig',
    # Helpers - Config section access
    'getConfigSection',
    'getActiveProfile',
    'getLoggedParameters',
    'getStaticParameters',
    'getRealtimeParameters',
    'getPollingInterval',
    'shouldQueryStaticOnFirstConnection',
    # Simulator
    'getSimulatorConfig',
    'isSimulatorEnabled',
    'getSimulatorProfilePath',
    'getSimulatorScenarioPath',
    'getSimulatorConnectionDelay',
    'getSimulatorUpdateInterval',
    'getSimulatorFailures',
]
