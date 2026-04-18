################################################################################
# File Name: cli_commands.py
# Purpose/Description: Stateless command handlers and help/status renderers for simulator CLI
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-043
# 2026-04-14    | Sweep 5       | Extracted from simulator_cli.py (task 4 split)
# ================================================================================
################################################################################

"""
Command handler helpers for SimulatorCli.

Module-level functions that implement each command action. Every function
takes the collaborating simulator/injector/runner objects (or None) and a
`printer` callable, so the SimulatorCli class stays a thin dispatcher.
"""

import logging
from collections.abc import Callable
from typing import Any

from .cli_types import CommandResult, CommandType

logger = logging.getLogger(__name__)

Printer = Callable[[str], None]


def showHelp(printer: Printer) -> None:
    """Display help message with available commands."""
    printer("\n" + "=" * 50 + "\n")
    printer("[CLI] SIMULATOR COMMANDS\n")
    printer("=" * 50 + "\n")
    printer("  p - Pause/Resume simulation\n")
    printer("  f - Inject failure\n")
    printer("  c - Clear all failures\n")
    printer("  s - Show status\n")
    printer("  h - Show this help\n")
    printer("  q - Quit simulation\n")
    printer("=" * 50 + "\n")


def promptFailureType(printer: Printer) -> CommandResult:
    """
    Prompt user for failure type to inject.

    Args:
        printer: Callable used for output

    Returns:
        CommandResult indicating prompt was shown
    """
    printer("\n[CLI] Select failure type to inject:\n")
    printer("  1. Connection Drop\n")
    printer("  2. Sensor Failure\n")
    printer("  3. Intermittent Sensor\n")
    printer("  4. Out of Range\n")
    printer("  5. DTC Codes\n")
    printer("  x. Cancel\n")
    printer("Enter selection: ")

    return CommandResult(
        command=CommandType.INJECT_FAILURE,
        success=True,
        message="Awaiting failure type selection",
    )


def injectFailure(
    failureInjector: Any | None,
    failureTypeStr: str,
    printer: Printer,
) -> CommandResult:
    """
    Inject a failure via the failure injector.

    Args:
        failureInjector: FailureInjector instance (or None)
        failureTypeStr: String name of failure type
        printer: Callable used for output

    Returns:
        CommandResult with injection status
    """
    if failureInjector is None:
        message = "No failure injector available"
        printer(f"\n[CLI] {message}\n")
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
            printer(f"\n[CLI] {message}\n")
            return CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=False,
                message=message,
            )

        # Check if already active
        if failureInjector.isFailureActive(failureType):
            message = f"Failure already active: {failureTypeStr}"
            printer(f"\n[CLI] {message}\n")
            return CommandResult(
                command=CommandType.INJECT_FAILURE,
                success=False,
                message=message,
            )

        # Inject the failure
        failureInjector.injectFailure(failureType)
        message = f"Injected failure: {failureTypeStr}"
        printer(f"\n[CLI] {message}\n")

        return CommandResult(
            command=CommandType.INJECT_FAILURE,
            success=True,
            message=message,
            details={"failureType": failureTypeStr},
        )

    except Exception as e:
        message = f"Failed to inject failure: {e}"
        printer(f"\n[CLI] {message}\n")
        return CommandResult(
            command=CommandType.INJECT_FAILURE,
            success=False,
            message=message,
        )


def clearFailures(
    failureInjector: Any | None,
    printer: Printer,
) -> CommandResult:
    """
    Clear all active failures.

    Args:
        failureInjector: FailureInjector instance (or None)
        printer: Callable used for output

    Returns:
        CommandResult with clear status
    """
    if failureInjector is None:
        message = "No failure injector available"
        printer(f"\n[CLI] {message}\n")
        return CommandResult(
            command=CommandType.CLEAR_FAILURES,
            success=False,
            message=message,
        )

    try:
        count = failureInjector.clearAllFailures()
        message = f"Cleared {count} active failure(s)"
        printer(f"\n[CLI] {message}\n")

        return CommandResult(
            command=CommandType.CLEAR_FAILURES,
            success=True,
            message=message,
            details={"clearedCount": count},
        )

    except Exception as e:
        message = f"Failed to clear failures: {e}"
        printer(f"\n[CLI] {message}\n")
        return CommandResult(
            command=CommandType.CLEAR_FAILURES,
            success=False,
            message=message,
        )


def showStatus(
    simulator: Any | None,
    scenarioRunner: Any | None,
    failureInjector: Any | None,
    pauseRequested: bool,
    printer: Printer,
) -> CommandResult:
    """
    Show current simulator status.

    Args:
        simulator: SensorSimulator instance (or None)
        scenarioRunner: DriveScenarioRunner instance (or None)
        failureInjector: FailureInjector instance (or None)
        pauseRequested: Whether simulation is currently paused
        printer: Callable used for output

    Returns:
        CommandResult with status info
    """
    printer("\n" + "=" * 50 + "\n")
    printer("[CLI] SIMULATOR STATUS\n")
    printer("=" * 50 + "\n")

    # Simulation state
    pausedStr = "PAUSED" if pauseRequested else "RUNNING"
    printer(f"  State: {pausedStr}\n")

    # Scenario info
    if scenarioRunner is not None:
        try:
            scenarioName = scenarioRunner.scenario.name
            currentPhase = scenarioRunner.getCurrentPhase()
            phaseName = currentPhase.name if currentPhase else "N/A"
            progress = scenarioRunner.getProgress()
            printer(f"  Scenario: {scenarioName}\n")
            printer(f"  Phase: {phaseName}\n")
            printer(f"  Progress: {progress:.1f}%\n")
        except Exception as e:
            printer(f"  Scenario: Error - {e}\n")

    # Vehicle state
    if simulator is not None:
        try:
            state = simulator.state
            printer(f"  RPM: {state.rpm:.0f}\n")
            printer(f"  Speed: {state.speedKph:.1f} km/h\n")
            printer(f"  Coolant: {state.coolantTempC:.1f} C\n")
            printer(f"  Throttle: {state.throttlePercent:.1f}%\n")
            printer(f"  Gear: {state.gear}\n")
        except Exception as e:
            printer(f"  Vehicle: Error - {e}\n")

    # Active failures
    if failureInjector is not None:
        try:
            activeFailures = failureInjector.getActiveFailures()
            if activeFailures:
                printer(f"  Active Failures: {', '.join(activeFailures.keys())}\n")
            else:
                printer("  Active Failures: None\n")
        except Exception as e:
            printer(f"  Failures: Error - {e}\n")

    printer("=" * 50 + "\n")

    return CommandResult(
        command=CommandType.STATUS,
        success=True,
        message="Status displayed",
    )
