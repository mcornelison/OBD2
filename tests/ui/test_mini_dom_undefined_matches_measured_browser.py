################################################################################
# File Name: test_mini_dom_undefined_matches_measured_browser.py
# Purpose/Description: US-719 -- pin BOTH of mini_dom.js's value setters to the
#   table MEASURED in two real browser engines, so the harness is neither more
#   forgiving nor less forgiving than the thing it models.
#
#   THE TABLE IS MEASURED, NOT REASONED, AND THAT IS THE WHOLE POINT. The story
#   this file closes started from the claim "real browsers stringify
#   `textContent = undefined` to "undefined"". Nobody had run it. Measured in
#   headless Chrome 152 AND Edge 152 it is FALSE: the browser reads back "" with
#   0 child nodes, identical to "" and to null. mini_dom was already faithful
#   there. The unfaithful member of the family was the OTHER setter:
#   `setAttribute(name, undefined)` stores the STRING "undefined" in the browser
#   and stored "" in mini_dom.
#
#   🔴 THE PIN ON THE FAITHFUL SETTER IS THE LOAD-BEARING HALF. Without it, the
#   next author meets the false premise in a TD or a comment and "fixes"
#   `textContent` into painting a word the Pi's Chromium kiosk never paints --
#   and every test built on that harness goes red for a defect that cannot occur
#   on the panel.
#
#   LIKE FOR LIKE. The node driver below runs the SAME seven cases, in the same
#   order, with the same "stale" pre-write, as the browser probe recorded in
#   offices/ralph/evidence/US-719-textcontent-undefined-real-browser-probe.md.
#   The recorded case set and the driver's case set are compared, so a case
#   cannot be added to the pin without a browser measurement behind it.
#
#   WHAT THIS DOES NOT COVER, stated so nothing below is read as more:
#     * A tile that DELETES a key. The browser hides that exactly as mini_dom
#       does (`textContent = undefined` paints nothing), so no rendered
#       assertion anywhere can see it. That needs a source/contract check --
#       US-726, not this file.
#     * `innerHTML` (the browser paints "undefined" for it; mini_dom does not
#       implement it) and `setAttribute` called with ONE argument. Neither is
#       exercised by the shipped kits and neither was pinned against a
#       measurement here.
#     * Any engine or version other than the two recorded in MEASURED_ENGINES.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Ralph (Rex)  | Initial -- US-719 (PM ruling on BL-us719,
#               |              | option A): both setters pinned to the measured
#               |              | Chrome 152 / Edge 152 table.
# ================================================================================
################################################################################

"""US-719: mini_dom.js value setters match the table measured in real browsers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MINI_DOM_JS = os.path.join(_HERE, "mini_dom.js")
_NODE = shutil.which("node")
_NODE_TIMEOUT_SECONDS = 60

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- mini_dom.js is the harness the shipped JS runs under",
)

MEASURED_ON = "2026-09-10"
MEASURED_ENGINES = (
    "HeadlessChrome/152.0.0.0 (Google Chrome)",
    "HeadlessChrome/152.0.0.0 Edg/152.0.0.0 (Microsoft Edge)",
)
MEASUREMENT_EVIDENCE = (
    "offices/ralph/evidence/US-719-textcontent-undefined-real-browser-probe.md"
)

# Both engines returned this table byte-for-byte (raw JSON in the evidence file).
MEASURED_TEXT_CONTENT: dict[str, dict[str, Any]] = {
    "undefined": {"read": "", "nodes": 0},
    "null": {"read": "", "nodes": 0},
    "empty": {"read": "", "nodes": 0},
    "zero": {"read": "0", "nodes": 1},
    "false": {"read": "false", "nodes": 1},
    "nan": {"read": "NaN", "nodes": 1},
    "text": {"read": "x", "nodes": 1},
}
MEASURED_SET_ATTRIBUTE: dict[str, str] = {
    "undefined": "undefined",
    "null": "null",
    "empty": "",
    "zero": "0",
    "false": "false",
    "nan": "NaN",
    "text": "x",
}

# Mirrors the browser probe's script. `undefined` and NaN cannot travel as JSON,
# so the cases are built on the JS side and only their NAMES come back.
_DRIVER_JS = """
"use strict";
var M = require(__MINI_DOM__);
var doc = new M.Document();
var CASES = [["undefined", undefined], ["null", null], ["empty", ""], ["zero", 0],
             ["false", false], ["nan", NaN], ["text", "x"]];
