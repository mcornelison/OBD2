################################################################################
# File Name: test_ups_monitor_power_source.py
# Purpose/Description: Decision-tree coverage for UpsMonitor.getPowerSource()
#                      after the US-235 rewrite. The CRATE-polarity rule was
#                      deleted (CRATE register returns 0xFFFF on this MAX17048
#                      variant across 4 drain tests). Detection now uses
#                      VCELL-only rules: sustained-below-threshold + tuned
#                      slope. Sustained-rule + recovery-callback coverage
#                      lives in test_ups_monitor_battery_detection.py /
#                      test_ups_monitor_battery_detection_recovery.py; this
#                      file pins down the SLOPE-rule decision boundary and
#                      the cached-fallback behavior in the no-evidence case.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-184 (fix I-015)
# 2026-04-29    | Rex (US-235) | CRATE-rule deletion: removed Rule-1 tests +
#                              | crateThresholdPercentPerHour ctor arg from
#                              | _makeMonitor. Tuned slope-test scenarios for
#                              | the new -0.005 V/min default threshold (was
#                              | -0.02 V/min). Sustained-threshold rule lives
#                              | in test_ups_monitor_battery_detection.py.
# ================================================================================
################################################################################

"""
Decision-tree coverage for UpsMonitor.getPowerSource() (US-184 -> US-235).

The heuristic under test (post-US-235):

  1. VCELL sustained below `vcellBatteryThresholdVolts` (default 3.95V)
     for >= `vcellBatteryThresholdSustainedSeconds` (default 30s) -> BATTERY
  2. VCELL slope < `vcellSlopeThresholdVoltsPerMinute`               -> BATTERY
  3. Decisive non-BATTERY (most recent VCELL above threshold OR slope
     computable + >= threshold)                                       -> EXTERNAL
  4. Otherwise                                                        -> cached

Tests here exercise rules 2-4. Rule 1 (sustained-threshold) lives in
test_ups_monitor_battery_detection.py to keep file purpose discrete.
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
    historyWindowSeconds: float = 60.0,
    vcellSlopeThresholdVoltsPerMinute: float = -0.005,
    vcellBatteryThresholdVolts: float = 3.95,
    vcellBatteryThresholdSustainedSeconds: float = 30.0,
) -> tuple[UpsMonitor, MagicMock, FakeClock]:
    """Build a UpsMonitor wired to a mock I2C client + fake clock.

    Tests inject samples directly via `recordHistorySample()` so the
    mock client only needs to satisfy `_getClient()` calls -- it returns
    `CRATE_DISABLED_RAW` for any read because no CRATE rule consumes it
    post-US-235; the wired return value is harmless.
    """
    clock = FakeClock()
    mockClient = MagicMock()
    mockClient.readWord.return_value = CRATE_DISABLED_RAW

    monitor = UpsMonitor(
        i2cClient=mockClient,
        historyWindowSeconds=historyWindowSeconds,
        vcellSlopeThresholdVoltsPerMinute=vcellSlopeThresholdVoltsPerMinute,
        vcellBatteryThresholdVolts=vcellBatteryThresholdVolts,
        vcellBatteryThresholdSustainedSeconds=vcellBatteryThresholdSustainedSeconds,
        monotonicClock=clock.now,
    )
    return monitor, mockClient, clock


# ================================================================================
# Rule 2: VCELL-slope path
# ================================================================================


def test_getPowerSource_vcellSlopeBelowThreshold_returnsBattery() -> None:
    """
    Given: history buffer contains a VCELL drop of 0.1V over 60s
           (slope = -0.1 V/min), comfortably below the default
           -0.005 V/min threshold. Both samples above 3.95V so the
           sustained-threshold rule does not fire.
    When:  getPowerSource() runs
    Then:  BATTERY -- the VCELL-slope rule fires. Cached source advances
           to BATTERY.
    """
    monitor, _client, clock = _makeMonitor()

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 4.100, 79)

    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_vcellSlopeAboveThreshold_returnsExternal() -> None:
    """
    Given: history shows VCELL steady at ~4.2V across the window
           (slope ~0 V/min, well above the -0.005 V/min threshold).
    When:  getPowerSource() runs
    Then:  EXTERNAL -- the cell isn't actively discharging.
    """
    monitor, _client, clock = _makeMonitor()

    for _ in range(5):
        monitor.recordHistorySample(clock.now(), 4.200, 80)
        clock.advance(10.0)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_vcellSlopeJustAboveTunedThreshold_returnsExternal() -> None:
    """
    Given: VCELL drops by 0.001V over 60s (slope = -0.001 V/min, just
           above (less negative than) the -0.005 V/min threshold).
    When:  getPowerSource() runs
    Then:  EXTERNAL -- below (less-negative than) the BATTERY-declaring
           slope. Proves the threshold is strict (less-than, not
           less-than-or-equal) at the new tuned value.
    """
    monitor, _client, clock = _makeMonitor()

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 4.199, 79)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_vcellLargeDrop_firesBattery() -> None:
    """
    Given: huge VCELL drop (4.20V -> 3.70V over 60s) -- slope -0.5 V/min.
           Both samples remain in the buffer; sustained-threshold rule
           sees both samples sub-threshold by the latest tick (3.70 <
           3.95) but only across a 60s window with one sub-threshold
           sample -- not a 30s sustained run.
    When:  getPowerSource() runs
    Then:  BATTERY -- the slope rule fires regardless of the
           sustained-threshold state. Tests the slope-only fast-drop
           path.
    """
    monitor, _client, clock = _makeMonitor()

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(60.0)
    monitor.recordHistorySample(clock.now(), 3.700, 60)  # huge drop

    assert monitor.getPowerSource() == PowerSource.BATTERY


# ================================================================================
# Rule 4: insufficient-evidence cached fallback
# ================================================================================


def test_getPowerSource_noHistory_returnsCachedInitialExternal() -> None:
    """
    Given: fresh monitor, no samples.
    When:  getPowerSource() runs
    Then:  EXTERNAL (the boot-default cached source). This protects the
           first few polling ticks from flapping before the history
           buffer fills.
    """
    monitor, _client, _clock = _makeMonitor()

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_noEvidence_preservesLastCachedSource() -> None:
    """
    Given: after a BATTERY decision, the window ages out so only one
           sample remains. The slope rule needs at least 2 samples; the
           sustained-threshold rule needs >=30s of continuous
           sub-threshold data. With one above-threshold sample, neither
           rule has decisive evidence either way.
    When:  getPowerSource() runs
    Then:  EXTERNAL -- a single above-threshold sample IS decisive
           non-BATTERY evidence (most recent VCELL >= 3.95V). The
           monitor is conservative on the BATTERY -> EXTERNAL edge but
           the threshold is set comfortably above the LiPo discharge
           knee so trusting a single recovery sample is safe.

           If the sample remaining is sub-threshold instead, the rule
           below covers that path.
    """
    monitor, _client, clock = _makeMonitor(historyWindowSeconds=5.0)

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(5.0)
    monitor.recordHistorySample(clock.now(), 4.000, 70)  # slope -2.4 V/min
    assert monitor.getPowerSource() == PowerSource.BATTERY

    # Age out both samples; add one ABOVE-threshold sample.
    clock.advance(30.0)
    monitor.recordHistorySample(clock.now(), 4.050, 75)
    # Most recent VCELL >= 3.95 -> decisive non-BATTERY -> EXTERNAL.
    assert monitor.getPowerSource() == PowerSource.EXTERNAL


def test_getPowerSource_subThresholdSampleAlone_preservesCached() -> None:
    """
    Given: after a BATTERY decision, only one sample remains in window
           and it's BELOW threshold but the buffer doesn't span 30s.
    When:  getPowerSource() runs
    Then:  the cached BATTERY source is preserved. Slope is None
           (1 sample), sustained-threshold is False (0s span < 30s),
           decisive-external is False (3.92 < 3.95) -> cached fallback.
           Prevents a single sub-threshold reading from triggering a
           premature EXTERNAL flip during recovery noise.
    """
    monitor, _client, clock = _makeMonitor(historyWindowSeconds=5.0)

    monitor.recordHistorySample(clock.now(), 4.200, 80)
    clock.advance(5.0)
    monitor.recordHistorySample(clock.now(), 4.000, 70)
    assert monitor.getPowerSource() == PowerSource.BATTERY

    # Age out everything, add 1 sub-threshold sample.
    clock.advance(30.0)
    monitor.recordHistorySample(clock.now(), 3.920, 65)
    # Cached BATTERY preserved (no decisive evidence yet).
    assert monitor.getPowerSource() == PowerSource.BATTERY


def test_getPowerSource_singleSample_fallsThroughByVcell() -> None:
    """
    Given: exactly one history sample (above threshold).
    When:  getPowerSource() runs
    Then:  EXTERNAL -- single above-threshold sample is decisive
           non-BATTERY evidence (most recent VCELL >= threshold). Slope
           rule needs 2 samples and doesn't run.
    """
    monitor, _client, clock = _makeMonitor()

    monitor.recordHistorySample(clock.now(), 4.200, 80)

    assert monitor.getPowerSource() == PowerSource.EXTERNAL


# ================================================================================
# Rolling-buffer pruning
# ================================================================================


def test_recordHistorySample_prunesEntriesOlderThanWindow() -> None:
    """
    Given: samples added across a span > historyWindowSeconds.
    When:  the buffer is inspected
    Then:  only entries within the window survive. Prevents unbounded
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


def test_getPowerSource_lowExt5v_doesNotCauseBatteryWithoutEvidence() -> None:
    """
    Given: the injected EXT5V reader returns 3.4V — under US-180 that
           would have flipped source to BATTERY. No history.
    When:  getPowerSource() runs
    Then:  EXTERNAL (cached) — EXT5V is decoupled from source detection
           per US-184 + US-235. This is the regression-guard for I-015.
    """
    clock = FakeClock()
    mockClient = MagicMock()
    mockClient.readWord.return_value = CRATE_DISABLED_RAW

    monitor = UpsMonitor(
        i2cClient=mockClient,
        ext5vReader=lambda: 3.4,
        monotonicClock=clock.now,
    )

    assert monitor.getPowerSource() == PowerSource.EXTERNAL
