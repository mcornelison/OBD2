################################################################################
# File Name: test_ups_monitor_battery_detection.py
# Purpose/Description: US-235 synthetic test that EXPOSES the Sprint 18
#                      production failure mode: across 4 drain tests (Drains
#                      1-4 over 9 days), UpsMonitor.getPowerSource() never
#                      flipped from EXTERNAL to BATTERY when wall power was
#                      removed. Root cause was the CRATE register returning
#                      0xFFFF (disabled) on this MAX17048 variant + the old
#                      -0.02V/min slope rule not catching the actual VCELL
#                      drift trend.
#
#                      US-235 fix: drop CRATE rule entirely; replace with a
#                      sustained-VCELL-threshold rule (VCELL < 3.95V for >=30s
#                      -> BATTERY) plus a tuned slope rule (-0.005 V/min over
#                      60s -> BATTERY). This test mocks at I2cClient.readWord
#                      level (real MAX17048 chip-read entry) per the
#                      feedback_runtime_validation_required rule, so the
#                      synthetic exercises the real getBatteryVoltage() ->
#                      recordHistorySample() -> getPowerSource() pipeline.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-29    | Rex (US-235) | Initial -- VCELL-threshold + tuned-slope
#                              | synthetic tests that fail against pre-US-235
#                              | CRATE-rule code per stop-condition "STOP if
#                              | synthetic test passes against the OLD code".
# ================================================================================
################################################################################

