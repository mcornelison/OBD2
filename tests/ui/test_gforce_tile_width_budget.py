################################################################################
# File Name: test_gforce_tile_width_budget.py
# Purpose/Description: US-631 (F-138) -- the HORIZONTAL budget of the G-FORCE
#   tile in the live home face's right column, and the record of what it
#   measured. The CIO's reproduction: "when the word right appears it's causing
#   the display to bounce up and down." `.tile-detail` declares no
#   `white-space: nowrap` and no `min-height`, so a detail string one character
#   wider rewraps, the tile grows a line, and `.live-col`'s `justify-content:
#   center` re-centres the whole column -- which is the bounce.
#
#   THE STORY'S MANDATORY ACCEPTANCE LINE IS "RECORD THE MEASUREMENT, PASS OR
#   FAIL", so the measurement is the deliverable and it is recorded here whether
#   or not it fits. IT DOES NOT FIT, and not marginally: the widest string the
#   detail line can ever hold needs ~3x the column it is given, and it still
#   needs ~2.3x after dropping to `--fs-meta`, the SMALLEST tier in the F-127
#   scale. No tier fits. That is the conditionalOutcome the story wrote in
#   advance ("a card-layout call for Iris -- surface it rather than shrinking the
#   font below the floor") and it is filed as I-us631.
#
#   FOUR things are guarded, and they fail for four different reasons:
#     1. THE RECORD (the mandatory AC) -- the deficit is asserted, so it is a
#        CHARACTERISATION test: whoever widens the column or restructures the
#        tile FAILS HERE ON PURPOSE and must re-record the number rather than
#        let a stale measurement sit in the suite looking authoritative.
#     2. THE F-127 FLOOR -- `.tile-value` stays at `--fs-primary`. This is the
#        guard with teeth: the cheapest way to "fix" a width overrun is to shrink
#        the type, and F-127 spent a whole sprint ruling that out.
#     3. THE US-645 INTERACTION -- the measurement was taken against `steady`
#        AND `stopped`, the labels US-645 introduces. If US-645 lands a label
#        wider than the set measured here, this test goes red instead of quietly
#        re-opening the bounce US-631 measured.
#     4. THE MODEL ITSELF -- it REPRODUCES Atlas's observed left->right bounce,
#        which is what licenses trusting it (see the calibration note below).
#
#   WHAT IS NOT GUARDED, stated rather than implied: this repo's render harness
#   resolves the CASCADE but NOT LAYOUT (render_harness.py fidelity limit 1), so
#   nothing here asserts "no wrap ON THE GLASS". That is validationCriteria #2
#   and #3 and both are owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-631 G-FORCE tile width budget.
# ================================================================================
################################################################################

"""US-631: what the G-FORCE tile's right column can hold, measured and recorded."""

from __future__ import annotations

import os
import re

import pytest

from tests.ui.css_type_scale import (
    DASHBOARD_CSS,
    readCss,
    resolveFontPx,
    ruleBlock,
    scaleValues,
)

# The band model is IMPORTED rather than re-derived. It already reads every
# vertical magnitude back out of the shipped sheet, and a second private copy of
# the same arithmetic is how two files come to disagree about the card height.
# The coupling is deliberate: a re-budget that moves the card body SHOULD move
# this story's vertical finding too.
from tests.ui.test_card_band_budget import LINE_HEIGHT_NORMAL, _BandBudget

CAROUSEL_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard", "carousel.js"
)

