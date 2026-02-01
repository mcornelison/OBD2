################################################################################
# File Name: shutdown_command.py
# Purpose/Description: Shutdown command mechanism for OBD-II system
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# ================================================================================
################################################################################

"""
Shutdown command mechanism for the Eclipse OBD-II system.

Provides:
- Shutdown script generation (shutdown.sh)
- GPIO button trigger support
- SIGTERM sending to running process
- Graceful shutdown wait (configurable, default 30 seconds)
- Optional Raspberry Pi power down after application stops
- Shutdown reason and timestamp logging

Usage:
    from obd.shutdown_command import (
        ShutdownCommand,
        generateShutdownScript,
        GpioButtonTrigger,
    )

    # Generate shutdown script
    generateShutdownScript(outputPath='shutdown.sh')

    # Use GPIO button trigger (Raspberry Pi)
    trigger = GpioButtonTrigger(gpioPin=17)
    trigger.start()

    # Programmatic shutdown
    cmd = ShutdownCommand(pidFile='/var/run/eclipse-obd2.pid')
    cmd.initiateShutdown(reason='user_request', powerOff=False)
"""

import logging
import os
import signal
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

DEFAULT_SHUTDOWN_TIMEOUT = 30  # seconds
DEFAULT_GPIO_PIN = 17  # BCM numbering
DEFAULT_PID_FILE = '/var/run/eclipse-obd2.pid'
DEFAULT_SERVICE_NAME = 'eclipse-obd2'

# Shutdown reasons
SHUTDOWN_REASON_USER_REQUEST = 'user_request'
SHUTDOWN_REASON_GPIO_BUTTON = 'gpio_button'
SHUTDOWN_REASON_LOW_BATTERY = 'low_battery'
SHUTDOWN_REASON_MAINTENANCE = 'maintenance'
SHUTDOWN_REASON_SYSTEM = 'system'


class ShutdownState(Enum):
    """State of the shutdown process."""
    IDLE = 'idle'
    INITIATING = 'initiating'
    WAITING = 'waiting'
    COMPLETED = 'completed'
    TIMEOUT = 'timeout'
    FAILED = 'failed'


# ================================================================================
# Exceptions
# ================================================================================

class ShutdownCommandError(Exception):
    """Base exception for shutdown command errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        """
        Initialize shutdown command error.

        Args:
            message: Error message
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ProcessNotFoundError(ShutdownCommandError):
    """Error when target process cannot be found."""
    pass


class ShutdownTimeoutError(ShutdownCommandError):
    """Error when shutdown times out."""
    pass


class GpioNotAvailableError(ShutdownCommandError):
    """Error when GPIO is not available."""
    pass


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class ShutdownResult:
    """Result of a shutdown operation."""
    success: bool
    state: ShutdownState
    reason: str
    startTime: datetime
    endTime: datetime | None = None
    durationSeconds: float = 0.0
    processId: int | None = None
    powerOffRequested: bool = False
    powerOffExecuted: bool = False
    errorMessage: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            'success': self.success,
            'state': self.state.value,
            'reason': self.reason,
            'startTime': self.startTime.isoformat(),
            'endTime': self.endTime.isoformat() if self.endTime else None,
            'durationSeconds': self.durationSeconds,
            'processId': self.processId,
            'powerOffRequested': self.powerOffRequested,
            'powerOffExecuted': self.powerOffExecuted,
            'errorMessage': self.errorMessage
        }


