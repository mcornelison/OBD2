################################################################################
# File Name: test_orchestrator_vcell_hysteresis.py
# Purpose/Description: US-234 hysteresis synthetic test. VCELL recovers from a
#                      WARNING state above warningVcell + hysteresisVcell
#                      (3.75V) and the orchestrator de-escalates to NORMAL,
#                      closing the battery_health_log row with the recovery
#                      VCELL stored. Mocks operate at I2C readWord per the
#                      runtime-validation-required fidelity rule.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-234) | Initial -- VCELL recovery (3.40 -> 3.80V) on
#                              | battery returns state to NORMAL via hysteresis
#                              | + closes battery_health_log row with end_vcell.
# ================================================================================
################################################################################

"""US-234 hysteresis synthetic test.

Scenario
--------
Cell drops to WARNING then recovers above warningVcell + hysteresisVcell
without the power-source flipping back to EXTERNAL (a momentary on-load
sag followed by load reduction). The orchestrator must:

1. Open a battery_health_log row at WARNING entry.
2. De-escalate to NORMAL once VCELL >= 3.70 + 0.05 = 3.75V.
3. Close the same battery_health_log row with end_vcell stored
   (column name is end_soc but post-US-234 the value is volts).

The hysteresis band must NOT de-escalate at exactly 3.71V (within
band) -- only at >= 3.75V.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

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
# I2C-level mock — matches test_orchestrator_vcell_thresholds.py fidelity
# ================================================================================

_VCELL_LSB_V = 78.125e-6


def _vcellWordLittleEndian(volts: float) -> int:
    raw = int(round(volts / _VCELL_LSB_V))
    bigEndian = raw & 0xFFFF
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


def _socWordLittleEndian(percent: int) -> int:
    bigEndian = (percent & 0xFF) << 8
    return ((bigEndian & 0xFF) << 8) | ((bigEndian >> 8) & 0xFF)


class _MockI2cClient:
    def __init__(self, vcellVolts: float, socPercent: int = 60):
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
    db = ObdDatabase(str(tmp_path / "test_us234_hysteresis.db"), walMode=False)
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
    return _MockI2cClient(vcellVolts=4.10)


@pytest.fixture()
def upsMonitor(mockI2c: _MockI2cClient) -> UpsMonitor:
    return UpsMonitor(i2cClient=mockI2c)


# ================================================================================
# Hysteresis behavior
# ================================================================================


class TestHysteresisRecovery:
    """VCELL recovery above warningVcell + hysteresisVcell de-escalates to NORMAL."""

    def test_warning_then_recovery_above_band_returns_to_normal(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        freshDb: ObdDatabase,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """3.65V (WARNING-only, > IMMINENT) -> 3.80V (above 3.75V band)
        -> NORMAL state + battery_health_log row closed with end_vcell."""
        recoveryFlags: list[bool] = []

        def onAcRestore() -> None:
            # Hysteresis recovery does NOT route through the AC-restore
            # callback (that fires only when source flips to EXTERNAL).
            # If this fires the test design is wrong.
            recoveryFlags.append(True)

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            onAcRestore=onAcRestore,
        )

        # Drain to WARNING-only (between IMMINENT 3.55V and WARNING 3.70V).
        # Pre-WARNING tick at 4.10V seeds the _highestBatteryVcell tracking.
        mockI2c.setVcell(4.10)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )
        mockI2c.setVcell(3.65)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )
        assert orchestrator.state == PowerState.WARNING

        drainEventId = orchestrator.activeDrainEventId
        assert drainEventId is not None

        # Recover above 3.75V hysteresis band, still on battery (load
        # reduction -- NOT an AC restore).
        mockI2c.setVcell(3.80)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )

        assert orchestrator.state == PowerState.NORMAL
        # Hysteresis recovery does NOT fire onAcRestore (that's only
        # for source-flips to EXTERNAL).
        assert recoveryFlags == []

        # battery_health_log row closed with end_vcell stored in end_soc column.
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainEventId,),
            ).fetchone()
        assert row[0] is not None
        assert row[1] == pytest.approx(3.80)

    def test_recovery_inside_band_does_not_de_escalate(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """3.65V (WARNING-only) -> 3.71V (inside hysteresis band, < 3.75V)
        -> state STAYS WARNING."""
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
        )

        mockI2c.setVcell(3.65)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )
        assert orchestrator.state == PowerState.WARNING

        # Inside band: 3.71 < 3.75 -> still WARNING.
        mockI2c.setVcell(3.71)
        orchestrator.tick(
            currentVcell=upsMonitor.getVcell(),
            currentSource=PowerSource.BATTERY,
        )
        assert orchestrator.state == PowerState.WARNING

    def test_oscillation_just_below_and_inside_band_fires_warning_once(
        self,
        thresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
        mockI2c: _MockI2cClient,
        upsMonitor: UpsMonitor,
    ) -> None:
        """Anti-flap: VCELL bounces 3.69 / 3.71 / 3.69 / 3.71 -- WARNING
        callback fires exactly ONCE despite four crossings of the
        threshold."""
        warningCount: list[int] = [0]

        def onWarning() -> None:
            warningCount[0] += 1

        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=MagicMock(),
            onWarning=onWarning,
        )

        for vcell in (3.69, 3.71, 3.69, 3.71):
            mockI2c.setVcell(vcell)
            orchestrator.tick(
                currentVcell=upsMonitor.getVcell(),
                currentSource=PowerSource.BATTERY,
            )

        assert warningCount[0] == 1
        assert orchestrator.state == PowerState.WARNING
