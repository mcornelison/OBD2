################################################################################
# File Name: test_dashboard_stop_tier_safety.py
# Purpose/Description: US-484-b tests -- the DTC STOP ("PULL OVER") tier carries
#   its signal by Spool's multi-channel treatment, not by a hex swap. Per Spool
#   2026-07-25 (offices/tuner/dtc-display-clear-safety-advisory.md 6d):
#   #D32F2F vs brand --red #E60012 differ mainly in SATURATION -- the weakest
#   discriminator the eye has at arm's length, worse on the narrow-gamut OSOYOO
#   panel. So the tests below assert the four non-colour channels as hard
#   requirements, with the token repoint as the third reinforcement:
#     ch.1  AREA + MOTION + TEXT -- full-bleed takeover, pulsing alarm frame,
#           an explicit "PULL OVER" directive rendered larger than base copy.
#     ch.2  near-black (#000/#0a0a0a) field + WHITE copy, never brand chrome;
#           text contrast >= the WCAG-AA large-text floor (3:1).
#     ch.3  deeper-and-darker axis only -- no warmer/orange shift (that would
#           collide with amber WATCH and invert the severity order).
#     ch.4  a STOP alarm is FULL BRIGHTNESS ALWAYS -- it overrides the US-483-b
#           auto-dim curve AND its alarmFloorLevel guard; only ambient dims.
#   Colour + contrast are computed from the PARSED token values (both files), so
#   a drift in specs/UI/tokens.css OR in the shipped dist re-reds these tests.
#   The on-panel render ("does a driver read it in a glance") stays a PI-RUNTIME
#   gate -- see the story's validationCriteria.
#   Node-probe tests skip when node is not on PATH.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-26    | Ralph (Rex)  | Initial -- US-484-b STOP-tier safety treatment.
# ================================================================================
################################################################################

"""US-484-b tests for the DTC STOP-tier multi-channel safety treatment."""

import json
import os
import re
import shutil
import subprocess

import pytest

_UI = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "UI")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dist", "dashboard-pi")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

nodeless = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- STOP-tier probe tests need node",
)

# The WCAG 2.x AA floor for large text (>=18.66px bold / >=24px). Every STOP
# copy pairing is checked against this, never eyeballed.
_WCAG_AA_LARGE = 3.0

# The two near-black fields Spool 6d ch.2 permits for the STOP surface.
_NEAR_BLACK = {"#000000", "#000", "#0A0A0A"}

# A grounded auto-dim config (mirrors config.json pi.display.autoDim) used by the
# ch.4 brightness probes. alarmFloorLevel is deliberately present + non-full: the
# point of ch.4 is that a STOP overrides even this floor, straight to 1.0.
_CFG = {
    "luxMin": 3.0,
    "luxFull": 1000.0,
    "minLevel": 0.15,
    "defaultLevel": 0.70,
    "alarmFloorLevel": 0.40,
    "luxStaleSec": 10,
    "curve": "logarithmic",
}
_TS = "2026-07-22T12:00:00+00:00"
_TS_MS = 1784721600000  # Date.parse(_TS) -- pinned so freshness math is fixed


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _probe(fn: str, *args: object) -> object:
    """Evaluate a pure carousel export against fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _tokenValue(css: str, name: str) -> str:
    """The declared value of a custom property, uppercased (real declarations
    only -- never a prose mention inside the SSOT's comment blocks)."""
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([^;]+);", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared"
    return match.group(1).strip().upper()


def _ruleBlock(css: str, selector: str) -> str:
    """The declaration body of the rule with exactly this selector.

    Anchored at line start so a DESCENDANT rule (`#dtc-takeover[...stop]
    .takeover-directive`) can never be mistaken for the base rule it overrides.
    """
    pattern = rf"^{re.escape(selector.rstrip(' {'))}\s*\{{([^}}]*)\}}"
    match = re.search(pattern, css, re.MULTILINE)
    assert match is not None, f"no rule declared for {selector}"
    return match.group(1)


def _rgb(hexColor: str) -> tuple:
    h = hexColor.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _relLuminance(hexColor: str) -> float:
    """WCAG 2.x relative luminance."""

    def _lin(channel: int) -> float:
        v = channel / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hexColor)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _relLuminance(a), _relLuminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _hueDeg(hexColor: str) -> float:
    r, g, b = (c / 255.0 for c in _rgb(hexColor))
    hi, lo = max(r, g, b), min(r, g, b)
    delta = hi - lo
    if delta == 0:
        return 0.0
    if hi == r:
        h = 60.0 * (((g - b) / delta) % 6)
    elif hi == g:
        h = 60.0 * (((b - r) / delta) + 2)
    else:
        h = 60.0 * (((r - g) / delta) + 4)
    return h % 360.0