# ---------------------------------------------------------------------------
# The one font metric this model needs, and how it is CONSTRAINED rather than
# assumed.
# ---------------------------------------------------------------------------
# A monospace advance ratio (glyph advance / font-size) cannot be read out of
# CSS -- it is a property of the face `--font-mono` resolves to. The band-budget
# model has the same shape of gap for `line-height: normal` and handles it the
# same way: state the assumption, then show the conclusions hold across the
# whole plausible range.
#
# WHAT MAKES THIS ONE BETTER THAN AN ASSUMPTION: Atlas's observation pins it.
# He measured that `0.0 left ...` and `0.0 right ...` -- one character apart --
# wrap to a DIFFERENT number of lines in this column. Greedy word-wrap in 108px
# at `--fs-label` only does that when `0.0 left` (8 chars) fits a line and
# `0.0 right` (9 chars) does not:
#
#     8 * 20 * a <= 108  ->  a <= 0.675
#     9 * 20 * a >  108  ->  a >  0.600
#
# So the observed defect CONSTRAINS the advance to (0.600, 0.675]. DejaVu Sans
# Mono -- what `ui-monospace` resolves to under Chromium on the Pi's Linux --
# has an advance of 0.60205, which lands inside that window by 0.37px of line
# box. The model is therefore calibrated against a real observation, not a
# number chosen to make the arithmetic come out.
ADVANCE_OBSERVED = 0.60205

# The window Atlas's bounce constrains the advance to. `test_theModel...`
# below re-derives these from the shipped column width rather than trusting the
# comment above.
ADVANCE_WINDOW = (0.600, 0.675)

# A deliberately over-wide range covering essentially every monospace face, used
# to show the "does not fit" finding does NOT depend on the calibration. If a
# conclusion survives 0.50 it is not an artefact of the font choice.
ADVANCE_ROBUST_RANGE = (0.50, 0.65)

# ---------------------------------------------------------------------------
# The label vocabulary the detail line can hold.
# ---------------------------------------------------------------------------
# gAxisDetail (carousel.js) formats `<n> <lateral> · <n> <longitudinal>`.
# TODAY's labels are read from the shipped source below; these are the labels
# the field will hold ONCE US-645 lands, and the story is explicit that the
# reservation must be sized for them: "Size for the widest string the label can
# ever hold, not the widest one it holds today."
#
# `stopped` (7) is wider than `steady` (6), and US-631's acceptance text names
# only `steady`. Both are taken from US-645's own acceptance -- "inside the
# deadband the label reads steady, and is upgraded to stopped ONLY when OBD
# SPEED IS TRULY ZERO" -- so sizing to `steady` alone would leave US-645 free to
# reintroduce exactly the bounce this story measured.
US645_LABELS = frozenset({"steady", "stopped"})
LATERAL_LABELS = frozenset({"left", "right"}) | US645_LABELS
LONGITUDINAL_LABELS = frozenset({"accel", "brake"}) | US645_LABELS

# The widest number the detail line can carry. The story's stated negative case
# is "a two-digit g reading under hard braking". `fmtG`/`gAxisDetail` apply NO
# magnitude clamp -- only the METER DOT clamps (`.imu-dot[data-clamped]`) -- so a
# two-digit reading reaches the text unmodified. Recorded honestly: two-digit g
# is an impact or a sensor fault, not a driving condition, so both it and the
# realistic single-digit case are measured below and reported separately.
WIDEST_NUMBER = "10.0"
REALISTIC_NUMBER = "1.2"

# Iris's F-127 floor: anything the driver must read to act is >= 34px. The
# G-FORCE magnitude is a driver-read value, so `--fs-primary` is a FLOOR here,
# not a preference.
LEGIBILITY_FLOOR_PX = 34


# ---------------------------------------------------------------------------
# Reading the shipped surface
# ---------------------------------------------------------------------------


def _flexBasisPx(css: str, selector: str) -> float:
    """The px basis of a `flex: <grow> <shrink> <basis>` shorthand.

    Args:
        css: the full stylesheet.
        selector: the exact selector whose rule declares the shorthand.

    Returns:
        The basis in px.
    """
    block = ruleBlock(css, selector)
    match = re.search(r"(?<![-\w])flex:\s*[0-9.]+\s+[0-9.]+\s+([0-9.]+)px", block)
    assert match is not None, f"{selector} declares no px flex-basis"
    return float(match.group(1))


