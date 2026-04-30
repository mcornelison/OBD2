################################################################################
# File Name: test_orchestrator_vcell_thresholds.py
# Purpose/Description: US-234 synthetic test that EXPOSES the Sprint 18
#                      production failure mode: MAX17048 SOC% reports a
#                      mis-calibrated 60% throughout a real drain that
#                      drops VCELL from 4.20V to 3.40V. The OLD SOC%-based
#                      ladder NEVER fires (SOC 60% never crosses warningSoc=30).
#                      The NEW VCELL-based ladder fires all 3 stages. Mocks
#                      operate at the I2C readWord level (MAX17048 chip-read
#                      level) per the new feedback_runtime_validation_required
#                      rule, NOT at UpsMonitor.getPowerSource() level which
#                      would bypass the bug class.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-234) | Initial -- VCELL stair-step drain synthetic
#                              | test that fails against pre-US-234 SOC%-based
#                              | orchestrator code per story stop-condition
#                              | "STOP if synthetic test passes against the OLD
#                              | SOC%-based code".
# ================================================================================
################################################################################

"""US-234 VCELL threshold synthetic test (the runtime-validation-required gate).

Discriminator design
--------------------
Across 4 drain tests over 9 days, the Pi hard-crashed every time at
VCELL 3.36-3.45V while MAX17048 SOC% was still reporting 57-63%. The
SOC%-based ladder shipped in Sprint 16 (warning 30 / imminent 25 /
trigger 20) NEVER fired -- SOC was always > 30. This test reproduces
that exact production state:

* MAX17048 VCELL register stair-steps 4.20V -> 3.40V across mocked time.
* MAX17048 SOC register STAYS PINNED AT 60% throughout the drain (the
  mis-calibration failure mode).
* MAX17048 CRATE register returns 0xFFFF (disabled, the in-the-wild
  state on this chip variant).

If this test were to pass against the pre-US-234 SOC%-based orchestrator,
the test would not be strong enough -- a 60% SOC reading never crosses
the old warningSoc=30 threshold so no stage would fire, no
battery_health_log row would land, and no shutdownAction would be called.
The test passing here proves the NEW VCELL-based orchestrator catches
the actual bug class.

Fidelity
--------
Mocks operate at :class:`I2cClient.readWord` -- the actual MAX17048
chip-read entry point. The real :class:`UpsMonitor` does the byte-swap
+ scale + history buffering. The orchestrator consumes
``monitor.getVcell()`` (real I2C path) and ``PowerSource.BATTERY``
(orthogonal control variable; US-235 fixes BATTERY-detection in a
parallel story).

The systemctl poweroff assertion routes through a real
:class:`ShutdownHandler` so the chain orchestrator -> handler ->
``subprocess.run(['systemctl', 'poweroff'])`` is exercised end-to-end
just as production runs it.
"""

from __future__ import annotations

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
from src.pi.power.battery_health import (
    BATTERY_HEALTH_LOG_TABLE,
    BatteryHealthRecorder,
)
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)

# ================================================================================
# Mock I2C client — MAX17048 chip-read fidelity
# ================================================================================

# MAX17048 stores VCELL big-endian on the wire; SMBus read_word_data
# returns little-endian. The real byte-swap happens inside UpsMonitor;
# this mock returns the LITTLE-ENDIAN value SMBus would return so the
# real swap produces the desired chip-order word.
_VCELL_LSB_V = 78.125e-6

# 60% SOC pinned across the drain — the production mis-calibration that
# caused 4 drain tests to silently bypass the SOC%-based ladder.
_SOC_PINNED_PCT = 60


def _vcellWordLittleEndian(volts: float) -> int:
    """Encode a VCELL voltage as the little-endian word SMBus would return.

    UpsMonitor's `_byteSwap16` reverses this back to chip order
    (big-endian) and applies the 78.125 µV/LSB scale. So volts -> raw
    -> swap-to-LE-for-SMBus mocks the real wire path.
    """
    raw = int(round(volts / _VCELL_LSB_V))
    bigEndian = raw & 0xFFFF
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    """Encode a SOC% as the little-endian word SMBus would return.

    UpsMonitor reads the high byte of the chip-order word as integer
    percent. Putting `percent` in the high byte of a big-endian word and
    swapping for SMBus' LE order puts it in the low byte of the LE word.
    """
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class _MockI2cClient:
    """Drop-in I2cClient for UpsMonitor with scriptable VCELL/SOC reads.

    Implements only :meth:`readWord` (the only I2C op UpsMonitor uses).
    Address is unused -- UpsMonitor calls with self._address always.
    """

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
        # VERSION / CONFIG / MODE -- not exercised in this test.
        return 0x0000

    def close(self) -> None:
        pass


# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_us234_thresholds.db"), walMode=False)
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
    """Mock I2C client starting at full charge (4.20V), SOC pinned 60%."""
    return _MockI2cClient(vcellVolts=4.20)


@pytest.fixture()
def upsMonitor(mockI2c: _MockI2cClient) -> UpsMonitor:
    """Real UpsMonitor wired to the mock I2C client."""
    return UpsMonitor(i2cClient=mockI2c)


# ================================================================================
# Discriminator-class tests
# ================================================================================


