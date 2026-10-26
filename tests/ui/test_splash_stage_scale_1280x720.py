################################################################################
# File Name: test_splash_stage_scale_1280x720.py
# Purpose/Description: US-869-h render pin -- the boot and shutdown splash pages
#   letterbox their 480x320 design to the REAL panel mode, 1280x720 (Atlas
#   MEASURED, wlr-randr, scale 1). Before this story both pages drew the design
#   1:1 in the 1280x720 viewport: the logo ~2.25x too small and the checklist /
#   progress bar left of centre (CIO on the glass, 2026-10-26). No test saw it
#   because render_harness.splashSurface defaults to viewport (480, 320), where
#   unscaled px are correct.
#
#   The harness resolves CSS but does no layout, so this file MODELS the box,
#   from declarations it reads and REFUSES to guess at:
#     - the real stage-scale.js + the page's inline scripts run against the
#       mini-DOM at the viewport (stage_scale_probe.js) and write --scale;
#     - an absolutely positioned element sits at its top/left in its containing
#       block (the nearest positioned or transformed ancestor);
#     - #stage is an in-flow child of a flex frame that centres it, scaled by
#       `transform: scale(var(--scale, 1))` about its centre.
#   Anything else (an unknown unit, a frame that does not centre, a different
#   transform) raises, so a stylesheet change the model cannot measure goes red.
#
#   The same assertions FAIL on the pre-fix pages (f3122210): the stage-less
#   negative below rebuilds that shape from the shipped markup and proves it.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-26    | Ralph (Rex)  | Initial -- US-869-h splash letterbox render pin.
# ================================================================================
################################################################################

"""US-869-h: the splash pages letterbox-scale their 480x320 design to 1280x720."""

from __future__ import annotations

import copy
import os
import re
import shutil
from typing import Any

import pytest

from tests.ui import render_harness as rh

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH -- the probe needs node"
)

BOOT = os.path.join(rh.SPLASH_DIR, "index.html")
SHUTDOWN = os.path.join(rh.SPLASH_DIR, "shutdown.html")

DESIGN = (480, 320)
PANEL = (1280, 720)  # the car's panel mode (Atlas, wlr-randr MEASURED)
TOLERANCE_PX = 1.0  # one CSS px of scale rounding (the acceptance)

# Which element each page is judged on, beside the logo box (#mark).
PAGE_TARGETS = [(BOOT, "checklist"), (SHUTDOWN, "progress")]

_POSITIONED = ("relative", "absolute", "fixed")


# ---------------------------------------------------------------------------
# The box model
# ---------------------------------------------------------------------------