var out = { textContent: {}, setAttribute: {} };
CASES.forEach(function (c) {
  var t = doc.createElement("span");
  t.textContent = "stale";
  t.textContent = c[1];
  out.textContent[c[0]] = { read: t.textContent, nodes: t.childNodes.length };
  var a = doc.createElement("span");
  a.setAttribute("data-x", c[1]);
  out.setAttribute[c[0]] = a.getAttribute("data-x");
});
process.stdout.write(JSON.stringify(out));
"""


def _runDriver(source: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(_NODE)],
        input=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_NODE_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, f"node driver failed:\n{completed.stderr}"
    result: dict[str, Any] = json.loads(completed.stdout)
    return result


@pytest.fixture(scope="module")
def harnessTable() -> dict[str, Any]:
    return _runDriver(_DRIVER_JS.replace("__MINI_DOM__", json.dumps(_MINI_DOM_JS)))


def test_textContent_undefined_readsBackEmptyWithNoChildNode_asMeasured(
    harnessTable: dict[str, Any],
) -> None:
    """
    Given: mini_dom's `textContent` setter
    When: `undefined` is assigned over existing text
    Then: it reads back "" with 0 child nodes -- what Chrome 152 and Edge 152 do

    THE FAITHFUL SETTER, PINNED SO IT STAYS FAITHFUL. This is the setter the
    original story wanted changed, on a premise nobody had measured. Changing it
    would make the harness paint a word the real panel never paints.
    """
    assert harnessTable["textContent"]["undefined"] == {"read": "", "nodes": 0}, (
        "mini_dom now paints something for `textContent = undefined`. A real "
        f"browser does NOT ({', '.join(MEASURED_ENGINES)}, measured {MEASURED_ON}, "
        f"{MEASUREMENT_EVIDENCE}): it reads back \"\" with 0 child nodes. "
        "Do not 'fix' this setter from the claim that browsers stringify it."
    )


def test_setAttribute_undefined_storesTheStringUndefined_asMeasured(
    harnessTable: dict[str, Any],
) -> None:
    """
    Given: mini_dom's `setAttribute`
    When: it is called with `undefined` as the value
    Then: the stored value is the STRING "undefined" -- what Chrome 152 and Edge 152 do

    THE UNFAITHFUL SETTER, FIXED. Storing "" made the harness more forgiving than
    the browser: a renderer writing `data-level` from a missing key gets
    `data-level="undefined"` on the Pi, which no `[data-level=...]` rule matches.
    """
    assert harnessTable["setAttribute"]["undefined"] == "undefined", (
        "mini_dom's setAttribute(name, undefined) stores "
        f"{harnessTable['setAttribute']['undefined']!r}; a real browser stores the "
        f"string 'undefined' ({', '.join(MEASURED_ENGINES)}, measured {MEASURED_ON})."
    )


def test_driverRunsExactlyTheMeasuredCases(harnessTable: dict[str, Any]) -> None:
    """
    Given: the node driver and the recorded browser table
    When: their case names are compared, per setter
    Then: they are identical -- no harness case lacks a browser measurement

    Without this, the full-table test below could quietly shrink (a case dropped
    from the driver) or grow a cell whose expected value was typed, not measured.
    """
    assert set(harnessTable["textContent"]) == set(MEASURED_TEXT_CONTENT)
    assert set(harnessTable["setAttribute"]) == set(MEASURED_SET_ATTRIBUTE)


@pytest.mark.parametrize("case", sorted(MEASURED_TEXT_CONTENT))
def test_textContent_everyMeasuredCase_matchesTheBrowser(
    harnessTable: dict[str, Any], case: str
) -> None:
    """
    Given: one case from the measured browser table
    When: mini_dom assigns it through `textContent`
    Then: the read-back text AND child-node count match the browser
    """
    assert harnessTable["textContent"][case] == MEASURED_TEXT_CONTENT[case]


@pytest.mark.parametrize("case", sorted(MEASURED_SET_ATTRIBUTE))
def test_setAttribute_everyMeasuredCase_matchesTheBrowser(
    harnessTable: dict[str, Any], case: str
) -> None:
    """
    Given: one case from the measured browser table
    When: mini_dom stores it through `setAttribute`
    Then: `getAttribute` returns what the browser returned
    """
    assert harnessTable["setAttribute"][case] == MEASURED_SET_ATTRIBUTE[case]


def test_buildTree_nullMarkupAttribute_stillStoresEmptyString() -> None:
    """
    Given: a parsed-markup attribute with no value (`hidden`), which arrives as null
    When: buildTree builds it through setAttribute
    Then: the attribute is present and "" -- NOT "null"

    The markup parser's null means "boolean attribute", which a browser parses as
    "". buildTree converts it BEFORE calling setAttribute; this pins that the
    setAttribute change did not reach through to the markup path.
    """
    source = """
"use strict";
var M = require(__MINI_DOM__);
var doc = new M.Document();
M.buildTree(doc, { tag: "div", attrs: { hidden: null, id: "card" }, children: [] }, doc.body);
var el = doc.getElementById("card");
process.stdout.write(JSON.stringify({ has: el.hasAttribute("hidden"),
                                      value: el.getAttribute("hidden"),
                                      hiddenIdl: el.hidden }));
""".replace("__MINI_DOM__", json.dumps(_MINI_DOM_JS))

    result = _runDriver(source)

    assert result == {"has": True, "value": "", "hiddenIdl": True}
