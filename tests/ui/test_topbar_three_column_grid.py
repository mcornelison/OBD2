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
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard"
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
    # US-696 removed `glyph-power`; `glyph-wifi` (ARCH-007) takes its place here
    # so the list still names every glyph the bar actually carries.
    for glyph in ("glyph-bt", "glyph-sync", "glyph-wifi"):
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


def _shippedLeftGlyphs() -> list[str]:
    """The glyph TEXTS the left cluster actually paints, READ from the markup.

    Read rather than restated, and that distinction is the whole of TD-us696
    below. Every budget assertion in this section used to be made against a
    hand-written `["BT", "⇅", "⚡"]`, which described the bar only until the
    next glyph landed -- and when one did, nothing forced the list to notice.
    A list derived from the markup cannot drift away from the bar it measures.
    """
    inner = _topbarMarkup(_readHtml())
    left = re.search(r'<div class="topbar-left">(.*?)</div>', inner, re.DOTALL)
    assert left is not None, "the left cluster must exist to be measured"
    glyphs = re.findall(r'<span class="glyph"[^>]*>([^<]*)</span>', left.group(1))
    assert glyphs, "no glyphs read from the left cluster -- markup or regex moved"
    return glyphs


def test_theShippedGlyphListIsReadFromTheMarkup_notRestated():
    """The non-degeneracy pin for `_shippedLeftGlyphs`, and it earns its place.

    The EMPTY case is already caught inside the helper (`assert glyphs`), so
    this pin is not needed for that. What it catches is the case that survives
    everything else: a regex that returns something NON-EMPTY BUT WRONG.

    Measured, not assumed. Mutating the capture to read the `data-state`
    attribute instead of the element text yields `["neutral"] * 3` -- three
    plausible-looking strings, so the helper's own assert passes. Both
    characterisation tests below SURVIVE it, because they assert `> share` and a
    too-wide fixture satisfies that trivially. Only this test dies, on `"BT" in
    glyphs`. A `>` assertion cannot notice being fed something too big; that is
    the honest weakness of the characterisation form and this is its counterweight.
    """
    glyphs = _shippedLeftGlyphs()
    assert "BT" in glyphs
    assert len(glyphs) >= 2, f"the left cluster reads implausibly short: {glyphs}"
    assert "⚡" not in glyphs, "US-696 removed the power glyph; it is back"


def test_rightClusterFitsItsGuaranteedTrackShare():
    """AC-2's "regardless of version-string length" holds only while the cluster
    fits the free-space share its `1fr` is guaranteed.

    SPLIT from the left cluster by US-696. The right side genuinely fits and
    this stays a real guard; the left side does not, and says so below rather
    than being carried along by a shared assertion.
    """
    model = _BarModel(readCss(_CSS_PATH))
    share = model.sideTrackShare()
    right = model.rightClusterWidth()
    assert right <= share, f"right cluster {right:.1f}px exceeds its {share:.1f}px share"


def test_theBarIsNotOverBudgetAcrossItsFullWidth():
    """AC-4's headline: the three clusters plus the gaps fit the usable bar.

    THIS is the assertion that means "nothing reflows into a second row", and it
    is the one US-696's band-budget criterion turns on. Measured on the glyphs
    the bar actually paints. Headroom went from 5.4px to 42.5px when US-696
    removed the bolt -- removing a glyph frees space, as that story predicted.
    """
    model = _BarModel(readCss(_CSS_PATH))
    used = (
        model.leftClusterWidth(_shippedLeftGlyphs())
        + model.centreWidth()
        + model.rightClusterWidth()
        + 2 * model.gap
    )
    assert used <= model.usable, f"{used:.1f}px used of {model.usable:.1f}px"


def test_leftClusterStillOverrunsItsTrackShare_us696NarrowedItButDidNotCloseIt():
    """CHARACTERISATION, filed as TD-us696 -- recorded, deliberately NOT fixed.

    THE FINDING. `test_aFourthGlyphStillFits_soP6DropsInWithNoRelayout` used to
    stand here and made "P-6 drops in with zero re-layout" a measured claim. It
    modelled the incoming glyph as a one-character `▾` at 27.0px. The glyph that
    actually shipped (ARCH-007) is the five-character `((•))` at 93.6px -- 3.5x
    the placeholder. So the guard passed, P-6 landed, and the left cluster went
    over its guaranteed share anyway. A guard that is real, that passes, and
    that cannot detect the class of change it exists to catch: this sprint's own
    thesis, in the band budget.

    THE OVERRUN IS REAL, NOT A MODEL ARTEFACT. This model reports UPPER bounds
    (MONO_ADVANCE_EM / SYMBOL_ADVANCE_EM are both worst-case), so an overrun it
    reports could in principle be slack. Re-measured with every character at the
    mono advance -- the optimistic bound -- the four-glyph bar was still over:
    175.6px against a 168.8px share. Over on BOTH bounds.

    WHAT US-696 DID TO IT. Removing the bolt took the cluster from 211.0px to
    173.9px against the same 168.8px share: the overrun falls from +42.2px to
    +5.1px on this bound, and the optimistic bound now FITS at 150.0px. So the
    story improved the condition by 37.1px and did not close it, which is why
    this is pinned rather than asserted away.

    IT IS NOT US-696'S TO FIX -- that story's own conditionalOutcomes say a
    band-budget finding "belongs in its own story". The consequence is bounded:
    a `1fr` is `minmax(auto, 1fr)`, so an oversized cluster grows its track and
    the CLOCK DRIFTS off the bar's midpoint. It does not wrap to a second row --
    the full-width budget above passes with 42.5px to spare.

    A fix that brings the cluster back under its share FAILS THIS TEST ON
    PURPOSE. That is the point: delete it then, do not weaken it.
    """
    model = _BarModel(readCss(_CSS_PATH))
    share = model.sideTrackShare()
    left = model.leftClusterWidth(_shippedLeftGlyphs())
    assert left > share, (
        f"left cluster {left:.1f}px is now within its {share:.1f}px share -- "
        "TD-us696 is FIXED. Delete this characterisation and restore the "
        "`left <= share` guard alongside test_rightClusterFitsItsGuaranteedTrackShare."
    )


def test_theNextGlyphIsARelayout_notADropIn():
    """The successor to `test_aFourthGlyphStillFits_soP6DropsInWithNoRelayout`,
    and the correction of its method.

    That guard's failure was not its arithmetic -- it was modelling a HYPOTHETICAL
    glyph at a width nobody had committed to. So this one models the next glyph
    at the width of the WIDEST GLYPH ALREADY ON THE BAR, which is the only glyph
    width this project has real evidence for. On that basis the answer today is
    NO: a fourth glyph does not fit, and whoever adds one is doing a re-layout.

    Stated as the honest negative rather than dropped. "We do not know if the
    next glyph fits" and "the next glyph does not fit" are different facts, and
    the first is what the deleted guard was really asserting.
    """
    model = _BarModel(readCss(_CSS_PATH))
    glyphs = _shippedLeftGlyphs()
    widest = max(
        _textWidthPx(glyph, model.glyphSize, model.glyphSpacing) for glyph in glyphs
    )
    withNext = model.leftClusterWidth(glyphs) + model.leftGap + widest
    share = model.sideTrackShare()
    assert withNext > share, (
        f"a 4th glyph at the widest shipped width takes the cluster to "
        f"{withNext:.1f}px against a {share:.1f}px share -- if this now fits, "
        "TD-us696 has been fixed and this guard should be re-stated positively."
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
