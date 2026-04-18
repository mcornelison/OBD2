################################################################################
# File Name: command_core.py
# Purpose/Description: ShutdownCommand class — process discovery, signaling, graceful termination
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-009
# 2026-04-14    | Sweep 5       | Extracted from command.py (task 4 split)
# ================================================================================
################################################################################

"""
ShutdownCommand — finds the target OBD-II process (via PID file or systemd),
sends it SIGTERM, waits for graceful exit, escalates to SIGKILL on timeout,
and optionally schedules a Pi power off afterwards.
"""

import logging
import os
import signal
import subprocess
import time
from datetime import datetime
from typing import Any

from .command_types import (
    SHUTDOWN_REASON_USER_REQUEST,
    ProcessNotFoundError,
    ShutdownConfig,
    ShutdownResult,
    ShutdownState,
)

logger = logging.getLogger(__name__)


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