def _stopTakeoverCss(css: str) -> str:
    """Every declaration that applies to the STOP takeover surface."""
    blocks = re.findall(
        r'#dtc-takeover\[data-severity="stop"\][^{]*\{[^}]*\}', css
    )
    assert blocks, "no #dtc-takeover STOP rule found"
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# PREREQ -- the token exists in the SSOT with Spool's value, and the dist reads
# it from there (never a hardcoded fork).
# ---------------------------------------------------------------------------


def test_criticalRed_isDeclaredInTheSsot_withSpoolsValue():
    """Spool set the value 2026-07-25 (6d), Atlas gated it into tokens.css."""
    assert _tokenValue(_read(_TOKENS), "critical-red") == "#D32F2F"


def test_dashboardCss_criticalRed_matchesSsot():
    """The dist declares the SAME value -- parsed from both files so a future
    edit to EITHER re-reds this (an assertion on one file would pass forever)."""
    assert _tokenValue(_read(_CSS), "critical-red") == _tokenValue(
        _read(_TOKENS), "critical-red"
    )


def test_dashboardCss_criticalRedLiteral_appearsOnceInRoot():
    """Every STOP surface goes through var(--critical-red) -- the hex is
    declared exactly once, in :root."""
    assert len(re.findall(r"#D32F2F", _read(_CSS), re.IGNORECASE)) == 1


# ---------------------------------------------------------------------------
# AC2 -- the STOP tier is repointed OFF the brand reds onto --critical-red.
# ---------------------------------------------------------------------------


def test_stopRibbon_rendersCriticalRed_notBrandRed():
    block = _ruleBlock(_read(_CSS), '#dtc-ribbon[data-level="stop"]')
    assert "var(--critical-red)" in block
    assert "--red-light" not in block and "var(--red)" not in block


def test_stopChip_rendersCriticalRed_notBrandRed():
    block = _ruleBlock(_read(_CSS), '.dtc-chip[data-level="stop"]')
    assert "var(--critical-red)" in block
    assert "--red-light" not in block and "var(--red)" not in block


def test_stopHero_bordersCriticalRed_notBrandRed():
    block = _ruleBlock(_read(_CSS), '.dtc-hero[data-level="stop"]')
    assert "var(--critical-red)" in block
    assert "--red-light" not in block and "var(--red)" not in block


def test_confirmOk_rendersCriticalRed_notBrandRed():
    """The consequential-action confirm is an alarm affordance, not brand
    chrome (tokens.css reserves the brand reds for the brand mark)."""
    block = _ruleBlock(_read(_CSS), "#confirm-ok")
    assert "var(--critical-red)" in block
    assert "--red-light" not in block


def test_noStopSurfaceReferencesABrandRed():
    """AC6 grep, as a parsed assertion: no rule that styles a STOP surface may
    reference --red / --red-light / --red-dark (Spool 6d ch.2 -- STOP never
    renders on brand chrome, or the driver cannot tell brand from danger)."""
    css = _read(_CSS)
    stopRules = re.findall(r"[^{}]*\bstop\b[^{}]*\{[^}]*\}", css)
    assert stopRules, "no STOP-tier rules found"
    for rule in stopRules:
        body = rule[rule.index("{") :]
        for brand in ("var(--red)", "var(--red-light)", "var(--red-dark)"):
            assert brand not in body, f"brand red {brand} still on a STOP rule: {rule}"


def test_carouselJs_stopTakeoverTier_bindsCriticalRedVar():
    """The token name also lives in JS as DATA (TAKEOVER_STYLE.colorVar) -- a
    CSS-only repoint would leave the STOP tier bound to a brand red."""
    js = _read(_JS)
    assert '"--critical-red"' in js
    assert 'colorVar: "--red"' not in js


@nodeless
def test_takeoverView_stop_carriesCriticalRedColorVar():
    data = {
        "codes": [{"code": "P0301", "severity": "stop", "short": "Cyl 1 misfire"}],
        "newSinceTs": "2026-07-26T10:00:00Z",
    }
    view = _probe("takeoverView", data)
    assert view["colorVar"] == "--critical-red"


