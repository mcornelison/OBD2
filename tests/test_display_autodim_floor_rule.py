################################################################################
# File Name: test_display_autodim_floor_rule.py
# Purpose/Description: US-627 tests for the pi.display.autoDim FLOOR COUPLING --
#   the cross-field rule that pi.display.autoDim.defaultLevel must be >=
#   pi.display.autoDim.minLevel. brightnessLevel() has TWO branches: the curve
#   branch clamps to minLevel, the lux===null (absent/stale/saturated feed)
#   branch returns defaultLevel UNCLAMPED. So minLevel is a floor on the CURVE,
#   never on displayed brightness, and a dead sensor could render BELOW the floor
#   an operator just raised for legibility (FOUND 2026-08-29: minLevel went
#   0.5 -> 0.75 while defaultLevel stayed 0.70).
#
#   The rule is enforced at CONFIG time, deliberately NOT clamped at runtime
#   (US-627 AC-4: a runtime clamp HIDES a bad config instead of rejecting it --
#   the inert-guard shape this project has catalogued repeatedly). The runtime
#   half of that decision is pinned in tests/ui/test_carousel_brightness.py.
#
#   The rule is checked on the EFFECTIVE (post-default) config, because that is
#   what the panel resolves: an operator who raises minLevel alone leaves
#   defaultLevel on its default, which is exactly the incident above.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Ralph (Rex)  | Initial -- US-627 defaultLevel >= minLevel rule.
# ================================================================================
################################################################################

"""US-627 tests for the pi.display.autoDim defaultLevel >= minLevel floor rule."""

import json
import os
import re

import pytest

from common.config.validator import DEFAULTS, ConfigValidationError, ConfigValidator

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_JSON = os.path.join(_REPO_ROOT, "config.json")
_CAROUSEL_JS = os.path.join(
    _REPO_ROOT, "src", "pi", "ui", "dashboard", "carousel.js"
)

_MIN_KEY = "pi.display.autoDim.minLevel"
_DEFAULT_KEY = "pi.display.autoDim.defaultLevel"


