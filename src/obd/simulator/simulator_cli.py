################################################################################
# File Name: simulator_cli.py
# Purpose/Description: CLI commands for controlling the OBD-II simulator
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-043
# ================================================================================
################################################################################

"""
Simulator CLI commands module for the Eclipse OBD-II simulator.

Provides:
- SimulatorCli class for handling keyboard commands during simulation
- Non-blocking input handling using threads
- Command processing for pause/resume, failure injection, status display
- Integration with developer display mode

Commands:
- p: Pause/resume simulation
- f: Inject a failure (prompts for type)
- c: Clear all failures
- s: Show current status
- q: Quit simulation

Usage:
    from obd.simulator.simulator_cli import SimulatorCli

    # Create CLI handler with simulator components
    cli = SimulatorCli(
        simulator=simulator,
        scenarioRunner=runner,
        failureInjector=injector,
        displayDriver=developerDriver,
    )

    # Start listening for commands
    cli.start()

    # In your main loop
    while running:
        # Process simulation...
        if cli.shouldQuit():
            break

    # Stop the CLI handler
    cli.stop()
"""

import logging
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================

# Command keys
COMMAND_PAUSE = 'p'
COMMAND_FAILURE = 'f'
COMMAND_CLEAR = 'c'
COMMAND_STATUS = 's'
COMMAND_QUIT = 'q'
COMMAND_HELP = 'h'

# Valid commands
VALID_COMMANDS = {COMMAND_PAUSE, COMMAND_FAILURE, COMMAND_CLEAR, COMMAND_STATUS, COMMAND_QUIT, COMMAND_HELP}

# Failure type shortcuts for the failure injection menu
FAILURE_TYPE_SHORTCUTS = {
    '1': 'connectionDrop',
    '2': 'sensorFailure',
    '3': 'intermittentSensor',
    '4': 'outOfRange',
    '5': 'dtcCodes',
}


# ================================================================================
# Enums
# ================================================================================

class CliState(Enum):
    """State of the CLI handler."""

    STOPPED = "stopped"
    RUNNING = "running"
    AWAITING_FAILURE_TYPE = "awaiting_failure_type"
    PAUSED = "paused"


class CommandType(Enum):
    """Type of CLI command."""

    PAUSE = "pause"
    RESUME = "resume"
    INJECT_FAILURE = "inject_failure"
    CLEAR_FAILURES = "clear_failures"
    STATUS = "status"
    QUIT = "quit"
    HELP = "help"
    UNKNOWN = "unknown"


# ================================================================================
# Data Classes
# ================================================================================

@dataclass
class CommandResult:
    """
    Result of executing a CLI command.

    Attributes:
        command: The command type that was executed
        success: Whether the command executed successfully
        message: Human-readable result message
        details: Additional details about the result
    """

    command: CommandType
    success: bool
    message: str
    details: Dict[str, Any] = None

    def __post_init__(self) -> None:
        """Initialize details if not provided."""
        if self.details is None:
            self.details = {}

    def toDict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "command": self.command.value,
            "success": self.success,
            "message": self.message,
            "details": self.details,
        }


