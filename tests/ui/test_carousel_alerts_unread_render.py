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
#   MOVED PIN (US-898-b1): the ALERTS card now renders states/alerts
#   (#alerts-card), not the dtc payload. Its cases are re-pointed: unread is
#   the provider's null `sources.code.checkedAtTs` ('codes not read yet'), and
#   a stored P0443 is its MINOR chip and the PROVIDER'S sentence (the page's
#   tier directive retired with the hero). The earned all-clear is US-898-b2's
#   (NONE / NO WARNINGS) and leaves this file. The ribbon still reads states/dtc
#   until US-899-a2, so its two cases are unchanged.
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
# 2026-10-20    | Ralph (Rex)  | US-898-b1 -- MOVED PIN: the card renders states/alerts;
#               |              | its cases re-pointed, the earned all-clear retired.
# ================================================================================
################################################################################

"""US-629 tests: the Alerts card never paints an unread DTC state as all-clear."""

from __future__ import annotations

import copy
import json
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
_UNREAD_VALUE = "codes not read yet"
_ALL_CLEAR_WORDS = ("No stored codes", "NONE", "NO WARNINGS", "clear")

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "alerts")


def _alerts(name: str) -> dict:
    """A states/alerts payload written by the real provider (US-898-b1 fixtures)."""
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _alertsUnread() -> dict:
    """No code read this boot and nothing active: the provider's unread shape."""
    alerts = copy.deepcopy(_alerts("two-stored-codes-real"))
    alerts["entries"] = []
    alerts["codeAlert"] = None
    alerts["sources"]["code"] = {"assessed": False, "checkedAtTs": None}
    alerts["codesCheckedThisSession"] = False
    alerts["checkedAtTs"] = None
    alerts["icon"] = {"state": "not_checked", "count": 0, "pulse": False}
    return alerts


def _alertsP0443() -> dict:
    """The real stored P0443 alone, codes read."""
    alerts = copy.deepcopy(_alerts("two-stored-codes-real"))
    alerts["entries"] = [e for e in alerts["entries"] if e["key"] == "P0443"]
    alerts["codeAlert"]["ids"] = [e["id"] for e in alerts["entries"]]
    alerts["icon"]["count"] = 1
    return alerts


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


def _renderedAlertsText(alerts: dict) -> str:
    """Boot the SHIPPED carousel.js over the SHIPPED markup; return card text.

    Composed on purpose. A correct view function proves nothing about what
    the operator reads -- US-494/495/498 were all two-correct-halves defects
    that every pure unit test passed, which is why render_harness.py exists.
    """
    surface = rh.dashboardSurface(rh.runDashboard(routes={"/alerts": alerts})["tree"])
    path = surface.pathById("alerts-card")
    return " ".join(_textOf(path[-1])) if path else ""


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
    text = _renderedAlertsText(_alerts("two-stored-codes-real"))
    assert "P0400" in text, f"harness read nothing from the Alerts card: {text!r}"


# ---------------------------------------------------------------------------
# END STATE, direction 1 -- available:false renders UNREAD, never an all-clear.
# ---------------------------------------------------------------------------


def test_alertsCard_unreadSourceWithMilFalse_rendersUnreadWithItsReason():
    """
    Given: states/alerts with no code read this boot (checkedAtTs null) and
           nothing active -- the provider's form of the measured unread state
    When: the shipped card renders it
    Then: the operator reads "codes not read yet".

          MOVED PIN (US-898-b1): the reason now lives in the provider's null
          checkedAtTs; the page reads it, never a mil flag.
    """
    text = _renderedAlertsText(_alertsUnread())
    assert _UNREAD_VALUE in text, text


def test_alertsCard_unreadSource_neverRendersTheAllClear():
    """
    Given: the same unread state
    When: the card body is read
    Then: "No stored codes" is absent.

          Unknown is not clear. mil:false + codes:[] is EXACTLY what a clean
          read looks like, so the all-clear is one dropped source check away at
          all times -- and it is the assertion the driver acts on.
    """
    text = _renderedAlertsText(_alertsUnread())
    for word in _ALL_CLEAR_WORDS:
        assert word not in text, (word, text)


# ---------------------------------------------------------------------------
# END STATE, direction 2 -- the earned all-clear. MOVED PIN (US-898-b1):
# RETIRED here. On states/alerts it is NONE / NO WARNINGS for a code read with
# nothing active, which is US-898-b2's to render (898-2/898-3 pin it there).
# ---------------------------------------------------------------------------


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
    Then: the operator reads the code, its MINOR tier and the PROVIDER'S
          sentence for it (Spool, verbatim).

          MOVED PIN (US-898-b1): the tier and the words are the provider's;
          the page's tier directive retired with the hero.
    """
    text = _renderedAlertsText(_alertsP0443())
    assert "P0443" in text, text
    assert "MINOR" in text, text
    assert "Emissions only. Safe to drive." in text, text


def test_alertsCard_storedCode_saysTheReadCompleted_neitherUnreadNorAllClear():
    """
    Given: the same stored-code state
    When: the card is read
    Then: the header reports 1 ACTIVE with the read time, and NEITHER the
          unread line NOR the all-clear appears (MOVED PIN, US-898-b1).

          This is THIS STORY's invariant applied to the read path. Directions 1
          and 2 pin that the two empty-codes states stay apart; nothing pinned
          that a card with a REAL CODE ON IT cannot also claim it was never
          read. Both borrowings are individually reachable -- the unread line
          from a dropped source check, the all-clear from a hero/rows
          disagreement -- and either one prints a contradiction.
    """
    text = _renderedAlertsText(_alertsP0443())
    assert "1 ACTIVE" in text and "codes read" in text, text
    assert _UNREAD_VALUE not in text, text
    for word in _ALL_CLEAR_WORDS:
        assert word not in text, (word, text)


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
    Given: the panel has no MIL indicator (the retired `alertsCardView`
           computed `mil` and nothing read it; states/alerts carries none)
    When: a state with the MIL LIT is rendered
    Then: nothing on the card says so. RECORDED, not fixed (I-us629).

          This is deliberately a characterisation and not an assertion that the
          behaviour is right. It is not a false all-clear -- an absent lamp
          claims nothing, so it is outside this story's END STATE -- but it IS
          a fact the punch list's "the MIL has been LIT since 2026-08-20"
          depends on. Whoever wires the lamp up will fail this test, which is
          the moment to read I-us629 and delete this test on purpose.
    """
    text = _renderedAlertsText(_alertsP0443())
    assert "P0443" in text, "negative control: the code itself DOES render"
    assert "MIL" not in text, text
