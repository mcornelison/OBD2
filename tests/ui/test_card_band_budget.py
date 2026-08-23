################################################################################
# File Name: test_card_band_budget.py
# Purpose/Description: US-557 (F-132) tests for the layout-band budget and its
#   tokenization. F-127 raised the type scale and left every chrome band at its
#   pre-F-127 height, so the cards overflowed and `#carousel { overflow: hidden }`
#   ate the difference in silence. THREE separate things are guarded here, and
#   they fail for three different reasons on purpose:
#     1. THE BUDGET (AC-2) -- a height model built from the SHIPPED values only,
#        so a token change moves the check instead of staling a comment. It has
#        a NEGATIVE SELF-TEST: a check never seen to fail is not known to be a
#        check.
#     2. THE TOKENIZATION (AC-4) -- the bands resolve from specs/UI/tokens.css,
#        and `#carousel`'s top/bottom derive from the same two values that define
#        the bars. The root cause was `28px` being a literal in one file and an
#        assumption in another, with nothing forcing the two to reconcile.
#     3. THE GREP GATE (AC-5) -- no retired band magnitude survives in a
#        VERTICAL-geometry property. Scoped to vertical geometry deliberately: a
#        band is a horizontal stripe that spends the stage's 320px of height, so
#        `padding: 0 14px` is not a band and a blind string search for "14px"
#        would report it as one.
#   WHAT IS NOT GUARDED, stated rather than implied: this repo's render harness
#   resolves the CASCADE but NOT LAYOUT (render_harness.py fidelity limit 1), so
#   no bench test here can assert "nothing is clipped on the glass". That is
#   validationCriteria #1 and #3, and it is owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Ralph (Rex)  | Initial -- US-557 band budget + tokenization.
# ================================================================================
################################################################################

"""US-557 tests for the dashboard's layout-band budget and its tokenization."""

from __future__ import annotations

import re

import pytest

from tests.ui.css_type_scale import DASHBOARD_CSS, TOKENS_CSS, readCss, ruleBlock, scaleValues

# The three bands US-557 promotes, with the values Iris's P-3 table sets. They
# are listed here so the SSOT and the dist mirror are both checked against ONE
# expectation rather than against each other -- two files agreeing on a wrong
# number is the failure mode a mirror-only comparison cannot see.
BAND_TOKENS = {
    "bar-h": 34,      # #topbar height. The one band that GREW: it was 28px
                      # carrying 26px glyphs, i.e. under-sized for its own
                      # contents. Paying 6px here is what P-2 needs.
    "dots-h": 16,     # #dots height. Restores the figure the F-127 budget had
                      # already assumed; the dots themselves paint 8px.
    "card-pad-y": 8,  # .card vertical padding, was 14px. Horizontal padding is
                      # deliberately NOT tokenized -- it spends no height, so it
                      # is not a band, and a fourth token is an Atlas Rule-10
                      # addition this story was not given.
}

# The stage's authored height. Read from the sheet by _stageHeightPx rather than
# hard-coded, because the whole budget hangs off it.
STAGE_HEIGHT_FALLBACK = 320

# `line-height: normal` on the faces --font-mono names resolves to roughly 1.2.
# THIS IS THE ONE ASSUMPTION IN THE MODEL and it is stated rather than buried:
# no rule on this surface declares a line-height for a tile line, so the exact
# line box is font-metric dependent and cannot be read out of CSS. Every
# conclusion below that MATTERS is asserted to hold at LINE_HEIGHT_FLOOR too --
# see test_theShippedThreeLineRow_overflowsAtAnyPlausibleLineHeight.
LINE_HEIGHT_NORMAL = 1.2

# A line box can never be shorter than its font size. Used to show that the
# overflow finding does not depend on the 1.2 above.
LINE_HEIGHT_FLOOR = 1.0

# The magnitudes US-557 retires from the band vocabulary (AC-5). 16px is NOT in
# this set: it is the NEW dots height, so listing it would make the gate fire on
# the fix.
RETIRED_BAND_PX = (28.0, 24.0, 14.0)

# Properties that spend the stage's vertical budget. `padding`/`margin` are
# included but only their VERTICAL components are read (see _verticalPxValues).
VERTICAL_GEOMETRY_PROPERTIES = frozenset(
    {
        "height",
        "min-height",
        "max-height",
        "top",
        "bottom",
        "padding",
        "padding-top",
        "padding-bottom",
        "margin",
        "margin-top",
        "margin-bottom",
    }
)

