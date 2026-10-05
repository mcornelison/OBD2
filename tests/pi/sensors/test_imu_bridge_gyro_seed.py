################################################################################
# File Name: test_imu_bridge_gyro_seed.py
# Purpose/Description: ARCH-066 (US-819) -- the bridge persists the AHRS's ZARU
#   gyro offset and seeds the next boot's engine with it, so a drive that leaves
#   before its first stop no longer integrates the full resting bias from zero.
# Author: Atlas (architect)
# Creation Date: 2026-10-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-04    | Atlas        | Initial (ARCH-066, CIO-directed build).
# ================================================================================
################################################################################

"""ARCH-066: GyroOffsetSeedStore + the bridge's seed load/persist wiring."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pi.bus.sample import Sample
from pi.sensors.ahrs_fusion import AhrsFusion
from pi.sensors.imu_state_bridge import (
    SEED_PERSIST_MIN_INTERVAL_S,
    STANDARD_GRAVITY_MS2,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_GYRO,
    TOPIC_OBD_SPEED,
    GyroOffsetSeedStore,
    ImuStateBridge,
    createImuStateBridgeFromConfig,
    resolveMountFrame,
)

HZ = 50.0
LEVEL = (0.0, 0.0, STANDARD_GRAVITY_MS2)
BIAS_RAD = tuple(float(x) for x in np.radians([-0.2, 0.7, 0.15]))


def _toRaw(vehicle):
    cols = [resolveMountFrame(e) for e in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))]
    return tuple(sum(cols[c][r] * vehicle[r] for r in range(3)) for c in range(3))


def _sample(topic: str, value: Any, capture: float, seq: int = 1) -> Sample:
    return Sample(topic=topic, source="imu", value=value, unit="", tsUtc="2026-10-04T00:00:00Z",
                  tsCapture=capture, driveId=None, dataSource="real", seq=seq)


def _parked(bridge: ImuStateBridge, seconds: float, startAt: float = 0.0) -> float:
    """Level, still, OBD SPEED 0 every second; gyro = the measured resting bias."""
    capture = startAt
    nextSpeed = startAt
    for i in range(int(seconds * HZ)):
        capture = startAt + i / HZ
        if capture >= nextSpeed:
            bridge.handleSample(_sample(TOPIC_OBD_SPEED, 0.0, capture))
            nextSpeed = capture + 1.0
        bridge.handleSample(_sample(TOPIC_IMU_GYRO, _toRaw(BIAS_RAD), capture, i + 1))
        bridge.handleSample(_sample(TOPIC_IMU_ACCEL, _toRaw(LEVEL), capture, i + 1))
    return capture + 1.0 / HZ


def _config(statesDir: Path) -> dict:
    return {"pi": {"bus": {"enabled": True},
                   "sensors": {"imu": {"enabled": True, "sampleHz": 50, "stateHz": 50}},
                   "splash": {"statesDir": str(statesDir)}}}


class _NullBus:
    def subscribe(self, *_a, **_k):
        return None


# ------------------------------------------------------------------- the store
def test_store_roundTrip_isAtomic(tmp_path: Path) -> None:
    store = GyroOffsetSeedStore(tmp_path / "seed.json")
    assert store.save((-0.2, 0.7, 0.15), "2026-10-04T21:00:00Z") is True
    assert store.load() == pytest.approx((-0.2, 0.7, 0.15))
    assert [p.name for p in tmp_path.iterdir()] == ["seed.json"]  # no temp left behind
    body = json.loads((tmp_path / "seed.json").read_text(encoding="utf-8"))
    assert body["schemaVersion"] == 1 and body["savedUtc"] == "2026-10-04T21:00:00Z"


@pytest.mark.parametrize(
    "content",
    ["{not json", json.dumps({"schemaVersion": 2, "offsetDps": [0, 0, 0]}),
     json.dumps({"schemaVersion": 1, "offsetDps": [0, 0]}), json.dumps([1, 2, 3])],
)
def test_store_load_refusesAnythingMalformed(tmp_path: Path, content: str) -> None:
    (tmp_path / "seed.json").write_text(content, encoding="utf-8")
    assert GyroOffsetSeedStore(tmp_path / "seed.json").load() is None


def test_store_absentFile_isNone_andAMissingDirectory_neverRaises(tmp_path: Path) -> None:
    store = GyroOffsetSeedStore(tmp_path / "missing-dir" / "seed.json")
    assert store.load() is None
    assert store.save((0.1, 0.1, 0.1), "2026-10-04T21:00:00Z") is False


# ------------------------------------------------------------- bridge wiring
def test_bridge_persistsTheZaruOffset_afterAStop(tmp_path: Path) -> None:
    store = GyroOffsetSeedStore(tmp_path / "seed.json")
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, stateHz=1,
                            pitchFusion=AhrsFusion(sampleHz=HZ), gyroSeedStore=store)
    _parked(bridge, 10.0)
    saved = store.load()
    assert saved is not None
    assert np.allclose(saved, (-0.2, 0.7, 0.15), atol=0.02)


def test_bridge_persistsAtMostOncePerInterval(tmp_path: Path) -> None:
    class _Counting(GyroOffsetSeedStore):
        saves = 0

        def save(self, offsetDps, savedUtc):  # noqa: D102
            type(self).saves += 1
            return super().save(offsetDps, savedUtc)

    store = _Counting(tmp_path / "seed.json")
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, stateHz=1,
                            pitchFusion=AhrsFusion(sampleHz=HZ), gyroSeedStore=store)
    t = _parked(bridge, SEED_PERSIST_MIN_INTERVAL_S - 2.0)  # several windows, one interval
    assert _Counting.saves == 1
    _parked(bridge, SEED_PERSIST_MIN_INTERVAL_S, startAt=t)
    assert _Counting.saves == 2


def test_factory_seedsTheEngine_fromTheStore(tmp_path: Path) -> None:
    seedPath = tmp_path / "seed.json"
    GyroOffsetSeedStore(seedPath).save((-0.2, 0.7, 0.15), "2026-10-04T21:00:00Z")
    bridge = createImuStateBridgeFromConfig(_config(tmp_path), _NullBus(), gyroSeedPath=str(seedPath))
    assert bridge is not None
    assert np.allclose(bridge._pitchFusion.gyroOffsetDps, (-0.2, 0.7, 0.15))  # noqa: SLF001


def test_factory_refusesAnImplausibleSeed_andStartsFromZero(tmp_path: Path) -> None:
    seedPath = tmp_path / "seed.json"
    GyroOffsetSeedStore(seedPath).save((0.0, 29.0, 0.0), "2026-10-04T21:00:00Z")  # a latched rate
    bridge = createImuStateBridgeFromConfig(_config(tmp_path), _NullBus(), gyroSeedPath=str(seedPath))
    assert bridge is not None
    assert bridge._pitchFusion.gyroOffsetDps == (0.0, 0.0, 0.0)  # noqa: SLF001


def test_pullingAway_persistsTheStopsFinalMean_atOnce(tmp_path: Path) -> None:
    """Inside the interval only the FIRST window would be saved; the stop's best
    mean must not wait an interval it may never get (power is lost at key-off)."""
    class _Counting(GyroOffsetSeedStore):
        saves = 0

        def save(self, offsetDps, savedUtc):  # noqa: D102
            type(self).saves += 1
            return super().save(offsetDps, savedUtc)

    store = _Counting(tmp_path / "seed.json")
    bridge = ImuStateBridge(None, str(tmp_path), sampleHz=50, stateHz=1,
                            pitchFusion=AhrsFusion(sampleHz=HZ), gyroSeedStore=store)
    t = _parked(bridge, 10.0)
    assert _Counting.saves == 1
    bridge.handleSample(_sample(TOPIC_OBD_SPEED, 12.0, t))
    assert _Counting.saves == 2
    assert store.load() == pytest.approx(bridge._pitchFusion.zaruOffsetDps)  # noqa: SLF001


def test_factoryBridge_writesTheSeedOffTheSampleThread(tmp_path: Path) -> None:
    seedPath = tmp_path / "seed.json"
    bridge = createImuStateBridgeFromConfig(_config(tmp_path), _NullBus(), gyroSeedPath=str(seedPath))
    assert bridge is not None
    _parked(bridge, 10.0)
    thread = bridge._seedSaveThread  # noqa: SLF001
    assert thread is not None and thread.name == "imu-gyro-seed-save"
    thread.join(timeout=5.0)
    assert GyroOffsetSeedStore(seedPath).load() is not None


def test_existingFactoryCallers_neverTouchTheRealSeedPath() -> None:
    """The autouse conftest fixture redirects the production default."""
    from pi.sensors import imu_state_bridge

    assert not imu_state_bridge.GYRO_OFFSET_SEED_PATH.startswith("/var/lib/")
