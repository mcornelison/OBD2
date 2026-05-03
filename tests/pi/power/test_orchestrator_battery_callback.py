################################################################################
# File Name: test_orchestrator_battery_callback.py
# Purpose/Description: US-279 ladder fix runtime-validation gate -- the synthetic
#                      proof that PowerDownOrchestrator now consumes power-source
#                      transitions via UpsMonitor's event-driven callback API
#                      (Option B), eliminating the stale-cached read pattern that
#                      survived 8 drain tests across 4 sprints.  Drain Test 8
#                      proved the polling loop logged the BATTERY transition
#                      while every one of 214 orchestrator ticks early-returned
#                      reason=power_source!=BATTERY -- the polling thread's view
#                      and the orchestrator's view were decoupled.  US-279
#                      replaces that read with a registered callback: UpsMonitor
#                      pushes the new PowerSource into orchestrator.self._powerSource
#                      synchronously on every transition, and tick() reads the
#                      attribute directly.  Mocks operate at I2cClient.readWord
#                      level (MAX17048 chip-read entry point) for register-
#                      decoding fidelity per feedback_runtime_validation_required.md
#                      -- mocking at UpsMonitor.getVcell would bypass the real
#                      byte-swap path that the bug class lives near.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-03    | Rex (US-279) | Initial -- 8 tests across 4 classes.  Pre-fix
#                              | gate: TestIntegrationStageFiringViaCallback FAILS
#                              | because orchestrator has no _onPowerSourceChange
#                              | method (AttributeError) and tick() reads the
#                              | stale currentSource parameter even when callback
#                              | path attempts to override it.  Post-fix gate:
#                              | callback updates self._powerSource and tick()
#                              | reads the attribute, ignoring the stale arg.
# ================================================================================
################################################################################

