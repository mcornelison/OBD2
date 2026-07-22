################################################################################
# File Name: test_display_autodim_config.py
# Purpose/Description: US-483-b tests for the pi.display.autoDim.* config keys --
#   the GROUNDED, PARAMETERIZED auto-dim curve the carousel brightness consumer
#   reads (CIO 2026-07-22: "a parameter, not hard-coded"). Confirms the validator
#   ships grounded defaults for every key AND rejects unsafe values (the alarm
#   floor + brightness levels must stay in [0,1]; luxMin/luxFull must be positive
#   with luxFull > luxMin) so a misconfiguration can never silently produce an
#   illegible screen or an un-flooring alarm. The keys live under pi.display.autoDim
#   (a NEW nested object) -- NOT pi.display.brightness, which is the live 0-100
#   hardware-backlight scalar (adafruit adapter / power_display dimming).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-22    | Ralph (Rex)  | Initial -- US-483-b pi.display.autoDim.* config.
# ================================================================================
################################################################################

"""US-483-b tests for the pi.display.autoDim.* grounded auto-dim config keys."""

import copy

import pytest

from common.config.validator import ConfigValidationError, ConfigValidator

# The grounded defaults the validator must apply (mirrors config.json).
_EXPECTED_DEFAULTS = {
    "pi.display.autoDim.luxMin": 3.0,
    "pi.display.autoDim.luxFull": 1000.0,
    "pi.display.autoDim.minLevel": 0.15,
    "pi.display.autoDim.defaultLevel": 0.70,
    "pi.display.autoDim.alarmFloorLevel": 0.40,
    "pi.display.autoDim.luxStaleSec": 10,
    "pi.display.autoDim.curve": "logarithmic",
}


def _minimalConfig() -> dict:
    """A minimal VALID config the validator accepts (defaults fill the rest).

    Includes the required top-level sections (pi, server) so validation only
    fails on the pi.display.autoDim value under test -- never vacuously on an
    unrelated missing-section error.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "test-device",
        "pi": {},
        "server": {"ai": {}, "database": {}, "api": {}},
    }


def _get(config: dict, dotted: str):
    node = config
    for part in dotted.split("."):
        node = node[part]
    return node


class TestDisplayAutoDimDefaults:
    def test_defaults_applied_whenAbsent(self):
        """Every pi.display.autoDim.* key gets its grounded default when absent."""
        validator = ConfigValidator()
        config = validator.validate(_minimalConfig())
        for dotted, expected in _EXPECTED_DEFAULTS.items():
            assert _get(config, dotted) == expected, dotted

    def test_explicitValue_preserved(self):
        """An explicit config value overrides the default (tuning is config)."""
        validator = ConfigValidator()
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": {"minLevel": 0.05}}}
        config = validator.validate(raw)
        assert _get(config, "pi.display.autoDim.minLevel") == 0.05
        # untouched keys still get their defaults
        assert _get(config, "pi.display.autoDim.defaultLevel") == 0.70


class TestDisplayAutoDimValidation:
    @pytest.mark.parametrize(
        "key,bad",
        [
            ("pi.display.autoDim.minLevel", 1.5),
            ("pi.display.autoDim.defaultLevel", -0.1),
            ("pi.display.autoDim.alarmFloorLevel", 2.0),
            ("pi.display.autoDim.alarmFloorLevel", "high"),
        ],
    )
    def test_levelOutOfUnitInterval_rejected(self, key, bad):
        validator = ConfigValidator()
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": {}}}
        # Set the one bad key via its leaf name.
        raw["pi"]["display"]["autoDim"][key.split(".")[-1]] = bad
        with pytest.raises(ConfigValidationError):
            validator.validate(raw)

    def test_luxFullNotAboveLuxMin_rejected(self):
        validator = ConfigValidator()
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": {"luxMin": 500.0, "luxFull": 100.0}}}
        with pytest.raises(ConfigValidationError):
            validator.validate(raw)

    def test_nonPositiveLuxMin_rejected(self):
        validator = ConfigValidator()
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": {"luxMin": 0.0}}}
        with pytest.raises(ConfigValidationError):
            validator.validate(raw)

    def test_groundedDefaults_passValidation(self):
        """The shipped grounded defaults are themselves valid (no self-own)."""
        validator = ConfigValidator()
        config = validator.validate(copy.deepcopy(_minimalConfig()))
        # A second validate of the already-defaulted config must not raise.
        validator.validate(config)
