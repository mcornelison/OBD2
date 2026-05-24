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
# 2. _subscribePowerMonitorToPowerSourceProvider wiring (SS-T4 / Atlas 2026-05-19)
# ================================================================================


class TestSubscribePowerMonitorToPowerSourceProvider:
    """SS-T4: the UI power-source path now flows from PowerSourceProvider
    (GPIO6 SSOT) via the dedicated B1 ``_PowerSourceUiBridge`` thread --
    NOT from the retired ``UpsMonitor.getPowerSource`` event subscription.
    The deep transition behaviour (present->lost->present feeds
    checkPowerStatus) is covered by
    ``tests/pi/orchestrator/test_lifecycle_power_source_ssot.py`` against
    the injectable bridge class directly. This class covers only the
    orchestrator-level wiring (the method's existence, idempotency, and
    no-PowerMonitor skip).
    """

    def test_subscribe_constructsProviderAndStartsBridge(
        self, monkeypatch
    ) -> None:
        """
        Given: PowerMonitor + a powerWatch config block
        When:  _subscribePowerMonitorToPowerSourceProvider is called
        Then:  a ``_powerSourceProvider`` is attached AND a started
               ``_powerSourceUiBridge`` is attached (the SSOT wiring is live).
        """
        # Mock the imports the method does internally so the test does not
        # require real GPIO.

        class _FakePld:
            def __init__(self, *, pin, powerPresentHigh):
                self.isAvailable = False  # safe direction
            def isExternalPowerPresent(self): return True
            def isPowerLost(self): return False
            def startupPolarityOk(self): return False

        # Patch the deferred imports done inside the method.
        import pi.hardware.pld_sensor as pldMod
        import pi.power.power_source_provider as pspMod
        monkeypatch.setattr(pldMod, "PldSensor", _FakePld)
        # Real PowerSourceProvider is fine (it's a thin wrapper).
        _ = pspMod  # silence unused

        cfg = _baseConfig(powerMonitorEnabled=True)
        cfg["pi"]["powerWatch"] = {
            "pldGpioPin": 6, "pldPowerPresentHigh": True, "uiPollSec": 0.01,
        }
        orch = _makeOrch(cfg)
        orch._database = MagicMock()
        orch._initializePowerMonitor()
        orch._subscribePowerMonitorToPowerSourceProvider()

        try:
            assert getattr(orch, "_powerSourceProvider", None) is not None
            bridge = getattr(orch, "_powerSourceUiBridge", None)
            assert bridge is not None
            # Duck-typed check (not isinstance): lifecycle.py is reachable via
            # two sys.modules entries (with/without the `src.` prefix), each
            # carrying its own class object -- isinstance across paths fails
            # (cross-module identity gotcha). The shape is what we care about.
            assert hasattr(bridge, "start") and hasattr(bridge, "stop")
            assert hasattr(bridge, "pollOnce")
        finally:
            # Always stop the bridge so the test doesn't leak a thread.
            if getattr(orch, "_powerSourceUiBridge", None) is not None:
                orch._shutdownPowerSourceUiBridge()

    def test_subscribe_isIdempotent(self, monkeypatch) -> None:
        """A second call must NOT replace the running bridge (no thread leak)."""
        from pi.obdii.orchestrator import lifecycle as lifecycleMod

        class _FakePld:
            def __init__(self, *, pin, powerPresentHigh):
                self.isAvailable = False
            def isExternalPowerPresent(self): return True
            def isPowerLost(self): return False
            def startupPolarityOk(self): return False

        import pi.hardware.pld_sensor as pldMod
        monkeypatch.setattr(pldMod, "PldSensor", _FakePld)

        cfg = _baseConfig(powerMonitorEnabled=True)
        cfg["pi"]["powerWatch"] = {
            "pldGpioPin": 6, "pldPowerPresentHigh": True, "uiPollSec": 0.01,
        }
        orch = _makeOrch(cfg)
        orch._database = MagicMock()
        orch._initializePowerMonitor()
        orch._subscribePowerMonitorToPowerSourceProvider()
        try:
            firstBridge = orch._powerSourceUiBridge
            orch._subscribePowerMonitorToPowerSourceProvider()
            assert orch._powerSourceUiBridge is firstBridge
        finally:
            if getattr(orch, "_powerSourceUiBridge", None) is not None:
                orch._shutdownPowerSourceUiBridge()
        _ = lifecycleMod  # silence unused

    def test_subscribe_skippedWhenPowerMonitorNone(self) -> None:
        """
        Given: PowerMonitor disabled -> None
        When:  _subscribePowerMonitorToPowerSourceProvider is called
        Then:  No-op; no bridge is started.
        """
        orch = _makeOrch(_baseConfig(powerMonitorEnabled=False))
        orch._database = MagicMock()
        orch._initializePowerMonitor()
        assert orch.powerMonitor is None
        orch._subscribePowerMonitorToPowerSourceProvider()
        assert getattr(orch, "_powerSourceUiBridge", None) is None


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
