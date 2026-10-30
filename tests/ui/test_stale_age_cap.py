################################################################################
# File Name: test_stale_age_cap.py
# Purpose/Description: V0.30.19 hotfix (Iris RULING 2026-10-30, the S105 M7 age
#   rule on every page): every shown age goes through ONE helper, ageCountText --
#   floor, clamped at 0, capped at '999+' -- and each page keeps its own suffix.
#   Found at the V0.30.19 Gate G: the Engine stale note read '18021 s' at 5 h.
#   Guarded, through each page's REAL view (node probe):
#     1. the helper: 18021 -> '999+', 998.7 -> '998' (floor, not round),
#        negative -> '0', 999 -> '999', not a number -> null;
#     2. Engine and Driving header notes ('<n> s'), O2 ('<n> s old'), Light
#        ('<n> s'), Nav ('NO UPDATE <n> s'), the Warnings stale clause
#        ('last reading <n> s ago') and Motion/DATA ('<n> s ago');
#     3. one helper, not five: no other age writer floors or rounds on its own.
#   NOT GUARDED: minutes or hours (Iris: not in V0.30; a new ask if wanted).
# Author: Atlas
# Creation Date: 2026-10-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-30    | Atlas        | Initial -- V0.30.19 hotfix item 1.
# ================================================================================
################################################################################

"""The S105 M7 age cap on every page, through one helper."""

from __future__ import annotations

import os
import re
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests.ui.test_light_page import _view as _lightView  # noqa: E402
from tests.ui.test_nav_page import _JS, _NODE_ONLY, _call, _imu, _ms  # noqa: E402

NOW = datetime(2026, 10, 30, 15, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)

# (age in seconds, the count every page must show)
CASES = [(18021, "999+"), (998.7, "998"), (999, "999"), (1000, "999+"), (45.9, "45")]


def _iso(ageSec: float) -> str:
    return (NOW - timedelta(seconds=ageSec)).isoformat().replace("+00:00", "Z")


def _staleParam(ageSec: float, value: float, unit: str, band: str | None = None) -> dict[str, Any]:
    last: dict[str, Any] = {"value": value, "ts": _iso(ageSec)}
    if band is not None:
        last["band"] = band
    return {"value": None, "unit": unit, "stale": True, "ts": _iso(ageSec), "last": last}


@_NODE_ONLY
@pytest.mark.parametrize(
    ("age", "want"), [(18021, "999+"), (998.7, "998"), (999, "999"), (999.9, "999"), (1000, "999+"),
                      (-3.2, "0"), (0, "0")],
)
def test_ageCountText_floorClampCap(age: float, want: str):
    assert _call("ageCountText", age) == want


@_NODE_ONLY
@pytest.mark.parametrize("bad", [None, "12"])
def test_ageCountText_noAge_isNull(bad: Any):
    assert _call("ageCountText", bad) is None


@_NODE_ONLY
@pytest.mark.parametrize(("age", "want"), CASES)
def test_engine_staleNotes(age: float, want: str):
    params = {"ENGINE_LOAD": _staleParam(age, 34.5, "%"), "THROTTLE_POS": _staleParam(age, 12.2, "%"),
              "TIMING_ADVANCE": _staleParam(age, 14, "deg")}
    readings = _call("engineView", {"params": params}, NOW_MS)["readings"]
    assert {pid: r["note"] for pid, r in readings.items()} == {pid: want + " s" for pid in params}


@_NODE_ONLY
@pytest.mark.parametrize(("age", "want"), CASES)
def test_driving_staleNote(age: float, want: str):
    params = {"COOLANT_TEMP": _staleParam(age, 88, "C", "green")}
    reading = _call("drivingView", {"params": params}, None, NOW_MS)["readings"]["COOLANT_TEMP"]
    assert (reading["stale"], reading["note"]) == (True, want + " s")


@_NODE_ONLY
@pytest.mark.parametrize(("age", "want"), CASES)
def test_o2_staleMeta(age: float, want: str):
    front = {"value": None, "stale": True, "ts": _iso(age), "last": {"value": 0.45, "ts": _iso(age)}}
    reading = _call("o2View", {"front": front, "rear": None}, NOW_MS)["front"]["reading"]
    assert reading["meta"] == want + " s old"


@_NODE_ONLY
@pytest.mark.parametrize(("age", "want"), CASES[:3])
def test_light_staleAge(age: float, want: str):
    # light-stale is 14 s old at its own `now`; shift the clock to the wanted age.
    v = _lightView("light-stale", shiftMs=round((age - 14) * 1000))
    assert v["stale"] is True and v["age"]["text"] == want + " s"


@_NODE_ONLY
@pytest.mark.parametrize(("age", "want"), CASES[:3])
def test_nav_noUpdateBadge(age: float, want: str):
    imu = _imu("stale-imu")
    view = _call("navHeadingView", imu, _ms(imu["ts"]) + round(age * 1000), 3.0)
    assert (view["state"], view["badge"]) == ("stale", "NO UPDATE " + want + " s")


@_NODE_ONLY
@pytest.mark.parametrize(("age", "want"), CASES + [(-3.2, "0")])
def test_warnings_and_motion_keepTheirSuffix(age: float, want: str):
    assert _call("warningStaleText", _iso(age), NOW_MS) == "last reading " + want + " s ago"
    assert _call("freshAgeText", age) == want + " s ago"


def test_oneHelper_noPageFloorsOrRoundsAnAgeItself():
    """Every age writer calls ageCountText; none keeps its own floor/round/cap."""
    with open(_JS, encoding="utf-8") as fh:
        js = fh.read()
    for fn in ("drivingAgeText", "o2AgeText", "freshAgeText", "warningStaleText"):
        body = re.search(r"function " + fn + r"\([^)]*\) \{(.*?)\n  \}", js, re.S).group(1)
        assert "ageCountText(" in body, fn
        assert not re.search(r"Math\.(floor|round)", body), fn
    assert '"NO UPDATE " + ageCountText(age) + " s"' in js
    assert 'text: ageCountText(ageSec) + " s", tone: "warn"' in js
    # The only floor-and-cap in the file is the helper's own.
    assert len(re.findall(r"AGE_CAP_SEC \+ \"\+\"", js)) == 1