class TestVcellStairStepFiresAllStages:
    """Stair-step VCELL drain 4.20 -> 3.40V fires WARNING, IMMINENT, TRIGGER
    in order while SOC% stays pinned at 60% (the production failure mode)."""

    def test_drain_4_20_to_3_40_fires_warning_imminent_trigger_in_order(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        stageOrder: list[str] = []

        def onWarning() -> None:
            stageOrder.append("warning")

        def onImminent() -> None:
            stageOrder.append("imminent")

        # ShutdownHandler with the legacy 10% trigger suppressed (per
        # US-216) so the only path to systemctl poweroff is via the
        # orchestrator's TRIGGER stage.
        handler = ShutdownHandler(
            shutdownDelay=30,
            lowBatteryThreshold=10,
            suppressLegacyTriggers=True,
        )
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=handler._executeShutdown,  # noqa: SLF001
            onWarning=onWarning,
            onImminent=onImminent,
        )

        # Stair-step the VCELL register down across 5 ticks. SOC stays
        # pinned at 60% (the production mis-calibration). At each step,
        # read VCELL through the REAL UpsMonitor (mocked at I2C level)
        # and feed orchestrator.tick. Wrap in patch so the TRIGGER
        # stage's systemctl poweroff is captured rather than executed.
        with patch(
            "src.pi.hardware.shutdown_handler.subprocess.run"
        ) as mockSubprocess:
            for stepVcell in (4.20, 3.80, 3.65, 3.50, 3.40):
                mockI2c.setVcell(stepVcell)
                # Real chip read: SMBus little-endian word -> byte-swap ->
                # 78.125 µV/LSB scale -> volts. Same path production runs.
                vcellFromMonitor = upsMonitor.getVcell()
                # Sanity: the round-trip through I2C + scale must
                # reproduce the input within the 78.125 µV resolution.
                assert vcellFromMonitor == pytest.approx(stepVcell, abs=1e-3)
                # SOC stays pinned at 60% — confirmation that the bug
                # class is exercised: pre-US-234 SOC%-based code reads
                # 60% > warningSoc=30 and would skip every stage.
                assert upsMonitor.getBatteryPercentage() == _SOC_PINNED_PCT
                orchestrator.tick(
                    currentVcell=vcellFromMonitor,
                    currentSource=PowerSource.BATTERY,
                )

        # All three stage transitions in correct order.
        assert orchestrator.state == PowerState.TRIGGER
        assert stageOrder == ["warning", "imminent"]

        # Exactly one systemctl poweroff invocation, with the right cmd.
        # The handler's _executeShutdown is bound as the orchestrator's
        # shutdownAction so this is the real production cmd line.
        assert mockSubprocess.call_count == 1
        cmd = mockSubprocess.call_args[0][0]
        assert cmd == ["systemctl", "poweroff"]

    def test_battery_health_log_row_created_at_warning_with_start_vcell(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """At WARNING entry, battery_health_log row exists with start_vcell
        in the start_soc column (US-234 reused schema, see orchestrator
        module docstring) and end_timestamp NULL."""
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
        )

        # Pre-WARNING: tick at 4.10V on battery so the orchestrator's
        # _highestBatteryVcell tracking captures the true drain-start
        # VCELL (story acceptance: "battery_health_log row created at
        # WARNING with start_vcell column populated").
        mockI2c.setVcell(4.10)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )
        # Cross WARNING.
        mockI2c.setVcell(3.65)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )

        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT drain_event_id, start_soc, end_timestamp "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchall()

        assert len(rows) == 1
        # start_soc column carries VCELL volts post-US-234 (column unrenamed
        # per doNotTouch). Captured drain-start VCELL is the highest pre-
        # WARNING reading (4.10V), not the WARNING-crossing VCELL (3.65V).
        assert rows[0][1] == pytest.approx(4.10, abs=1e-3)
        assert rows[0][2] is None  # end_timestamp not yet set


# ================================================================================
# The bug-class proof: pinned-SOC% drain DOES fire stages now
# ================================================================================


class TestProductionFailureModeReproduced:
    """The 4-drain production failure mode: SOC stays high while VCELL
    crashes. Pre-US-234 the orchestrator never fired; post-US-234 it
    fires all three stages. This class exists to make the bug class
    explicit -- if it ever regresses the test name will surface why.
    """

    def test_soc_pinned_60pct_does_not_prevent_vcell_trigger(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """The whole point of US-234: a stuck-high SOC reading no longer
        prevents orchestrator from firing. Pre-US-234 with SOC=60% the
        old code never crossed warningSoc=30; with US-234 the VCELL
        path renders SOC% irrelevant to the trigger decision."""
        shutdownAction = MagicMock()
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
        )

        # SOC pinned 60 throughout. A pre-US-234 SOC%-based ladder would
        # see 60 > warningSoc=30 and skip every tick. US-234 reads
        # VCELL directly -- 3.40V <= triggerVcell=3.45V fires TRIGGER.
        for stepVcell in (4.20, 3.65, 3.50, 3.40):
            mockI2c.setVcell(stepVcell)
            assert upsMonitor.getBatteryPercentage() == _SOC_PINNED_PCT
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )

        assert orchestrator.state == PowerState.TRIGGER
        shutdownAction.assert_called_once()
