################################################################################
# File Name: test_imu_rate_derived_consumers.py
# Purpose/Description: US-796-f -- re-check what DERIVES from the IMU rates at
#     the shipped 4 / 2 / 1 triple (US-796-b). Two consumers compute a window
#     from sampleHz: the plausibility gate's stuck-value run limit and the state
#     bridge's magnetometer/gyro pairing window. Each is pinned at 4 Hz with the
#     wall-clock window it now covers, each is proven to read the rate from
#     config (a poisoned module default must not move it), and the regression
#     check holds: a genuinely stuck sensor is still detected, and the mag/gyro
#     pairing still pairs at stateHz 1.
#
#     2026-09-28 (ARCH-064, Controller Ruling 14/15, Task 5 fix round):
#     `sampleHz` is no longer 4 -- ARCH-064 raised it to 50 Hz as the IMU's
#     INTERNAL acquisition/fusion read rate (persistHz/stateHz, the STORED
#     rates, stay under the 4 Hz ceiling; see
#     specs/data-acquisition-architecture.md §4.2.a). The "shipped config"
#     tests below are updated to the amended relationship rather than deleted
#     -- they still prove the same two properties (rate comes from config,
#     not a poisoned module default) at the NEW shipped rate. The gate's
#     stuck-value window is unaffected in WALL-CLOCK terms (still 2.0 s; only
#     the sample-count it takes to cover that changed, 8 -> 100). The bridge's
#     mag/gyro pairing window is NOT unaffected -- at 50 Hz the naive
#     MAG_MAX_AGE_POLLS/sampleHz collapses to 0.1 s, tight enough that an
#     ordinary scheduler hiccup drops a paired gyro reading, so Ruling 14
#     floors it at MIN_PAIRING_WINDOW_S = 0.5 s
#     (`imu_state_bridge.ImuStateBridge.__init__`).
# Author: Rex (US-796-f)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-21    | Rex (US-796-f) | Initial -- pinned at the shipped 4 Hz triple.
# 2026-09-28    | Atlas          | ARCH-064 Rulings 14/15 (Task 5 fix round):
#               | (ARCH-064)     | updated the four tests that read the shipped
#               |                | config.json to the amended sampleHz 50
#               |                | relationship -- gate run-limit 8 -> 100
#               |                | (same 2.0 s wall-clock window); bridge
#               |                | pairing window 1.25 s -> 0.5 s (Ruling 14's
#               |                | floor, not the un-floored 0.1 s).
# ================================================================================
################################################################################
"""US-796-f: the rate-derived IMU consumers. Updated 2026-09-28 (ARCH-064) for
sampleHz 50 (internal read) / persistHz 2 / stateHz 1 (stored, under the 4 Hz
ceiling)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import pi.sensors.imu_state_bridge as bridgeModule
import pi.sensors.sensor_reader as readerModule
from pi.bus.bus import SampleBus
from pi.bus.sample import Sample
from pi.sensors.imu_state_bridge import (
    IMU_BODY_FRAME,
    MAG_MAX_AGE_POLLS,
    MIN_PAIRING_WINDOW_S,
    STANDARD_GRAVITY_MS2,
    ImuStateBridge,
    createImuStateBridgeFromConfig,
    resolveMountFrame,
)
from pi.sensors.plausibility_gate import (
    DEFAULT_INVARIANT_DWELL_S,
    REASON_SENSOR_STALE,
    ChannelPolicy,
    PlausibilityGate,
)
from pi.sensors.sensor_reader import TOPIC_IMU_MAG, createSensorReadersFromConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]

# A general low-rate test point (US-796-b's 2026-09-21 shipped triple; no
# longer the shipped sampleHz after ARCH-064 -- see _SHIPPED_SAMPLE_HZ below
# -- but still a valid, explicit rate to construct consumers at directly, and
# BELOW Ruling 14's MIN_PAIRING_WINDOW_S floor is not engaged here).
_SAMPLE_HZ = 4
_STATE_HZ = 1

# The rate these windows were designed at before US-796-b, AND (ARCH-064,
# 2026-09-28) the rate config.json ships again today, for a different reason:
# the IMU's internal acquisition/fusion read, not a stored rate. Two separate
# rulings landing on the same number is a coincidence worth naming so it is
# not misread as one.
_LEGACY_SAMPLE_HZ = 50

# The rate config.json actually ships (ARCH-064, 2026-09-28): sampleHz 50 as
# the internal fusion read; persistHz/stateHz stay 2/1 under the 4 Hz ceiling
# (specs/data-acquisition-architecture.md §4.2.a). Named separately from
# _LEGACY_SAMPLE_HZ above even though the value is the same, so a reader does
# not have to infer "shipped" from a comment about the past.
_SHIPPED_SAMPLE_HZ = 50

# At 50 Hz: 2.0 s dwell * 50 samples/s = 100 bit-identical samples -- the SAME
# 2.0 s wall-clock window the 8-sample limit covered at 4 Hz (8/4 == 100/50).
_EXPECTED_RUN_LIMIT_AT_SHIPPED_HZ = 100

# At 50 Hz: 5 polls / 50 Hz = 0.1 s, BELOW Ruling 14's MIN_PAIRING_WINDOW_S
# (0.5 s) floor -- the floor applies, so the actual pairing window is 0.5 s,
# not the un-floored 0.1 s.
_EXPECTED_PAIRING_WINDOW_AT_SHIPPED_HZ_S = MIN_PAIRING_WINDOW_S

# A module default no config would ever carry. If a consumer resolves its rate
# from the default instead of from config, its derived window moves to this
# rate's value and the assertion names the defect.
_POISON_HZ = 1000

# A SEPARATE poison rate for the bridge's pairing-window test only (Ruling 14
# fix round). At the shipped 50 Hz, both the correct rate (5/50=0.1 s) and
# _POISON_HZ=1000 (5/1000=0.005 s) land BELOW MIN_PAIRING_WINDOW_S and are
# floored to the SAME 0.5 s -- the floor would silently defeat the "config
# wins over the poisoned default" check. A poison rate whose window survives
# the floor un-collapsed keeps the check discriminating: 5/2=2.5 s, clearly
# not 0.5 s, if the poisoned default were used instead of config.
_POISON_HZ_ABOVE_FLOOR = 2

# At 4 Hz: 4 samples/s * 2.0 s dwell = 8 bit-identical samples, which spans
# 8 / 4 = 2.0 s of wall clock -- the SAME window 100 samples spanned at 50 Hz.
_EXPECTED_RUN_LIMIT_AT_4HZ = 8
_EXPECTED_RUN_WINDOW_S = 2.0

# At 4 Hz: 5 polls * 0.25 s = 1.25 s pairing window (was 5 * 0.02 = 0.1 s).
_EXPECTED_PAIRING_WINDOW_AT_4HZ_S = 1.25

_BURST_INTERVAL_S = 1.0 / _SAMPLE_HZ


def _shippedImu() -> dict[str, Any]:
    """The pi.sensors.imu section exactly as config.json ships it."""
    with open(_REPO_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)["pi"]["sensors"]["imu"]


def _busConfig(imu: dict[str, Any]) -> dict[str, Any]:
    """A config with the bus on and ONLY the IMU enabled."""
    return {
        "pi": {
            "bus": {"enabled": True},
            "sensors": {"imu": dict(imu, enabled=True), "light": {"enabled": False}},
        }
    }


def _raw(vehicle: tuple[float, float, float]) -> tuple[float, ...]:
    """Express a VEHICLE-frame vector in the board's raw axes (inverse mount)."""
    cols = [
        resolveMountFrame(axis, IMU_BODY_FRAME)
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    ]
    return tuple(sum(cols[col][row] * vehicle[row] for row in range(3)) for col in range(3))


