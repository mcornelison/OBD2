################################################################################
# File Name: test_carousel_brightness.py
# Purpose/Description: US-483-b tests for the carousel display-brightness
#   consumer (F-121). The dashboard is a PURE CONSUMER of the states/light file
#   the light bridge writes. Since US-893-a the bridge is the ONE brightness
#   applier: it publishes brightnessLevel from the one curve, and the page
#   APPLIES that level through appliedBrightness() (Atlas A7). The page keeps
#   only the load-bearing alarm override (US-484-b / Spool 6d ch.4: a real STOP
#   alert is FULL brightness always -- this SUPERSEDED the original
#   alarmFloorLevel floor so completely that US-595 retired that config key)
#   and an honest fallback (an absent/stale/malformed feed holds the injected
#   defaultLevel -- no fake "auto" behavior). Two layers are covered on the
#   bench: (1) the pure appliedBrightness / brightnessAlarmActive logic via the
#   node probe, and (2) static wiring assertions on the shipped dist assets (the
#   light fetch, the filter apply, the config-injection global, and the US-893-a
#   grep gate: no curve, no lux threshold literal, no log outside luxAxisX). The
#   Iris AC-7 "tracks live lux on the REAL Pi" checks are PI-RUNTIME gates.
#   Skipped when node is not on PATH (a node-less CI box) for the probe tests.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-22    | Ralph (Rex)  | Initial -- US-483-b display-brightness consumer.
# 2026-08-29    | Ralph (Rex)  | US-627: pin the TWO-BRANCH ASYMMETRY -- the
#                                curve branch clamps to minLevel, the
#                                absent/stale-feed branch returns defaultLevel
#                                UNCLAMPED. Both halves measured, plus a
#                                call-site documentation guard (VC-3). The floor
#                                is enforced at config time, never at runtime
#                                (AC-4), so these tests keep a future clamp from
#                                silently retiring that loud failure.
# 2026-10-14    | Rex (US-878-b)| The page still matches the frozen golden table
#                                the light bridge is pinned to, so the Pi's
#                                published level and the panel cannot drift.
# 2026-10-19    | Rex (US-893-a)| Re-pointed at the APPLIED level. MOVED PIN
#                                (US-893-a): the brightnessCurve tests, the
#                                page brightnessLevel tests and the page-vs-
#                                golden rows are retired with the page curve
#                                (the golden table now pins the ONE curve, in
#                                the bridge); appliedBrightness replaces them
#                                case for case. The US-627 curve-branch clamp
#                                moved to the bridge (test_brightness_golden);
#                                the unclamped fallback stays pinned here.
# 2026-10-19    | Rex (US-893-b)| MOVED PIN (US-893-b): the zero-log gate admits
#                                the log calls inside luxAxisX (Atlas A2).
# 2026-10-20    | Rex (US-899-a1)| MOVED PIN (US-899-a1): brightnessAlarmActive
#                                keys on states/alerts.takeover, so its three
#                                cases take alerts payloads (+ a dtc STOP code
#                                alone is now false).
# ================================================================================
################################################################################

"""US-483-b / US-893-a tests for the carousel display-brightness consumer."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "src",
    "pi",
    "ui",
    "dashboard",
)
_HTML = os.path.join(_DIST, "dashboard.html")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")

# A fixed sample read-time + its epoch-ms, so the freshness math is deterministic
# (the node probe compares nowMs against Date.parse(ts)).
_TS = "2026-07-22T12:00:00+00:00"
_TS_MS = int(datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC).timestamp() * 1000)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _probe(fn: str, *args: object) -> object:
    """Evaluate a pure carousel export against fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


nodeless = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- brightness probe tests need node",
)

# The injected window.DISPLAY_AUTODIM as the browser receives it (the raw
# pi.display.autoDim section). The page reads ONLY defaultLevel and luxStaleSec;
# the curve keys ride along because the server injects the whole section.
_CFG = {
    "luxMin": 3.0,
    "luxFull": 300.0,
    "minLevel": 0.75,
    "defaultLevel": 0.70,
    # US-595: alarmFloorLevel retired -- config.json no longer carries it.
    "luxStaleSec": 10,
    "curve": "logarithmic",
}


def _fresh(ms_after: int = 5000) -> int:
    return _TS_MS + ms_after


def _light(level: object = 0.8, *, mode: str = "auto", **extra: object) -> dict:
    """A states/light payload carrying the bridge's published level."""
    payload: dict = {"lux": 22.0, "ts": _TS, "brightnessLevel": level, "brightnessMode": mode}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# appliedBrightness -- the page APPLIES the published level (Atlas A7).
# ---------------------------------------------------------------------------


