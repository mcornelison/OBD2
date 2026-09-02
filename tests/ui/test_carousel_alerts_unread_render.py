################################################################################
# File Name: test_carousel_alerts_unread_render.py
# Purpose/Description: US-629 (F-138, punch-list 2.1) -- RECORD THE PASS on the
#   Alerts card's unread-vs-no-faults distinction, on the RENDERED SURFACE.
#
#   WHY A NEW FILE WHEN US-429/US-542 ALREADY TESTED THIS. They pinned the
#   unread path (`alertsCardView` returns a typed NA; the card body shows the
#   moved "DTC not read - since key-off" line). What NOBODY pinned is the OTHER
#   direction on the surface: that a GENUINE all-clear actually renders. Today
#   "No stored codes" appears in the suite exactly once, as an ABSENCE
#   (test_carousel_idle_face_retirement.py, over an unread source). An absence
#   assertion cannot tell a correct renderer from one that prints nothing, so a
#   regression that silently dropped the all-clear line would leave the whole
#   existing DTC suite green. That asymmetry is the hole this file closes.
#
#   THE LIVE SHAPE IS USED VERBATIM, and that is the point of the story. Atlas
#   measured mil:false + codes:[] sitting BESIDE source.dtc.available:false while
#   P0443 was stored and the MIL was lit. The two states are told apart ONLY by
#   the source block -- both carry an empty array and both carry mil:false -- so
#   the fixtures here carry `mil` explicitly rather than omitting it, which is
#   what the pre-existing `_dtcUnread()` fixture does.
#
#   FINDING RECORDED, NOT FIXED (sprint contract: a VERIFY story that finds a
#   defect RECORDS it and FILES a fix story, it never quietly becomes the fix):
#   `alertsCardView` computes `mil` at carousel.js:2086 and NOTHING consumes it.
#   The panel has no MIL indicator at all. Filed as offices/pm/issues/I-us629-*.
#   It is NOT a false all-clear -- an absent lamp claims nothing -- so it is out
#   of this story's END STATE, and it is pinned below as a CHARACTERISATION so
#   the day someone wires the lamp up, they are told this file has an opinion.
#
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-629 punch-list 2.1 recorded pass.
# 2026-08-31    | Ralph (Rex)  | Closed criterion 3: pinned the P0443 read path on
#               |              | BOTH surfaces it can mean -- the card hero (code,
#               |              | tier chip, directive, count line) and the #dtc-
#               |              | ribbon banner, incl. the ribbon's unread case.
# ================================================================================
################################################################################

