################################################################################
# File Name: test_imu_state_chip_temp.py
# Purpose/Description: Unit tests for states/imu chipTempC (US-894-h, F-127):
#     the ICM-20948 DIE temperature in degC at 1 dp, or null with a reason. The
#     bridge holds the latest raw.imu.temp and pairs it with the accel being
#     written by capture age (the _freshGyro rule). chipTempC is NOT a derived
#     field: tilt_unresolved keeps it; only unavailableReason nulls it (Atlas
#     ruling 2026-10-27, CORRECTION 2).
# Author: Rex (US-894-h)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Unit tests for states/imu chipTempC (US-894-h)."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from pi.bus.bus import SampleBus
from pi.bus.sample import Sample
from pi.sensors import imu_state_bridge, sensor_reader
from pi.sensors.imu_state_bridge import (
    _DERIVED_FIELDS,
    REASON_NO_READING,
    REASON_SENSOR_ABSENT,
    REASON_TILT_UNRESOLVED,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_TEMP,
    ImuStateBridge,
    buildImuState,
    createImuStateBridgeFromConfig,
)
from tests.pi.sensors.test_imu_state_bridge import (
    _EXPECTED_KEYS,
    _accel,
    _config,
    _gate,
    _level,
    _presence,
    _readState,
)

_TS = "2026-10-27T15:00:00Z"


def _temp(value, *, capture: float) -> Sample:
    """One raw.imu.temp sample, as ImuReader publishes it after the accel."""
    return Sample(
        topic=TOPIC_IMU_TEMP,
        source="imu",
        value=value,
        unit=sensor_reader.UNIT_TEMP,
        tsUtc=_TS,
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=1,
    )


def _live(**kwargs):
    return buildImuState(tsUtc=_TS, gravity=_level(), linear=(0.0, 0.0, 0.0), **kwargs)


# ------------------------------------------------------------------ buildImuState


def test_imu_state_publishes_chip_temp_c():
    """
    Given: the builder with and without a supplied chipTempC
    When: states/imu is assembled
    Then: 41.26 -> 41.3; None -> null + no_reading; unavailable -> null + that
          reason; gravity None + 41.26 -> 41.3; omitted -> exactly today's payload
    """
    paired = _live(chipTempC=41.26)
    assert paired["chipTempC"] == 41.3
    assert "chipTempC" not in paired["reasons"]
    assert set(paired) == _EXPECTED_KEYS | {"chipTempC"}

    stale = _live(chipTempC=None)
    assert stale["chipTempC"] is None
    assert stale["reasons"]["chipTempC"] == REASON_NO_READING

    absent = buildImuState(
        tsUtc=_TS, unavailableReason=REASON_SENSOR_ABSENT, chipTempC=41.26
    )
    assert "chipTempC" in absent and absent["chipTempC"] is None
    assert absent["reasons"]["chipTempC"] == REASON_SENSOR_ABSENT

    tilted = buildImuState(tsUtc=_TS, gravity=None, chipTempC=41.26)
    assert tilted["reasons"]["gLat"] == REASON_TILT_UNRESOLVED
    assert tilted["chipTempC"] == 41.3
    assert "chipTempC" not in tilted["reasons"]

    today = _live()
    assert set(today) == _EXPECTED_KEYS
    assert "chipTempC" not in today["reasons"]
    withTemp = dict(paired)
    del withTemp["chipTempC"]
    assert withTemp == today


def test_chipTempC_isNotADerivedField_soNoBlanketOrGateCanNullIt():
    assert "chipTempC" not in _DERIVED_FIELDS
    gated = _live(chipTempC=41.26, fieldReasons={"chipTempC": "sensor_stale"})
    assert gated["chipTempC"] == 41.3
    assert "chipTempC" not in gated["reasons"]


