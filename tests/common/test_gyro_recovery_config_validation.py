################################################################################
# File Name: test_gyro_recovery_config_validation.py
# Purpose/Description: US-803-a -- the validator accepts the three gyro-recovery
#     keys under pi.sensors.imu and REJECTS a wrong-typed value for each rather
#     than falling back to the default. gyroRecoverySampleCount must be an
#     INTEGER (a float reaches range() and silently disables recovery), and
#     gyroFaultMinRadS is bounded above by the gyro's +/-500 dps full scale.
# Author: Rex (US-803-a)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Rex (US-803-a) | Initial -- accept, wrong-type, bound pins.
# ================================================================================
################################################################################
"""Validator tests for the three gyro-recovery keys under pi.sensors.imu (US-803-a)."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import pytest

from src.common.config.validator import (
    GYRO_FULL_SCALE_RAD_S,
    ConfigValidationError,
    ConfigValidator,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

_GYRO_RECOVERY_KEYS = (
    "gyroFaultMinRadS",
    "gyroRecoverySampleCount",
    "gyroRecoverySettleSec",
)


def _shippedConfig() -> dict[str, Any]:
    return json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def _rejects(key: str, value: Any) -> str:
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"][key] = value
    with pytest.raises(ConfigValidationError) as info:
        ConfigValidator().validate(raw)
    return str(info.value)


def test_validate_shippedConfig_noErrorAndNoWarningNamingTheKeys(
    caplog: pytest.LogCaptureFixture,
):
    """
    Given: the shipped config.json
    When: it is validated
    Then: it passes, and no warning names any of the three keys
    """
    with caplog.at_level(logging.WARNING):
        ConfigValidator().validate(_shippedConfig())

    named = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING
        and any(key in r.getMessage() for key in _GYRO_RECOVERY_KEYS)
    ]
    assert named == []


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("gyroFaultMinRadS", 0.35),
        ("gyroRecoverySampleCount", 7),
        ("gyroRecoverySettleSec", 0.25),
        ("gyroRecoverySettleSec", 2),
    ],
)
def test_validate_nonDefaultValue_accepted(key: str, value: Any):
    """
    Given: a well-typed non-default value for one key
    When: it is validated
    Then: it passes and the value is kept, not replaced by the default
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"][key] = value

    result = ConfigValidator().validate(raw)

    assert result["pi"]["sensors"]["imu"][key] == value


@pytest.mark.parametrize("key", _GYRO_RECOVERY_KEYS)
@pytest.mark.parametrize("value", ["5", True, [1], 0, -1])
def test_validate_wrongTypedOrNonPositive_rejectedNamingTheKey(key: str, value: Any):
    """
    Given: one key set to a string, bool, list, zero or negative
    When: it is validated
    Then: ConfigValidationError names the key -- no silent fallback to default
    """
    assert f"pi.sensors.imu.{key}" in _rejects(key, value)


def test_validate_fractionalSampleCount_rejected():
    """
    Given: gyroRecoverySampleCount = 2.5
    When: it is validated
    Then: it is rejected. A float reaches range(count) in _sampleGyro, raises
          TypeError, is swallowed by _recoverGyro and silently disables the
          recovery on every boot -- so it has to fail at the config boundary
    """
    assert "pi.sensors.imu.gyroRecoverySampleCount" in _rejects(
        "gyroRecoverySampleCount", 2.5
    )


def test_validate_integralFloatSampleCount_rejected():
    """
    Given: gyroRecoverySampleCount = 20.0
    When: it is validated
    Then: it is rejected -- range() refuses 20.0 exactly as it refuses 2.5
    """
    assert "pi.sensors.imu.gyroRecoverySampleCount" in _rejects(
        "gyroRecoverySampleCount", 20.0
    )


def test_fullScaleCeiling_isFiveHundredDegreesPerSecond():
    """
    Given: the gyro runs at +/-500 dps (GYRO_CONFIG_1 FS_SEL=1, read off the Pi)
    When: the ceiling constant is read
    Then: it is 500 deg/s in rad/s -- 8.727 to three places
    """
    assert GYRO_FULL_SCALE_RAD_S == math.radians(500)
    assert round(GYRO_FULL_SCALE_RAD_S, 3) == 8.727


def test_validate_faultThresholdAtFullScale_accepted():
    """
    Given: gyroFaultMinRadS exactly at the full-scale ceiling
    When: it is validated
    Then: it passes -- the bound excludes only values the gyro cannot reach
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"]["gyroFaultMinRadS"] = GYRO_FULL_SCALE_RAD_S

    ConfigValidator().validate(raw)


def test_validate_faultThresholdAboveFullScale_rejected():
    """
    Given: gyroFaultMinRadS above the gyro's +/-500 dps full scale
    When: it is validated
    Then: it is rejected -- the sensor can never report that rate, so fault
          detection would be silently OFF
    """
    message = _rejects("gyroFaultMinRadS", 9.0)

    assert "pi.sensors.imu.gyroFaultMinRadS" in message
    assert "full scale" in message
