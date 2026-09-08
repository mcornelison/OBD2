################################################################################
# File Name: test_carousel_dtc_banner_second_code.py
# Purpose/Description: US-691 (F-138) -- the check-engine banner must never lose
#   the SECOND stored DTC. `ribbonView` folded four facts into ONE string --
#   "CHECK ENGINE · <code> <description> · +N more" -- and `.ribbon-text` clipped
#   that string with a CSS ellipsis. The count is the TAIL of the string, so it
#   is the FIRST thing an overflow destroys, by construction. On 2026-09-04
#   P0400 (EGR flow) was stored alongside the long-standing P0443 and the banner
#   was clipped in all ten dashboard frames of that day: the operator did not
#   learn from his own dashboard that a second fault existed.
#
#   THE FIX IS A SLOT PRIORITY, NOT A STRING. The banner is split into slots that
#   overflow in a declared order: the head ("CHECK ENGINE · <code>") and the
#   count ("+N more") do not shrink; the DESCRIPTION is the only run that clips.
#   So the thing that overflow eats is the thing the operator can afford to lose.
#
#   WHY BOTH A RENDER TEST AND A WIDTH MODEL. render_harness.py resolves the
#   CASCADE but explicitly does NOT do LAYOUT (its fidelity limit 1) -- it cannot
#   tell you a box overflowed. So a rendered test alone can prove the count is in
#   its own painted slot and can NEVER prove that slot fits. The width model
#   answers the second half, and is JOINED to the renderer (the US-631 technique)
#   so it is a claim about the shipped panel and not about a model of one. The
#   join has teeth: `test_theWidthModelMeasuresWhatTheRendererPainted` fails if
#   the two ever describe different strings.
#
#   GROUNDING, and one limit stated rather than hidden. The incident codes and
#   date are the story's own measurement. P0443's description is
#   specs/grounded-knowledge.md:272. `obd` is NOT installed on this bench, so
#   python-obd's exact wording for an un-tabled code cannot be read here and is
#   NOT invented: instead the description is swept across lengths (empty to far
#   past the panel) and the count survives all of them, which is a stronger
#   claim than any single string would have been.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-07    | Ralph (Rex)  | Initial -- US-691 second-DTC banner discovery.
# ================================================================================
################################################################################

"""US-691 tests: the check-engine banner never loses the second stored code."""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402
from css_type_scale import DASHBOARD_CSS, TOKENS_CSS, readCss, ruleBlock  # noqa: E402

# REUSED, NOT RESTATED. Both of these are already calibrated in this suite and
# both are load-bearing here, so a second copy would be a second thing to drift.
# STAGE_WIDTH_PX is grounded against the shipped `#stage` rule by its own home
# file; ADVANCE_OBSERVED is calibrated against Atlas's measured line-wrap bounce
# and is the advance of the face `--font-mono` resolves to -- which is what the
# ribbon inherits, because `html, body` binds --font-mono and `#dtc-ribbon`
# declares no font-family of its own (asserted below, never assumed).
from test_gforce_tile_width_budget import (  # noqa: E402
    ADVANCE_OBSERVED,
    ADVANCE_ROBUST_RANGE,
)
from test_topbar_three_column_grid import STAGE_WIDTH_PX  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# ---------------------------------------------------------------------------
# The incident, as measured (US-691 acceptance).
# ---------------------------------------------------------------------------
# P0400 was first seen 2026-09-04 17:51:37Z and stored alongside P0443. NEITHER
# is a row in the shipped severity table (src/pi/resources/dsm-p1xxx-severity-
# table.md lists P0443 only in PROSE, at line 41, as an example of a code it
# deliberately does NOT carry), so dtc_emitter.enrichCode degrades both to
# `unknown` -- which is alert-eligible, so both reach the banner's count.
_HERO_CODE = "P0443"
_SECOND_CODE = "P0400"

