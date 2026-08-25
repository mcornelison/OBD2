################################################################################
# File Name: test_carousel_battery_health_verdict.py
# Purpose/Description: US-504 tests for the Battery section of the merged Health
#   card. Three things move here:
#     1. The TEMP tile is GONE. The MAX17048 is a voltage-based fuel gauge with
#        NO temperature register (Spool), so the tile could only ever have shown
#        "not captured" or a fabricated number. The `ambient_temp_c` COLUMN
#        stays -- a future BMP390 legitimately fills it.
#     2. ONE verdict vocabulary end-to-end. The card spoke green/attn/low while
#        the (new) producer speaks Spool's good/degraded/replace/unknown -- two
#        enums for one fact is the cross-module identity drift that cost the
#        9-drain saga. The display tiers are retired; the card carries Spool's
#        words.
#     3. NEVER alarm-red, at ANY verdict state including `replace` (Spool: the
#        UPS margin is ~12 min against the <1 min a clean shutdown needs, so a
#        thinned data-integrity margin must never compete with coolant or a
#        DTC-STOP on a driving surface).
#   Pure logic runs through the shared node probe; the browser-only DOM wiring
#   is pinned by reading the shipped artifact, because a correct view the
#   renderer never paints renders nothing (US-494/US-495/US-503).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-504 verdict vocab + TEMP removal.
# ================================================================================
################################################################################

"""US-504: the Battery section speaks Spool's verdict and never alarms."""

import json
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "pi", "ui", "dashboard", "carousel.js",
)

_TS = "2026-08-01T12:00:00Z"

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

# Every verdict the producer can emit (pi/power/battery_health_verdict.py).
_VERDICTS = ("good", "degraded", "replace", "unknown")

# The tile level that paints alarm red. No battery verdict may ever reach it.
_ALARM_LEVEL = "down"


def _view(fn: str, *args: object) -> object:
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    # encoding pinned: the card's copy carries "·" and "—", which mojibake
    # through the Windows locale codec and turn a real assertion into noise.
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _battery(**extra: object) -> dict:
    payload: dict = {
        "health": "good",
        "vcellV": 4.02,
        "soc": 88,
        "socCalibrated": True,
        "draining": False,
        "ambientTempC": None,
        "lastHealthCheckTs": "2026-07-25T09:00:00Z",
        "ts": _TS,
    }
    payload.update(extra)
    return payload


def _js() -> str:
    with open(_JS, encoding="utf-8") as fh:
        return fh.read()


def _fnBody(js: str, name: str) -> str:
    """The source text of one `function <name>(` up to the next declaration."""
    start = js.index("function " + name + "(")
    candidates = [
        js.find("\n  function ", start + 1),
        js.find("\n    function ", start + 1),
        js.find("\n      function ", start + 1),
    ]
    ends = [e for e in candidates if e != -1]
    return js[start: min(ends)] if ends else js[start:]


# ---------------------------------------------------------------------------
# AC-1 -- the TEMP tile is gone (no source can ever fill it).
# ---------------------------------------------------------------------------


def test_batteryHealthView_hasNoTempTile():
    """The MAX17048 has no temperature register, so the tile had no source."""
    view = _view("batteryHealthView", _battery())
    assert "temp" not in view


def test_batteryHealthView_ignoresAnAmbientTempEvenWhenPresent():
    """Even a populated ambient_temp_c does not resurrect the tile -- removal
    is structural, not a null-check. (The COLUMN stays for a future BMP390.)"""
    view = _view("batteryHealthView", _battery(ambientTempC=21.5))
    assert "temp" not in view


def test_renderBatteryHealthBody_paintsNoTempTile():
    """The DOM renderer must have lost the tile too: a view key removed while
    the renderer still appends it is a runtime crash, and a renderer still
    painting a tile the view no longer builds is the US-494 shape."""
    body = _fnBody(_js(), "renderBatteryHealthBody")
    assert "view.temp" not in body


