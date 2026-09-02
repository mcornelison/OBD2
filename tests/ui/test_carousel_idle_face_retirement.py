################################################################################
# File Name: test_carousel_idle_face_retirement.py
# Purpose/Description: US-542 (F-127) tests -- the idle/STANDBY face retirement.
#   US-541 made the live IMU the permanent home face, which left the parked
#   "STANDBY / engine off - OBD asleep" screen unreachable. US-542 deletes it
#   and relocates the two things that were only ever ON it because it happened
#   to be what a parked operator saw. Four groups, one per acceptance clause:
#     AC-1a THE STANDBY HERO IS GONE, and gone from anything EXECUTABLE -- not
#           merely unselected. A retired disposition left in the file is a
#           sentence waiting to be printed by the next edit that revives its
#           condition, and this particular sentence is a confident claim about
#           the VEHICLE ("engine off") that would be assembled out of a SENSOR
#           fault. The surviving face has exactly one disposition.
#     AC-1b THE CLOCK MOVED TO THE TOP BAR. Pinned by ANCESTRY, not by sampling
#           a face: the property that matters is "no face decision can take the
#           clock away", and a test that boots one face and finds a clock proves
#           that only for the face it booted.
#     AC-2  "DTC not read - since key-off" MOVED TO ALERTS. Pinned on BOTH sides
#           (the pure view AND the rendered card) and in BOTH directions: it
#           must fire on an unread source and must NOT fire on a real empty
#           read, which is the opposite lie and the more dangerous one.
#     AC-4  THE PARKED LOGIC IS UNTOUCHED. `carouselIdle` / `parkedNext` still
#           read system-status; the retirement is display-only. Two different
#           things in this file are called "idle" -- the parked SSOT and the
#           motion-fault face -- and that collision is exactly how a future edit
#           re-couples them, so the separation is asserted rather than assumed.
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-542 idle-face retirement.
# ================================================================================
################################################################################

"""US-542 tests for the idle/STANDBY face retirement (via node)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard"
)
_JS = os.path.join(_DIST, "carousel.js")
_HTML = os.path.join(_DIST, "dashboard.html")
_CSS = os.path.join(_DIST, "dashboard.css")

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

# The retired copy, named so its ABSENCE is a pin rather than a coincidence.
_RETIRED_HERO = "STANDBY"
_RETIRED_SUBSTATE = "engine off · OBD asleep"
# The moved fact (AC-2), verbatim from the retired face's `idleFaultsFact`.
_MOVED_VALUE = "DTC not read"
_MOVED_DETAIL = "since key-off"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> Any:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _fnBody(js: str, name: str) -> str:
    """One `function <name>(` up to the next declaration at the SAME indent.

    Indent-aware, inherited from US-541's gate: the browser-only renderers are
    nested six spaces deep, and a fixed two-space probe swallows the rest of the
    file -- which makes every ABSENCE assertion below pass vacuously, the one
    direction a broken probe fails silently in.
    """
    start = js.index(f"function {name}(")
    indent = js[js.rfind("\n", 0, start) + 1 : start]
    nxt = js.find("\n" + indent + "function ", start + 1)
    return js[start:] if nxt == -1 else js[start:nxt]


def _codeOnly(src: str) -> str:
    """Drop comment lines so an absence assertion cannot fire on the prose that
    DOCUMENTS the removal. This file's own comments name every retired string,
    and so does carousel.js -- an un-stripped grep would fail on the explanation
    of the fix rather than on the defect (the US-507 lesson)."""
    keep = []
    for line in src.splitlines():
        bare = line.strip()
        if bare.startswith("//") or bare.startswith("*") or bare.startswith("/*"):
            continue
        keep.append(line)
    return "\n".join(keep)


def _dtcUnread(reason: str = "no key-on read yet") -> dict:
    """A `dtc` payload whose SOURCE is unavailable -- the state the moved line
    exists for. Note `codes: []`: the array is empty here exactly as it is on a
    genuine clean read, which is why "no read happened" has to be carried by the
    source block and can never be inferred from the codes."""
    return {"codes": [], "source": {"dtc": {"available": False, "reason": reason}}}


def _dtcCleanRead() -> dict:
    """A REAL key-on read that found nothing. Same empty array, opposite fact."""
    return {
        "codes": [],
        "mil": False,
        "source": {"dtc": {"available": True, "reason": None}},
    }


def _cardText(tree: dict, stateName: str) -> str:
    """All rendered text under the card bound to ``stateName``.

    Joined rather than structured on purpose: this is the "did the two halves
    connect?" backstop, and what it needs to know is whether the operator can
    READ the line -- not which span carries which half of it.
    """
    surface = rh.dashboardSurface(tree)
    for path in surface.paths():
        if path[-1].get("attrs", {}).get("data-state") == stateName:
            return " ".join(_textOf(path[-1]))
    return ""


def _textOf(node: dict) -> list[str]:
    out = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"].strip())
        else:
            out.extend(_textOf(child))
    return [t for t in out if t]


# ---------------------------------------------------------------------------
# The probes are pinned FIRST. Every assertion below is an absence or an
# ancestry check, and both fail open when the tool that reads the file is
# broken -- so the tools get their negative controls before they are trusted.
# ---------------------------------------------------------------------------


def test_codeOnly_stillSeesRealCode():
    """Over-stripping is the dangerous direction: it deletes the very text the
    absence pins hunt for, and every one of them then passes for free."""
    stripped = _codeOnly(_read(_JS))
    assert "function idleCardView(" in stripped
    assert "function alertsCardView(" in stripped


def test_fnBody_isBoundedAndDoesNotSwallowTheFile():
    """A body probe that runs to EOF makes an absence assertion meaningless --
    it would report "STANDBY is not in renderIdleBody" only because it never
    found renderIdleBody's end either."""
    js = _read(_JS)
    body = _fnBody(js, "idleCardView")
    assert "wordmark" in body, "negative control: the probe can see real code"
    assert len(body) < len(js) / 4, "the probe swallowed the file"


