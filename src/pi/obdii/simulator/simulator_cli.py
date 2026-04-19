################################################################################
# File Name: simulator_cli.py
# Purpose/Description: SimulatorCli class — keyboard command handler for simulation
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-043
# 2026-04-14    | Sweep 5       | Split types/input/commands into cli_* modules
# ================================================================================
################################################################################

"""
Simulator CLI commands module for the Eclipse OBD-II simulator.

Provides:
- SimulatorCli class for handling keyboard commands during simulation
- Non-blocking input handling using threads
- Command processing for pause/resume, failure injection, status display
- Integration with developer display mode

Supporting modules:
- cli_types: enums, constants, CommandResult
- cli_input: platform-specific single-character input
- cli_commands: stateless command handlers

Commands:
- p: Pause/resume simulation
- f: Inject a failure (prompts for type)
- c: Clear all failures
- s: Show current status
- q: Quit simulation

Usage:
    from obd.simulator.simulator_cli import SimulatorCli

    cli = SimulatorCli(
        simulator=simulator,
        scenarioRunner=runner,
        failureInjector=injector,
        displayDriver=developerDriver,
    )

    cli.start()
    while not cli.shouldQuit():
        # Run simulation...
        pass
    cli.stop()
"""

import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from .cli_commands import (
    clearFailures,
    injectFailure,
    promptFailureType,
    showHelp,
    showStatus,
)
from .cli_input import readChar
from .cli_types import (
    COMMAND_CLEAR,
    COMMAND_FAILURE,
    COMMAND_HELP,
    COMMAND_PAUSE,
    COMMAND_QUIT,
    COMMAND_STATUS,
    FAILURE_TYPE_SHORTCUTS,
    VALID_COMMANDS,
    CliState,
    CommandResult,
    CommandType,
)

logger = logging.getLogger(__name__)


__all__ = [
    'CliState',
    'CommandResult',
    'CommandType',
    'SimulatorCli',
    'createSimulatorCli',
    'createSimulatorCliFromConfig',
]