# ---------------------------------------------------------------------------
# Spool 6d ch.1 -- AREA + MOTION + TEXT carry STOP (colour is 3rd).
# ---------------------------------------------------------------------------


def test_stopTakeover_isFullBleed():
    """AREA channel: the takeover covers the whole design box. The STOP rules
    must not claw that back to a panel/card."""
    css = _read(_CSS)
    base = _ruleBlock(css, "#dtc-takeover {")
    assert "position: fixed" in base and "inset: 0" in base
    stop = _stopTakeoverCss(css)
    assert "inset:" not in stop, "STOP must not shrink the full-bleed surface"


def test_stopTakeover_pulses():
    """MOTION channel: a live STOP pulses. The keyframes must exist (a dangling
    animation name silently renders static)."""
    css = _read(_CSS)
    stop = _stopTakeoverCss(css)
    match = re.search(r"animation:\s*([a-zA-Z0-9-]+)", stop)
    assert match, "STOP takeover has no animation (motion channel missing)"
    assert f"@keyframes {match.group(1)}" in css


def test_stopTakeover_motionIsOnlyOnALiveStop():
    """Carousel spec 4: motion never implies a state that isn't real. The pulse
    is scoped to [data-severity="stop"], never to the base takeover rule."""
    base = _ruleBlock(_read(_CSS), "#dtc-takeover {")
    assert "animation" not in base


@nodeless
def test_stopTakeover_directiveSaysPullOver():
    """TEXT channel: the directive is explicit, not a colour the driver has to
    interpret."""
    data = {
        "codes": [{"code": "P0301", "severity": "stop", "short": "Cyl 1 misfire"}],
        "newSinceTs": "2026-07-26T10:00:00Z",
    }
    assert "PULL OVER" in _probe("takeoverView", data)["directive"].upper()


def test_stopTakeover_directiveIsLargerThanBaseCopy():
    """AREA channel again: on a STOP the directive is the biggest thing on the
    panel, so the signal survives a glance at arm's length."""
    css = _read(_CSS)
    base = _ruleBlock(css, ".takeover-directive {")
    baseSize = float(re.search(r"font-size:\s*([0-9.]+)px", base).group(1))
    stop = _stopTakeoverCss(css)
    stopSize = float(re.search(r"font-size:\s*([0-9.]+)px", stop).group(1))
    assert stopSize > baseSize, f"STOP directive {stopSize}px <= base {baseSize}px"


# ---------------------------------------------------------------------------
# Spool 6d ch.2 -- near-black field, WHITE copy, WCAG-AA large-text floor.
# ---------------------------------------------------------------------------


def test_stopTakeover_rendersOnNearBlack():
    css = _read(_CSS)
    stop = _stopTakeoverCss(css)
    match = re.search(r"background:\s*([^;]+);", stop)
    assert match, "STOP takeover declares no background"
    value = match.group(1).strip()
    varMatch = re.fullmatch(r"var\(--([a-zA-Z0-9-]+)\)", value)
    resolved = _tokenValue(css, varMatch.group(1)) if varMatch else value.upper()
    assert resolved in _NEAR_BLACK, f"STOP field {resolved} is not near-black"


def test_stopTakeover_copyIsWhite():
    stop = _stopTakeoverCss(_read(_CSS))
    assert re.search(r"color:\s*#fff(fff)?\s*;", stop, re.IGNORECASE)


def test_stopCopy_onCriticalRed_meetsWcagAaLargeText():
    """The directive band: WHITE on --critical-red, computed from the SSOT."""
    ratio = _contrast("#FFFFFF", _tokenValue(_read(_TOKENS), "critical-red"))
    assert ratio >= _WCAG_AA_LARGE, f"white on critical-red = {ratio:.2f}:1"


def test_stopCopy_onNearBlack_meetsWcagAaLargeText():
    ratio = _contrast("#FFFFFF", "#000000")
    assert ratio >= _WCAG_AA_LARGE


def test_criticalRed_onNearBlack_meetsWcagAaLargeText():
    """The alarm frame itself must be visible against its own field."""
    ratio = _contrast(_tokenValue(_read(_TOKENS), "critical-red"), "#000000")
    assert ratio >= _WCAG_AA_LARGE, f"critical-red on black = {ratio:.2f}:1"


