################################################################################
# File Name: telemetry_logger.py
# Purpose/Description: System telemetry logger for Raspberry Pi hardware monitoring
# Author: Ralph Agent
# Creation Date: 2026-01-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-26    | Ralph Agent  | Initial implementation for US-RPI-011
# ================================================================================
################################################################################

"""
System telemetry logger for Raspberry Pi hardware monitoring.

This module provides logging of system telemetry data in JSON format using
Python's logging RotatingFileHandler. Telemetry includes UPS battery metrics,
CPU temperature, and disk space.

Usage:
    from hardware.telemetry_logger import TelemetryLogger

    # Create logger with default settings
    logger = TelemetryLogger()

    # Set UPS monitor for battery telemetry
    logger.setUpsMonitor(upsMonitor)

    # Start logging
    logger.start()

    # Stop logging
    logger.stop()

Note:
    This module integrates with the UpsMonitor from hardware.ups_monitor
    and reads system metrics from the OS. Log files are rotated at 100MB
    or after 7 days.
"""

import json
import logging
import os
import shutil
import socket
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .platform_utils import isRaspberryPi

logger = logging.getLogger(__name__)


# ================================================================================
# Telemetry Logger Exceptions
# ================================================================================


class TelemetryLoggerError(Exception):
    """Base exception for telemetry logger errors."""
    pass


class TelemetryLoggerNotAvailableError(TelemetryLoggerError):
    """Exception raised when telemetry logging is not available."""
    pass


# ================================================================================
# Telemetry Logger Constants
# ================================================================================

# Default configuration
DEFAULT_LOG_PATH = "/var/log/carpi/telemetry.log"
DEFAULT_LOG_INTERVAL = 10.0  # seconds
DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100MB
DEFAULT_BACKUP_COUNT = 7  # Keep 7 log files (roughly 7 days at 100MB/day)

# CPU temperature file path (Linux/Raspberry Pi)
CPU_TEMP_PATH = "/sys/class/thermal/thermal_zone0/temp"


# ================================================================================
# JSON Formatter
# ================================================================================


class JsonFormatter(logging.Formatter):
    """
    Custom formatter that outputs log records as JSON.

    Each log record is formatted as a single JSON line with the telemetry
    data stored in the message field.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON string representation of the record
        """
        # The message should already be a JSON string
        return record.getMessage()


# ================================================================================
# Telemetry Logger Class
# ================================================================================


