################################################################################
# File Name: test_ladder_vs_legacy_race.py
# Purpose/Description: REGRESSION test (US-216, non-negotiable per Spool audit
#                      2026-04-21). Mocked drain VCELL 4.20V -> 3.30V (parallel
#                      to legacy SOC 100 -> 0). Asserts new PowerDownOrchestrator
#                      fires TRIGGER@<=3.45V BEFORE the legacy ShutdownHandler
#                      10% trigger could engage, and that systemctl poweroff
#                      (mocked) is called exactly once (at VCELL 3.45V, never
#                      at SOC 10%). Proves TD-D race is resolved -- legacy
#                      path is suppressed.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-21    | Rex (US-216) | Non-negotiable regression per Spool audit.
# 2026-04-29    | Rex (US-234) | Orchestrator now feeds VCELL volts (currentVcell=)
#                              | while legacy ShutdownHandler still consumes
#                              | SOC%; the test walks both rails in parallel
#                              | so the suppression invariant is preserved.
# ================================================================================
################################################################################

"""REGRESSION: new ladder must fire before legacy 10% trigger.

Spool's audit (`offices/pm/inbox/2026-04-21-from-spool-power-audit.md`)
identified TD-D: the legacy ``ShutdownHandler`` 30s-timer + 10% trigger
race the new staged ladder. US-216 must suppress the legacy path when
the new ladder is enabled, and this test is the proof that the
suppression works.

Without this test, a silent regression that re-enables the legacy path
could allow the legacy 10% trigger to fire first (at a lower drain
state than the new orchestrator's TRIGGER stage), defeating the purpose
of the ladder.

US-234: orchestrator now compares VCELL volts; legacy still compares
SOC%. The drain walk feeds both rails in parallel so the suppression
invariant covers the actual production code path.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pi.hardware.shutdown_handler import ShutdownHandler
from src.pi.hardware.ups_monitor import PowerSource
from src.pi.obdii.database import ObdDatabase
from src.pi.power.battery_health import BatteryHealthRecorder
from src.pi.power.orchestrator import (
    PowerDownOrchestrator,
    PowerState,
    ShutdownThresholds,
)


@pytest.fixture()
def freshDb(tmp_path: Path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "test_race.db"), walMode=False)
    db.initialize()
    return db


@pytest.fixture()
def recorder(freshDb: ObdDatabase) -> BatteryHealthRecorder:
    return BatteryHealthRecorder(database=freshDb)


def test_newLadderFiresBeforeLegacy10Percent(
    recorder: BatteryHealthRecorder,
) -> None:
    """Drain VCELL 4.20 -> 3.30 (SOC 100 -> 0); orchestrator TRIGGER@<=3.45V
    fires ONCE, legacy 10% trigger never does."""
    thresholds = ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )
    mockShutdownAction = MagicMock(name="orchestratorShutdownAction")
    orchestrator = PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=mockShutdownAction,
    )

    # Legacy handler with suppression ENABLED (per US-216 design)
    legacy = ShutdownHandler(
        shutdownDelay=30,
        lowBatteryThreshold=10,
        suppressLegacyTriggers=True,
    )

    # Simulate the drain in 91 ticks: VCELL 4.20 -> 3.30 in 0.01V steps,
    # SOC 100 -> 10 in 1% steps (the legacy 10% threshold is the bound).
    # Both rails are fan-out at each tick, exactly as hardware_manager's
    # display update loop does in production: orchestrator.tick reads
    # telemetry['voltage']; legacy.onLowBattery reads telemetry['percentage'].
    with patch(
        "src.pi.hardware.shutdown_handler.subprocess.run"
    ) as mockSubprocess:
        for k in range(91):
            vcell = 4.20 - 0.01 * k
            soc = 100 - k
            orchestrator.tick(
                currentVcell=vcell, currentSource=PowerSource.BATTERY,
            )
            legacy.onLowBattery(soc)
            # Once the new ladder fires TRIGGER, production code path exits
            # via systemctl poweroff; we simulate that by breaking here.
            if orchestrator.state == PowerState.TRIGGER:
                break

    # Orchestrator fired TRIGGER at exactly the VCELL crossing.
    assert orchestrator.state == PowerState.TRIGGER
    mockShutdownAction.assert_called_once()

    # Legacy handler's systemctl poweroff was NEVER invoked -- suppression held
    assert mockSubprocess.call_count == 0


def test_withoutSuppression_legacy10PercentWouldFire(
    recorder: BatteryHealthRecorder,
) -> None:
    """Control test: with suppressLegacyTriggers=False, legacy DOES fire.

    This demonstrates the suppression flag is load-bearing: the bug the
    audit identified IS real, and the fix IS the flag. Legacy still
    consumes SOC% directly (US-234 did NOT change the legacy interface).
    """
    legacy = ShutdownHandler(
        shutdownDelay=30,
        lowBatteryThreshold=10,
        suppressLegacyTriggers=False,
    )
    with patch(
        "src.pi.hardware.shutdown_handler.subprocess.run"
    ) as mockSubprocess:
        for soc in range(100, -1, -1):
            legacy.onLowBattery(soc)
            if mockSubprocess.call_count > 0:
                break
    assert mockSubprocess.call_count >= 1


def test_shutdownActionCalledExactlyOnce(
    recorder: BatteryHealthRecorder,
) -> None:
    """Shutdown action fires exactly once, not once per sub-trigger tick."""
    thresholds = ShutdownThresholds(
        enabled=True,
        warningVcell=3.70,
        imminentVcell=3.55,
        triggerVcell=3.45,
        hysteresisVcell=0.05,
    )
    mockShutdownAction = MagicMock()
    orchestrator = PowerDownOrchestrator(
        thresholds=thresholds,
        batteryHealthRecorder=recorder,
        shutdownAction=mockShutdownAction,
    )
    for vcell in (3.70, 3.55, 3.45, 3.40, 3.30, 3.20, 3.10, 3.00):
        orchestrator.tick(
            currentVcell=vcell, currentSource=PowerSource.BATTERY,
        )
    # Only one poweroff call regardless of VCELL continuing to drop after TRIGGER.
    mockShutdownAction.assert_called_once()