class SimulatorCli:
    """
    CLI command handler for the OBD-II simulator.

    Provides keyboard command handling during simulation for:
    - Pausing/resuming simulation
    - Injecting failures
    - Clearing failures
    - Displaying status
    - Quitting

    Uses non-blocking input handling via a background thread to avoid
    interrupting the main simulation loop.

    Attributes:
        isRunning: Whether the CLI handler is active
        isPaused: Whether simulation is paused
        shouldQuit: Whether quit has been requested

    Example:
        cli = SimulatorCli(
            simulator=simulator,
            scenarioRunner=runner,
            failureInjector=injector,
            displayDriver=driver,
        )
        cli.start()

        while not cli.shouldQuit():
            # Run simulation...
            pass

        cli.stop()
    """

    def __init__(
        self,
        simulator: Any | None = None,
        scenarioRunner: Any | None = None,
        failureInjector: Any | None = None,
        displayDriver: Any | None = None,
        outputStream: Any = None,
        inputStream: Any = None,
    ) -> None:
        """
        Initialize SimulatorCli.

        Args:
            simulator: SensorSimulator instance (optional)
            scenarioRunner: DriveScenarioRunner instance (optional)
            failureInjector: FailureInjector instance (optional)
            displayDriver: Display driver for output (optional)
            outputStream: Stream for output (default: sys.stdout)
            inputStream: Stream for input (default: sys.stdin)
        """
        self.simulator = simulator
        self.scenarioRunner = scenarioRunner
        self.failureInjector = failureInjector
        self.displayDriver = displayDriver
        self._outputStream = outputStream or sys.stdout
        self._inputStream = inputStream or sys.stdin

        # State
        self._state = CliState.STOPPED
        self._quitRequested = False
        self._pauseRequested = False

        # Threading
        self._inputThread: threading.Thread | None = None
        self._stopEvent = threading.Event()
        self._lock = threading.Lock()

        # Input queue for pending commands
        self._pendingCommands: list[str] = []

        # Callbacks
        self._onCommand: Callable[[CommandType, CommandResult], None] | None = None
        self._onQuit: Callable[[], None] | None = None
        self._onPause: Callable[[bool], None] | None = None

        # Statistics
        self._commandCount = 0
        self._startTime: float | None = None

        logger.debug("SimulatorCli initialized")

    # ==========================================================================
    # Lifecycle
    # ==========================================================================

    def start(self) -> bool:
        """
        Start the CLI handler.

        Starts a background thread for non-blocking input handling.

        Returns:
            True if started successfully
        """
        if self._state == CliState.RUNNING:
            logger.warning("CLI already running")
            return False

        self._state = CliState.RUNNING
        self._quitRequested = False
        self._stopEvent.clear()
        self._startTime = time.time()

        # Start input thread
        self._inputThread = threading.Thread(
            target=self._inputLoop,
            daemon=True,
            name="SimulatorCliInput"
        )
        self._inputThread.start()

        # Show help message
        showHelp(self._print)

        logger.info("SimulatorCli started")
        return True

    def stop(self) -> None:
        """
        Stop the CLI handler.

        Stops the background input thread and cleans up resources.
        """
        if self._state == CliState.STOPPED:
            return

        self._state = CliState.STOPPED
        self._stopEvent.set()

        if self._inputThread:
            # Thread may be blocking on input, so we use a short timeout
            self._inputThread.join(timeout=0.5)
            self._inputThread = None

        logger.info(f"SimulatorCli stopped | commands={self._commandCount}")

    def shouldQuit(self) -> bool:
        """
        Check if quit has been requested.

        Returns:
            True if the 'q' command was received
        """
        return self._quitRequested

    def isPaused(self) -> bool:
        """
        Check if simulation is paused.

        Returns:
            True if pause was requested via 'p' command
        """
        return self._pauseRequested

    @property
    def isRunning(self) -> bool:
        """Check if CLI handler is running."""
        return self._state != CliState.STOPPED

    @property
    def state(self) -> CliState:
        """Get current CLI state."""
        return self._state

    # ==========================================================================
    # Input Handling
    # ==========================================================================

    def _inputLoop(self) -> None:
        """
        Background thread loop for reading input.

        Reads characters from stdin in a non-blocking manner on Windows
        and Unix systems.
        """
        while not self._stopEvent.is_set():
            try:
                char = readChar(self._inputStream)
                if char:
                    self._processChar(char)
            except Exception as e:
                if not self._stopEvent.is_set():
                    logger.error(f"Input error: {e}")

            # Small sleep to prevent busy loop
            time.sleep(0.05)

    def _processChar(self, char: str) -> None:
        """
        Process a single input character.

        Args:
            char: The character received
        """
        # Handle failure type selection if awaiting
        if self._state == CliState.AWAITING_FAILURE_TYPE:
            self._handleFailureTypeSelection(char)
            return

        # Handle normal commands
        if char in VALID_COMMANDS:
            self._handleCommand(char)
        else:
            # Ignore invalid commands silently
            pass

    def _handleCommand(self, command: str) -> None:
        """
        Handle a CLI command.

        Args:
            command: Single character command
        """
        self._commandCount += 1
        result = self._dispatchCommand(command)

        # Log command
        self._logCommand(result)

        # Trigger callback
        if self._onCommand:
            try:
                self._onCommand(result.command, result)
            except Exception as e:
                logger.warning(f"Command callback error: {e}")

    def _dispatchCommand(self, command: str) -> CommandResult:
        """
        Dispatch a single-character command to its handler.

        Args:
            command: Single character command

        Returns:
            CommandResult from the handler
        """
        if command == COMMAND_PAUSE:
            return self._togglePause()
        if command == COMMAND_FAILURE:
            self._state = CliState.AWAITING_FAILURE_TYPE
            return promptFailureType(self._print)
        if command == COMMAND_CLEAR:
            return clearFailures(self.failureInjector, self._print)
        if command == COMMAND_STATUS:
            return showStatus(
                self.simulator,
                self.scenarioRunner,
                self.failureInjector,
                self._pauseRequested,
                self._print,
            )
        if command == COMMAND_QUIT:
            return self._handleQuit()
        if command == COMMAND_HELP:
            showHelp(self._print)
            return CommandResult(
                command=CommandType.HELP,
                success=True,
                message="Help displayed",
            )
        return CommandResult(
            command=CommandType.UNKNOWN,
            success=False,
            message=f"Unknown command: {command}",
        )

    def _handleFailureTypeSelection(self, char: str) -> None:
        """
        Handle failure type selection when awaiting input.

        Args:
            char: Character representing failure type selection
        """
        self._state = CliState.RUNNING

        if char in FAILURE_TYPE_SHORTCUTS:
            failureTypeStr = FAILURE_TYPE_SHORTCUTS[char]
            result = injectFailure(self.failureInjector, failureTypeStr, self._print)
        elif char == 'x' or char == '\x1b':  # x or escape to cancel
            result = CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=True,
                message="Failure injection cancelled",
            )
            self._print("Cancelled\n")
        else:
            result = CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=False,
                message=f"Invalid failure type: {char}",
            )
            self._print(f"Invalid selection: {char}\n")

        # Log command
        self._logCommand(result)

        # Trigger callback
        if self._onCommand:
            try:
                self._onCommand(result.command, result)
            except Exception as e:
                logger.warning(f"Command callback error: {e}")

    # ==========================================================================
    # Stateful Command Implementations
    # ==========================================================================

    def _togglePause(self) -> CommandResult:
        """
        Toggle pause state.

        Returns:
            CommandResult with pause/resume status
        """
        self._pauseRequested = not self._pauseRequested
        commandType = CommandType.PAUSE if self._pauseRequested else CommandType.RESUME

        # Pause/resume scenario runner if available
        if self.scenarioRunner is not None:
            try:
                if self._pauseRequested:
                    self.scenarioRunner.pause()
                else:
                    self.scenarioRunner.resume()
            except Exception as e:
                logger.warning(f"Failed to {commandType.value} scenario runner: {e}")

        message = "Simulation PAUSED" if self._pauseRequested else "Simulation RESUMED"
        self._print(f"\n[CLI] {message}\n")

        # Trigger pause callback
        if self._onPause:
            try:
                self._onPause(self._pauseRequested)
            except Exception as e:
                logger.warning(f"Pause callback error: {e}")

        return CommandResult(
            command=commandType,
            success=True,
            message=message,
            details={"paused": self._pauseRequested},
        )

    def _handleQuit(self) -> CommandResult:
        """
        Handle quit command.

        Returns:
            CommandResult with quit status
        """
        self._quitRequested = True
        message = "Quit requested - shutting down..."
        self._print(f"\n[CLI] {message}\n")

        # Trigger quit callback
        if self._onQuit:
            try:
                self._onQuit()
            except Exception as e:
                logger.warning(f"Quit callback error: {e}")

        return CommandResult(
            command=CommandType.QUIT,
            success=True,
            message=message,
        )

    # ==========================================================================
    # Output and Logging
    # ==========================================================================

    def _print(self, message: str) -> None:
        """
        Print message to output stream.

        Args:
            message: Message to print
        """
        try:
            self._outputStream.write(message)
            self._outputStream.flush()
        except Exception as e:
            logger.error(f"Output error: {e}")

    def _logCommand(self, result: CommandResult) -> None:
        """
        Log a command execution.

        Args:
            result: CommandResult to log
        """
        statusStr = "OK" if result.success else "FAIL"
        logger.info(f"CLI command: {result.command.value} | {statusStr} | {result.message}")

    # ==========================================================================
    # Callbacks
    # ==========================================================================

    def setOnCommandCallback(
        self,
        callback: Callable[[CommandType, CommandResult], None] | None
    ) -> None:
        """Set callback for when a command is executed."""
        self._onCommand = callback

    def setOnQuitCallback(self, callback: Callable[[], None] | None) -> None:
        """Set callback for when quit is requested."""
        self._onQuit = callback

    def setOnPauseCallback(self, callback: Callable[[bool], None] | None) -> None:
        """Set callback for when pause state changes."""
        self._onPause = callback

    # ==========================================================================
    # Direct Command Execution (for testing)
    # ==========================================================================

    def executeCommand(self, command: str) -> CommandResult:
        """
        Execute a command directly (for testing).

        This method processes a command synchronously without using
        the background input thread.

        Args:
            command: Single character command to execute

        Returns:
            CommandResult with execution status
        """
        command = command.lower()

        if command not in VALID_COMMANDS:
            result = CommandResult(
                command=CommandType.UNKNOWN,
                success=False,
                message=f"Unknown command: {command}",
            )
            self._triggerCommandCallback(result)
            return result

        # Handle command directly
        self._commandCount += 1
        result = self._dispatchCommand(command)

        # Trigger callback
        self._triggerCommandCallback(result)

        # Log command
        self._logCommand(result)

        return result

    def _triggerCommandCallback(self, result: CommandResult) -> None:
        """
        Trigger the command callback if set.

        Args:
            result: CommandResult to pass to callback
        """
        if self._onCommand:
            try:
                self._onCommand(result.command, result)
            except Exception as e:
                logger.warning(f"Command callback error: {e}")

    def injectFailureByType(self, failureTypeStr: str) -> CommandResult:
        """
        Inject a failure by type string (for testing).

        Args:
            failureTypeStr: Failure type string (e.g., 'connectionDrop')

        Returns:
            CommandResult with injection status
        """
        return injectFailure(self.failureInjector, failureTypeStr, self._print)

    # ==========================================================================
    # Statistics
    # ==========================================================================

    def getCommandCount(self) -> int:
        """
        Get number of commands processed.

        Returns:
            Total command count
        """
        return self._commandCount

    def getUptime(self) -> float:
        """
        Get CLI handler uptime in seconds.

        Returns:
            Seconds since start() was called, or 0 if not running
        """
        if self._startTime is None:
            return 0.0
        return time.time() - self._startTime


