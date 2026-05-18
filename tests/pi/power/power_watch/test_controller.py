################################################################################
# File Name: test_controller.py
# Purpose/Description: Tests: PowerWatch controller -- debounced
#                      sustained-on-battery confirmation, VCELL-floor backstop
#                      (successful read only), total-cap bound, power-return
#                      abort, and the 2026-05-18 bricking-loop regressions
#                      (transient BATTERY blip must NOT power off; a failed
#                      VCELL read must NOT immediately power off).
# Author: (implementation plan 2026-05-17)
# Creation Date: 2026-05-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author  | Description
# ================================================================================
# 2026-05-17    | Plan    | Initial -- P2-T4 controller tests.
# 2026-05-18    | Plan    | Rewritten for the debounced model (bricking hotfix).
# ================================================================================
################################################################################
from src.pi.power.power_watch.controller import PowerWatch


def _pw(**kw):
    base = dict(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: None,
        vcellFloor=3.40,
        totalCapSec=2.0,
        confirmWindowSec=0.0,  # no-debounce default for the simple cases
        confirmPollSec=0.0,
        sleepFn=lambda _s: None,
    )
    base.update(kw)
    return PowerWatch(**base)


def test_sustained_battery_runs_pipeline_then_powers_off():
    calls = []
    pw = _pw(
        isOnBattery=lambda: True,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert calls == ["pipeline", "poweroff"]


def test_vcell_floor_short_circuits_pipeline_when_confirmed():
    calls = []
    pw = _pw(
        isOnBattery=lambda: True,
        vcell=lambda: 3.30,  # successful low read, battery confirmed
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert calls == ["poweroff"]  # floor backstop, pipeline skipped


def test_power_return_during_pipeline_window_aborts():
    calls = []
    flips = iter([True, False])  # entry confirmed; post-window power back
    pw = _pw(
        isOnBattery=lambda: next(flips, False),
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert "poweroff" not in calls


def test_not_on_battery_at_entry_resumes():
    calls = []
    pw = _pw(
        isOnBattery=lambda: False,
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert calls == []


def test_transient_battery_blip_does_NOT_power_off():
    """THE 2026-05-18 bricking-bug regression. A BATTERY signal that does not
    hold through the confirm window (external power physically present, e.g.
    the boot VCELL sag) must NEVER reach the pipeline or poweroff."""
    calls = []
    seq = iter([True, False])  # on-battery at entry, gone on first re-poll
    clock = iter([0.0, 0.0])  # deadline = 0 + 20 = 20; first while-check at 0 < 20
    pw = _pw(
        isOnBattery=lambda: next(seq, False),
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        confirmWindowSec=20.0,
        confirmPollSec=5.0,
        monotonicFn=lambda: next(clock, 100.0),
    )
    pw.handleOnBattery()
    assert calls == []  # no pipeline, NO poweroff -- transient rejected


def test_sustained_through_real_confirm_window_proceeds():
    """Positive debounce: on-battery held across the whole confirm window ->
    real power loss -> proceed to pipeline + poweroff."""
    calls = []
    clock = iter([0.0, 0.0, 5.0, 11.0])  # deadline=10; loops at 0,5; exits at 11
    pw = _pw(
        isOnBattery=lambda: True,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        confirmWindowSec=10.0,
        confirmPollSec=5.0,
        monotonicFn=lambda: next(clock, 100.0),
    )
    pw.handleOnBattery()
    assert calls == ["pipeline", "poweroff"]


def test_failed_vcell_read_does_NOT_immediately_power_off():
    """Reversed direction (bricking hotfix): a failed VCELL read AFTER
    sustained battery is confirmed proceeds via the bounded pipeline then
    poweroff -- it must NOT be a bare instant floor->poweroff (that converted
    a boot-time I2C settle into an immediate self-poweroff)."""
    calls = []

    def _raise():
        raise OSError("i2c not ready (boot settle)")

    pw = _pw(
        isOnBattery=lambda: True,
        vcell=_raise,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
    )
    pw.handleOnBattery()
    assert calls == ["pipeline", "poweroff"]  # NOT ["poweroff"]
