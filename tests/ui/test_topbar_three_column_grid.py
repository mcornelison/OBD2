################################################################################
# File Name: test_topbar_three_column_grid.py
# Purpose/Description: US-555 (F-132) tests for the top bar's three-column grid.
#   The clock must sit at the GEOMETRIC CENTRE of the bar, not at the end of a
#   left cluster, and it must stay there whatever the version string reads. The
#   US-542 comment in the sheet argued against centring; it is right that two
#   `auto` margins in one flex row split the free space BETWEEN them (so the
#   clock drifts with the version-string length) and wrong that this rules out
#   centring -- a `1fr auto 1fr` grid centres on the BAR, not on the leftover.
#
#   WHAT IS ACTUALLY GUARDED HERE, because "it looks centred" is not testable
#   from a stylesheet and the repo's render harness resolves the CASCADE but NOT
#   LAYOUT (see render_harness.py fidelity limit 1):
#     1. the STRUCTURE that makes centring geometric -- equal side tracks, the
#        clock alone in the middle track, exactly three grid children;
#     2. the ABSENCE of the mechanism the old comment rightly feared -- no auto
#        margin anywhere in the bar, on any element, forever;
#     3. the WIDTH BOUND (AC-4). `1fr` is `minmax(auto, 1fr)`, so a side track
#        that outgrows its free-space share pushes the centre track off centre.
#        Centring is therefore structural UP TO a measurable bound, and the
#        bound is asserted here rather than asserted away -- including with the
#        Atlas-gated P-6 WiFi glyph added, which is AC-4's actual question.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Ralph (Rex)  | Initial -- US-555 top-bar three-column grid.
# ================================================================================
################################################################################

"""US-555 tests for the dashboard top bar's three-column grid."""

from __future__ import annotations

import os
import re

import pytest

from tests.ui.css_type_scale import readCss, ruleBlock

_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML_PATH = os.path.join(_DIST, "dashboard.html")
_CSS_PATH = os.path.join(_DIST, "dashboard.css")

# The design box. Not a guess: #stage is authored at exactly this size and the
# whole box is uniformly scaled by transform (US-482 letterbox), so the CSS
# layout canvas is 480x320 at EVERY panel resolution -- the viewport only moves
# `--scale`. Pinned below by test_theWidthCheckCanvasIsTheAuthoredStageBox.
STAGE_WIDTH_PX = 480

# Monospace advance as a fraction of the font size. 0.6em is the WIDEST advance
# among the faces `--font-mono` actually names (Menlo / DejaVu Sans Mono are
# ~0.602em; Consolas is 0.550em; the ui-monospace resolutions -- SF Mono,
# Cascadia Mono -- are 0.60em), so every width this model reports is an UPPER
# BOUND and a pass here passes on the narrower faces too.
MONO_ADVANCE_EM = 0.6

# A non-ASCII pictograph is NOT served from the mono face -- it falls through to
# a symbol font, where the advance is typically full-em. Modelled at 1.0em so
# the glyph cluster is over-estimated rather than under-estimated.
SYMBOL_ADVANCE_EM = 1.0

# The longest string the clock can hold: `fmtClock` renders 12-hour with a
# meridiem, so "12:45 PM" (8 chars) is the maximum, never "9:05 AM".
LONGEST_CLOCK_TEXT = "12:45 PM"

# The version chip as it reads on a real deploy. "V?.?.?" (the honest unreadable
# sentinel) is SHORTER, so the deployed string is the binding case.
LONGEST_VERSION_TEXT = "V0.29.29"


def _readHtml() -> str:
    with open(_HTML_PATH, encoding="utf-8") as fh:
        return fh.read()


def _stripComments(markup: str) -> str:
    """Markup with HTML comments removed.

    The comments here are long design prose that legitimately DISCUSS ids and
    class names; only what actually paints may satisfy a structural assertion.
    """
    return re.sub(r"<!--.*?-->", "", markup, flags=re.DOTALL)


