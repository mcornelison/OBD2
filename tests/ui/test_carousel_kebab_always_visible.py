################################################################################
# File Name: test_carousel_kebab_always_visible.py
# Purpose/Description: US-659 (F-138) -- the top-bar `⋮` renders in EVERY state.
#   CIO ruling 2026-08-31 (punch-list H6): ALWAYS SHOW THE MENU. The US-490
#   visibility gate is removed entirely; the 5-second long-press remains the
#   real control, so the glyph stops lying about an affordance that was always
#   reachable.
#
#   THIS FILE PINS A DELETION, which is a different job from pinning a feature.
#   A deleted conditional with no test is restored in six months by whoever
#   reads its absence as a bug, so every assertion here is written to FAIL if
#   the gate comes back -- by any of the FIVE mechanisms that made it up. The
#   gate was never one conditional:
#
#     1. dashboard.html shipped the button with a `hidden` attribute (the
#        pre-first-poll window).
#     2. `menuAccess(parked)` returned `tapVisible: parked === true` (policy).
#     3. `applyMenuAccess()` wrote `btn.hidden = !access.tapVisible` (paint).
#     4. the click handler read `menuBtn.hidden` back and refused (US-490 AC-4
#        defence in depth).
#     5. dashboard.css `#menu-btn[hidden] { display: none }` removed it from
#        flow rather than merely fading it.
#
#   FOUR OF THE FIVE ARE GONE. THE FIFTH IS KEPT, and what it is protecting had
#   to be MEASURED rather than reasoned -- the plausible answer was wrong.
#
#   Section 1 can only witness a restored gate if the `hidden` attribute really
#   removes the button from flow. The first draft of this file asserted that
#   `#menu-btn[hidden] { display: none }` was load-bearing for that, because
#   #menu-btn declares its own `display: flex` (US-556) which outranks the UA
#   `[hidden]` rule. True of the UA rule -- and irrelevant, because the US-495
#   GLOBAL guard `[hidden] { display: none !important }` (dashboard.css:199)
#   outranks `display: flex` as well. Dropping the local rule changes nothing.
#   The two mechanisms are redundant with each other; only removing BOTH lets a
#   hidden kebab paint. Measured on the shipped cascade, table in
#   `test_aHiddenKebabHasNoBox_whichIsWhatLetsSection1Fail`.
#
#   THE MUTATION IS WHAT CAUGHT IT, and not by going red. M4 (delete the local
#   rule as dead CSS) killed exactly ONE test -- the one asserting the rule was
#   present -- while the end-to-end cascade proof stayed green. A mutation that
#   kills only the test that restates it, and not the test that would suffer the
#   consequence, is reporting that the stated consequence does not follow. Worth
#   generalising: READ WHICH TESTS A MUTATION KILLS, NOT JUST WHETHER IT DIED.
#
#   VALIDATION CRITERION 3 IS CLOSED BEHAVIOURALLY, NOT BY GREP, and that is the
#   point of the story rather than a nicety. Removing the visibility gate leaves
#   the long-press as the ONLY protection on a menu that can stop services -- and
#   the long-press had never once been exercised end-to-end. Its pure arithmetic
#   (longPressProgress/isLongPressComplete) is well covered, and
#   test_carousel_menu_access.py greps the handler for the ABSENCE of gate
#   identifiers, but nothing had ever held a finger down and watched the menu
#   open. Had the wiring been broken, this story would have removed the thing
#   that was masking it. Section 4 drives the shipped pointer handlers against
#   the virtual wall clock through a new `{pointer}` probe step, and it pins the
#   hold as a MEASURED DURATION -- 5 s opens, 4.999 s does not.
#
#   FINDING RECORDED, NOT FIXED -- offices/pm/issues/I-us659-*.md. The kebab's
#   S-2 tap target is a NEGATIVE-inset pseudo-element (`#menu-btn::after`,
#   US-556) that extends 3px outside the 34px band on every side, and
#   dashboard.css:341-343 records the honest bound it was accepted under: the
#   lower 3px overlays the top of #carousel, which "can only ever intercept a
#   parked tap, never a swipe at speed" BECAUSE #menu-btn was display:none while
#   driving. That premise is what this story removes. Held by a characterisation
#   test in section 6 that whoever re-weighs the target will fail on purpose.
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
# 2026-08-31    | Ralph (Rex)  | Initial -- US-659: pin the removal of the ⋮
#               |              | visibility gate, and the long-press it leaves
#               |              | as the only protection.
# ================================================================================
################################################################################