class Layout:
    """Frame-px boxes for the splash's absolute/flex layout at one viewport."""

    def __init__(self, tree: dict[str, Any], viewport: tuple[int, int]) -> None:
        self.viewport = viewport
        self.surface = rh.splashSurface(tree, viewport=viewport)

    def _decl(self, path: list, prop: str) -> str | None:
        found = self.surface.winningDeclaration(path, prop)
        return None if found is None else found[0].strip()

    def _length(self, value: str, reference: float) -> float:
        if value == "0":
            return 0.0
        match = re.fullmatch(r"(-?\d+(?:\.\d+)?)(px|%|vw|vh)", value)
        if match is None:
            raise ValueError(f"the model cannot measure {value!r}")
        number, unit = float(match.group(1)), match.group(2)
        if unit == "%":
            return number * reference / 100
        if unit == "vw":
            return number * self.viewport[0] / 100
        if unit == "vh":
            return number * self.viewport[1] / 100
        return number

    def _isBody(self, path: list) -> bool:
        return path[-1]["tag"] == "body"

    def containingBlock(self, path: list) -> list:
        """The nearest positioned or transformed ancestor (else the body)."""
        for depth in range(len(path) - 1, 0, -1):
            ancestor = path[:depth]
            if self._isBody(ancestor):
                return ancestor
            position = self._decl(ancestor, "position")
            transform = self._decl(ancestor, "transform")
            if position in _POSITIONED or (transform not in (None, "none")):
                return ancestor
        raise ValueError("no containing block")

    def size(self, path: list) -> tuple[float, float]:
        if self._isBody(path):
            return float(self.viewport[0]), float(self.viewport[1])
        cbW, cbH = self.size(self.containingBlock(path))
        width, height = self._decl(path, "width"), self._decl(path, "height")
        if width is None or height is None:
            raise ValueError(f"#{path[-1]['attrs'].get('id')} has no declared box")
        return self._length(width, cbW), self._length(height, cbH)

    def scaleOf(self, path: list) -> float:
        """The element's own uniform scale: 1 unless it is the letterboxed stage."""
        transform = self._decl(path, "transform")
        if transform in (None, "none"):
            return 1.0
        if transform != "scale(var(--scale, 1))":
            raise ValueError(f"the model cannot apply transform {transform!r}")
        if self._decl(path, "transform-origin") != "center center":
            raise ValueError("the letterbox scales about its centre")
        inline = (path[-1].get("style") or {}).get("--scale")
        return float(inline) if inline is not None else 1.0

    def toFrame(self, path: list, x: float, y: float) -> tuple[float, float]:
        """A point in the element's own (untransformed) box -> frame px."""
        if self._isBody(path):
            return x, y
        width, height = self.size(path)
        scale = self.scaleOf(path)
        x, y = width / 2 + (x - width / 2) * scale, height / 2 + (y - height / 2) * scale

        position = self._decl(path, "position")
        if position == "absolute":
            cb = self.containingBlock(path)
            left, top = self.offset(path, cb, width, height)
            return self.toFrame(cb, left + x, top + y)

        parent = path[:-1]
        if self._isBody(parent):
            # The frame itself: a body child at the origin (html, body margin 0).
            assert self._decl(path, "margin") in (None, "0"), "the frame is offset"
            return x, y
        if (
            self._decl(parent, "display") == "flex"
            and self._decl(parent, "align-items") == "center"
            and self._decl(parent, "justify-content") == "center"
        ):
            parentW, parentH = self.size(parent)
            return self.toFrame(parent, (parentW - width) / 2 + x, (parentH - height) / 2 + y)
        raise ValueError(f"the model cannot place in-flow #{path[-1]['attrs'].get('id')}")

    def offset(self, path: list, cb: list, width: float, height: float) -> tuple[float, float]:
        cbW, cbH = self.size(cb)
        left, top = self._decl(path, "left"), self._decl(path, "top")
        if left is None or top is None:
            raise ValueError(f"#{path[-1]['attrs'].get('id')} is not placed by top/left")
        return self._length(left, cbW), self._length(top, cbH)

    def box(self, elementId: str) -> tuple[float, float, float, float]:
        """(left, top, right, bottom) of the element in frame px."""
        path = self.surface.pathById(elementId)
        assert path is not None, f"#{elementId} is not on the page"
        cb = self.containingBlock(path)
        cbW, cbH = self.size(cb)
        width = self._length(self._decl(path, "width") or "", cbW)
        heightDecl = self._decl(path, "height")
        height = self._length(heightDecl, cbH) if heightDecl is not None else 0.0
        left, top = self.offset(path, cb, width, height)
        x0, y0 = self.toFrame(cb, left, top)
        x1, y1 = self.toFrame(cb, left + width, top + height)
        return x0, y0, x1, y1


def _layout(markup: str, viewport: tuple[int, int], tree: dict | None = None) -> Layout:
    run = rh.runStageScale(markup, viewport, tree=tree)
    assert run["errors"] == [], run["errors"]
    return Layout(run["tree"], viewport)