@nodeless
def test_appliedBrightness_freshAuto_appliesThePublishedLevel():
    """A fresh 'auto' payload is applied exactly as published."""
    out = _probe("appliedBrightness", _light(0.8), _CFG, _fresh(), False)
    assert out == {"level": 0.8, "basis": "auto"}


@nodeless
def test_appliedBrightness_freshDefaultMode_appliedAsPublished():
    """A fresh null-lux 'default' payload is applied as published -- lux is NOT
    consulted, the bridge already chose defaultLevel."""
    light = _light(1.0, mode="default", lux=None)
    out = _probe("appliedBrightness", light, _CFG, _fresh(), False)
    assert out == {"level": 1.0, "basis": "default"}


@nodeless
def test_appliedBrightness_luxIsNotConsulted():
    """A dark lux beside a full published level is full: the page has no curve."""
    out = _probe("appliedBrightness", _light(1.0, lux=0.0), _CFG, _fresh(), False)
    assert out["level"] == 1.0


@nodeless
def test_appliedBrightness_twelveSecondsOld_appliesInjectedDefault():
    """VC: states/light 12 s old, injected defaultLevel 1.0 -> applied 1.0."""
    cfg = dict(_CFG, defaultLevel=1.0)
    out = _probe("appliedBrightness", _light(0.75), cfg, _fresh(12000), False)
    assert out == {"level": 1.0, "basis": "fallback"}


@nodeless
def test_appliedBrightness_stopAlarm_isFull():
    """VC: STOP alarm active, brightnessLevel 0.8 -> applied 1.0."""
    out = _probe("appliedBrightness", _light(0.8), _CFG, _fresh(), True)
    assert out == {"level": 1.0, "basis": "alert"}


@nodeless
def test_appliedBrightness_absentFile_holdsDefault():
    """No states/light (null) -> the injected default, no fabricated auto."""
    out = _probe("appliedBrightness", None, _CFG, _fresh(), False)
    assert out == {"level": 0.70, "basis": "fallback"}


@nodeless
def test_appliedBrightness_noPublishedLevel_isFallback_neverThrows():
    """A {lux, ts} payload (an older producer) has no level -> fallback."""
    out = _probe("appliedBrightness", {"lux": 1.0, "ts": _TS}, _CFG, _fresh(), False)
    assert out == {"level": 0.70, "basis": "fallback"}


@nodeless
@pytest.mark.parametrize("level", [-0.1, 1.5, "0.8", None, True])
def test_appliedBrightness_outOfRangeOrNonNumericLevel_isFallback_neverClamped(level):
    """US-627: an out-of-range level is fallback, NEVER silently repaired."""
    out = _probe("appliedBrightness", _light(level), _CFG, _fresh(), False)
    assert out == {"level": 0.70, "basis": "fallback"}


@nodeless
def test_appliedBrightness_levelBoundsAreInclusive():
    """0 and 1 are in range."""
    assert _probe("appliedBrightness", _light(0), _CFG, _fresh(), False)["level"] == 0
    assert _probe("appliedBrightness", _light(1), _CFG, _fresh(), False)["level"] == 1


@nodeless
def test_appliedBrightness_staleBoundary_inclusiveAtLuxStaleSec():
    """age == luxStaleSec is fresh; 1 ms past it is fallback."""
    edge = _probe("appliedBrightness", _light(0.8), _CFG, _fresh(10000), False)
    past = _probe("appliedBrightness", _light(0.8), _CFG, _fresh(10001), False)
    assert edge["basis"] == "auto"
    assert past["basis"] == "fallback"


@nodeless
@pytest.mark.parametrize("ts", [None, "not-a-timestamp", 12345])
def test_appliedBrightness_undatedPayload_isFallback(ts):
    """An undated level is the one most likely to be stale -> fallback."""
    out = _probe("appliedBrightness", _light(0.8, ts=ts), _CFG, _fresh(), False)
    assert out["basis"] == "fallback"


@nodeless
def test_appliedBrightness_sourceUnavailable_isFallback():
    """An explicit honest-availability marker is not a level to apply."""
    light = _light(0.8, source={"light": {"available": False, "reason": "sensor disabled"}})
    out = _probe("appliedBrightness", light, _CFG, _fresh(), False)
    assert out["basis"] == "fallback"


@nodeless
def test_appliedBrightness_stopAlarmStaleFeed_isStillFull():
    """A STOP with a stale/dead feed does NOT fall back to the default -- the
    alarm overrides the honest fallback too (ch.4)."""
    assert _probe("appliedBrightness", _light(0.8), _CFG, _fresh(20000), True)["level"] == 1.0
    assert _probe("appliedBrightness", None, _CFG, _fresh(), True)["level"] == 1.0