@dataclass
class ShutdownConfig:
    """Configuration for shutdown command."""
    timeoutSeconds: int = DEFAULT_SHUTDOWN_TIMEOUT
    pidFile: str = DEFAULT_PID_FILE
    serviceName: str = DEFAULT_SERVICE_NAME
    gpioPin: int = DEFAULT_GPIO_PIN
    gpioPullUp: bool = True
    gpioDebounceMs: int = 200
    powerOffEnabled: bool = False
    powerOffDelaySeconds: int = 5
    logFile: str | None = None

    def toDict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            'timeoutSeconds': self.timeoutSeconds,
            'pidFile': self.pidFile,
            'serviceName': self.serviceName,
            'gpioPin': self.gpioPin,
            'gpioPullUp': self.gpioPullUp,
            'gpioDebounceMs': self.gpioDebounceMs,
            'powerOffEnabled': self.powerOffEnabled,
            'powerOffDelaySeconds': self.powerOffDelaySeconds,
            'logFile': self.logFile
        }


# ================================================================================
# ShutdownCommand Class
# ================================================================================

class ShutdownCommand:
    """
    Manages shutdown command operations for the OBD-II system.

    Handles sending SIGTERM to the running process, waiting for graceful
    shutdown, and optionally powering down the Raspberry Pi.

    Attributes:
        _config: Shutdown configuration
        _state: Current shutdown state
        _database: Optional database for logging

    Example:
        cmd = ShutdownCommand()
        result = cmd.initiateShutdown(reason='user_request')
        if result.success:
            print(f"Shutdown completed in {result.durationSeconds}s")
    """

    def __init__(
        self,
        config: ShutdownConfig | None = None,
        pidFile: str | None = None,
        timeoutSeconds: int | None = None,
        database: Any | None = None
    ):
        """
        Initialize shutdown command.

        Args:
            config: Shutdown configuration
            pidFile: Path to PID file (overrides config)
            timeoutSeconds: Shutdown timeout (overrides config)
            database: Optional database for logging
        """
        self._config = config or ShutdownConfig()

        if pidFile:
            self._config.pidFile = pidFile
        if timeoutSeconds:
            self._config.timeoutSeconds = timeoutSeconds

        self._database = database
        self._state = ShutdownState.IDLE
        self._lastResult: ShutdownResult | None = None

    def getState(self) -> ShutdownState:
        """Get current shutdown state."""
        return self._state

    def getLastResult(self) -> ShutdownResult | None:
        """Get result of last shutdown operation."""
        return self._lastResult

    def getProcessId(self) -> int | None:
        """
        Get process ID from PID file or systemd.

        Returns:
            Process ID if found, None otherwise
        """
        # Try PID file first
        pid = self._getProcessIdFromFile()
        if pid:
            return pid

        # Try systemd as fallback
        return self._getProcessIdFromSystemd()

    def _getProcessIdFromFile(self) -> int | None:
        """
        Get process ID from PID file.

        Returns:
            Process ID if file exists and is valid, None otherwise
        """
        try:
            if not os.path.exists(self._config.pidFile):
                return None

            with open(self._config.pidFile) as f:
                content = f.read().strip()
                if content:
                    pid = int(content)
                    # Verify process exists
                    if self._isProcessRunning(pid):
                        return pid
        except (ValueError, OSError) as e:
            logger.debug(f"Error reading PID file: {e}")

        return None

    def _getProcessIdFromSystemd(self) -> int | None:
        """
        Get process ID from systemd.

        Returns:
            Process ID if service is running, None otherwise
        """
        try:
            result = subprocess.run(
                ['systemctl', 'show', self._config.serviceName, '--property=MainPID'],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if output.startswith('MainPID='):
                    pid = int(output.split('=')[1])
                    if pid > 0 and self._isProcessRunning(pid):
                        return pid

        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

        return None

    def _isProcessRunning(self, pid: int) -> bool:
        """
        Check if a process is running.

        Args:
            pid: Process ID to check

        Returns:
            True if process is running, False otherwise
        """
        try:
            os.kill(pid, 0)  # Signal 0 just checks if process exists
            return True
        except (OSError, ProcessLookupError):
            return False

    def initiateShutdown(
        self,
        reason: str = SHUTDOWN_REASON_USER_REQUEST,
        powerOff: bool = False,
        wait: bool = True
    ) -> ShutdownResult:
        """
        Initiate graceful shutdown of the OBD-II system.

        Sends SIGTERM to the running process and waits for it to terminate.
        Optionally powers down the Raspberry Pi after the application stops.

        Args:
            reason: Reason for shutdown (for logging)
            powerOff: Whether to power off Raspberry Pi after shutdown
            wait: Whether to wait for process to terminate

        Returns:
            ShutdownResult with operation details

        Raises:
            ProcessNotFoundError: If target process cannot be found
            ShutdownTimeoutError: If shutdown times out
        """
        startTime = datetime.now()
        result = ShutdownResult(
            success=False,
            state=ShutdownState.INITIATING,
            reason=reason,
            startTime=startTime,
            powerOffRequested=powerOff
        )

        self._state = ShutdownState.INITIATING

        try:
            # Log shutdown initiation
            self._logShutdownEvent(reason, 'initiated')
            logger.info(f"Initiating shutdown | reason={reason} | powerOff={powerOff}")

            # Get process ID
            pid = self.getProcessId()
            if not pid:
                raise ProcessNotFoundError(
                    "Cannot find running process to shutdown",
                    {'pidFile': self._config.pidFile, 'service': self._config.serviceName}
                )

            result.processId = pid
            logger.info(f"Found process | pid={pid}")

            # Send SIGTERM
            self._sendSignal(pid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to process | pid={pid}")

            if wait:
                # Wait for graceful shutdown
                self._state = ShutdownState.WAITING
                result.state = ShutdownState.WAITING

                if self._waitForProcessExit(pid):
                    self._state = ShutdownState.COMPLETED
                    result.state = ShutdownState.COMPLETED
                    result.success = True
                    logger.info("Process terminated gracefully")
                else:
                    # Timeout - process didn't exit
                    self._state = ShutdownState.TIMEOUT
                    result.state = ShutdownState.TIMEOUT
                    result.errorMessage = f"Timeout waiting for process after {self._config.timeoutSeconds}s"
                    logger.warning(result.errorMessage)

                    # Send SIGKILL as last resort
                    if self._isProcessRunning(pid):
                        logger.warning(f"Sending SIGKILL to process | pid={pid}")
                        self._sendSignal(pid, signal.SIGKILL)
                        time.sleep(1)
                        result.success = not self._isProcessRunning(pid)
            else:
                # Not waiting - assume success after sending signal
                result.success = True
                self._state = ShutdownState.COMPLETED
                result.state = ShutdownState.COMPLETED

            # Handle power off
            if powerOff and result.success:
                result.powerOffExecuted = self._executePowerOff()

        except ProcessNotFoundError:
            raise
        except Exception as e:
            self._state = ShutdownState.FAILED
            result.state = ShutdownState.FAILED
            result.errorMessage = str(e)
            logger.error(f"Shutdown failed: {e}")

        finally:
            result.endTime = datetime.now()
            result.durationSeconds = (result.endTime - startTime).total_seconds()
            self._lastResult = result

            # Log completion
            self._logShutdownEvent(reason, 'completed', result)

        return result

    def _sendSignal(self, pid: int, sig: int) -> None:
        """
        Send a signal to a process.

        Args:
            pid: Process ID
            sig: Signal number

        Raises:
            ProcessNotFoundError: If process doesn't exist
        """
        try:
            os.kill(pid, sig)
        except ProcessLookupError as e:
            raise ProcessNotFoundError(f"Process {pid} not found") from e

    def _waitForProcessExit(self, pid: int) -> bool:
        """
        Wait for a process to exit.

        Args:
            pid: Process ID to wait for

        Returns:
            True if process exited within timeout, False otherwise
        """
        startTime = time.time()
        checkInterval = 0.5  # Check every 500ms

        while time.time() - startTime < self._config.timeoutSeconds:
            if not self._isProcessRunning(pid):
                return True
            time.sleep(checkInterval)

        return False

    def _executePowerOff(self) -> bool:
        """
        Execute Raspberry Pi power off.

        Returns:
            True if power off was initiated, False otherwise
        """
        logger.info(f"Executing power off in {self._config.powerOffDelaySeconds}s")

        try:
            # Use shutdown command with delay
            subprocess.run(
                ['sudo', 'shutdown', '-h', f'+{self._config.powerOffDelaySeconds // 60}',
                 '"Eclipse OBD-II shutdown"'],
                check=False  # Don't raise on non-zero exit
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Failed to initiate power off: {e}")
            return False

    def _logShutdownEvent(
        self,
        reason: str,
        event: str,
        result: ShutdownResult | None = None
    ) -> None:
        """
        Log shutdown event to database.

        Args:
            reason: Shutdown reason
            event: Event type (initiated/completed)
            result: Optional shutdown result
        """
        if not self._database:
            return

        try:
            with self._database.connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO connection_log
                    (event_type, mac_address, success, error_message, retry_count)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f'shutdown_{event}',
                        reason,
                        1 if (result and result.success) else 0,
                        result.errorMessage if result else None,
                        0
                    )
                )
            logger.debug(f"Logged shutdown event | event={event}")
        except Exception as e:
            logger.warning(f"Failed to log shutdown event: {e}")

    def stopViaSystemctl(self) -> bool:
        """
        Stop the service via systemctl.

        Returns:
            True if service was stopped, False otherwise
        """
        try:
            result = subprocess.run(
                ['sudo', 'systemctl', 'stop', self._config.serviceName],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError) as e:
            logger.error(f"Failed to stop service via systemctl: {e}")
            return False


# ================================================================================
# GPIO Button Trigger
# ================================================================================

# Try to import GPIO library (Raspberry Pi specific)
GPIO_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO = None


class GpioButtonTrigger:
    """
    GPIO button trigger for initiating shutdown.

    Monitors a GPIO pin for button presses and initiates shutdown
    when pressed. Uses pull-up resistor by default (button connects
    pin to ground when pressed).

    Attributes:
        _config: Shutdown configuration
        _shutdownCommand: ShutdownCommand instance
        _running: Whether monitoring is active
        _callback: Optional callback on button press

    Example:
        trigger = GpioButtonTrigger(gpioPin=17, callback=onButtonPress)
        trigger.start()
        # ... application runs ...
        trigger.stop()
    """

    def __init__(
        self,
        gpioPin: int = DEFAULT_GPIO_PIN,
        config: ShutdownConfig | None = None,
        shutdownCommand: ShutdownCommand | None = None,
        callback: Callable[[], None] | None = None,
        autoShutdown: bool = True,
        powerOff: bool = False
    ):
        """
        Initialize GPIO button trigger.

        Args:
            gpioPin: GPIO pin number (BCM numbering)
            config: Shutdown configuration
            shutdownCommand: ShutdownCommand instance to use
            callback: Optional callback when button is pressed
            autoShutdown: Whether to automatically initiate shutdown
            powerOff: Whether to power off after shutdown

        Raises:
            GpioNotAvailableError: If GPIO library is not available
        """
        if not GPIO_AVAILABLE:
            raise GpioNotAvailableError(
                "RPi.GPIO not available - GPIO button trigger requires Raspberry Pi"
            )

        self._config = config or ShutdownConfig()
        self._config.gpioPin = gpioPin

        self._shutdownCommand = shutdownCommand
        self._callback = callback
        self._autoShutdown = autoShutdown
        self._powerOff = powerOff
        self._running = False
        self._lastPressTime = 0

    def start(self) -> None:
        """
        Start monitoring GPIO button.

        Sets up GPIO pin with pull-up resistor and falling edge detection.
        """
        if self._running:
            logger.warning("GPIO button trigger already running")
            return

        logger.info(f"Starting GPIO button trigger | pin={self._config.gpioPin}")

        try:
            GPIO.setmode(GPIO.BCM)

            # Set up pin with pull-up
            pullUpDown = GPIO.PUD_UP if self._config.gpioPullUp else GPIO.PUD_DOWN
            GPIO.setup(self._config.gpioPin, GPIO.IN, pull_up_down=pullUpDown)

            # Add event detection for falling edge (button press with pull-up)
            edge = GPIO.FALLING if self._config.gpioPullUp else GPIO.RISING
            GPIO.add_event_detect(
                self._config.gpioPin,
                edge,
                callback=self._onButtonPress,
                bouncetime=self._config.gpioDebounceMs
            )

            self._running = True
            logger.info("GPIO button trigger started")

        except Exception as e:
            logger.error(f"Failed to start GPIO button trigger: {e}")
            raise GpioNotAvailableError(f"Failed to initialize GPIO: {e}") from e

    def stop(self) -> None:
        """
        Stop monitoring GPIO button.

        Cleans up GPIO resources.
        """
        if not self._running:
            return

        logger.info("Stopping GPIO button trigger")

        try:
            GPIO.remove_event_detect(self._config.gpioPin)
            GPIO.cleanup(self._config.gpioPin)
        except Exception as e:
            logger.warning(f"Error during GPIO cleanup: {e}")

        self._running = False
        logger.info("GPIO button trigger stopped")

    def _onButtonPress(self, channel: int) -> None:
        """
        Handle button press event.

        Args:
            channel: GPIO channel that triggered the event
        """
        currentTime = time.time()

        # Additional software debounce
        if currentTime - self._lastPressTime < (self._config.gpioDebounceMs / 1000.0):
            return

        self._lastPressTime = currentTime

        logger.info(f"GPIO button pressed | channel={channel}")

        # Execute callback if provided
        if self._callback:
            try:
                self._callback()
            except Exception as e:
                logger.error(f"Error in button callback: {e}")

        # Initiate shutdown if auto-shutdown is enabled
        if self._autoShutdown:
            self._initiateShutdown()

    def _initiateShutdown(self) -> None:
        """Initiate shutdown via button press."""
        logger.info("Initiating shutdown from GPIO button press")

        if self._shutdownCommand:
            try:
                result = self._shutdownCommand.initiateShutdown(
                    reason=SHUTDOWN_REASON_GPIO_BUTTON,
                    powerOff=self._powerOff
                )
                if not result.success:
                    logger.error(f"Shutdown failed: {result.errorMessage}")
            except Exception as e:
                logger.error(f"Error initiating shutdown: {e}")

    def isRunning(self) -> bool:
        """Check if GPIO monitoring is active."""
        return self._running


# ================================================================================
# Script Generation
# ================================================================================

def generateShutdownScript(
    outputPath: str = 'shutdown.sh',
    config: ShutdownConfig | None = None,
    powerOff: bool = False
) -> str:
    """
    Generate a shell script for shutting down the OBD-II system.

    The script:
    - Sends SIGTERM to the running process
    - Waits for graceful shutdown (max 30 seconds)
    - Optionally powers down the Raspberry Pi

    Args:
        outputPath: Path to write the script
        config: Shutdown configuration
        powerOff: Whether to include power off option

    Returns:
        Path to the generated script
    """
    cfg = config or ShutdownConfig()

    # Build power off section
    powerOffSection = ''
    if powerOff or cfg.powerOffEnabled:
        powerOffSection = f'''
# Power off option
POWER_OFF_DELAY={cfg.powerOffDelaySeconds}

if [[ "$POWER_OFF" == "true" ]]; then
    print_status "Scheduling system power off in $POWER_OFF_DELAY seconds"
    sudo shutdown -h +$((POWER_OFF_DELAY / 60)) "Eclipse OBD-II scheduled shutdown"
fi
'''

    script = f'''#!/bin/bash
################################################################################
# Eclipse OBD-II Shutdown Script
# Generated: {datetime.now().isoformat()}
#
# This script gracefully shuts down the Eclipse OBD-II system.
# Usage: ./shutdown.sh [--power-off]
################################################################################

set -e

# Configuration
SERVICE_NAME="{cfg.serviceName}"
PID_FILE="{cfg.pidFile}"
SHUTDOWN_TIMEOUT={cfg.timeoutSeconds}
POWER_OFF="${{1:-false}}"

# Process --power-off argument
if [[ "$1" == "--power-off" ]] || [[ "$1" == "-p" ]]; then
    POWER_OFF="true"
fi

# Colors for output
RED='\\033[0;31m'
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m' # No Color

print_status() {{
    echo -e "${{GREEN}}[OK]${{NC}} $1"
}}

print_error() {{
    echo -e "${{RED}}[ERROR]${{NC}} $1"
}}

print_warning() {{
    echo -e "${{YELLOW}}[WARN]${{NC}} $1"
}}

echo "=================================================="
echo "Eclipse OBD-II Shutdown"
echo "=================================================="
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Shutdown initiated"
echo ""

# Function to get PID
get_pid() {{
    # Try PID file first
    if [[ -f "$PID_FILE" ]]; then
        local pid=$(cat "$PID_FILE" 2>/dev/null)
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi

    # Try systemd
    if command -v systemctl &> /dev/null; then
        local pid=$(systemctl show "$SERVICE_NAME" --property=MainPID --value 2>/dev/null)
        if [[ -n "$pid" ]] && [[ "$pid" != "0" ]] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return 0
        fi
    fi

    # Try pgrep as last resort
    local pid=$(pgrep -f "python.*main.py" 2>/dev/null | head -1)
    if [[ -n "$pid" ]]; then
        echo "$pid"
        return 0
    fi

    return 1
}}

# Function to wait for process exit
wait_for_exit() {{
    local pid=$1
    local timeout=$2
    local elapsed=0

    echo -n "Waiting for process to exit "
    while kill -0 "$pid" 2>/dev/null && [[ $elapsed -lt $timeout ]]; do
        echo -n "."
        sleep 1
        ((elapsed++))
    done
    echo ""

    if kill -0 "$pid" 2>/dev/null; then
        return 1  # Still running
    fi
    return 0  # Exited
}}

# Get the process ID
PID=$(get_pid)

if [[ -z "$PID" ]]; then
    print_warning "No running Eclipse OBD-II process found"
    echo ""

    # Check if service exists but is stopped
    if systemctl is-enabled "$SERVICE_NAME" 2>/dev/null; then
        print_status "Service exists but is not running"
    fi

    # Handle power off even if process not running
    if [[ "$POWER_OFF" == "true" ]]; then
        echo ""
        read -p "Power off system anyway? [y/N] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_status "Scheduling system power off"
            sudo shutdown -h +0 "Eclipse OBD-II shutdown"
        fi
    fi

    exit 0
fi

echo "Found process: PID=$PID"
echo ""

# Send SIGTERM for graceful shutdown
echo "Sending SIGTERM to process $PID..."
kill -TERM "$PID" 2>/dev/null || true

# Wait for graceful shutdown
if wait_for_exit "$PID" "$SHUTDOWN_TIMEOUT"; then
    print_status "Process terminated gracefully"
else
    print_warning "Process did not exit within $SHUTDOWN_TIMEOUT seconds"
    echo ""
    read -p "Send SIGKILL to force termination? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        kill -9 "$PID" 2>/dev/null || true
        sleep 1
        if kill -0 "$PID" 2>/dev/null; then
            print_error "Failed to terminate process"
            exit 1
        else
            print_status "Process terminated (forced)"
        fi
    else
        print_error "Shutdown incomplete - process still running"
        exit 1
    fi
fi

# Clean up PID file
if [[ -f "$PID_FILE" ]]; then
    rm -f "$PID_FILE" 2>/dev/null || true
fi

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Shutdown completed"
{powerOffSection}
echo ""
echo "=================================================="
echo "Shutdown Complete!"
echo "=================================================="
'''

    with open(outputPath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(script)

    # Make executable
    try:
        currentMode = os.stat(outputPath).st_mode
        os.chmod(outputPath, currentMode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except (OSError, AttributeError):
        pass  # May fail on Windows

    return outputPath


def generateGpioTriggerScript(
    outputPath: str = 'gpio_shutdown_trigger.py',
    config: ShutdownConfig | None = None
) -> str:
    """
    Generate a Python script for GPIO button shutdown trigger.

    This is a standalone script that can be run as a service to
    monitor a GPIO button and initiate shutdown when pressed.

    Args:
        outputPath: Path to write the script
        config: Shutdown configuration

    Returns:
        Path to the generated script
    """
    cfg = config or ShutdownConfig()

    script = f'''#!/usr/bin/env python3
################################################################################
# Eclipse OBD-II GPIO Shutdown Trigger
# Generated: {datetime.now().isoformat()}
#
# Standalone script to monitor GPIO button and initiate shutdown when pressed.
# Run as a service: sudo systemctl start eclipse-obd2-gpio
################################################################################

import signal
import sys
import time
import logging
import subprocess

# Configuration
GPIO_PIN = {cfg.gpioPin}
DEBOUNCE_MS = {cfg.gpioDebounceMs}
SERVICE_NAME = "{cfg.serviceName}"
POWER_OFF_ENABLED = {str(cfg.powerOffEnabled).lower()}
POWER_OFF_DELAY = {cfg.powerOffDelaySeconds}

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Try to import GPIO
try:
    import RPi.GPIO as GPIO
except ImportError:
    logger.error("RPi.GPIO not available - this script requires Raspberry Pi")
    sys.exit(1)

running = True

def signal_handler(signum, frame):
    global running
    logger.info("Received signal, stopping...")
    running = False

def initiate_shutdown():
    logger.info("Button pressed - initiating shutdown")

    # Stop the OBD-II service
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'stop', SERVICE_NAME],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info(f"Service {{SERVICE_NAME}} stopped")
        else:
            logger.warning(f"Failed to stop service: {{result.stderr}}")
    except Exception as e:
        logger.error(f"Error stopping service: {{e}}")

    # Power off if enabled
    if POWER_OFF_ENABLED:
        logger.info(f"Scheduling power off in {{POWER_OFF_DELAY}} seconds")
        try:
            subprocess.run(
                ['sudo', 'shutdown', '-h', f'+{{POWER_OFF_DELAY // 60}}'],
                check=False
            )
        except Exception as e:
            logger.error(f"Error scheduling power off: {{e}}")

def button_callback(channel):
    initiate_shutdown()

def main():
    global running

    logger.info(f"Eclipse OBD-II GPIO Shutdown Trigger starting")
    logger.info(f"Monitoring GPIO pin {{GPIO_PIN}}")

    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Set up GPIO
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(GPIO_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(
        GPIO_PIN,
        GPIO.FALLING,
        callback=button_callback,
        bouncetime=DEBOUNCE_MS
    )

    logger.info("GPIO button trigger running")

    try:
        while running:
            time.sleep(1)
    finally:
        GPIO.cleanup(GPIO_PIN)
        logger.info("GPIO cleanup complete")

if __name__ == '__main__':
    main()
'''

    with open(outputPath, 'w', encoding='utf-8', newline='\n') as f:
        f.write(script)

    # Make executable
    try:
        currentMode = os.stat(outputPath).st_mode
        os.chmod(outputPath, currentMode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except (OSError, AttributeError):
        pass

    return outputPath


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
    shutdown = config.get('shutdown', {})
    autoStart = config.get('autoStart', {})

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


def isGpioAvailable() -> bool:
    """
    Check if GPIO library is available.

    Returns:
        True if RPi.GPIO can be imported, False otherwise
    """
    return GPIO_AVAILABLE


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