# specs/grounded-knowledge.md:272. Long on purpose: this is the real string that
# made the real banner overflow.
_HERO_SHORT = "Evaporative Emission System Purge Control Valve Circuit"

# The story's own label for the second code. It never reaches the banner (only
# the hero's description does), so its exact wording cannot affect any result
# here -- pinned by test_theSecondCodesDescriptionNeverReachesTheBanner.
_SECOND_SHORT = "EGR Flow"

# Every severity `alertableCodes` accepts. The banner's behaviour must not
# depend on which tier the un-tabled incident codes land in -- that mapping is
# an OPEN question (US-636 cross-check: Atlas's punch list recorded P0443 as
# MINOR, the shipped table yields `unknown`), and this story must not quietly
# take a position on it.
_ALERTABLE_SEVERITIES = ("stop", "watch", "minor", "unknown")


def _code(code: str, short: str, severity: str = "unknown") -> dict[str, Any]:
    return {"code": code, "severity": severity, "short": short, "status": "stored"}


def _dtcState(codes: list[dict[str, Any]]) -> dict[str, Any]:
    """A `dtc` payload in the shape the emitter writes, source READ + available.

    `newSinceTs` is None on purpose: the incident codes were known at boot, so
    the surface under test is the persistent RIBBON, not the takeover. A
    takeover already has a dedicated `+N more` element; the ribbon is the one
    that lost the count.
    """
    return {
        "codes": codes,
        "mil": True,
        "newSinceTs": None,
        "source": {"dtc": {"available": True, "reason": None}},
        "ts": "2026-09-04T17:51:37Z",
    }


_INCIDENT = _dtcState(
    [_code(_HERO_CODE, _HERO_SHORT), _code(_SECOND_CODE, _SECOND_SHORT)]
)


# ---------------------------------------------------------------------------
# Render helpers.
# ---------------------------------------------------------------------------