# ---------------------------------------------------------------------------
# AC-1a -- the STANDBY hero is retired, not merely unselected.
# ---------------------------------------------------------------------------


def test_theStandbyClaimIsGoneFromAnythingExecutable():
    """
    Given: US-541 left the parked disposition unreachable but still written down
    When: the shipped carousel.js is read with its comments stripped
    Then: neither the hero title nor its "engine off" substate survives.

          Unreachable is not the same as retired. The sentence claims a fact
          about the VEHICLE, and the only remaining route to this view is a DEAD
          SENSOR -- so the day someone restores a condition that selects it, the
          display states "engine off" on the evidence of a broken accelerometer.
          Deleting the sentence is what makes that impossible rather than
          unlikely (US-500: nothing executes dead code, so nothing proves it
          still resolves -- and nothing stops it resolving WRONG).
    """
    code = _codeOnly(_read(_JS))
    assert _RETIRED_SUBSTATE not in code
    assert f'"{_RETIRED_HERO}"' not in code


def test_idleCardView_hasOneDispositionAndItNamesTheDeadInstrument():
    """
    Given: the face is now reachable ONLY because the motion feed died
    When: the view is assembled with any reason
    Then: the hero states that, every time -- there is no second title left for
          a future edit to select.
    """
    for reason in ("no motion feed", "sensor not detected", "reading stale"):
        view = _view("idleCardView", None, None, reason)
        assert view["hero"]["title"] == "NO MOTION DATA"
        assert view["hero"]["substate"] == reason
        assert view["hero"]["level"] == "neutral"


def test_idleCardView_cannotSeeTheDtcPayloadAtAll():
    """
    Given: the faults tile moved to the Alerts card
    When: the shipped declaration is read
    Then: `idleCardView` takes (systemStatusData, batteryData, motionReason).

          The signature is the guard, not a tidy-up (the US-541 pattern). A view
          that cannot SEE the dtc payload cannot quietly re-borrow the fact that
          just left it; a future re-borrow has to widen the signature first,
          which is a visible act rather than a line added to a facts object.
    """
    sig = re.search(r"function idleCardView\(([^)]*)\)", _read(_JS))
    assert sig, "idleCardView is gone"
    params = [p.strip() for p in sig.group(1).split(",") if p.strip()]
    assert params == ["systemStatusData", "batteryData", "motionReason"], params


