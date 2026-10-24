################################################################################
# File Name: test_applied_brightness_override.py
# Purpose/Description: US-878-c (Atlas B4, VCs a-d) -- the page's ONE brightness
#   applier honours a FIXED level, pi.display.autoDim.overrideLevel, read ONLY
#   from the per-request settings blob ({found, value}, Atlas B13). The override
#   is a CONFIG fact, so it survives a dead light sensor; a STOP still wins.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Rex (US-878-c)| Initial -- applier step 2 'fixed', the Light
#               |              | status basis, the {found, value} blob reader.
# ================================================================================
################################################################################

"""US-878-c tests for appliedBrightness's 'fixed' step and its consumers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from typing import Any

import pytest

_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard", "carousel.js"
)
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

_OVERRIDE_KEY = "pi.display.autoDim.overrideLevel"
_TS = "2026-07-22T12:00:00+00:00"
_NOW_MS = int(datetime(2026, 7, 22, 12, 0, 5, tzinfo=UTC).timestamp() * 1000)
_CFG = {"luxMin": 3.0, "luxFull": 300.0, "minLevel": 0.75, "defaultLevel": 0.70,
        "luxStaleSec": 10, "curve": "logarithmic"}
_LIGHT = {"lux": 22.0, "ts": _TS, "brightnessLevel": 0.9, "brightnessMode": "auto"}


def _call(fn: str, *args: Any) -> Any:
    """One exported carousel.js function, called with JSON args (undefined ->
    a trailing argument the caller omitted)."""
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "const v = c[a.fn].apply(null, a.args);"
        "process.stdout.write(JSON.stringify(v === undefined ? null : v));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script],
        input=json.dumps({"js": _JS, "fn": fn, "args": list(args)}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _settings(entry: Any) -> dict[str, Any]:
    return {"pi.display.carousel.autoRotateS": {"found": True, "value": 8}, _OVERRIDE_KEY: entry}


def _fixed(level: Any) -> dict[str, Any]:
    return _settings({"found": True, "value": level})


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Atlas B4 VCs (a)-(d)
# ---------------------------------------------------------------------------


def test_a_noLightState_override08_isFixed():
    """(a) no states/light at all + overrideLevel 0.8 -> {0.8, 'fixed'}."""
    assert _call("appliedBrightness", None, _CFG, _NOW_MS, False, _fixed(0.8)) == {
        "level": 0.8, "basis": "fixed",
    }


def test_a_aFreshBridgeLevel_isOverriddenByTheFixedLevel():
    assert _call("appliedBrightness", _LIGHT, _CFG, _NOW_MS, False, _fixed(0.8)) == {
        "level": 0.8, "basis": "fixed",
    }


def test_b_stopStillWins_overAFixedLevel():
    """(b) the same + a STOP -> {1.0, 'alert'}: STOP stays first."""
    assert _call("appliedBrightness", None, _CFG, _NOW_MS, True, _fixed(0.8)) == {
        "level": 1.0, "basis": "alert",
    }


@pytest.mark.parametrize("light", [None, _LIGHT, {**_LIGHT, "ts": "2026-07-22T11:00:00+00:00"}])
def test_c_overrideNull_isByteIdenticalToNoSettingsAtAll(light):
    """(c) overrideLevel null (auto) -> exactly what the applier returns without
    the blob, which is what every pre-US-878-c applier test calls."""
    today = _call("appliedBrightness", light, _CFG, _NOW_MS, False)
    assert _call("appliedBrightness", light, _CFG, _NOW_MS, False, _fixed(None)) == today
    assert _call("appliedBrightness", light, _CFG, _NOW_MS, False, None) == today


def test_d_foundFalse_isNotFixed():
    """(d) found:false (unresolvable) -> not 'fixed'; auto on the glass."""
    out = _call("appliedBrightness", None, _CFG, _NOW_MS, False,
                _settings({"found": False, "value": None}))
    assert out == {"level": 0.70, "basis": "fallback"}


@pytest.mark.parametrize("level", [1.2, -0.1, "0.8", True])
def test_outsideZeroToOneOrNotANumber_fallsThrough_neverClamped(level):
    """US-627: never clamp -- an out-of-range or non-numeric override is not
    applied at all, so the operator never believes a level that is not shown."""
    out = _call("appliedBrightness", _LIGHT, _CFG, _NOW_MS, False, _fixed(level))
    assert out == {"level": 0.9, "basis": "auto"}


@pytest.mark.parametrize("level", [0, 1])
def test_theZeroToOneBoundsAreInclusive(level):
    assert _call("appliedBrightness", None, _CFG, _NOW_MS, False, _fixed(level)) == {
        "level": level, "basis": "fixed",
    }


@pytest.mark.parametrize(
    "settings",
    [
        {_OVERRIDE_KEY: 0.8},                    # a bare value is not the B13 shape
        {_OVERRIDE_KEY: {"value": 0.8}},          # no found flag
        {"pi.calibration.mode": {"found": True, "value": True}},  # key absent
        "__DISPLAY_SETTINGS__",                   # un-substituted preview
    ],
)
def test_aBlobThatIsNotFoundTrue_isNeverFixed(settings):
    out = _call("appliedBrightness", None, _CFG, _NOW_MS, False, settings)
    assert out["basis"] == "fallback"


# ---------------------------------------------------------------------------
# The Light page status line (Iris I12)
# ---------------------------------------------------------------------------


def test_lightStatus_fixedBasis_readsFixedInSettings():
    status = _call("lightStatusView", {"level": 0.8, "basis": "fixed"})
    assert status["text"] == "BRIGHTNESS 80 % (fixed in Settings)"
    assert status["label"] == "BRIGHTNESS"
    assert status["note"] == "(fixed in Settings)"


def test_validation_sensorAbsent_override08_isFixed_andTheStatusSaysSo():
    """VC: settings blob overrideLevel {found: true, value: 0.8}, light sensor
    absent -> appliedBrightness {0.8, 'fixed'}; status 'BRIGHTNESS 80 % (fixed
    in Settings)'."""
    view = _call("lightPageView", None, _CFG, _NOW_MS, False, _fixed(0.8))
    assert view["absent"] is True
    assert view["applied"] == {"level": 0.8, "basis": "fixed"}
    assert view["status"]["text"] == "BRIGHTNESS 80 % (fixed in Settings)"


