################################################################################
# File Name: __init__.py
# Purpose/Description: Hardware package initialization for Raspberry Pi modules
# Author: Ralph Agent
# Creation Date: 2026-01-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-25    | Ralph Agent  | Initial implementation for US-RPI-003
# ================================================================================
################################################################################

"""
Hardware package for Raspberry Pi-specific functionality.

This package provides hardware abstraction for Raspberry Pi features:
- Platform detection (isRaspberryPi, getPlatformInfo)
- I2C communication (I2cClient)
- UPS monitoring (UpsMonitor)
- Graceful shutdown handling (ShutdownHandler)
- GPIO button handling (GpioButton)
- Status display management (StatusDisplay)
- System telemetry logging (TelemetryLogger)
- Hardware integration management (HardwareManager)

All modules gracefully handle non-Pi systems by returning safe defaults
or logging warnings when hardware features are unavailable.

Usage:
    from hardware import isRaspberryPi, getPlatformInfo

    if isRaspberryPi():
        # Enable Pi-specific features using HardwareManager
        from hardware import HardwareManager, createHardwareManagerFromConfig

        # Option 1: Create from config
        manager = createHardwareManagerFromConfig(config)

        # Option 2: Create with defaults
        manager = HardwareManager()

        # Start all hardware modules
        manager.start()

        # Get status
        status = manager.getStatus()

        # Update display
        manager.updateObdStatus('connected')
        manager.updateErrorCount(warnings=0, errors=0)

        # Stop all hardware modules
        manager.stop()

    # Individual module access (for advanced usage):
    from hardware import (
        I2cClient, UpsMonitor, PowerSource, ShutdownHandler,
        GpioButton, StatusDisplay, TelemetryLogger
    )
"""

from .platform_utils import isRaspberryPi, getPlatformInfo
from .i2c_client import (
    I2cClient,
    I2cError,
    I2cNotAvailableError,
    I2cCommunicationError,
    I2cDeviceNotFoundError,
)
from .ups_monitor import (
    UpsMonitor,
    UpsMonitorError,
    UpsNotAvailableError,
    PowerSource,
)
from .shutdown_handler import (
    ShutdownHandler,
    ShutdownHandlerError,
)
from .gpio_button import (
    GpioButton,
    GpioButtonError,
    GpioNotAvailableError,
)
from .status_display import (
    StatusDisplay,
    StatusDisplayError,
    DisplayNotAvailableError,
    ConnectionStatus,
    PowerSourceDisplay,
)
from .telemetry_logger import (
    TelemetryLogger,
    TelemetryLoggerError,
    TelemetryLoggerNotAvailableError,
)
from .hardware_manager import (
    HardwareManager,
    HardwareManagerError,
    createHardwareManagerFromConfig,
)

__all__ = [
    # Platform utilities
    'isRaspberryPi',
    'getPlatformInfo',
    # I2C client
    'I2cClient',
    'I2cError',
    'I2cNotAvailableError',
    'I2cCommunicationError',
    'I2cDeviceNotFoundError',
    # UPS monitoring
    'UpsMonitor',
    'UpsMonitorError',
    'UpsNotAvailableError',
    'PowerSource',
    # Shutdown handling
    'ShutdownHandler',
    'ShutdownHandlerError',
    # GPIO button
    'GpioButton',
    'GpioButtonError',
    'GpioNotAvailableError',
    # Status display
    'StatusDisplay',
    'StatusDisplayError',
    'DisplayNotAvailableError',
    'ConnectionStatus',
    'PowerSourceDisplay',
    # Telemetry logging
    'TelemetryLogger',
    'TelemetryLoggerError',
    'TelemetryLoggerNotAvailableError',
    # Hardware manager
    'HardwareManager',
    'HardwareManagerError',
    'createHardwareManagerFromConfig',
]