# Vertical uses of a retired magnitude that are NOT bands. Each entry needs a
# reason, because an allowlist without one is an exemption nobody can re-audit.
# Keyed by (selector-fragment, property).
NON_BAND_EXEMPTIONS = {
    (".confirm-box", "padding"): (
        "a centred modal box inside a full-screen overlay -- it floats over the "
        "stage rather than spending a stripe of its 320px, so its padding is "
        "box chrome, not a band"
    ),
    (".menu-status", "min-height"): (
        "reserved space for one status line inside the setup-menu overlay, so "
        "the band below it does not jump when the line appears -- again an "
        "overlay, not the carousel stage"
    ),
}


# ---------------------------------------------------------------------------
# CSS reading helpers
# ---------------------------------------------------------------------------


def _stripComments(css: str) -> str:
    """The sheet with `/* ... */` removed, so prose cannot trip a gate."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _declarations(css: str):
    """Every (selector, property, value) triple declared in a stylesheet.

    Args:
        css: the full stylesheet text.

    Returns:
        A list of (selector, property, value) tuples, comments removed and
        whitespace collapsed.
    """
    out = []
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", _stripComments(css)):
        selector = " ".join(rule.group(1).split())
        for piece in rule.group(2).split(";"):
            if ":" not in piece:
                continue
            prop, _, value = piece.partition(":")
            out.append((selector, prop.strip().lower(), " ".join(value.split())))
    return out


def _verticalPxValues(prop: str, value: str) -> list:
    """The px magnitudes in a declaration that spend VERTICAL space.

    A `padding`/`margin` shorthand puts the vertical components at index 0 and,
    when four values are given, index 2. Charging index 1 would report
    `padding: 0 14px` -- a purely horizontal inset -- as a 14px band, which is
    how a blind grep for the magnitude produces a false positive.

    Args:
        prop: the (lower-cased) property name.
        value: the declaration value.

    Returns:
        The vertical px magnitudes as floats; empty when the property spends no
        vertical space or the value carries no px literal.
    """
    if prop not in VERTICAL_GEOMETRY_PROPERTIES:
        return []
    parts = value.split()
    if prop in ("padding", "margin"):
        wanted = [parts[0]] if len(parts) < 3 else [parts[0], parts[2]]
    else:
        wanted = parts[:1]
    out = []
    for part in wanted:
        match = re.fullmatch(r"([0-9.]+)px", part)
        if match is not None:
            out.append(float(match.group(1)))
    return out


def _tokenPx(css: str, name: str) -> float:
    """The px magnitude declared for a custom property, read not assumed."""
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([0-9.]+)px;", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared as a px value"
    return float(match.group(1))


def _stageHeightPx(css: str) -> float:
    """The authored design-box height, read from `#stage`."""
    block = ruleBlock(css, "#stage")
    match = re.search(r"(?<![-\w])height:\s*([0-9.]+)px", block)
    assert match is not None, "#stage does not declare a px height"
    return float(match.group(1))


def _declaredVar(css: str, selector: str, prop: str) -> str:
    """The `var(--x)` token a declaration resolves through, or "" if it is bare.

    Args:
        css: the full stylesheet.
        selector: the exact selector.
        prop: the property to read.

    Returns:
        The token name without its leading `--`, or "" when the declaration is
        not a var() reference.
    """
    block = ruleBlock(css, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*var\(--([a-zA-Z0-9-]+)\)", block)
    return match.group(1) if match is not None else ""


def _shorthandVerticalVar(css: str, selector: str, prop: str) -> str:
    """The token in the FIRST (vertical) slot of a shorthand declaration."""
    block = ruleBlock(css, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*var\(--([a-zA-Z0-9-]+)\)\s", block)
    return match.group(1) if match is not None else ""


# ---------------------------------------------------------------------------
# The budget model
# ---------------------------------------------------------------------------


class _BandBudget:
    """The stage's vertical budget, derived from the SHIPPED sheet only.

    Nothing here is a magnitude copied out of the design note: every number is
    read back out of `dashboard.css`, so changing a token moves this model and a
    re-budget that breaks the ceiling fails HERE rather than on the glass.
    """

    def __init__(self, css: str, lineHeight: float = LINE_HEIGHT_NORMAL) -> None:
        self.css = css
        self.lineHeight = lineHeight
        self.stage = _stageHeightPx(css)
        self.barH = _tokenPx(css, "bar-h")
        self.dotsH = _tokenPx(css, "dots-h")
        self.cardPadY = _tokenPx(css, "card-pad-y")
        scale = scaleValues(css)
        self.titleSize = scale[_declaredVar(css, ".card-title", "font-size")]
        self.titleMargin = self._titleMarginBottom()
        self.tilePadY = self._tilePaddingY()
        self.tileBorder = self._tileBorderPx()
        self.labelSize = scale[_declaredVar(css, ".tile-label", "font-size")]
        self.valueSize = scale[_declaredVar(css, ".tile-value", "font-size")]
        self.detailSize = scale[_declaredVar(css, ".tile-detail", "font-size")]
        self.footerSize = scale["fs-meta"]

    def _titleMarginBottom(self) -> float:
        block = ruleBlock(self.css, ".card-title")
        match = re.search(r"(?<![-\w])margin:\s*([^;]+)", block)
        assert match is not None, ".card-title declares no margin"
        parts = re.findall(r"([0-9.]+)px|(\b0\b)", match.group(1))
        # `margin: 0 0 6px 0` -- the bottom component is index 2.
        values = [float(px) if px else 0.0 for px, _ in parts]
        assert len(values) >= 3, ".card-title margin is not a 3+ value shorthand"
        return values[2]

    def _tilePaddingY(self) -> float:
        block = ruleBlock(self.css, ".tile")
        match = re.search(r"(?<![-\w])padding:\s*([0-9.]+)px", block)
        assert match is not None, ".tile declares no px padding"
        return float(match.group(1))

    def _tileBorderPx(self) -> float:
        block = ruleBlock(self.css, ".tile")
        match = re.search(r"border-bottom:\s*([0-9.]+)px", block)
        assert match is not None, ".tile declares no px border-bottom"
        return float(match.group(1))

    def _line(self, sizePx: float) -> float:
        return sizePx * self.lineHeight

    @property
    def chrome(self) -> float:
        """Every px of stage height spent before a single fact is drawn."""
        return (
            self.barH
            + self.dotsH
            + 2 * self.cardPadY
            + self._line(self.titleSize)
            + self.titleMargin
        )

    @property
    def body(self) -> float:
        """The height `.card-body` actually gets."""
        return self.stage - self.chrome

    def rowHeight(self, withDetail: bool, isLast: bool = False) -> float:
        """One `.tile` as the sheet actually builds it.

        Args:
            withDetail: include the `.tile-detail` line. carousel.js's
                appendTile appends that span UNCONDITIONALLY, so True is the
                shipped shape and False is the two-line row the F-127 budget
                modelled.
            isLast: `.tile:last-child` drops its border-bottom.

        Returns:
            The row height in px.
        """
        height = 2 * self.tilePadY + self._line(self.labelSize) + self._line(self.valueSize)
        if withDetail:
            height += self._line(self.detailSize)
        if not isLast:
            height += self.tileBorder
        return height

    def content(self, rows: int, withDetail: bool, footer: bool) -> float:
        """What `rows` tiles plus an optional footer line demand."""
        total = sum(self.rowHeight(withDetail, isLast=(i == rows - 1)) for i in range(rows))
        if footer:
            total += self._line(self.footerSize)
        return total


# ---------------------------------------------------------------------------
# AC-2 -- the reclaimed budget.
# ---------------------------------------------------------------------------


def test_chromeReclaim_landsTheBodyAtTheBudgetedHeight():
    """Iris's P-3 table reclaims +23px of chrome and lands `.card-body` at
    224px. Asserted as a COMPUTED total, not as four separate constants: the
    story is the SUM, and four independently-correct bands that add to the wrong
    body is exactly the failure F-127's budget already had."""
    model = _BandBudget(readCss(DASHBOARD_CSS))
    assert model.stage == STAGE_HEIGHT_FALLBACK
    assert model.body == pytest.approx(224.0, abs=0.5), (
        f"chrome={model.chrome} body={model.body} -- P-3 budgets 224px of card "
        f"body (bar 34 + dots 16 + card pad 16 + title 30 = 96 of 320)"
    )