def _minimalConfig(autoDim: dict | None = None) -> dict:
    """A minimal VALID config so validation only fails on the rule under test.

    Mirrors tests/test_display_autodim_config.py so a failure here can never be
    a vacuous "missing required section" error.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "test-device",
        "pi": {"display": {"autoDim": dict(autoDim or {})}},
        "server": {"ai": {}, "database": {}, "api": {}},
    }


def _autoDimOf(config: dict) -> dict:
    return config["pi"]["display"]["autoDim"]


class TestFloorRuleRejectsInversion:
    """defaultLevel below minLevel is refused loudly at validate time."""

    def test_explicitDefaultLevelBelowMinLevel_rejected(self):
        """
        Given: both levels set explicitly, with defaultLevel under the floor
        When: the config is validated
        Then: validation fails rather than shipping an illegible fallback
        """
        validator = ConfigValidator()
        raw = _minimalConfig({"minLevel": 0.75, "defaultLevel": 0.30})

        with pytest.raises(ConfigValidationError):
            validator.validate(raw)

    def test_defaultLevelLeftOnItsDefault_belowRaisedMinLevel_rejected(self):
        """
        Given: the 2026-08-29 incident -- minLevel raised to 0.75 ALONE, so
            defaultLevel silently stays on its grounded default of 0.70
        When: the config is validated
        Then: validation fails

        THE LOAD-BEARING CASE. The rule must run on the EFFECTIVE (post-default)
        config, because that is what the panel resolves. MEASURED before the fix:
        this config validated cleanly with minLevel=0.75 / defaultLevel=0.70.
        A rule that only compared EXPLICIT keys would miss the exact incident
        this story exists for.
        """
        validator = ConfigValidator()
        raw = _minimalConfig({"minLevel": 0.75})

        # Premise: the shipped default really is below the minLevel under test,
        # so this case cannot pass vacuously if the defaults are ever retuned.
        assert DEFAULTS[_DEFAULT_KEY] < 0.75

        with pytest.raises(ConfigValidationError):
            validator.validate(raw)

    def test_rejectionMessage_namesBothKeys(self):
        """
        Given: a config violating the floor rule
        When: validation fails
        Then: the message names BOTH keys and both values (US-627 VC-1)

        A message naming only one key sends the reader to the wrong half of a
        two-key coupling.
        """
        validator = ConfigValidator()
        raw = _minimalConfig({"minLevel": 0.75, "defaultLevel": 0.30})

        with pytest.raises(ConfigValidationError) as exc:
            validator.validate(raw)

        message = str(exc.value)
        assert "defaultLevel" in message
        assert "minLevel" in message
        assert "0.75" in message
        assert "0.3" in message

    def test_rejection_reportsTheOffendingFieldForRepair(self):
        """
        Given: a config violating the floor rule
        When: validation fails
        Then: missingFields carries the key an operator must edit
        """
        validator = ConfigValidator()
        raw = _minimalConfig({"minLevel": 0.75, "defaultLevel": 0.30})

        with pytest.raises(ConfigValidationError) as exc:
            validator.validate(raw)

        assert _DEFAULT_KEY in exc.value.missingFields


class TestFloorRuleAcceptsValidPairs:
    """The rule is a floor (>=), not a strict ordering, and stays narrow."""

    def test_defaultLevelEqualToMinLevel_accepted(self):
        """
        Given: defaultLevel exactly equal to minLevel
        When: the config is validated
        Then: it passes -- sitting ON the floor is not below it
        """
        validator = ConfigValidator()
        config = validator.validate(_minimalConfig({"minLevel": 0.75, "defaultLevel": 0.75}))

        assert _autoDimOf(config)["defaultLevel"] == 0.75

    def test_defaultLevelAboveMinLevel_accepted(self):
        """
        Given: defaultLevel above minLevel (the shipped shape)
        When: the config is validated
        Then: it passes and both values survive untouched
        """
        validator = ConfigValidator()
        config = validator.validate(_minimalConfig({"minLevel": 0.75, "defaultLevel": 1.0}))

        autoDim = _autoDimOf(config)
        assert autoDim["minLevel"] == 0.75
        assert autoDim["defaultLevel"] == 1.0

    def test_groundedDefaults_satisfyTheirOwnRule(self):
        """
        Given: a config that sets NO autoDim key at all
        When: the config is validated
        Then: the grounded defaults pass their own rule (no self-own)
        """
        validator = ConfigValidator()
        config = validator.validate(_minimalConfig())

        autoDim = _autoDimOf(config)
        assert autoDim["defaultLevel"] >= autoDim["minLevel"]

    def test_badlyTypedLevel_stillRaisesTheRangeError_notATypeError(self):
        """
        Given: a non-numeric defaultLevel alongside a numeric minLevel
        When: the config is validated
        Then: the existing [0.0, 1.0] range error is raised

        ORDERING GUARD. The cross-field comparison must never run before the
        per-key type/range checks, or a string value would raise TypeError from
        inside the validator instead of a ConfigValidationError an operator can
        read.
        """
        validator = ConfigValidator()
        raw = _minimalConfig({"minLevel": 0.75, "defaultLevel": "high"})

        with pytest.raises(ConfigValidationError) as exc:
            validator.validate(raw)

        assert "[0.0, 1.0]" in str(exc.value)


class TestShippedConfigHonoursTheFloor:
    """US-627 VC-2: the config.json actually on disk satisfies the rule."""

    def test_shippedAutoDimLevels_satisfyTheFloorRule(self):
        """
        Given: the pi.display.autoDim block from the committed config.json
        When: it is validated
        Then: it passes

        The regression test for the 2026-08-29 incident itself. It asserts the
        RELATIONSHIP, never the values, so it stays true as Iris retunes and goes
        red only if the two keys diverge again.
        """
        with open(_CONFIG_JSON, encoding="utf-8") as fh:
            shipped = json.load(fh)

        autoDim = shipped["pi"]["display"]["autoDim"]

        # Premise check: the block must still carry the two keys, or this test
        # would pass vacuously on a gutted config (US-609 inert-guard lesson).
        assert "minLevel" in autoDim
        assert "defaultLevel" in autoDim

        config = ConfigValidator().validate(_minimalConfig(autoDim))
        resolved = _autoDimOf(config)
        assert resolved["defaultLevel"] >= resolved["minLevel"]


class TestValidatorDefaultsMatchThePanelDefaults:
    """The rule's promise is about the PANEL, so the two default sets must agree."""

    @staticmethod
    def _panelDefaults() -> dict[str, float]:
        """Parse the numeric BRIGHTNESS_DEFAULTS block out of carousel.js."""
        with open(_CAROUSEL_JS, encoding="utf-8") as fh:
            source = fh.read()

        start = source.index("var BRIGHTNESS_DEFAULTS")
        end = source.index("\n  };", start)
        block = source[start:end]

        return {
            key: float(value)
            for key, value in re.findall(
                r"^\s*([A-Za-z]+):\s*(-?\d+(?:\.\d+)?),", block, re.M
            )
        }

    def test_levelDefaults_agreeBetweenValidatorAndCarousel(self):
        """
        Given: the validator DEFAULTS and the carousel BRIGHTNESS_DEFAULTS
        When: the two level defaults are compared
        Then: they are identical

        WHY THIS BELONGS TO US-627. The validator resolves a config against ITS
        defaults; the panel resolves the SAME raw config.json against the JS
        BRIGHTNESS_DEFAULTS (states_http_server injects the raw section, not the
        validated one). "defaultLevel >= minLevel" is therefore a true statement
        about the screen only while the two default sets agree. Let them drift
        and validate_config would green-light a config the panel still renders
        below its floor -- the same inert guard one level up.
        """
        panel = self._panelDefaults()

        # Premise: the parse found a real block, not an empty dict.
        assert "minLevel" in panel, panel
        assert "defaultLevel" in panel, panel

        assert panel["minLevel"] == DEFAULTS[_MIN_KEY]
        assert panel["defaultLevel"] == DEFAULTS[_DEFAULT_KEY]

    def test_panelDefaults_satisfyTheFloorRule(self):
        """
        Given: the carousel's own built-in fallback defaults
        When: the floor rule is applied to them
        Then: they satisfy it -- a config-less kiosk cannot render below its floor
        """
        panel = self._panelDefaults()

        assert panel["defaultLevel"] >= panel["minLevel"]