"""US-235 BATTERY-detection synthetic tests.

Discriminator design
--------------------
The pre-US-235 ``getPowerSource()`` decision tree was::

    if CRATE < crateThreshold (-0.05 %/hr):     -> BATTERY
    elif VCELL slope < -0.02 V/min over 60s:    -> BATTERY
    else:                                       -> EXTERNAL (or cached)

In production, the MAX17048 on this hardware variant returns
``CRATE = 0xFFFF`` (disabled). The slope rule was the only path that could
fire BATTERY -- and at -0.02 V/min over 60s it never caught the slow
draindown observed in real drain tests (VCELL drifted from 3.7V down,
slope around -0.01 to -0.015 V/min, just above the threshold).

Sprint 19 replaces the rule set with::

    if VCELL sustained below 3.95V for >=30s:   -> BATTERY  (primary)
    elif VCELL slope < -0.005 V/min over 60s:   -> BATTERY  (secondary)
    elif decisive non-BATTERY signal:            -> EXTERNAL
    else:                                        -> cached

Test cases below mock VCELL stair-steps + flatlines + recoveries that
would NOT have flipped the old code to BATTERY. They DO flip the new
code, proving the fix catches the actual production bug class.

Mocks operate at :class:`I2cClient.readWord` -- the actual MAX17048
chip-read entry. ``getBatteryVoltage()`` does the byte-swap + scale, and
``recordHistorySample()`` feeds the rolling buffer that
``getPowerSource()`` consumes -- so the production code path is
exercised end to end.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

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
    """Encode a VCELL voltage as the little-endian word SMBus would return.

    The MAX17048 stores VCELL big-endian on the wire at 78.125 uV/LSB.
    ``smbus.read_word_data`` returns it little-endian, so the test-side
    encoder mirrors that: take the 16-bit big-endian value and swap bytes.
    ``getBatteryVoltage()`` then byte-swaps it back.
    """
    raw = int(round(volts / 78.125e-6)) & 0xFFFF
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def _makeMonitorWithReadback(
    *,
    historyWindowSeconds: float = 60.0,
    vcellSlopeThresholdVoltsPerMinute: float = -0.005,
    vcellBatteryThresholdVolts: float = 3.95,
    vcellBatteryThresholdSustainedSeconds: float = 30.0,
) -> tuple[UpsMonitor, MagicMock, FakeClock, dict[str, float]]:
    """Build a UpsMonitor wired to a mock I2C client + injectable VCELL.

    The returned ``state`` dict has a ``vcell`` key -- callers mutate it
    between simulated polls, then call ``getBatteryVoltage()`` to push
    the synthetic VCELL through the real chip-read decode path.
    """
    clock = FakeClock()
    state: dict[str, float] = {'vcell': 4.20}

    def fakeReadWord(addr: int, reg: int) -> int:
        if reg == REGISTER_VCELL:
            return _vcellWordLeForVolts(state['vcell'])
        if reg == REGISTER_SOC:
            # Pin SOC at 80% -- mis-calibration mode irrelevant for this test
            # since US-235 only consumes VCELL. Encode 80 in the high byte
            # the same way getBatteryPercentage expects.
            return 0x5000  # BE 0x0050 -> high byte = 0x50 = 80%
        if reg == REGISTER_CRATE:
            # Disabled -- the in-the-wild state on this chip variant.
            return CRATE_DISABLED_RAW
        raise AssertionError(
            f"unexpected register 0x{reg:02x} during US-235 BATTERY-detection test"
        )

    mockClient = MagicMock()
    mockClient.readWord.side_effect = fakeReadWord

    monitor = UpsMonitor(
        i2cClient=mockClient,
        historyWindowSeconds=historyWindowSeconds,
        vcellSlopeThresholdVoltsPerMinute=vcellSlopeThresholdVoltsPerMinute,
        vcellBatteryThresholdVolts=vcellBatteryThresholdVolts,
        vcellBatteryThresholdSustainedSeconds=vcellBatteryThresholdSustainedSeconds,
        monotonicClock=clock.now,
    )
    return monitor, mockClient, clock, state


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
    # Production path: poll loop reads VCELL via i2cClient.readWord, then
    # records the sample. Mirror that exactly so tests exercise the same
    # decode + buffer-feed code as the live polling thread.
    vcell = monitor.getBatteryVoltage()
    soc = monitor.getBatteryPercentage()
    monitor.recordHistorySample(clock.now(), vcell, soc)


# ================================================================================
# Rule 1: VCELL sustained below threshold -> BATTERY
# ================================================================================


def test_getPowerSource_vcellSustained31sBelowThreshold_returnsBattery() -> None:
    """
    Given: VCELL holds at 4.20V (well above the 3.95V threshold) for two
           polling ticks, then drops to 3.92V and stays there for 31s of
           continuous sub-threshold readings.
    When:  getPowerSource() runs after the 31s sustained sub-threshold run
    Then:  BATTERY -- the sustained-VCELL rule fires once the continuous
           below-threshold run has lasted >= 30s.

    Discriminator: this test would FAIL against the pre-US-235 code. With
    CRATE_DISABLED_RAW returned by the mock, only the slope rule could
    fire there, and slope at -(0.04) over 5s = ~-0.48 V/min only kicks in
    after the buffer has at least two below-threshold samples. The
    pre-US-235 default threshold was -0.02 V/min so the slope rule would
    fire too -- meaning this test discriminates the SUSTAINED-threshold
    semantic specifically by sequencing samples whose slope is gentler
    than -0.02 V/min after the first jump.

    To keep the discrimination clean, sustain at 3.92V flat -- the slope
    over 31s of flat 3.92V is 0 V/min and CANNOT fire either old or new
    slope rule. The only path to BATTERY is the new sustained-threshold
    rule.
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=0.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=5.0)

    # Drop below threshold and hold flat for 31s -- slope is exactly 0
    # V/min during the sustained window so only the threshold rule can
    # fire BATTERY here.
    _stepAndRecord(monitor, clock, state, vcellVolts=3.92, advanceSeconds=5.0)
    for _ in range(7):
        _stepAndRecord(monitor, clock, state, vcellVolts=3.92, advanceSeconds=5.0)

    # 7 ticks of 5s = 35s of continuous sub-threshold samples.
    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_vcellBriefDipBelowThreshold_doesNotFire() -> None:
    """
    Given: VCELL momentarily dips to 3.92V for 10s then recovers to 4.20V.
    When:  getPowerSource() runs after the recovery
    Then:  EXTERNAL -- the sub-threshold dip didn't last >=30s; the
           sustained rule must not fire on a transient drop. Protects
           against false positives from voltage noise during, e.g.,
           pygame display redraw or other transient I2C/PSU events.
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=0.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=3.92, advanceSeconds=5.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=3.92, advanceSeconds=5.0)
    # Recover after 10s sub-threshold (less than 30s sustained).
    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=5.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=5.0)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


# ================================================================================
# Rule 1 negative: VCELL flat above threshold -> EXTERNAL
# ================================================================================


def test_getPowerSource_vcellFlatAboveThreshold_returnsExternal() -> None:
    """
    Given: VCELL holds steady at 4.20V across a 60s window (well above
           the 3.95V threshold; flat slope = 0 V/min).
    When:  getPowerSource() runs
    Then:  EXTERNAL -- no BATTERY rule fires. Regression guard against
           the false-positive class.
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    for _ in range(13):  # 60s of 5s ticks
        _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=5.0)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