def _topbarMarkup(html: str) -> str:
    """The `<header id="topbar">...</header>` element, comments stripped."""
    match = re.search(r'<header id="topbar">(.*?)</header>', html, re.DOTALL)
    assert match is not None, 'dashboard.html must keep the <header id="topbar">'
    return _stripComments(match.group(1))


def _topbarChildTags(html: str) -> list[str]:
    """The element children of #topbar, outermost only, in document order.

    Returns a list of `<tag id=... class=...>` opening-tag strings. Nesting is
    tracked so the glyphs INSIDE a cluster are not mistaken for grid children --
    which is the whole point: a three-column grid with five children puts the
    clock in the wrong track.
    """
    inner = _topbarMarkup(html)
    children: list[str] = []
    depth = 0
    for token in re.finditer(r"<(/?)([a-zA-Z][-\w]*)([^>]*?)(/?)>", inner):
        closing, tag, attrs, selfClosing = token.groups()
        if closing:
            depth -= 1
            continue
        if depth == 0:
            children.append(f"<{tag}{attrs}>")
        if not selfClosing and tag.lower() not in ("br", "hr", "img", "input", "meta"):
            depth += 1
    return children


def _cssVarPx(css: str, name: str) -> float:
    """The px magnitude declared for a custom property, read not assumed."""
    match = re.search(rf"{re.escape(name)}:\s*([0-9.]+)px", css)
    assert match is not None, f"{name} is not declared as a px value"
    return float(match.group(1))