def _declaredPx(css: str, selector: str, prop: str) -> float:
    """A plain `<prop>: <n>px` declaration read out of one rule."""
    block = ruleBlock(css, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*([0-9.]+)px", block)
    assert match is not None, f"{selector} declares no px {prop}"
    return float(match.group(1))


def _gapPx(css: str, selector: str) -> float:
    """The `gap` declared on one rule."""
    return _declaredPx(css, selector, "gap")


def _tierPx(css: str, selector: str) -> int:
    """The effective px size of one rule's `font-size`.

    Uses the SHARED US-539 resolver, which handles both the tokenized and the
    bare-px spelling. Resolving a bare px rather than refusing it is deliberate:
    if someone escapes the scale to make this tile fit, the guard that cares
    (`test_theDetailLineIsNotShrunkBelowTheScale`) must report the SIZE THEY
    CHOSE, not die in fixture setup. A guard that errors instead of failing
    hands back a stack trace where a number was wanted.
    """
    size = resolveFontPx(css, ruleBlock(css, selector))
    assert size > 0, f"{selector} declares no resolvable font-size"
    return size


def _shippedAxisLabels() -> set:
    """The direction words `gAxisDetail` actually ships today.

    Read from source so the US-645 superset above cannot silently stop covering
    the real vocabulary.

    Returns:
        The set of quoted words in the gAxisDetail function body.
    """
    with open(CAROUSEL_JS, encoding="utf-8") as fh:
        js = fh.read()
    match = re.search(r"function gAxisDetail\([^)]*\)\s*\{(.*?)\n  \}", js, re.DOTALL)
    assert match is not None, "gAxisDetail is not declared in carousel.js"
    body = match.group(1)
    # The separator is punctuation, not a label; everything else quoted in this
    # function is a direction word.
    return {w for w in re.findall(r'"([^"]*)"', body) if w.strip() and w.strip() != "·"}


# ---------------------------------------------------------------------------
# The width model
# ---------------------------------------------------------------------------


def _textPx(text: str, fontPx: float, advance: float) -> float:
    """Rendered width of a monospace string."""
    return len(text) * fontPx * advance


def _charsPerLine(widthPx: float, fontPx: float, advance: float) -> int:
    """How many monospace characters fit one line of `widthPx`."""
    return int(widthPx // (fontPx * advance))


def _wrapLines(text: str, widthPx: float, fontPx: float, advance: float) -> int:
    """Line count after greedy word wrapping, the way a browser breaks text.

    Args:
        text: the string to wrap.
        widthPx: the available content width.
        fontPx: the resolved font size.
        advance: the monospace advance ratio.

    Returns:
        The number of line boxes the string occupies (>= 1).
    """
    limit = _charsPerLine(widthPx, fontPx, advance)
    assert limit >= 1, "a column too narrow for one character is not a wrap problem"
    lines, current = 1, ""
    for word in text.split(" "):
        if not current:
            # A word longer than the line still occupies ONE box: no rule on
            # this surface sets `word-break`, so a browser overflows an
            # unbreakable word rather than splitting it. Starting a new line
            # here would over-count every long token.
            current = word
            continue
        candidate = current + " " + word
        if len(candidate) <= limit:
            current = candidate
        else:
            lines += 1
            current = word
    return lines


def _detailString(number: str, lateral: str, longitudinal: str) -> str:
    """gAxisDetail's format, kept in ONE place so the model cannot drift."""
    return f"{number} {lateral} · {number} {longitudinal}"


def _widestDetail(number: str = WIDEST_NUMBER) -> str:
    """The widest string the detail line can ever hold, US-645 included."""
    return _detailString(
        number,
        max(LATERAL_LABELS, key=len),
        max(LONGITUDINAL_LABELS, key=len),
    )


class _GColumn:
    """The live face's right column, read back out of the shipped sheet."""

    def __init__(self, css: str) -> None:
        self.css = css
        self.width = _flexBasisPx(css, ".live-g")
        self.meter = _declaredPx(css, ".live-g .imu-meter", "height")
        self.gap = _gapPx(css, ".live-g")
        self.labelPx = _tierPx(css, ".tile-label")
        self.valuePx = _tierPx(css, ".tile-value")
        self.detailPx = _tierPx(css, ".tile-detail")
        self.smallestTierPx = min(scaleValues(css).values())
        self.tilePadY = _declaredPx(css, ".tile", "padding")

    def detailHeightAvailable(self) -> float:
        """Vertical room left for `.tile-detail` after the column's furniture.

        `_BandBudget` is built HERE rather than in __init__ on purpose: it reads
        the whole card's vertical budget and refuses a sheet that has escaped the
        type scale, so constructing it eagerly would turn every horizontal guard
        in this file into a setup ERROR the moment someone shrinks a tier -- and
        the horizontal guards are precisely the ones that need to speak up in
        that case. Fail where the fault is, not everywhere at once.
        """
        used = (
            self.meter
            + self.gap
            + 2 * self.tilePadY
            + self.labelPx * LINE_HEIGHT_NORMAL
            + self.valuePx * LINE_HEIGHT_NORMAL
        )
        return _BandBudget(self.css).body - used


@pytest.fixture(scope="module")
def css() -> str:
    return readCss(DASHBOARD_CSS)


@pytest.fixture(scope="module")
def column(css) -> _GColumn:
    return _GColumn(css)


# ---------------------------------------------------------------------------
# 4. The model reproduces the observation that licenses it.
# ---------------------------------------------------------------------------


def test_theModelReproducesTheObservedLeftToRightBounce(column):
    """Given: the CIO's reproduction -- the word `right` makes the card bounce.

    When: the shipped column width and type tier are run through the wrap model.
    Then: `0.0 left ...` and `0.0 right ...` occupy DIFFERENT line counts.

    This is the test that makes every other number in this file credible. A
    width model that could not reproduce the one bounce somebody actually
    watched would be arithmetic, not a measurement.
    """
    left = _detailString("0.0", "left", "accel")
    right = _detailString("0.0", "right", "accel")
    leftLines = _wrapLines(left, column.width, column.detailPx, ADVANCE_OBSERVED)
    rightLines = _wrapLines(right, column.width, column.detailPx, ADVANCE_OBSERVED)
    assert rightLines > leftLines, (
        f"the model does not reproduce the reported defect: {left!r} takes "
        f"{leftLines} lines and {right!r} takes {rightLines}. The CIO watched "
        f"the card bounce on exactly this transition, so a model that flattens "
        f"it is wrong and nothing else in this file can be trusted."
    )


def test_theObservedBounceConstrainsTheAdvanceRatio(column):
    """Given: the bounce happens at all.

    When: solved for the advance ratio that makes 8 chars fit and 9 not.
    Then: the window is (0.600, 0.675] and the assumed advance sits inside it.

    The advance is the ONE font metric this model cannot read out of CSS. It is
    not asserted here -- it is DERIVED from the observation, which is what keeps
    it from being a number chosen to suit the conclusion.
    """
    lower = column.width / (9 * column.detailPx)
    upper = column.width / (8 * column.detailPx)
    assert (lower, upper) == pytest.approx(ADVANCE_WINDOW, abs=0.005), (
        f"the observed bounce constrains the advance to ({lower:.4f}, "
        f"{upper:.4f}], which is not the recorded {ADVANCE_WINDOW}"
    )
    assert lower < ADVANCE_OBSERVED <= upper, (
        f"the assumed advance {ADVANCE_OBSERVED} is OUTSIDE the window the "
        f"observed bounce allows ({lower:.4f}, {upper:.4f}] -- either the "
        f"observation or the metric is wrong, and both need a human"
    )


# ---------------------------------------------------------------------------
# 1. THE RECORD -- the mandatory acceptance line.
# ---------------------------------------------------------------------------


def test_recordTheMeasurement_theDetailLineDoesNotFitItsColumn(column):
    """Given: the widest string `.tile-detail` can ever hold (US-645 included).

    When: measured against the width `.live-g` actually reserves.
    Then: it does not fit, and the deficit is RECORDED.

    THIS TEST FAILS ON PURPOSE WHEN THE LAYOUT IS FIXED. It is the story's
    "record the measurement, pass or fail" line, so the number has to be pinned
    rather than narrated -- a stale measurement in a passing suite is worse than
    none, because it looks authoritative.
    """
    widest = _widestDetail()
    needed = _textPx(widest, column.detailPx, ADVANCE_OBSERVED)
    assert needed > column.width, (
        f"{widest!r} now FITS {column.width}px ({needed:.1f}px needed). The "
        f"US-631 finding no longer holds -- re-record the measurement and close "
        f"I-us631 rather than deleting this test."
    )
    # Recorded for Iris, in the failure text of the assertion that carries it.
    assert needed / column.width > 2.5, (
        f"RECORDED (US-631): the detail line needs {needed:.1f}px for "
        f"{widest!r} ({len(widest)} chars at {column.detailPx}px) and has "
        f"{column.width}px -- {needed / column.width:.2f}x over. The overrun "
        f"has shrunk below 2.5x, so the Iris escalation needs re-stating."
    )


def test_recordTheMeasurement_noTierInTheScaleFitsTheDetailLine(column):
    """Given: the smallest tier the F-127 scale offers.

    When: the widest detail string is measured at THAT tier.
    Then: it still does not fit.

    This is the number that makes the escalation unavoidable. If the string fit
    at `--fs-meta` the fix would be a tier change and no design call would be
    needed; it does not, so the column -- not the type -- is the constraint.
    """
    widest = _widestDetail()
    needed = _textPx(widest, column.smallestTierPx, ADVANCE_OBSERVED)
    assert needed > column.width, (
        f"{widest!r} FITS {column.width}px at the smallest tier "
        f"({column.smallestTierPx}px, {needed:.1f}px needed) -- US-631 is a tier "
        f"change after all, not a layout call. Re-open the story."
    )


@pytest.mark.parametrize("advance", ADVANCE_ROBUST_RANGE)
def test_theDetailOverrunHoldsAtAnyPlausibleAdvance(column, advance):
    """Given: the advance ratio is the model's one unread input.

    When: the overrun is recomputed at both ends of an over-wide range.
    Then: it does not fit at either.

    Same discipline as the band budget's LINE_HEIGHT_FLOOR check: a finding that
    only holds at the calibrated metric is a finding about the metric.
    """
    needed = _textPx(_widestDetail(), column.detailPx, advance)
    assert needed > column.width, (
        f"at advance {advance} the detail line fits ({needed:.1f}px vs "
        f"{column.width}px) -- the overrun is an artefact of the font metric, "
        f"not a property of the layout"
    )


def test_recordTheMeasurement_theColumnCannotEvenReserveTheWrappedHeight(column):
    """Given: the story's sanctioned alternative -- "a min-height that cannot
        reflow" -- which kills the bounce without needing the string to fit.

    When: the worst-case wrapped height is measured against the room the column
        has left after its meter, label and value.
    Then: it does not fit either.

    This is why US-631 ships NO CSS. Both of the story's two offered mechanisms
    ("nowrap plus a width that fits" / "a min-height that cannot reflow") are out
    of room in a 108px column, so there is no in-surface fix left that does not
    shrink type below the F-127 floor.
    """
    widest = _widestDetail()
    lines = _wrapLines(widest, column.width, column.detailPx, ADVANCE_OBSERVED)
    needed = lines * column.detailPx * LINE_HEIGHT_NORMAL
    available = column.detailHeightAvailable()
    assert needed > available, (
        f"the worst case now RESERVES cleanly ({lines} lines = {needed:.1f}px "
        f"in {available:.1f}px available) -- a min-height fix is back on the "
        f"table and US-631 can be closed in-surface. Re-open it."
    )
    assert lines >= 4, (
        f"RECORDED (US-631): the worst-case detail wraps to {lines} lines "
        f"({needed:.1f}px) and the column has {available:.1f}px, room for "
        f"{int(available // (column.detailPx * LINE_HEIGHT_NORMAL))}. The wrap "
        f"count has changed -- re-record it."
    )


def test_recordTheMeasurement_thePrimaryValueAtTheFloorIsTheMarginalCase(column):
    """Given: the widest plausible PRIMARY value, at the F-127 legibility floor.

    When: measured against the same column.
    Then: the realistic single-digit reading fits and the two-digit one does not.

    Recorded as a SEPARATE and honestly weaker finding than the detail-line one:
    it is marginal (a few px), it depends on the font metric in a way the detail
    finding does not, and a two-digit g is an impact or a sensor fault rather
    than a driving condition. Atlas saw the unit `g` wrap when the tile still
    printed TWO decimals; ARCH-011's cut to one decimal masked that, and a
    two-digit reading brings it straight back.
    """
    realistic = f"{REALISTIC_NUMBER} g"
    widest = f"{WIDEST_NUMBER} g"
    realisticPx = _textPx(realistic, column.valuePx, ADVANCE_OBSERVED)
    widestPx = _textPx(widest, column.valuePx, ADVANCE_OBSERVED)
    assert realisticPx <= column.width, (
        f"RECORDED (US-631): even the ordinary reading {realistic!r} no longer "
        f"fits ({realisticPx:.1f}px vs {column.width}px). That is a harder "
        f"failure than US-631 measured and should be escalated as such."
    )
    assert widestPx > column.width, (
        f"RECORDED (US-631): {widest!r} now fits ({widestPx:.1f}px vs "
        f"{column.width}px) -- the story's stated negative case is satisfied "
        f"and this half of the finding should be withdrawn."
    )


# ---------------------------------------------------------------------------
# 2. THE F-127 FLOOR -- the guard with teeth.
# ---------------------------------------------------------------------------


def test_theGforceValueStaysAtTheLegibilityFloor(column):
    """Given: the cheapest way to make a width overrun go away is smaller type.

    When: the shipped `.tile-value` tier is read.
    Then: it is still at or above Iris's 34px driver-must-read floor.

    THE LOAD-BEARING GUARD OF THIS STORY. US-631's conditionalOutcome is
    explicit -- "surface it rather than shrinking the font below the floor" --
    and this is the only thing standing between that instruction and the
    obvious shortcut. It is deliberately NOT scoped to `.live-g`: the G-FORCE
    magnitude is the same `.tile-value` everywhere it renders.
    """
    assert column.valuePx >= LEGIBILITY_FLOOR_PX, (
        f".tile-value is {column.valuePx}px, below the F-127 legibility floor "
        f"of {LEGIBILITY_FLOOR_PX}px. If this moved to make the G-FORCE tile "
        f"fit, that is the exact trade US-631 forbids -- the column is the "
        f"problem, not the type."
    )


def test_theDetailLineIsNotShrunkBelowTheScale(column, css):
    """Given: the same shortcut, applied to the detail line instead.

    When: `.tile-detail`'s tier is read.
    Then: it is still a declared F-127 tier, not a bare px escape hatch.

    A bare `font-size: 11px` here would "fix" the wrap and silently leave the
    scale US-539 tokenized -- the drift that story exists to prevent.
    """
    block = ruleBlock(css, ".tile-detail")
    assert re.search(r"(?<![-\w])font-size:\s*var\(--fs-", block), (
        ".tile-detail no longer takes its size from the F-127 scale. A bare px "
        "size here is how a width overrun gets fixed by leaving the scale."
    )
    assert column.detailPx >= column.smallestTierPx, (
        f".tile-detail is {column.detailPx}px, below the smallest declared tier "
        f"({column.smallestTierPx}px)"
    )


# ---------------------------------------------------------------------------
# 3. THE US-645 INTERACTION.
# ---------------------------------------------------------------------------


def test_theShippedLabelsAreCoveredByTheMeasuredVocabulary():
    """Given: the measurement was taken against a FUTURE label set.

    When: the words gAxisDetail actually ships are read out of carousel.js.
    Then: every one of them is inside the set that was measured.

    This is the US-645 tripwire. US-631's acceptance warns that US-645's neutral
    third state is wider than both of today's labels and "WILL BITE IF IGNORED".
    If US-645 lands a word outside the measured set, the reservation this story
    sized is wrong and this goes red -- instead of the bounce quietly returning.
    """
    shipped = _shippedAxisLabels()
    measured = LATERAL_LABELS | LONGITUDINAL_LABELS
    unmeasured = shipped - measured
    assert not unmeasured, (
        f"gAxisDetail ships {sorted(unmeasured)}, which US-631 never measured. "
        f"Widest measured was {max(measured, key=len)!r} "
        f"({len(max(measured, key=len))} chars); "
        f"{sorted(unmeasured, key=len)[-1]!r} is "
        f"{len(sorted(unmeasured, key=len)[-1])}. Re-record the US-631 "
        f"measurement against the new vocabulary."
    )


def test_theMeasuredVocabularyIncludesTheUs645Labels():
    """Given: US-645 introduces `steady` and upgrades it to `stopped`.

    When: the measured vocabulary is inspected.
    Then: both are in it, and `stopped` is the widest.

    US-631's own text names only `steady`. `stopped` is wider, comes from the
    same US-645 acceptance line, and sizing to `steady` alone would leave US-645
    free to reintroduce the bounce -- so the wider word is pinned here
    deliberately rather than inherited by accident.
    """
    measured = LATERAL_LABELS | LONGITUDINAL_LABELS
    assert US645_LABELS <= measured, "US-645's labels are not in the measured set"
    assert max(measured, key=len) == "stopped", (
        f"the widest measured label is {max(measured, key=len)!r}; US-631 sized "
        f"against 'stopped' and a wider one invalidates the recorded number"
    )


def test_theWidestDetailUsesTheWidestLabelOnBothAxes():
    """Given: the widest-string builder.

    When: it is asked for the worst case.
    Then: both axes carry the widest label, not just the lateral one.

    Guards the model against the exact reading error US-631 warns about --
    sizing for the label that changes today and forgetting the other axis has
    the identical defect.
    """
    widest = _widestDetail()
    assert widest.count("stopped") == 2, (
        f"the worst case {widest!r} does not put the widest label on BOTH axes"
    )
    assert widest == "10.0 stopped · 10.0 stopped", (
        f"the recorded worst case has changed to {widest!r} -- every measurement "
        f"in this file was taken against the previous one"
    )


# ---------------------------------------------------------------------------
# Negative self-tests -- a check never seen to fail is not known to be a check.
# ---------------------------------------------------------------------------


def test_theWrapModelGoesRedOnAColumnThatWouldActuallyFit(column):
    """Given: the wrap model reports an overrun.

    When: the same string is measured against a column wide enough to hold it.
    Then: it reports a fit.

    Without this the overrun assertions could be passing because the model
    always says "does not fit".
    """
    widest = _widestDetail()
    generous = _textPx(widest, column.detailPx, ADVANCE_OBSERVED) + 1
    assert _wrapLines(widest, generous, column.detailPx, ADVANCE_OBSERVED) == 1
    assert _textPx(widest, column.detailPx, ADVANCE_OBSERVED) <= generous


@pytest.mark.parametrize(
    "text,limitChars,expected",
    [
        ("aaa bbb", 7, 1),
        ("aaa bbb", 6, 2),
        ("aaaaaaaa", 3, 1),  # a word longer than the line still occupies one box
        ("a b c d", 3, 2),
    ],
)
def test_theGreedyWrapMatchesBrowserWordBreaking(text, limitChars, expected):
    """Given: the wrap model stands in for a browser's line breaking.

    When: run over cases with a known answer.
    Then: it agrees.

    `_wrapLines` takes px, so the cases are expressed at a 1px font and an
    advance of 1.0, making `limitChars` the literal character budget.
    """
    assert _wrapLines(text, float(limitChars), 1.0, 1.0) == expected