def test_idleCardView_carriesNoFaultsTile():
    """
    Given: the moved fact
    When: the view is assembled
    Then: the facts set is exactly the two that survived.

          Set equality, not a `"faults" not in` check: the second fails to
          notice the tile coming back under any other name, and the failure mode
          this guards is a later story re-adding "just one more readout" to the
          card the legibility scale was re-laid to thin out (US-540-b).
    """
    view = _view("idleCardView", None, None, "no motion feed")
    assert set(view["facts"]) == {"lastDrive", "battery"}


def test_theRetiredFaceIsNotStillBeingBuiltByTheRenderer():
    """
    Given: a renderer can keep painting a field the view no longer supplies
    When: `renderIdleBody` is read
    Then: it appends neither a faults tile nor a clock.

          Both halves of a markup/renderer pair have to be asserted -- US-540-b
          shipped an orphan `data-vehicle-speaks` attribute past a suite whose
          orphan-check only watched the JS.
    """
    body = _codeOnly(_fnBody(_read(_JS), "renderIdleBody"))
    assert "view.facts.lastDrive" in body, "negative control: the pin sees real code"
    assert "faults" not in body
    assert "fmtClock" not in body
    assert "fmtDate" not in body


def test_theDateFormatterWentWithTheHeaderItServed():
    """
    Given: the parked header was `fmtDate`'s only caller
    When: the shipped file is read
    Then: it is deleted, along with its month/day tables.

          The date is the one piece of that header US-542 does NOT relocate (the
          top bar has room for a clock, not a clock and a date) -- a named loss.
          Leaving the formatter behind would turn a decision into an accident
          nobody can find later.
    """
    code = _codeOnly(_read(_JS))
    assert "fmtDate" not in code
    assert "IDLE_MONTHS" not in code


# ---------------------------------------------------------------------------
# AC-1b -- the clock moved to the persistent top bar.
# ---------------------------------------------------------------------------


def test_theTopBarShipsAnEmptyClockSlot():
    """
    Given: the clock is chrome now
    When: the shipped markup is read
    Then: the slot exists and ships EMPTY.

          Empty is the honest pre-first-paint state. A hard-coded "12:00" would
          be a fabricated reading on the one surface that is always visible, and
          it would still be there if the painter never ran -- the same defect
          class as the version chip's hard-coded sentinel (US-501).
    """
    html = _read(_HTML)
    slot = re.search(r'<span id="topbar-clock">(.*?)</span>', html, re.S)
    assert slot, "no #topbar-clock element in the shipped markup"
    assert slot.group(1).strip() == ""


def test_theClockIsPaintedFromTheOneSharedFormatter():
    """
    Given: `fmtClock` is the pinned 12-hour face (US-503)
    When: the top-bar painter is read
    Then: it calls that formatter rather than owning a second one.

          Two formatters is how one surface drifts back to 24-hour time while
          every test of the other stays green -- which is the shape of the
          US-494/US-499/US-502 failures this project keeps re-learning.
    """
    js = _read(_JS)
    assert len(re.findall(r"function fmtClock\(", js)) == 1
    assert "fmtClock(" in _codeOnly(_fnBody(js, "renderTopbarClock"))


def test_theClockPainterWritesOnlyWhenTheFaceActuallyChanges():
    """
    Given: the painter is driven by the 4 Hz card tick
    When: its body is read
    Then: it compares before it writes.

          The face moves once a minute, so an unguarded write is ~240 pointless
          DOM mutations a minute on the always-visible surface. Needless
          always-on repaint work on this panel is not theoretical: US-537's RCA
          traced the US-522 freeze to exactly that kind of permanent cost.
    """
    body = _codeOnly(_fnBody(_read(_JS), "renderTopbarClock"))
    assert "lastClockText" in body
    assert "return" in body


def test_theRetiredClockSelectorsAreGoneFromTheStylesheet():
    """
    Given: `.idle-clock` / `.idle-date` dressed a header that no longer has them
    When: the stylesheet is read
    Then: both rules are gone.

          Dead selectors are not untidy here, they are loaded: US-540-b found
          the retired `.health-*` block still carrying tile overrides that would
          have silently shrunk the new type scale on the first reuse of the
          class name. Same sheet, same failure, one story later.
    """
    css = rh.parseCss(_read(_CSS))
    selectors = {rule.selector for rule in css}
    assert ".idle-clock" not in selectors
    assert ".idle-date" not in selectors
    assert "#topbar-clock" in selectors, "negative control: the new rule IS there"