def _imu(field: str, vehicle: tuple[float, float, float], seq: int, capture: float) -> Sample:
    """One raw.imu.<field> sample under a burst's shared seq."""
    return Sample(
        topic=f"raw.imu.{field}",
        source="imu",
        value=_raw(vehicle),
        unit="x",
        tsUtc="2026-09-21T00:00:00Z",
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


_LEVEL = (0.0, 0.0, STANDARD_GRAVITY_MS2)
_NORTH_FIELD = (20.0, 0.0, -40.0)
_STILL = (0.0, 0.0, 0.0)


class _RecordingBridge(ImuStateBridge):
    """A bridge whose state writes are captured instead of hitting tmpfs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.writes: list[dict[str, Any]] = []

    def _writeState(self, payload: dict) -> None:
        self.writes.append(payload)


# ---------------------------------------------------------------------------
# Plausibility gate: the invariant-run limit at 4 Hz
# ---------------------------------------------------------------------------


def test_plausibilityGate_atFourHz_runLimitIsEight_spanningTwoSeconds():
    """
    Given: the shipped 4 Hz IMU rate and the default 2.0 s dwell
    When: the gate derives its stuck-value run limit
    Then: it is exactly 8 samples, which covers 2.0 s of wall clock -- the same
          window the 100-sample limit covered at 50 Hz, so the rate change did
          not shorten the guard
    """
    gate = PlausibilityGate(sampleHz=_SAMPLE_HZ)
    legacy = PlausibilityGate(sampleHz=_LEGACY_SAMPLE_HZ)

    assert gate.invariantRunLimit == _EXPECTED_RUN_LIMIT_AT_4HZ
    assert gate.invariantRunLimit / _SAMPLE_HZ == _EXPECTED_RUN_WINDOW_S
    assert legacy.invariantRunLimit / _LEGACY_SAMPLE_HZ == _EXPECTED_RUN_WINDOW_S
    assert _EXPECTED_RUN_WINDOW_S == DEFAULT_INVARIANT_DWELL_S


def test_imuReaderFromShippedConfig_gateRunLimitIsTheShippedHzValue():
    """
    Given: the shipped config.json IMU section (ARCH-064: sampleHz 50, the
           internal fusion read rate -- Ruling 15, Task 5 fix round)
    When: the reader is built through the production factory
    Then: its gate's run limit is the 50 Hz value (100), not the 4 Hz one (8)
          -- the SAME 2.0 s wall-clock window either way (100/50 == 8/4); only
          the sample count needed to cover it moved with the rate
    """
    readers = createSensorReadersFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert len(readers) == 1
    assert readers[0]._gate.invariantRunLimit == _EXPECTED_RUN_LIMIT_AT_SHIPPED_HZ
    assert readers[0]._gate.invariantRunLimit / _SHIPPED_SAMPLE_HZ == _EXPECTED_RUN_WINDOW_S


def test_imuReaderFromConfig_ignoresTheModuleDefaultRate(monkeypatch: pytest.MonkeyPatch):
    """
    Given: the module's fallback IMU rate poisoned to 1000 Hz
    When: the reader is built from a config that states sampleHz 50
    Then: the run limit is still 100 -- the rate came from config; had it come
          from the default the limit would be 2000
    """
    monkeypatch.setattr(readerModule, "DEFAULT_IMU_SAMPLE_HZ", _POISON_HZ)

    readers = createSensorReadersFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert readers[0]._gate.invariantRunLimit == _EXPECTED_RUN_LIMIT_AT_SHIPPED_HZ


def test_stuckMagAtFourHz_isStaleOnTheEighthIdenticalSample_twoSecondsIn():
    """
    Given: an IMU reader's gate at 4 Hz and a magnetometer latched on one value
    When: the same bit-identical reading arrives once per 0.25 s poll
    Then: samples 1-7 (0.0-1.5 s) still pass and sample 8 -- 2.0 s of an
          unmoving value -- is refused sensor_stale: a genuinely stuck sensor
          is still detected at the new rate
    """
    gate = PlausibilityGate(
        sampleHz=_SAMPLE_HZ, policies={TOPIC_IMU_MAG: ChannelPolicy(invariance=True)}
    )
    latched = (12.3, -4.5, 40.1)

    verdicts = [gate.check(TOPIC_IMU_MAG, latched) for _ in range(_EXPECTED_RUN_LIMIT_AT_4HZ)]

    assert all(v.ok for v in verdicts[:-1])
    assert verdicts[-1].ok is False
    assert verdicts[-1].reason == REASON_SENSOR_STALE


def test_ditheringMagAtFourHz_isNeverStale():
    """
    Given: the gate at 4 Hz and a real magnetometer dithering by one LSB
    When: 20 s of polls arrive
    Then: no sample is refused -- the slower rate did not turn dither into a run
    """
    gate = PlausibilityGate(
        sampleHz=_SAMPLE_HZ, policies={TOPIC_IMU_MAG: ChannelPolicy(invariance=True)}
    )
    samples = [(12.3 + (i % 2) * 0.15, -4.5, 40.1) for i in range(20 * _SAMPLE_HZ)]

    assert all(gate.check(TOPIC_IMU_MAG, s).ok for s in samples)


# ---------------------------------------------------------------------------
# State bridge: the magnetometer/gyro pairing window, and Ruling 14's floor
# ---------------------------------------------------------------------------


def test_bridgeAtFourHz_pairingWindowIsOnePointTwoFiveSeconds():
    """
    Given: the bridge at a 4 Hz sample rate (above Ruling 14's floor -- the
           floor does not engage here, and this pin holds unchanged)
    When: the mag/gyro pairing window is derived
    Then: it is MAG_MAX_AGE_POLLS (5) * 0.25 s = 1.25 s
    """
    bridge = ImuStateBridge(None, "unused", sampleHz=_SAMPLE_HZ, stateHz=_STATE_HZ)

    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_4HZ_S
    assert bridge._magMaxAgeS == MAG_MAX_AGE_POLLS * _BURST_INTERVAL_S
    assert bridge._magMaxAgeS > MIN_PAIRING_WINDOW_S


def test_bridgeAtShippedHz_pairingWindowIsFlooredAtHalfSecond_notPointOne():
    """
    Given: the bridge at the shipped 50 Hz sample rate (ARCH-064 Ruling 14,
           Task 5 fix round)
    When: the mag/gyro pairing window is derived
    Then: it is MIN_PAIRING_WINDOW_S (0.5 s), NOT the un-floored
          MAG_MAX_AGE_POLLS / 50 = 0.1 s -- a scheduler hiccup up to ~500 ms
          must not drop a paired gyro reading and integrate it as zero rate
    """
    bridge = ImuStateBridge(None, "unused", sampleHz=_SHIPPED_SAMPLE_HZ, stateHz=_STATE_HZ)

    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_SHIPPED_HZ_S
    assert bridge._magMaxAgeS == MIN_PAIRING_WINDOW_S
    unflooredWindow = MAG_MAX_AGE_POLLS / _SHIPPED_SAMPLE_HZ
    assert unflooredWindow < MIN_PAIRING_WINDOW_S, "the floor must actually be engaging here"
    assert bridge._magMaxAgeS != unflooredWindow


def test_bridgeFromShippedConfig_pairingWindowIsFlooredAtHalfSecond():
    """
    Given: the shipped config.json IMU section (sampleHz 50, ARCH-064)
    When: the bridge is built through the production factory
    Then: its pairing window is 0.5 s (Ruling 14's floor), not the un-floored
          0.1 s and not the pre-ARCH-064 1.25 s (4 Hz)
    """
    bridge = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert bridge is not None
    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_SHIPPED_HZ_S


def test_bridgeFromConfig_ignoresTheModuleDefaultRate(monkeypatch: pytest.MonkeyPatch):
    """
    Given: the bridge module's fallback IMU rate poisoned to a rate ABOVE
           Ruling 14's floor (2 Hz -> 2.5 s window), so flooring cannot make
           the poisoned path coincidentally match the correct answer
    When: the bridge is built from a config that states sampleHz 50
    Then: the pairing window is still 0.5 s (the floored, shipped-rate value)
          -- had the rate come from the poisoned default it would be 2.5 s
    """
    monkeypatch.setattr(bridgeModule, "DEFAULT_IMU_SAMPLE_HZ", _POISON_HZ_ABOVE_FLOOR)

    bridge = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert bridge is not None
    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_SHIPPED_HZ_S
    poisonedWindow = MAG_MAX_AGE_POLLS / _POISON_HZ_ABOVE_FLOOR
    assert bridge._magMaxAgeS != poisonedWindow


@pytest.mark.parametrize(
    ("ageS", "paired"),
    [
        (0.0, True),
        (_BURST_INTERVAL_S, True),
        (_EXPECTED_PAIRING_WINDOW_AT_4HZ_S, True),
        (_EXPECTED_PAIRING_WINDOW_AT_4HZ_S + _BURST_INTERVAL_S, False),
    ],
)
def test_bridgeAtFourHz_magAndGyroPairUpToTheWindowEdge(ageS: float, paired: bool):
    """
    Given: the bridge at 4 Hz holding one mag and one gyro reading at t=0
    When: an accel burst arrives ``ageS`` later
    Then: both pair up to and including 1.25 s and neither pairs one burst past
          it -- the same boundary for both, since they share one window
    """
    bridge = ImuStateBridge(None, "unused", sampleHz=_SAMPLE_HZ, stateHz=_STATE_HZ)
    bridge.handleSample(_imu("mag", _NORTH_FIELD, seq=1, capture=0.0))
    bridge.handleSample(_imu("gyro", _STILL, seq=1, capture=0.0))

    assert (bridge._freshMag(ageS) is not None) is paired
    assert (bridge._freshGyro(ageS) is not None) is paired


def test_bridgeAtFourOne_everyDisplayWriteCarriesAPairedHeading():
    """
    Given: the bridge at sampleHz 4 / stateHz 1, fed full accel+gyro+mag bursts
           every 0.25 s for 3 s
    When: the display writes (one per second)
    Then: every write carries a live heading -- pairing is judged against the
          burst that triggered the write, so the 1 s display interval does not
          starve the 1.25 s pairing window
    """
    bridge = _RecordingBridge(None, "unused", sampleHz=_SAMPLE_HZ, stateHz=_STATE_HZ)

    for seq in range(3 * _SAMPLE_HZ):
        capture = seq * _BURST_INTERVAL_S
        bridge.handleSample(_imu("mag", _NORTH_FIELD, seq, capture))
        bridge.handleSample(_imu("gyro", _STILL, seq, capture))
        bridge.handleSample(_imu("accel", _LEVEL, seq, capture))

    assert len(bridge.writes) == 3
    assert all(w["headingDeg"] is not None for w in bridge.writes)
    assert all("headingDeg" not in w["reasons"] for w in bridge.writes)