"""US-629 tests: the Alerts card never paints an unread DTC state as all-clear."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The two claims, named so each is pinned in BOTH directions rather than only
# in the one the original defect happened to point at.
_UNREAD_VALUE = "DTC not read"
_ALL_CLEAR = "No stored codes"


def _dtcState(available: bool, reason: str | None, codes: list[dict[str, Any]]) -> dict:
    """A `dtc` payload in the shape the emitter actually writes.

    `mil` and `codes` are ALWAYS present and always the same on both sides of
    the distinction -- that is the whole hazard. Only `source.dtc.available`
    separates "we read, and it was clean" from "nothing has read yet".
    """
    return {
        "codes": codes,
        "mil": any(c.get("severity") in ("stop", "watch", "minor") for c in codes),
        "newSinceTs": None,
        "source": {"dtc": {"available": available, "reason": reason}},
        "ts": "2026-08-31T15:54:00Z",
    }


def _renderedAlertsText(dtcState: dict) -> str:
    """Boot the SHIPPED carousel.js over the SHIPPED markup; return card text.

    Composed on purpose. A correct `alertsCardView` proves nothing about what
    the operator reads -- US-494/495/498 were all two-correct-halves defects
    that every pure unit test passed, which is why render_harness.py exists.
    """
    surface = _renderDtc(dtcState)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == "dtc":
            return " ".join(_textOf(path[-1]))
    return ""


def _renderDtc(dtcState: dict):
    """One boot of the shipped dashboard over `dtcState`; return the surface."""
    return rh.dashboardSurface(rh.runDashboard(routes={"/dtc": dtcState})["tree"])


def _ribbon(dtcState: dict) -> tuple[bool, str]:
    """The persistent alert banner as (doesItPaint, itsText).

    Read through `surface.rendered()` rather than off the text alone, because
    the ribbon is suppressed by the `hidden` ATTRIBUTE, not by emptying it --
    its text survives a hide. Asserting on text only would have called a
    permanently-visible ribbon correct.
    """
    surface = _renderDtc(dtcState)
    path = surface.pathById("dtc-ribbon")
    if path is None:
        return (False, "")
    return (surface.rendered(path), " ".join(_textOf(path[-1])))


def _textOf(node: dict) -> list[str]:
    out = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


# ---------------------------------------------------------------------------
# The probe gets its negative control FIRST. Two of the three assertions below
# are ABSENCES, and an absence passes vacuously when the harness silently
# returns "" -- a broken reader and a correct renderer are indistinguishable.
# ---------------------------------------------------------------------------


def test_theHarnessActuallyReadsTheAlertsCard_negativeControl():
    """
    Given: every "must not say X" assertion in this file fails open if the
           harness cannot find the card at all
    When: a payload with a known, unmistakable code is rendered
    Then: that code is in the text.

          Without this, a renamed `data-state` or a probe crash would turn the
          whole file green while pinning nothing.
    """
    text = _renderedAlertsText(
        _dtcState(True, None, [{"code": "P0301", "severity": "stop", "short": "Misfire"}])
    )
    assert "P0301" in text, f"harness read nothing from the Alerts card: {text!r}"


# ---------------------------------------------------------------------------
# END STATE, direction 1 -- available:false renders UNREAD, never an all-clear.
# ---------------------------------------------------------------------------


def test_alertsCard_unreadSourceWithMilFalse_rendersUnreadWithItsReason():
    """
    Given: the EXACT live state Atlas measured -- mil:false, codes:[], beside
           source.dtc.available:false, reason "not read yet"
    When: the shipped card renders it
    Then: the operator reads "DTC not read" AND the emitter's reason.

          The pre-existing fixture for this path omits `mil` entirely. That is
          a weaker test than the defect deserves: the danger is precisely that
          a renderer reaches for the mil flag FIRST and paints a clean lamp
          from a field nobody has populated. Carrying mil:false explicitly is
          what makes this a pin on the measured state rather than on a
          convenient one.
    """
    text = _renderedAlertsText(_dtcState(False, "not read yet", []))
    assert _UNREAD_VALUE in text, text
    assert "not read yet" in text, text


def test_alertsCard_unreadSource_neverRendersTheAllClear():
    """
    Given: the same unread state
    When: the card body is read
    Then: "No stored codes" is absent.

          Unknown is not clear. mil:false + codes:[] is EXACTLY what a clean
          read looks like, so the all-clear is one dropped source check away at
          all times -- and it is the assertion the driver acts on.
    """
    text = _renderedAlertsText(_dtcState(False, "not read yet", []))
    assert _ALL_CLEAR not in text, text


# ---------------------------------------------------------------------------
# END STATE, direction 2 -- available:true DOES earn the all-clear. THE HALF
# THAT WAS MISSING: the suite could not previously tell a correct renderer from
# one that had stopped printing the all-clear altogether.
# ---------------------------------------------------------------------------


def test_alertsCard_genuineEmptyRead_rendersTheEarnedAllClear():
    """
    Given: a real key-on read that completed and found nothing
    When: the card renders
    Then: it says "No stored codes" -- and does NOT borrow the unread line.

          This is the pin in the direction nobody had pinned. Suppressing the
          all-clear is the mirror-image lie: it tells the driver to go read
          codes that were already read, and it would have shipped green.
    """
    text = _renderedAlertsText(_dtcState(True, None, []))
    assert _ALL_CLEAR in text, text
    assert _UNREAD_VALUE not in text, text


# ---------------------------------------------------------------------------
# END STATE, direction 3 -- the READ path with a real stored code. The punch
# list reports this rendered correctly in-car (2.2), so this is a recorded pass.
#
# P0443 is GROUNDED, not invented (specs/grounded-knowledge.md:149) -- EVAP
# purge control valve circuit, MIL lit since 2026-08-20, "no engine risk",
# emissions-only. That is the `minor` tier, which carries chip "MINOR", level
# "minor" and directive "SAFE TO CLEAR ONCE LOGGED" (carousel.js:1967).
#
# WHICH FACTS OF THE HERO ARE PINNED, and why the rest deliberately are not.
# The hero block carries four fields (chip, code, short, directive). Pinning all
# four would make this a change-detector on a fixture; pinning none would leave
# criterion 3 unrecorded. The line drawn here is WHAT THE DRIVER ACTS ON:
#
#   PINNED  code       -- the identity of the fault. It needs a pin of its own
#                         and cannot lean on the negative control in the
#                         characterisation test below: that test is DESIGNED to
#                         be deleted the day a MIL lamp is wired up (I-us629),
#                         and it would take the only P0443 render-pin with it.
#   PINNED  chip +     -- the tier, and the tier is the safety claim. P0443 is
#           directive     emissions-only with "no engine risk"; mis-tiered as
#                         `stop` the SAME payload prints "REDUCE LOAD · PULL
#                         OVER". That is the F-1/S-4 invariant reaching the
#                         operator, and it is the one thing here that can hurt.
#   PINNED  the count  -- "1 stored · 0 pending" is how the card SAYS the read
#           line          completed and found something. It is the direction-3
#                         counterpart to the all-clear.
#   NOT     short      -- straight payload passthrough. Pinning it asserts that
#                         the fixture equals the fixture.
#   NOT     DOM shape  -- class names and element order are Iris's to change.
#                         A test that fails on a re-skin trains people to edit
#                         tests, which is how a real pin gets weakened.
# ---------------------------------------------------------------------------

# P0443 exactly as the emitter carries it -- `minor`, per grounded-knowledge.
_P0443 = {"code": "P0443", "severity": "minor", "short": "EVAP purge control valve circuit"}


def test_alertsCard_storedMinorCode_rendersTheHeroWithItsTierAndDirective():
    """
    Given: a completed read carrying the real stored P0443, MIL lit
    When: the shipped card renders it
    Then: the operator reads the code, its MINOR tier and the tier's directive.

          Criterion 3, on the card. The directive is the assertion with teeth:
          it is derived from `severity` alone, so this pin fails the moment the
          tier mapping drifts -- which would tell the driver to pull over for an
          emissions code, or to keep driving on one that means stop.
    """
    text = _renderedAlertsText(_dtcState(True, None, [_P0443]))
    assert "P0443" in text, text
    assert "MINOR" in text, text
    assert "SAFE TO CLEAR ONCE LOGGED" in text, text


def test_alertsCard_storedCode_saysTheReadCompleted_neitherUnreadNorAllClear():
    """
    Given: the same stored-code state
    When: the card is read
    Then: the count line reports 1 stored / 0 pending, and NEITHER the unread
          line NOR the all-clear appears.

          This is THIS STORY's invariant applied to the read path. Directions 1
          and 2 pin that the two empty-codes states stay apart; nothing pinned
          that a card with a REAL CODE ON IT cannot also claim it was never
          read. Both borrowings are individually reachable -- the unread line
          from a dropped source check, the all-clear from a hero/rows
          disagreement -- and either one prints a contradiction.
    """
    text = _renderedAlertsText(_dtcState(True, None, [_P0443]))
    assert "1 stored · 0 pending" in text, text
    assert _UNREAD_VALUE not in text, text
    assert _ALL_CLEAR not in text, text


# ---------------------------------------------------------------------------
# ...and on the OTHER surface criterion 3 can mean. "Banner" is the ribbon:
# `#dtc-ribbon`, the persistent strip above the carousel (design §5.2). It is a
# separate renderer from the card and can fail independently of it, so the
# criterion is closed on both rather than on whichever one was meant.
# ---------------------------------------------------------------------------


def test_ribbon_storedMinorCode_rendersTheCheckEngineBannerForThatCode():
    """
    Given: the stored P0443
    When: the ribbon renders
    Then: it PAINTS, and names CHECK ENGINE and the code.
    """
    painted, text = _ribbon(_dtcState(True, None, [_P0443]))
    assert painted, "the ribbon did not paint for a live stored code"
    assert "CHECK ENGINE" in text, text
    assert "P0443" in text, text


def test_ribbon_unreadSource_doesNotPaint():
    """
    Given: the unread state -- mil:false, codes:[], available:false
    When: the ribbon is checked
    Then: it does not paint.

          The mirror of the card's rule on the banner surface. An unread source
          carries no known fault, and a ribbon is an ASSERTION that one exists;
          raising it over a source nobody has read is the same fabrication as
          the all-clear, pointing the other way.
    """
    painted, _ = _ribbon(_dtcState(False, "not read yet", []))
    assert not painted, "the ribbon asserted a fault over a source nobody read"


# ---------------------------------------------------------------------------
# CHARACTERISATION of the finding, not a fix (see the header + I-us629).
# ---------------------------------------------------------------------------


def test_theMilFlagIsComputedButNeverRendered_characterisation():
    """
    Given: `alertsCardView` computes `mil` (carousel.js:2086) and no renderer
           reads it -- the panel has no MIL indicator
    When: a state with the MIL LIT is rendered
    Then: nothing on the card says so. RECORDED, not fixed (I-us629).

          This is deliberately a characterisation and not an assertion that the
          behaviour is right. It is not a false all-clear -- an absent lamp
          claims nothing, so it is outside this story's END STATE -- but it IS
          a fact the punch list's "the MIL has been LIT since 2026-08-20"
          depends on. Whoever wires the lamp up will fail this test, which is
          the moment to read I-us629 and delete this test on purpose.
    """
    text = _renderedAlertsText(
        _dtcState(True, None, [{"code": "P0443", "severity": "minor", "short": "EVAP purge"}])
    )
    assert "P0443" in text, "negative control: the code itself DOES render"
    assert "MIL" not in text, text
