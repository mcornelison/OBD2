################################################################################
# File Name: test_controller.py
# Purpose/Description: Tests: ShutdownSequencer controller (renamed from
#                      PowerWatch in SS-T5) -- smoothed
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
# 2026-05-19    | Plan SS-T5 | Renamed class PowerWatch -> ShutdownSequencer +
#                              ctor params confirm* -> smoothing*; semantics
#                              unchanged (the SS-T2 debounce IS the spec sec 3
#                              smoothing).
# ================================================================================
################################################################################
from src.pi.power.power_watch.controller import ShutdownSequencer


def _pw(**kw):
    base = dict(
        isOnBattery=lambda: True,
        vcell=lambda: 3.9,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: None,
        vcellFloor=3.40,
        totalCapSec=2.0,
        smoothingSec=0.0,  # no-smoothing default for the simple cases
        smoothingPollSec=0.0,
        sleepFn=lambda _s: None,
    )
    base.update(kw)
    return ShutdownSequencer(**base)


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
    hold through the smoothing window (external power physically present,
    e.g. an electrical blip on the GPIO6 line) must NEVER reach the pipeline
    or poweroff."""
    calls = []
    seq = iter([True, False])  # on-battery at entry, gone on first re-poll
    clock = iter([0.0, 0.0])  # deadline = 0 + 20 = 20; first while-check at 0 < 20
    pw = _pw(
        isOnBattery=lambda: next(seq, False),
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        smoothingSec=20.0,
        smoothingPollSec=5.0,
        monotonicFn=lambda: next(clock, 100.0),
    )
    pw.handleOnBattery()
    assert calls == []  # no pipeline, NO poweroff -- transient rejected


def test_sustained_through_real_confirm_window_proceeds():
    """Positive smoothing: on-battery held across the whole smoothing window
    -> real power loss -> proceed to pipeline + poweroff."""
    calls = []
    clock = iter([0.0, 0.0, 5.0, 11.0])  # deadline=10; loops at 0,5; exits at 11
    pw = _pw(
        isOnBattery=lambda: True,
        runPipelineFn=lambda: calls.append("pipeline"),
        powerOffFn=lambda: calls.append("poweroff"),
        smoothingSec=10.0,
        smoothingPollSec=5.0,
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


# SS-T5: rename PowerWatch -> ShutdownSequencer; confirm* -> smoothing*. The
# pre-rename test below FAILS (ShutdownSequencer absent, smoothingSec absent),
# turns GREEN after T5 lands; the test then doubles as a regression-net that
# the canonical class name + smoothing* params stay stable (spec sec 3
# safety-property naming).
def test_shutdownSequencer_blipRejectedBySmoothing_noPoweroff():
    """Spec sec 3 / plan Task 5 Step 1. A power-LOST blip that recovers
    inside the smoothing window must NEVER fire the shutdown window. This
    is the in-V1 safety property that prevents the 2026-05-18 bricking
    loop class. After T5: the class is ShutdownSequencer; the param is
    smoothingSec (validated config); the trigger comes from the
    PowerSourceProvider SSOT via __main__.py's wiring."""
    from src.pi.power.power_watch.controller import ShutdownSequencer
    calls = {"off": 0}
    seq = ShutdownSequencer(
        isOnBattery=iter([True, False]).__next__,  # blip then recovered
        vcell=lambda: 3.9,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: calls.__setitem__("off", calls["off"] + 1),
        vcellFloor=3.50, totalCapSec=45,
        smoothingSec=5, smoothingPollSec=0,
        sleepFn=lambda _s: None,
    )
    seq.handleOnBattery()
    assert calls["off"] == 0  # blip => never powered off