# ---------------------------------------------------------------------------
# Spool 6d ch.3 -- deeper-and-darker axis; no warmer/orange shift; the tiers
# below STOP are unchanged so the severity ramp still reads in order.
# ---------------------------------------------------------------------------


def test_criticalRed_isDeeperAndDarkerThanTheBrandReds():
    tokens = _read(_TOKENS)
    critical = _tokenValue(tokens, "critical-red")
    for brand in ("red", "red-light"):
        other = _tokenValue(tokens, brand)
        assert _relLuminance(critical) < _relLuminance(other), brand
        assert max(_rgb(critical)) < max(_rgb(other)), brand


def test_criticalRed_hasNoWarmBias():
    """A warmer/orange shift lifts GREEN above BLUE. #D32F2F holds G == B, so
    the axis vs brand red is saturation+darkness only, never hue-toward-amber."""
    _, g, b = _rgb(_tokenValue(_read(_TOKENS), "critical-red"))
    assert g == b, f"green {g} != blue {b} -- the STOP red has a warm bias"


def test_criticalRed_doesNotCollideWithAmberWatch():
    """Severity order integrity: STOP must stay hue-distant from WATCH amber."""
    tokens = _read(_TOKENS)
    separation = abs(
        _hueDeg(_tokenValue(tokens, "critical-red"))
        - _hueDeg(_tokenValue(tokens, "amber-warn"))
    )
    assert separation >= 40.0, f"STOP/WATCH hue separation only {separation:.1f} deg"


def test_watchAndMinorTiers_areUnchanged():
    """WATCH stays --amber-warn and MINOR stays --green-ok on every surface the
    STOP repoint touched."""
    css = _read(_CSS)
    assert (
        "var(--amber-warn)" in _ruleBlock(css, '#dtc-ribbon[data-level="watch"]')
    )
    assert "var(--green-ok)" in _ruleBlock(css, '#dtc-ribbon[data-level="minor"]')
    assert "var(--amber-warn)" in _ruleBlock(css, '.dtc-chip[data-level="watch"]')
    assert "var(--green-ok)" in _ruleBlock(css, '.dtc-chip[data-level="minor"]')
    assert _tokenValue(css, "amber-warn") == "#FFC400"
    assert _tokenValue(css, "green-ok") == "#35C46A"


# ---------------------------------------------------------------------------
# Spool 6d ch.4 -- a STOP alarm is FULL BRIGHTNESS ALWAYS (only ambient dims).
# ---------------------------------------------------------------------------


@nodeless
def test_brightnessLevel_stopAlarmInTheDark_isFullBrightness():
    """LOAD-BEARING: the darkest possible ambient reading cannot dim a live
    PULL-OVER alarm at all."""
    light = {"lux": 0.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _TS_MS + 5000, True) == 1.0


@nodeless
def test_brightnessLevel_stopAlarm_overridesTheAlarmFloor():
    """ch.4 is stronger than the US-483-b floor: a STOP goes to FULL, not to
    alarmFloorLevel (0.40 here)."""
    light = {"lux": 1.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _TS_MS + 5000, True) == 1.0


@nodeless
def test_brightnessLevel_stopAlarm_isFullEvenOnAStaleOrAbsentFeed():
    """A dead light sensor must never leave the alarm at the 0.70 default."""
    stale = {"lux": 1.0, "ts": _TS}
    assert _probe("brightnessLevel", stale, _CFG, _TS_MS + 20000, True) == 1.0
    assert _probe("brightnessLevel", None, _CFG, _TS_MS + 5000, True) == 1.0


@nodeless
def test_brightnessLevel_withoutAStopAlarm_ambientStillDims():
    """Only ambient content dims -- the ch.4 override must not disable auto-dim
    for the normal case (that would defeat US-483-b entirely)."""
    light = {"lux": 1.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _TS_MS + 5000, False) == 0.15


@nodeless
def test_brightnessAlarmActive_onlyStopForcesFullBrightness():
    """A WATCH is a real code but not the PULL-OVER alarm -- it keeps dimming."""
    assert _probe("brightnessAlarmActive", {"codes": [{"code": "P0301", "severity": "stop"}]}) is True
    assert _probe("brightnessAlarmActive", {"codes": [{"code": "P0420", "severity": "watch"}]}) is False
