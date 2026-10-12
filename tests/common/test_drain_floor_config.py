################################################################################
# File Name: test_drain_floor_config.py
# Purpose/Description: US-776-b -- pi.powerWatch.drainFloorVolts, the drain's own
#                      stopping point, exists in DEFAULTS and config.json with
#                      the same range check as vcellFloorVolts, which stays
#                      untouched as the pre-pipeline emergency backstop.
# Author: Rex (US-776-b)
# Creation Date: 2026-09-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-17    | Rex (US-776-b) | Initial -- default, range checks, config.json.
# ================================================================================
################################################################################
"""Tests for the pi.powerWatch.drainFloorVolts config key (US-776-b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.config.validator import ConfigValidationError, ConfigValidator

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _baseCfg(powerWatch: dict | None = None) -> dict:
    return {
        "protocolVersion": "1",
        "schemaVersion": "1",
        "deviceId": "d",
        "pi": {} if powerWatch is None else {"powerWatch": powerWatch},
        "server": {},
    }


class TestDrainFloorDefault:
    def test_validate_absentKey_defaultsTo360_andVcellFloorStays350(self) -> None:
        """
        Given: a config without pi.powerWatch
        When: it is validated
        Then: drainFloorVolts defaults to the provisional 3.60 V and
            vcellFloorVolts is still the 3.50 V backstop
        """
        # Act
        cfg = ConfigValidator().validate(_baseCfg())

        # Assert
        pw = cfg["pi"]["powerWatch"]
        assert pw["drainFloorVolts"] == 3.60
        assert pw["vcellFloorVolts"] == 3.50

    def test_configJson_carriesDrainFloor360(self) -> None:
        """
        Given: the shipped config.json
        When: it is read
        Then: pi.powerWatch.drainFloorVolts is 3.60 and validates
        """
        # Arrange
        raw = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))

        # Assert
        assert raw["pi"]["powerWatch"]["drainFloorVolts"] == 3.60


class TestDrainFloorRange:
    @pytest.mark.parametrize("bad", [2.5, 3.0, 4.3, 5.0, -1, True, "3.6"])
    def test_validate_outOfRangeOrWrongType_rejected(self, bad: object) -> None:
        """
        Given: drainFloorVolts outside (3.0, 4.3) V, or not a number
        When: the config is validated
        Then: ConfigValidationError names the key
        """
        # Act / Assert
        with pytest.raises(ConfigValidationError) as info:
            ConfigValidator().validate(_baseCfg({"drainFloorVolts": bad}))
        assert "pi.powerWatch.drainFloorVolts" in str(info.value)

    def test_validate_inRange_accepted(self) -> None:
        """
        Given: an in-range drainFloorVolts
        When: the config is validated
        Then: the value is kept as given
        """
        # Act
        cfg = ConfigValidator().validate(_baseCfg({"drainFloorVolts": 3.65}))

        # Assert
        assert cfg["pi"]["powerWatch"]["drainFloorVolts"] == 3.65

    def test_validate_vcellFloorOutOfRange_stillRejectedByName(self) -> None:
        """
        Given: an out-of-range vcellFloorVolts (the backstop's check is shared)
        When: the config is validated
        Then: the error still names vcellFloorVolts
        """
        # Act / Assert
        with pytest.raises(ConfigValidationError) as info:
            ConfigValidator().validate(_baseCfg({"vcellFloorVolts": 2.5}))
        assert "pi.powerWatch.vcellFloorVolts" in str(info.value)
