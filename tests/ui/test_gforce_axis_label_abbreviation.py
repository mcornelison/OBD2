################################################################################
# File Name: test_gforce_axis_label_abbreviation.py
# Purpose/Description: US-631 (A) (F-138) -- the G-FORCE detail line no longer
#   BOUNCES when the lateral direction flips. The CIO, from the driver's seat
#   2026-08-31: "abbreviate the words left and right in the lower right hand
#   corner ... they do bounce as the word right will wrap around cuz it's too
#   long to fit on the screen." Atlas photographed both states one minute apart:
#   2:46 PM rendered FOUR lines, 2:47 PM rendered THREE. The tile grew by a whole
#   line box when the word changed, and `.live-col { justify-content: center }`
#   re-centred the column around it.
#
#   THE MECHANISM, AND WHY THE FIX IS TWO CHARACTERS. `.tile-detail` declares no
#   `white-space: nowrap` and no `min-height`, so line count is a pure function
#   of string length in a 108px column. On that line the lateral word was the
#   ONLY token whose length varied with the data -- `left` is 4, `right` is 5,
#   while `accel` and `brake` are both 5 and never moved anything. At `L`/`R` the
#   rendered length depends only on the two MAGNITUDES, so no change of DIRECTION
#   can change the line count. The bounce is removed at its source rather than
#   suppressed in the stylesheet.
#
#   THE TRAP THIS FILE IS BUILT AROUND. Constant length is trivially achievable
#   the WRONG way: collapse both directions to one token and the bounce also
#   disappears -- along with the sign contract `gAxisDetail` exists to publish
#   ("0.3 brake" while accelerating is how a mounted-backwards board announces
#   itself). So every length claim here is paired with a DISTINGUISHABILITY
#   claim. Either one alone can be satisfied by a fix that breaks the other.
#
#   WHAT THIS STORY-HALF DOES NOT CLOSE, recorded rather than implied: the line
#   still WRAPS. (A) makes the wrap STABLE, not absent. The width reservation is
#   US-631 (B), it does not fit at any tier in the F-127 scale, and it is with
#   Iris as I-us631. The post-(A) figure is re-recorded here so the escalation
#   carries a current number instead of a pre-fix one.
#
#   FIDELITY, stated: the render harness resolves the CASCADE, not LAYOUT
#   (render_harness.py limit 1), so nothing here can assert "no wrap ON THE
#   GLASS". What it CAN do -- and does -- is take the string the SHIPPED
#   carousel.js actually painted through the SHIPPED markup and stylesheet at
#   480x320, and run THAT through the calibrated width model from
#   test_gforce_tile_width_budget.py. The string is measured, not assumed.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-631 (A) lateral label abbreviation.
# ================================================================================
################################################################################

"""US-631 (A): flipping the lateral direction can no longer reflow the tile."""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
from typing import Any

import pytest

from tests.ui import render_harness as rh
from tests.ui.css_type_scale import DASHBOARD_CSS, readCss

# The width model is IMPORTED, never re-derived. It is calibrated against the one
# bounce a human actually watched, and a second private copy of the same
# arithmetic is how two files come to disagree about the same column. Importing
# it also means a re-budget of `.live-g` moves BOTH stories' findings at once.
from tests.ui.test_gforce_tile_width_budget import (
    ADVANCE_OBSERVED,
    ADVANCE_ROBUST_RANGE,
    LATERAL_LABELS,
    LONGITUDINAL_LABELS,
    US645_LABELS,
    _detailString,
    _GColumn,
    _shippedAxisLabels,
    _textPx,
    _wrapLines,
)

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

# The shipped panel. Every layout claim in this file is about THIS viewport --
# the width budget is a fact about 480x320 and nothing else.
PANEL = (480, 320)

# The words the CIO watched bounce. Kept as literals so the pre-fix case stays
# available as a negative control: a model that reports "no bounce" for the
# CURRENT labels is only meaningful if it still reports one for the OLD ones.
PREFIX_LATERAL = ("left", "right")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the shipped carousel.js needs node to render",
)


