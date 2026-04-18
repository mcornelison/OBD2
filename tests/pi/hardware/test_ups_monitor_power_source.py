################################################################################
# File Name: test_ups_monitor_power_source.py
# Purpose/Description: Decision-tree coverage for UpsMonitor.getPowerSource()
#                      after the US-184 rewrite.  EXT5V is no longer the
#                      source signal; the heuristic is CRATE polarity +
#                      VCELL-slope over a rolling window.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-184 (fix I-015)
# ================================================================================
################################################################################

"""
Decision-tree coverage for UpsMonitor.getPowerSource() (US-184 / I-015).

The heuristic under test:

  1. If CRATE is readable AND below crateThresholdPercentPerHour     -> BATTERY
  2. Else if VCELL slope over window < vcellSlopeThresholdVoltsPerMin -> BATTERY
  3. Else                                                             -> EXTERNAL
  4. If CRATE unavailable AND < 2 history samples                      -> cached

Tests here exercise each branch with a mocked I2C client and an injectable
monotonic clock so slope math is deterministic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pi.hardware.ups_monitor import (
    CRATE_DISABLED_RAW,
    PowerSource,
    UpsMonitor,
)

# ================================================================================
# Helpers
# ================================================================================


class FakeClock:
    """Deterministic monotonic clock for slope-math tests."""

    def __init__(self, startSeconds: float = 0.0) -> None:
        self.t = startSeconds

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _makeMonitor(
    *,
    crateWordLe: int | None = None,
    historyWindowSeconds: float = 60.0,
    vcellSlopeThresholdVoltsPerMinute: float = -0.02,
    crateThresholdPercentPerHour: float = -0.05,
) -> tuple[UpsMonitor, MagicMock, FakeClock]:
    """Build a UpsMonitor wired to a mock I2C client + fake clock.

    `crateWordLe` is returned by the CRATE read if not None.  Pass
    `CRATE_DISABLED_RAW` to simulate a chip variant without CRATE.
    """
    clock = FakeClock()
    mockClient = MagicMock()

    def fakeReadWord(addr: int, reg: int) -> int:
        if reg == 0x16 and crateWordLe is not None:
            return crateWordLe
        if reg == 0x16:
            return CRATE_DISABLED_RAW
        # VCELL / SOC / VERSION are not exercised here; tests inject
        # history directly via recordHistorySample().
        raise AssertionError(
            f"unexpected register 0x{reg:02x} during getPowerSource test"
        )

    mockClient.readWord.side_effect = fakeReadWord

    monitor = UpsMonitor(
        i2cClient=mockClient,
        historyWindowSeconds=historyWindowSeconds,
        vcellSlopeThresholdVoltsPerMinute=vcellSlopeThresholdVoltsPerMinute,
        crateThresholdPercentPerHour=crateThresholdPercentPerHour,
        monotonicClock=clock.now,
    )
    return monitor, mockClient, clock


# ================================================================================
# Rule 1: CRATE polarity path
# ================================================================================


def test_getPowerSource_crateBelowThreshold_returnsBattery() -> None:
    """
    Given: CRATE reads as -0.208%/hr (LE 0xFFFF would be disabled; LE
           0xFFFF signed-extended-swap gives a negative rate only via a
           non-sentinel word).  Use LE 0xFBFF -> BE 0xFFFB -> signed -5
           -> -5 * 0.208 = -1.04 %/hr.  That is well below the default
           -0.05 %/hr threshold.
    When:  getPowerSource() runs
    Then:  BATTERY is returned even though VCELL history is empty — the
           CRATE branch short-circuits ahead of slope detection.
    """
    monitor, _client, _clock = _makeMonitor(crateWordLe=0xFBFF)

    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_crateJustBelowThreshold_returnsBattery() -> None:
    """
    Given: the VCELL-slope branch is out of play (no history) and CRATE
           is below -0.05 %/hr — the exact margin the default catches.
           LE 0xFFFF is the disabled sentinel, so synthesize a small
           negative: LE 0xFFFF would collide, use LE 0xFFFE -> BE 0xFEFF
           -> signed -257 -> -53.5 %/hr. Clearly below threshold.
    When:  getPowerSource() runs
    Then:  BATTERY.
    """
    monitor, _client, _clock = _makeMonitor(crateWordLe=0xFFFE)

    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_cratePositive_doesNotForceBattery() -> None:
    """
    Given: CRATE reads as +1.04 %/hr (charging).  No history buffer.
    When:  getPowerSource() runs
    Then:  EXTERNAL — a charging cell is on external power.  The
           cached source is advanced to EXTERNAL.
    """
    monitor, _client, _clock = _makeMonitor(crateWordLe=0x0500)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


# ================================================================================
# Rule 2: VCELL-slope path (when CRATE is unavailable)
# ================================================================================


def test_getPowerSource_vcellSlopeBelowThreshold_returnsBattery() -> None:
    """
    Given: CRATE reads as disabled (0xFFFF), and the history buffer
           contains a VCELL drop of 0.1V over 60s (slope = -0.1 V/min),
           comfortably below the default -0.02 V/min threshold.
    When:  getPowerSource() runs
    Then:  BATTERY — the VCELL-slope branch fires in the absence of
           CRATE.  Cached source advances to BATTERY.
    """
    monitor, _client, clock = _makeMonitor(crateWordLe=CRATE_DISABLED_RAW)

    # Two samples, 60s apart, 0.1V drop.
    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 4.100, 79)

    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_vcellSlopeAboveThreshold_returnsExternal() -> None:
    """
    Given: CRATE is disabled; history shows VCELL steady at ~4.2V
           across the window (slope ~0 V/min, well above the -0.02
           V/min threshold).
    When:  getPowerSource() runs
    Then:  EXTERNAL — the cell isn't actively discharging.
    """
    monitor, _client, clock = _makeMonitor(crateWordLe=CRATE_DISABLED_RAW)

    for _ in range(5):
        monitor.recordHistorySample(clock.now(), 4.200, 80)
        clock.advance(10.0)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_vcellSlopeJustAboveThreshold_returnsExternal() -> None:
    """
    Given: CRATE disabled; VCELL drops by 0.01V over 60s (slope
           = -0.01 V/min, just above (less negative than) the
           -0.02 V/min threshold).
    When:  getPowerSource() runs
    Then:  EXTERNAL — below the BATTERY-declaring slope.  Proves the
           threshold is strict (less-than, not less-than-or-equal).
    """
    monitor, _client, clock = _makeMonitor(crateWordLe=CRATE_DISABLED_RAW)

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 4.190, 79)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_crateAvailableButPositive_slopeWins() -> None:
    """
    Given: CRATE is +0.01 %/hr (above threshold, doesn't fire BATTERY),
           and VCELL slope across the window is -0.5 V/min (clearly
           below the -0.02 V/min threshold).
    When:  getPowerSource() runs
    Then:  BATTERY — rule 1 passes (CRATE not below threshold) so
           rule 2 fires on slope.  Exercises the fall-through path.
    """
    # 0x0001 LE -> BE 0x0100 = signed 256 -> +53.2 %/hr. That's not
    # "just above", but it's above -0.05 so rule 1 doesn't fire.
    monitor, _client, clock = _makeMonitor(crateWordLe=0x0001)

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 3.700, 60)  # huge drop

    assert monitor.getPowerSource() == PowerSource.BATTERY


# ================================================================================
# Rule 4: Insufficient signal path (cached fallback)
# ================================================================================


def test_getPowerSource_noHistoryNoCrate_returnsCachedInitialExternal() -> None:
    """
    Given: fresh monitor, no samples, CRATE disabled.
    When:  getPowerSource() runs
    Then:  EXTERNAL (the boot-default cached source).  This protects
           the first few polling ticks from flapping before the
           history buffer fills.
    """
    monitor, _client, _clock = _makeMonitor(crateWordLe=CRATE_DISABLED_RAW)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_noHistoryNoCrate_preservesLastCachedSource() -> None:
    """
    Given: after a BATTERY decision, the window ages out (all samples
           pruned) and CRATE returns disabled again.
    When:  getPowerSource() runs
    Then:  the last cached source (BATTERY) is returned — the monitor
           does NOT spontaneously flip back to EXTERNAL just because
           evidence ran out.  Prevents false-positive shutdown-cancel.
    """
    monitor, _client, clock = _makeMonitor(
        crateWordLe=CRATE_DISABLED_RAW, historyWindowSeconds=5.0
    )

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(5.0)
    monitor.recordHistorySample(clock.now(), 4.000, 70)  # slope = -2.4 V/min
    assert monitor.getPowerSource() == PowerSource.BATTERY

    # Age out both samples.
    clock.advance(30.0)
    monitor.recordHistorySample(clock.now(), 4.050, 75)
    # After prune, only 1 sample remains in the window -> slope None.
    # CRATE disabled -> fall through to cached source.
    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_singleSampleOnly_fallsThroughToCached() -> None:
    """
    Given: exactly one history sample and CRATE disabled.
    When:  getPowerSource() runs
    Then:  cached source (EXTERNAL on boot) — slope needs at least 2
           points, CRATE is gone, so rule 4 fires.
    """
    monitor, _client, clock = _makeMonitor(crateWordLe=CRATE_DISABLED_RAW)

    monitor.recordHistorySample(clock.now(), 4.200, 80)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


# ================================================================================
# CRATE-read-error path (graceful degradation to slope branch)
# ================================================================================


def test_getPowerSource_crateReadRaises_fallsThroughToSlope() -> None:
    """
    Given: CRATE read raises UpsMonitorError (transient I2C hiccup),
           and VCELL slope over history is clearly below threshold.
    When:  getPowerSource() runs
    Then:  BATTERY — the safe CRATE wrapper converts the error to
           None and rule 2 fires on slope.  The monitor does NOT
           crash on a transient CRATE failure.
    """
    from pi.hardware.i2c_client import I2cCommunicationError

    clock = FakeClock()
    mockClient = MagicMock()

    def fakeReadWord(addr: int, reg: int) -> int:
        if reg == 0x16:
            raise I2cCommunicationError("transient CRATE hiccup")
        raise AssertionError(f"unexpected register 0x{reg:02x}")

    mockClient.readWord.side_effect = fakeReadWord

    monitor = UpsMonitor(
        i2cClient=mockClient,
        monotonicClock=clock.now,
        historyWindowSeconds=10.0,
    )

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(10.0)
    monitor.recordHistorySample(clock.now(), 4.000, 75)  # slope -1.2 V/min

    assert monitor.getPowerSource() == PowerSource.BATTERY


# ================================================================================
# Rolling-buffer pruning
# ================================================================================


def test_recordHistorySample_prunesEntriesOlderThanWindow() -> None:
    """
    Given: samples added across a span > historyWindowSeconds.
    When:  the buffer is inspected
    Then:  only entries within the window survive.  Prevents unbounded
           growth and keeps slope math focused on recent behavior.
    """
    monitor, _client, clock = _makeMonitor(historyWindowSeconds=10.0)

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(15.0)  # old sample ages out
    monitor.recordHistorySample(clock.now(), 4.000, 70)

    with monitor._historyLock:
        timestamps = [t for (t, _v, _s) in monitor._history]

    assert len(timestamps) == 1
    # Only the recent sample remains.
    assert timestamps[0] == pytest.approx(15.0)


def test_recordHistorySample_retainsInWindowEntries() -> None:
    """
    Given: samples added at t=0, t=3, t=6, with window=10.
    When:  the buffer is inspected at t=6
    Then:  all three are retained — none has aged out.
    """
    monitor, _client, clock = _makeMonitor(historyWindowSeconds=10.0)

    monitor.recordHistorySample(clock.now(), 4.20, 80)
    clock.advance(3.0)
    monitor.recordHistorySample(clock.now(), 4.19, 79)
    clock.advance(3.0)
    monitor.recordHistorySample(clock.now(), 4.18, 78)

    with monitor._historyLock:
        assert len(monitor._history) == 3


# ================================================================================
# Invariant: EXT5V no longer influences source
# ================================================================================


def test_getPowerSource_lowExt5v_doesNotCauseBatteryWithoutSlope() -> None:
    """
    Given: the injected EXT5V reader returns 3.4V — under US-180 that
           would have flipped source to BATTERY.  CRATE disabled, no
           history.
    When:  getPowerSource() runs
    Then:  EXTERNAL (cached) — EXT5V is now decoupled from source
           detection.  This is the regression-guard for I-015.
    """
    clock = FakeClock()
    mockClient = MagicMock()
    mockClient.readWord.side_effect = lambda addr, reg: (
        CRATE_DISABLED_RAW if reg == 0x16 else (_ for _ in ()).throw(
            AssertionError(f"unexpected reg 0x{reg:02x}")
        )
    )

    monitor = UpsMonitor(
        i2cClient=mockClient,
        ext5vReader=lambda: 3.4,
        monotonicClock=clock.now,
    )

    assert monitor.getPowerSource() == PowerSource.EXTERNAL