# ================================================================================
# SimulatorCli Class
# ================================================================================

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
        simulator: Optional[Any] = None,
        scenarioRunner: Optional[Any] = None,
        failureInjector: Optional[Any] = None,
        displayDriver: Optional[Any] = None,
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
        self._inputThread: Optional[threading.Thread] = None
        self._stopEvent = threading.Event()
        self._lock = threading.Lock()

        # Input queue for pending commands
        self._pendingCommands: List[str] = []

        # Callbacks
        self._onCommand: Optional[Callable[[CommandType, CommandResult], None]] = None
        self._onQuit: Optional[Callable[[], None]] = None
        self._onPause: Optional[Callable[[bool], None]] = None

        # Statistics
        self._commandCount = 0
        self._startTime: Optional[float] = None

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
        self._showHelp()

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
                # Try to read input with timeout
                char = self._readChar()
                if char:
                    self._processChar(char)
            except Exception as e:
                if not self._stopEvent.is_set():
                    logger.error(f"Input error: {e}")

            # Small sleep to prevent busy loop
            time.sleep(0.05)

    def _readChar(self) -> Optional[str]:
        """
        Read a single character from input stream.

        Uses platform-specific non-blocking input where available.

        Returns:
            Character read, or None if no input available
        """
        # Try to use msvcrt on Windows for non-blocking input
        try:
            import msvcrt
            if msvcrt.kbhit():
                char = msvcrt.getch().decode('utf-8', errors='ignore')
                return char.lower()
        except (ImportError, AttributeError):
            pass

        # Try to use select on Unix
        try:
            import select
            if select.select([self._inputStream], [], [], 0.1)[0]:
                char = self._inputStream.read(1)
                if char:
                    return char.lower()
        except (ImportError, OSError, TypeError):
            pass

        return None

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

        if command == COMMAND_PAUSE:
            result = self._togglePause()
        elif command == COMMAND_FAILURE:
            result = self._promptFailureType()
        elif command == COMMAND_CLEAR:
            result = self._clearFailures()
        elif command == COMMAND_STATUS:
            result = self._showStatus()
        elif command == COMMAND_QUIT:
            result = self._handleQuit()
        elif command == COMMAND_HELP:
            result = self._handleHelp()
        else:
            result = CommandResult(
                command=CommandType.UNKNOWN,
                success=False,
                message=f"Unknown command: {command}",
            )

        # Log command
        self._logCommand(result)

        # Trigger callback
        if self._onCommand:
            try:
                self._onCommand(result.command, result)
            except Exception as e:
                logger.warning(f"Command callback error: {e}")

    def _handleFailureTypeSelection(self, char: str) -> None:
        """
        Handle failure type selection when awaiting input.

        Args:
            char: Character representing failure type selection
        """
        self._state = CliState.RUNNING

        if char in FAILURE_TYPE_SHORTCUTS:
            failureTypeStr = FAILURE_TYPE_SHORTCUTS[char]
            result = self._injectFailure(failureTypeStr)
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
    # Command Implementations
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

    def _promptFailureType(self) -> CommandResult:
        """
        Prompt user for failure type to inject.

        Returns:
            CommandResult indicating prompt was shown
        """
        self._state = CliState.AWAITING_FAILURE_TYPE

        self._print("\n[CLI] Select failure type to inject:\n")
        self._print("  1. Connection Drop\n")
        self._print("  2. Sensor Failure\n")
        self._print("  3. Intermittent Sensor\n")
        self._print("  4. Out of Range\n")
        self._print("  5. DTC Codes\n")
        self._print("  x. Cancel\n")
        self._print("Enter selection: ")

        return CommandResult(
            command=CommandType.INJECT_FAILURE,
            success=True,
            message="Awaiting failure type selection",
        )

    def _injectFailure(self, failureTypeStr: str) -> CommandResult:
        """
        Inject a failure.

        Args:
            failureTypeStr: String name of failure type

        Returns:
            CommandResult with injection status
        """
        if self.failureInjector is None:
            message = "No failure injector available"
            self._print(f"\n[CLI] {message}\n")
            return CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=False,
                message=message,
            )

        try:
            # Import FailureType locally to avoid circular imports
            from .failure_injector import FailureType

            failureType = FailureType.fromString(failureTypeStr)
            if failureType is None:
                message = f"Unknown failure type: {failureTypeStr}"
                self._print(f"\n[CLI] {message}\n")
                return CommandResult(
                    command=CommandType.INJECT_FAILURE,
                    success=False,
                    message=message,
                )

            # Check if already active
            if self.failureInjector.isFailureActive(failureType):
                message = f"Failure already active: {failureTypeStr}"
                self._print(f"\n[CLI] {message}\n")
                return CommandResult(
                    command=CommandType.INJECT_FAILURE,
                    success=False,
                    message=message,
                )

            # Inject the failure
            self.failureInjector.injectFailure(failureType)
            message = f"Injected failure: {failureTypeStr}"
            self._print(f"\n[CLI] {message}\n")

            return CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=True,
                message=message,
                details={"failureType": failureTypeStr},
            )

        except Exception as e:
            message = f"Failed to inject failure: {e}"
            self._print(f"\n[CLI] {message}\n")
            return CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=False,
                message=message,
            )

    def _clearFailures(self) -> CommandResult:
        """
        Clear all active failures.

        Returns:
            CommandResult with clear status
        """
        if self.failureInjector is None:
            message = "No failure injector available"
            self._print(f"\n[CLI] {message}\n")
            return CommandResult(
                command=CommandType.CLEAR_FAILURES,
                success=False,
                message=message,
            )

        try:
            count = self.failureInjector.clearAllFailures()
            message = f"Cleared {count} active failure(s)"
            self._print(f"\n[CLI] {message}\n")

            return CommandResult(
                command=CommandType.CLEAR_FAILURES,
                success=True,
                message=message,
                details={"clearedCount": count},
            )

        except Exception as e:
            message = f"Failed to clear failures: {e}"
            self._print(f"\n[CLI] {message}\n")
            return CommandResult(
                command=CommandType.CLEAR_FAILURES,
                success=False,
                message=message,
            )

    def _showStatus(self) -> CommandResult:
        """
        Show current simulator status.

        Returns:
            CommandResult with status info
        """
        self._print("\n" + "=" * 50 + "\n")
        self._print("[CLI] SIMULATOR STATUS\n")
        self._print("=" * 50 + "\n")

        # Simulation state
        pausedStr = "PAUSED" if self._pauseRequested else "RUNNING"
        self._print(f"  State: {pausedStr}\n")

        # Scenario info
        if self.scenarioRunner is not None:
            try:
                scenarioName = self.scenarioRunner.scenario.name
                currentPhase = self.scenarioRunner.getCurrentPhase()
                phaseName = currentPhase.name if currentPhase else "N/A"
                progress = self.scenarioRunner.getProgress()
                self._print(f"  Scenario: {scenarioName}\n")
                self._print(f"  Phase: {phaseName}\n")
                self._print(f"  Progress: {progress:.1f}%\n")
            except Exception as e:
                self._print(f"  Scenario: Error - {e}\n")

        # Vehicle state
        if self.simulator is not None:
            try:
                state = self.simulator.state
                self._print(f"  RPM: {state.rpm:.0f}\n")
                self._print(f"  Speed: {state.speedKph:.1f} km/h\n")
                self._print(f"  Coolant: {state.coolantTempC:.1f} C\n")
                self._print(f"  Throttle: {state.throttlePercent:.1f}%\n")
                self._print(f"  Gear: {state.gear}\n")
            except Exception as e:
                self._print(f"  Vehicle: Error - {e}\n")

        # Active failures
        if self.failureInjector is not None:
            try:
                activeFailures = self.failureInjector.getActiveFailures()
                if activeFailures:
                    self._print(f"  Active Failures: {', '.join(activeFailures.keys())}\n")
                else:
                    self._print("  Active Failures: None\n")
            except Exception as e:
                self._print(f"  Failures: Error - {e}\n")

        self._print("=" * 50 + "\n")

        return CommandResult(
            command=CommandType.STATUS,
            success=True,
            message="Status displayed",
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

    def _handleHelp(self) -> CommandResult:
        """
        Handle help command.

        Returns:
            CommandResult with help status
        """
        self._showHelp()
        return CommandResult(
            command=CommandType.HELP,
            success=True,
            message="Help displayed",
        )

    def _showHelp(self) -> None:
        """Display help message with available commands."""
        self._print("\n" + "=" * 50 + "\n")
        self._print("[CLI] SIMULATOR COMMANDS\n")
        self._print("=" * 50 + "\n")
        self._print("  p - Pause/Resume simulation\n")
        self._print("  f - Inject failure\n")
        self._print("  c - Clear all failures\n")
        self._print("  s - Show status\n")
        self._print("  h - Show this help\n")
        self._print("  q - Quit simulation\n")
        self._print("=" * 50 + "\n")

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
        callback: Optional[Callable[[CommandType, CommandResult], None]]
    ) -> None:
        """
        Set callback for when a command is executed.

        Args:
            callback: Function(commandType, result) to call, or None to clear
        """
        self._onCommand = callback

    def setOnQuitCallback(self, callback: Optional[Callable[[], None]]) -> None:
        """
        Set callback for when quit is requested.

        Args:
            callback: Function() to call on quit, or None to clear
        """
        self._onQuit = callback

    def setOnPauseCallback(self, callback: Optional[Callable[[bool], None]]) -> None:
        """
        Set callback for when pause state changes.

        Args:
            callback: Function(isPaused) to call, or None to clear
        """
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

        if command == COMMAND_PAUSE:
            result = self._togglePause()
        elif command == COMMAND_FAILURE:
            # For testing, just return the prompt result
            result = self._promptFailureType()
        elif command == COMMAND_CLEAR:
            result = self._clearFailures()
        elif command == COMMAND_STATUS:
            result = self._showStatus()
        elif command == COMMAND_QUIT:
            result = self._handleQuit()
        elif command == COMMAND_HELP:
            result = self._handleHelp()
        else:
            result = CommandResult(
                command=CommandType.UNKNOWN,
                success=False,
                message=f"Unknown command: {command}",
            )

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
        return self._injectFailure(failureTypeStr)

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
    simulator: Optional[Any] = None,
    scenarioRunner: Optional[Any] = None,
    failureInjector: Optional[Any] = None,
    displayDriver: Optional[Any] = None,
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
    config: Dict[str, Any],
    simulator: Optional[Any] = None,
    scenarioRunner: Optional[Any] = None,
    failureInjector: Optional[Any] = None,
    displayDriver: Optional[Any] = None,
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