class TelemetryLogger:
    """
    System telemetry logger for Raspberry Pi.

    Logs telemetry data in JSON format including:
    - timestamp: ISO 8601 timestamp
    - power_source: 'external' or 'battery'
    - battery_v: Battery voltage in volts
    - battery_ma: Battery current in milliamps
    - battery_pct: Battery percentage (0-100)
    - cpu_temp: CPU temperature in Celsius (null on non-Pi)
    - disk_free_mb: Free disk space in megabytes

    Attributes:
        logPath: Path to the telemetry log file
        logInterval: Logging interval in seconds
        maxBytes: Maximum log file size before rotation
        backupCount: Number of backup files to keep

    Example:
        logger = TelemetryLogger(logPath="/var/log/carpi/telemetry.log")
        logger.setUpsMonitor(upsMonitor)
        logger.start()
    """

    def __init__(
        self,
        logPath: str = DEFAULT_LOG_PATH,
        logInterval: float = DEFAULT_LOG_INTERVAL,
        maxBytes: int = DEFAULT_MAX_BYTES,
        backupCount: int = DEFAULT_BACKUP_COUNT,
    ):
        """
        Initialize telemetry logger.

        Args:
            logPath: Path to the telemetry log file
            logInterval: Logging interval in seconds (default: 10)
            maxBytes: Maximum log file size in bytes (default: 100MB)
            backupCount: Number of backup files to keep (default: 7)

        Raises:
            ValueError: If logInterval is not positive
            ValueError: If maxBytes is not positive
            ValueError: If backupCount is negative
        """
        if logInterval <= 0:
            raise ValueError("Log interval must be positive")
        if maxBytes <= 0:
            raise ValueError("Max bytes must be positive")
        if backupCount < 0:
            raise ValueError("Backup count cannot be negative")

        self._logPath = logPath
        self._logInterval = logInterval
        self._maxBytes = maxBytes
        self._backupCount = backupCount

        # UPS monitor reference (for battery telemetry)
        self._upsMonitor: Optional[Any] = None  # UpsMonitor type

        # Custom readers for testing
        self._cpuTempReader: Optional[Callable[[], Optional[float]]] = None
        self._diskFreeReader: Optional[Callable[[], Optional[int]]] = None

        # Logging state
        self._loggingThread: Optional[threading.Thread] = None
        self._stopEvent = threading.Event()
        self._isLogging = False
        self._lock = threading.Lock()

        # File logger (created on start)
        self._fileLogger: Optional[logging.Logger] = None
        self._fileHandler: Optional[RotatingFileHandler] = None

        # Error callback
        self._onError: Optional[Callable[[Exception], None]] = None

        logger.debug(
            f"TelemetryLogger initialized: logPath={logPath}, "
            f"logInterval={logInterval}s, maxBytes={maxBytes}, "
            f"backupCount={backupCount}"
        )

    def setUpsMonitor(self, monitor: Any) -> None:
        """
        Set the UPS monitor for battery telemetry.

        Args:
            monitor: UpsMonitor instance for reading battery data
        """
        self._upsMonitor = monitor
        logger.debug("UPS monitor set for telemetry logging")

    def setCpuTempReader(self, reader: Callable[[], Optional[float]]) -> None:
        """
        Set a custom CPU temperature reader (for testing).

        Args:
            reader: Callable returning CPU temperature in Celsius or None
        """
        self._cpuTempReader = reader

    def setDiskFreeReader(self, reader: Callable[[], Optional[int]]) -> None:
        """
        Set a custom disk free space reader (for testing).

        Args:
            reader: Callable returning free disk space in MB or None
        """
        self._diskFreeReader = reader

    def start(self) -> bool:
        """
        Start telemetry logging.

        Creates the log file directory if needed and starts the background
        logging thread.

        Returns:
            True if logging started successfully, False otherwise

        Raises:
            RuntimeError: If logging is already running
        """
        with self._lock:
            if self._isLogging:
                raise RuntimeError("Telemetry logging is already running")

            try:
                # Create log directory if needed
                logDir = Path(self._logPath).parent
                logDir.mkdir(parents=True, exist_ok=True)

                # Create dedicated logger for telemetry
                self._fileLogger = logging.getLogger(
                    f"telemetry.{id(self)}"
                )
                self._fileLogger.setLevel(logging.INFO)
                self._fileLogger.propagate = False  # Don't propagate to root

                # Create rotating file handler
                self._fileHandler = RotatingFileHandler(
                    self._logPath,
                    maxBytes=self._maxBytes,
                    backupCount=self._backupCount,
                    encoding='utf-8'
                )
                self._fileHandler.setFormatter(JsonFormatter())
                self._fileLogger.addHandler(self._fileHandler)

                # Start logging thread
                self._stopEvent.clear()
                self._isLogging = True

                self._loggingThread = threading.Thread(
                    target=self._loggingLoop,
                    name="TelemetryLoggerThread",
                    daemon=True
                )
                self._loggingThread.start()

                logger.info(
                    f"Telemetry logging started: {self._logPath} "
                    f"(interval={self._logInterval}s)"
                )
                return True

            except OSError as e:
                logger.error(f"Failed to start telemetry logging: {e}")
                self._cleanup()
                return False

    def stop(self) -> None:
        """
        Stop telemetry logging.

        Safe to call even if logging is not running.
        """
        with self._lock:
            if not self._isLogging:
                return

            self._stopEvent.set()

            if self._loggingThread is not None and self._loggingThread.is_alive():
                self._loggingThread.join(timeout=5.0)

            self._cleanup()
            logger.info("Telemetry logging stopped")

    def _cleanup(self) -> None:
        """Clean up logging resources."""
        self._isLogging = False
        self._loggingThread = None

        if self._fileHandler is not None:
            self._fileHandler.close()
            if self._fileLogger is not None:
                self._fileLogger.removeHandler(self._fileHandler)
            self._fileHandler = None

        self._fileLogger = None

    def _loggingLoop(self) -> None:
        """Background logging loop."""
        while not self._stopEvent.is_set():
            try:
                self._logTelemetry()
            except Exception as e:
                logger.error(f"Error logging telemetry: {e}")
                if self._onError is not None:
                    try:
                        self._onError(e)
                    except Exception as callbackError:
                        logger.error(
                            f"Error in telemetry error callback: {callbackError}"
                        )

            # Wait for next interval (or stop signal)
            self._stopEvent.wait(timeout=self._logInterval)

    def _logTelemetry(self) -> None:
        """Log a single telemetry record."""
        telemetry = self.getTelemetry()

        if self._fileLogger is not None:
            jsonStr = json.dumps(telemetry, default=str)
            self._fileLogger.info(jsonStr)
            logger.debug(f"Telemetry logged: {telemetry}")

    def getTelemetry(self) -> Dict[str, Any]:
        """
        Get current telemetry data.

        Returns:
            Dictionary with telemetry fields:
            - timestamp: ISO 8601 timestamp
            - power_source: 'external', 'battery', or 'unknown'
            - battery_v: Battery voltage in volts (or None)
            - battery_ma: Battery current in mA (or None)
            - battery_pct: Battery percentage 0-100 (or None)
            - cpu_temp: CPU temperature in Celsius (or None)
            - disk_free_mb: Free disk space in MB (or None)
        """
        telemetry: Dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'power_source': None,
            'battery_v': None,
            'battery_ma': None,
            'battery_pct': None,
            'cpu_temp': self._getCpuTemp(),
            'disk_free_mb': self._getDiskFreeMb(),
        }

        # Get battery telemetry from UPS monitor
        if self._upsMonitor is not None:
            try:
                upsTelemetry = self._upsMonitor.getTelemetry()
                telemetry['power_source'] = upsTelemetry['powerSource'].value
                telemetry['battery_v'] = upsTelemetry['voltage']
                telemetry['battery_ma'] = upsTelemetry['current']
                telemetry['battery_pct'] = upsTelemetry['percentage']
            except Exception as e:
                logger.warning(f"Failed to get UPS telemetry: {e}")

        return telemetry

    def _getCpuTemp(self) -> Optional[float]:
        """
        Get CPU temperature in Celsius.

        Returns:
            CPU temperature in Celsius, or None if unavailable
        """
        # Use custom reader if set (for testing)
        if self._cpuTempReader is not None:
            return self._cpuTempReader()

        # Only available on Linux
        if not isRaspberryPi():
            return None

        try:
            with open(CPU_TEMP_PATH, 'r') as f:
                # Temperature is in millidegrees Celsius
                tempMillidegrees = int(f.read().strip())
                return tempMillidegrees / 1000.0
        except (FileNotFoundError, IOError, ValueError) as e:
            logger.debug(f"Could not read CPU temperature: {e}")
            return None

    def _getDiskFreeMb(self) -> Optional[int]:
        """
        Get free disk space in megabytes.

        Returns:
            Free disk space in MB, or None if unavailable
        """
        # Use custom reader if set (for testing)
        if self._diskFreeReader is not None:
            return self._diskFreeReader()

        try:
            usage = shutil.disk_usage('/')
            return usage.free // (1024 * 1024)
        except (OSError, AttributeError) as e:
            logger.debug(f"Could not read disk free space: {e}")
            return None

    @property
    def logPath(self) -> str:
        """Get the log file path."""
        return self._logPath

    @property
    def logInterval(self) -> float:
        """Get the logging interval in seconds."""
        return self._logInterval

    @logInterval.setter
    def logInterval(self, value: float) -> None:
        """Set the logging interval in seconds."""
        if value <= 0:
            raise ValueError("Log interval must be positive")
        self._logInterval = value

    @property
    def maxBytes(self) -> int:
        """Get the maximum log file size in bytes."""
        return self._maxBytes

    @property
    def backupCount(self) -> int:
        """Get the number of backup files to keep."""
        return self._backupCount

    @property
    def isLogging(self) -> bool:
        """Check if logging is active."""
        return self._isLogging

    @property
    def onError(self) -> Optional[Callable[[Exception], None]]:
        """Get the error callback."""
        return self._onError

    @onError.setter
    def onError(self, callback: Optional[Callable[[Exception], None]]) -> None:
        """Set the error callback."""
        self._onError = callback

    def close(self) -> None:
        """
        Close the telemetry logger and release resources.

        Stops logging if active.
        """
        self.stop()
        logger.debug("TelemetryLogger closed")

    def __enter__(self) -> 'TelemetryLogger':
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - close the logger."""
        self.close()

    def __del__(self) -> None:
        """Destructor - ensure resources are released."""
        # Check for _lock since __del__ may be called on partially init objects
        if hasattr(self, '_lock') and hasattr(self, '_isLogging'):
            self.close()
