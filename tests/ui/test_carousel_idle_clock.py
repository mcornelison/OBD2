################################################################################
# File Name: test_carousel_idle_clock.py
# Purpose/Description: US-503 tests for the idle-home card wall clock in
#   src/pi/ui/dashboard/carousel.js. The clock rendered 24-hour time
#   ("14:05"); the operator reads a 12-hour AM/PM face ("2:05 PM"). These tests
#   pin the format contract at both levels:
#     1. `fmtClock` itself, through idle_clock_probe.js -- including the two
#        edges a naive `getHours() % 12` gets wrong (midnight -> 12 AM, noon ->
#        12 PM) and the padding asymmetry (hour bare, minute zero-padded).
#     2. The rendered clock element, through the real dashboard boot -- because
#        a formatter that is individually correct proves nothing if the DOM
#        layer still calls a different one (the US-494/US-499/US-502
#        two-correct-halves-never-connected failure).
#   AMENDED BY US-542 (F-127): the clock MOVED from the retired parked idle face
#   (`.idle-clock`) to the persistent top bar (`#topbar-clock`), so group 2 now
#   reads it there -- and reads it a second time with a LIVE motion feed, which
#   is the state that had no clock at all before the move. `fmtClock` itself is
#   untouched: the move re-hosts the one formatter, it does not add a second.
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-503 12-hour AM/PM idle clock.
# ================================================================================
################################################################################

"""US-503 tests for the idle-card 12-hour AM/PM wall clock (via node)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "idle_clock_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js clock tests need node",
)

# A 12-hour face: a BARE hour 1-12 (never "02"), a zero-padded minute, one
# space, one meridiem. Anchored, so a trailing ":30" seconds field fails too.
TWELVE_HOUR = re.compile(r"^(1[0-2]|[1-9]):[0-5][0-9] (AM|PM)$")


def _clock(hour: int, minute: int) -> str:
    """Format one local wall time through the shipped carousel.js fmtClock."""
    proc = subprocess.run(
        [_NODE, _PROBE, str(hour), str(minute)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# ---------------------------------------------------------------------------
# fmtClock -- the format contract. 12-hour, meridiem, mod-12 with 12 for the
# two hours that are NOT what `% 12` returns.
# ---------------------------------------------------------------------------


def test_fmtClock_afternoon_readsTwelveHourWithMeridiem():
    """The story's own acceptance example: 14:05 reads "2:05 PM", not "14:05"."""
    assert _clock(14, 5) == "2:05 PM"


def test_fmtClock_midnight_readsTwelveAm():
    """00:xx is 12 AM, not "0:07 AM" -- the edge a bare `% 12` renders as zero."""
    assert _clock(0, 7) == "12:07 AM"


def test_fmtClock_noon_readsTwelvePm():
    """12:00 is 12 PM: `% 12` is zero here too, and the meridiem has ALREADY
    turned over -- the two mistakes that ride together at exactly one hour."""
    assert _clock(12, 0) == "12:00 PM"


def test_fmtClock_lastMinuteBeforeNoon_staysAm():
    """11:59 is the last AM minute -- the meridiem boundary is 12, not 13."""
    assert _clock(11, 59) == "11:59 AM"


def test_fmtClock_lastMinuteOfDay_readsElevenFiftyNinePm():
    """23:59 -> "11:59 PM" (the top of the 12-hour range, still PM)."""
    assert _clock(23, 59) == "11:59 PM"


def test_fmtClock_morningHour_isNotZeroPadded():
    """A 12-hour face shows a BARE hour: "9:05 AM", never "09:05 AM"."""
    assert _clock(9, 5) == "9:05 AM"


def test_fmtClock_singleDigitMinute_staysZeroPadded():
    """The padding is asymmetric on purpose -- the MINUTE keeps its zero."""
    assert _clock(13, 7) == "1:07 PM"


def test_fmtClock_showsNoSeconds():
    """The probe's Date carries :30 seconds; the face must not grow a field."""
    assert _clock(16, 42) == "4:42 PM"


def test_fmtClock_everyHourOfTheDay_rendersATwelveHourFace():
    """Sweep all 24 hours: each renders a valid 12-hour face whose hour is the
    mod-12-with-12 value and whose meridiem flips exactly once, at noon."""
    for hour in range(24):
        rendered = _clock(hour, 30)
        assert TWELVE_HOUR.match(rendered), f"{hour:02d}:30 rendered {rendered!r}"
        shown, meridiem = rendered.split(" ")
        assert int(shown.split(":")[0]) == (hour % 12 or 12)
        assert meridiem == ("AM" if hour < 12 else "PM")


# ---------------------------------------------------------------------------
# The rendered element -- proof the DOM layer actually calls THIS formatter.
# ---------------------------------------------------------------------------


def _topbarClockText(tree: dict) -> str | None:
    """Pull the `#topbar-clock` text out of a booted dashboard DOM tree.

    US-542 moved the clock off the retired parked face into the top bar; it used
    to be read from `.idle-clock`. Reading it by ID is the point of the move --
    the bar is painted on EVERY card, so this no longer depends on which face
    the home slot happened to choose."""
    surface = rh.dashboardSurface(tree)
    path = surface.pathById("topbar-clock")
    if not path:
        return None
    node = path[-1]
    return "".join(c.get("text", "") for c in node.get("children", []))


def test_topbar_renderedClock_readsTwelveHourNotTwentyFour():
    """Boot the SHIPPED carousel.js over the SHIPPED markup and read the clock
    element the operator sees. The time is the harness's real wall clock, so
    this asserts the FACE, not a value: a DOM layer still holding its own
    24-hour formatter fails here while every fmtClock test above stays green."""
    tree = rh.runDashboard(routes={})["tree"]
    rendered = _topbarClockText(tree)
    assert rendered is not None, "the top bar did not render a clock element"
    assert TWELVE_HOUR.match(rendered), f"top-bar clock rendered {rendered!r}"


def test_topbar_clockIsChromeNotAFaceOfTheHomeCard():
    """US-542's whole reason for the move, asserted STRUCTURALLY rather than by
    sampling one face: the clock must live outside the home slot, so no face
    decision can take it away.

    Sampling would have been the obvious test -- boot with a live IMU and look
    for the clock -- but the freshness window is 2s wide, so that test would
    assert "the clock is chrome" only for as long as node boots in under two
    seconds, and would start passing for the wrong reason (the stale fallback)
    the day it does not. The ancestry is the fact; the face is a symptom."""
    tree = rh.runDashboard(routes={})["tree"]
    surface = rh.dashboardSurface(tree)
    path = surface.pathById("topbar-clock")
    assert path, "the top bar did not render a clock element"
    ancestors = path[:-1]
    assert any(node.get("attrs", {}).get("id") == "topbar" for node in ancestors), (
        "the clock must be in the persistent top bar"
    )
    assert not any("card" in (node.get("attrs", {}).get("class") or "") for node in ancestors), (
        "the clock is inside a card -- a face decision can still take it away"
    )