def test_theBudgetImprovedRatherThanJustMoved():
    """The pre-US-557 bands (28/24/14 + a 26px title) left 201px. Pinning the
    BEFORE figure here keeps `+23px` a measured delta rather than a claim in a
    commit message."""
    css = readCss(DASHBOARD_CSS)
    model = _BandBudget(css)
    before = _BandBudget(css)
    before.barH, before.dotsH, before.cardPadY = 28.0, 24.0, 14.0
    before.titleSize, before.titleMargin = scaleValues(css)["fs-secondary"], 8.0
    assert before.body == pytest.approx(201.0, abs=0.5), before.body
    assert model.body - before.body == pytest.approx(23.0, abs=1.0)


@pytest.mark.parametrize("token,inflated", [("bar-h", 60), ("dots-h", 48), ("card-pad-y", 24)])
def test_theBudgetCheckGoesRedWhenABandIsWrong(token, inflated):
    """THE NEGATIVE SELF-TEST. A budget check that has never been seen to fail
    is not known to be a budget check -- the same rule US-555's width model and
    US-563's schema guard were built under. Inflating any ONE band must break
    the 224px body, so the check cannot be passing for an unrelated reason."""
    css = readCss(DASHBOARD_CSS)
    broken = re.sub(rf"(--{token}:\s*)[0-9.]+px", rf"\g<1>{inflated}px", css)
    assert broken != css, f"the substitution did not fire for --{token}"
    model = _BandBudget(broken)
    assert model.body < 224.0, (
        f"--{token}: {inflated}px must NOT still leave a 224px body; if it does, "
        f"the model is not reading this token"
    )


