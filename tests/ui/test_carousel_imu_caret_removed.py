################################################################################
# File Name: test_carousel_imu_caret_removed.py
# Purpose/Description: US-715 -- the static `.imu-caret` triangle is REMOVED from
#   the compass tape (CIO 2026-09-09), and the TAPE, its ticks and its labels all
#   STAY. Scope is exactly one element.
#
#   WHY THE REMOVAL AND THE RETENTION ARE PINNED TOGETHER, IN EVERY TEST BELOW.
#   "No caret renders" is satisfied by deleting the whole tape, by deleting the
#   live face, or by a harness that threw before painting anything -- three ways
#   to pass this story while destroying its subject. US-696 and US-697 both hit
#   this: an absence assertion is satisfied by deleting far too much. So every
#   absence claim here is PAIRED with a positive that the tape still drew, and
#   the file opens with a control that the live face painted at all.
#
#   THIS IS NOT A RE-SUPPRESSION OF `headingDeg`, AND THE TESTS SAY SO. The
#   charter's standing rule is that hiding a real measurement is the opposite
#   failure. The tape stays (section 1), the numeric HEADING tile stays
#   (section 4). Only static furniture goes.
#
#   THE BEARING NUMBER IS PINNED AS A SHAPE, NEVER AS A VALUE, AND THAT IS
#   DELIBERATE. `headingDeg` is WRONG on this tree today -- the body-frame axis
#   swap (US-708) and the magnetometer SNR (A-30) are both live, and I-us708b
#   holds six measured-red bearing assertions in
#   test_carousel_heading_bare_bearing_recorded_pass.py. A live east bearing
#   currently paints "0° N". Pinning 90 here would fail for SOMEBODY ELSE'S
#   reason and read as this story's regression. `^\d+° [NSEW]{1,3}$` is true
#   before and after the axis fix, so it measures what this story actually
#   changed: nothing.
#
#   THE TAPE STILL WILL NOT SCROLL CORRECTLY AFTER THIS STORY. That is the same
#   A-30 defect and it is NOT a regression -- this file removes furniture and
#   touches no producer. Nothing here should be read as the compass being fixed;
#   the tape remains the visible symptom, which is precisely why Atlas's
#   objection is satisfied by keeping it.
#
#   HARNESS FIDELITY LIMIT (TD-089), which is why no test below counts ticks:
#   mini_dom.js implements `removeChild` but NOT `firstChild`, so `renderTape`'s
#   clear is a NO-OP here and ticks ACCUMULATE across paints. Measured: the tick
#   geometry repeats ~9x in one render. Every tape claim here is therefore over
#   the SET of distinct geometries, never over a count. The CARET is unaffected
#   by this -- `buildTape` appends it ONCE at construction, not per paint.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Ralph (Rex)  | Initial -- US-715: remove the static IMU caret,
#               |              | keep the tape. Rendered absence + retention
#               |              | pairs, the three-file token sweep, the
#               |              | comment-only escape hatch, and the freed-top-6-
#               |              | units layout claim.
# ================================================================================
################################################################################

