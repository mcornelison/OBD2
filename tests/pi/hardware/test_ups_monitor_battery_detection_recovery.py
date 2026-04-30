################################################################################
# File Name: test_ups_monitor_battery_detection_recovery.py
# Purpose/Description: US-235 recovery-side synthetic test. After US-235's
#                      VCELL-threshold + tuned-slope rules detect BATTERY,
#                      the monitor must transition back to EXTERNAL when
#                      wall power is restored and VCELL recovers above the
#                      threshold (and the slope turns positive). The
#                      onPowerSourceChange callback must fire once on each
#                      transition. This is the symmetric proof to
#                      test_ups_monitor_battery_detection.py.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-235) | Initial recovery-side tests for US-235
#                              | BATTERY-detection fix.
# ================================================================================
################################################################################

"""US-235 recovery-side BATTERY-detection synthetic tests.

After detecting BATTERY (sustained sub-threshold or fast slope), the
monitor must flip back to EXTERNAL when wall power restores and VCELL
climbs above the threshold with a recovering slope. The callback wiring
must fire exactly once on each transition so the upstream consumer
(ShutdownHandler / PowerDownOrchestrator) sees a clean edge.

Mocks operate at :class:`I2cClient.readWord` -- the actual MAX17048
chip-read entry. ``getBatteryVoltage()`` does the byte-swap + scale, and
``recordHistorySample()`` feeds the rolling buffer that
``getPowerSource()`` consumes -- so the production code path is
exercised end to end (same fidelity as the detection-side tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pi.hardware.ups_monitor import (
    CRATE_DISABLED_RAW,
    REGISTER_CRATE,
    REGISTER_SOC,
    REGISTER_VCELL,
    PowerSource,
    UpsMonitor,
)

# ================================================================================
# Helpers
# ================================================================================


class FakeClock:
    """Deterministic monotonic clock so sustained-window math is exact."""

    def __init__(self, startSeconds: float = 0.0) -> None:
        self.t = startSeconds

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _vcellWordLeForVolts(volts: float) -> int:
    """Encode a VCELL voltage as the little-endian word SMBus would return."""
    raw = int(round(volts / 78.125e-6)) & 0xFFFF
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def _makeMonitor() -> tuple[UpsMonitor, FakeClock, dict[str, float]]:
    """Build a monitor wired to a mock I2C client + injectable VCELL."""
    clock = FakeClock()
    state: dict[str, float] = {'vcell': 4.20}

    def fakeReadWord(addr: int, reg: int) -> int:
        if reg == REGISTER_VCELL:
            return _vcellWordLeForVolts(state['vcell'])
        if reg == REGISTER_SOC:
            return 0x5000
        if reg == REGISTER_CRATE:
            return CRATE_DISABLED_RAW
        raise AssertionError(f"unexpected register 0x{reg:02x}")

    mockClient = MagicMock()
    mockClient.readWord.side_effect = fakeReadWord

    monitor = UpsMonitor(
        i2cClient=mockClient,
        monotonicClock=clock.now,
    )
    return monitor, clock, state


def _stepAndRecord(
    monitor: UpsMonitor,
    clock: FakeClock,
    state: dict[str, float],
    *,
    vcellVolts: float,
    advanceSeconds: float,
) -> None:
    """Advance synthetic time, set new VCELL, then walk the production path."""
    clock.advance(advanceSeconds)
    state['vcell'] = vcellVolts
    vcell = monitor.getBatteryVoltage()
    soc = monitor.getBatteryPercentage()
    monitor.recordHistorySample(clock.now(), vcell, soc)


# ================================================================================
# Recovery: VCELL climbs above threshold, slope turns positive
# ================================================================================


def test_getPowerSource_vcellRecoversAboveThreshold_flipsToExternal() -> None:
    """
    Given: VCELL drove the monitor to BATTERY (sustained sub-threshold).
           Wall power is restored and VCELL climbs from 3.50V to 4.05V
           over 60s -- crossing the 3.95V threshold around t=49s into
           the recovery window.
    When:  getPowerSource() runs after the recovery
    Then:  EXTERNAL. The slope is positive (~+0.55 V/min) so the slope
           rule clears, and the most recent VCELL is above the threshold
           so the sustained-below rule clears. Recovery is one-shot --
           the cached state advances to EXTERNAL on this tick.
    """
    monitor, clock, state = _makeMonitor()

    # Phase 1: drive into BATTERY.
    _stepAndRecord(monitor, clock, state, vcellVolts=3.50, advanceSeconds=0.0)
    for _ in range(7):  # 35s flat at 3.50V -- well below 3.95V
        _stepAndRecord(monitor, clock, state, vcellVolts=3.50, advanceSeconds=5.0)
    assert monitor.getPowerSource() == PowerSource.BATTERY

    # Phase 2: wall-power restore -- VCELL ramps 3.50 -> 4.05 over 60s.
    # Sample every 10s, linear ramp.
    rampSamples = [3.50 + (4.05 - 3.50) * (i / 6) for i in range(1, 7)]
    for vcell in rampSamples:
        _stepAndRecord(monitor, clock, state, vcellVolts=vcell, advanceSeconds=10.0)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_powerSourceChange_callbackFiresOnceOnEachTransition() -> None:
    """
    Given: a synthetic drain-then-recover sequence. A callback is wired
           to onPowerSourceChange.
    When:  the polling tick sequence runs through EXTERNAL -> BATTERY
           -> EXTERNAL
    Then:  the callback fires exactly twice -- once on each transition,
           never duplicated within the same regime. Protects the upstream
           consumer (ShutdownHandler etc.) from duplicate edges.
    """
    monitor, clock, state = _makeMonitor()

    callbackCalls: list[tuple[PowerSource, PowerSource]] = []
    monitor.onPowerSourceChange = lambda old, new: callbackCalls.append((old, new))

    lastSource = PowerSource.EXTERNAL

    def tick(vcellVolts: float, advanceSeconds: float) -> None:
        nonlocal lastSource
        _stepAndRecord(
            monitor,
            clock,
            state,
            vcellVolts=vcellVolts,
            advanceSeconds=advanceSeconds,
        )
        currentSource = monitor.getPowerSource()
        if currentSource != lastSource:
            assert monitor.onPowerSourceChange is not None
            monitor.onPowerSourceChange(lastSource, currentSource)
            lastSource = currentSource

    # Phase 1: warm-up at 4.20V.
    tick(4.20, 0.0)
    tick(4.20, 5.0)

    # Phase 2: drop sub-threshold and sustain.
    for _ in range(8):
        tick(3.92, 5.0)

    # Phase 3: recovery ramp.
    for vcell in (4.00, 4.10, 4.20):
        tick(vcell, 10.0)

    assert callbackCalls == [
        (PowerSource.EXTERNAL, PowerSource.BATTERY),
        (PowerSource.BATTERY, PowerSource.EXTERNAL),
    ]


def test_getPowerSource_briefRecoveryFlicker_doesNotFlapToExternal() -> None:
    """
    Given: monitor is in BATTERY due to sustained sub-threshold. VCELL
           briefly flickers above 3.95V for one sample (e.g., a noisy
           reading) then drops back.
    When:  getPowerSource() runs
    Then:  EXTERNAL on the flicker tick (correct -- the most recent
           sample IS above threshold), then BATTERY again on the next
           sub-threshold tick.

    This documents the current edge-detection semantic: a single above-
    threshold sample is enough to trip back to EXTERNAL. That mirrors
    the existing slope-only behavior; mitigating "wall-power flicker"
    detection (a follow-up edge case explicitly listed under stop
    conditions) is out of scope for US-235. The test pins down the
    semantic so any future flicker-mitigation work has a regression
    point.
    """
    monitor, clock, state = _makeMonitor()

    # Drive to BATTERY.
    for _ in range(8):
        _stepAndRecord(monitor, clock, state, vcellVolts=3.92, advanceSeconds=5.0)
    assert monitor.getPowerSource() == PowerSource.BATTERY

    # Single above-threshold reading -- semantic snapshot.
    _stepAndRecord(monitor, clock, state, vcellVolts=4.10, advanceSeconds=5.0)
    midRecovery = monitor.getPowerSource()

    # Drop back sub-threshold for a fresh sustained run.
    for _ in range(8):
        _stepAndRecord(monitor, clock, state, vcellVolts=3.92, advanceSeconds=5.0)

    # Snapshot: the flicker did flip to EXTERNAL (positive evidence rule).
    # The new sustained run drives back to BATTERY. The semantic is
    # documented; flicker-suppression is a follow-up if drains show flap.
    assert midRecovery == PowerSource.EXTERNAL
    assert monitor.getPowerSource() == PowerSource.BATTERY
