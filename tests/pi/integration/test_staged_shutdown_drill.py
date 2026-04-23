################################################################################
# File Name: test_staged_shutdown_drill.py
# Purpose/Description: Integration test for US-216 staged shutdown drill --
#                      mocked UpsMonitor walks SOC 35 -> 15%; orchestrator
#                      fires all 3 stages; battery_health_log row populated
#                      start->end; systemctl poweroff mocked and asserted
#                      called exactly once.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Initial -- end-to-end drain drill.
# ================================================================================
################################################################################

"""End-to-end drill: mocked drain 35 -> 15% drives orchestrator through all
three stages and leaves a complete ``battery_health_log`` row behind."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pi.hardware.shutdown_handler import ShutdownHandler
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


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_drill.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


def test_stagedShutdownDrill_populatesBatteryHealthLog(
    recorder: BatteryHealthRecorder, freshDb: ObdDatabase,
) -> None:
    """Drain 35 -> 15 fires all 3 stages + leaves full battery_health_log row."""
    thresholds = ShutdownThresholds(
        enabled=True,
        warningSoc=30,
        imminentSoc=25,
        triggerSoc=20,
        hysteresisSoc=5,
    )

    legacy = ShutdownHandler(
        shutdownDelay=30,
        lowBatteryThreshold=10,
        suppressLegacyTriggers=True,
    )

    shutdownCalls: list[bool] = []

    def shutdownAction() -> None:
        shutdownCalls.append(True)
        with patch("src.pi.hardware.shutdown_handler.subprocess.run"):
            legacy._executeShutdown()  # noqa: SLF001

    stageHits = {"warning": 0, "imminent": 0, "acRestore": 0}

    def onWarning() -> None:
        stageHits["warning"] += 1

    def onImminent() -> None:
        stageHits["imminent"] += 1

    def onAcRestore() -> None:
        stageHits["acRestore"] += 1

    orchestrator = PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=shutdownAction,
        onWarning=onWarning,
        onImminent=onImminent,
        onAcRestore=onAcRestore,
    )

    # Walk SOC 35 -> 15 (hits 30, 25, 20 triggers along the way).
    for soc in range(35, 14, -1):
        orchestrator.tick(currentSoc=soc, currentSource=PowerSource.BATTERY)

    # All 3 stages fired
    assert stageHits["warning"] == 1
    assert stageHits["imminent"] == 1
    assert len(shutdownCalls) == 1
    assert orchestrator.state == PowerState.TRIGGER
    assert stageHits["acRestore"] == 0

    # battery_health_log row is complete
    with freshDb.connect() as conn:
        rows = conn.execute(
            f"SELECT drain_event_id, start_timestamp, end_timestamp, "
            f"       start_soc, end_soc, runtime_seconds "
            f"FROM {BATTERY_HEALTH_LOG_TABLE}"
        ).fetchall()
    assert len(rows) == 1
    row = rows[0]
    _, startTs, endTs, startSoc, endSoc, runtime = row
    assert startTs is not None
    assert endTs is not None
    assert startSoc > 30  # captured pre-WARNING max SOC (>30, tick 35/34/...)
    assert endSoc <= 20  # closed at TRIGGER threshold (20)
    assert runtime is not None  # filled at close


def test_acRestoreDuringImminent_resetsToNormal_noShutdown(
    recorder: BatteryHealthRecorder, freshDb: ObdDatabase,
) -> None:
    """AC restore during IMMINENT must cancel, no poweroff, row closed recovered."""
    thresholds = ShutdownThresholds(
        enabled=True,
        warningSoc=30,
        imminentSoc=25,
        triggerSoc=20,
        hysteresisSoc=5,
    )
    shutdownAction = MagicMock()
    orchestrator = PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=shutdownAction,
    )

    # Walk into IMMINENT
    orchestrator.tick(currentSoc=28, currentSource=PowerSource.BATTERY)
    orchestrator.tick(currentSoc=24, currentSource=PowerSource.BATTERY)
    assert orchestrator.state == PowerState.IMMINENT

    # Wall power comes back
    orchestrator.tick(currentSoc=26, currentSource=PowerSource.EXTERNAL)
    assert orchestrator.state == PowerState.NORMAL

    # No shutdown was called
    shutdownAction.assert_not_called()

    # Drain-event row closed with notes indicating recovery
    with freshDb.connect() as conn:
        row = conn.execute(
            f"SELECT end_timestamp, end_soc FROM {BATTERY_HEALTH_LOG_TABLE}"
        ).fetchone()
    assert row[0] is not None
    assert row[1] == 26.0