# ---------------------------------------------------------------------------
# AC-6 -- the capacity ceiling, and what the SHIPPED row actually costs.
# ---------------------------------------------------------------------------


def test_theDeclaredCeiling_threeTwoLineRowsPlusAFooter_fits():
    """The ceiling Iris declared -- 3 rows + 1 footer -- holds for the row she
    MODELLED: label + value, no detail line."""
    model = _BandBudget(readCss(DASHBOARD_CSS))
    demand = model.content(rows=3, withDetail=False, footer=True)
    assert demand <= model.body, f"demand={demand} body={model.body}"


def test_theShippedThreeLineRow_doesNotFitThreeTimes_evenInTheNewBudget():
    """THE FINDING THIS MODEL EXISTS TO CATCH, and it is a SECOND omission in the
    same budget rather than a build regression.

    F-127 s3 modelled a row as `20 + 4 + 34 = 58px` -- a label and a value. The
    shipped `.tile` has THREE lines: carousel.js's appendTile appends a
    `.tile-detail` span UNCONDITIONALLY (every tile factory in the file supplies
    a `detail:`), and that line is `--fs-label` = 20px. The budget never counted
    it. So three real tiles do not fit in 224px, and reclaiming the chrome --
    which is still the right move, and still worth +23px -- does not by itself
    discharge the clipping on a three-tile card.

    This is pinned as a PASSING assertion of the overflow, not as an xfail: the
    overflow is a measured fact about the current surface, and a test that goes
    green when it disappears would hide the day someone fixes it."""
    model = _BandBudget(readCss(DASHBOARD_CSS))
    two = model.content(rows=2, withDetail=True, footer=True)
    three = model.content(rows=3, withDetail=True, footer=False)
    assert two <= model.body, (
        f"two shipped tiles + a footer must fit the reclaimed body "
        f"(demand={two} body={model.body}) -- if this fails the reclaim bought "
        f"nothing at all"
    )
    assert three > model.body, (
        f"three shipped three-line tiles are expected to OVERFLOW 224px "
        f"(demand={three} body={model.body}). If this now passes, the row shape "
        f"changed -- re-read the ceiling before deleting this test"
    )


def test_theShippedThreeLineRow_overflowsAtAnyPlausibleLineHeight():
    """The overflow above must not be an artefact of LINE_HEIGHT_NORMAL. A line
    box can never be shorter than its font size, so re-running the model at
    line-height 1.0 is the most generous case physically available -- and three
    shipped rows still do not fit. The finding is therefore robust to the one
    assumption in the model."""
    model = _BandBudget(readCss(DASHBOARD_CSS), lineHeight=LINE_HEIGHT_FLOOR)
    assert model.content(rows=3, withDetail=True, footer=False) > model.body


