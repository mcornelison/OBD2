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
#   US-894-e: the Battery card is retired; these rules now hold on the System
#   page's UPS detail (upsDetailView), its successor.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-504 verdict vocab + TEMP removal.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-e): the Battery card retired;
#               |              | every rule re-pointed at the System page's UPS
#               |              | detail (upsDetailView / systemStatusView). The
#               |              | unknown verdict reads `--` (spec s4.6.1); the
#               |              | F-9 line is the detail's healthCheck.
# ================================================================================
################################################################################

"""US-504: the UPS detail speaks Spool's verdict and never alarms."""

import json
import os
import shutil
import subprocess

import pytest

from tests.ui.render_harness import _fnBody

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

# MOVED PIN (US-894-e): the Battery card's view is now the UPS detail. The
# system-status beside the cell supplies only the source + LAST STOP.
_STATUS = {"power": {"source": "external", "reasons": {}}, "ts": _TS}


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


def _detail(battery: dict) -> dict:
    return _view("upsDetailView", _STATUS, battery, None)


def _js() -> str:
    with open(_JS, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# AC-1 -- the TEMP tile is gone (no source can ever fill it).
# MOVED PIN (US-894-e): pinned on the UPS detail, the card's successor.
# ---------------------------------------------------------------------------


def test_upsDetail_hasNoTemp():
    """The MAX17048 has no temperature register, so the tile had no source."""
    detail = _detail(_battery())
    assert not any("temp" in k.lower() for k in detail)


def test_upsDetail_ignoresAnAmbientTempEvenWhenPresent():
    """Even a populated ambient_temp_c does not resurrect the tile -- removal
    is structural, not a null-check. (The COLUMN stays for a future BMP390.)"""
    detail = _detail(_battery(ambientTempC=21.5))
    assert not any("temp" in k.lower() for k in detail)
    assert "21.5" not in json.dumps(detail)


def test_renderUpsDetail_paintsNoTemp():
    """The DOM renderer must not paint a temperature either (MOVED PIN
    (US-894-e): renderBatteryHealthBody is gone with the card)."""
    body = _fnBody(_js(), "renderUpsDetail")
    assert "temp" not in body.lower()


# ---------------------------------------------------------------------------
# AC-3/AC-5 -- ONE vocabulary, and it never alarms.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("good", "GOOD"),
        ("degraded", "DEGRADED"),
        ("replace", "REPLACE"),
        # MOVED PIN (US-894-e): spec s4.6.1 -- `--`, the page's no-data mark.
        ("unknown", "--"),
    ],
)
def test_healthTile_rendersTheSpoolVerdictWord(verdict, expected):
    assert _detail(_battery(health=verdict))["health"]["value"] == expected


def test_goodVerdict_readsOk():
    assert _detail(_battery(health="good"))["health"]["level"] == "ok"


def test_unknownVerdict_readsUnavailableNotOk():
    """The honest end-state of this subsystem today: no confident claim."""
    assert _detail(_battery(health="unknown"))["health"]["level"] == "unavailable"


@pytest.mark.parametrize("verdict", ["degraded", "replace"])
def test_degradedAndReplace_areInformationalNotAPassClaim(verdict):
    """Spool: informational at EVERY state including `replace`. `ok` would
    claim health the data does not support; `down` would alarm. Neutral is the
    only tier that is neither."""
    assert _detail(_battery(health=verdict))["health"]["level"] == "neutral"


@pytest.mark.parametrize("verdict", _VERDICTS)
def test_noVerdictEverPaintsAlarmRed(verdict):
    """The load-bearing severity rule -- a thinned UPS margin is not a car
    risk and must never own the screen."""
    level = _detail(_battery(health=verdict))["health"]["level"]
    # MOVED PIN (US-894-e): the UPS detail is never amber either (s4.6.1).
    assert level not in (_ALARM_LEVEL, "amber")


def test_theRetiredDisplayTiersAreGone():
    """green/attn/low were a SECOND enum for the `health` fact. Leaving them
    mapped keeps a live red path reachable by a value nothing emits -- exactly
    how a future producer would resurrect the alarm this story forbids."""
    for retired in ("green", "attn", "low"):
        health = _detail(_battery(health=retired))["health"]
        assert health["value"] == "--"  # MOVED PIN (US-894-e): was an em dash
        assert health["level"] == "unavailable"


# ---------------------------------------------------------------------------
# AC-4 -- last-health-check travels with every verdict. MOVED PIN (US-894-e):
# the F-9 line is the UPS detail's own healthCheck line (was the tail of the
# HEALTH tile's detail string).
# ---------------------------------------------------------------------------


def test_healthDetail_carriesTheLastCheckDateAndAge():
    detail = _detail(_battery(health="good"))
    assert detail["healthCheck"] == "last health check · 2026-07-25 (7 days ago)"


def test_unknownVerdict_stillShowsWhenTheLastRealCheckWas():
    """The honest state: verdict unknown, but the DATE of the last real check
    is itself the signal -- not hidden behind the unknown."""
    detail = _detail(_battery(health="unknown", lastHealthCheckTs="2026-05-16T09:00:00Z"))
    assert "2026-05-16" in detail["healthCheck"]
    assert "77 days ago" in detail["healthCheck"]


def test_noHealthCheckEver_readsNeverNotToday():
    detail = _detail(_battery(lastHealthCheckTs=None))
    assert detail["healthCheck"] == "last health check · never"


# ---------------------------------------------------------------------------
# The System PAGE carries all of the above (the page view, not just the detail
# view -- a correct view the page never asks for renders nothing). MOVED PIN
# (US-894-e): the Battery card and its sourceCardSpec entry are retired; the
# seam is now systemStatusView, whose upsDetail the overlay paints.
# ---------------------------------------------------------------------------


def _systemPage(battery: dict) -> dict:
    return _view("systemStatusView", _STATUS, None, battery, None)


def test_theBatteryCardIsRetired():
    assert _view("sourceCardSpec", "battery-health") is None


def test_systemPage_carriesTheVerdictWord():
    page = _systemPage(_battery(health="replace"))
    assert page["upsDetail"]["health"]["value"] == "REPLACE"
    assert page["upsDetail"]["health"]["level"] != _ALARM_LEVEL


def test_systemPage_hasNoTempTile():
    page = _systemPage(_battery())
    assert not any("temp" in k.lower() for k in page["upsDetail"])
