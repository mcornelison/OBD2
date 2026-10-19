################################################################################
# File Name: test_brightness_golden.py
# Purpose/Description: US-878-b frozen golden table -- THE single reference for
#     the auto-dim curve. The light bridge ports carousel.js brightnessCurve /
#     brightnessLevel (without the page-side STOP override) and must reproduce
#     today's page to 1e-9 for every row.
#
#     The expected values were produced by running TODAY's carousel.js in node
#     (require of src/pi/ui/dashboard/carousel.js, the module the tests/ui
#     carousel_probe.js harness loads), calling
#     brightnessLevel({lux, ts}, cfg, ts + 1 s, false) with cfg = the validator
#     DEFAULTS autoDim below, then frozen here as literals. They are never
#     recomputed: a later change to either curve has to change this table on
#     purpose. NaN and Infinity were passed as JS literals (JSON cannot carry
#     them), which is why the freeze did not go through the JSON probe argv.
#
#     Config is the validator DEFAULTS, never config.json, so a retune of the
#     shipped config (US-879) cannot break the table.
# Author: Rex (US-878-b)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""US-878-b golden table: the bridge's brightness equals today's page curve."""

from __future__ import annotations

import math

import pytest

from common.config.validator import DEFAULTS
from pi.sensors.light_state_bridge import brightnessLevel, buildLightState

_TOLERANCE = 1e-9

_AUTODIM_PREFIX = "pi.display.autoDim."


def _defaultsAutoDim(curve: str) -> dict:
    """The validator DEFAULTS autoDim section, with ``curve`` set."""
    section = {
        key[len(_AUTODIM_PREFIX):]: value
        for key, value in DEFAULTS.items()
        if key.startswith(_AUTODIM_PREFIX)
    }
    section["curve"] = curve
    return section


# (lux, logarithmic level, linear level) -- frozen from node on 2026-10-14.
_GOLDEN: list[tuple[str, float | None, float, float]] = [
    ("null", None, 0.7, 0.7),
    ("-1", -1.0, 0.7, 0.7),
    ("NaN", math.nan, 0.7, 0.7),
    ("inf", math.inf, 0.7, 0.7),
    ("0", 0.0, 0.15, 0.15),
    ("2.9", 2.9, 0.15, 0.15),
    ("3.0", 3.0, 0.15, 0.15),
    ("3.1", 3.1, 0.15, 0.15),
    ("10", 10.0, 0.2072548061449685, 0.15),
    ("54.77", 54.77, 0.4999929103088766, 0.15),
    ("999", 999.0, 0.999827771439737, 0.9989969909729187),
    ("1000", 1000.0, 1.0, 1.0),
    ("5000", 5000.0, 1.0, 1.0),
]

# luxFull <= luxMin (a misconfigured range): the page goes full, never div0.
_DEGENERATE = {"lux": 50.0, "luxMin": 100.0, "luxFull": 100.0, "expected": 1.0}


def test_goldenConfig_isTheValidatorDefaults():
    """
    Given: the validator DEFAULTS
    When: the golden config is built from them
    Then: it is the config the table was frozen under (a DEFAULTS change
        must re-freeze the table, not silently shift it)
    """
    section = _defaultsAutoDim("logarithmic")

    assert section["luxMin"] == 3.0
    assert section["luxFull"] == 1000.0
    assert section["minLevel"] == 0.15
    assert section["defaultLevel"] == 0.70


@pytest.mark.parametrize("curve", ["logarithmic", "linear"])
@pytest.mark.parametrize(("name", "lux", "logLevel", "linLevel"), _GOLDEN)
def test_brightnessLevel_matchesTheFrozenPageCurve(name, lux, logLevel, linLevel, curve):
    """
    Given: a golden row and the validator-default autoDim under ``curve``
    When: the bridge's brightnessLevel computes the level
    Then: it equals today's carousel.js output to 1e-9
    """
    expected = logLevel if curve == "logarithmic" else linLevel

    level = brightnessLevel(lux, _defaultsAutoDim(curve))

    assert abs(level - expected) <= _TOLERANCE, (name, curve, level)


# US-893-a (Atlas A3): the rows whose lux is not a reading (not finite, or
# negative). Their LEVEL is unchanged -- already defaultLevel -- and their mode
# is 'default'; every other row stays 'auto'.
_NOT_A_READING = {"null", "-1", "NaN", "inf"}


@pytest.mark.parametrize("curve", ["logarithmic", "linear"])
@pytest.mark.parametrize(("name", "lux", "logLevel", "linLevel"), _GOLDEN)
def test_publishedState_carriesTheFrozenLevel(name, lux, logLevel, linLevel, curve):
    """
    Given: a golden row reaching buildLightState as the burst's lux
    When: the bridge builds the states/light payload
    Then: brightnessLevel matches the table; brightnessMode is 'default' for a
        lux that is not a reading, else 'auto'

    MOVED PIN (US-893-a, Atlas ruled): the null-lux row's mode, and beside it
    the '-1' row's (A3), were 'auto' and are now 'default'. Level table
    UNCHANGED.
    """
    expected = logLevel if curve == "logarithmic" else linLevel

    state = buildLightState(lux=lux, tsUtc="2026-10-20T15:02:11.3Z",
                            autoDim=_defaultsAutoDim(curve))

    assert abs(state["brightnessLevel"] - expected) <= _TOLERANCE, (name, curve)
    expectedMode = "default" if name in _NOT_A_READING else "auto"
    assert state["brightnessMode"] == expectedMode, (name, curve)


def test_brightnessLevel_degenerateRange_matchesThePage():
    """luxFull <= luxMin -> full brightness, exactly as the page (no div0)."""
    autoDim = dict(
        _defaultsAutoDim("logarithmic"),
        luxMin=_DEGENERATE["luxMin"], luxFull=_DEGENERATE["luxFull"],
    )

    level = brightnessLevel(_DEGENERATE["lux"], autoDim)

    assert abs(level - _DEGENERATE["expected"]) <= _TOLERANCE


def test_brightnessLevel_nullLux_defaultBelowMinLevel_isUnclamped():
    """
    Given: defaultLevel 0.70 below minLevel 0.75 (a test config; validate_config
        rejects it) and a null lux
    When: brightnessLevel resolves the fallback branch
    Then: 0.70 -- the floor bounds the curve, never the fallback (US-627);
        node gave 0.7 for this config too
    """
    autoDim = dict(_defaultsAutoDim("logarithmic"), minLevel=0.75, defaultLevel=0.70)

    assert brightnessLevel(None, autoDim) == pytest.approx(0.70, abs=_TOLERANCE)