def _declaredVarName(css: str, selector: str, prop: str) -> str:
    """The custom property a declaration resolves through, without its `--`.

    US-556 needs this so the bar's width model can charge the kebab whatever the
    sheet actually gives it, rather than a magnitude restated here. Asserting the
    declaration IS a `var()` is the point: a bare literal would silently produce
    a plausible number and re-create the drift the model exists to catch.

    Args:
        css: the full stylesheet.
        selector: the exact selector.
        prop: the property to read.

    Returns:
        The token name without its leading `--`.
    """
    block = ruleBlock(css, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*var\(--([a-zA-Z0-9-]+)\)", block)
    assert match is not None, f"{selector} does not bind `{prop}` to a token"
    return match.group(1)


def _shorthandPx(block: str, prop: str, index: int) -> float:
    """The Nth px magnitude of a shorthand declaration inside a rule block."""
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*([^;]+);", block)
    assert match is not None, f"no `{prop}` declaration in the rule block"
    parts = re.findall(r"([0-9.]+)px", match.group(1))
    assert len(parts) > index, f"`{prop}` has no component {index}"
    return float(parts[index])


def _textWidthPx(text: str, fontSizePx: float, letterSpacingEm: float) -> float:
    """Upper-bound rendered width of a run of text in the bar.

    ASCII is charged the mono advance; anything else is charged a full em (see
    the module constants for why both figures are upper bounds).
    """
    total = 0.0
    for char in text:
        advance = MONO_ADVANCE_EM if char.isascii() else SYMBOL_ADVANCE_EM
        total += fontSizePx * (advance + letterSpacingEm)
    return total


class _BarModel:
    """The bar's width budget, derived from the SHIPPED values only.

    Every magnitude is read out of the real stylesheet -- token values, the
    bar's own padding and gap, the kebab's declared width. Nothing here is a
    literal copied from the design note, so a token change moves the check.
    """

    def __init__(self, css: str) -> None:
        bar = ruleBlock(css, "#topbar")
        self.padding = _shorthandPx(bar, "padding", 0)
        self.gap = _shorthandPx(bar, "gap", 0)
        self.glyphSize = _cssVarPx(css, "--fs-secondary")
        self.clockSize = _cssVarPx(css, "--fs-label")
        self.chipSize = _cssVarPx(css, "--fs-meta")
        # MOVED PIN (US-556). This read `--tap-min`, because the kebab's PAINTED
        # box was `min-height/min-width: var(--tap-min)`. US-556 split the visual
        # box from the hit box: the button now paints at `--bar-h` and reaches
        # the tap minimum through an ABSOLUTELY POSITIONED `::after`, which takes
        # no space in the bar's grid. Charging `--tap-min` here would keep the
        # model green while measuring a box that no longer exists -- a stale
        # measurement is exactly what F-132 is closing, so the width is read from
        # the declaration instead of restated.
        self.kebabWidth = _cssVarPx(css, "--" + _declaredVarName(css, "#menu-btn", "width"))
        clusterGap = ruleBlock(css, "#topbar .topbar-right")
        self.clusterGap = _shorthandPx(clusterGap, "gap", 0)
        leftCluster = ruleBlock(css, "#topbar .topbar-left")
        self.leftGap = _shorthandPx(leftCluster, "gap", 0)
        self.glyphSpacing = 0.04  # #topbar .glyph letter-spacing, em
        self.chipSpacing = 0.06  # #version-chip letter-spacing, em
        self.clockSpacing = 0.04  # #topbar-clock letter-spacing, em

    @property
    def usable(self) -> float:
        """Bar width inside its own horizontal padding."""
        return STAGE_WIDTH_PX - 2 * self.padding

    def leftClusterWidth(self, glyphs: list[str]) -> float:
        runs = sum(
            _textWidthPx(glyph, self.glyphSize, self.glyphSpacing) for glyph in glyphs
        )
        return runs + self.leftGap * max(0, len(glyphs) - 1)

    def centreWidth(self, text: str = LONGEST_CLOCK_TEXT) -> float:
        return _textWidthPx(text, self.clockSize, self.clockSpacing)

    def rightClusterWidth(self, version: str = LONGEST_VERSION_TEXT) -> float:
        chip = _textWidthPx(version, self.chipSize, self.chipSpacing)
        return chip + self.clusterGap + self.kebabWidth

    def sideTrackShare(self, text: str = LONGEST_CLOCK_TEXT) -> float:
        """Free space each `1fr` side track is guaranteed.

        The two side tracks split whatever is left after the bar's padding, the
        two column gaps and the auto-sized centre track. A cluster wider than
        its share grows its track past `1fr` -- `1fr` is `minmax(auto, 1fr)` --
        and THAT is the one way the grid can still let the clock drift.
        """
        free = self.usable - 2 * self.gap - self.centreWidth(text)
        return free / 2


# ---------------------------------------------------------------------------
# AC-1 -- the grid itself.
# ---------------------------------------------------------------------------


def test_topbar_isAThreeColumnGridWithEqualSideTracks():
    """`1fr auto 1fr`: the two side tracks are the SAME track definition, which
    is what makes the middle one land on the bar's midpoint. Any other template
    (`auto 1fr auto`, unequal fractions) centres on something else."""
    block = ruleBlock(readCss(_CSS_PATH), "#topbar")
    assert "display: grid" in block
    assert "grid-template-columns: 1fr auto 1fr" in block


def test_topbar_isNoLongerAFlexRow():
    """MOVED PIN. The bar WAS `display: flex`, and in a flex row the only tool
    for centring is an auto margin -- the very thing the US-542 comment ruled
    out. Leaving the flex declaration behind would not merely be dead: it is
    declared before the grid in the same block, so a later re-order silently
    restores the layout this story replaced."""
    block = ruleBlock(readCss(_CSS_PATH), "#topbar")
    assert "display: flex" not in block


def test_versionChip_hasNoAutoLeftMargin():
    """AC-1, second half. The chip pushed itself right with `margin-left: auto`;
    the right TRACK does that now."""
    block = ruleBlock(readCss(_CSS_PATH), "#version-chip")
    assert "margin-left: auto" not in block


# ---------------------------------------------------------------------------
# AC-2 -- centring is STRUCTURAL. Two halves: the drift mechanism is gone, and
# the clock is genuinely the middle track.
# ---------------------------------------------------------------------------


def test_noAutoMarginAnywhereInTheBar_notJustOnTheVersionChip():
    """The defect class is `auto` margins in this bar, not one declaration on
    one element. Dropping the chip's margin while some future rule adds one to
    the kebab re-creates the exact drift, and a test naming only #version-chip
    would stay green through it."""
    css = readCss(_CSS_PATH)
    offenders = []
    for match in re.finditer(r"(?m)^([^\n{}]*\{[^{}]*\})", css):
        rule = match.group(1)
        selector = rule.split("{", 1)[0].strip()
        if not any(
            key in selector
            for key in ("#topbar", "#version-chip", "#menu-btn", ".topbar-")
        ):
            continue
        body = rule.split("{", 1)[1]
        if re.search(r"margin(-left|-right|-inline[-\w]*)?:[^;]*\bauto\b", body):
            offenders.append(selector)
    assert offenders == [], f"auto margin re-introduced in the top bar: {offenders}"


def test_clock_isCentredInItsOwnTrack():
    """`justify-self: center` pins the clock to the middle of the auto track.
    Without it the clock sits at the track's start edge, which is centred only
    while the track is exactly as wide as the text."""
    block = ruleBlock(readCss(_CSS_PATH), "#topbar-clock")
    assert "justify-self: center" in block


def test_topbar_hasExactlyThreeGridChildren_clockInTheMiddle():
    """THE structural assertion. A three-column template with five children
    wraps into implicit rows and the clock lands in column 2 of row 1 by
    accident, not by design -- it would still LOOK right today and break the
    moment a glyph is added. Exactly three children, clock second."""
    children = _topbarChildTags(_readHtml())
    assert len(children) == 3, f"#topbar must have 3 grid children, got: {children}"
    assert 'class="topbar-left"' in children[0]
    assert 'id="topbar-clock"' in children[1]
    assert 'class="topbar-right"' in children[2]


def test_glyphsSitLeft_versionAndKebabSitRight():
    """The clusters hold what the design says they hold. Reads the markup, so a
    glyph left behind as a bare grid child fails here as well as above."""
    inner = _topbarMarkup(_readHtml())
    left = re.search(r'<div class="topbar-left">(.*?)</div>', inner, re.DOTALL)
    right = re.search(r'<div class="topbar-right">(.*?)</div>', inner, re.DOTALL)
    assert left is not None and right is not None
    for glyph in ("glyph-bt", "glyph-sync", "glyph-power"):
        assert f'id="{glyph}"' in left.group(1), f"{glyph} is not in the left cluster"
        assert f'id="{glyph}"' not in right.group(1)
    assert 'id="version-chip"' in right.group(1)
    assert 'id="menu-btn"' in right.group(1)


def test_clusters_areFlexRows_soTheirContentsStillSitInline():
    """The wrappers must not change how the glyphs read. Grid children default
    to `display: block`, which would stack BT / sync / power vertically inside a
    bar one `--bar-h` tall -- a silent, total regression that no id-based test
    would see.

    MOVED PIN (US-557): this used to say "a 28px bar". The assertions are
    unchanged and still pass; only the stated reason had gone stale, because
    US-557 moved the bar height off a literal and up to 34px. A guard whose
    stated reason is false is the next reader's wrong turn -- and leaving a
    dependent measurement behind after a value moved is the exact defect US-557
    exists to remove, so it would have been a poor place to make an exception."""
    css = readCss(_CSS_PATH)
    left = ruleBlock(css, "#topbar .topbar-left")
    right = ruleBlock(css, "#topbar .topbar-right")
    assert "display: flex" in left
    assert "display: flex" in right
    assert "justify-content: flex-end" in right, (
        "the right cluster must pack against the bar's right edge; without it "
        "the version chip floats at the start of a track that is wider than it"
    )


# ---------------------------------------------------------------------------
# AC-3 -- the US-542 comment is UPDATED, not deleted.
# ---------------------------------------------------------------------------


def test_us542Comment_isAmendedNotDeleted():
    """The old comment's reasoning about auto margins is CORRECT and is the
    record of why the obvious fix is wrong. Deleting it invites the next reader
    to re-derive it the hard way. It must survive, name this story, and keep the
    auto-margin argument that is still true."""
    css = readCss(_CSS_PATH)
    clockComment = css[css.index("/* US-542: the wall clock") : css.index("#topbar-clock {")]
    assert "US-555" in clockComment, "the amended comment must name the story that moved it"
    assert "auto" in clockComment, "the auto-margin reasoning must survive the amendment"
    assert "grid" in clockComment, "the comment must say what replaced the flex row"


# ---------------------------------------------------------------------------
# AC-4 -- the width check, and the bound it actually proves.
# ---------------------------------------------------------------------------


def test_theWidthCheckCanvasIsTheAuthoredStageBox():
    """Grounds STAGE_WIDTH_PX rather than trusting it. The panel resolution is
    NOT the layout canvas: #stage is a fixed design box scaled by transform, so
    the bar is 480 CSS px wide whether the Pi scans out 480x320 or 1280x720."""
    stage = ruleBlock(readCss(_CSS_PATH), "#stage")
    assert f"width: {STAGE_WIDTH_PX}px" in stage
    assert "transform: scale(var(--scale, 1))" in stage


def test_everyClusterFitsItsGuaranteedTrackShare_today():
    """AC-2's "regardless of version-string length" holds only while each side
    cluster fits the free-space share its `1fr` is guaranteed. Asserted, not
    assumed."""
    model = _BarModel(readCss(_CSS_PATH))
    share = model.sideTrackShare()
    left = model.leftClusterWidth(["BT", "⇅", "⚡"])
    right = model.rightClusterWidth()
    assert left <= share, f"left cluster {left:.1f}px exceeds its {share:.1f}px share"
    assert right <= share, f"right cluster {right:.1f}px exceeds its {share:.1f}px share"


def test_theBarIsNotOverBudgetAcrossItsFullWidth():
    """AC-4's headline: the three clusters plus the gaps fit the usable bar."""
    model = _BarModel(readCss(_CSS_PATH))
    used = (
        model.leftClusterWidth(["BT", "⇅", "⚡"])
        + model.centreWidth()
        + model.rightClusterWidth()
        + 2 * model.gap
    )
    assert used <= model.usable, f"{used:.1f}px used of {model.usable:.1f}px"


def test_aFourthGlyphStillFits_soP6DropsInWithNoRelayout():
    """AC-4's actual question. The Atlas-gated P-6 WiFi glyph joins the LEFT
    cluster; if that pushes the left track past its share the clock moves and
    P-6 becomes a re-layout instead of a drop-in. This is the guard that makes
    "zero re-layout" a measured claim rather than a hope."""
    model = _BarModel(readCss(_CSS_PATH))
    withWifi = model.leftClusterWidth(["BT", "⇅", "⚡", "▾"])
    share = model.sideTrackShare()
    assert withWifi <= share, (
        f"a 4th glyph takes the left cluster to {withWifi:.1f}px, past its "
        f"{share:.1f}px share -- P-6 would move the clock"
    )


@pytest.mark.parametrize(
    "version",
    ["V0.29.29.29.29.29", "V0.29.29-rc.1+build.20260821"],
)
def test_theWidthModelCanFail_negativeControl(version: str):
    """A budget check that has never been seen to go red is not known to be a
    budget check. An absurdly long version string MUST break the bound -- which
    also states the real limit of AC-2: the clock is centred up to a version
    length, not unconditionally."""
    model = _BarModel(readCss(_CSS_PATH))
    assert model.rightClusterWidth(version) > model.sideTrackShare()
