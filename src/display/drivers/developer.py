################################################################################
# File Name: developer.py
# Purpose/Description: Developer display driver - detailed console logging
# Author: Ralph Agent
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | Ralph Agent  | Initial creation (US-005) - extracted from display_manager.py
# ================================================================================
################################################################################
"""
Developer display driver implementation.

Provides verbose output of all operations for debugging and development.
Outputs to stdout with formatted display showing:
- Timestamped status updates
- Detailed parameter values
- Alert history
- Operation timing
- SIM indicator when in simulation mode
- Current scenario phase (if running scenario)
- Active failure injections
"""

import logging
import sys
from datetime import datetime
from typing import Any

from display.types import AlertInfo, StatusInfo

from .base import BaseDisplayDriver

logger = logging.getLogger(__name__)


class DeveloperDisplayDriver(BaseDisplayDriver):
    """
    Developer display driver - detailed console logging.

    Provides verbose output of all operations for debugging and development.
    Outputs to stdout with formatted display showing:
    - Timestamped status updates
    - Detailed parameter values
    - Alert history
    - Operation timing
    - SIM indicator when in simulation mode
    - Current scenario phase (if running scenario)
    - Active failure injections
    """

    # ANSI color codes for terminal output
    COLORS = {
        'reset': '\033[0m',
        'red': '\033[91m',
        'green': '\033[92m',
        'yellow': '\033[93m',
        'blue': '\033[94m',
        'magenta': '\033[95m',
        'cyan': '\033[96m',
        'white': '\033[97m',
        'bold': '\033[1m',
    }

    def __init__(self, config: dict[str, Any] | None = None):
        """
        Initialize developer display driver.

        Args:
            config: Optional configuration dictionary with keys:
                - useColors: Enable ANSI colors (default: True)
                - showTimestamps: Show timestamps in output (default: True)
        """
        super().__init__(config)
        self._useColors = config.get('useColors', True) if config else True
        self._showTimestamps = config.get('showTimestamps', True) if config else True
        self._outputStream = sys.stdout
        self._statusUpdateCount = 0
        self._alertCount = 0
        self._isSimulationMode = False
        self._simulatorStatus: Any | None = None  # SimulatorStatus

    def setOutputStream(self, stream: Any) -> None:
        """
        Set the output stream for console output.

        Args:
            stream: Output stream (default: sys.stdout)
        """
        self._outputStream = stream

    def setSimulationMode(self, enabled: bool) -> None:
        """
        Set whether the system is in simulation mode.

        When enabled, the SIM indicator will be shown prominently
        in status output.

        Args:
            enabled: True to enable simulation mode display
        """
        self._isSimulationMode = enabled

    def setSimulatorStatus(self, status: Any) -> None:
        """
        Set the current simulator status for display.

        Args:
            status: SimulatorStatus object with current simulator state
        """
        self._simulatorStatus = status

    def getSimulatorStatus(self) -> Any | None:
        """
        Get the current simulator status.

        Returns:
            SimulatorStatus object or None if not set
        """
        return self._simulatorStatus

    def initialize(self) -> bool:
        """
        Initialize developer display driver.

        Returns:
            True (always successful)
        """
        self._print(
            f"\n{'='*60}\n"
            f"  Eclipse OBD-II Performance Monitor - Developer Mode\n"
            f"{'='*60}\n"
        )
        self._initialized = True
        logger.info("Developer display driver initialized - verbose console output enabled")
        return True

    def shutdown(self) -> None:
        """Shutdown developer display driver."""
        self._print(
            f"\n{'='*60}\n"
            f"  Developer Mode Shutdown\n"
            f"  Status updates: {self._statusUpdateCount}\n"
            f"  Alerts shown: {self._alertCount}\n"
            f"{'='*60}\n"
        )
        self._initialized = False

    def showStatus(self, status: StatusInfo) -> None:
        """
        Display detailed status information to console.

        Args:
            status: StatusInfo object with current status
        """
        self._lastStatus = status
        self._statusUpdateCount += 1

        timestamp = self._getTimestamp()
        connColor = 'green' if status.connectionStatus == 'Connected' else 'red'
        dbColor = 'green' if status.databaseStatus == 'Ready' else 'yellow'

        # Build header with SIM indicator if in simulation mode
        header = f"\n{self._color('cyan', '--- STATUS UPDATE ---')}"
        if self._isSimulationMode:
            simIndicator = self._color('bold', self._color('magenta', '[SIM]'))
            header = f"\n{simIndicator} {self._color('cyan', '--- STATUS UPDATE ---')}"
        header += timestamp

        output = [
            header,
            f"  Connection: {self._color(connColor, status.connectionStatus)}",
            f"  Database:   {self._color(dbColor, status.databaseStatus)}",
            f"  RPM:        {status.currentRpm if status.currentRpm else '---'}",
            f"  Coolant:    {status.coolantTemp if status.coolantTemp else '---'} C",
            f"  Profile:    {status.profileName}",
            f"  Alerts:     {len(status.activeAlerts)}"
        ]

        # Add simulator status section if in simulation mode
        if self._isSimulationMode and self._simulatorStatus is not None:
            simStatus = self._simulatorStatus
            output.append(f"\n  {self._color('magenta', '--- SIMULATOR STATUS ---')}")

            # Show scenario info if available
            if simStatus.scenarioName:
                scenarioInfo = f"  Scenario:   {simStatus.scenarioName}"
                if simStatus.currentPhase:
                    scenarioInfo += f" [{simStatus.currentPhase}]"
                output.append(scenarioInfo)

                # Show progress
                progressBar = self._renderProgressBar(simStatus.scenarioProgress)
                output.append(f"  Progress:   {progressBar} {simStatus.scenarioProgress:.1f}%")

                # Show elapsed time
                elapsed = simStatus.elapsedSeconds
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                output.append(f"  Elapsed:    {mins}m {secs}s")

                # Show loops if applicable
                if simStatus.loopsCompleted > 0:
                    output.append(f"  Loops:      {simStatus.loopsCompleted}")

            # Show active failures
            if simStatus.activeFailures:
                failuresColor = 'red' if len(simStatus.activeFailures) > 0 else 'green'
                output.append(f"  Failures:   {self._color(failuresColor, ', '.join(simStatus.activeFailures))}")
            else:
                output.append(f"  Failures:   {self._color('green', 'none')}")

        if status.activeAlerts:
            output.append("  Active alerts:")
            for alert in status.activeAlerts[:3]:  # Show first 3
                output.append(f"    - {alert}")

        self._print('\n'.join(output))

    def showAlert(self, alert: AlertInfo) -> None:
        """
        Display alert with detailed information.

        Args:
            alert: AlertInfo object with alert details
        """
        if not alert.acknowledged:
            self._activeAlerts.append(alert)
        self._alertCount += 1

        timestamp = self._getTimestamp()
        priorityColor = 'red' if alert.priority <= 2 else 'yellow'

        output = [
            f"\n{self._color('bold', self._color(priorityColor, '!!! ALERT !!!'))}{timestamp}",
            f"  Priority: {self._color(priorityColor, f'P{alert.priority}')}",
            f"  Message:  {alert.message}",
        ]

        self._print('\n'.join(output))

    def clearDisplay(self) -> None:
        """Clear display state and show clear message."""
        self._activeAlerts.clear()
        self._print(f"\n{self._color('cyan', '--- DISPLAY CLEARED ---')}")

    def _print(self, message: str) -> None:
        """
        Print message to output stream.

        Args:
            message: Message to print
        """
        try:
            print(message, file=self._outputStream, flush=True)
        except Exception as e:
            logger.error(f"Error writing to output stream: {e}")

    def _getTimestamp(self) -> str:
        """Get formatted timestamp string."""
        if not self._showTimestamps:
            return ""
        return f" [{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]"

    def _color(self, color: str, text: str) -> str:
        """
        Apply ANSI color to text.

        Args:
            color: Color name
            text: Text to colorize

        Returns:
            Colorized text (or original if colors disabled)
        """
        if not self._useColors:
            return text
        colorCode = self.COLORS.get(color, '')
        resetCode = self.COLORS.get('reset', '')
        return f"{colorCode}{text}{resetCode}"

    def _renderProgressBar(self, percent: float, width: int = 20) -> str:
        """
        Render a text-based progress bar.

        Args:
            percent: Progress percentage (0-100)
            width: Width of the progress bar in characters

        Returns:
            Progress bar string like [=========>         ]
        """
        percent = max(0, min(100, percent))
        filledWidth = int((percent / 100) * width)
        emptyWidth = width - filledWidth

        if filledWidth > 0:
            bar = "=" * (filledWidth - 1) + ">"
        else:
            bar = ""
        bar += " " * emptyWidth

        return f"[{bar}]"