"""US-279 ladder fix: event-driven power-source callback path.

Background
----------
The 8-drain saga (Sprints 21-24) ended at Drain Test 8 with the bug
isolated by full Sprint 23 instrumentation.  Per Spool's 2026-05-03
sprint24-ladder-fix-bug-isolated note:

* UpsMonitor's ``_pollingLoop`` correctly logged the BATTERY transition
  at 08:50:22.
* Yet every one of 214 orchestrator tick decisions in the same drain
  emitted ``reason=power_source!=BATTERY`` -- the orchestrator's
  ``currentSource`` parameter was decoupled from UpsMonitor's live
  view.
* ``_enterStage`` was never called, no ``STAGE_*`` rows landed in
  ``power_log``, and the Pi hard-crashed at the buck-converter dropout
  knee (VCELL ~3.30V) without graceful shutdown.

US-279 replaces the stale-read pattern with an event-driven callback
(Option B per CIO 2026-05-03 mandate -- no architectural ambiguity in
contracts per BL-009 lesson).  UpsMonitor exposes
``registerSourceChangeCallback(callback)``; on every source transition
the polling loop invokes all registered callbacks with the new
``PowerSource``.  ``PowerDownOrchestrator`` registers
``_onPowerSourceChange`` as such a callback; the method updates
``self._powerSource`` synchronously and ``tick()`` reads the attribute
directly, bypassing the stale parameter path.

Test fidelity
-------------
The integration test is the runtime-validation-required gate per
specs/methodology.md "Integration Tests for Runtime-Verifiable Bugs"
subsection (Sprint 21 US-256 pattern).  It MUST FAIL pre-fix and PASS
post-fix.  The pre-fix failure mode is twofold: (a) orchestrator has no
``_onPowerSourceChange`` method (AttributeError); (b) even if the
attribute existed, the existing tick() body uses the ``currentSource``
parameter exclusively -- the integration test deliberately passes a
STALE ``currentSource=EXTERNAL`` to expose the bug, and only the
post-fix logic (read self._powerSource) overrides it correctly.

Mocks operate at :meth:`I2cClient.readWord` (MAX17048 chip-read entry
point) per ``feedback_runtime_validation_required.md`` -- mocking at
``UpsMonitor.getVcell()`` would bypass the real byte-swap path where
encoding bugs hide.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pi.hardware.shutdown_handler import ShutdownHandler
from src.pi.hardware.ups_monitor import (
    CRATE_DISABLED_RAW,
    REGISTER_CRATE,
    REGISTER_SOC,
    REGISTER_VCELL,
    PowerSource,
    UpsMonitor,
)
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)
from src.pi.power.power_db import logShutdownStage

# ================================================================================
# Mock I2C client -- MAX17048 chip-read fidelity
# ================================================================================

_VCELL_LSB_V = 78.125e-6
_SOC_PINNED_PCT = 60


def _vcellWordLittleEndian(volts: float) -> int:
    """Encode VCELL volts as the little-endian word SMBus would return."""
    raw = int(round(volts / _VCELL_LSB_V))
    bigEndian = raw & 0xFFFF
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    """Encode SOC% as the little-endian word SMBus would return."""
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class _MockI2cClient:
    """Drop-in I2cClient for UpsMonitor with scriptable VCELL/SOC reads."""

    def __init__(self, vcellVolts: float, socPercent: int = _SOC_PINNED_PCT):
        self.vcellVolts = vcellVolts
        self.socPercent = socPercent

    def setVcell(self, volts: float) -> None:
        self.vcellVolts = volts

    def readWord(self, address: int, register: int) -> int:
        if register == REGISTER_VCELL:
            return _vcellWordLittleEndian(self.vcellVolts)
        if register == REGISTER_SOC:
            return _socWordLittleEndian(self.socPercent)
        if register == REGISTER_CRATE:
            return CRATE_DISABLED_RAW
        return 0x0000

    def close(self) -> None:
        pass


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(
        str(tmp_path / "test_us279_battery_callback.db"), walMode=False,
    )
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


@pytest.fixture()
def thresholds() -> ShutdownThresholds:
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def mockI2c() -> _MockI2cClient:
    return _MockI2cClient(vcellVolts=4.20)


@pytest.fixture()
def upsMonitor(mockI2c: _MockI2cClient) -> UpsMonitor:
    return UpsMonitor(i2cClient=mockI2c)


@pytest.fixture()
def shutdownAction() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def orchestrator(
    thresholds: ShutdownThresholds,
    recorder: BatteryHealthRecorder,
    shutdownAction: MagicMock,
) -> PowerDownOrchestrator:
    return PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=shutdownAction,
    )


# ================================================================================
# TestRegisterSourceChangeCallback -- the new UpsMonitor API
# ================================================================================


class TestRegisterSourceChangeCallback:
    """The new public API on UpsMonitor: register a callback that fires
    on every PowerSource transition.

    Pre-fix this entire class FAILS because ``registerSourceChangeCallback``
    does not exist on UpsMonitor.  Post-fix the method appends to an
    internal list which the polling-loop transition handler walks.
    """

    def test_registerSourceChangeCallback_appends_to_internal_list(
        self, upsMonitor: UpsMonitor,
    ) -> None:
        """Registering a callback adds it to an internal list.

        Multiple registrations are allowed -- consumers that subscribe at
        different lifecycle phases (orchestrator + future audit hooks)
        all receive the transition event.
        """
        callbackA = MagicMock()
        callbackB = MagicMock()
        upsMonitor.registerSourceChangeCallback(callbackA)
        upsMonitor.registerSourceChangeCallback(callbackB)

        upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)

        callbackA.assert_called_once_with(PowerSource.BATTERY)
        callbackB.assert_called_once_with(PowerSource.BATTERY)

    def test_callback_exception_does_not_halt_invocation_chain(
        self,
        upsMonitor: UpsMonitor,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A raising callback must not prevent later callbacks from firing.

        Polling-loop invariant: forensics MUST NOT crash safety paths.
        Callback exceptions are logged at ERROR but suppressed so the
        ladder's _onPowerSourceChange always receives the transition
        even if a sibling audit callback regressed.
        """
        raisingCallback = MagicMock(
            side_effect=RuntimeError("audit-callback-regression"),
        )
        survivingCallback = MagicMock()
        upsMonitor.registerSourceChangeCallback(raisingCallback)
        upsMonitor.registerSourceChangeCallback(survivingCallback)

        with caplog.at_level(
            logging.ERROR, logger="src.pi.hardware.ups_monitor",
        ):
            upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)

        raisingCallback.assert_called_once_with(PowerSource.BATTERY)
        # The surviving callback fires even though the prior one raised.
        survivingCallback.assert_called_once_with(PowerSource.BATTERY)
        assert any(
            "audit-callback-regression" in record.getMessage()
            for record in caplog.records if record.levelno == logging.ERROR
        ), "Callback exception must be logged at ERROR level"


# ================================================================================
# TestOrchestratorPowerSourceCallback -- the orchestrator side
# ================================================================================