# ================================================================================
# Helper Functions
# ================================================================================

def createSimulatorCli(
    simulator: Any | None = None,
    scenarioRunner: Any | None = None,
    failureInjector: Any | None = None,
    displayDriver: Any | None = None,
) -> SimulatorCli:
    """
    Create a SimulatorCli instance.

    Convenience function for creating a CLI handler with the common
    simulator components.

    Args:
        simulator: SensorSimulator instance
        scenarioRunner: DriveScenarioRunner instance
        failureInjector: FailureInjector instance
        displayDriver: Display driver for output

    Returns:
        Configured SimulatorCli instance

    Example:
        cli = createSimulatorCli(
            simulator=simulator,
            scenarioRunner=runner,
            failureInjector=injector,
        )
        cli.start()
    """
    return SimulatorCli(
        simulator=simulator,
        scenarioRunner=scenarioRunner,
        failureInjector=failureInjector,
        displayDriver=displayDriver,
    )


def createSimulatorCliFromConfig(
    config: dict[str, Any],
    simulator: Any | None = None,
    scenarioRunner: Any | None = None,
    failureInjector: Any | None = None,
    displayDriver: Any | None = None,
) -> SimulatorCli:
    """
    Create a SimulatorCli from configuration.

    Args:
        config: Configuration dictionary (for future extensions)
        simulator: SensorSimulator instance
        scenarioRunner: DriveScenarioRunner instance
        failureInjector: FailureInjector instance
        displayDriver: Display driver for output

    Returns:
        Configured SimulatorCli instance
    """
    # Config is available for future extensions
    _ = config

    return SimulatorCli(
        simulator=simulator,
        scenarioRunner=scenarioRunner,
        failureInjector=failureInjector,
        displayDriver=displayDriver,
    )