@nodeless
def test_appliedBrightness_missingConfig_usesTheBuiltInDefaults():
    """No injected config -> the built-in default (preview/file:// safe)."""
    assert _probe("appliedBrightness", None, None, _fresh(), False)["level"] == 0.70
    assert _probe("appliedBrightness", _light(0.8), None, _fresh(), False)["level"] == 0.8


@nodeless
def test_appliedBrightness_staleWindowComesFromTheInjection():
    """luxStaleSec is config: a 30 s window keeps a 20 s old level fresh."""
    cfg = dict(_CFG, luxStaleSec=30)
    out = _probe("appliedBrightness", _light(0.8), cfg, _fresh(20000), False)
    assert out["basis"] == "auto"


# ---------------------------------------------------------------------------
# brightnessAlarmActive -- a PULL OVER is up (drives the override).
# MOVED PIN (US-899-a1): it keys on states/alerts.takeover != null, no longer on
# the states/dtc ribbon level.
# ---------------------------------------------------------------------------


@nodeless
def test_brightnessAlarmActive_aTakeover_isTrue():
    data = {"takeover": {"id": "engine:COOLANT_TEMP:stop"}, "entries": []}
    assert _probe("brightnessAlarmActive", data) is True


@nodeless
def test_brightnessAlarmActive_aWatchWithNoTakeover_isFalse():
    """WATCH is a real alert but not the PULL-OVER alarm -> no forced full."""
    data = {"takeover": None, "icon": {"state": "watch"},
            "entries": [{"id": "engine:BATTERY_V:watch", "tier": "watch"}]}
    assert _probe("brightnessAlarmActive", data) is False


@nodeless
def test_brightnessAlarmActive_noTakeoverOrNoPayload_isFalse():
    assert _probe("brightnessAlarmActive", {"takeover": None}) is False
    assert _probe("brightnessAlarmActive", None) is False
    # A states/dtc STOP code is not the takeover's driver any more.
    assert _probe("brightnessAlarmActive", {"codes": [{"code": "P0300", "severity": "stop"}]}) is False


# ---------------------------------------------------------------------------
# Static wiring -- the shipped dist assets carry the consumer plumbing. These
# run without node (they are the deploy-truth the PI-RUNTIME AC-7 rests on).
# ---------------------------------------------------------------------------


def test_js_exports_theBrightnessApi():
    js = _read(_JS)
    for name in ("appliedBrightness", "brightnessAlarmActive", "resolveAutoDimConfig"):
        assert name + ": " + name in js, name


def test_js_tick_fetchesLightState():
    """The consumer reads states/light (never the sensor) each poll.

    US-507 moved the read behind the per-tick `stateOnce` cache (the Health
    card's Light section and the auto-dim now share one payload, so fetching it
    twice could resolve the printed reading and the brightness against two
    different samples). The invariant is unchanged and is what is asserted: the
    poll requests `light`, and that request goes through the STATE-FILE fetcher
    -- the consumer never touches the sensor.
    """
    js = _read(_JS)
    assert 'stateOnce("light")' in js
    assert "await fetchState(name)" in js


def test_js_tick_appliesTheAppliedBrightnessLevel():
    """The screen frame gets appliedBrightness(...).level -- the one applier."""
    js = _read(_JS)
    call = js[js.index("applyBrightness(\n          appliedBrightness("):]
    assert ").level" in call[:300]


def test_js_appliesBrightnessViaCssVar():
    """Brightness is applied as a CSS var on the screen frame (software dim)."""
    js = _read(_JS)
    assert 'setProperty("--display-brightness"' in js


def test_js_readsInjectedConfigGlobal():
    """defaultLevel and luxStaleSec come from the injected config global."""
    js = _read(_JS)
    assert "DISPLAY_AUTODIM" in js


def test_css_screen_appliesBrightnessFilter():
    css = _read(_CSS)
    screen = css[css.index("#screen {"):css.index("#stage {")]
    assert "filter: brightness(var(--display-brightness, 1));" in screen


def test_html_injectsDisplayAutodimConfigGlobal():
    """dashboard.html carries the config placeholder the state server substitutes
    (quoted so an un-substituted preview stays valid JS -> JS uses defaults)."""
    html = _read(_HTML)
    assert 'window.DISPLAY_AUTODIM = "__DISPLAY_AUTODIM__";' in html


# ---------------------------------------------------------------------------
# US-893-a grep gate (Atlas A2) -- on carousel.js with // and /* */ comments
# stripped: (i) BRIGHTNESS_DEFAULTS holds no curve key; (ii) no numeric
# luxMin / luxFull / minLevel literal anywhere; (iii) every Math.log /
# Math.log10 inside luxAxisX (US-893-b). Identifiers such as curve.luxMin stay
# allowed.
# ---------------------------------------------------------------------------