def test_chipTempC_tiltUnresolved_nullTemp_isNoReading_notTheBlanket():
    tilted = buildImuState(tsUtc=_TS, gravity=None, chipTempC=None)
    assert tilted["chipTempC"] is None
    assert tilted["reasons"]["chipTempC"] == REASON_NO_READING


def test_chipTempC_gateRefusalReason_isCarriedVerbatim():
    refused = buildImuState(tsUtc=_TS, unavailableReason="sensor_stale", chipTempC=40.0)
    assert refused["chipTempC"] is None
    assert refused["reasons"]["chipTempC"] == "sensor_stale"


# ------------------------------------------------------------------------- bridge


def test_bridge_pairsTheHeldTemp_withTheAccelBeingWritten(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_temp(41.26, capture=0.0))
    bridge.handleSample(_accel(_level(), capture=0.02))
    state = _readState(tmp_path)
    assert state["chipTempC"] == 41.3
    assert "chipTempC" not in state["reasons"]


def test_bridge_noTempYet_isNullNoReading(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_accel(_level(), capture=0.0))
    state = _readState(tmp_path)
    assert state["chipTempC"] is None
    assert state["reasons"]["chipTempC"] == REASON_NO_READING


def test_bridge_tempOutsideThePairingWindow_isNullNoReading(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1, magMaxAgeSec=1.25)
    bridge.handleSample(_temp(41.26, capture=0.0))
    bridge.handleSample(_accel(_level(), capture=1.3))
    state = _readState(tmp_path)
    assert state["chipTempC"] is None
    assert state["reasons"]["chipTempC"] == REASON_NO_READING


def test_bridge_tempPublishedAsNone_isNullNoReading(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_temp(None, capture=0.0))
    bridge.handleSample(_accel(_level(), capture=0.02))
    state = _readState(tmp_path)
    assert state["chipTempC"] is None
    assert state["reasons"]["chipTempC"] == REASON_NO_READING


def test_bridge_nonFiniteTemp_isNullNoReading_neverAFailedWrite(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_temp(float("nan"), capture=0.0))
    bridge.handleSample(_accel(_level(), capture=0.02))
    state = _readState(tmp_path)
    assert state["chipTempC"] is None
    assert state["reasons"]["chipTempC"] == REASON_NO_READING


def test_bridge_sensorAbsent_isNullWithThatReason(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_temp(41.26, capture=0.0))
    bridge.handleSample(_presence(False, capture=0.01))
    state = _readState(tmp_path)
    assert "chipTempC" in state and state["chipTempC"] is None
    assert state["reasons"]["chipTempC"] == REASON_SENSOR_ABSENT


def test_bridge_accelGateRefusal_isNullWithTheGateReason(tmp_path: Path):
    bridge = ImuStateBridge(None, str(tmp_path), stateHz=1)
    bridge.handleSample(_temp(41.26, capture=0.0))
    bridge.handleSample(_gate(TOPIC_IMU_ACCEL, "sensor_stale"))
    state = _readState(tmp_path)
    assert state["chipTempC"] is None
    assert state["reasons"]["chipTempC"] == "sensor_stale"


def test_bridge_tempTopic_isTheProducersConstant_andIsSubscribed(tmp_path: Path):
    assert TOPIC_IMU_TEMP == sensor_reader.TOPIC_IMU_TEMP
    bridge = createImuStateBridgeFromConfig(_config(statesDir=str(tmp_path)), SampleBus())
    assert bridge is not None
    assert sensor_reader.TOPIC_IMU_TEMP in bridge._sub.topics  # noqa: SLF001


def test_chipTempC_isNamedTheDieTemperature_neverACabinReading():
    """The meaning is the ICM-20948 die (Atlas + Spool 2026-10-27)."""
    for source in (inspect.getsource(imu_state_bridge),):
        for line in source.splitlines():
            if "chipTemp" in line or "TOPIC_IMU_TEMP" in line:
                assert not re.search(r"cabin|interior|ambient", line, re.I), line
