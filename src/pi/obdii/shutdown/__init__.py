################################################################################
# File Name: __init__.py
# Purpose/Description: Shutdown subpackage for graceful shutdown handling
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial subpackage creation (US-001)
# 2026-04-13    | Ralph Agent  | Sweep 1: consolidate shutdown_manager and shutdown_command
# ================================================================================
################################################################################
"""
Shutdown Subpackage.

This subpackage contains shutdown handling components:
- Shutdown manager
- Shutdown command execution
- GPIO button trigger
- Shutdown script generation
"""

from .command import (
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
    SHUTDOWN_REASON_USER_REQUEST,
    GpioButtonTrigger,
    GpioNotAvailableError,
    ProcessNotFoundError,
    ShutdownCommand,
    ShutdownCommandError,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
    ShutdownTimeoutError,
    createShutdownCommandFromConfig,
    generateGpioTriggerScript,
    generateShutdownScript,
    isGpioAvailable,
    sendShutdownSignal,
)
from .manager import (
    ShutdownManager,
    createShutdownManager,
    installGlobalShutdownHandler,
)

__all__ = [
    # Shutdown Manager
    "ShutdownManager",
    "createShutdownManager",
    "installGlobalShutdownHandler",
    # Shutdown Command
    "ShutdownCommand",
    "ShutdownConfig",
    "ShutdownResult",
    "ShutdownState",
    "ShutdownCommandError",
    "ProcessNotFoundError",
    "ShutdownTimeoutError",
    "GpioNotAvailableError",
    "GpioButtonTrigger",
    "generateShutdownScript",
    "generateGpioTriggerScript",
    "createShutdownCommandFromConfig",
    "isGpioAvailable",
    "sendShutdownSignal",
    "SHUTDOWN_REASON_USER_REQUEST",
    "SHUTDOWN_REASON_GPIO_BUTTON",
    "SHUTDOWN_REASON_LOW_BATTERY",
    "SHUTDOWN_REASON_MAINTENANCE",
    "SHUTDOWN_REASON_SYSTEM",
]
