################################################################################
# File Name: test_carousel_brightness.py
# Purpose/Description: US-483-b tests for the carousel display-brightness
#   consumer (F-121). The dashboard is a PURE CONSUMER of the states/light file
#   US-483-a writes ({lux, ts}); it drives an auto-dim curve whose values are
#   GROUNDED CONFIG PARAMETERS (never hardcoded), with a load-bearing alarm
#   override (US-484-b / Spool 6d ch.4: a real STOP alert is FULL brightness
#   always -- this SUPERSEDES the original alarmFloorLevel floor) and an honest
#   fallback
#   (an absent/stale feed holds a fixed default -- no fake "auto" behavior). Two
#   layers are covered on the bench: (1) the pure brightnessCurve / brightnessLevel
#   / brightnessAlarmActive math via the node probe, and (2) static wiring
#   assertions on the shipped dist assets (the light fetch, the filter apply, the
#   config-injection global). The Iris AC-7 "tracks live lux on the REAL Pi"
#   checks (cover the sensor / STOP takeover) are PI-RUNTIME gates.
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
# ================================================================================
################################################################################

"""US-483-b tests for the carousel display-brightness consumer."""

import json
import os
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
    "specs",
    "UI",
    "dist",
    "dashboard-pi",
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
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


nodeless = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- brightness probe tests need node",
)

# Grounded config the browser would receive (mirrors config.json pi.display.autoDim).
_CFG = {
    "luxMin": 3.0,
    "luxFull": 1000.0,
    "minLevel": 0.15,
    "defaultLevel": 0.70,
    "alarmFloorLevel": 0.40,
    "luxStaleSec": 10,
    "curve": "logarithmic",
}


def _fresh(ms_after: int = 5000) -> int:
    return _TS_MS + ms_after


# ---------------------------------------------------------------------------
# brightnessCurve -- the pure perceptual lux->0..1 mapping.
# ---------------------------------------------------------------------------


@nodeless
def test_brightnessCurve_atOrBelowLuxMin_isZero():
    """lux <= luxMin -> 0 (the caller floors it to minLevel)."""
    assert _probe("brightnessCurve", 3.0, 3.0, 1000.0, "logarithmic") == 0
    assert _probe("brightnessCurve", 1.0, 3.0, 1000.0, "logarithmic") == 0


@nodeless
def test_brightnessCurve_atOrAboveLuxFull_isOne():
    """lux >= luxFull -> 1 (full brightness in daylight)."""
    assert _probe("brightnessCurve", 1000.0, 3.0, 1000.0, "logarithmic") == 1
    assert _probe("brightnessCurve", 5000.0, 3.0, 1000.0, "logarithmic") == 1


@nodeless
def test_brightnessCurve_logarithmic_isMonotonicMidpoint():
    """A mid lux maps between 0 and 1, and log rises faster in the dark than
    linear would (perceptual): at the geometric mean it is ~0.5."""
    geo = (3.0 * 1000.0) ** 0.5  # ~54.8 lux
    mid = _probe("brightnessCurve", geo, 3.0, 1000.0, "logarithmic")
    assert 0.45 < mid < 0.55


@nodeless
def test_brightnessCurve_degenerateRange_fallsBackToFull():
    """luxFull <= luxMin is a misconfiguration -> never divide-by-zero; full."""
    assert _probe("brightnessCurve", 50.0, 100.0, 100.0, "logarithmic") == 1


# ---------------------------------------------------------------------------
# brightnessLevel -- clamp(minLevel, curve(lux), 1.0) + honest fallback + floor.
# ---------------------------------------------------------------------------


@nodeless
def test_brightnessLevel_freshDarkLux_dimsTowardMinLevel():
    """A fresh dark reading (lux at/below luxMin) with no alarm dims to minLevel."""
    light = {"lux": 1.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _fresh(), False) == 0.15


@nodeless
def test_brightnessLevel_freshBrightLux_goesFull():
    """A fresh daylight reading goes to full brightness."""
    light = {"lux": 5000.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _fresh(), False) == 1.0


