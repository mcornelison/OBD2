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
# Author: Rex (US-796-f)
# Creation Date: 2026-09-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-796-f: the rate-derived IMU consumers, pinned at 4 Hz / stateHz 1."""

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
    DEFAULT_MAG_MAX_AGE_S,
    IMU_BODY_FRAME,
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

# The shipped triple (US-796-b, CIO ruling 2026-09-21). Exact values.
_SAMPLE_HZ = 4
_STATE_HZ = 1

# The rate these windows were designed at before US-796-b.
_LEGACY_SAMPLE_HZ = 50

# A module default no config would ever carry. If a consumer resolves its rate
# from the default instead of from config, its derived window moves to this
# rate's value and the assertion names the defect.
_POISON_HZ = 1000

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


def test_imuReaderFromShippedConfig_gateRunLimitIsEight():
    """
    Given: the shipped config.json IMU section
    When: the reader is built through the production factory
    Then: its gate's run limit is the 4 Hz value (8), not the 50 Hz one (100)
    """
    readers = createSensorReadersFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert len(readers) == 1
    assert readers[0]._gate.invariantRunLimit == _EXPECTED_RUN_LIMIT_AT_4HZ


def test_imuReaderFromConfig_ignoresTheModuleDefaultRate(monkeypatch: pytest.MonkeyPatch):
    """
    Given: the module's fallback IMU rate poisoned to 1000 Hz
    When: the reader is built from a config that states sampleHz 4
    Then: the run limit is still 8 -- the rate came from config; had it come
          from the default the limit would be 2000
    """
    monkeypatch.setattr(readerModule, "DEFAULT_IMU_SAMPLE_HZ", _POISON_HZ)

    readers = createSensorReadersFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert readers[0]._gate.invariantRunLimit == _EXPECTED_RUN_LIMIT_AT_4HZ


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
# State bridge: the magnetometer/gyro pairing window at 4 Hz
# ---------------------------------------------------------------------------


def test_bridgeAtFourHz_pairingWindowIsOnePointTwoFiveSeconds():
    """
    Given: the bridge at the shipped 4 Hz sample rate
    When: the mag/gyro pairing window is derived
    Then: it is 1.25 s -- the magMaxAgeSec default (US-803-b), which is the
          5 polls * 0.25 s the window was counted in before the key carried seconds
    """
    bridge = ImuStateBridge(None, "unused", sampleHz=_SAMPLE_HZ, stateHz=_STATE_HZ)

    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_4HZ_S
    assert bridge._magMaxAgeS == DEFAULT_MAG_MAX_AGE_S == 5 * _BURST_INTERVAL_S


def test_bridgeFromShippedConfig_pairingWindowIsTheFourHzValue():
    """
    Given: the shipped config.json IMU section
    When: the bridge is built through the production factory
    Then: its pairing window is 1.25 s (4 Hz), not 0.1 s (50 Hz)
    """
    bridge = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert bridge is not None
    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_4HZ_S


def test_bridgeFromConfig_ignoresTheModuleDefaultRate(monkeypatch: pytest.MonkeyPatch):
    """
    Given: the bridge module's fallback IMU rate poisoned to 1000 Hz
    When: the bridge is built from a config that states sampleHz 4
    Then: the pairing window is still 1.25 s. Since US-803-b the window is the
          magMaxAgeSec key in seconds and no rate sizes it; before, a rate
          taken from the default would have made it 0.005 s and nothing paired
    """
    monkeypatch.setattr(bridgeModule, "DEFAULT_IMU_SAMPLE_HZ", _POISON_HZ)

    bridge = createImuStateBridgeFromConfig(_busConfig(_shippedImu()), SampleBus())

    assert bridge is not None
    assert bridge._magMaxAgeS == _EXPECTED_PAIRING_WINDOW_AT_4HZ_S


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