def test_everyDriverReadTierSurvived():
    """AC-3. The reclaim is CHROME only. `.tile-value` is the driver-read
    number and must still bind --fs-primary; the five scale values must be
    untouched. `.card-title` dropping to --fs-label is the one deliberate
    demotion and is allowed precisely because a title is a LABEL, not a value."""
    css = readCss(DASHBOARD_CSS)
    assert _declaredVar(css, ".tile-value", "font-size") == "fs-primary"
    assert scaleValues(css) == {
        "fs-hero": 44,
        "fs-primary": 34,
        "fs-secondary": 26,
        "fs-label": 20,
        "fs-meta": 15,
    }
    assert _declaredVar(css, ".card-title", "font-size") == "fs-label"


# ---------------------------------------------------------------------------
# AC-4 -- the bands are tokens, and #carousel derives from them.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("token,expected", sorted(BAND_TOKENS.items()))
def test_bandTokensAreDeclaredInTheSsotAndMirroredInTheDist(token, expected):
    """dashboard.html links ONLY dashboard.css (the kiosk is offline in the car,
    so a second stylesheet fetch would fail in the one place that matters), so
    the dist sheet mirrors the SSOT by hand. Both files are checked against the
    SAME expectation -- comparing them only to each other cannot see two files
    agreeing on a wrong number."""
    assert _tokenPx(readCss(TOKENS_CSS), token) == expected
    assert _tokenPx(readCss(DASHBOARD_CSS), token) == expected


@pytest.mark.parametrize(
    "selector,prop,token",
    [
        ("#topbar", "height", "bar-h"),
        ("#carousel", "top", "bar-h"),
        ("#rotate-progress", "top", "bar-h"),
        ("#dtc-ribbon", "top", "bar-h"),
        ("#carousel", "bottom", "dots-h"),
        ("#dots", "height", "dots-h"),
    ],
    ids=lambda v: str(v),
)
def test_everyBandSiteResolvesFromItsToken(selector, prop, token):
    """The root cause, stated as a test: `28px` was a literal in `#topbar` and
    an independent literal in `#carousel { top }`, `#rotate-progress { top }` and
    `#dtc-ribbon { top }`. FOUR copies of one fact, with nothing forcing them to
    reconcile when F-127 moved the type scale. They now read one token."""
    assert _declaredVar(readCss(DASHBOARD_CSS), selector, prop) == token


def test_cardVerticalPaddingResolvesFromItsToken():
    """`.card` uses the shorthand, so only its FIRST slot is the band. The
    horizontal slot stays a literal on purpose -- it spends no stage height."""
    assert _shorthandVerticalVar(readCss(DASHBOARD_CSS), ".card", "padding") == "card-pad-y"


def test_carouselDerivesItsExtentFromTheSameTokensAsTheBars():
    """The load-bearing consequence of AC-4: the carousel's top/bottom and the
    bars' heights are now the SAME two values, so the gap between them cannot
    reopen. Asserted as an identity between the sites, not as two magnitudes."""
    css = readCss(DASHBOARD_CSS)
    topToken = _declaredVar(css, "#carousel", "top")
    bottomToken = _declaredVar(css, "#carousel", "bottom")
    # Both halves must be REAL tokens before they are compared. Two bare
    # literals both resolve to "" here, and "" == "" is a green identity test
    # over the exact defect this story removes.
    assert topToken and bottomToken, "#carousel still declares bare band literals"
    assert topToken == _declaredVar(css, "#topbar", "height")
    assert bottomToken == _declaredVar(css, "#dots", "height")


# ---------------------------------------------------------------------------
# AC-5 -- the grep gate.
# ---------------------------------------------------------------------------


def test_noRetiredBandMagnitudeSurvivesInVerticalGeometry():
    """The DoD gate, mirroring US-539's. Scoped to VERTICAL geometry because a
    band is a stripe of the stage's height: `padding: 0 14px` and the `circle
    28px` mask radius are not bands, and a blind string grep would report both.
    Non-band vertical uses are exempted BY NAME WITH A REASON above."""
    offenders = []
    for selector, prop, value in _declarations(readCss(DASHBOARD_CSS)):
        for magnitude in _verticalPxValues(prop, value):
            if magnitude not in RETIRED_BAND_PX:
                continue
            exempt = any(
                frag in selector and prop == exemptProp
                for (frag, exemptProp) in NON_BAND_EXEMPTIONS
            )
            if not exempt:
                offenders.append(f"{selector} {{ {prop}: {value} }}")
    assert offenders == [], (
        "retired band magnitudes left in vertical geometry -- promote them to a "
        f"token or exempt them with a reason: {offenders}"
    )


