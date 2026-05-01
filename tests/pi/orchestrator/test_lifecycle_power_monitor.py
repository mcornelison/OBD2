################################################################################
# File Name: test_lifecycle_power_monitor.py
# Purpose/Description: US-243 / B-050 -- lifecycle wiring for PowerMonitor
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex (US-243) | Initial: assert _initializePowerMonitor creates
#                              | a PowerMonitor when pi.power.power_monitor.enabled
#                              | is true; assert _subscribePowerMonitorToUpsMonitor
#                              | wires UpsMonitor.onPowerSourceChange to a fan-out
#                              | that preserves the prior ShutdownHandler callback.
# ================================================================================
################################################################################

"""US-243 / B-050: lifecycle wiring tests for PowerMonitor activation.

The DB-write path itself is exercised in
``tests/pi/power/test_power_monitor_db_write.py``.  This file covers the
plumbing inside ``LifecycleMixin``:

1. ``_initializePowerMonitor`` -- gated on
   ``pi.power.power_monitor.enabled`` (default true) AND a live DB.
2. ``_subscribePowerMonitorToUpsMonitor`` -- chains the UpsMonitor
   ``onPowerSourceChange`` callback so the legacy ShutdownHandler
   handler keeps firing AND PowerMonitor receives every transition.
3. ``_shutdownPowerMonitor`` -- symmetry with the rest of the lifecycle
   (drops the reference; safe to call before init).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pi.hardware.ups_monitor import PowerSource as HwPowerSource
from pi.obdii.orchestrator.core import ApplicationOrchestrator

# ================================================================================
# Helpers
# ================================================================================


def _baseConfig(
    *,
    powerMonitorEnabled: bool = True,
) -> dict[str, Any]:
    """Minimum tier-aware config that boots the orchestrator in simulate mode."""
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "chi-eclipse-01",
        "pi": {
            "database": {"path": ":memory:"},
            "power": {
                "power_monitor": {"enabled": powerMonitorEnabled},
            },
        },
        "server": {},
    }


def _makeOrch(config: dict[str, Any]) -> ApplicationOrchestrator:
    # simulate=True keeps the OBD path mocked; this test exercises just
    # the PowerMonitor wiring, not full init.
    return ApplicationOrchestrator(config=config, simulate=True)


# ================================================================================
# 1. _initializePowerMonitor gating
# ================================================================================


class TestInitializePowerMonitor:

    def test_enabledConfig_andDbPresent_createsPowerMonitor(self) -> None:
        """
        Given: pi.power.power_monitor.enabled=true AND a live DB
        When:  _initializePowerMonitor is called
        Then:  orchestrator has a PowerMonitor instance.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()  # surrogate live DB
        orch._initializePowerMonitor()

        assert orch.powerMonitor is not None

    def test_disabledConfig_leavesPowerMonitorNone(self) -> None:
        """
        Given: pi.power.power_monitor.enabled=false
        When:  _initializePowerMonitor is called
        Then:  no PowerMonitor is constructed (gate honored).
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=False))
        orch._database = MagicMock()
        orch._initializePowerMonitor()

        assert orch.powerMonitor is None

    def test_missingDatabase_leavesPowerMonitorNone(self) -> None:
        """
        Given: pi.power.power_monitor.enabled=true BUT database is None
        When:  _initializePowerMonitor is called
        Then:  no PowerMonitor is constructed -- power_log writes need a DB.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = None
        orch._initializePowerMonitor()

        assert orch.powerMonitor is None

    def test_powerMonitor_isInitiallyEnabled(self) -> None:
        """
        Given: A constructed PowerMonitor with enabled=True passed in
        When:  Reading its enabled state via the public getCurrentPowerSource API
        Then:  Construction succeeded and the monitor is in an active state.

        Note: PowerMonitor.getStatus() has a pre-existing non-reentrant-lock
        deadlock (getStatus + getStats both acquire ``self._lock``;
        ``threading.Lock`` is not reentrant). Filed as TD-041; out of scope
        per US-243 ``doNotTouch: PowerMonitor's internal state machine logic``.
        This test reads the simpler public surface to avoid the deadlock.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()

        assert orch.powerMonitor is not None
        # getCurrentPowerSource() is a thin getter (no lock acquisition)
        # so it's deadlock-safe.  Initial state is UNKNOWN until the
        # first checkPowerStatus call -- proves the object is alive.
        # NB: import from ``pi.power.types`` (matches the relative-import
        # path PowerMonitor uses internally), not ``src.pi.power.types``
        # -- conftest puts src/ on sys.path so the two prefixes resolve
        # to distinct module objects whose enum members compare unequal.
        from pi.power.types import PowerSource as PmPowerSource
        assert orch.powerMonitor.getCurrentPowerSource() == PmPowerSource.UNKNOWN


# ================================================================================
# 2. _subscribePowerMonitorToUpsMonitor wiring
# ================================================================================


class TestSubscribePowerMonitorToUpsMonitor:
    """The fan-out wraps any existing onPowerSourceChange callback.

    HardwareManager._wireComponents calls
    ShutdownHandler.registerWithUpsMonitor which sets
    upsMonitor.onPowerSourceChange = handler.onPowerSourceChange.
    The PowerMonitor subscription must preserve that path.
    """

    def test_subscribe_setsOnPowerSourceChange(self) -> None:
        """
        Given: PowerMonitor + a HardwareManager whose UpsMonitor exists
        When:  _subscribePowerMonitorToUpsMonitor is called
        Then:  UpsMonitor.onPowerSourceChange is no longer the bare prior
               callback -- it's the fan-out wrapper.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()

        priorCallback = MagicMock()
        fakeUps = MagicMock()
        fakeUps.onPowerSourceChange = priorCallback
        orch._hardwareManager = MagicMock()
        orch._hardwareManager.upsMonitor = fakeUps

        orch._subscribePowerMonitorToUpsMonitor()

        # The UpsMonitor's callback was replaced (not the bare prior).
        assert fakeUps.onPowerSourceChange is not priorCallback
        assert fakeUps.onPowerSourceChange is not None

    def test_fanOut_preservesPriorCallback(self) -> None:
        """
        Given: A prior ShutdownHandler callback was registered
        When:  Fan-out fires on a UpsMonitor transition
        Then:  Prior callback is invoked with the original args.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()

        priorCallback = MagicMock()
        fakeUps = MagicMock()
        fakeUps.onPowerSourceChange = priorCallback
        orch._hardwareManager = MagicMock()
        orch._hardwareManager.upsMonitor = fakeUps

        orch._subscribePowerMonitorToUpsMonitor()

        # Trigger via the freshly wired fan-out.
        fakeUps.onPowerSourceChange(
            HwPowerSource.EXTERNAL, HwPowerSource.BATTERY,
        )

        priorCallback.assert_called_once_with(
            HwPowerSource.EXTERNAL, HwPowerSource.BATTERY,
        )

    def test_fanOut_invokesPowerMonitorCheckPowerStatus(self) -> None:
        """
        Given: The fan-out is wired
        When:  UpsMonitor fires EXTERNAL -> BATTERY
        Then:  PowerMonitor.checkPowerStatus is called with onAcPower=False.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()

        # Spy on the PowerMonitor's checkPowerStatus directly.
        orch._powerMonitor.checkPowerStatus = MagicMock()

        fakeUps = MagicMock()
        fakeUps.onPowerSourceChange = None
        orch._hardwareManager = MagicMock()
        orch._hardwareManager.upsMonitor = fakeUps

        orch._subscribePowerMonitorToUpsMonitor()
        fakeUps.onPowerSourceChange(
            HwPowerSource.EXTERNAL, HwPowerSource.BATTERY,
        )

        orch._powerMonitor.checkPowerStatus.assert_called_once_with(False)

    def test_acRestore_callsCheckPowerStatusTrue(self) -> None:
        """
        Given: Fan-out wired
        When:  BATTERY -> EXTERNAL transition fires
        Then:  PowerMonitor.checkPowerStatus(True) is called.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()
        orch._powerMonitor.checkPowerStatus = MagicMock()

        fakeUps = MagicMock()
        fakeUps.onPowerSourceChange = None
        orch._hardwareManager = MagicMock()
        orch._hardwareManager.upsMonitor = fakeUps

        orch._subscribePowerMonitorToUpsMonitor()
        fakeUps.onPowerSourceChange(
            HwPowerSource.BATTERY, HwPowerSource.EXTERNAL,
        )

        orch._powerMonitor.checkPowerStatus.assert_called_once_with(True)

    def test_subscribe_skippedWhenPowerMonitorNone(self) -> None:
        """
        Given: PowerMonitor was disabled -> None
        When:  _subscribePowerMonitorToUpsMonitor is called
        Then:  No-op; UpsMonitor's prior callback is left intact.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=False))
        orch._database = MagicMock()
        orch._initializePowerMonitor()
        assert orch.powerMonitor is None

        priorCallback = MagicMock()
        fakeUps = MagicMock()
        fakeUps.onPowerSourceChange = priorCallback
        orch._hardwareManager = MagicMock()
        orch._hardwareManager.upsMonitor = fakeUps

        orch._subscribePowerMonitorToUpsMonitor()

        assert fakeUps.onPowerSourceChange is priorCallback

    def test_subscribe_skippedWhenUpsMonitorNone(self) -> None:
        """
        Given: HardwareManager has no UpsMonitor (non-Pi or init failure)
        When:  _subscribePowerMonitorToUpsMonitor is called
        Then:  No exception; nothing is wired.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()

        orch._hardwareManager = MagicMock()
        orch._hardwareManager.upsMonitor = None

        # Should not raise.
        orch._subscribePowerMonitorToUpsMonitor()


# ================================================================================
# 3. _shutdownPowerMonitor symmetry
# ================================================================================


class TestShutdownPowerMonitor:

    def test_shutdown_dropsReference(self) -> None:
        """
        Given: A constructed PowerMonitor
        When:  _shutdownPowerMonitor is called
        Then:  The reference is cleared.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=True))
        orch._database = MagicMock()
        orch._initializePowerMonitor()
        assert orch.powerMonitor is not None

        orch._shutdownPowerMonitor()

        assert orch.powerMonitor is None

    def test_shutdown_idempotent_whenNeverInitialized(self) -> None:
        """
        Given: PowerMonitor was never initialized (None)
        When:  _shutdownPowerMonitor is called
        Then:  No exception (idempotent shutdown invariant).
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=False))

        # Should not raise.
        orch._shutdownPowerMonitor()

        assert orch.powerMonitor is None