@nodeless
def test_brightnessLevel_absentFile_holdsDefault():
    """No states/light (null) -> the fixed default, no fabricated auto behavior."""
    assert _probe("brightnessLevel", None, _CFG, _fresh(), False) == 0.70


@nodeless
def test_brightnessLevel_nullLux_holdsDefault():
    """Saturated reading (lux=null, honest) -> the fixed default, never 0/inf."""
    light = {"lux": None, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _fresh(), False) == 0.70


@nodeless
def test_brightnessLevel_staleTs_holdsDefault():
    """A reading older than luxStaleSec -> the fixed default (honest fallback)."""
    light = {"lux": 1.0, "ts": _TS}
    # 20s later, luxStaleSec=10 -> stale -> default (NOT the dark minLevel).
    assert _probe("brightnessLevel", light, _CFG, _fresh(20000), False) == 0.70


@nodeless
def test_brightnessLevel_stopAlarmDarkLux_isFullBrightness():
    """LOAD-BEARING (US-484-b supersedes the original 0.40 floor): Spool 6d ch.4
    makes a real STOP FULL brightness always, so the darkest cabin cannot dim the
    PULL-OVER alarm at all. Full coverage in test_dashboard_stop_tier_safety.py."""
    light = {"lux": 1.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _fresh(), True) == 1.0


@nodeless
def test_brightnessLevel_stopAlarmBrightLux_staysFull():
    """A bright reading under a STOP is full for both reasons -- the ch.4
    override and the ambient curve agree."""
    light = {"lux": 5000.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _fresh(), True) == 1.0


@nodeless
def test_brightnessLevel_stopAlarmStaleFeed_isStillFull():
    """A STOP with a stale/dead feed does NOT fall back to the 0.70 default --
    the alarm overrides the honest fallback too (ch.4)."""
    light = {"lux": 1.0, "ts": _TS}
    assert _probe("brightnessLevel", light, _CFG, _fresh(20000), True) == 1.0


@nodeless
def test_brightnessLevel_missingConfig_usesGroundedDefaults():
    """No injected config -> built-in grounded defaults (preview/file:// safe)."""
    light = {"lux": 1.0, "ts": _TS}
    # dark + no alarm -> minLevel default (0.15).
    assert _probe("brightnessLevel", light, None, _fresh(), False) == 0.15


# ---------------------------------------------------------------------------
# brightnessAlarmActive -- a real active STOP present (drives the alarm floor).
# ---------------------------------------------------------------------------


@nodeless
def test_brightnessAlarmActive_stopCode_isTrue():
    data = {"codes": [{"code": "P0300", "severity": "stop"}]}
    assert _probe("brightnessAlarmActive", data) is True


@nodeless
def test_brightnessAlarmActive_watchCode_isFalse():
    """WATCH is a real alert but not the PULL-OVER alarm -> no forced floor."""
    data = {"codes": [{"code": "P0420", "severity": "watch"}]}
    assert _probe("brightnessAlarmActive", data) is False


@nodeless
def test_brightnessAlarmActive_noCodesOrUnavailable_isFalse():
    assert _probe("brightnessAlarmActive", {"codes": []}) is False
    assert _probe("brightnessAlarmActive", None) is False


# ---------------------------------------------------------------------------
# Static wiring -- the shipped dist assets carry the consumer plumbing. These
# run without node (they are the deploy-truth the PI-RUNTIME AC-7 rests on).
# ---------------------------------------------------------------------------


def test_js_exports_theBrightnessApi():
    js = _read(_JS)
    for name in ("brightnessCurve", "brightnessLevel", "brightnessAlarmActive"):
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


def test_js_appliesBrightnessViaCssVar():
    """Brightness is applied as a CSS var on the screen frame (software dim)."""
    js = _read(_JS)
    assert 'setProperty("--display-brightness"' in js


def test_js_readsInjectedConfigGlobal():
    """The curve values come from the injected config global, not hardcoded."""
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
