################################################################################
# File Name: __init__.py
# Purpose/Description: Display subpackage for display drivers and management
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-01-22    | Ralph Agent  | US-005: Added driver exports
# ================================================================================
################################################################################
"""
Display Subpackage.

This subpackage contains display components:
- Display drivers (headless, minimal, developer)
- Display manager
- Adafruit hardware adapters
- Display types and exceptions
"""

from .types import (
    DisplayMode,
    StatusInfo,
    AlertInfo,
)
from .exceptions import (
    DisplayError,
    DisplayInitializationError,
    DisplayOutputError,
)
from .drivers import (
    BaseDisplayDriver,
    HeadlessDisplayDriver,
    MinimalDisplayDriver,
    DeveloperDisplayDriver,
    NullDisplayAdapter,
)

__all__: list[str] = [
    # Types
    'DisplayMode',
    'StatusInfo',
    'AlertInfo',
    # Exceptions
    'DisplayError',
    'DisplayInitializationError',
    'DisplayOutputError',
    # Drivers
    'BaseDisplayDriver',
    'HeadlessDisplayDriver',
    'MinimalDisplayDriver',
    'DeveloperDisplayDriver',
    'NullDisplayAdapter',
]
