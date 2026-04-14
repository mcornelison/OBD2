################################################################################
# File Name: __init__.py
# Purpose/Description: Display drivers subpackage for display output implementations
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-005)
# ================================================================================
################################################################################
"""
Display Drivers Subpackage.

This subpackage contains display driver implementations:
- BaseDisplayDriver: Abstract base class for all drivers
- HeadlessDisplayDriver: No display output, logs only
- MinimalDisplayDriver: Adafruit 1.3" 240x240 TFT display
- DeveloperDisplayDriver: Detailed console logging for debugging
"""

from .base import BaseDisplayDriver
from .developer import DeveloperDisplayDriver
from .headless import HeadlessDisplayDriver
from .minimal import MinimalDisplayDriver, NullDisplayAdapter

__all__: list[str] = [
    # Base class
    'BaseDisplayDriver',
    # Drivers
    'HeadlessDisplayDriver',
    'MinimalDisplayDriver',
    'DeveloperDisplayDriver',
    # Adapters
    'NullDisplayAdapter',
]