def _assertAtTheDesignFraction(markup: str, elementId: str, tree: dict | None = None) -> None:
    design, panel = _layout(markup, DESIGN, tree), _layout(markup, PANEL, tree)
    dLeft, dTop, dRight, dBottom = design.box(elementId)
    pLeft, pTop, pRight, pBottom = panel.box(elementId)

    expectedTop = dTop / DESIGN[1] * PANEL[1]
    assert abs(pTop - expectedTop) <= TOLERANCE_PX, (
        f"#{elementId} top {pTop:.1f}px at 1280x720, expected {expectedTop:.1f}px "
        f"({dTop / DESIGN[1]:.3f} of the frame height, as at 480x320)"
    )
    if dBottom > dTop:  # the box declares a height: its extent scales too
        expectedHeight = (dBottom - dTop) / DESIGN[1] * PANEL[1]
        assert abs((pBottom - pTop) - expectedHeight) <= TOLERANCE_PX, (
            f"#{elementId} is {pBottom - pTop:.1f}px tall at 1280x720, "
            f"expected {expectedHeight:.1f}px"
        )
    leftGap, rightGap = pLeft, PANEL[0] - pRight
    assert abs(leftGap - rightGap) <= TOLERANCE_PX, (
        f"#{elementId} is off-centre at 1280x720: left gap {leftGap:.1f}px, "
        f"right gap {rightGap:.1f}px"
    )


def _stageless(markup: str) -> dict:
    """The shipped page with #stage unwrapped -- the pre-fix (f3122210) shape."""
    tree = copy.deepcopy(rh.parseMarkup(markup))

    def unwrap(node: dict) -> None:
        children = []
        for child in node.get("children", []):
            if child.get("attrs", {}).get("id") == "stage":
                children.extend(child["children"])
            else:
                unwrap(child)
                children.append(child)
        node["children"] = children

    unwrap(tree)
    return tree


# ---------------------------------------------------------------------------
# The pin: 1280x720 looks like 480x320, only bigger
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("markup", [BOOT, SHUTDOWN], ids=["boot", "shutdown"])
def test_theLogoBox_holdsItsDesignFraction_andIsCentred_at1280x720(markup):
    """
    Given: the page at the car's 1280x720 and at the 480x320 design box
    Then: #mark's top and height are the same fraction of the frame height
          (60 % tall: 432 px of 720, Iris R2) and it is horizontally centred
    """
    _assertAtTheDesignFraction(markup, "mark")


@pytest.mark.parametrize("markup, elementId", PAGE_TARGETS, ids=["boot", "shutdown"])
def test_theChecklistAndTheProgressBar_holdTheirFraction_andAreCentred(markup, elementId):
    """
    Given: the boot #checklist and the shutdown #progress (the same slot,
           x 52-428, y 194 of the design box)
    Then: at 1280x720 they sit at the design fraction of the frame height and
          centred -- the CIO's photo had both left of centre and small
    """
    _assertAtTheDesignFraction(markup, elementId)


def test_theCarPanel_isTheExampleScale_2_25_withHundredPxBars():
    """The story's worked example, end to end: scale 2.25, the stage is
    1080x720 with 100 px bars, and #mark is 432 px tall (60 % of 720)."""
    layout = _layout(BOOT, PANEL)
    stage = layout.surface.pathById("stage")
    assert layout.scaleOf(stage) == 2.25
    left, top, right, bottom = layout.box("mark")
    assert (left, right) == (100.0, 1180.0)
    assert (top, bottom - top) == (54.0, 432.0)


@pytest.mark.parametrize("markup, elementId", PAGE_TARGETS, ids=["boot", "shutdown"])
def test_thePreFixShape_failsThePin(markup, elementId):
    """
    Given: the shipped page with #stage unwrapped (the f3122210 shape: every
           box absolute against the full-viewport #splash-stage)
    Then: the same assertions go red -- the pin can see the bug it pins
    """
    tree = _stageless(markup)
    with pytest.raises(AssertionError):
        _assertAtTheDesignFraction(markup, "mark", tree)
    with pytest.raises(AssertionError):
        _assertAtTheDesignFraction(markup, elementId, tree)


