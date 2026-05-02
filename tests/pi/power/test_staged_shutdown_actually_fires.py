################################################################################
# File Name: test_staged_shutdown_actually_fires.py
# Purpose/Description: US-252 runtime-validation-required gate -- the synthetic
#                      proof that the staged-shutdown ladder ACTUALLY FIRES
#                      end-to-end across a stair-step VCELL drain.  Across 5
#                      drain tests over 3 weeks (Sprints 17/18/20 + post-deploy
#                      drains 1-5) the Pi hard-crashed at the LiPo discharge
#                      knee because tick() was coupled to _displayUpdateLoop,
#                      which only ran when StatusDisplay succeeded.  US-252
#                      decouples tick() to a dedicated thread AND wires a
#                      power_log writer so each stage transition leaves a
#                      forensic row.  Mocks operate at I2cClient.readWord level
#                      (MAX17048 chip-read entry point) per
#                      feedback_runtime_validation_required.md, NOT at
#                      PowerDownOrchestrator.fireWarning level which would
#                      bypass the bug class.
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex (US-252) | Initial -- runtime-validation-required gate
#                              | for the staged-shutdown ladder.  Mocks at
#                              | I2cClient.readWord (chip-read fidelity);
#                              | exercises real UpsMonitor + PowerDownOrchestrator
#                              | + ShutdownHandler + ObdDatabase + powerLogWriter
#                              | closure.  Discriminator: this test FAILS against
#                              | pre-US-252 code because (a) pre-US-252
#                              | orchestrator has no powerLogWriter parameter
#                              | so the power_log assertions never get rows and
#                              | (b) HardwareManager-level test fails pre-fix
#                              | because tick() was gated on _statusDisplay
#                              | being non-None.
# ================================================================================
################################################################################

"""US-252 staged-shutdown actually-fires synthetic test.

Acceptance gates (from sprint.json US-252):

* When VCELL crosses each threshold (downward), PowerDownOrchestrator
  fires the corresponding stage AND writes a row to power_log with
  event_type + vcell + timestamp.
* At TRIGGER (VCELL <= 3.45V), PowerDownOrchestrator calls
  ``subprocess.run(['systemctl', 'poweroff'])`` AND writes a final
  power_log row.
* Tests exist that mock I2cClient.readWord with stair-step VCELL trace
  4.20V -> 3.40V; assert all 3 stages fire; assert power_log rows
  written; assert subprocess mock called exactly once at TRIGGER.

Discriminator design
--------------------
The bug that survived 5 drain tests across 3 weeks was NOT a logic
error in the orchestrator -- the ladder's state machine is correct
(US-216 + US-234 already passed similar threshold tests).  The bug was
a **lifecycle coupling**: ``_displayUpdateLoop`` was the only caller of
``orchestrator.tick``, and it only spawned when ``StatusDisplay``
successfully initialized.  A pygame fault, a missing HDMI cable, or
``pi.hardware.statusDisplay.enabled=false`` silently disabled the
safety ladder.

The two test classes here close the gap from different angles:

* :class:`TestStagedShutdownActuallyFires` exercises the orchestrator
  + powerLogWriter integration with a real DB + real UpsMonitor + real
  ShutdownHandler.  Its discriminator is the power_log assertions:
  pre-US-252 the orchestrator has no powerLogWriter parameter, so the
  rows never land regardless of state-machine correctness.

* :class:`TestPowerDownTickThreadDecoupledFromDisplay` is the
  architectural proof.  It builds a HardwareManager with the display
  disabled and asserts the orchestrator still ticks.  Pre-US-252 this
  test FAILS because tick() rode on _displayUpdateLoop which never
  spawned without a display.
"""

from __future__ import annotations

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
# Mock I2C client -- MAX17048 chip-read fidelity (mirrors US-234 test)
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
        self.readWordCalls: list[tuple[int, int]] = []

    def setVcell(self, volts: float) -> None:
        self.vcellVolts = volts

    def readWord(self, address: int, register: int) -> int:
        self.readWordCalls.append((address, register))
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
    db = ObdDatabase(str(tmp_path / "test_us252_actually_fires.db"), walMode=False)
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


# ================================================================================
# TestStagedShutdownActuallyFires -- the runtime-validation-required gate
# ================================================================================