def test_theGrepGateGoesRedOnAReLandedBandLiteral():
    """The gate's own negative self-test. Same rule as the budget model: a gate
    nobody has seen fail is not known to be a gate."""
    relanded = _verticalPxValues("height", "28px")
    assert relanded == [28.0]
    assert all(v in RETIRED_BAND_PX for v in relanded)


@pytest.mark.parametrize(
    "prop,value,expected",
    [
        ("padding", "0 14px", []),          # horizontal only -- not a band
        ("padding", "5px 14px", [5.0]),     # vertical is the 5, not the 14
        ("padding", "14px 16px", [14.0]),   # the retired card shorthand
        ("padding", "8px 16px 8px 16px", [8.0, 8.0]),
        ("height", "28px", [28.0]),
        ("height", "var(--bar-h)", []),
        ("-webkit-mask", "radial-gradient(circle 28px at center, ...)", []),
        ("border-radius", "24px", []),
    ],
)
def test_verticalPxReader_chargesOnlyWhatSpendsHeight(prop, value, expected):
    """Pins the discriminator itself. The `padding: 0 14px` row is the one that
    matters: it is a real declaration in this sheet, and treating it as a band
    would force a false exemption that then hides a real one."""
    assert _verticalPxValues(prop, value) == expected


def test_everyExemptionStillMatchesSomethingAndCarriesAReason():
    """An allowlist entry that no longer matches anything is a dead exemption
    quietly widening the gate. Both halves are checked: the reason exists, and
    the rule it excuses still exists."""
    declarations = _declarations(readCss(DASHBOARD_CSS))
    for (frag, prop), reason in NON_BAND_EXEMPTIONS.items():
        assert reason.strip(), f"exemption {frag}/{prop} carries no reason"
        hits = [
            (sel, value)
            for sel, declProp, value in declarations
            if frag in sel and declProp == prop and _verticalPxValues(prop, value)
        ]
        assert hits, (
            f"exemption {frag} {{ {prop} }} matches nothing -- delete it rather "
            f"than leaving the gate widened for a rule that is gone"
        )


# ---------------------------------------------------------------------------
# AC-7 -- no silent clip.
# ---------------------------------------------------------------------------


def test_cardBodyCanActuallyShrink_soOverflowIsItsOwnProblem():
    """`min-height: 0` is the load-bearing half and the least obvious one. A
    column flex item defaults to `min-height: auto`, which REFUSES to shrink
    below its content -- so an over-full `.card-body` pushes `.card` past 100%
    height and `#carousel { overflow: hidden }` eats the difference outside the
    card. Without this declaration the overflow rule below is inert: the body
    never overflows, the CARD does."""
    block = ruleBlock(readCss(DASHBOARD_CSS), ".card-body")
    assert re.search(r"(?<![-\w])min-height:\s*0", block), block


def test_cardBodyAdmitsOverflowRatherThanSwallowingIt():
    """AC-7. The surface has to say when it is holding more than it shows.
    `overflow-y: auto` is what makes the extra content REACHABLE; the two
    background layers are what make it VISIBLE:
      - a `--bg` cover pinned to the bottom of the CONTENT (`local`), and
      - a `--text-tertiary` rule pinned to the bottom of the BOX (`scroll`).
    The cover rides the content, so it only sits over the rule once you have
    reached the end -- i.e. the rule shows exactly while something is still
    below. That is the honest signal, and it is CSS-only, so it cannot go stale
    the way a measured-once JS check would."""
    block = ruleBlock(readCss(DASHBOARD_CSS), ".card-body")
    assert re.search(r"(?<![-\w])overflow-y:\s*auto", block), block
    assert "no-repeat local" in block, "no content-anchored cover layer"
    assert "no-repeat scroll" in block, "no box-anchored rule layer"
    assert "var(--text-tertiary)" in block, (
        "the overflow cue must reuse an existing neutral token -- a state colour "
        "here would be a fourth thing claiming to mean degraded"
    )


def test_theOverflowCueIsNotAnAlarmColour():
    """A clipped card is a LAYOUT fact, not a vehicle fault. Painting the cue
    amber or red would put a layout condition into the alert vocabulary that
    US-488 spent a story making mean exactly one thing each."""
    block = ruleBlock(readCss(DASHBOARD_CSS), ".card-body")
    for banned in ("--amber-warn", "--critical-red", "--green-ok", "--destructive"):
        assert banned not in block, f"{banned} must not dress the overflow cue"