# ---------------------------------------------------------------------------
# AC-3/AC-5 -- ONE vocabulary, and it never alarms.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("good", "GOOD"),
        ("degraded", "DEGRADED"),
        ("replace", "REPLACE"),
        ("unknown", "—"),
    ],
)
def test_healthTile_rendersTheSpoolVerdictWord(verdict, expected):
    view = _view("batteryHealthView", _battery(health=verdict))
    assert view["health"]["value"] == expected


def test_goodVerdict_readsOk():
    view = _view("batteryHealthView", _battery(health="good"))
    assert view["health"]["level"] == "ok"


def test_unknownVerdict_readsUnavailableNotOk():
    """The honest end-state of this subsystem today: no confident claim."""
    view = _view("batteryHealthView", _battery(health="unknown"))
    assert view["health"]["level"] == "unavailable"


@pytest.mark.parametrize("verdict", ["degraded", "replace"])
def test_degradedAndReplace_areInformationalNotAPassClaim(verdict):
    """Spool: informational at EVERY state including `replace`. `ok` would
    claim health the data does not support; `down` would alarm. Neutral is the
    only tier that is neither."""
    view = _view("batteryHealthView", _battery(health=verdict))
    assert view["health"]["level"] == "neutral"


@pytest.mark.parametrize("verdict", _VERDICTS)
def test_noVerdictEverPaintsAlarmRed(verdict):
    """The load-bearing severity rule -- a thinned UPS margin is not a car
    risk and must never own the screen."""
    view = _view("batteryHealthView", _battery(health=verdict))
    assert view["health"]["level"] != _ALARM_LEVEL


def test_theRetiredDisplayTiersAreGone():
    """green/attn/low were a SECOND enum for the `health` fact. Leaving them
    mapped keeps a live red path reachable by a value nothing emits -- exactly
    how a future producer would resurrect the alarm this story forbids."""
    for retired in ("green", "attn", "low"):
        view = _view("batteryHealthView", _battery(health=retired))
        assert view["health"]["value"] == "—"
        assert view["health"]["level"] == "unavailable"


# ---------------------------------------------------------------------------
# AC-4 -- last-health-check travels with every verdict.
# ---------------------------------------------------------------------------


def test_healthDetail_carriesTheLastCheckDateAndAge():
    view = _view("batteryHealthView", _battery(health="good"))
    assert view["health"]["detail"] == "last health check · 2026-07-25 (7 days ago)"


def test_unknownVerdict_stillShowsWhenTheLastRealCheckWas():
    """The honest state the card ships in: verdict unknown, but the DATE of the
    last real check is itself the signal -- not hidden behind the unknown."""
    view = _view(
        "batteryHealthView",
        _battery(health="unknown", lastHealthCheckTs="2026-05-16T09:00:00Z"),
    )
    assert "2026-05-16" in view["health"]["detail"]
    assert "77 days ago" in view["health"]["detail"]


def test_noHealthCheckEver_readsNeverNotToday():
    view = _view("batteryHealthView", _battery(lastHealthCheckTs=None))
    assert view["health"]["detail"] == "last health check · never"


# ---------------------------------------------------------------------------
# The Battery CARD carries all of the above (the card view, not just the source
# view -- a correct view the card never asks for renders nothing). US-540-b
# retired the merged Health card these two used to reach through; the seam they
# actually need is unchanged, so they now go through sourceCardView directly.
# ---------------------------------------------------------------------------


def _batteryCard(battery: dict) -> dict:
    spec = _view("sourceCardSpec", "battery-health")
    sysData = {"ts": _TS, "obd": {"connected": False}}
    return _view("sourceCardView", spec, battery, sysData, {}, 0)


def test_batteryCard_carriesTheVerdictWord():
    card = _batteryCard(_battery(health="replace"))
    assert card["view"]["health"]["value"] == "REPLACE"
    assert card["view"]["health"]["level"] != _ALARM_LEVEL


def test_batteryCard_hasNoTempTile():
    card = _batteryCard(_battery())
    assert "temp" not in card["view"]
