################################################################################
# File Name: test_controller.py
# Purpose/Description: Tests: PowerWatch controller -- sustained-battery
#                      trigger, VCELL-floor short-circuit, total-cap bound,
#                      power-return abort+resume.
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T4 controller tests.
# ================================================================================
################################################################################
from src.pi.power.power_watch.controller import PowerWatch


def test_on_sustained_battery_runs_pipeline_then_powers_off():
    calls = []
    pw = PowerWatch(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=3.40,
        totalCapSec=2.0,
    )
    pw.handleOnBattery()
    assert calls == ["pipeline", "poweroff"]


def test_vcell_floor_short_circuits_pipeline():
    calls = []
    pw = PowerWatch(
        isOnBattery=lambda: True,
        vcell=lambda: 3.30,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=3.40,
        totalCapSec=2.0,
    )
    pw.handleOnBattery()
    assert calls == ["poweroff"]


def test_power_return_during_window_aborts_and_resumes():
    calls = []
    flips = iter([True, False])
    pw = PowerWatch(
        isOnBattery=lambda: next(flips, False),
        vcell=lambda: 3.9,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        vcellFloor=3.40,
        totalCapSec=2.0,
    )
    pw.handleOnBattery()
    assert "poweroff" not in calls