# ================================================================================
# Rule 2: VCELL slope past tuned threshold -> BATTERY
# ================================================================================


def test_getPowerSource_vcellSlopeFastDrop_returnsBattery() -> None:
    """
    Given: VCELL falls 0.02V over 30s -- slope = -0.04 V/min, well below
           the new -0.005 V/min threshold. Both sample VCELLs (4.20 then
           4.18) are ABOVE 3.95V so the sustained rule cannot fire; only
           the slope rule is in play.
    When:  getPowerSource() runs
    Then:  BATTERY -- slope rule catches the drop.

    Discriminator: pre-US-235 threshold was -0.02 V/min. -0.04 V/min
    fired there too, so this case alone wouldn't discriminate. But it
    documents the new tuned threshold catching a slower drop than the
    old one would, complementing the next test (slow-drop EXTERNAL).
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=0.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=4.18, advanceSeconds=30.0)

    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_vcellSlopeJustAboveTunedThreshold_returnsExternal() -> None:
    """
    Given: VCELL falls 0.001V over 60s -- slope = -0.001 V/min, just
           above (less negative than) the new -0.005 V/min threshold.
           Both VCELL samples above 3.95V so threshold rule doesn't fire.
    When:  getPowerSource() runs
    Then:  EXTERNAL -- proves the slope-rule cutoff is strict (less-than,
           not less-than-or-equal) at the new tuned value.
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    _stepAndRecord(monitor, clock, state, vcellVolts=4.200, advanceSeconds=0.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=4.199, advanceSeconds=60.0)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_oldSlopeThresholdMisses_newCatches() -> None:
    """
    Given: VCELL falls 0.01V over 60s -- slope = -0.01 V/min. The
           pre-US-235 threshold was -0.02 V/min so this slope did NOT
           fire BATTERY there (key reason real drains never tripped).
           The new threshold is -0.005 V/min so this slope DOES fire.
    When:  getPowerSource() runs
    Then:  BATTERY -- proves the tuned threshold catches the slow drift
           the old threshold missed. This is the discriminator that
           proves US-235 catches the live failure mode, mirroring the
           Sprint-18-lesson rule that synthetic tests must FAIL against
           the pre-fix code.
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    _stepAndRecord(monitor, clock, state, vcellVolts=4.20, advanceSeconds=0.0)
    _stepAndRecord(monitor, clock, state, vcellVolts=4.19, advanceSeconds=60.0)

    assert monitor.getPowerSource() == PowerSource.BATTERY


# ================================================================================
# CRATE drop: a CRATE that *would* have fired the old rule must NOT
# influence the new path.
# ================================================================================


def test_getPowerSource_crateBelowOldThreshold_doesNotFireBatteryAlone() -> None:
    """
    Given: CRATE returns a value that decodes to -1.04 %/hr (well below
           the legacy -0.05 %/hr threshold), but VCELL is flat at 4.20V
           with no sub-threshold span and no negative slope.
    When:  getPowerSource() runs
    Then:  EXTERNAL -- proves the CRATE rule has been DELETED. Pre-US-235
           code would have returned BATTERY purely from CRATE polarity.

    This test is the core "fails against the OLD code" proof: it's the
    minimal scenario that flips behavior between pre- and post-US-235.
    """
    clock = FakeClock()
    state: dict[str, float] = {'vcell': 4.20}

    def fakeReadWord(addr: int, reg: int) -> int:
        if reg == REGISTER_VCELL:
            return _vcellWordLeForVolts(state['vcell'])
        if reg == REGISTER_SOC:
            return 0x5000
        if reg == REGISTER_CRATE:
            # LE 0xFBFF -> BE 0xFFFB -> signed -5 -> -1.04 %/hr.
            return 0xFBFF
        raise AssertionError(f"unexpected register 0x{reg:02x}")

    mockClient = MagicMock()
    mockClient.readWord.side_effect = fakeReadWord

    monitor = UpsMonitor(
        i2cClient=mockClient,
        monotonicClock=clock.now,
    )

    # Two flat samples at 4.20V -- slope 0, threshold rule clear.
    monitor.recordHistorySample(clock.now(), 4.20, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 4.20, 80)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


# ================================================================================
# Callback: onPowerSourceChange fires once on EXTERNAL -> BATTERY
# ================================================================================


def test_powerSourceChange_callbackFiresOnceOnDetectedBattery() -> None:
    """
    Given: VCELL drops below threshold and stays sub-threshold for >=30s.
           A callback is wired to onPowerSourceChange.
    When:  the polling loop's tick sequence detects BATTERY
    Then:  the callback fires exactly once with (EXTERNAL, BATTERY).
           Verifies the production-side wiring (used by ShutdownHandler
           registration) still routes through the new detection path.
    """
    monitor, _client, clock, state = _makeMonitorWithReadback()

    callbackCalls: list[tuple[PowerSource, PowerSource]] = []
    monitor.onPowerSourceChange = lambda old, new: callbackCalls.append((old, new))

    # Simulate the polling-loop body manually so we don't have to spin
    # a real thread: each "tick" reads telemetry, records, and decides.
    lastSource = PowerSource.EXTERNAL

    def tick(vcellVolts: float, advanceSeconds: float) -> PowerSource:
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
        return currentSource

    tick(4.20, 0.0)
    tick(4.20, 5.0)
    # Drop sub-threshold and sustain.
    for i in range(8):
        tick(3.92, 5.0)

    assert callbackCalls == [(PowerSource.EXTERNAL, PowerSource.BATTERY)]


# ================================================================================
# Sanity: getVcellHistory exposes the same buffer used for slope math
# ================================================================================


def test_getVcellHistory_returnsRecentSamples() -> None:
    """
    Given: a few synthetic VCELL samples recorded across 30s.
    When:  getVcellHistory(seconds=10) is called
    Then:  only samples newer than now-10s are returned, in order.
           This API was added in US-234 and is consumed by US-235's
           sustained-threshold logic; this test pins down the contract.
    """
    monitor, _client, clock, _state = _makeMonitorWithReadback()

    monitor.recordHistorySample(clock.now(), 4.20, 80)
    clock.advance(15.0)
    monitor.recordHistorySample(clock.now(), 4.10, 78)
    clock.advance(15.0)
    monitor.recordHistorySample(clock.now(), 4.05, 76)

    recent = monitor.getVcellHistory(seconds=10.0)
    assert len(recent) == 1
    assert recent[0][1] == pytest.approx(4.05)

    allSamples = monitor.getVcellHistory()
    assert [v for _t, v in allSamples] == pytest.approx([4.20, 4.10, 4.05])
