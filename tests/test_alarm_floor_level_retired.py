################################################################################
# File Name: test_alarm_floor_level_retired.py
# Purpose/Description: US-595 guards for the RETIREMENT of
#   pi.display.autoDim.alarmFloorLevel -- a tunable that resolved cleanly,
#   validated cleanly, and changed nothing. US-484-b (Spool 6d ch.4) made a live
#   STOP alarm FULL brightness always, so brightnessLevel() short-circuits on
#   `alarmActive` BEFORE any ambient math runs; the one condition that ever
#   consumed the alarm floor became the one condition that returns 1.0. The key
#   was left resolvable as a compatibility shim and never removed.
#
#   This file pins the removal ACROSS ALL FOUR PRODUCTION SITES AT ONCE
#   (config.json, the validator DEFAULTS registry, the validator range loop,
#   carousel.js BRIGHTNESS_DEFAULTS), because a HALF-removal is worse than no
#   removal: it is the state in which one tier still advertises the tunable.
#   US-627's default-parity test compares only minLevel/defaultLevel BY NAME and
#   cannot see this key at all (US-595 AC-8, measured), so the coupling needed
#   its own guard rather than an assumed one.
#
#   EVERY absence assertion here is paired with a PREMISE CHECK that the SIBLING
#   keys are still present at the same site. An "X is not in Y" assertion passes
#   vacuously the moment Y is renamed, gutted or fails to parse -- the inert-guard
#   shape this project has catalogued repeatedly (US-609, US-604, US-620).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-30    | Ralph (Rex)  | Initial -- US-595 alarmFloorLevel retirement.
# ================================================================================
################################################################################

"""US-595 guards: pi.display.autoDim.alarmFloorLevel is retired from all sites."""

import json
import re
from pathlib import Path

import pytest

from common.config.validator import (
    DEFAULTS,
    ConfigValidationError,
    ConfigValidator,
)
from tests.ui.test_carousel_brightness import _TS, _TS_MS, _probe, nodeless

# The retired key, in both the renderings it ever had: the validator's dotted
# path and the leaf name the browser receives.
_RETIRED_DOTTED = "pi.display.autoDim.alarmFloorLevel"
_RETIRED_LEAF = "alarmFloorLevel"

# The SIBLING keys that must survive. These are the premise of every assertion
# below -- if these are missing, the site did not parse (or was gutted) and an
# absence check would be meaningless rather than reassuring.
_SURVIVING_LEAVES = ("minLevel", "defaultLevel", "luxMin", "luxFull", "curve")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_JSON = _REPO_ROOT / "config.json"
_CAROUSEL_JS = _REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "carousel.js"

# An ALREADY-DEPLOYED config.json: it still carries the retired key, because a
# Pi in the field was imaged before this story. US-595 AC-6 / VC-2 -- removal
# must not break resolution on such an overlay.
_OLD_OVERLAY = {
    "luxMin": 3.0,
    "luxFull": 1000.0,
    "minLevel": 0.15,
    "defaultLevel": 0.70,
    "alarmFloorLevel": 0.40,
    "luxStaleSec": 10,
    "curve": "logarithmic",
}


def _minimalConfig() -> dict:
    """A minimal config the validator accepts, so failures are never vacuous.

    Mirrors tests/test_display_autodim_config.py so the two files agree on what
    "a valid config" means.
    """
    return {
        "protocolVersion": "1.0.0",
        "schemaVersion": "1.0.0",
        "deviceId": "test-device",
        "pi": {},
        "server": {"ai": {}, "database": {}, "api": {}},
    }


def _shippedAutoDim() -> dict:
    """The pi.display.autoDim object as SHIPPED in config.json."""
    with open(_CONFIG_JSON, encoding="utf-8") as fh:
        return json.load(fh)["pi"]["display"]["autoDim"]


def _brightnessDefaultsLiteral() -> dict[str, str]:
    """Parse the BRIGHTNESS_DEFAULTS object literal out of carousel.js.

    Returns a mapping of key -> raw value text. Deliberately a SOURCE read that
    needs no node, so the carousel half of the four-site coupling is still
    guarded on a bench without a JS runtime -- a guard that silently skips is a
    guard that is not there. The node probe below checks the same property
    behaviourally; two independent routes to one fact.
    """
    source = _CAROUSEL_JS.read_text(encoding="utf-8")
    match = re.search(
        r"var\s+BRIGHTNESS_DEFAULTS\s*=\s*\{(.*?)\n\s*\};",
        source,
        re.DOTALL,
    )
    assert match, "BRIGHTNESS_DEFAULTS literal not found in carousel.js"
    body = match.group(1)
    # Strip // comments before reading keys: the retirement leaves prose behind
    # that legitimately NAMES the key, and a raw-text scan would read that as a
    # live entry (US-572: two guards on one rule must read the file the same way).
    stripped = "\n".join(re.sub(r"//.*$", "", line) for line in body.splitlines())
    return {
        m.group(1): m.group(2).strip()
        for m in re.finditer(r"^\s*(\w+)\s*:\s*([^,\n]+)", stripped, re.MULTILINE)
    }