def _stripJsComments(src: str) -> str:
    """carousel.js with // and /* */ comments removed (string-literal aware)."""
    out: list[str] = []
    i, n = 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(src[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j == -1 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _code() -> str:
    return _stripJsComments(_read(_JS))


def test_gate_stripperRemovesCommentsButKeepsCode():
    """Premise: the stripper drops comments and keeps the code beside them."""
    sample = 'var a = 1; // luxMin: 3\n/* Math.log(x) */ var b = "//kept";'
    stripped = _stripJsComments(sample)
    assert "luxMin" not in stripped
    assert "Math.log" not in stripped
    assert 'var b = "//kept";' in stripped
    assert "var a = 1;" in stripped


def test_gate_brightnessDefaults_holdsNoCurveKey():
    """(i) BRIGHTNESS_DEFAULTS shrinks to {defaultLevel, luxStaleSec}."""
    code = _code()
    match = re.search(r"var\s+BRIGHTNESS_DEFAULTS\s*=\s*\{(.*?)\};", code, re.DOTALL)
    assert match, "BRIGHTNESS_DEFAULTS literal not found"
    keys = set(re.findall(r"(\w+)\s*:", match.group(1)))
    assert keys == {"defaultLevel", "luxStaleSec"}


def test_gate_noNumericLuxThresholdLiteral():
    """(ii) no luxMin / luxFull / minLevel assigned a number anywhere."""
    hits = re.findall(r"\b(luxMin|luxFull|minLevel)\s*[:=]\s*-?[\d.]", _code())
    assert hits == []


def test_gate_everyLogarithmIsInsideLuxAxisX():
    """(iii) The page computes no curve. MOVED PIN (US-893-b, Atlas A2: "893-b's
    gate then admits exactly the log calls inside luxAxisX"): was ZERO
    Math.log / Math.log10; the Light page's log-lux AXIS needs one helper, and
    every log call in carousel.js sits inside it (also pinned, with the
    function's bounds, in test_light_page.py)."""
    code = _code()
    start = code.index("function luxAxisX(")
    end = code.index("\n  }\n", start)
    hits = [m.start() for m in re.finditer(r"Math\.log(?:10)?\b", code)]
    assert hits and all(start < h < end for h in hits), hits


def test_gate_pageCurveFunctionsAreDeleted():
    """brightnessCurve and the page's brightnessLevel are gone (US-893-a)."""
    code = _code()
    assert "function brightnessCurve" not in code
    assert "function brightnessLevel" not in code


# ---------------------------------------------------------------------------
# US-627 -- the fallback is applied UNCLAMPED. minLevel bounds the CURVE (in
# the bridge since US-893-a, pinned by tests/pi/sensors/test_brightness_golden.py
# test_brightnessLevel_nullLux_defaultBelowMinLevel_isUnclamped); the page
# fallback returns defaultLevel verbatim. That is enforced at CONFIG time
# (validator rule, tests/test_display_autodim_floor_rule.py) and deliberately
# NOT clamped here -- AC-4: a runtime clamp hides a bad config instead of
# rejecting it.
# ---------------------------------------------------------------------------


@nodeless
def test_appliedBrightness_fallback_isNotClampedToMinLevel():
    """
    Given: a (config-invalid) defaultLevel BELOW minLevel and a dead light feed
    When: appliedBrightness resolves the fallback
    Then: it returns defaultLevel verbatim -- no floor is applied

    MEASURES the US-627 asymmetry rather than asserting it from the source. Such
    a config can no longer pass validate_config; if one reaches the panel anyway,
    the panel must keep reporting it honestly instead of masking it.
    """
    cfg = dict(_CFG, minLevel=0.75, defaultLevel=0.30)

    assert _probe("appliedBrightness", None, cfg, _fresh(), False)["level"] == 0.30


def test_js_appliedBrightness_documentsTheUnclampedFallback():
    """US-627 VC-3: the asymmetry is documented AT THE APPLIER.

    Asserts the anchors a reader needs (both key names, the unclamped fact, and
    where the rule actually lives), not the exact prose -- rewording stays green,
    deleting the explanation goes red.
    """
    js = _read(_JS)
    start = js.index("function appliedBrightness(")
    # The explanation block sits immediately above the function.
    block = js[max(0, start - 1800):start]

    assert "minLevel" in block
    assert "defaultLevel" in block
    assert "NOT clamped" in block or "UNCLAMPED" in block
    assert "validate_config" in block