"""US-715: the static compass caret is removed; the tape it sat on stays."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
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

from pi.bus.sample import Sample  # noqa: E402
from pi.sensors.imu_state_bridge import (  # noqa: E402
    IMU_STATE_FILENAME,
    STANDARD_GRAVITY_MS2,
    TOPIC_IMU_ACCEL,
    TOPIC_IMU_MAG,
    ImuStateBridge,
)

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default.
PANEL = (480, 320)

_REPO = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
_DASH = os.path.join(_REPO, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_CSS = os.path.join(_DASH, "dashboard.css")
_HTML = os.path.join(_DASH, "dashboard.html")

# VC2's subject: markup, CSS and JS. Named as a tuple so that a file JOINING the
# dashboard's shipped set is a one-line change here rather than a silent gap --
# US-710's lesson, that a sweep cannot notice it stopped being asked about a tree.
_SHIPPED_FILES = (_HTML, _CSS, _CAROUSEL_JS)

# The class token this story deletes. Spelled ONCE.
_CARET_CLASS = "imu-caret"

# The CIO's ruling, the date the comments must record.
_DECISION_DATE = "2026-09-09"

G = STANDARD_GRAVITY_MS2

_T0_ISO = "2026-08-31T12:00:00Z"
_T0_MS = 1787227200000  # 2026-08-31T12:00:00Z in epoch ms
_NOW_MS = _T0_MS + 1000  # one second later: inside carousel.js's 2 s IMU window

# A magnetometer vector the REAL producer resolves to a live bearing against
# level gravity. Which bearing is NOT asserted anywhere in this file -- see the
# header. It is here to make the tape AVAILABLE, nothing more.
_MAG_LIVE = (0.0, 20.0, -40.0)

# Measured off the shipped renderer BEFORE this story's edit, and re-asserted
# after it, which is the whole of VC5: removing a polygon that occupied y 0..6
# must move nothing else. Ticks hang from y1 down to y2; labels sit on y.
_TAPE_VIEWBOX = "0 0 100 26"
_TICK_Y1 = {8, 10}  # major ticks start at 8, minor at 10
_TICK_Y2 = {16}
_LABEL_Y = {25}
# The caret occupied the top 6 units. After removal the tape's topmost ink is
# the major tick at y=8, so nothing may be drawn above it.
_FREED_TOP_UNITS = 6


# ------------------------------------------------------------------- producer


def _sample(topic: str, value: Any, unit: str, *, seq: int = 1, capture: float = 0.0):
    """One bus sample, stamped at the pinned instant."""
    return Sample(
        topic=topic,
        source="imu",
        value=value,
        unit=unit,
        tsUtc=_T0_ISO,
        tsCapture=capture,
        driveId=None,
        dataSource="real",
        seq=seq,
    )


def _liveImuState(tmpPath: Path) -> dict[str, Any]:
    """A LIVE states/imu payload written by the REAL bridge, carrying a bearing.

    Through the real producer rather than a hand-written dict: a fixture written
    to agree with the renderer cannot witness that the tape is fed at all, and
    an AVAILABLE tape is the precondition for every retention claim below.
    """
    bridge = ImuStateBridge(None, str(tmpPath))
    bridge.handleSample(_sample(TOPIC_IMU_MAG, _MAG_LIVE, "uT"))
    bridge.handleSample(_sample(TOPIC_IMU_ACCEL, (0.0, 0.0, G), "m/s^2"))
    return json.loads((tmpPath / IMU_STATE_FILENAME).read_text(encoding="utf-8"))


# --------------------------------------------------------------------- render


def _run(imu: Any) -> dict[str, Any]:
    """Boot the SHIPPED carousel over the SHIPPED markup at the panel size."""
    return rh.runDashboard(
        routes={"/imu": imu},
        steps=[{"flush": 4}],
        viewport=PANEL,
        nowMs=_NOW_MS,
    )["tree"]


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []) or []:
            yield from _walk(child)


def _classOf(node: dict[str, Any]) -> str:
    return str(node.get("attrs", {}).get("class") or "")


def _classes(node: dict[str, Any]) -> set[str]:
    return set(_classOf(node).split())


def _text(node: dict[str, Any] | None) -> str:
    if node is None:
        return ""
    if "text" in node:
        return str(node["text"])
    return " ".join(_text(c) for c in node.get("children", []) or []).strip()


def _nodesWithClass(tree: dict[str, Any], cls: str) -> list[dict[str, Any]]:
    return [node for node in _walk(tree) if cls in _classes(node)]


def _tapeSvg(tree: dict[str, Any]) -> dict[str, Any] | None:
    found = _nodesWithClass(tree, "imu-tape")
    return found[0] if found else None


def _tapeLabels(tree: dict[str, Any]) -> list[str]:
    """The rose labels drawn on the tape. Accumulate per TD-089 -- use the SET."""
    return [_text(node) for node in _nodesWithClass(tree, "imu-tape-label")]


def _attrFloats(nodes: list[dict[str, Any]], attr: str) -> set[float]:
    out: set[float] = set()
    for node in nodes:
        raw = node.get("attrs", {}).get(attr)
        if raw is not None:
            out.add(float(raw))
    return out


def _tapeInkYs(tree: dict[str, Any]) -> set[float]:
    """Every vertical coordinate any tape child actually draws ink at.

    Reads `y1`/`y2`/`y` off the tape's OWN descendants rather than a named list
    of shapes, so a NEW element added above the ticks is caught by VC5's claim
    instead of sliding past a hand-written inventory.
    """
    svg = _tapeSvg(tree)
    assert svg is not None, "no compass tape in the rendered tree"
    ys: set[float] = set()
    for node in _walk(svg):
        if node is svg:
            continue
        for attr in ("y", "y1", "y2"):
            raw = node.get("attrs", {}).get(attr)
            if raw is not None:
                ys.add(float(raw))
        points = node.get("attrs", {}).get("points")
        if points:
            for pair in str(points).split():
                if "," in pair:
                    ys.add(float(pair.split(",")[1]))
    return ys


# ----------------------------------------------------------------- source text


def _readShipped(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def _rel(path: str) -> str:
    return os.path.relpath(path, _REPO).replace("\\", "/")


def _stripComments(text: str, *, css: bool) -> str:
    """``text`` with its comments removed, so what is left is CODE.

    `//` is stripped ONLY at the start of a stripped line. A mid-line `//` may be
    inside a string literal (a URL), and treating that as a comment would strip
    REAL CODE -- which would make this sweep quietly weaker. Erring toward
    keeping code is the safe direction for a "must not appear in code" claim.
    """
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    if css:
        return text
    return "\n".join(
        "" if line.strip().startswith("//") else line for line in text.splitlines()
    )


def _cssTapeComment() -> str:
    """The comment block immediately above the `.imu-tape` rule."""
    text = _readShipped(_CSS)
    rule = text.index(".imu-tape {")
    start = text.rindex("/*", 0, rule)
    end = text.index("*/", start)
    return text[start : end + 2]


def _jsTapeRationale() -> str:
    """The contiguous `//` block that introduces `buildTape`."""
    lines = _readShipped(_CAROUSEL_JS).splitlines()
    anchor = next(i for i, line in enumerate(lines) if "var TAPE_W" in line)
    out: list[str] = []
    i = anchor - 1
    while i >= 0 and lines[i].strip().startswith("//"):
        out.append(lines[i])
        i -= 1
    return "\n".join(reversed(out))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


# =============================================================================
# 1. THE CONTROL -- the subject of every absence claim below actually painted.
# =============================================================================


def test_theLiveFacePaintsTheCompassTape_control(tmp_path):
    """
    Given: a live IMU payload from the real bridge
    When: the shipped panel renders
    Then: the compass tape SVG is in the tree, with ticks and rose labels

    US-638's rule, and this file cannot do without it: an absence test whose
    SUBJECT failed to render is not a measurement. A harness that throws is
    indistinguishable from a panel that omits the caret, and it would make every
    other test here pass for free. This runs FIRST and asserts the opposite.
    """
    tree = _run(_liveImuState(tmp_path))

    assert _tapeSvg(tree) is not None, "the compass tape did not render at all"
    assert _nodesWithClass(tree, "imu-tick"), "the tape drew no ticks"
    assert _tapeLabels(tree), "the tape drew no rose labels"


# =============================================================================
# 2. THE REMOVAL -- rendered, and paired with the tape's survival every time.
# =============================================================================


def test_theCompassTape_drawsNoCaretTriangle(tmp_path):
    """
    Given: the live face painted, with the tape present
    When: the whole tree is searched for the caret's class
    Then: not one node carries it -- while the tape is still there

    THE STORY'S ONE BEHAVIOURAL CLAIM. The retention half is asserted in the
    SAME test on purpose: `assert not caret` alone is satisfied by a renderer
    that dropped the tape, the live face, or the card, and this story's entire
    risk is over-deletion rather than under-deletion.
    """
    tree = _run(_liveImuState(tmp_path))

    assert _tapeSvg(tree) is not None, "the tape went with the caret"
    assert _nodesWithClass(tree, _CARET_CLASS) == [], (
        "the static caret triangle is still painted on the compass tape"
    )


def test_theTapeKeepsItsTicksAndItsLabels(tmp_path):
    """
    Given: the caret removed
    When: the tape's ticks and rose labels are read off the panel
    Then: both survive, and the labels still bracket a bearing

    VC1's second half, as its own failure. Scope is EXACTLY one element: the
    ticks and labels are the tape's readable content and Atlas's objection is
    answered only while they render -- the tape is the moving half, and it stays
    the visible symptom of A-30.

    The label SET is asserted, never a count: TD-089 makes ticks accumulate
    across paints under this harness.
    """
    tree = _run(_liveImuState(tmp_path))

    ticks = _nodesWithClass(tree, "imu-tick")
    labels = _tapeLabels(tree)

    assert ticks, "the tape lost its ticks"
    assert any("imu-tick-major" in _classOf(t) for t in ticks), "no major tick drawn"
    assert labels, "the tape lost its rose labels"
    assert all(re.fullmatch(r"[NSEW]{1,3}", label) for label in set(labels)), (
        sorted(set(labels))
    )


def test_theCaretIsGoneFromTheJsThatBuildsTheTape(tmp_path):
    """
    Given: the tape still builds
    When: `buildTape`'s output is inspected for a polygon
    Then: there is none anywhere on the tape, of any class

    THE CLASS COULD BE RENAMED RATHER THAN THE ELEMENT REMOVED, and every
    class-based assertion in this file would go green on a caret that is still
    on the screen. This one is blind to the class: the caret is the tape's only
    `polygon`, so "no polygon on the tape" is the shape claim the operator would
    actually recognise.
    """
    svg = _tapeSvg(_run(_liveImuState(tmp_path)))
    assert svg is not None

    polygons = [n for n in _walk(svg) if n.get("tag") == "polygon"]

    assert polygons == [], f"a triangle is still drawn on the tape: {polygons}"


# =============================================================================
# 3. THE TOKEN -- gone from markup, CSS and JS, with no orphaned style rule.
# =============================================================================


def test_theCaretClassAppearsInNoShippedDashboardFile():
    """
    Given: the shipped markup, stylesheet and script
    When: each is swept for the caret's class token
    Then: zero matches, in all three

    VC2. Per-file so the diagnostic NAMES the file that still carries it rather
    than reporting a total -- a count tells you a sweep failed and not where.
    """
    offenders = {
        _rel(path): _readShipped(path).count(_CARET_CLASS)
        for path in _SHIPPED_FILES
        if _CARET_CLASS in _readShipped(path)
    }

    assert offenders == {}, f"`{_CARET_CLASS}` survives in {offenders}"


def test_theCaretStyleRuleIsNotLeftOrphaned():
    """
    Given: the element deleted from the JS
    When: the stylesheet is read for its selector
    Then: no `.imu-caret` rule remains -- and the tape's OWN rules all do

    VC2 names the orphaned rule specifically, because a rule for an element that
    no longer exists is dead weight that reads as live styling to the next
    person. The sibling rules are asserted in the same breath: deleting the whole
    tape block would satisfy the first assertion and destroy the tape.
    """
    css = _readShipped(_CSS)

    assert not re.search(rf"\.{re.escape(_CARET_CLASS)}\s*\{{", css), (
        "the caret's style rule is still in dashboard.css"
    )
    for survivor in (".imu-tape", ".imu-tick", ".imu-tick-major", ".imu-tape-label"):
        assert re.search(rf"{re.escape(survivor)}\s*[,{{]", css), (
            f"{survivor} was deleted along with the caret"
        )


def test_theWordCaretSurvivesOnlyInComments_neverInCode():
    """
    Given: the decision recorded in prose beside the tape
    When: comments are stripped and the remaining CODE is swept
    Then: the word `caret` appears nowhere in it

    A NARROWED PREDICATE, NARROWED DELIBERATELY AND RECORDED HERE RATHER THAN
    QUIETLY -- US-697 hit this exact collision one story ago. VC2's token sweep
    and VC3's "record the decision" pull in opposite directions: the comment that
    documents WHY the caret went may need to name it. So the sweep's SUBJECT is
    narrowed from the whole file to its CODE, which is STRICTER for the claim
    that matters, not weaker -- only code can put a triangle on the glass; a
    comment cannot. This is what stops the element re-entering under a new class
    name after `imu-caret` is retired.
    """
    for path in _SHIPPED_FILES:
        code = _stripComments(_readShipped(path), css=path == _CSS)
        assert "caret" not in code.lower(), (
            f"`caret` is still live code in {_rel(path)}, not merely recorded"
        )


# =============================================================================
# 4. THE COMMENTS -- the overruled argument is recorded, not left standing.
# =============================================================================


def test_theCssTapeComment_recordsTheDecisionInsteadOfTheFurniture():
    """
    Given: a CSS comment that ARGUED FOR the caret in the present tense
    When: the tape block's comment is read after the removal
    Then: the original argument is gone, and the CIO's dated decision is there

    VC3, and the reason it is an acceptance criterion at all: the comment says
    the caret "never moves -- a tape's readability comes entirely from one fixed
    reference". That is a REAL design argument that the CIO overruled
    deliberately. Left behind, it describes furniture that no longer exists and
    reads as a live constraint -- the stale-documentation class this project
    keeps paying for.

    Deleting the comment outright does NOT pass: the date and the decision
    marker are required, so the argument has to be REPLACED rather than dropped.
    """
    comment = _squash(_cssTapeComment())

    assert "never moves -- a tape's readability" not in comment, (
        "the overruled argument is still stated as current fact"
    )
    assert _DECISION_DATE in comment, "the CIO's decision date is not recorded"
    assert "remov" in comment, "the comment does not record that the caret went"
    assert "tape" in comment, "the comment no longer describes what IS there"


def test_theJsTapeRationale_alsoStopsDescribingTheCaretAsPresent():
    """
    Given: the same argument, stated a second time above `buildTape`
    When: that rationale block is read
    Then: it too records the decision rather than the furniture

    THE STORY NAMES THE CSS COMMENT AND NOT THIS ONE, AND THIS ONE IS THE MORE
    MISLEADING OF THE TWO. carousel.js says the caret "must never move" and
    explains the render loop in terms of it -- sitting directly above the
    function this story edits, where the next person to touch the tape will read
    it. Same element, same decision, same stale-documentation class; leaving it
    would satisfy the letter of VC3 and none of its point.
    """
    rationale = _squash(_jsTapeRationale())

    assert "static furniture" not in rationale, (
        "carousel.js still introduces the caret as present furniture"
    )
    assert _DECISION_DATE in rationale, "the decision date is not recorded in the JS"
    assert "tape" in rationale, "the rationale no longer describes the tape"


# =============================================================================
# 5. THE NEIGHBOURS -- the numeric HEADING tile is untouched.
# =============================================================================


def test_theNumericHeadingTile_rendersExactlyAsBefore(tmp_path):
    """
    Given: the same live payload
    When: the HEADING tile is read off the Home card
    Then: it still paints a bearing and a cardinal, at a live level

    VC4, and the charter's standing rule: this story must not read as a
    re-suppression of `headingDeg`. The precise bearing is not lost with the
    caret -- it is rendered here, independently, which is exactly what makes the
    tape a supplementary cue rather than the sole readout and what makes the
    removal acceptable.

    A SHAPE, NOT A NUMBER -- see the header. The bearing is wrong on this tree
    (I-us708b / US-708 / A-30) and asserting 90 would fail for another story's
    reason. The empty detail is US-697's, one story back, and is re-checked here
    because this file renders the same tile.
    """
    tiles = {}
    for node in _walk(_run(_liveImuState(tmp_path))):
        if "tile" in _classes(node):
            label = next(
                (_text(c) for c in _walk(node) if "tile-label" in _classes(c)), ""
            )
            if label:
                tiles[label] = node

    assert "HEADING" in tiles, sorted(tiles)
    tile = tiles["HEADING"]
    value = next(_text(c) for c in _walk(tile) if "tile-value" in _classes(c))
    detail = next(_text(c) for c in _walk(tile) if "tile-detail" in _classes(c))

    assert re.fullmatch(r"\d+° [NSEW]{1,3}", value), value
    assert detail == "", detail
    assert tile.get("attrs", {}).get("data-level") == "neutral"


# =============================================================================
# 6. THE LAYOUT -- the freed top 6 units, and the tape that must not collapse.
# =============================================================================


def test_theTapeGeometryBelowTheCaret_isUnchanged(tmp_path):
    """
    Given: the caret removed from a 26-unit viewBox
    When: the tape's viewBox, tick and label coordinates are read
    Then: every one of them is what it was before the removal

    VC5's first half. These values were MEASURED off the shipped renderer before
    the edit and are re-asserted after it: the caret was absolutely positioned in
    a viewBox, so removing it must reflow precisely nothing. If any of these
    moved, the deletion did more than delete.
    """
    tree = _run(_liveImuState(tmp_path))
    svg = _tapeSvg(tree)
    assert svg is not None

    ticks = _nodesWithClass(tree, "imu-tick")
    labels = _nodesWithClass(tree, "imu-tape-label")

    assert svg.get("attrs", {}).get("viewBox") == _TAPE_VIEWBOX
    assert _attrFloats(ticks, "y1") == _TICK_Y1
    assert _attrFloats(ticks, "y2") == _TICK_Y2
    assert _attrFloats(labels, "y") == _LABEL_Y


def test_theTopSixUnitsTheCaretOccupied_areNowEmpty(tmp_path):
    """
    Given: a caret that was drawn at `50,0 46,6 54,6` -- the top 6 units
    When: every vertical coordinate the tape draws ink at is collected
    Then: none is above the first tick, so nothing reflowed into the gap

    VC5's second half, and the one assertion here that is RED before the edit --
    the caret's own `points` put ink at y=0. Collected by walking the tape's real
    descendants rather than a list of known shapes, so this also catches a NEW
    element quietly taking the vacated space later.
    """
    ys = _tapeInkYs(_run(_liveImuState(tmp_path)))

    assert ys, "the tape drew no geometry at all"
    assert min(ys) > _FREED_TOP_UNITS, (
        f"something is still drawn in the tape's freed top {_FREED_TOP_UNITS} "
        f"units: lowest y is {min(ys)}"
    )


def test_theTapeDoesNotCollapseWithoutTheCaret(tmp_path):
    """
    Given: the caret gone
    When: the tape's horizontal extent is measured across its ticks
    Then: it still spans the full width, edge label to edge label

    conditionalOutcomes[0] says that if the caret turns out to be LOAD-BEARING
    for the SVG layout -- the tape collapsing without it -- that is to be
    REPORTED, because it changes the fix from a deletion to a re-layout. This is
    the test that would report it. It passes: the tape's geometry comes from an
    explicit viewBox and per-tick coordinates, not from the content bounding box,
    so no child can be structural.
    """
    tree = _run(_liveImuState(tmp_path))
    xs = _attrFloats(_nodesWithClass(tree, "imu-tick"), "x1")

    assert xs, "the tape drew no ticks to measure"
    assert min(xs) < 10 and max(xs) > 90, sorted(xs)
