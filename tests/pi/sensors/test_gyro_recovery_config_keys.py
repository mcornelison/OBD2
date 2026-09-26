################################################################################
# File Name: test_gyro_recovery_config_keys.py
# Purpose/Description: US-803-a -- the three A-34 gyro-recovery tunables
#     (GYRO_FAULT_MIN_RAD_S, DEFAULT_SAMPLE_COUNT, DEFAULT_SETTLE_S) ship in
#     config.json under pi.sensors.imu at their module defaults, and each one is
#     proven LIVE on the real startup path: the shipped config.json, overridden
#     with a non-default value, validated, built into an ImuReader by
#     createSensorReadersFromConfig and taken through the reader's own device
#     factory (_makeIcm20948 -> _buildImuDevice -> _recoverGyro ->
#     recoverGyroIfFaulted) against a fake ICM, changes what the recovery DOES.
# Author: Rex (US-803-a)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Rex (US-803-a) | Initial -- override, absent and no-change pins.
# ================================================================================
################################################################################
"""Tests that the three gyro-recovery config keys reach the startup recovery."""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from common.config.validator import DEFAULTS, ConfigValidator
from pi.bus.bus import SampleBus
from pi.sensors import gyro_recovery, sensor_reader
from pi.sensors.gyro_recovery import REG_PWR_MGMT_2
from pi.sensors.sensor_reader import ImuReader, createSensorReadersFromConfig

_REPO_ROOT = Path(__file__).resolve().parents[3]

# The module defaults, read from gyro_recovery itself and never restated, so a
# test can only pass when config.json and the validator agree with the code.
_MODULE_DEFAULTS: dict[str, Any] = {
    "gyroFaultMinRadS": gyro_recovery.GYRO_FAULT_MIN_RAD_S,
    "gyroRecoverySampleCount": gyro_recovery.DEFAULT_SAMPLE_COUNT,
    "gyroRecoverySettleSec": gyro_recovery.DEFAULT_SETTLE_S,
}

# A constant rate between the shipped threshold (0.10) and the override (0.50):
# the default detector calls it a fault, the overridden one does not.
_MID_RATE_RAD_S = 0.30
# Comfortably above either threshold -- the 14-30 deg/s latch is 0.24-0.52 rad/s.
_FAULTED_RATE_RAD_S = 0.55
_HEALTHY_RATE_RAD_S = 0.014


class _FakeI2cDevice:
    """Records register writes; mimics adafruit's I2CDevice context manager."""

    def __init__(self) -> None:
        self.writes: list[tuple[int, int]] = []

    def __enter__(self) -> _FakeI2cDevice:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def write(self, payload: bytes) -> None:
        self.writes.append((payload[0], payload[1]))


class _FakeIcm:
    """An ICM-20948 with a constant gyro rate that counts every gyro read."""

    def __init__(self, rateRadS: float) -> None:
        self._rate = rateRadS
        self.gyroReads = 0
        self.i2c_device = _FakeI2cDevice()
        self._bank = 0

    @property
    def gyro(self) -> tuple[float, float, float]:
        self.gyroReads += 1
        return (self._rate, 0.0, 0.0)

    @property
    def pwrMgmt2Writes(self) -> list[tuple[int, int]]:
        return [w for w in self.i2c_device.writes if w[0] == REG_PWR_MGMT_2]


def _shippedConfig() -> dict[str, Any]:
    return json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def _runStartupRecovery(
    raw: dict[str, Any], rateRadS: float, monkeypatch: pytest.MonkeyPatch
) -> tuple[_FakeIcm, list[float]]:
    """Validate ``raw``, build the ImuReader, and run its real device factory.

    Only the hardware edges are faked: the adafruit driver module, the I2C bus
    and the magnetometer bypass. Everything between the reader and the register
    writes is the production code path.

    Returns:
        The fake ICM (for read/write counts) and every ``time.sleep`` duration
        the recovery requested.
    """
    config = ConfigValidator().validate(copy.deepcopy(raw))
    config["pi"]["bus"]["enabled"] = True
    config["pi"]["sensors"]["imu"]["enabled"] = True
    config["pi"]["sensors"]["light"]["enabled"] = False
    readers = createSensorReadersFromConfig(config, SampleBus())
    (reader,) = [r for r in readers if isinstance(r, ImuReader)]

    icm = _FakeIcm(rateRadS)
    fakeDriver = types.ModuleType("adafruit_icm20x")
    fakeDriver.ICM20948 = lambda _bus, address: icm  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "adafruit_icm20x", fakeDriver)
    monkeypatch.setattr(sensor_reader, "_makeI2c", lambda: "i2c-bus")
    monkeypatch.setattr(sensor_reader, "_attachDirectMagnetometer", lambda dev, _bus: dev)
    sleeps: list[float] = []
    monkeypatch.setattr(gyro_recovery.time, "sleep", sleeps.append)

    reader._defaultDeviceFactory()  # noqa: SLF001 -- the real startup path

    return icm, sleeps


