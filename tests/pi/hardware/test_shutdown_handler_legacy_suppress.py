################################################################################
# File Name: test_shutdown_handler_legacy_suppress.py
# Purpose/Description: Tests for ShutdownHandler's legacy-path suppression
#                      flag (US-216). When suppressLegacyTriggers=True,
#                      the 30s-after-BATTERY timer + 10% low-battery
#                      trigger DO NOT fire. When False, legacy behavior
#                      is preserved for backward compat.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- suppression flag per Spool audit.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.hardware.shutdown_handler` legacy-suppression flag.

The new US-216 PowerDownOrchestrator races the legacy ShutdownHandler
30s-after-BATTERY timer + 10% low-battery trigger. Spool audit TD-D
mandates the legacy path is suppressed when the new ladder is active.
"""

from __future__ import annotations

from unittest.mock import patch

from src.pi.hardware.shutdown_handler import ShutdownHandler
from src.pi.hardware.ups_monitor import PowerSource


class TestSuppressLegacyTriggersEnabled:
    """suppressLegacyTriggers=True -> both legacy paths are inert."""

    def test_onPowerSourceChangeBattery_doesNotScheduleShutdown(
        self,
    ) -> None:
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        assert handler.isShutdownPending is False
        handler.close()

    def test_onLowBatteryAtThreshold_doesNotCallSystemctl(self) -> None:
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            handler.onLowBattery(5)
            handler.onLowBattery(0)
        assert mockSubprocess.call_count == 0
        handler.close()

    def test_executeShutdown_stillWorksWhenCalledExplicitly(self) -> None:
        """Even with suppression, an explicit _executeShutdown call still runs.

        This is the path US-216's orchestrator uses at TRIGGER@20%. The
        suppression is about automatic/implicit legacy paths; the wrapped
        terminal action stays callable.
        """
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            handler._executeShutdown()  # noqa: SLF001
        mockSubprocess.assert_called_once()
        handler.close()


class TestSuppressLegacyTriggersDisabled:
    """suppressLegacyTriggers=False -> legacy behavior preserved (default)."""

    def test_onPowerSourceChangeBattery_schedulesShutdown(self) -> None:
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=False,
        )
        handler.onPowerSourceChange(PowerSource.EXTERNAL, PowerSource.BATTERY)
        assert handler.isShutdownPending is True
        handler.cancelShutdown()
        handler.close()

    def test_onLowBatteryBelowThreshold_callsSystemctl(self) -> None:
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=False,
        )
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            handler.onLowBattery(5)
        mockSubprocess.assert_called_once()
        handler.close()

    def test_defaultIsNonSuppressing_backwardsCompat(self) -> None:
        """Omitting suppressLegacyTriggers preserves pre-US-216 behavior."""
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
        )
        assert handler.suppressLegacyTriggers is False
        handler.close()