"""US-659 tests: the ⋮ renders in every state, and the long-press still gates."""

from __future__ import annotations

import os
import re
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The shipped panel, not the harness default: the top bar is laid out under a
# media query and reading it at 1920x1080 measures a bar the driver never sees.
PANEL = (480, 320)

_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_HTML = os.path.join(_DASH, "dashboard.html")
_CSS = os.path.join(_DASH, "dashboard.css")

# A fixed virtual wall clock. Section 4 measures a DURATION, so the instant it
# starts from must not be the machine's -- see US-641's nowMs seam.
_NOW_MS = 1_756_659_000_000


def _readSource(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _systemStatus(
    *, obdAvailable: bool, driveState: str = "idle", driveId: Any = None
) -> dict:
    """A system-status payload from the SHIPPED builder, never hand-written.

    `idle` is DERIVED inside the builder (`(not obdAvailable) and driveState !=
    "recording"`, emitter line 199), so it cannot be passed in -- the two real
    operational poles are reached by the inputs that produce them.
    """
    return buildSystemStatusState(
        obdLinkState="linked" if obdAvailable else "down",
        obdRetries=0,
        obdLastSeenS=1 if obdAvailable else None,
        syncLastOkTs="2026-08-31T15:45:22Z",
        syncRows=1204,
        syncPending=0,
        syncStale=False,
        powerSource="external",
        driveState=driveState,
        driveId=driveId,
        nowIso="2026-08-31T15:45:52Z",
        obdAvailable=obdAvailable,
    )


def _parked() -> dict:
    """Engine off, no OBD link -- the one state the old gate revealed the ⋮ in."""
    payload = _systemStatus(obdAvailable=False, driveState="idle")
    assert payload["idle"] is True, "fixture drifted -- this is meant to be the parked pole"
    return payload


def _driving() -> dict:
    """A drive is RECORDING -- the state the whole gate existed to suppress."""
    payload = _systemStatus(obdAvailable=True, driveState="recording", driveId=51)
    assert payload["idle"] is False, "fixture drifted -- this is meant to be the driving pole"
    return payload


# Every state the acquisition chain can hand the panel, keyed by CAUSE so a
# failure names the condition rather than an index.
#
# The first two are the real operational poles and come from the shipped builder
# untouched. The rest OVERWRITE `idle` on a builder-made payload, and that is
# deliberate rather than lazy: today's emitter derives a strict boolean and can
# never write these, but the removed gate read the field strictly BECAUSE a
# truncated file, an older emitter or a future one can. Those are exactly the
# payloads it resolved to "assume driving, hide the button", so they are the
# states whose rendering this story changes.
def _everyState() -> dict[str, dict | None]:
    def _withIdle(value: Any) -> dict:
        payload = _driving()
        payload["idle"] = value
        return payload

    idleless = _parked()
    del idleless["idle"]
    return {
        "parked": _parked(),
        "driving": _driving(),
        "idle_key_absent": idleless,
        "idle_is_the_string_true": _withIdle("true"),
        "idle_is_the_string_false": _withIdle("false"),
        "idle_is_a_number": _withIdle(1),
        "idle_is_null": _withIdle(None),
        "no_system_status_file": None,
    }


def _render(state: dict | None, steps: list[dict] | None = None) -> rh.Surface:
    """Boot the SHIPPED carousel.js over the SHIPPED markup at 480x320.

    `state is None` serves NO /system-status route at all, so the fetch 404s --
    the "am I driving?" question is genuinely unanswerable, which is the state
    the old gate was most confident about hiding.
    """
    routes: dict[str, Any] = {}
    if state is not None:
        routes["/system-status"] = state
    tree = rh.runDashboard(
        routes=routes,
        steps=steps if steps is not None else [{"flush": 4}],
        viewport=PANEL,
    )["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _kebabPaints(surface: rh.Surface) -> bool:
    """True when #menu-btn AND every ancestor actually has a box."""
    path = surface.pathById("menu-btn")
    assert path is not None, "#menu-btn is not in the DOM at all"
    return surface.rendered(path)


def _executableCode(js: str) -> str:
    """carousel.js with its comments removed.

    NOT named `_codeOnly`: tests/ui/test_carousel_idle_face_retirement.py:107
    already defines a helper by that name in this package, and it is
    LINE-oriented -- it drops lines that START with a comment marker and so
    keeps TRAILING `// ...` text. This one strips comment SPANS, which the
    sweeps below need (a trailing comment on a live line can mention
    `menuAccess` just as easily as a standalone one). Two same-named helpers
    with different strictness in one package is a trap; the names differ so a
    reader can see which guarantee they are getting.

    The source sweeps below have to assert about CODE, not prose. The deletion
    this story makes is worth a tombstone comment -- one that NAMES the retired
    identifiers so the next reader knows what used to be there and why it must
    not come back -- and a naive substring search cannot tell that explanation
    from a restored gate. Stripping first is also the stronger test: it is the
    executable text that decides whether the ⋮ is hidden.

    HONEST BOUND: this is a lexical strip, not a JS parser. A `//` inside a
    string literal takes the rest of that line with it, so the result is good
    for ABSENCE assertions (what remains is a subset of the real code) and must
    not be used to prove something is present.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", js)


# ---------------------------------------------------------------------------
# Section 1 -- END STATE. The kebab renders in every state (criterion 1).
#
# On the RENDERED surface, not on a flag: the gate had a JS half and a CSS half
# and only the resolved cascade can answer "does the driver see it".
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize("cause", sorted(_everyState()))
def test_theKebabRendersInEveryState(cause: str):
    """The ruling, one state at a time. `driving` is the state the gate existed
    to suppress and `no_system_status_file` is the state it was most confident
    about -- both must now paint."""
    assert _kebabPaints(_render(_everyState()[cause])) is True, (
        f"the ⋮ does not paint when {cause}"
    )


@_needsNode
def test_theKebabRendersBeforeTheFirstPollReturns():
    """The markup half, isolated. `flush: 0` runs no poll round at all, so this
    is the shipped DOM as the browser first paints it -- the window the old gate
    covered by shipping `hidden` in the markup. A fix that only unhid the button
    from the poll would leave the boot frame blank and pass every other test
    here, because every other test flushes."""
    assert _kebabPaints(_render(_driving(), steps=[{"flush": 0}])) is True


@_needsNode
def test_theKebabSurvivesTheStateFileVANISHINGUnderIt():
    """Not the same claim as `no_system_status_file` above, which is a cold boot
    that never had an answer. Here the panel polls a PARKED car four times, the
    producer dies, and it polls four more -- the shape a latching gate would
    still get right on a cold boot and wrong in the car."""
    surface = _render(
        _parked(),
        steps=[{"flush": 4}, {"setRoutes": {}}, {"flush": 4}],
    )
    assert _kebabPaints(surface) is True


# ---------------------------------------------------------------------------
# Section 2 -- the removal is PINNED (criterion 2). Re-introduce a visibility
# gate by any of its four retired mechanisms and one of these goes red.
# ---------------------------------------------------------------------------


def test_theMarkupNoLongerShipsTheKebabHidden():
    """Mechanism 1. Read off the ATTRIBUTE LIST, not the raw tag text: a
    substring search for "hidden" inside the tag also matches `aria-hidden` and
    would keep smiling through a restored gate."""
    surface = rh.Surface(rh.parseMarkup(_HTML), "", PANEL)
    path = surface.pathById("menu-btn")
    assert path is not None, "#menu-btn is not in the shipped markup"
    assert "hidden" not in path[-1].get("attrs", {}), (
        "the ⋮ ships hidden again -- the boot window has a visibility gate"
    )


def test_noPolicyFunctionDecidesWhetherTheKebabIsVisible():
    """Mechanisms 2 and 3. `menuAccess`/`applyMenuAccess`/`updateMenuAccess` were
    the policy, the paint and the wiring; a gate cannot be restored in the shape
    it had without one of these names coming back.

    Asserted against the STRIPPED source: the tombstone comment left at the
    deletion site names all four on purpose, and a sweep that could not tell
    that apart would force the explanation to be deleted to keep the test green
    -- which is how a deletion loses the record of why it happened."""
    js = _executableCode(_readSource(_CAROUSEL_JS))
    for gone in ("menuAccess", "applyMenuAccess", "updateMenuAccess", "tapVisible"):
        assert gone not in js, f"`{gone}` is back -- the ⋮ visibility gate was restored"


def test_nothingWritesTheKebabsHiddenFlag():
    """Mechanisms 2/3 again, but by BEHAVIOUR-IN-SOURCE rather than by name, so a
    gate rebuilt under fresh identifiers is caught too. The button is fetched
    once in `setupMenu`; no assignment to its `hidden` may exist anywhere."""
    js = _executableCode(_readSource(_CAROUSEL_JS))
    for writer in ("menuBtn.hidden", 'getElementById("menu-btn").hidden'):
        assert writer not in js, f"`{writer}` -- something touches the ⋮'s hidden flag again"


def test_theTapHandlerNoLongerRefusesOnAHiddenFlag():
    """Mechanism 4, US-490's defence in depth. It was correct while there WAS a
    gate; kept now it is a silent restore point -- re-add `hidden` in the markup
    and the tap dies with nothing else changing."""
    js = _executableCode(_readSource(_CAROUSEL_JS))
    start = js.index('menuBtn.addEventListener("click"')
    handler = js[start : js.index("if (closeBtn)", start)]
    assert "hidden" not in handler, "the tap path is gated on a visibility flag again"


def test_aHiddenKebabHasNoBox_whichIsWhatLetsSection1Fail():
    """MECHANISM 5 IS KEPT, and this pins the INVARIANT rather than either rule.

    Section 1 can only witness a restored gate if `hidden` actually removes the
    button from flow. Two rules in the shipped sheet do that independently, and
    which one wins was worth measuring rather than assuming -- the first draft of
    this test asserted `#menu-btn[hidden]` was load-bearing on the reasoning that
    `#menu-btn`'s own `display: flex` (US-556) outranks the UA `[hidden]` rule.
    That is true of the UA rule and false here: the US-495 global guard
    `[hidden] { display: none !important }` (dashboard.css:199) carries
    `!important` and outranks it too.

    MEASURED on the shipped cascade with `hidden` planted back on the button:
        both rules ............ no box (decided by `[hidden]`)
        drop #menu-btn[hidden]  no box (decided by `[hidden]`)
        drop the global guard   no box (decided by `#menu-btn[hidden]`)
        drop BOTH ............. PAINTS (display:flex, `#menu-btn`)

    So the honest pin is the invariant plus the fact that at least one mechanism
    survives -- asserted here, and proven behaviourally by the test below. A test
    naming only one rule would have gone red on a legitimate tidy-up of a
    genuinely redundant rule while the protection was still intact."""
    from tests.ui.test_dashboard_stop_tier_safety import _read

    css = _read(_CSS)
    mechanisms = [
        "[hidden] { display: none !important; }",  # US-495 global guard
        "#menu-btn[hidden] { display: none; }",  # US-490's local rule
    ]
    surviving = [rule for rule in mechanisms if rule in css]
    assert surviving, (
        "BOTH rules that make `hidden` remove an element from flow are gone -- a "
        "restored ⋮ visibility gate would now set `hidden` while the button "
        "carried on painting, and section 1 would stay green through it"
    )


@_needsNode
def test_reIntroducingTheGateWouldBeCaught_provenOnTheRealCascade():
    """The claim above, MEASURED rather than reasoned. Render the shipped markup
    with `hidden` planted back on the kebab -- the one edit a restored gate makes
    that this harness can stage -- and the section 1 assertion must FAIL. This is
    what makes the sweep a tripwire instead of a description; if the stylesheet
    rule is ever dropped, this test goes red and names the reason."""
    shipped = _readSource(_HTML)
    html = shipped.replace(
        '<button id="menu-btn" class="tap-target" aria-label="System Setup">',
        '<button id="menu-btn" class="tap-target" aria-label="System Setup" hidden>',
    )
    # Refuse to run vacuously. If the shipped tag ever stops matching, this test
    # would otherwise "prove" the tripwire against unmodified markup.
    assert html != shipped, "the plant did not take -- the #menu-btn tag was reshaped"
    tmp = os.path.join(os.path.dirname(__file__), "_us659_gated_markup.html")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(html)
        tree = rh.runDashboard(
            routes={"/system-status": _parked()},
            steps=[{"flush": 4}],
            markupPath=tmp,
            viewport=PANEL,
        )["tree"]
        surface = rh.dashboardSurface(tree, viewport=PANEL)
        assert _kebabPaints(surface) is False, (
            "a hidden ⋮ still paints -- section 1 can no longer witness a restored gate"
        )
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


# ---------------------------------------------------------------------------
# Section 3 -- the affordance the glyph was lying about. The tap now opens the
# menu in the state the gate suppressed.
# ---------------------------------------------------------------------------


def _menuIsOpen(surface: rh.Surface) -> bool:
    path = surface.pathById("setup-menu")
    assert path is not None, "#setup-menu is not in the DOM"
    return surface.rendered(path)


@_needsNode
@pytest.mark.parametrize("cause", ["parked", "driving", "no_system_status_file"])
def test_tappingTheKebabOpensTheMenu(cause: str):
    """`driving` is the case US-490 AC-4 refused. The ruling replaces that refusal
    with the long-press (section 4), so the tap must now be honoured everywhere
    -- otherwise the glyph is still lying, just in the other direction."""
    surface = _render(
        _everyState()[cause], steps=[{"flush": 4}, {"click": "menu-btn"}, {"flush": 1}]
    )
    assert _menuIsOpen(surface) is True, f"the ⋮ paints but does nothing when {cause}"


@_needsNode
def test_theMenuIsClosedUntilItIsAskedFor():
    """The control for the test above. Without it a menu that shipped OPEN would
    satisfy every assertion in this section, and the overlay would simply sit on
    the panel."""
    assert _menuIsOpen(_render(_everyState()["driving"])) is False


# ---------------------------------------------------------------------------
# Section 4 -- THE NEGATIVE CASE. Removing the VISIBILITY gate must not weaken
# the LONG-PRESS gate (criterion 3).
#
# Driven end-to-end for the first time: a real pointerdown on the shipped
# handler, the real 50ms setInterval, and the virtual wall clock supplying the
# elapsed time. Nothing here calls an exported pure function.
# ---------------------------------------------------------------------------


def _hold(holdMs: int, *, moveTo: tuple[int, int] | None = None, release: bool = False):
    """Press the carousel, let `holdMs` of wall clock pass, and read the panel.

    The press lands at (100, 200) -- inside the carousel, well clear of the top
    bar -- so nothing here depends on where the kebab's hit box reaches.
    """
    steps: list[dict[str, Any]] = [
        {"flush": 4},
        {"pointer": {"id": "carousel", "type": "pointerdown", "x": 100, "y": 200}},
    ]
    if moveTo is not None:
        steps.append(
            {"pointer": {"id": "carousel", "type": "pointermove", "x": moveTo[0], "y": moveTo[1]}}
        )
    if release:
        steps.append({"pointer": {"id": "carousel", "type": "pointerup", "x": 100, "y": 200}})
    steps.append({"advanceMs": holdMs, "flush": 1})
    tree = rh.runDashboard(
        routes={"/system-status": _driving()},
        steps=steps,
        viewport=PANEL,
        nowMs=_NOW_MS,
    )["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


@_needsNode
def test_theFiveSecondHoldOpensTheMenu():
    """The protection that is now the ONLY protection, exercised rather than
    grepped. Held while a drive is RECORDING, which is also criterion 3's real
    subject: the override is state-blind and always was."""
    assert _menuIsOpen(_hold(5000)) is True


@_needsNode
def test_aHoldOneMillisecondShortDoesNotOpenTheMenu():
    """The hold is a MEASURED DURATION, not "a press happened". Without this the
    test above is satisfied by a handler that opens on pointerdown, which would
    be the story doing the exact opposite of what was asked."""
    assert _menuIsOpen(_hold(4999)) is False


@_needsNode
def test_aSwipeCancelsTheHold():
    """Movement past LONG_PRESS_MOVE_PX is a swipe, not a hold. This is what
    stops the menu appearing under a driver changing cards -- and with the ⋮ now
    painting at all times, card swiping is the commonest thing happening on this
    surface."""
    assert _menuIsOpen(_hold(5000, moveTo=(400, 200))) is False


@_needsNode
def test_aSmallDriftDoesNotCancelTheHold():
    """The other side of the same threshold, so "cancel on move" cannot be
    satisfied by cancelling on ANY move -- a finger resting on glass is never
    perfectly still, and a hold that dies on 2px of drift is unusable."""
    assert _menuIsOpen(_hold(5000, moveTo=(102, 201))) is True


@_needsNode
def test_releasingEarlyCancelsTheHold():
    """A tap on the carousel body must not arm anything that later opens the
    menu on its own."""
    assert _menuIsOpen(_hold(5000, release=True)) is False


def test_theLongPressPathIsNotGatedByAnyVisibilityState():
    """The scope fence, as a source ABSENCE -- kept from US-490 because the
    behavioural tests above cannot prove a gate is absent for every input, only
    that it is absent for the inputs they drive. Both halves are needed."""
    js = _executableCode(_readSource(_CAROUSEL_JS))
    start = js.index('carousel.addEventListener("pointerdown"')
    block = js[start : js.index('carousel.addEventListener("pointercancel"', start)]
    for gate in ("menuAccess", "tapVisible", "carouselIdle", "menuBtn.hidden", "parked"):
        assert gate not in block, f"the long-press override is gated by {gate}"


def test_theHoldThresholdIsStillFiveSeconds():
    """The constant behind section 4, pinned so a story that "keeps the
    long-press" while shortening it to 500ms is caught. 5s is the D-6
    deliberateness budget, not an implementation detail -- and it is the whole
    reason the CIO could rule the visibility gate away."""
    assert "var LONG_PRESS_MS = 5000;" in _readSource(_CAROUSEL_JS)


# ---------------------------------------------------------------------------
# Section 5 -- scope fence. This story changes WHERE the menu can be reached
# from, never what it does once open. The destructive items keep their confirms.
# ---------------------------------------------------------------------------


def test_exitStillRoutesThroughTheConfirmingAction():
    """Exit / Close UI is a dashboard `stop`, so it inherits requiresConfirm. It
    must not gain a direct postAction shortcut while this file is open -- the
    menu just became reachable in one tap from every state, which raises the
    cost of an unconfirmed action rather than lowering it."""
    js = _readSource(_CAROUSEL_JS)
    start = js.index("if (exitBtn) {")
    block = js[start : js.index("\n      }", start)]
    assert 'doAction("eclipse-dashboard.service", "stop")' in block
    assert "postAction(" not in block, "Exit gained a shortcut past the confirm"


# ---------------------------------------------------------------------------
# Section 6 -- FINDING, recorded not fixed (I-us659).
#
# conditionalOutcome 1: "if the gate turns out to protect something real that
# nobody documented, RECORD that finding". It protected something real and it
# WAS documented -- in the stylesheet, as an honest bound on a different story's
# fix. The ruling stands; the bound now needs re-weighing by Iris.
# ---------------------------------------------------------------------------


def test_theTapTargetStillOverlapsTheCarousel_aBoundThatNowAppliesAtSpeed():
    """CHARACTERISATION. `#menu-btn::after` carries a NEGATIVE inset -- the S-2
    40px minimum minus the 34px band, halved -- so the hit box extends 3px past
    the painted button on every side. dashboard.css records the bound this was
    accepted under: the lower 3px overlays the top of #carousel, and that "can
    only ever intercept a parked tap, never a swipe at speed" BECAUSE #menu-btn
    was display:none while driving.

    US-659 removes that premise. The overlap is unchanged and this story does not
    touch it -- narrowing the target would breach the S-2 minimum, which is an
    Iris call, not a dev one. Recorded so the arithmetic is on the record: whoever
    re-weighs it fails this test on purpose.
    """
    from tests.ui.test_dashboard_stop_tier_safety import _read

    css = _read(_CSS)

    # Read the two tokens out of the stylesheet rather than restating them, so a
    # future band or tap-minimum change re-derives the overhang here instead of
    # leaving this file quoting arithmetic that no longer holds.
    def _tokenPx(name: str) -> float:
        match = re.search(rf"--{name}:\s*([0-9.]+)px", css)
        assert match is not None, f"--{name} is no longer declared in px"
        return float(match.group(1))

    overhangPx = (_tokenPx("bar-h") - _tokenPx("tap-min")) / 2
    assert overhangPx == -3.0, (
        f"the hit box overhangs the band by {-overhangPx}px, not 3px -- "
        "re-measure the carousel overlap before closing I-us659"
    )
    assert "inset: calc((var(--bar-h) - var(--tap-min)) / 2);" in css, (
        "the hit box no longer derives its overhang -- re-measure before closing I-us659"
    )
    # The upper 3px is clipped by `html, body { overflow: hidden }`; the lower
    # 3px is on the glass, over the top of #carousel, and is now live at speed.
