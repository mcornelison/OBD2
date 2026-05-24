################################################################################
# File Name: test_shutdown_handler_legacy_suppress.py
# Purpose/Description: Tests for ShutdownHandler's legacy-path suppression
#                      flag. When suppressLegacyTriggers=True, the
#                      30s-after-BATTERY timer + 10% low-battery automatic
#                      trigger DO NOT fire.  Phase-2 cutover: HardwareManager
#                      now wires suppressLegacyTriggers=True UNCONDITIONALLY
#                      (eclipse-powerwatch is the sole shutdown decider).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- suppression flag per Spool audit.
# 2026-05-15    | Ralph        | US-341 calibration: _executeShutdown now raises
#                 (US-341)     | ShutdownHandlerError on non-zero returncode
#                              | (was silent warning + return). Tests that
#                              | mock subprocess.run without setting returncode
#                              | now hit the raise path because an unconfigured
#                              | MagicMock returncode is truthy.  Configure the
#                              | mock to return returncode=0 so the success
#                              | path runs and the call-was-made assertion
#                              | stays intact.
# 2026-05-18    | Plan (P2-T9) | Legacy-ladder cutover: legacy in-app ladder
#                              | deleted.  HardwareManager now passes
#                              | suppressLegacyTriggers=True unconditionally
#                              | (no shutdownThresholds dependency).  Removed
#                              | the old conditional/back-compat toggling
#                              | tests; added the unconditional-wiring
#                              | assertion against
#                              | HardwareManager._initializeShutdownHandler.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.hardware.shutdown_handler` legacy-suppression flag.

Phase-2 cutover: eclipse-powerwatch is the SOLE shutdown decider.  The
legacy in-app automatic low-battery trigger must never fire, so
:class:`HardwareManager` wires ``suppressLegacyTriggers=True``
unconditionally.  These tests pin (a) the class-level suppression
contract and (b) that HardwareManager actually wires it that way.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.pi.hardware.hardware_manager import HardwareManager
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

        The suppression is about automatic/implicit legacy battery paths;
        the wrapped terminal action (used by the GPIO BUTTON path) stays
        callable.
        """
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            # US-341: _executeShutdown raises on non-zero returncode; mock
            # the success path so the assertion checks call-was-made.
            mockSubprocess.return_value = MagicMock(
                returncode=0, stderr="", stdout=""
            )
            handler._executeShutdown()  # noqa: SLF001
        mockSubprocess.assert_called_once()
        handler.close()


class TestHardwareManagerWiresSuppressionUnconditionally:
    """Phase-2 cutover: HardwareManager always suppresses legacy triggers."""

    def test_initializeShutdownHandler_passesSuppressTrue(self) -> None:
        """_initializeShutdownHandler must wire suppressLegacyTriggers=True.

        eclipse-powerwatch is the sole shutdown decider -- there is no
        conditional/shutdownThresholds toggle anymore.  The constructed
        ShutdownHandler must report suppression on.
        """
        manager = HardwareManager.__new__(HardwareManager)
        manager._shutdownDelay = 30
        manager._lowBatteryThreshold = 10
        manager._poweroffTimeoutSeconds = 60
        manager._shutdownHandler = None

        manager._initializeShutdownHandler()

        assert manager._shutdownHandler is not None
        assert manager._shutdownHandler.suppressLegacyTriggers is True
        manager._shutdownHandler.close()
