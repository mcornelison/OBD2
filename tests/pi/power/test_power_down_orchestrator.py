################################################################################
# File Name: test_power_down_orchestrator.py
# Purpose/Description: Unit tests for PowerDownOrchestrator (US-216) --
#                      state machine transitions NORMAL -> WARNING@30 ->
#                      IMMINENT@25 -> TRIGGER@20 on a mocked drain, plus
#                      hysteresis, AC-restore cancellation, and stage-
#                      behavior callback firing.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- staged-shutdown state machine.
# ================================================================================
################################################################################

"""Unit tests for :mod:`src.pi.power.orchestrator.PowerDownOrchestrator`.

Tests drive the state machine via :meth:`PowerDownOrchestrator.tick` with
mocked SOC + ``PowerSource`` values, so they do not touch real hardware.
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
        warningSoc=30,
        imminentSoc=25,
        triggerSoc=20,
        hysteresisSoc=5,
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
    """SOC drops below each threshold -> state escalates."""

    def test_acPower_stays_normal_atAnySoc(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=5, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.state == PowerState.NORMAL

    def test_batteryAbove30_stays_normal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=50, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.NORMAL

    def test_batteryAt30_entersWarning(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING

    def test_batteryAt29_entersWarning(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING

    def test_warning_thenBatteryAt25_entersImminent(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.IMMINENT

    def test_imminent_thenBatteryAt20_entersTrigger(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=20, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.TRIGGER

    def test_triggerIsTerminal_furtherTicksIgnored(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=20, currentSource=PowerSource.BATTERY)
        shutdownCalls = orchestrator._shutdownAction.call_count  # noqa: SLF001
        orchestrator.tick(currentSoc=15, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=5, currentSource=PowerSource.BATTERY)
        # Shutdown action fires exactly once, even with further ticks below 20
        assert orchestrator._shutdownAction.call_count == shutdownCalls  # noqa: SLF001
        assert shutdownCalls == 1
        assert orchestrator.state == PowerState.TRIGGER

    def test_skipsIntermediateStatesWhenSocDropsFast(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """If one tick goes straight from 50 -> 18, fire all stages in order."""
        orchestrator.tick(currentSoc=50, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=18, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.TRIGGER
        orchestrator._onWarning.assert_called_once()  # noqa: SLF001
        orchestrator._onImminent.assert_called_once()  # noqa: SLF001
        orchestrator._shutdownAction.assert_called_once()  # noqa: SLF001


# ================================================================================
# Hysteresis
# ================================================================================


class TestHysteresis:
    """+hysteresisSoc gap prevents flap on 29/31 oscillation."""

    def test_warning_thenSocBackTo31_staysWarning(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """SOC 30 -> 31 should NOT de-escalate to NORMAL without +5% band."""
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING
        orchestrator.tick(currentSoc=31, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING

    def test_warning_thenOscillates29_31_firesWarningOnlyOnce(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=31, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=29, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=31, currentSource=PowerSource.BATTERY)
        # Warning action fired exactly once despite oscillation
        assert orchestrator._onWarning.call_count == 1  # noqa: SLF001

    def test_warning_thenSocClimbsTo35_deEscalatesToNormal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """SOC >= warningSoc + hysteresisSoc (35) -> de-escalate to NORMAL."""
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=35, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.NORMAL


# ================================================================================
# AC-restore cancellation
# ================================================================================


class TestAcRestore:
    """Power source BATTERY -> EXTERNAL during non-NORMAL cancels stages."""

    def test_warning_thenAcRestored_returnsToNormal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.WARNING
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.state == PowerState.NORMAL

    def test_imminent_thenAcRestored_returnsToNormal(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=24, currentSource=PowerSource.BATTERY)
        assert orchestrator.state == PowerState.IMMINENT
        orchestrator.tick(currentSoc=24, currentSource=PowerSource.EXTERNAL)
        assert orchestrator.state == PowerState.NORMAL

    def test_acRestore_firesAcRestoreCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.EXTERNAL)
        orchestrator._onAcRestore.assert_called_once()  # noqa: SLF001

    def test_acRestore_inNormal_doesNotFireCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """EXTERNAL tick while in NORMAL is a no-op (no callback)."""
        orchestrator.tick(currentSoc=90, currentSource=PowerSource.EXTERNAL)
        orchestrator._onAcRestore.assert_not_called()  # noqa: SLF001

    def test_acRestore_closesDrainEventAsRecovered(
        self,
        orchestrator: PowerDownOrchestrator,
        freshDb: ObdDatabase,
    ) -> None:
        """AC restore closes battery_health_log row with notes='recovered'."""
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
        drainId = orchestrator.activeDrainEventId
        assert drainId is not None
        orchestrator.tick(currentSoc=32, currentSource=PowerSource.EXTERNAL)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc "
                f"FROM {BATTERY_HEALTH_LOG_TABLE} "
                f"WHERE drain_event_id = ?",
                (drainId,),
            ).fetchone()
        assert row[0] is not None  # end_timestamp written
        assert row[1] == 32.0  # end_soc

    def test_acRestoreThenFreshDrain_firesWarningAgain(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        """After AC restore, next battery drop below 30 fires WARNING again."""
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=40, currentSource=PowerSource.EXTERNAL)
        orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
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
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        with freshDb.connect() as conn:
            rows = conn.execute(
                f"SELECT drain_event_id, start_soc, end_timestamp "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == 30.0  # start_soc
        assert rows[0][2] is None  # end_timestamp not yet set

    def test_warning_firesOnWarningCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator._onWarning.assert_called_once()  # noqa: SLF001

    def test_imminent_firesOnImminentCallback(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        orchestrator._onImminent.assert_called_once()  # noqa: SLF001

    def test_trigger_closesBatteryHealthLogRow(
        self,
        orchestrator: PowerDownOrchestrator,
        freshDb: ObdDatabase,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=20, currentSource=PowerSource.BATTERY)
        with freshDb.connect() as conn:
            row = conn.execute(
                f"SELECT end_timestamp, end_soc "
                f"FROM {BATTERY_HEALTH_LOG_TABLE}"
            ).fetchone()
        assert row[0] is not None
        assert row[1] == 20.0

    def test_trigger_callsShutdownActionExactlyOnce(
        self, orchestrator: PowerDownOrchestrator,
    ) -> None:
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=20, currentSource=PowerSource.BATTERY)
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
            warningSoc=30,
            imminentSoc=25,
            triggerSoc=20,
            hysteresisSoc=5,
        )
        shutdownAction = MagicMock()
        onWarning = MagicMock()
        orchestrator = PowerDownOrchestrator(
            thresholds=thresholds,
            batteryHealthRecorder=recorder,
            shutdownAction=shutdownAction,
            onWarning=onWarning,
        )
        orchestrator.tick(currentSoc=10, currentSource=PowerSource.BATTERY)
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
        orchestrator.tick(currentSoc=30, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=25, currentSource=PowerSource.BATTERY)
        orchestrator.tick(currentSoc=20, currentSource=PowerSource.BATTERY)
        shutdownAction.assert_called_once()
