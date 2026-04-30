################################################################################
# File Name: test_power_down_orchestrator.py
# Purpose/Description: Unit tests for PowerDownOrchestrator (US-216 + US-234) --
#                      state machine transitions NORMAL -> WARNING@<=3.70V ->
#                      IMMINENT@<=3.55V -> TRIGGER@<=3.45V on a mocked drain,
#                      plus hysteresis (+0.05V), AC-restore cancellation, and
#                      stage-behavior callback firing.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- staged-shutdown state machine.
# 2026-04-29    | Rex (US-234) | Switched mocks from SOC% (currentSoc=) to
#                              | VCELL volts (currentVcell=). ShutdownThresholds
#                              | constructor uses warningVcell/imminentVcell/
#                              | triggerVcell/hysteresisVcell. battery_health_log
#                              | start_soc/end_soc columns now hold VCELL volts.
# ================================================================================
################################################################################

"""Unit tests for :mod:`src.pi.power.orchestrator.PowerDownOrchestrator`.

Tests drive the state machine via :meth:`PowerDownOrchestrator.tick` with
mocked VCELL + ``PowerSource`` values, so they do not touch real hardware.
US-234 switched the trigger source from MAX17048 SOC% to VCELL volts.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.pi.hardware.ups_monitor import PowerSource
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
# Fixtures
# ================================================================================


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_orchestrator.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


@pytest.fixture()
def defaultThresholds() -> ShutdownThresholds:
    return ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )


@pytest.fixture()
def orchestrator(
    defaultThresholds: ShutdownThresholds,
    recorder: BatteryHealthRecorder,
) -> PowerDownOrchestrator:
    """Default orchestrator with a mocked shutdown action."""
    return PowerDownOrchestrator(
        thresholds=defaultThresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=MagicMock(),
        onWarning=MagicMock(),
        onImminent=MagicMock(),
        onAcRestore=MagicMock(),
    )


# ================================================================================
# Initial state
# ================================================================================


class TestInitialState:
    """Orchestrator starts in NORMAL state."""

    def test_startsInNormalState(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        assert orchestrator.state == PowerState.NORMAL

    def test_noActiveDrainEventAtStart(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        assert orchestrator.activeDrainEventId is None


# ================================================================================
# Escalation transitions
# ================================================================================


class TestEscalation:
    """VCELL drops below each threshold -> state escalates."""

    def test_acPower_stays_normal_atAnyVcell(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.30, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.state == PowerState.NORMAL

    def test_batteryAbove370_stays_normal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.95, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.NORMAL

    def test_batteryAt370_entersWarning(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING

    def test_batteryAt369_entersWarning(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.69, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING

    def test_warning_thenBatteryAt355_entersImminent(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.IMMINENT

    def test_imminent_thenBatteryAt345_entersTrigger(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.TRIGGER

    def test_triggerIsTerminal_furtherTicksIgnored(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        shutdownCalls = orchestrator._shutdownAction.call_count  # noqa: SLF001
        orchestrator.tick(currentVcell=3.40, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.30, currentSource=PowerSource.BATTERY)
        # Shutdown action fires exactly once even with further ticks below trigger.
        assert orchestrator._shutdownAction.call_count == shutdownCalls  # noqa: SLF001
        assert shutdownCalls == 1
        assert orchestrator.state == PowerState.TRIGGER

    def test_skipsIntermediateStatesWhenVcellDropsFast(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """If one tick goes 4.00 -> 3.40, fire all stages in order."""
        orchestrator.tick(currentVcell=4.00, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.40, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.TRIGGER
        orchestrator._onWarning.assert_called_once()  # noqa: SLF001
        orchestrator._onImminent.assert_called_once()  # noqa: SLF001
        orchestrator._shutdownAction.assert_called_once()  # noqa: SLF001


# ================================================================================
# Hysteresis
# ================================================================================


class TestHysteresis:
    """+hysteresisVcell gap prevents flap on 3.69/3.71V oscillation."""

    def test_warning_thenVcellBackTo371_staysWarning(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """VCELL 3.70 -> 3.71 should NOT de-escalate without +0.05V band."""
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING
        orchestrator.tick(currentVcell=3.71, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING

    def test_warning_thenOscillates_369_371_firesWarningOnlyOnce(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.69, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.71, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.69, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.71, currentSource=PowerSource.BATTERY)
        # Warning action fired exactly once despite oscillation.
        assert orchestrator._onWarning.call_count == 1  # noqa: SLF001

    def test_warning_thenVcellClimbsTo375_deEscalatesToNormal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """VCELL >= warningVcell + hysteresisVcell (3.75) -> de-escalate."""
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.75, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.NORMAL


# ================================================================================
# AC-restore cancellation
# ================================================================================


class TestAcRestore:
    """Power source BATTERY -> EXTERNAL during non-NORMAL cancels stages."""

    def test_warning_thenAcRestored_returnsToNormal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.state == PowerState.NORMAL

    def test_imminent_thenAcRestored_returnsToNormal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.54, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.IMMINENT
        orchestrator.tick(currentVcell=3.54, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.state == PowerState.NORMAL

    def test_acRestore_firesAcRestoreCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.EXTERNAL)
        orchestrator._onAcRestore.assert_called_once()  # noqa: SLF001

    def test_acRestore_inNormal_doesNotFireCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """EXTERNAL tick while in NORMAL is a no-op (no callback)."""
        orchestrator.tick(currentVcell=4.10, currentSource=PowerSource.EXTERNAL)
        orchestrator._onAcRestore.assert_not_called()  # noqa: SLF001

    def test_acRestore_closesDrainEventAsRecovered(
        self,
        orchestrator: PowerDownOrchestrator,
        freshDb: ObdDatabase,
    ) -> None:
        """AC restore closes battery_health_log row with end_vcell stored."""
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
        drainId = orchestrator.activeDrainEventId
        assert drainId is not None
        orchestrator.tick(currentVcell=3.82, currentSource=PowerSource.EXTERNAL)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] is not None  # end_timestamp written
        # end_soc column carries VCELL volts post-US-234 (column unrenamed).
        assert row[1] == pytest.approx(3.82)

    def test_acRestoreThenFreshDrain_firesWarningAgain(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """After AC restore, next battery drop below 3.70V fires WARNING again."""
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.95, currentSource=PowerSource.EXTERNAL)
        orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
        assert orchestrator._onWarning.call_count == 2  # noqa: SLF001


# ================================================================================
# Stage-behavior callbacks + battery_health_log wiring
# ================================================================================


class TestStageBehaviors:
    """Each stage fires its callback and touches battery_health_log correctly."""

    def test_warning_opensBatteryHealthLogRow(
        self,
        orchestrator: PowerDownOrchestrator,
        freshDb: ObdDatabase,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT drain_event_id, start_soc, end_timestamp "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchall()
        assert len(rows) == 1
        # start_soc carries VCELL volts post-US-234 (schema unchanged).
        assert rows[0][1] == pytest.approx(3.70)
        assert rows[0][2] is None  # end_timestamp not yet set

    def test_warning_firesOnWarningCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator._onWarning.assert_called_once()  # noqa: SLF001

    def test_imminent_firesOnImminentCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator._onImminent.assert_called_once()  # noqa: SLF001

    def test_trigger_closesBatteryHealthLogRow(
        self,
        orchestrator: PowerDownOrchestrator,
        freshDb: ObdDatabase,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchone()
        assert row[0] is not None
        # end_soc carries VCELL volts post-US-234.
        assert row[1] == pytest.approx(3.45)

    def test_trigger_callsShutdownActionExactlyOnce(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        orchestrator._shutdownAction.assert_called_once()  # noqa: SLF001


# ================================================================================
# Disabled orchestrator
# ================================================================================


class TestDisabledByConfig:
    """When ShutdownThresholds.enabled=False, tick is a no-op."""

    def test_disabled_doesNotFireAnyStage(
        self,
        recorder: BatteryHealthRecorder,
    ) -> None:
        thresholds = ShutdownThresholds(
            enabled=False,
            warningVcell=3.70,
            imminentVcell=3.55,
            triggerVcell=3.45,
            hysteresisVcell=0.05,
        )
        shutdownAction = MagicMock()
        onWarning = MagicMock()
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
            onWarning=onWarning,
        )
        orchestrator.tick(currentVcell=3.20, currentSource=PowerSource.BATTERY)
        onWarning.assert_not_called()
        shutdownAction.assert_not_called()
        assert orchestrator.state == PowerState.NORMAL


# ================================================================================
# Callback error handling
# ================================================================================


class TestCallbackErrorIsolation:
    """A raising stage callback must not prevent state advancement or shutdown."""

    def test_onWarning_raises_stillAdvancesToImminent(
        self,
        defaultThresholds: ShutdownThresholds,
        recorder: BatteryHealthRecorder,
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("simulated callback failure")

        shutdownAction = MagicMock()
        orchestrator = PowerDownOrchestrator(
            thresholds=defaultThresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
            onWarning=boom,
        )
        orchestrator.tick(currentVcell=3.70, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.55, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentVcell=3.45, currentSource=PowerSource.BATTERY)
        shutdownAction.assert_called_once()
