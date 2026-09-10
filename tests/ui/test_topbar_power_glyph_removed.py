################################################################################
# File Name: test_topbar_power_glyph_removed.py
# Purpose/Description: US-696 (F-132) -- the lightning glyph is GONE from the top
#   bar, and the POWER MEASUREMENT it displayed is not.
#
#   THE CIO'S RULING: "if I can see the screen the power is on", so a glyph that
#   restates that is spending a slot in a band that has no slots to spare. The
#   argument he was given and overrode is recorded in the story and is not
#   re-argued here: the glyph distinguished `external` (green) from `battery`
#   (amber) and was therefore the only on-screen signal during a UPS ride-down --
#   the one window where "screen lit => mains present" is false. His call is that
#   the automatic sequenced poweroff makes that signal unactionable.
#
#   WHY A REMOVAL NEEDS ITS OWN FILE, AND WHY HALF OF IT IS POSITIVE. A deletion
#   test is satisfied by deleting far too much: "no #glyph-power in the DOM" is
#   equally true of a top bar that failed to render at all, of a carousel.js that
#   threw on load, and of a `glyphs` block someone removed wholesale. Every
#   absence asserted below is therefore read in the SAME pass as the siblings
#   that must survive it -- BT, sync and WiFi in the markup; `btGlyphState` /
#   `syncGlyphState` / `wifiGlyphState` in the source; the other three keys in
#   the view. That is this office's standing lesson (US-638): an absence measured
#   on a surface that did not render is not a measurement.
#
#   THE LOAD-BEARING PIN IS THE ONE THAT IS NOT ABOUT THE GLYPH.
#   `test_theMeasurementSurvivedTheDisplay_*` is the story's third validation
#   criterion and the only one that can fail in the direction that would matter
#   on the car: `power.source` is the SENSED fact (PowerSourceProvider SSOT,
#   US-502) and other consumers read it. Removing a DISPLAY must not remove a
#   MEASUREMENT, and the two are one keystroke apart in this file's diff.
#
#   THE SYSTEM STATUS CARD'S POWER ROW STAYS. It is a drill-down with a typed
#   reason, not chrome, and the ruling was about the top bar. Pinned here rather
#   than left to the drill-down suite, because "the CIO asked for the power
#   display to go" is exactly the sentence a future session would over-apply.
#
#   BAND BUDGET (F-127): removing a glyph FREES space, and the confirmation the
#   story asks for lives in test_topbar_three_column_grid.py where the width
#   model is. See the finding recorded there -- the left cluster overruns its
#   guaranteed track share TODAY, before and after this story, because the P-6
#   WiFi glyph shipped five characters wide against a guard that modelled one.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Ralph (Rex)  | Initial -- US-696 power glyph removal + the pin
#               |              | that the sensed source outlived its display.
# ================================================================================
################################################################################

"""US-696: the top-bar power glyph is removed; `power.source` is not."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
    ),
)

import render_harness as rh  # noqa: E402

from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

_DASHBOARD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src",
    "pi",
    "ui",
    "dashboard",
)
_HTML_PATH = os.path.join(_DASHBOARD, "dashboard.html")
_CSS_PATH = os.path.join(_DASHBOARD, "dashboard.css")
_JS_PATH = os.path.join(_DASHBOARD, "carousel.js")

# The shipped panel, not the harness default -- a top-bar glyph is a 3.5" signal
# and measuring it at 1920x1080 resolves media queries the operator never sees.
PANEL = (480, 320)

# The glyphs that MUST outlive this story. Every absence assertion below is read
# in the same pass as this list, so a bar that failed to render cannot pass.
SURVIVING_GLYPH_IDS = ("glyph-bt", "glyph-sync", "glyph-wifi")

# The state functions that MUST outlive `powerGlyphState`. Same purpose: a
# truncated or unreadable carousel.js cannot satisfy the removal by accident.
SURVIVING_GLYPH_FNS = ("btGlyphState", "syncGlyphState", "wifiGlyphState")

_NOW = "2026-09-10T14:20:00Z"


def _readText(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _stripHtmlComments(markup: str) -> str:
    """Markup with comments removed.

    The top bar's comments are long design prose that legitimately DISCUSS ids
    -- including, after this story, the ruling that removed one. Only what
    actually paints may satisfy or fail a structural assertion.
    """
    return re.sub(r"<!--.*?-->", "", markup, flags=re.DOTALL)


def _stripJsComments(js: str) -> str:
    """Source with block and line comments removed, for the same reason.

    A comment recording that `powerGlyphState` was deleted is desirable; it must
    not be what makes the grep for it non-empty.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return re.sub(r"(?m)//.*$", "", js)


def _systemStatus(**overrides: Any) -> dict:
    """A payload from the SHIPPED producer's own builder, never hand-written.

    A hand-written fixture stays green through a producer rename (US-628); this
    story's whole risk is that a producer field goes missing behind a display
    change, so the fixture has to come from the producer.
    """
    args: dict[str, Any] = {
        "obdLinkState": "linked",
        "obdRetries": 0,
        "obdLastSeenS": 1,
        "syncLastOkTs": "2026-09-10T14:19:40Z",
        "syncRows": 1204,
        "syncPending": 0,
        "syncStale": False,
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": _NOW,
        "obdAvailable": True,
    }
    args.update(overrides)
    return buildSystemStatusState(**args)