# ---------------------------------------------------------------------------
# What stays full-frame
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("viewport", [DESIGN, PANEL])
def test_theWarning_staysFullFrame_outsideTheStage(viewport):
    """
    Given: #warning frames the whole viewport on purpose (US-885-c, Plymouth's
           full-frame rule)
    Then: it is not inside #stage and its box is the viewport, unscaled
    """
    layout = _layout(BOOT, viewport)
    path = layout.surface.pathById("warning")
    assert all(node.get("attrs", {}).get("id") != "stage" for node in path)
    assert layout.box("warning") == (0.0, 0.0, float(viewport[0]), float(viewport[1]))


@pytest.mark.parametrize("markup", [BOOT, SHUTDOWN], ids=["boot", "shutdown"])
def test_everyDesignElement_isInsideTheOneStage(markup):
    """The logo, wordmark, chip and checklist / progress all scale as ONE unit;
    #amber-ring frames the viewport and stays outside."""
    surface = rh.splashSurface(rh.parseMarkup(markup))
    inside = ["mark", "wordmark", "version-chip"]
    inside += ["checklist", "degraded-msg"] if markup == BOOT else ["progress"]
    for elementId in inside:
        ids = [n.get("attrs", {}).get("id") for n in surface.pathById(elementId)]
        assert ids.count("stage") == 1, f"#{elementId} is not inside #stage"
    if markup == BOOT:
        ring = [n.get("attrs", {}).get("id") for n in surface.pathById("amber-ring")]
        assert "stage" not in ring


# ---------------------------------------------------------------------------
# Load + resize only; degenerate viewports; the file absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("markup", [BOOT, SHUTDOWN], ids=["boot", "shutdown"])
def test_theScale_isSetOnLoadAndResize_withNoTimer(markup):
    """C-Atlas-8: the scale is applied on load and re-applied on resize; the
    letterbox arms no timer."""
    run = rh.runStageScale(markup, DESIGN, resizeTo=PANEL)
    assert run["errors"] == []
    assert run["timers"] == 0
    assert run["resizeListeners"] == 1
    stage = rh.splashSurface(run["tree"]).pathById("stage")
    assert stage[-1]["style"]["--scale"] == "2.25"


@pytest.mark.parametrize("markup", [BOOT, SHUTDOWN], ids=["boot", "shutdown"])
@pytest.mark.parametrize(
    "viewport", [(0, 0), ("NaN", "NaN"), ("Infinity", 720), (1280, "Infinity")]
)
def test_aDegenerateViewport_scalesToOne(markup, viewport):
    """A transient 0x0 layout pass or a non-finite size yields scale 1, never
    0 / NaN / Infinity."""
    run = rh.runStageScale(markup, viewport)
    assert run["errors"] == []
    stage = rh.splashSurface(run["tree"]).pathById("stage")
    assert stage[-1]["style"]["--scale"] == "1"


@pytest.mark.parametrize("markup", [BOOT, SHUTDOWN], ids=["boot", "shutdown"])
def test_withTheScalerAbsent_thePageStillRendersUnscaled(markup):
    """
    Given: stage-scale.js did not load (a 404 is not a script error)
    Then: the inline guard throws nothing, --scale is never written, and the
          CSS default scale(var(--scale, 1)) draws the design 1:1
    """
    run = rh.runStageScale(markup, PANEL, withSharedScaler=False)
    assert run["errors"] == []
    layout = Layout(run["tree"], PANEL)
    stage = layout.surface.pathById("stage")
    assert "--scale" not in (stage[-1].get("style") or {})
    assert layout.scaleOf(stage) == 1.0
    assert layout.surface.rendered(layout.surface.pathById("mark"))


@pytest.mark.parametrize("markup", [BOOT, SHUTDOWN], ids=["boot", "shutdown"])
def test_thePageLoadsTheOneScaler_beforeItsBinding(markup):
    """Both pages load stage-scale.js (the one source) and then bind it."""
    with open(markup, encoding="utf-8") as fh:
        html = fh.read()
    assert html.count('<script src="stage-scale.js"></script>') == 1
    assert html.index('<script src="stage-scale.js">') < html.index("bindStageScale(")