# ---------------------------------------------------------------------------
# THE FOUR-SITE COUPLING -- the guard US-595 AC-8 requires. A half-removal is
# the failure mode this file exists for, so it gets one test that sees all four
# sites at once and NAMES the ones still carrying the key.
# ---------------------------------------------------------------------------


class TestFourSiteRemovalCoupling:
    def test_alarmFloorLevel_absentFromEveryProductionSite(self):
        """
        Given: the four production sites that carried alarmFloorLevel
        When: each is read for the key
        Then: none carries it -- and a partial removal names the survivors
        """
        # Arrange -- read all four sites the way each is actually consumed.
        validator = ConfigValidator()
        resolved = validator.validate(_minimalConfig())
        sites = {
            "config.json": set(_shippedAutoDim()),
            "validator.py DEFAULTS": {
                key.rsplit(".", 1)[-1]
                for key in DEFAULTS
                if key.startswith("pi.display.autoDim.")
            },
            "validator.py applied output": set(
                resolved["pi"]["display"]["autoDim"]
            ),
            "carousel.js BRIGHTNESS_DEFAULTS": set(_brightnessDefaultsLiteral()),
        }

        # PREMISE -- every site must still carry the surviving siblings. Without
        # this, an empty/failed parse would satisfy the assertion below while
        # checking nothing at all.
        for name, leaves in sites.items():
            missing = [k for k in ("minLevel", "defaultLevel") if k not in leaves]
            assert not missing, (
                f"premise failed: {name} no longer carries {missing} -- this "
                f"guard cannot report on alarmFloorLevel from a site it did "
                f"not successfully read"
            )

        # Act
        stillPresent = sorted(
            name for name, leaves in sites.items() if _RETIRED_LEAF in leaves
        )

        # Assert
        assert not stillPresent, (
            f"alarmFloorLevel is RETIRED (US-595) but is still live at: "
            f"{stillPresent}. All sites move together -- a key removed from "
            f"some tiers and advertised by others is the false affordance this "
            f"story exists to delete."
        )


# ---------------------------------------------------------------------------
# THE PYTHON TIER
# ---------------------------------------------------------------------------


class TestValidatorNoLongerKnowsTheKey:
    def test_notInDefaultsRegistry(self):
        """
        Given: the validator DEFAULTS registry
        When: it is searched for the retired dotted path
        Then: it is absent, while its siblings remain
        """
        # PREMISE: the autoDim block is still registered.
        for leaf in _SURVIVING_LEAVES:
            assert f"pi.display.autoDim.{leaf}" in DEFAULTS, leaf
        assert _RETIRED_DOTTED not in DEFAULTS

    def test_notAppliedAsADefault(self):
        """
        Given: a config with no pi.display.autoDim section at all
        When: the validator applies its defaults
        Then: the retired key is not conjured into existence
        """
        resolved = ConfigValidator().validate(_minimalConfig())
        autoDim = resolved["pi"]["display"]["autoDim"]
        # PREMISE: defaults really were applied to this section.
        assert autoDim["minLevel"] == 0.15
        assert autoDim["defaultLevel"] == 0.70
        assert _RETIRED_LEAF not in autoDim

    def test_noLongerRangeValidated(self):
        """
        Given: a config setting the RETIRED key to a wildly out-of-range value
        When: it is validated
        Then: it is ignored, not rejected -- the range loop no longer names it

        This is the BEHAVIOURAL proof that validator.py's [0,1] loop dropped the
        key, rather than a grep for its absence from a tuple. The premise half
        asserts a SURVIVING key at the same bad value still raises, so a
        validator that stopped checking levels entirely cannot pass this.
        """
        # PREMISE: the loop still rejects an out-of-range SURVIVING level.
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": {"minLevel": 2.0}}}
        with pytest.raises(ConfigValidationError):
            ConfigValidator().validate(raw)

        # Act / Assert: the retired key is inert, not policed.
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": {_RETIRED_LEAF: 2.0}}}
        ConfigValidator().validate(raw)

    def test_shippedConfigJsonDoesNotCarryIt(self):
        """
        Given: the config.json this repo actually ships
        When: its pi.display.autoDim section is read
        Then: the retired key is gone and the live tunables remain
        """
        autoDim = _shippedAutoDim()
        # PREMISE: this is really the autoDim section, not an empty dict.
        for leaf in _SURVIVING_LEAVES:
            assert leaf in autoDim, leaf
        assert _RETIRED_LEAF not in autoDim


# ---------------------------------------------------------------------------
# THE BROWSER TIER -- guarded twice: a source read that always runs, and a
# behavioural probe that asks the module what it BUILT (US-626: a substring
# assertion on a declaration is not a structural guard).
# ---------------------------------------------------------------------------