def _view(fn: str, *args: Any):
    """One pure carousel.js view function, evaluated under node."""
    # encoding="utf-8" is load-bearing on Windows: `text=True` alone decodes
    # node's UTF-8 stdout with the locale codec (cp1252 here), which turns the
    # tile's em-dash into U+FFFD and fails a correct assertion.
    proc = subprocess.run(
        [_NODE, _PROBE, fn] + [json.dumps(a) for a in args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _surface(payload: Any):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    routes = {} if payload is None else {"/system-status": payload}
    tree = rh.runDashboard(routes=routes, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


# ---------------------------------------------------------------------------
# AC-1 -- the element is gone from the bar the operator actually looks at.
# ---------------------------------------------------------------------------


def test_renderedTopBar_hasNoPowerGlyph_andStillPaintsItsSiblings():
    """THE story's first validation criterion, on the RENDERED surface.

    `pathById` returning None is only evidence if the bar rendered at all, so
    the three survivors are resolved AND confirmed displayed in the same boot.
    Without that pair this test passes on a carousel.js that throws at load.
    """
    surface = _surface(_systemStatus())

    for glyphId in SURVIVING_GLYPH_IDS:
        path = surface.pathById(glyphId)
        assert path is not None, f"#{glyphId} vanished with the power glyph"
        assert surface.rendered(path), f"#{glyphId} is in the DOM but not displayed"

    assert surface.pathById("glyph-power") is None, (
        "the lightning glyph is still in the rendered top bar"
    )


def test_shippedMarkup_declaresNoPowerGlyph():
    """The markup SSOT, comments stripped.

    Read separately from the rendered check because they fail differently: a
    span left in the markup but hidden by CSS would pass the render test and
    still be a slot the F-127 budget is charged for.
    """
    markup = _stripHtmlComments(_readText(_HTML_PATH))

    for glyphId in SURVIVING_GLYPH_IDS:
        assert f'id="{glyphId}"' in markup, f"{glyphId} lost its slot"
    assert 'id="glyph-power"' not in markup


def test_noOrphanedPowerGlyphRule_isLeftInTheStylesheet():
    """A style rule for an element that no longer exists is the stale-residue
    class this sprint family exists to remove. Today the glyph colours are bound
    generically by `[data-state]` and there is no `#glyph-power` rule -- this
    pins that nobody adds one back, and that nobody 'tidied' the generic rule
    away with it, which would silently grey out the three survivors.
    """
    css = _readText(_CSS_PATH)

    assert "#glyph-power" not in css
    assert '#topbar .glyph[data-state="amber"]' in css
    assert '#topbar .glyph[data-state="ok"]' in css


# ---------------------------------------------------------------------------
# AC-2 -- the state function had exactly one consumer, so it goes with it.
# ---------------------------------------------------------------------------


def test_carouselJs_neitherDefinesNorExportsPowerGlyphState():
    """`powerGlyphState` is dead once the glyph is gone -- a state function with
    no consumer is precisely the residue this story is removing.

    Comments are stripped first: the deletion is worth RECORDING in a comment,
    and a recording must not be what keeps the symbol grep non-empty.
    """
    source = _stripJsComments(_readText(_JS_PATH))

    for fn in SURVIVING_GLYPH_FNS:
        assert fn in source, f"{fn} was deleted along with powerGlyphState"
    assert "powerGlyphState" not in source


def test_glyphView_carriesTheOtherThreeStates_andNoPowerKey():
    """The view is where the glyph's state was computed. Asserting the exact key
    SET rather than `"power" not in glyphs` is deliberate: the negative alone is
    satisfied by returning `{}`, which would blank the whole bar and is the
    single most likely way to over-delete here.
    """
    view = _view("systemStatusView", _systemStatus())

    assert sorted(view["glyphs"]) == ["bt", "sync", "wifi"]
    assert view["glyphs"]["bt"] == "ok"
    assert view["glyphs"]["sync"] == "ok"


# ---------------------------------------------------------------------------
# AC-3 -- THE MEASUREMENT SURVIVED THE DISPLAY. The one that matters on the car.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,value,level",
    [
        ("external", "EXTERNAL", "ok"),
        ("battery", "BATTERY", "amber"),
        ("unknown", "—", "unavailable"),
    ],
)
def test_theMeasurementSurvivedTheDisplay_sourceIsSensedAndStillRendered(
    source: str, value: str, level: str
):
    """`power.source` is the SENSED fact, not chrome -- other consumers read it.

    Both halves are asserted because they fail independently: the producer could
    stop emitting the field (the payload assertion catches it) or the tile could
    stop rendering it (the tile assertion catches it), and this story's diff
    touches the line between them. All three sensed states are swept, because a
    removal that collapsed the vocabulary to one value would satisfy any single
    case -- including `unknown`, where honest-instrument forbids a confident
    reading and the tile must still say so.
    """
    payload = _systemStatus(powerSource=source)

    assert payload["power"]["source"] == source

    tile = _view("powerTile", payload["power"])
    assert tile["value"] == value
    assert tile["level"] == level


def test_theSystemStatusCard_stillCarriesItsPowerRow():
    """The drill-down Power row STAYS -- it is a typed reason, not chrome, and
    the ruling was about the top bar.

    Driven from a BATTERY payload on purpose: `systemIssueRows` lists what is
    not ok, so a healthy external supply would be absent from it for the right
    reason and this test would pass with the row deleted.
    """
    payload = _systemStatus(powerSource="battery")
    view = _view("systemStatusView", payload)

    assert view["tiles"]["power"]["value"] == "BATTERY"
    assert view["tiles"]["power"]["level"] == "amber"

    labels = [row["label"] for row in view["drill"]["rows"]]
    assert "POWER" in labels, f"the Power row left with the glyph: {labels}"
