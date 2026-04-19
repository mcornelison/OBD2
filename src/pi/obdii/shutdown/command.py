################################################################################
# File Name: command.py
# Purpose/Description: Facade re-exporting the shutdown command subsystem + convenience helpers
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# 2026-04-14    | Sweep 5       | Split into command_* modules; file now a facade
# ================================================================================
################################################################################

"""
Shutdown command facade (legacy import path).

The implementation now lives in sibling modules:
- command_types: exceptions, enum, ShutdownResult, ShutdownConfig, constants
- command_core: ShutdownCommand class (process signaling)
- command_gpio: GpioButtonTrigger class, GPIO_AVAILABLE probe
- command_scripts: generateShutdownScript, generateGpioTriggerScript

This file remains as a compatibility shim so existing imports continue to work:

    from obd.shutdown.command import ShutdownCommand, GpioButtonTrigger

Prefer importing directly from the specific module in new code.
"""

import logging
import os
import signal

from .command_core import ShutdownCommand
from .command_gpio import GPIO_AVAILABLE, GpioButtonTrigger, isGpioAvailable
from .command_scripts import generateGpioTriggerScript, generateShutdownScript
from .command_types import (
    DEFAULT_GPIO_PIN,
    DEFAULT_PID_FILE,
    DEFAULT_SERVICE_NAME,
    DEFAULT_SHUTDOWN_TIMEOUT,
    SHUTDOWN_REASON_GPIO_BUTTON,
    SHUTDOWN_REASON_LOW_BATTERY,
    SHUTDOWN_REASON_MAINTENANCE,
    SHUTDOWN_REASON_SYSTEM,
    SHUTDOWN_REASON_USER_REQUEST,
    GpioNotAvailableError,
    ProcessNotFoundError,
    ShutdownCommandError,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
    ShutdownTimeoutError,
)

logger = logging.getLogger(__name__)


# ================================================================================
# Helper Functions
# ================================================================================

def createShutdownCommandFromConfig(config: dict) -> ShutdownCommand:
    """
    Create ShutdownCommand from application configuration.

    Args:
        config: Application configuration dictionary

    Returns:
        Configured ShutdownCommand instance
    """
    shutdownConfig = _parseShutdownConfig(config)
    return ShutdownCommand(config=shutdownConfig)


def _parseShutdownConfig(config: dict) -> ShutdownConfig:
    """
    Parse shutdown configuration from application config.

    Args:
        config: Application configuration dictionary

    Returns:
        ShutdownConfig instance
    """
    shutdown = config.get('pi', {}).get('shutdown', {})
    autoStart = config.get('pi', {}).get('autoStart', {})

    return ShutdownConfig(
        timeoutSeconds=shutdown.get('timeoutSeconds', DEFAULT_SHUTDOWN_TIMEOUT),
        pidFile=shutdown.get('pidFile', DEFAULT_PID_FILE),
        serviceName=autoStart.get('serviceName', DEFAULT_SERVICE_NAME),
        gpioPin=shutdown.get('gpioPin', DEFAULT_GPIO_PIN),
        gpioPullUp=shutdown.get('gpioPullUp', True),
        gpioDebounceMs=shutdown.get('gpioDebounceMs', 200),
        powerOffEnabled=shutdown.get('powerOffEnabled', False),
        powerOffDelaySeconds=shutdown.get('powerOffDelaySeconds', 5),
        logFile=shutdown.get('logFile')
    )


def sendShutdownSignal(
    pidFile: str = DEFAULT_PID_FILE,
    serviceName: str = DEFAULT_SERVICE_NAME
) -> bool:
    """
    Send SIGTERM to the running OBD-II process.

    Convenience function for simple shutdown scenarios.

    Args:
        pidFile: Path to PID file
        serviceName: Name of systemd service

    Returns:
        True if signal was sent, False if process not found
    """
    cmd = ShutdownCommand(pidFile=pidFile)
    cmd._config.serviceName = serviceName

    pid = cmd.getProcessId()
    if not pid:
        return False

    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


__all__ = [
    'DEFAULT_GPIO_PIN',
    'DEFAULT_PID_FILE',
    'DEFAULT_SERVICE_NAME',
    'DEFAULT_SHUTDOWN_TIMEOUT',
    'GPIO_AVAILABLE',
    'GpioButtonTrigger',
    'GpioNotAvailableError',
    'ProcessNotFoundError',
    'SHUTDOWN_REASON_GPIO_BUTTON',
    'SHUTDOWN_REASON_LOW_BATTERY',
    'SHUTDOWN_REASON_MAINTENANCE',
    'SHUTDOWN_REASON_SYSTEM',
    'SHUTDOWN_REASON_USER_REQUEST',
    'ShutdownCommand',
    'ShutdownCommandError',
    'ShutdownConfig',
    'ShutdownResult',
    'ShutdownState',
    'ShutdownTimeoutError',
    'createShutdownCommandFromConfig',
    'generateGpioTriggerScript',
    'generateShutdownScript',
    'isGpioAvailable',
    'sendShutdownSignal',
]
