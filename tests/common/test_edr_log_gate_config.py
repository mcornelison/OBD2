################################################################################
# File Name: test_edr_log_gate_config.py
# Purpose/Description: US-767-b -- pi.sensors.logGate.{enabled,preRollSec,holdSec}
#                      exist in validator DEFAULTS as true / 60 / 300 (Atlas's
#                      US-734 plan, Tasks 7-8), the two windows must be positive,
#                      and config.json carries all three.
# Author: Rex (US-767-b)
# Creation Date: 2026-09-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-18    | Rex (US-767-b) | Initial -- defaults, positive checks, config.
# ================================================================================
################################################################################
"""Tests for the pi.sensors.logGate config keys (US-767-b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.config.validator import ConfigValidationError, ConfigValidator

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _baseCfg(logGate: dict | None = None) -> dict:
    return {
        "protocolVersion": "1",
        "schemaVersion": "1",
        "deviceId": "d",
        "pi": {} if logGate is None else {"sensors": {"logGate": logGate}},
        "server": {},
    }


class TestLogGateDefaults:
    def test_validate_absentKeys_defaultTo_true_60_300(self) -> None:
        """
        Given: a config without pi.sensors.logGate
        When: it is validated
        Then: enabled True, preRollSec 60, holdSec 300
        """
        cfg = ConfigValidator().validate(_baseCfg())

        gate = cfg["pi"]["sensors"]["logGate"]
        assert gate == {"enabled": True, "preRollSec": 60, "holdSec": 300}

    def test_configJson_carriesTheThreeKeys(self) -> None:
        """
        Given: the shipped config.json
        When: it is read and validated
        Then: pi.sensors.logGate is true / 60 / 300 and validates
        """
        raw = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))

        assert raw["pi"]["sensors"]["logGate"] == {
            "enabled": True, "preRollSec": 60, "holdSec": 300,
        }


class TestLogGatePositive:
    @pytest.mark.parametrize("key", ["preRollSec", "holdSec"])
    @pytest.mark.parametrize("bad", [0, -1, -0.5, True, "60"])
    def test_validate_nonPositiveOrWrongType_rejected(self, key: str, bad: object) -> None:
        """
        Given: a pre-roll or hold that is zero, negative or not a number
        When: the config is validated
        Then: ConfigValidationError names the key
        """
        with pytest.raises(ConfigValidationError) as info:
            ConfigValidator().validate(_baseCfg({key: bad}))
        assert f"pi.sensors.logGate.{key}" in str(info.value)

    def test_validate_positive_kept(self) -> None:
        """A positive pre-roll and hold are kept as given."""
        cfg = ConfigValidator().validate(_baseCfg({"preRollSec": 30, "holdSec": 120.5}))

        gate = cfg["pi"]["sensors"]["logGate"]
        assert gate["preRollSec"] == 30
        assert gate["holdSec"] == 120.5