# ---------------------------------------------------------------------------
# Fixtures: the real producer payload, the real render
# ---------------------------------------------------------------------------


def _liveImu(gLat: float, gLon: float) -> dict[str, Any]:
    """A states/imu payload the shipped `imuView` accepts as LIVE.

    Stamped from the wall clock rather than a fixed instant: `imuView` ages the
    reading against `Date.now()` inside node, so a frozen stamp would go stale
    on its own and drop the home slot to the IDLE face -- which has no G-FORCE
    tile at all, and every assertion here would then pass for the wrong reason.

    Args:
        gLat: lateral g, signed (+ right).
        gLon: longitudinal g, signed (+ accelerating).

    Returns:
        The state-file payload.
    """
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "ts": now,
        "available": True,
        "gLat": gLat,
        "gLon": gLon,
        "gMag": round((gLat**2 + gLon**2) ** 0.5, 3),
        "headingDeg": 180.0,
        "gradePct": 1.0,
    }


def _nowMs() -> int:
    """Wall clock in ms -- `liveCardView` ages the reading against it."""
    return int(dt.datetime.now(dt.UTC).timestamp() * 1000)


def _surface(gLat: float, gLon: float):
    """Boot the SHIPPED carousel.js over the SHIPPED markup + stylesheet."""
    tree = rh.runDashboard(routes={"/imu": _liveImu(gLat, gLon)}, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _textOf(node: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return out


def _paintedInGColumn(surface, className: str) -> str | None:
    """The printed text of the first PAINTED `className` inside `.live-g`.

    Scoped to the g-force column on purpose: `.tile-detail` is the shared tile
    idiom and the heading/grade/altitude tiles use it too, so an unscoped lookup
    could measure the wrong string entirely. Painted, not merely present -- an
    element under a `display: none` ancestor is not on the panel, which is the
    whole reason the real cascade is resolved here.
    """
    for path in surface.pathsByClass(className):
        if not surface.rendered(path):
            continue
        if not any("live-g" in (n.get("attrs", {}).get("class") or "").split() for n in path):
            continue
        return " ".join(_textOf(path[-1])).strip()
    return None


def _paintedDetail(gLat: float, gLon: float) -> str:
    """The detail string the panel ACTUALLY shows for one reading."""
    detail = _paintedInGColumn(_surface(gLat, gLon), "tile-detail")
    assert detail, "the G-FORCE tile painted no detail line"
    return detail


def _view(fn: str, *args: object) -> Any:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn] + [json.dumps(a) for a in args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def column() -> _GColumn:
    """The live face's right column, read back out of the shipped sheet."""
    return _GColumn(readCss(DASHBOARD_CSS))


# ---------------------------------------------------------------------------
# 0. Negative control. Every claim below is about a string on the panel, and
#    all of them would "pass" vacuously on a live face that never painted.
# ---------------------------------------------------------------------------


def test_theGforceTilePaints_negativeControlForEveryClaimBelow():
    """
    Given: a live, fresh motion feed
    When:  the panel renders at 480x320
    Then:  the G-FORCE tile is genuinely painted -- label, value and detail

    Without this, a regression that dropped the live face entirely would leave
    every length comparison below comparing nothing to nothing.
    """
    surface = _surface(0.30, 0.12)

    assert _paintedInGColumn(surface, "tile-label") == "G-FORCE", (
        "the G-FORCE tile did not paint -- every assertion in this file would be "
        "an artefact of the harness rather than a fact about the panel"
    )
    assert _paintedInGColumn(surface, "tile-value"), "the g magnitude did not paint"
    assert _paintedInGColumn(surface, "tile-detail"), "the axis detail did not paint"


# ---------------------------------------------------------------------------
# 1. THE FIX: a change of DIRECTION cannot change the rendered length.
# ---------------------------------------------------------------------------


def test_flippingTheLateralDirectionDoesNotChangeTheRenderedLength():
    """
    Given: the CIO's exact reproduction -- the same corner taken the other way
    When:  both readings are rendered through the shipped carousel.js
    Then:  the two painted strings have IDENTICAL length

    THE HEADLINE PIN OF US-631 (A). `.tile-detail` sets no `white-space` and no
    `min-height`, so in a fixed column the line count is a pure function of
    length: equal length is equal line count is no reflow is no bounce.
    """
    left = _paintedDetail(-0.30, 0.12)
    right = _paintedDetail(0.30, 0.12)

    assert len(left) == len(right), (
        f"the detail line still changes length when the direction flips: "
        f"{left!r} is {len(left)} chars and {right!r} is {len(right)}. That is "
        f"the bounce the CIO watched -- one extra character rewraps the line, "
        f"grows the tile and re-centres the column."
    )


def test_theDirectionIsStillLegibleAfterTheAbbreviation():
    """
    Given: constant length is trivially achievable by DELETING the distinction
    When:  the two directions are rendered
    Then:  they still render DIFFERENTLY

    Paired with the length pin above on purpose. A fix that collapsed both
    directions to one token would satisfy that test perfectly and silently throw
    away the sign contract -- the thing that makes a mounted-backwards board
    visible to the operator instead of a quietly mirrored dot.
    """
    left = _paintedDetail(-0.30, 0.12)
    right = _paintedDetail(0.30, 0.12)

    assert left != right, (
        f"both lateral directions now paint {left!r}. The bounce is gone because "
        f"the DISTINCTION is gone, which is not the fix -- the sign contract is "
        f"how a backwards-mounted IMU announces itself."
    )
    assert " L " in f" {left} " and " R " not in f" {left} ", (
        f"a left-hand corner painted {left!r}, which does not carry L"
    )
    assert " R " in f" {right} " and " L " not in f" {right} ", (
        f"a right-hand corner painted {right!r}, which does not carry R"
    )


@pytest.mark.parametrize(
    "gLat,gLon",
    [(0.30, 0.12), (-0.30, 0.12), (0.30, -0.12), (-0.30, -0.12)],
)
def test_everySignCombinationRendersTheSameLength(gLat, gLon):
    """
    Given: two signed axes, so FOUR label combinations, not two
    When:  each is rendered at the same magnitudes
    Then:  every one is the same length as the canonical right/accel case

    US-631's acceptance is explicit that the longitudinal axis has the identical
    defect shape and must not be forgotten ("sizing for the label that changes
    today and forgetting the other axis"). `accel` and `brake` happen to be
    equal length today, so this passes -- and goes red the moment that stops
    being true, which is exactly when the bounce would come back on the far axis.
    """
    reference = _paintedDetail(0.30, 0.12)
    painted = _paintedDetail(gLat, gLon)

    assert len(painted) == len(reference), (
        f"{painted!r} ({len(painted)} chars) does not match the reference "
        f"{reference!r} ({len(reference)}). Some label pair still varies in "
        f"width, so the tile can still reflow on a sign change."
    )


def test_theLongitudinalLabelsAreEqualLengthWhichIsWhyTheyWereNotAbbreviated(column):
    """
    Given: US-631 (A) abbreviated ONLY the lateral axis
    When:  the shipped longitudinal vocabulary is read out of carousel.js
    Then:  every word in it is the same length

    Records the REASON the other axis was left alone, so a future reader does
    not mistake it for an oversight: `accel` and `brake` are both 5 characters,
    so that axis never contributed to the reflow. If a longitudinal word of a
    different length is ever added, the bounce returns on that axis and this
    goes red rather than the panel starting to move again.
    """
    shipped = _shippedAxisLabels()
    longitudinal = shipped & LONGITUDINAL_LABELS
    assert longitudinal, f"no longitudinal label recognised in {sorted(shipped)}"
    widths = {len(word) for word in longitudinal}
    assert len(widths) == 1, (
        f"the shipped longitudinal labels {sorted(longitudinal)} are no longer "
        f"all the same length ({sorted(widths)}). US-631's bounce is back on the "
        f"longitudinal axis -- abbreviate to a constant width the way the lateral "
        f"axis was, or reserve the column."
    )


# ---------------------------------------------------------------------------
# 2. THE SIGN CONTRACT -- the thing the abbreviation had to preserve.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "gLat,gLon,lateral,longitudinal",
    [
        (0.30, 0.12, "R", "accel"),
        (-0.30, 0.12, "L", "accel"),
        (0.30, -0.12, "R", "brake"),
        (-0.30, -0.12, "L", "brake"),
    ],
)
def test_theSignContractSurvivesTheAbbreviation(gLat, gLon, lateral, longitudinal):
    """
    Given: the whole point of naming the axes is to publish the SIGN CONTRACT
    When:  each quadrant is rendered on the panel
    Then:  the direction words match the signs the state file carried

    This is the mounted-backwards detector. It is asserted on the RENDERED
    string, not on `gAxisDetail` in isolation, because a mirrored axis would
    reach the driver through the renderer -- and the sign is the one thing an
    abbreviation could invert without changing a single width.
    """
    painted = _paintedDetail(gLat, gLon)
    tokens = painted.split()

    assert lateral in tokens, (
        f"{gLat:+.2f} g lateral painted {painted!r}, which does not carry "
        f"{lateral!r} -- the sign contract is inverted or lost"
    )
    assert longitudinal in tokens, (
        f"{gLon:+.2f} g longitudinal painted {painted!r}, which does not carry "
        f"{longitudinal!r}"
    )


def test_theMagnitudesAreUnsignedBecauseTheWordCarriesTheDirection():
    """
    Given: the direction is published as a word, so the number must not repeat it
    When:  a hard left / hard brake is rendered
    Then:  no minus sign reaches the tile

    A `-0.3 L` would state the direction twice and read as a DOUBLE negative.
    Pinned because an abbreviation is exactly the moment someone reaches for a
    sign to compensate for the shorter word.
    """
    painted = _paintedDetail(-0.30, -0.12)
    assert "-" not in painted and "−" not in painted, (
        f"the detail line {painted!r} carries a sign as well as a direction word"
    )


def test_theRetiredWordsNoLongerReachThePanel():
    """
    Given: the CIO named `right` as the word that bounces
    When:  both lateral directions are rendered
    Then:  neither `left` nor `right` appears on the tile at all

    The symptom vocabulary is gone from the surface the CIO was looking at, not
    merely shortened somewhere upstream.
    """
    for painted in (_paintedDetail(-0.30, 0.12), _paintedDetail(0.30, 0.12)):
        for word in PREFIX_LATERAL:
            assert word not in painted, (
                f"the panel still paints {word!r} in {painted!r} -- US-631 (A) "
                f"did not reach the rendered tile"
            )


def test_theShippedVocabularyIsTheAbbreviatedOne():
    """
    Given: the width budget in test_gforce_tile_width_budget.py was re-recorded
        against `L`/`R`
    When:  the words gAxisDetail actually ships are read out of carousel.js
    Then:  the lateral pair is exactly {L, R}

    Keeps the two US-631 files from drifting apart: the measurement file sizes
    against a vocabulary, and this asserts the vocabulary it sized against is the
    one on the panel.

    UPDATED 2026-09-01 (US-645): the lateral axis gained a NEUTRAL, `-`, for
    readings inside the deadband. It is one character, exactly like `L` and `R`,
    so US-631 (A)'s constant-length property is untouched -- which is the whole
    reason US-645 was required to spell it that way. The pair is now a triple and
    the width claim is asserted directly rather than implied by the membership.
    """
    shipped = _shippedAxisLabels()
    lateral = shipped - LONGITUDINAL_LABELS
    assert lateral == {"L", "R", "-"}, (
        f"gAxisDetail ships lateral labels {sorted(lateral)}, not "
        f"{{'L', 'R', '-'}}. US-631's width measurement was taken against the "
        f"abbreviated pair plus US-645's one-character neutral."
    )
    assert {len(w) for w in lateral} == {1}, (
        f"the lateral labels {sorted(lateral)} are no longer all one character, "
        f"so a direction change can grow the tile again"
    )
    assert lateral <= LATERAL_LABELS, (
        f"{sorted(lateral)} is outside the measured vocabulary "
        f"{sorted(LATERAL_LABELS)} -- re-record the US-631 measurement"
    )


# ---------------------------------------------------------------------------
# 3. THE LINE COUNT -- the bounce itself, through the calibrated width model.
# ---------------------------------------------------------------------------


def test_theShippedColumnWrapsBothDirectionsToTheSameLineCount(column):
    """
    Given: the strings the panel ACTUALLY painted, and the real column width
    When:  both are wrapped by the model calibrated against the observed bounce
    Then:  they occupy the same number of line boxes -- and the PRE-FIX pair
        still does not, so the model has not simply stopped seeing bounces

    The negative control in the second half is what makes the first half mean
    anything. Equal line counts are also what a model that always returns 1 would
    report.
    """
    left = _paintedDetail(-0.30, 0.12)
    right = _paintedDetail(0.30, 0.12)
    leftLines = _wrapLines(left, column.width, column.detailPx, ADVANCE_OBSERVED)
    rightLines = _wrapLines(right, column.width, column.detailPx, ADVANCE_OBSERVED)

    assert leftLines == rightLines, (
        f"{left!r} wraps to {leftLines} lines and {right!r} to {rightLines} in "
        f"the shipped {column.width}px column -- the tile still grows on the "
        f"direction change"
    )

    oldLeft = _detailString("0.3", PREFIX_LATERAL[0], "accel")
    oldRight = _detailString("0.3", PREFIX_LATERAL[1], "accel")
    assert _wrapLines(oldLeft, column.width, column.detailPx, ADVANCE_OBSERVED) != _wrapLines(
        oldRight, column.width, column.detailPx, ADVANCE_OBSERVED
    ), (
        "the model no longer reproduces the PRE-FIX bounce, so its report that "
        "the current labels do not bounce is worthless -- recalibrate before "
        "trusting anything in this file"
    )


def test_theWidthModelAgreesWithTheRendererBeforeItIsSweptExhaustively(column):
    """
    Given: the exhaustive sweep below runs against the width MODEL, because
        160,000 node renders is not a test
    When:  the model's idea of the format is compared to what the SHIPPED
        renderer actually painted, in all four quadrants
    Then:  they agree character for character

    THE LICENCE FOR THE SWEEP. Without this the sweep would be a claim about
    `_detailString`, not about the tile: a renderer that started emitting a
    different format would leave it green forever. This is the join that makes
    the exhaustive result a fact about the panel.
    """
    for gLat, gLon, lateral, longitudinal in (
        (0.30, 0.12, "R", "accel"),
        (-0.30, 0.12, "L", "accel"),
        (0.30, -0.12, "R", "brake"),
        (-0.30, -0.12, "L", "brake"),
    ):
        painted = _paintedDetail(gLat, gLon)
        modelled = f"{abs(gLat):.1f} {lateral} · {abs(gLon):.1f} {longitudinal}"
        assert painted == modelled, (
            f"the renderer painted {painted!r} but the width model builds "
            f"{modelled!r} -- the sweep below would be measuring a format that "
            f"is not on the panel"
        )


def test_theTileHeightIsConstantAcrossTheWholeRepresentableRange(column):
    """
    Given: US-631 (A) claims the tile cannot grow on a DIRECTION change
    When:  every reading the shipped tile can represent is swept -- both axes,
        both directions, both longitudinal words, 0.0 to 19.9 g
    Then:  every single one occupies the SAME number of line boxes

    THE STRONGEST RESULT IN THIS FILE, and it is stronger than the story asked
    for. US-631 (A) was scoped to stop the LEFT->RIGHT bounce; the sweep shows
    the tile height is constant across the entire representable range, including
    the two-digit readings the story flagged as its negative case. There is no
    value, and no combination of values, at which this tile changes height.

    The range is stated rather than assumed: `fmtG`/`gAxisDetail` apply no
    magnitude clamp (only the meter DOT clamps), so a two-digit reading reaches
    the text unmodified. 19.9 g covers every impact or sensor fault worth
    rendering; beyond that the tile has stopped being the problem.

    Swept DENSELY on each axis in turn rather than as a full cross product: a
    line break can only be introduced by a token getting longer, and sweeping one
    axis at 0.1 against every distinct token length on the other reaches every
    combination that can matter for a fraction of the work.
    """
    spans = [f"{n / 10:.1f}" for n in range(0, 200)]
    lengths = ["0.0", "0.9", "9.9", "10.0", "19.9"]
    # Both vocabularies are READ FROM THE SHIPPED SOURCE, not written out here.
    # A sweep over hardcoded labels would stay green over a renderer that had
    # gone back to variable-width words -- it would be sweeping this file's
    # memory of the fix rather than the fix.
    shipped = _shippedAxisLabels()
    shippedLongitudinal = sorted(shipped & LONGITUDINAL_LABELS)
    shippedLateral = sorted(shipped - LONGITUDINAL_LABELS)
    assert shippedLateral and shippedLongitudinal, (
        f"could not read both axis vocabularies out of gAxisDetail: {sorted(shipped)}"
    )

    seen: dict[int, str] = {}
    for dense, sparse in ((spans, lengths), (lengths, spans)):
        for lat in dense:
            for lon in sparse:
                for lateral in shippedLateral:
                    for longitudinal in shippedLongitudinal:
                        text = f"{lat} {lateral} · {lon} {longitudinal}"
                        lines = _wrapLines(
                            text, column.width, column.detailPx, ADVANCE_OBSERVED
                        )
                        seen.setdefault(lines, text)

    assert len(seen) == 1, (
        "the tile changes height within its own value range: "
        + "; ".join(f"{lines} lines at {text!r}" for lines, text in sorted(seen.items()))
        + f". Any two of those rendering in succession is a bounce -- in a "
        f"{column.width}px column with no `min-height`, a change of line count "
        f"IS the defect US-631 was raised for."
    )


@pytest.mark.parametrize("advance", ADVANCE_ROBUST_RANGE)
def test_theBounceIsGoneAtAnyPlausibleFontMetric(column, advance):
    """
    Given: the monospace advance ratio is the model's one input it cannot read
        out of CSS
    When:  both directions are wrapped at both ends of an over-wide range
    Then:  the line counts still agree

    Same discipline the width budget applies to its overrun finding: a result
    that only holds at the calibrated metric is a result about the metric. This
    one is robust for a structural reason -- equal-length strings with identical
    word boundaries wrap identically at ANY advance -- and that is worth pinning,
    because it is precisely what a re-lengthened label would destroy.
    """
    left = _paintedDetail(-0.30, 0.12)
    right = _paintedDetail(0.30, 0.12)

    assert _wrapLines(left, column.width, column.detailPx, advance) == _wrapLines(
        right, column.width, column.detailPx, advance
    ), f"at advance {advance} the two directions still wrap differently"


# ---------------------------------------------------------------------------
# 4. RECORD THE MEASUREMENT, PASS OR FAIL -- the story's mandatory line,
#    re-taken AFTER (A) so the Iris escalation carries a current number.
# ---------------------------------------------------------------------------


def test_recordTheMeasurement_theAbbreviatedLineStillDoesNotFitTheColumn(column):
    """
    Given: US-631 (A) is the BOUNCE fix, and (B) -- the width reservation -- is
        still owed
    When:  the widest string the abbreviated vocabulary can hold TODAY is
        measured against the column
    Then:  it still overruns, and the post-(A) figure is RECORDED

    THIS FAILS ON PURPOSE WHEN THE COLUMN IS FIXED. The story's mandatory line is
    "RECORD THE MEASUREMENT, PASS OR FAIL", and the pre-(A) number in
    test_gforce_tile_width_budget.py is no longer the number that describes what
    ships -- a stale measurement in a passing suite is worse than none, because
    it looks authoritative. Recorded honestly: (A) bought real width (the widest
    lateral word went from 5 characters to 1) and it was not nearly enough.
    """
    # `sorted` before `max` so the recorded string is deterministic across runs:
    # `accel` and `brake` tie on length, and a set's iteration order does not.
    shippedLongitudinal = sorted(LONGITUDINAL_LABELS - US645_LABELS)
    widestToday = _detailString("10.0", "R", max(shippedLongitudinal, key=len))
    needed = _textPx(widestToday, column.detailPx, ADVANCE_OBSERVED)

    assert needed > column.width, (
        f"{widestToday!r} now FITS {column.width}px ({needed:.1f}px needed). "
        f"US-631 (B) is closed by (A) after all -- re-record and close I-us631 "
        f"rather than deleting this test."
    )
    assert needed / column.width > 1.5, (
        f"RECORDED (US-631, post-(A)): the widest SHIPPED detail string "
        f"{widestToday!r} needs {needed:.1f}px for {len(widestToday)} chars at "
        f"{column.detailPx}px and has {column.width}px -- "
        f"{needed / column.width:.2f}x over. The overrun has dropped below 1.5x, "
        f"so the Iris escalation needs re-stating with the smaller number."
    )


def test_recordTheMeasurement_theOrdinaryReadingStillWraps(column):
    """
    Given: the ORDINARY case, not the worst one -- a gentle corner while
        accelerating, which is what the tile shows most of the time
    When:  measured against the shipped column
    Then:  it still wraps, and by how much is RECORDED

    The honest statement of what the driver gets after (A): a tile that no longer
    MOVES, but is still broken across lines. This is the number that tells Iris
    whether (B) is still wanted at the same priority -- which is what US-631's
    acceptance asks for in as many words ("close (A), measure, and report the
    remaining wrap rather than assuming (B) is still wanted").

    MEASURED, and it is the best of the available outcomes rather than merely a
    smaller one: Atlas photographed the tile at THREE lines and FOUR lines one
    minute apart. Post-(A) it sits at THREE in every lateral state -- so the
    abbreviation did not split the difference, it pinned the tile at the shorter
    of the two heights the driver was actually shown.
    """
    ordinary = _paintedDetail(0.30, 0.12)
    lines = _wrapLines(ordinary, column.width, column.detailPx, ADVANCE_OBSERVED)
    needed = _textPx(ordinary, column.detailPx, ADVANCE_OBSERVED)

    assert lines > 1, (
        f"RECORDED (US-631, post-(A)): the ordinary reading {ordinary!r} now fits "
        f"the {column.width}px column on ONE line ({needed:.1f}px needed). The "
        f"remaining wrap is gone and US-631 (B) can be withdrawn."
    )
    assert lines == 3, (
        f"RECORDED (US-631, post-(A)): the ordinary reading {ordinary!r} "
        f"({len(ordinary)} chars, {needed:.1f}px) wraps to {lines} lines in "
        f"{column.width}px, not the 3 recorded. Re-record this figure for "
        f"I-us631 before trusting the escalation."
    )


def test_recordTheHonestLimit_aWiderMAGNITUDEStillChangesTheLength():
    """
    Given: (A) fixed the varying LABEL, and deliberately nothing else
    When:  a reading crosses from one digit to two
    Then:  the string still gets LONGER -- stated, not hidden

    THE LIMIT OF THE CLAIM ABOVE, recorded so nobody reads the sweep as more than
    it is. The sweep shows no line count changes ANYWHERE in the current column
    at the current tier -- but that is the two extra characters landing inside a
    line box that happens to have room, not a property of the fix. The fix made
    the LABEL constant-width; it did not make the NUMBER constant-width, and it
    could not without lying about the reading.

    So the invariant is conditional on the layout: change `.live-g`'s width or
    `.tile-detail`'s tier and this length difference can start crossing a
    boundary again. That is precisely why the sweep is exhaustive and lives in
    the same file -- whoever lands US-631 (B) re-runs it, and it answers.
    """
    single = _view("liveCardView", _liveImu(0.30, 9.90), None, _nowMs())["g"]["detail"]
    double = _view("liveCardView", _liveImu(0.30, 10.00), None, _nowMs())["g"]["detail"]

    assert len(double) > len(single), (
        f"a two-digit magnitude no longer widens the line ({single!r} vs "
        f"{double!r}) -- if the number is being clamped or truncated that is a "
        f"different and more serious change than US-631 (A) made"
    )