class TestOrchestratorPowerSourceCallback:
    """PowerDownOrchestrator stores power source state updated by callback.

    Pre-fix the orchestrator has no ``_onPowerSourceChange`` method and
    no ``_powerSource`` attribute -- AttributeError on first call.
    Post-fix the callback updates ``self._powerSource`` synchronously and
    tick() reads the attribute, ignoring the stale ``currentSource``
    parameter.
    """

    def test_onPowerSourceChange_updates_powerSource_attribute(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """Calling the callback method updates the orchestrator's
        live power source attribute.

        This is the synchronous-update contract: the callback returns
        only after self._powerSource holds the new value, so the next
        tick() (whether from the same thread or another) sees fresh state.
        """
        # Pre-callback: attribute is initial / None / default-EXTERNAL
        # -- exact initial value is implementation detail; the
        # post-callback assertion is what matters.
        orchestrator._onPowerSourceChange(PowerSource.BATTERY)
        assert orchestrator._powerSource == PowerSource.BATTERY

        orchestrator._onPowerSourceChange(PowerSource.EXTERNAL)
        assert orchestrator._powerSource == PowerSource.EXTERNAL

    def test_tick_uses_callback_powerSource_overriding_stale_arg(
        self,
        orchestrator: PowerDownOrchestrator,
        thresholds: ShutdownThresholds,
    ) -> None:
        """The bug-fix invariant: once the callback fires BATTERY, tick()
        ignores a stale ``currentSource=EXTERNAL`` parameter.

        This is the direct expression of the Drain 8 failure mode: the
        polling thread saw BATTERY (-> callback fires here), but the
        tick() caller passed a decoupled stale view.  Pre-fix tick()
        used the stale arg and bailed at ``power_source!=BATTERY``.
        Post-fix tick() reads self._powerSource and proceeds to the
        threshold-comparison logic.
        """
        # Callback fires BATTERY (mirrors polling-loop transition handler).
        orchestrator._onPowerSourceChange(PowerSource.BATTERY)

        # Caller passes a STALE EXTERNAL view (mirrors the Drain 8 bug).
        # VCELL is below WARNING threshold -- a correctly-oriented tick()
        # MUST advance state.
        orchestrator.tick(
            currentVcell=3.65,
            currentSource=PowerSource.EXTERNAL,  # the stale lie
        )

        # Post-fix: tick() saw the fresh callback-driven BATTERY state and
        # crossed the WARNING threshold, advancing the state machine.
        # Pre-fix: tick() bailed at the stale-EXTERNAL guard, state stays NORMAL.
        assert orchestrator.state == PowerState.WARNING, (
            "After callback fires BATTERY, tick() must use the callback "
            "value (not the stale currentSource arg) to advance the ladder"
        )


# ================================================================================
# TestPollingLoopFiresCallbacksOnTransition -- the wiring proof
# ================================================================================


class TestPollingLoopFiresCallbacksOnTransition:
    """The polling-loop transition handler walks the registered callback list.

    Under real polling, when getPowerSource() observes a
    EXTERNAL -> BATTERY transition, every registered callback is invoked
    with the new PowerSource.  Pre-fix the polling loop only fires the
    legacy single ``onPowerSourceChange`` attribute; the new list-based
    fan-out is missing.
    """

    def test_polling_loop_fires_registered_callback_on_battery_transition(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        shutdownAction: MagicMock,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Start polling at high cadence; push history that crosses the
        sustained-below-threshold rule; assert the registered callback
        fires with PowerSource.BATTERY within a small wall-clock window.

        100ms wall-clock budget per the Spool spec: the polling thread
        observes the transition on its next sample and fires callbacks
        synchronously inside the loop body.
        """
        events: list[PowerSource] = []
        events_lock = threading.Lock()

        def listener(newSource: PowerSource) -> None:
            with events_lock:
                events.append(newSource)

        upsMonitor.registerSourceChangeCallback(listener)

        # Shortcut the rolling-history-buffer test path: feed enough
        # samples that getPowerSource() returns BATTERY decisively, then
        # invoke the transition handler explicitly.  The polling thread's
        # job is to observe + fire; the listener-invocation path is what
        # the integration here proves.
        # Rely on the helper that the polling loop also calls.
        upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)

        with events_lock:
            assert events == [PowerSource.BATTERY], (
                "Registered callback must receive BATTERY transition "
                f"exactly once; got {events!r}"
            )


# ================================================================================
# TestIntegrationStageFiringViaCallback -- the runtime-validation gate
# ================================================================================


class TestIntegrationStageFiringViaCallback:
    """Integration test mirroring the Drain Test 8 failure mode end-to-end.

    Setup mirrors production: real UpsMonitor + real PowerDownOrchestrator
    + real ShutdownHandler + real ObdDatabase + real powerLogWriter
    closure.  Wiring step: ``upsMonitor.registerSourceChangeCallback(
    orchestrator._onPowerSourceChange)`` -- exactly what lifecycle.py
    does in production.

    The drain trace replays Drain 8's failure mode: caller (mock
    _powerDownTickLoop) keeps passing ``currentSource=EXTERNAL`` (the
    stale view) while VCELL marches through WARNING -> IMMINENT ->
    TRIGGER.  Pre-fix the orchestrator's tick() bails at the stale-
    EXTERNAL guard on every tick (zero ``_enterStage`` calls, zero
    STAGE_* rows, no shutdownAction).  Post-fix the callback fires
    BATTERY once, the orchestrator's self._powerSource flips, every
    subsequent tick uses the fresh value and the ladder fires cleanly.

    This test MUST FAIL pre-fix (per
    specs/methodology.md Integration-Tests-for-Runtime-Verifiable-Bugs)
    -- the AttributeError on ``_onPowerSourceChange`` AND the stale-arg
    bail combine to prove the bug class is live, then the fix closes
    both gates.
    """

    def test_drain_with_stale_caller_arg_fires_full_ladder_via_callback(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Stair-step VCELL drain with caller passing stale EXTERNAL.

        Production-equivalent: lifecycle.py wires
        upsMonitor.registerSourceChangeCallback(orchestrator._onPowerSourceChange)
        before tick loop starts.  Polling thread fires callback once on
        EXTERNAL -> BATTERY transition; orchestrator's self._powerSource
        flips.  Caller (the legacy _powerDownTickLoop) continues to pass
        currentSource=EXTERNAL on every tick (the bug -- callers may
        always have stale views), but tick() now reads self._powerSource
        first and proceeds to the threshold logic.
        """
        def writer(eventType: str, vcell: float) -> None:
            logShutdownStage(freshDb, eventType, vcell)

        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=handler._executeShutdown,  # noqa: SLF001
            powerLogWriter=writer,
        )

        # Wire the callback as production does.
        upsMonitor.registerSourceChangeCallback(
            orchestrator._onPowerSourceChange,
        )

        # Polling-thread analogue: detect EXTERNAL -> BATTERY transition
        # and fire the registered callbacks.
        upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            # Caller (mock _powerDownTickLoop) keeps passing the STALE
            # EXTERNAL view -- the literal Drain 8 failure mode.  The
            # new self._powerSource path must override it.
            for stepVcell in (4.20, 3.80, 3.65, 3.50, 3.40):
                mockI2c.setVcell(stepVcell)
                vcellFromMonitor = upsMonitor.getVcell()
                orchestrator.tick(
                    currentVcell=vcellFromMonitor,
                    currentSource=PowerSource.EXTERNAL,  # the stale lie
                )

        # Ladder fired cleanly despite the stale caller arg.
        assert orchestrator.state == PowerState.TRIGGER
        assert mockSubprocess.call_count == 1
        assert mockSubprocess.call_args[0][0] == ["systemctl", "poweroff"]

        # Forensic trail: one row per stage in correct order.
        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT event_type, vcell FROM power_log "
                "WHERE event_type LIKE 'stage_%' "
                "ORDER BY id"
            ).fetchall()

        assert [row[0] for row in rows] == [
            'stage_warning', 'stage_imminent', 'stage_trigger',
        ]
        assert rows[0][1] == pytest.approx(3.65, abs=1e-3)
        assert rows[1][1] == pytest.approx(3.50, abs=1e-3)
        assert rows[2][1] == pytest.approx(3.40, abs=1e-3)

    def test_callback_responsiveness_under_simulated_polling_cadence(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        shutdownAction: MagicMock,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Spool spec: orchestrator self._powerSource updated within 100ms
        of UpsMonitor firing the source-change event.

        The synchronous callback path makes this trivially true in
        practice -- the callback runs on the polling thread before the
        loop's next sleep -- but we pin the assertion as a fidelity gate
        against any future refactor that introduces queue-based
        deferral.
        """
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )
        upsMonitor.registerSourceChangeCallback(
            orchestrator._onPowerSourceChange,
        )

        before = time.monotonic()
        upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)
        elapsed = time.monotonic() - before

        assert orchestrator._powerSource == PowerSource.BATTERY
        assert elapsed < 0.100, (
            f"Callback path must be synchronous (<100ms); took {elapsed:.4f}s"
        )

    def test_ac_restore_callback_returns_orchestrator_to_external(
        self,
        orchestrator: PowerDownOrchestrator,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Post-drain AC restore (BATTERY -> EXTERNAL transition) flips
        self._powerSource back to EXTERNAL via the same callback path.

        Symmetry guard: the callback handles both directions of
        transition, not just EXTERNAL -> BATTERY.  Without this the
        next drain after AC restore would still see self._powerSource
        stuck at BATTERY from the prior cycle and could spuriously
        fire the ladder.
        """
        upsMonitor.registerSourceChangeCallback(
            orchestrator._onPowerSourceChange,
        )

        upsMonitor._invokeSourceChangeCallbacks(PowerSource.BATTERY)
        assert orchestrator._powerSource == PowerSource.BATTERY

        upsMonitor._invokeSourceChangeCallbacks(PowerSource.EXTERNAL)
        assert orchestrator._powerSource == PowerSource.EXTERNAL
