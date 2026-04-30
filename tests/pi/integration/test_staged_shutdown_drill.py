################################################################################
# File Name: test_staged_shutdown_drill.py
# Purpose/Description: Integration test for US-216 + US-234 staged shutdown
#                      drill -- mocked drain VCELL 3.80 -> 3.40V; orchestrator
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
# 2026-04-29    | Rex (US-234) | Drain mocks switched from SOC% (35 -> 15) to
#                              | VCELL volts (3.80 -> 3.40). battery_health_log
#                              | start_soc/end_soc columns now hold VCELL volts.
# ================================================================================
################################################################################

"""End-to-end drill: mocked drain 3.80V -> 3.40V drives orchestrator through
all three stages and leaves a complete ``battery_health_log`` row behind."""

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
    """Drain 3.80V -> 3.40V fires all 3 stages + leaves full battery_health_log row."""
    thresholds = ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
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

    # Walk VCELL 3.80 -> 3.40 in 0.01V steps (hits 3.70 / 3.55 / 3.45 along
    # the way).
    vcell = 3.80
    while vcell > 3.39:
        orchestrator.tick(
            currentVcell=round(vcell, 3),
            currentSource=PowerSource.BATTERY,
        )
        vcell -= 0.01

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
    _, startTs, endTs, startSocColumn, endSocColumn, runtime = row
    assert startTs is not None
    assert endTs is not None
    # start_soc + end_soc columns now hold VCELL volts post-US-234
    # (column rename deferred; see orchestrator module docstring).
    assert startSocColumn > 3.70  # captured pre-WARNING max VCELL
    assert endSocColumn <= 3.45  # closed at or below TRIGGER threshold
    assert runtime is not None  # filled at close


def test_acRestoreDuringImminent_resetsToNormal_noShutdown(
    recorder: BatteryHealthRecorder, freshDb: ObdDatabase,
) -> None:
    """AC restore during IMMINENT must cancel, no poweroff, row closed recovered."""
    thresholds = ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )
    shutdownAction = MagicMock()
    orchestrator = PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=shutdownAction,
    )

    # Walk into IMMINENT.
    orchestrator.tick(currentVcell=3.68, currentSource=PowerSource.BATTERY)
    orchestrator.tick(currentVcell=3.54, currentSource=PowerSource.BATTERY)
    assert orchestrator.state == PowerState.IMMINENT

    # Wall power comes back at 3.60V (still below WARNING but EXTERNAL ->
    # full reset).
    orchestrator.tick(currentVcell=3.60, currentSource=PowerSource.EXTERNAL)
    assert orchestrator.state == PowerState.NORMAL

    # No shutdown was called.
    shutdownAction.assert_not_called()

    # Drain-event row closed with end_soc holding the AC-restore VCELL.
    with freshDb.connect() as conn:
        row = conn.execute(
            f"SELECT end_timestamp, end_soc FROM {BATTERY_HEALTH_LOG_TABLE}"
        ).fetchone()
    assert row[0] is not None
    assert row[1] == pytest.approx(3.60)