class TestStagedShutdownActuallyFires:
    """Mock I2cClient.readWord with stair-step trace 4.20 -> 3.40 V across
    mocked ticks; assert all 3 stages fire, power_log gains stage rows
    with vcell populated, subprocess.run called exactly once at TRIGGER.

    This is the runtime-validation-required gate.  Pre-US-252 the
    orchestrator has no ``powerLogWriter`` parameter, so the power_log
    row assertions cannot pass.
    """

    def _buildOrchestrator(
        self,
        *,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        shutdownAction: object,
    ) -> PowerDownOrchestrator:
        def writer(eventType: str, vcell: float) -> None:
            logShutdownStage(freshDb, eventType, vcell)

        return PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
            powerLogWriter=writer,
        )

    def test_drain_4_20_to_3_40_writes_three_stage_rows_to_power_log(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Stair-step drain fires WARNING/IMMINENT/TRIGGER and each stage
        leaves a power_log row with the correct event_type + vcell."""
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator = self._buildOrchestrator(
            thresholds=thresholds,
            recorder=recorder,
            freshDb=freshDb,
            shutdownAction=handler._executeShutdown,  # noqa: SLF001
        )

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            for stepVcell in (4.20, 3.80, 3.65, 3.50, 3.40):
                mockI2c.setVcell(stepVcell)
                vcellFromMonitor = upsMonitor.getVcell()
                assert vcellFromMonitor == pytest.approx(stepVcell, abs=1e-3)
                orchestrator.tick(
                    currentVcell=vcellFromMonitor,
                    currentSource=PowerSource.BATTERY,
                )

        assert orchestrator.state == PowerState.TRIGGER
        assert mockSubprocess.call_count == 1
        assert mockSubprocess.call_args[0][0] == ["systemctl", "poweroff"]

        # power_log forensic trail: one row per stage in order.
        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT event_type, power_source, on_ac_power, vcell "
                "FROM power_log "
                "WHERE event_type IN ('stage_warning','stage_imminent','stage_trigger') "
                "ORDER BY id"
            ).fetchall()

        assert len(rows) == 3
        assert [row[0] for row in rows] == [
            'stage_warning', 'stage_imminent', 'stage_trigger',
        ]
        # Every stage row records the LiPo cell voltage at threshold
        # crossing -- vcell column is populated, not NULL.
        for row in rows:
            assert row[1] == 'battery'
            assert row[2] == 0
            assert row[3] is not None

        # The vcell value at each stage matches the drain step that
        # crossed the threshold.  WARNING fires at <=3.70V (step 3.65),
        # IMMINENT at <=3.55V (step 3.50), TRIGGER at <=3.45V (step 3.40).
        assert rows[0][3] == pytest.approx(3.65, abs=1e-3)
        assert rows[1][3] == pytest.approx(3.50, abs=1e-3)
        assert rows[2][3] == pytest.approx(3.40, abs=1e-3)

    def test_power_log_only_gains_stage_rows_during_battery_drain(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """A drain that never crosses WARNING leaves no stage rows.

        Sanity gate: the writer must not fabricate rows.  This proves the
        powerLogWriter is wired off the actual stage-transition path,
        not a misplaced unconditional log on every tick.
        """
        orchestrator = self._buildOrchestrator(
            thresholds=thresholds,
            recorder=recorder,
            freshDb=freshDb,
            shutdownAction=MagicMock(),
        )

        # Drain stops at 3.80V -- above WARNING (3.70).
        for stepVcell in (4.20, 4.00, 3.85, 3.80):
            mockI2c.setVcell(stepVcell)
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )

        assert orchestrator.state == PowerState.NORMAL

        with freshDb.connect() as conn:
            rows = conn.execute(
                "SELECT COUNT(*) FROM power_log "
                "WHERE event_type LIKE 'stage_%'"
            ).fetchone()
        assert rows[0] == 0

    def test_subprocess_poweroff_called_exactly_once_at_trigger(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Even with multiple ticks past TRIGGER, subprocess.run is
        invoked exactly once.  TRIGGER is terminal -- subsequent ticks
        must not re-fire poweroff."""
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator = self._buildOrchestrator(
            thresholds=thresholds,
            recorder=recorder,
            freshDb=freshDb,
            shutdownAction=handler._executeShutdown,  # noqa: SLF001
        )

        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            for stepVcell in (4.20, 3.65, 3.50, 3.40, 3.36, 3.32):
                mockI2c.setVcell(stepVcell)
                orchestrator.tick(
                    currentVcell=upsMonitor.getVcell(),
                    currentSource=PowerSource.BATTERY,
                )

        assert mockSubprocess.call_count == 1
        assert orchestrator.state == PowerState.TRIGGER


# ================================================================================
# TestPowerDownTickThreadDecoupledFromDisplay -- the architectural proof
# ================================================================================


class TestPowerDownTickThreadDecoupledFromDisplay:
    """Proves the US-252 architectural fix: ladder thread runs whether
    or not the display initializes.

    Pre-US-252 the orchestrator's tick() was called from
    ``_displayUpdateLoop``, which only spawned when ``_statusDisplay``
    was non-None.  When pygame fails to init (production HDMI cable
    issue, software-renderer fault, or ``displayEnabled=False``), the
    safety ladder silently disabled.  US-252 introduces a dedicated
    ``_powerDownTickThread`` started whenever upsMonitor +
    powerDownOrchestrator are wired, regardless of display state.

    These tests exercise ``HardwareManager._powerDownTickLoop`` directly
    so they run on Windows / non-Pi without needing the I2C HAL.
    """

    def test_tick_loop_calls_orchestrator_tick_with_telemetry_values(self) -> None:
        """The new loop reads UpsMonitor.getTelemetry() and calls
        orchestrator.tick(currentVcell, currentSource) on each iteration."""
        from src.pi.hardware.hardware_manager import HardwareManager

        mockUps = MagicMock()
        mockUps.getTelemetry.return_value = {
            'voltage': 3.65,
            'percentage': 60,
            'powerSource': PowerSource.BATTERY,
        }

        mockOrch = MagicMock()
        manager = HardwareManager.__new__(HardwareManager)
        manager._upsMonitor = mockUps
        manager._powerDownOrchestrator = mockOrch
        manager._shutdownHandler = None
        manager._stopEvent = threading.Event()
        manager._pollInterval = 0.01
        # US-265 liveness state required by the tick loop entry log
        # + per-iteration health check.  The __new__ pattern bypasses
        # __init__ so test stubs MUST set the same attributes the
        # production loop reads.
        manager._tickHealthCheckIntervalS = 60.0
        manager._lastTickHealthCheckMono = time.monotonic()
        manager._lastTickHealthCheckCount = 0
        manager._lastTickHealthCheckOnBattery = False
        manager._tickHealthAlarmCount = 0

        # Run loop in background; stop after a few iterations.
        thread = threading.Thread(target=manager._powerDownTickLoop, daemon=True)
        thread.start()
        time.sleep(0.05)
        manager._stopEvent.set()
        thread.join(timeout=1.0)

        assert mockOrch.tick.call_count >= 1
        # All calls used the telemetry voltage + powerSource.
        for callArgs in mockOrch.tick.call_args_list:
            kwargs = callArgs.kwargs
            assert kwargs['currentVcell'] == pytest.approx(3.65, abs=1e-6)
            assert kwargs['currentSource'] == PowerSource.BATTERY

    def test_tick_loop_runs_without_status_display(self) -> None:
        """The bug class proof.  The tick loop must run even though
        ``_statusDisplay`` is None.  Pre-US-252 this scenario silently
        disabled the safety ladder."""
        from src.pi.hardware.hardware_manager import HardwareManager

        mockUps = MagicMock()
        mockUps.getTelemetry.return_value = {
            'voltage': 3.40,
            'percentage': 60,
            'powerSource': PowerSource.BATTERY,
        }
        mockOrch = MagicMock()

        manager = HardwareManager.__new__(HardwareManager)
        manager._upsMonitor = mockUps
        manager._statusDisplay = None  # the production failure mode
        manager._powerDownOrchestrator = mockOrch
        manager._shutdownHandler = None
        manager._stopEvent = threading.Event()
        manager._pollInterval = 0.01
        # US-265 liveness state required by the tick loop entry log
        # + per-iteration health check.
        manager._tickHealthCheckIntervalS = 60.0
        manager._lastTickHealthCheckMono = time.monotonic()
        manager._lastTickHealthCheckCount = 0
        manager._lastTickHealthCheckOnBattery = False
        manager._tickHealthAlarmCount = 0

        thread = threading.Thread(target=manager._powerDownTickLoop, daemon=True)
        thread.start()
        time.sleep(0.05)
        manager._stopEvent.set()
        thread.join(timeout=1.0)

        assert mockOrch.tick.called, (
            "Pre-US-252 regression: orchestrator.tick was never called "
            "because the ladder was coupled to the display loop"
        )

    def test_tick_loop_skips_orchestrator_when_voltage_unreadable(self) -> None:
        """Defensive: a telemetry read returning voltage=None must not
        feed garbage into orchestrator.tick.  Loop continues otherwise."""
        from src.pi.hardware.hardware_manager import HardwareManager

        mockUps = MagicMock()
        mockUps.getTelemetry.return_value = {
            'voltage': None,
            'percentage': 60,
            'powerSource': PowerSource.UNKNOWN,
        }
        mockOrch = MagicMock()

        manager = HardwareManager.__new__(HardwareManager)
        manager._upsMonitor = mockUps
        manager._powerDownOrchestrator = mockOrch
        manager._shutdownHandler = None
        manager._stopEvent = threading.Event()
        manager._pollInterval = 0.01
        # US-265 liveness state required by the tick loop entry log
        # + per-iteration health check.
        manager._tickHealthCheckIntervalS = 60.0
        manager._lastTickHealthCheckMono = time.monotonic()
        manager._lastTickHealthCheckCount = 0
        manager._lastTickHealthCheckOnBattery = False
        manager._tickHealthAlarmCount = 0

        thread = threading.Thread(target=manager._powerDownTickLoop, daemon=True)
        thread.start()
        time.sleep(0.05)
        manager._stopEvent.set()
        thread.join(timeout=1.0)

        assert mockOrch.tick.call_count == 0