class TestCarouselDefaultsNoLongerCarryIt:
    def test_sourceLiteralDoesNotDeclareIt(self):
        """
        Given: the BRIGHTNESS_DEFAULTS literal in carousel.js
        When: its keys are parsed (comments stripped)
        Then: the retired key is not among them
        """
        keys = _brightnessDefaultsLiteral()
        # PREMISE: the literal parsed, and parsed correctly.
        for leaf in _SURVIVING_LEAVES:
            assert leaf in keys, f"premise failed: {leaf} missing -- bad parse?"
        assert keys["minLevel"] == "0.15"
        assert _RETIRED_LEAF not in keys

    @nodeless
    def test_resolvedDefaultsDoNotContainIt(self):
        """
        Given: resolveAutoDimConfig with no injected config
        When: it returns the grounded defaults
        Then: the retired key is absent from what it actually BUILT
        """
        out = _probe("resolveAutoDimConfig", {})
        # PREMISE: the probe really resolved the defaults.
        assert out["minLevel"] == 0.15
        assert out["defaultLevel"] == 0.70
        assert _RETIRED_LEAF not in out


# ---------------------------------------------------------------------------
# US-595 AC-6 / VC-2 -- AN ALREADY-DEPLOYED OVERLAY STILL CARRIES THE KEY.
# This is the constraint that made US-484-b leave the shim in place, and it is
# a real one, not an excuse. Both tiers must IGNORE the key, never choke on it.
# ---------------------------------------------------------------------------


class TestOldOverlayCarryingTheRetiredKey:
    def test_validatorAcceptsIt_andStillResolvesTheLiveKeys(self):
        """
        Given: an old config.json overlay that still carries alarmFloorLevel
        When: it is validated
        Then: validation succeeds and every LIVE key resolves to its own value
        """
        raw = _minimalConfig()
        raw["pi"] = {"display": {"autoDim": dict(_OLD_OVERLAY)}}
        resolved = ConfigValidator().validate(raw)["pi"]["display"]["autoDim"]
        # The live tunables are honoured, not collaterally damaged.
        assert resolved["minLevel"] == 0.15
        assert resolved["defaultLevel"] == 0.70
        assert resolved["luxStaleSec"] == 10
        assert resolved["curve"] == "logarithmic"

    @nodeless
    def test_resolveAutoDimConfig_dropsIt_withoutDisturbingTheRest(self):
        """
        Given: the same old overlay handed to the browser
        When: resolveAutoDimConfig merges it over the grounded defaults
        Then: the retired key is dropped and every live key still resolves

        resolveAutoDimConfig iterates BRIGHTNESS_DEFAULTS, not the injected
        object, so an unknown key is ignored BY CONSTRUCTION rather than by a
        rule someone must remember to keep. That is why removal is safe here.
        """
        out = _probe("resolveAutoDimConfig", dict(_OLD_OVERLAY))
        assert _RETIRED_LEAF not in out
        assert out["minLevel"] == 0.15
        assert out["defaultLevel"] == 0.70
        assert out["luxStaleSec"] == 10
        assert out["curve"] == "logarithmic"


# ---------------------------------------------------------------------------
# WHY REMOVAL IS SAFE AT ALL -- and therefore what must never quietly regress.
# The floor was not deleted because it stopped mattering; it was SUPERSEDED by
# a stronger rule. If that short-circuit is ever removed there would be neither
# a floor NOR a key, so the retirement owes the supersession an assertion
# (US-609: a deliberate decision left unpinned is a decision that gets undone).
# ---------------------------------------------------------------------------


class TestTheSupersedingRuleThatMakesRemovalSafe:
    @nodeless
    def test_stopAlarmIsFullBrightness_notAnyFloor(self):
        """
        Given: the darkest ambient reading and a deliberately DIM config
        When: brightnessLevel runs with a live STOP alarm
        Then: it returns FULL -- and the same config without the alarm does not

        The negative half is the load-bearing one: it proves the 1.0 came from
        the alarm short-circuit firing, not from a config that would have read
        full anyway. Without it this test passes on a broken short-circuit.
        """
        dim = dict(_OLD_OVERLAY)
        dim["minLevel"] = 0.15
        dim["defaultLevel"] = 0.15
        dark = {"lux": 0.0, "ts": _TS}

        assert _probe("brightnessLevel", dark, dim, _TS_MS + 5000, True) == 1.0
        # PREMISE: this config genuinely renders dim when no alarm is live.
        assert _probe("brightnessLevel", dark, dim, _TS_MS + 5000, False) < 0.5

    @nodeless
    def test_retiredKeyCannotDimALiveStopAlarm(self):
        """
        Given: an old overlay whose alarmFloorLevel is a LOW 0.40
        When: a STOP alarm is live
        Then: the surface is FULL -- the stale key has no effect whatsoever

        This is the field scenario in one assertion: a Pi imaged before this
        story, still carrying the key, must not dim a PULL-OVER alarm to 0.40.
        """
        dark = {"lux": 0.0, "ts": _TS}
        level = _probe("brightnessLevel", dark, dict(_OLD_OVERLAY), _TS_MS + 5000, True)
        assert level == 1.0