def test_lightPage_theDotSitsAtTheFixedLevel():
    fresh = {**_LIGHT, "curve": {"points": [[3.0, 0.75], [300.0, 1.0]], "minLevel": 0.75,
                                 "luxMin": 3.0, "luxFull": 300.0}}
    fixed = _call("lightPageView", fresh, _CFG, _NOW_MS, False, _fixed(0.8))
    auto = _call("lightPageView", fresh, _CFG, _NOW_MS, False, _fixed(None))
    assert fixed["applied"]["basis"] == "fixed"
    assert fixed["curve"]["dot"]["y"] != auto["curve"]["dot"]["y"]


def test_sourceCardView_threadsTheBlobToTheLightPage():
    spec = _call("sourceCardSpec", "light")
    card = _call("sourceCardView", spec, None, None, _CFG, _NOW_MS, 60000, False, _fixed(0.8))
    assert card["view"]["status"]["text"] == "BRIGHTNESS 80 % (fixed in Settings)"


def test_fixedStatus_isNeverAmber():
    """Iris I12: --text-secondary, never amber -- the note is the secondary
    run and the status carries no warn tone."""
    css = _read(os.path.join(os.path.dirname(_JS), "dashboard.css"))
    rule = css[css.index("#light-card .light-status-note"):]
    assert "color: var(--text-secondary)" in rule[: rule.index("}")]
    assert "tone" not in _call("lightStatusView", {"level": 0.8, "basis": "fixed"})


# ---------------------------------------------------------------------------
# The {found, value} blob reader (Atlas B13) and the wiring
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ({_OVERRIDE_KEY: {"found": True, "value": None}}, {"found": True, "value": None}),
        ({_OVERRIDE_KEY: {"found": True, "value": 0.8}}, {"found": True, "value": 0.8}),
        ({_OVERRIDE_KEY: {"found": False, "value": None}}, {"found": False, "value": None}),
        ({}, {"found": False, "value": None}),
        (None, {"found": False, "value": None}),
        ({_OVERRIDE_KEY: 0.8}, {"found": False, "value": None}),
    ],
)
def test_settingsEntry_distinguishesResolvedNullFromUnresolvable(source, expected):
    assert _call("settingsEntry", source, _OVERRIDE_KEY) == expected


def test_band_readsTheEntryValue_soAnUnresolvableKeyRendersUnknown():
    js = _read(_JS)
    assert "render(settingsEntry(settingsSource, spec.key).value" in js
    spec = {"key": "pi.calibration.mode", "label": "Calibration mode", "kind": "bool",
            "apply": "capture-restart"}
    unresolved = _call("settingsEntry", {"pi.calibration.mode": {"found": False, "value": None}},
                       "pi.calibration.mode")
    assert _call("settingsRowView", spec, unresolved["value"])["display"] == "Unknown"


def test_bothApplierCallers_passTheSettingsBlob():
    """The panel and the Light page read the SAME blob, so they cannot disagree."""
    js = _read(_JS)
    panel = js[js.index("applyBrightness(\n          appliedBrightness("):]
    assert "settingsSource" in panel[: panel.index(").level")]
    card = js[js.index("sourceCardView(\n                spec, data,"):]
    assert "settingsSource" in card[: card.index(")\n            );")]


def test_theOverrideHasNoSecondCarrier():
    """B4: no states/light key, no bridge timer -- the blob is the only source."""
    js = _read(_JS)
    assert "lightData.overrideLevel" not in js
    assert "brightnessOverride" not in js