# ---------------------------------------------------------------------------
# AC-2 -- "DTC not read - since key-off" moved to the Alerts card.
# ---------------------------------------------------------------------------


def test_alertsCardView_unreadSource_carriesTheMovedLine():
    """
    Given: the DTC source is unavailable (no key-on read has happened)
    When: the Alerts view is assembled
    Then: it states "DTC not read - since key-off".

          US-429 already refused to print "No stored codes" over an unread
          source, but a bare typed NA says only that the instrument is silent.
          WHEN the silence started is the fact the retired face carried, and it
          is the one that tells the operator this is normal after a key-off
          rather than a fault that just appeared.
    """
    view = _view("alertsCardView", _dtcUnread())
    assert view["unavailable"] is True
    assert view["notRead"]["value"] == _MOVED_VALUE
    assert view["notRead"]["detail"].startswith(_MOVED_DETAIL)


def test_alertsCardView_keepsTheEmittersReasonBesideTheMovedLine():
    """
    Given: "since key-off" is WHEN and the emitter's reason is WHY
    When: the view is assembled
    Then: both survive.

          Dropping either to make room for the other loses a real fact. The
          reason is also still on the view itself, so nothing that already read
          `view.reason` breaks on the relocation.
    """
    view = _view("alertsCardView", _dtcUnread("bus asleep"))
    assert "bus asleep" in view["notRead"]["detail"]
    assert view["reason"] == "bus asleep"


def test_alertsCardView_unreadSource_isGreyNotACalmNeutral():
    """
    Given: the retired face rendered this line NEUTRAL, among other tiles
    When: it is re-hosted alone on the Alerts card
    Then: it takes the `unavailable` level.

          Neutral read as "calm" beside a battery tile and a last-drive tile.
          Alone on the Alerts card it would read as a completed read with
          nothing to report -- the false all-clear US-429 exists to prevent.
          Grey is this whole dashboard's word for "no read happened".
    """
    view = _view("alertsCardView", _dtcUnread())
    assert view["notRead"]["level"] == "unavailable"


def test_alertsCardView_realEmptyRead_neverBorrowsTheMovedLine():
    """
    Given: a genuine key-on read that found no codes
    When: the view is assembled
    Then: no `notRead` line -- the card says its honest all-clear instead.

          This is the pin in the OTHER direction, and it guards the more
          dangerous lie. "DTC not read" over a completed clean read tells the
          operator to go read the codes that were already read; the two states
          share an empty `codes` array and are told apart ONLY by the source
          block, so a one-character slip collapses them.
    """
    view = _view("alertsCardView", _dtcCleanRead())
    assert view.get("unavailable") is not True
    assert "notRead" not in view
    assert view["hero"] is None
    assert view["rows"] == []


def test_alertsCard_renderedBody_actuallyShowsTheMovedLine():
    """
    Given: a correct view proves nothing if the renderer paints something else
    When: the SHIPPED carousel.js boots over the SHIPPED markup with an unread
          dtc state
    Then: the operator can read the moved line on the Alerts card.

          The two-correct-halves-never-connected backstop. The old renderer
          composed its own "NA" via `renderNaBody`, which would have swallowed
          the moved fact whole while every pure test above stayed green.
    """
    tree = rh.runDashboard(routes={"/dtc": _dtcUnread("no key-on read yet")})["tree"]
    text = _cardText(tree, "dtc")
    assert _MOVED_VALUE in text, text
    assert _MOVED_DETAIL in text, text


def test_alertsCard_renderedBody_neverSaysNoStoredCodesOverAnUnreadSource():
    """
    Given: the same boot
    When: the Alerts body is read
    Then: the false all-clear is absent from the rendered text.

          Asserted on the SURFACE and not only in the view, because this is the
          claim the operator acts on -- and the one US-429 was filed over.
    """
    tree = rh.runDashboard(routes={"/dtc": _dtcUnread()})["tree"]
    assert "No stored codes" not in _cardText(tree, "dtc")


