################################################################################
# File Name: test_pitch_fusion_config_validation.py
# Purpose/Description: US-802-a -- the shipped config.json validates with no
#     error and no warning naming pi.sensors.imu, and the validator REJECTS a
#     wrong-typed value for each of the six pitch-fusion keys rather than
#     falling back to the default.
# Author: Rex (US-802-a)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-24    | Rex (US-802-a) | Initial -- shipped-config and wrong-type pins.
# 2026-10-19    | Rex (US-910)   | zuptWindowStops upper bound 999: 1000 rejected,
#               |                | 999 and 20 accepted.
# ================================================================================
################################################################################
"""Validator tests for the six pitch-fusion keys under pi.sensors.imu (US-802-a)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from src.common.config.validator import ConfigValidationError, ConfigValidator

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PITCH_FUSION_KEYS = (
    "pitchTauSec",
    "accelTrustBand",
    "zuptMinStopSec",
    "zuptSpeedMaxAgeSec",
    "zuptMinStops",
    "zuptWindowStops",
)


def _shippedConfig() -> dict[str, Any]:
    return json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def test_validate_shippedConfig_noErrorAndNoImuWarning(caplog: pytest.LogCaptureFixture):
    """
    Given: the shipped config.json
    When: it is validated
    Then: it passes, and no warning names pi.sensors.imu
    """
    with caplog.at_level(logging.WARNING):
        ConfigValidator().validate(_shippedConfig())

    imuWarnings = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and "pi.sensors.imu" in r.getMessage()
    ]
    assert imuWarnings == []


@pytest.mark.parametrize("key", _PITCH_FUSION_KEYS)
def test_validate_stringValue_rejectedNamingTheKey(key: str):
    """
    Given: the shipped config.json with one key set to a numeric-looking string
    When: it is validated
    Then: ConfigValidationError names the key -- no silent fallback to default
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"][key] = "5"

    with pytest.raises(ConfigValidationError) as info:
        ConfigValidator().validate(raw)

    assert f"pi.sensors.imu.{key}" in str(info.value)


def test_validate_zuptWindowStopsAboveMax_rejectedNamingKeyAndMax():
    """
    Given: the shipped config.json with zuptWindowStops = 1000
    When: it is validated
    Then: ConfigValidationError names pi.sensors.imu.zuptWindowStops and 999
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"]["zuptWindowStops"] = 1000

    with pytest.raises(ConfigValidationError) as info:
        ConfigValidator().validate(raw)

    message = str(info.value)
    assert "pi.sensors.imu.zuptWindowStops" in message
    assert "999" in message
    assert info.value.missingFields == ["pi.sensors.imu.zuptWindowStops"]


@pytest.mark.parametrize("stops", [999, 20])
def test_validate_zuptWindowStopsAtOrBelowMax_accepted(stops: int):
    """
    Given: the shipped config.json with zuptWindowStops = 999 (the bound) or 20 (shipped)
    When: it is validated
    Then: no error, and the value is kept as given
    """
    raw = _shippedConfig()
    raw["pi"]["sensors"]["imu"]["zuptWindowStops"] = stops

    result = ConfigValidator().validate(raw)

    assert result["pi"]["sensors"]["imu"]["zuptWindowStops"] == stops


def test_zuptWindowStopsMax_isTheMeasuredMotionWidth():
    """
    Given: the validator module
    When: its bound constant is read
    Then: it is 999 -- the stop count Motion's TILT FIX was measured against
    """
    from src.common.config import validator

    assert validator.ZUPT_WINDOW_STOPS_MAX == 999