def test_configJson_carriesAllThreeKeysAtTheModuleDefaults():
    """
    Given: the shipped config.json
    When: pi.sensors.imu is read
    Then: all three keys are present, each equal to (and the same type as) the
          gyro_recovery module default
    """
    imu = _shippedConfig()["pi"]["sensors"]["imu"]

    for key, default in _MODULE_DEFAULTS.items():
        assert key in imu, key
        assert imu[key] == default, key
        assert type(imu[key]) is type(default), key


def test_validatorDefaults_matchTheModuleDefaults():
    """
    Given: the validator's DEFAULTS
    When: the three gyro-recovery entries are read
    Then: each equals the gyro_recovery module default -- an absent key changes
          nothing
    """
    for key, default in _MODULE_DEFAULTS.items():
        assert DEFAULTS[f"pi.sensors.imu.{key}"] == default, key


def test_gyroFaultMinRadS_override_isTheThresholdTheStartupCheckUses(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Given: a stationary gyro reading a constant 0.30 rad/s, and
           gyroFaultMinRadS overridden to 0.50
    When: the ImuReader's startup path runs
    Then: the gyro is judged healthy and NOT power-cycled -- under the 0.10
          module default the same readings would be a fault
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"]["gyroFaultMinRadS"] = 0.50

    icm, _sleeps = _runStartupRecovery(raw, _MID_RATE_RAD_S, monkeypatch)

    assert icm.pwrMgmt2Writes == []


def test_gyroFaultMinRadS_shipped_powerCyclesTheSameReadings(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Given: the same 0.30 rad/s gyro and the shipped config.json
    When: the startup path runs
    Then: the recovery power-cycles the gyro -- the control for the override
          test, proving the 0.30 rate is a fault at the shipped threshold
    """
    icm, _sleeps = _runStartupRecovery(_shippedConfig(), _MID_RATE_RAD_S, monkeypatch)

    assert icm.pwrMgmt2Writes != []


def test_gyroRecoverySampleCount_override_isHowManyReadsTheCheckTakes(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Given: a healthy gyro and gyroRecoverySampleCount overridden to 7
    When: the startup path runs
    Then: the check reads the gyro exactly 7 times, not the module's 20
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"]["gyroRecoverySampleCount"] = 7

    icm, _sleeps = _runStartupRecovery(raw, _HEALTHY_RATE_RAD_S, monkeypatch)

    assert icm.gyroReads == 7


def test_gyroRecoverySettleSec_override_isTheSettleTheCycleWaits(
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Given: a latched gyro and gyroRecoverySettleSec overridden to 0.25
    When: the startup path runs and power-cycles the gyro
    Then: both settle waits are 0.25 s, not the module's 1.0 s
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"]["gyroRecoverySettleSec"] = 0.25

    icm, sleeps = _runStartupRecovery(raw, _FAULTED_RATE_RAD_S, monkeypatch)

    assert icm.pwrMgmt2Writes != []
    assert sleeps == [0.25, 0.25]


def test_shippedConfig_behavesExactlyAsTheModuleDefaults(monkeypatch: pytest.MonkeyPatch):
    """
    Given: the shipped config.json and a latched gyro
    When: the startup path runs
    Then: it takes DEFAULT_SAMPLE_COUNT reads each side of the cycle and waits
          DEFAULT_SETTLE_S twice -- adding the keys changed no shipped behaviour
    """
    icm, sleeps = _runStartupRecovery(_shippedConfig(), _FAULTED_RATE_RAD_S, monkeypatch)

    assert icm.gyroReads == 2 * gyro_recovery.DEFAULT_SAMPLE_COUNT
    assert sleeps == [gyro_recovery.DEFAULT_SETTLE_S] * 2


@pytest.mark.parametrize("key", list(_MODULE_DEFAULTS))
def test_keyAbsent_startupPathBehavesAsTheModuleDefaults(
    key: str, monkeypatch: pytest.MonkeyPatch
):
    """
    Given: the shipped config.json with one of the three keys removed
    When: the startup path runs against a latched gyro
    Then: it behaves exactly as the module defaults
    """
    raw = _shippedConfig()
    del raw["pi"]["sensors"]["imu"][key]

    icm, sleeps = _runStartupRecovery(raw, _FAULTED_RATE_RAD_S, monkeypatch)

    assert icm.pwrMgmt2Writes != []
    assert icm.gyroReads == 2 * gyro_recovery.DEFAULT_SAMPLE_COUNT
    assert sleeps == [gyro_recovery.DEFAULT_SETTLE_S] * 2