# ---------------------------------------------------------------------------
# AC-4 -- the parked / auto-rotate-pause logic reads SYSTEM-STATUS, not the
# removed face. The retirement is display-only, and that is verified, not
# asserted in prose.
# ---------------------------------------------------------------------------


def test_carouselIdle_isStillTheParkedSsotAndReadsSystemStatusOnly():
    """
    Given: the word "idle" now means two different things in this file -- the
           parked SSOT and the retired motion-fault face
    When: `carouselIdle` is exercised
    Then: it still reads the emitter's system-status flag, untouched by the
          retirement.

          The collision is the hazard AC-4 is about: a future edit that reads
          "the idle face is gone" and deletes this too would take the
          auto-rotate pause and the ⋮ reveal with it.
    """
    assert _view("carouselIdle", {"idle": True}) is True
    assert _view("carouselIdle", {"idle": False}) is False
    assert _view("carouselIdle", None) is False


def test_carouselIdle_neverReachesForTheRetiredFace():
    """
    Given: the display-only claim
    When: the parked SSOT's body is read
    Then: it names no face, no view and no motion payload.

          A grep of the body rather than the signature alone: a stale global
          would couple them just as tightly as a parameter would.
    """
    body = _codeOnly(_fnBody(_read(_JS), "carouselIdle"))
    assert "systemStatusData" in body, "negative control: the pin sees real code"
    for forbidden in ("idleCardView", "homeFace", "imuView", "motionReason"):
        assert forbidden not in body


def test_parkedNext_reducesTheResolvedIdleSignalNotAFace():
    """
    Given: `parkedNext` is the debounce behind the ⋮ reveal and the rotate pause
    When: its declaration and body are read
    Then: it takes the resolved flag + a clock + config, and reaches for no face.
    """
    js = _read(_JS)
    sig = re.search(r"function parkedNext\(([^)]*)\)", js)
    assert sig, "parkedNext is gone"
    params = [p.strip() for p in sig.group(1).split(",") if p.strip()]
    assert params == ["prev", "rawIdle", "nowMs", "cfg"], params
    body = _codeOnly(_fnBody(js, "parkedNext"))
    for forbidden in ("idleCardView", "homeFace", "imuView"):
        assert forbidden not in body


def test_parkedNext_stillDebouncesAcrossTheRetirement():
    """
    Given: the reducer is the thing AC-4 says must keep working
    When: a parked reading is held past the on-threshold
    Then: it latches -- behaviour, not just a signature.

          A structural pin alone would stay green over a reducer gutted to
          `return prev`, which is exactly what "the retirement is display-only"
          has to rule out.
    """
    cfg = {"parkedOnS": 3, "parkedOffS": 5}
    first = _view("parkedNext", None, True, 0, cfg)
    assert first["parked"] is False, "an unheld reading must not latch immediately"
    held = _view("parkedNext", first, True, 3000, cfg)
    assert held["parked"] is True


def test_theParkedSignalStillHasLiveConsumers():
    """
    Given: US-541 removed the home face as a consumer of `carouselIdle`
    When: the shipped file is read
    Then: the surviving consumer is still there.

          Without this the suite would go green on a retirement that quietly
          took the home-nav edge with it -- a regression no absence pin above
          can see, because it looks like more deletion of the same thing.

    US-659 REPOINTED THIS FROM A COUNT TO A NAME, and the count is why it had
    to be. It asserted `>= 3` occurrences of `carouselIdle(` as a proxy for "the
    consumers are still there". Two of those three were the DEFINITION and the
    ⋮ visibility gate -- and when the CIO's punch-list H6 ruling removed the
    gate, this test failed while the consumer it names in its own docstring
    (the home-nav edge) was untouched. A count cannot witness WHICH call sites
    survive, so it reports a deliberate deletion and a real regression
    identically. Now asserted by name, which is both stricter and legible.
    """
    code = _codeOnly(_read(_JS))
    start = code.index("function updateHomeNav(sysData)")
    body = code[start : code.index("\n      }", start)]
    assert "carouselIdle(sysData)" in body, (
        "the home-nav edge lost its parked SSOT along with the retired face"
    )