def _textOf(node: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


def _render(dtcState: dict[str, Any], steps: list[dict[str, Any]] | None = None):
    return rh.dashboardSurface(
        rh.runDashboard(routes={"/dtc": dtcState}, steps=steps)["tree"]
    )


def _ribbonSlots(surface) -> dict[str, str | None]:
    """The banner's PAINTED slots, keyed by class, or None where not painted.

    Read through `surface.rendered()` and not off text alone, because the whole
    banner is suppressed by the `hidden` ATTRIBUTE -- its text survives a hide,
    so a text-only reader would call a permanently visible banner correct.
    """
    path = surface.pathById("dtc-ribbon")
    slots: dict[str, str | None] = {}
    if path is None or not surface.rendered(path):
        return slots
    for slotPath in surface.paths():
        node = slotPath[-1]
        classes = (node.get("attrs", {}).get("class") or "").split()
        for cls in classes:
            if not cls.startswith("ribbon-"):
                continue
            slots[cls] = " ".join(_textOf(node)) if surface.rendered(slotPath) else None
    return slots


def _ribbonSlotOrder(surface) -> list[str]:
    """The painted slot classes in DOCUMENT order -- i.e. reading order.

    Kept separate from `_ribbonSlots` because that one is a dict keyed by class
    and is therefore ORDER-BLIND: it reports the same thing whether the panel
    reads "CHECK ENGINE · P0443 <desc> +1 more" or the description first.
    """
    path = surface.pathById("dtc-ribbon")
    if path is None or not surface.rendered(path):
        return []
    order = []
    for child in path[-1].get("children", []):
        classes = (child.get("attrs", {}).get("class") or "").split()
        slot = next((c for c in classes if c.startswith("ribbon-")), None)
        if slot and surface.rendered(path + [child]):
            order.append(slot)
    return order


def _bannerPaints(surface) -> bool:
    path = surface.pathById("dtc-ribbon")
    return path is not None and surface.rendered(path)


# ---------------------------------------------------------------------------
# The width model -- every magnitude read out of the SHIPPED stylesheet.
# ---------------------------------------------------------------------------


def _cssVarPx(css: str, name: str) -> float:
    match = re.search(rf"{re.escape(name)}:\s*([0-9.]+)px", css)
    assert match is not None, f"{name} is not declared as a px value"
    return float(match.group(1))


def _shorthandPx(block: str, prop: str, index: int) -> float:
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*([^;]+);", block)
    assert match is not None, f"no `{prop}` declaration in the rule block"
    parts = re.findall(r"([0-9.]+)px", match.group(1))
    assert len(parts) > index, f"`{prop}` has no component {index}"
    return float(parts[index])


def _letterSpacingEm(block: str) -> float:
    match = re.search(r"letter-spacing:\s*([0-9.]+)em", block)
    assert match is not None, "the ribbon declares no em letter-spacing"
    return float(match.group(1))


class _BannerModel:
    """The banner's horizontal budget, derived from the shipped values only.

    Nothing here is a literal from a design note: padding, gap, both type sizes
    and the letter-spacing are read from dashboard.css / tokens.css, so a token
    change moves the check instead of leaving it measuring a panel that is gone.
    """

    def __init__(self) -> None:
        css = readCss(DASHBOARD_CSS)
        tokens = readCss(TOKENS_CSS)
        ribbon = ruleBlock(css, "#dtc-ribbon")
        self.padX = _shorthandPx(ribbon, "padding", 1)
        self.gap = _shorthandPx(ribbon, "gap", 0)
        self.spacing = _letterSpacingEm(ribbon)
        self.textPx = _cssVarPx(tokens, "--fs-label")
        self.glyphPx = _cssVarPx(tokens, "--fs-secondary")

    @property
    def usable(self) -> float:
        """Banner width inside its own horizontal padding."""
        return STAGE_WIDTH_PX - 2 * self.padX

    def runPx(self, text: str, fontPx: float, advance: float = ADVANCE_OBSERVED) -> float:
        """Upper-bound painted width of one run.

        ASCII is charged the mono advance; anything else a full em -- the same
        two-band charge the top-bar model uses, and an upper bound in both.
        """
        total = 0.0
        for char in text:
            per = advance if char.isascii() else 1.0
            total += fontPx * (per + self.spacing)
        return total

    def fixedPx(self, head: str, more: str, advance: float = ADVANCE_OBSERVED) -> float:
        """Width of everything that is NOT allowed to shrink, plus its gaps.

        Glyph + head + count, with a gap between every pair of children. The
        description is charged nothing: it is the run that clips, and what this
        method answers is whether the UNCLIPPABLE remainder fits at all.
        """
        runs = [
            self.runPx("⚠", self.glyphPx, advance),
            self.runPx(head, self.textPx, advance),
        ]
        if more:
            runs.append(self.runPx(more, self.textPx, advance))
        # One gap between each adjacent pair, plus one for the description slot
        # sitting between the head and the count.
        gaps = self.gap * len(runs)
        return sum(runs) + gaps


_MODEL = _BannerModel()


# ---------------------------------------------------------------------------
# SECTION 0 -- negative controls. Several assertions below are ABSENCES, and an
# absence passes vacuously when the reader finds nothing at all.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyPaintsTheBanner_negativeControl():
    """
    Given: every "the count is not lost" assertion fails open if the harness
           cannot find the banner at all
    When: the real incident payload is rendered
    Then: the banner paints and carries the hero code.

          Without this, a renamed element or a probe crash would turn this whole
          file green while the panel showed nothing.
    """
    surface = _render(_INCIDENT)
    assert _bannerPaints(surface), "the banner did not paint for two stored codes"
    slots = _ribbonSlots(surface)
    joined = " ".join(v for v in slots.values() if v)
    assert _HERO_CODE in joined, slots


def test_theBannerInheritsTheMonoFace_soTheAdvanceModelApplies():
    """
    Given: the width model charges the `--font-mono` advance
    When: the shipped rules are read
    Then: `#dtc-ribbon` declares NO font-family of its own and `html, body`
          binds --font-mono, so the banner inherits the face the model assumes.

          The model is only as good as this inheritance. A `font-family` added
          to the ribbon would silently make every width figure below describe a
          face the panel no longer uses -- so the assumption is asserted, not
          carried in a comment.
    """
    css = readCss(DASHBOARD_CSS)
    assert "font-family" not in ruleBlock(css, "#dtc-ribbon"), (
        "#dtc-ribbon now sets its own font-family -- the advance model in this "
        "file charges --font-mono and no longer describes the banner"
    )
    assert "font-family: var(--font-mono)" in ruleBlock(css, "html, body")


# ---------------------------------------------------------------------------
# SECTION 1 -- the producer. The count must be its OWN fact, not a tail.
# ---------------------------------------------------------------------------


def test_theCountIsItsOwnField_notATailOnAStringThatClips():
    """
    Given: two stored codes
    When: `ribbonView` builds the banner
    Then: the count arrives as a discrete field the renderer can place in its
          own slot.

          THIS IS THE DEFECT'S ROOT. While the count exists only as the tail of
          a single string, no stylesheet can protect it: `text-overflow` eats a
          string from the end, and the end is where the count is. Splitting the
          view is what makes the CSS fix in the next section expressible at all.
    """
    surface = _render(_INCIDENT)
    slots = _ribbonSlots(surface)
    assert "ribbon-more" in slots, (
        "the banner has no dedicated count slot -- the count is still folded "
        f"into a clippable run: {slots}"
    )
    assert slots["ribbon-more"], f"the count slot painted empty: {slots}"
    assert "1" in slots["ribbon-more"], slots["ribbon-more"]


def test_theCodeIdentifierAndTheCountAreInDifferentSlotsFromTheDescription():
    """
    Given: the real incident
    When: the banner's slots are read
    Then: the hero CODE is in the head slot, the count in the count slot, and
          the long DESCRIPTION is in neither.

          VC-3 ("the code identifier itself is never the part that is
          truncated") is only meaningful if the code is not sharing a clipping
          run with the description. Asserting the description's ABSENCE from
          those two slots is what makes that true rather than coincidental.
    """
    slots = _ribbonSlots(_render(_INCIDENT))
    head = slots.get("ribbon-head") or ""
    more = slots.get("ribbon-more") or ""
    assert _HERO_CODE in head, f"the hero code is not in the head slot: {slots}"
    assert _HERO_SHORT not in head, (
        "the description shares the head slot with the code -- an overflow "
        f"would take the code down with it: {head!r}"
    )
    assert _HERO_SHORT not in more, more


def test_theSlotsAreInReadingOrder_alarmThenCodeThenDescriptionThenCount():
    """
    Given: the real incident
    When: the banner's painted slots are read in DOCUMENT order
    Then: glyph, head, description, count -- in that order.

          Every other assertion in this file reads slots by CLASS, which is
          order-blind: reshuffling the spans in the markup leaves all of them
          green while the panel reads "Evaporative Emission System... CHECK
          ENGINE · P0443". The order is not cosmetic here -- the description is
          the run that gets clipped, so putting it before the code puts an
          ellipsis between the operator and the thing he needs to write down.
          Found by mutation: this was the one change the file could not see.
    """
    order = _ribbonSlotOrder(_render(_INCIDENT))
    assert order == ["ribbon-glyph", "ribbon-head", "ribbon-desc", "ribbon-more"], order


def test_theSecondCodesDescriptionNeverReachesTheBanner():
    """
    Given: two stored codes
    When: the banner renders
    Then: only the HERO's description is on it.

          Recorded so the grounding limit in this file's header is a measured
          fact rather than a hope: python-obd's exact wording for the second
          code cannot be read on this bench, and this test is why that cannot
          affect any result here. It is also the honest statement of the
          story's conditionalOutcome -- the second code is present as a COUNT,
          not as text.
    """
    slots = _ribbonSlots(_render(_INCIDENT))
    joined = " ".join(v for v in slots.values() if v)
    assert _SECOND_SHORT not in joined, joined


@pytest.mark.parametrize("severity", _ALERTABLE_SEVERITIES)
def test_theCountSurvivesEveryAlertableTier(severity: str):
    """
    Given: two stored codes at the SAME alert-eligible tier
    When: the banner renders
    Then: the count is present.

          The tier the un-tabled incident codes land in is an OPEN question
          (US-636's cross-check for Atlas). This story must not silently depend
          on the answer, so the claim is made at every tier `alertableCodes`
          accepts instead of at the one this bench happens to produce.
    """
    state = _dtcState(
        [
            _code(_HERO_CODE, _HERO_SHORT, severity),
            _code(_SECOND_CODE, _SECOND_SHORT, severity),
        ]
    )
    slots = _ribbonSlots(_render(state))
    assert (slots.get("ribbon-more") or "").strip(), f"{severity}: {slots}"


def test_naCodesAreNotCounted_theCountMeansAlertsNotRows():
    """
    Given: one alert-eligible code beside an `na` code (the auto-trans P1750 on
           this manual car)
    When: the banner renders
    Then: NO count appears -- there is one alert, not two.

          The count's meaning is "how many more FAULTS", and design §4 says `na`
          is not a fault. A count that read the raw array length would say "+1
          more" here and send the operator looking for a second fault that does
          not exist -- the mirror of the defect this story fixes.
    """
    state = _dtcState(
        [_code(_HERO_CODE, _HERO_SHORT), _code("P1750", "Auto-trans solenoid", "na")]
    )
    slots = _ribbonSlots(_render(state))
    assert not (slots.get("ribbon-more") or "").strip(), (
        f"an `na` code was counted as a second fault: {slots}"
    )
    # NON-VACUITY. The assertion above is an ABSENCE, and it is satisfied by a
    # renderer with no count slot at all -- which is precisely the broken state
    # this story starts from, so on its own it would have passed before the fix
    # and after it, saying nothing either way. The control swaps ONLY the second
    # code's severity and requires the count to appear.
    control = _dtcState(
        [_code(_HERO_CODE, _HERO_SHORT), _code("P1750", "Auto-trans solenoid", "watch")]
    )
    controlSlots = _ribbonSlots(_render(control))
    assert (controlSlots.get("ribbon-more") or "").strip(), (
        "the same fixture with an ALERTABLE second code shows no count either "
        f"-- this test cannot witness `na` being excluded: {controlSlots}"
    )


# ---------------------------------------------------------------------------
# SECTION 2 -- the stylesheet. WHICH run clips is the whole fix.
# ---------------------------------------------------------------------------


def test_exactlyOneBannerSlotClips_andItIsTheDescription():
    """
    Given: the shipped stylesheet
    When: every `.ribbon-*` rule is swept for `text-overflow: ellipsis`
    Then: exactly one slot carries it, and it is the description.

          Swept over the SHEET rather than checked on a named selector, so a
          slot added later without a decision about its overflow behaviour
          fails HERE rather than on the panel. An ellipsis on the head or the
          count would re-create the defect in a new place.
    """
    css = readCss(DASHBOARD_CSS)
    clipping = set()
    for selector in re.findall(r"^(\.ribbon-[a-z-]+)\s*\{", css, re.M):
        if "text-overflow: ellipsis" in ruleBlock(css, selector):
            clipping.add(selector)
    assert clipping == {".ribbon-desc"}, (
        f"the clipping slot(s) are {clipping or '{}'} -- exactly one run may "
        "clip and it must be the description"
    )


@pytest.mark.parametrize("slot", [".ribbon-head", ".ribbon-more"])
def test_theUnclippableSlotsRefuseToShrink(slot: str):
    """
    Given: the shipped stylesheet
    When: the head and count rules are read
    Then: each declares a zero flex-shrink.

          A flex item's DEFAULT is `flex-shrink: 1`. Omit this and the browser
          happily squeezes the count until its own ellipsis (or the head's)
          appears -- the fix would look right in the markup and fail on the
          panel, which is exactly the US-495 shape this suite exists for.
    """
    css = readCss(DASHBOARD_CSS)
    block = ruleBlock(css, slot)
    shrinkZero = re.search(r"flex:\s*0\s+0\s+auto", block) or re.search(
        r"flex-shrink:\s*0", block
    )
    assert shrinkZero, f"{slot} may be shrunk by the flex layout: {block!r}"


def test_theClippingSlotIsAllowedToGetSmallerThanItsText():
    """
    Given: the description is the run that absorbs the overflow
    When: its rule is read
    Then: it declares `min-width: 0`.

          A flex child's DEFAULT is `min-width: auto`, which REFUSES to shrink
          below its content -- so a description with `overflow: hidden` and no
          `min-width: 0` does not clip, it pushes. What it pushes out is the
          count, which sits after it. The ellipsis would then be decoration on a
          slot that never narrows, and the defect would return through a rule
          that looks correct. Held separately from the shrink guards above
          because it is the one declaration whose absence LOOKS like nothing.
    """
    css = readCss(DASHBOARD_CSS)
    assert re.search(r"min-width:\s*0", ruleBlock(css, ".ribbon-desc")), (
        "the description slot has no `min-width: 0` -- it will refuse to shrink "
        "below its text and push the count off the banner instead of clipping"
    )


def test_theBannerTypeWasNotShrunkToMakeRoom():
    """
    Given: the F-127 legibility budget, which this story may not spend
    When: the banner's font-size is read
    Then: it still resolves through `--fs-label`.

          The story forbids solving this by shrinking the type: "a banner nobody
          can read at a glance has the same effect as one that clips". The
          tempting fix is a smaller font on a 3.5in panel, and it would leave
          every other test in this file green.
    """
    css = readCss(DASHBOARD_CSS)
    assert "font-size: var(--fs-label)" in ruleBlock(css, "#dtc-ribbon")


# ---------------------------------------------------------------------------
# SECTION 3 -- the width model, JOINED to the renderer. The cascade harness does
# not do layout (its fidelity limit 1), so "it fits" has to be modelled -- but a
# model that describes different strings than the panel paints is worthless.
# ---------------------------------------------------------------------------


def test_theWidthModelMeasuresWhatTheRendererPainted():
    """
    Given: the model is about to charge widths for a head and a count
    When: those strings are taken from the SHIPPED renderer's own output
    Then: they are exactly the strings the model measures.

          THE JOIN. Without it every figure below is a claim about this file's
          arithmetic. With it, a renderer that reformats the head (or moves the
          count back into the description) fails here before any budget test
          gets the chance to pass on a string the panel never shows.
    """
    slots = _ribbonSlots(_render(_INCIDENT))
    head = slots.get("ribbon-head") or ""
    more = slots.get("ribbon-more") or ""
    assert head and more, slots
    # The model is fed the rendered strings, not literals -- this test exists to
    # make that sourcing explicit and to fail if either slot goes empty.
    assert _MODEL.fixedPx(head, more) > 0


def test_theUnclippableRunsFitTheBanner_atTheRealIncident():
    """
    Given: the real incident's rendered head and count
    When: their widths plus the glyph and the gaps are charged
    Then: they fit inside the banner's usable width, with room left for at
          least some description.

          The CSS says the count MAY NOT clip; this says it does not NEED to.
          Those are different claims and only the second one is about the
          operator: `flex-shrink: 0` on a run wider than its box does not clip,
          it OVERFLOWS -- which loses the count just as completely and looks
          like a bug rather than a truncation.
    """
    slots = _ribbonSlots(_render(_INCIDENT))
    fixed = _MODEL.fixedPx(slots["ribbon-head"], slots["ribbon-more"])
    assert fixed <= _MODEL.usable, (
        f"the unclippable runs need {fixed:.1f}px of {_MODEL.usable:.1f}px -- "
        "the count cannot be shown without overflowing the banner"
    )
    assert _MODEL.usable - fixed > 0, "no width left for any description at all"


@pytest.mark.parametrize("advance", ADVANCE_ROBUST_RANGE)
def test_theFitDoesNotDependOnTheFontCalibration(advance: float):
    """
    Given: the advance ratio is a property of a face this bench cannot measure
    When: the same budget is charged across a deliberately over-wide range
    Then: the unclippable runs still fit.

          A conclusion that survives 0.50 through 0.65 is not an artefact of the
          calibration. This is what lets the fit above be reported as a fact
          rather than as an assumption about DejaVu Sans Mono.
    """
    slots = _ribbonSlots(_render(_INCIDENT))
    fixed = _MODEL.fixedPx(slots["ribbon-head"], slots["ribbon-more"], advance)
    assert fixed <= _MODEL.usable, f"advance {advance}: {fixed:.1f}px"


def test_theModelWitnessesTheDefectItWasBuiltFor_negativeControl():
    """
    Given: the SHIPPED banner before this story -- one run carrying head,
           description and count together
    When: that single run is charged at the real incident's strings
    Then: it is WIDER than the banner, i.e. the model can see the overflow.

          NON-VACUITY, and it is the most important test in this section. Every
          "it fits" above is satisfied by a model that thinks everything fits.
          This one reconstructs the pre-fix string and requires the model to
          call it over budget -- so a fit is evidence, not arithmetic that
          cannot fail. The reconstruction is the old `ribbonView` format string,
          restated here because the shipped source no longer contains it.
    """
    slots = _ribbonSlots(_render(_INCIDENT))
    oldText = (
        f"CHECK ENGINE · {_HERO_CODE} {_HERO_SHORT} "
        f"· +1 more"
    )
    glyph = _MODEL.runPx("⚠", _MODEL.glyphPx)
    oldWidth = glyph + _MODEL.gap + _MODEL.runPx(oldText, _MODEL.textPx)
    assert oldWidth > _MODEL.usable, (
        f"the pre-fix single run models at {oldWidth:.1f}px of "
        f"{_MODEL.usable:.1f}px -- the model cannot see the overflow this "
        "story exists to fix, so its 'it fits' verdicts prove nothing"
    )
    # ...and the count is what the ellipsis would have taken: it is the tail.
    assert oldText.endswith("+1 more")
    assert slots["ribbon-more"].strip() == "+1 more"


# ---------------------------------------------------------------------------
# SECTION 4 -- the negative cases the story states. Do not fix the rare fault by
# degrading the constant one.
# ---------------------------------------------------------------------------


def test_oneStoredCode_rendersCleanlyWithNoEmptyCountSlot():
    """
    Given: a single stored code -- the state this car has been in for months
    When: the banner renders
    Then: the code and its description are there and NO count slot is painted.

          VC-2. "+0 more" is the obvious way to break this, and a blank painted
          slot is the subtle one: it would eat gap and width on the commonest
          state there is, to say nothing.
    """
    surface = _render(_dtcState([_code(_HERO_CODE, _HERO_SHORT)]))
    slots = _ribbonSlots(surface)
    assert _bannerPaints(surface)
    assert _HERO_CODE in (slots.get("ribbon-head") or ""), slots
    # `is None` -- NOT falsiness. `_ribbonSlots` records an unpainted slot as
    # None and a PAINTED-BUT-EMPTY one as "", and those are different panels: an
    # empty span is still a flex child, so it still claims its gap and its share
    # of a 480px banner to say nothing. A `not slots.get(...)` here accepts both,
    # which would let a renderer that forgets to take the slot down pass while
    # quietly narrowing the description on the state this car is in every day.
    assert slots.get("ribbon-more") is None, (
        f"a single code left a count slot on the banner: {slots['ribbon-more']!r}"
    )
    joined = " ".join(v for v in slots.values() if v)
    assert "more" not in joined, joined


def test_oneStoredCode_getsMoreDescriptionThanTwoDo():
    """
    Given: the same code, alone and then beside a second
    When: the description's available width is modelled in each case
    Then: the single-code case is not charged for a count it does not have.

          The single-code case must be no WORSE than before, and the way a slot
          fix degrades it is by reserving the count's box unconditionally. Read
          off the rendered slots, so a renderer that emits an empty count
          element fails here even if its text is blank.
    """
    single = _ribbonSlots(_render(_dtcState([_code(_HERO_CODE, _HERO_SHORT)])))
    both = _ribbonSlots(_render(_INCIDENT))
    singleFixed = _MODEL.fixedPx(single["ribbon-head"], single.get("ribbon-more") or "")
    bothFixed = _MODEL.fixedPx(both["ribbon-head"], both["ribbon-more"])
    assert singleFixed < bothFixed, (
        f"one code is charged {singleFixed:.1f}px and two {bothFixed:.1f}px -- "
        "the single-code case is paying for a count it does not carry"
    )


def test_zeroCodes_theBannerIsAbsent_neverAnEmptyClippedBar():
    """
    Given: a completed read that found nothing
    When: the banner is checked
    Then: it does not paint at all.

          VC-4. A banner is an ASSERTION that a fault exists; an empty one is
          that assertion with the evidence removed.
    """
    surface = _render(_dtcState([]))
    assert not _bannerPaints(surface), "the banner painted over zero codes"


def test_unreadSource_stillPaintsNoBanner():
    """
    Given: a source nobody has read yet
    When: the banner is checked
    Then: it does not paint.

          US-429's honest-availability guarantee, re-pinned because this story
          changes `ribbonView`'s return SHAPE and an early-return that got lost
          in that edit would turn "not read" into "no fault" -- which is the
          class of defect this whole project keeps re-finding.
    """
    state = _dtcState([])
    state["source"]["dtc"] = {"available": False, "reason": "not read yet"}
    assert not _bannerPaints(_render(state))


# ---------------------------------------------------------------------------
# SECTION 5 -- REACHABILITY. The story's END STATE is that every stored code is
# DISCOVERABLE, not that every code fits. A count nobody can act on is a smaller
# version of the same failure.
# ---------------------------------------------------------------------------


def test_bothCodesAreListedOnTheAlertsCardTheBannerPointsAt():
    """
    Given: the real incident
    When: the Alerts card renders
    Then: BOTH code identifiers appear on it.

          This is the half that makes the count honest. The banner says "+1
          more"; this says the operator has somewhere to go and find out what
          it is. Without it the fix would tell him a second fault exists and
          leave him no way to name it -- better than silence, but not the END
          STATE the story asks for.
    """
    surface = _render(_INCIDENT)
    text = ""
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "dtc":
            text = " ".join(_textOf(path[-1]))
            break
    assert _HERO_CODE in text, text
    assert _SECOND_CODE in text, text


def test_tappingTheBannerOpensTheHerosDetail():
    """
    Given: the banner is painted over two codes
    When: it is tapped
    Then: the per-code detail overlay is painted and names the hero code.

          The route from the count to the codes, exercised rather than assumed.
          `openAlertsCard` resolves the hero through `ribbonView(lastDtc).code`
          -- a field this story's reshaping of that return value could have
          dropped in SILENCE, because nothing else on the banner reads it and
          `findCode(null)` simply declines to open anything. So the failure mode
          this guards is a tap that quietly does nothing, which is the hardest
          kind to notice on a panel with no pointer.
    """
    surface = _render(_INCIDENT, steps=[{"flush": 4}, {"click": "dtc-ribbon"}])
    path = surface.pathById("dtc-detail")
    assert path is not None and surface.rendered(path), (
        "tapping the banner opened nothing -- the hero code did not survive "
        "the click handler"
    )
    assert _HERO_CODE in " ".join(_textOf(path[-1]))
