################################################################################
# File Name: test_carousel_dot_card_mapping.py
# Purpose/Description: US-635 (F-138) -- RECORD THE PASS for Atlas punch-list
#   item 1.9: "every carousel dot maps to a reachable card". Atlas observed 6
#   dots against six cards on the live Pi. This file makes that observation
#   survive as evidence rather than as somebody's memory.
#
#   WHAT WAS ALREADY RECORDED, and why it is not enough. Two shipped tests
#   already assert `visibleDots == visibleCards`
#   (test_carousel_card_set.py::test_oneDotPerVisibleCard and
#   test_render_regression.py::test_dotsMatchVisibleCards_onABench). Both are
#   COUNT assertions and both run on a bench where ALL SIX cards are visible, so
#   between them they leave two holes:
#
#     1. NO MAPPING. A count cannot witness WHICH card a dot reaches. Six dots
#        that all navigate to card 0 satisfy both existing tests exactly. The
#        punch-list item is about reachability, and reachability is per-dot.
#     2. THE NEGATIVE CASE HAS NEVER BEEN RENDERED. `data-vehicle-gated` is on
#        NO card in the shipped markup -- measured, not assumed (US-507 took the
#        last one when Fuel Trim became a section, and US-540-b brought it back
#        as an UNGATED card). So `gatedCards` is empty on the real Pi, nothing is
#        ever hidden, and `dots[d].hidden = flags[d]` is dead on every existing
#        rendered test. The equality those tests assert is satisfied by
#        "everything is visible", which is true for a reason that has nothing to
#        do with the geometry they claim to guard. Deleting the dot-hiding line
#        leaves both of them green. That is the US-501/US-634 shape again -- two
#        independently-green halves with the load-bearing branch between them --
#        and it is why this file gates a card ON PURPOSE and renders it.
#
#   The pure-function half (visualPosition / nextVisibleIndex /
#   nearestVisibleIndex) is pinned in test_carousel_pi_local_cards.py. This file
#   deliberately does NOT re-test those: it asserts the WIRING, i.e. that the
#   dots the browser actually builds are hung on that math and on the same card
#   list. Everything below boots the SHIPPED carousel.js over the SHIPPED markup
#   and resolves the SHIPPED stylesheet (tests/ui/render_harness.py), because a
#   correct routine the boot never calls renders nothing (US-494/US-495).
#
#   OUTCOME: PASS. The behaviour Atlas observed is correct in every case
#   exercised here, including the four the gate forces. Per the story's
#   conditional outcome, nothing was fixed -- this is a recording, not a repair.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-635 dot/card mapping recorded.
# ================================================================================
################################################################################

"""US-635 tests: every carousel dot maps to a reachable card (punch list 1.9)."""

import os
import re
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# The CIO/Iris-locked card set (US-540-b), in carousel order. Named here so a
# mapping assertion can say WHICH card it expected, not just an index.
_CARD_SET = ["Home", "Alerts", "System Status", "Battery", "Fuel Trim", "Light"]

# carousel.js labels each dot by its ABSOLUTE card index, 1-based.
def _dotLabel(cardIndex: int) -> str:
    return f"card {cardIndex + 1}"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sysState(obdAvailable: bool) -> dict[str, Any]:
    """A bench Pi's system-status. `idle` is held INDEPENDENT of the vehicle
    flag on purpose: `carouselIdle` reads `idle` and `vehicleConnected` reads
    `source.obd.available`, and the idle edge fires US-508's home navigation.
    Letting the two move together would make every gate test also a home-nav
    test, and the home nav would silently supply the answer.
    """
    return {
        "wifi": {"state": "up", "ssid": "bench", "rssiDbm": -50},
        "obdLink": {
            "state": "linked" if obdAvailable else "down",
            "retries": 0,
            "lastSeenS": 2,
        },
        "sync": {"lastOkTs": _now(), "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "idle", "driveId": None},
        "source": {"obd": {"available": obdAvailable}},
        "idle": True,
        "ts": _now(),
    }


def _routes(obdAvailable: bool = False) -> dict[str, Any]:
    """A bench Pi with a live UPS + light feed and no stored codes."""
    return {
        "/system-status": _sysState(obdAvailable),
        "/battery-health": {
            "health": "good",
            "vcellV": 4.02,
            "soc": 88,
            "socCalibrated": True,
            "draining": False,
            "lastHealthCheckTs": _now(),
            "ts": _now(),
        },
        "/light": {"lux": 120.0, "ts": _now()},
        "/dtc": {"codes": [], "newSinceTs": None, "ts": _now()},
        "/ltft-trend": None,
    }


def _writeMarkup(html: str) -> str:
    path = os.path.join(tempfile.mkdtemp(prefix="us635-"), "dashboard.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def _shippedMarkup() -> str:
    with open(_HTML, encoding="utf-8") as fh:
        return fh.read()


def _gatedMarkup(label: str) -> str:
    """The shipped markup with ONE card put behind the US-496 vehicle gate.

    The gate is a real, shipped mechanism (`applyVehicleGate`) that today has no
    card attached to it. Attaching one is how the hidden-card branch of the dot
    geometry gets rendered at all -- see the file header.
    """
    html = _shippedMarkup()
    out = html.replace(f'aria-label="{label}"', f'data-vehicle-gated aria-label="{label}"', 1)
    assert out != html, f"no card is labelled {label!r} -- the card set moved"
    return _writeMarkup(out)


def _visibleCards(surface: rh.Surface) -> list[str]:
    return [
        (path[-1]["attrs"].get("aria-label") or "?")
        for path in surface.pathsByClass("card")
        if surface.rendered(path)
    ]


def _allCards(surface: rh.Surface) -> list[str]:
    return [
        (path[-1]["attrs"].get("aria-label") or "?")
        for path in surface.pathsByClass("card")
    ]


def _visibleDots(surface: rh.Surface) -> list[str]:
    return [
        (path[-1]["attrs"].get("aria-label") or "?")
        for path in surface.pathsByClass("dot")
        if surface.rendered(path)
    ]


def _activeDot(surface: rh.Surface) -> str:
    """The aria-label of the dot painted `active`, which is what tells the
    operator where they are. Exactly one must be active AND VISIBLE: an active
    dot the operator cannot see is the same dead affordance as a dot with no
    card behind it."""
    active = [
        (path[-1]["attrs"].get("aria-label") or "?")
        for path in surface.pathsByClass("dot")
        if surface.rendered(path) and "active" in (path[-1]["attrs"].get("class") or "").split()
    ]
    assert len(active) == 1, f"expected exactly one visible active dot, got {active}"
    return active[0]


def _landedCard(surface: rh.Surface) -> str:
    """The card the carousel has actually navigated to, read the way the panel
    shows it: `#track`'s translateX step, counted across the VISIBLE cards.

    Deliberately NOT read off the active dot -- the whole point is that the two
    are independent readings which must agree."""
    path = surface.pathById("track")
    assert path is not None, "#track is not in the DOM"
    transform = ((path[-1].get("style") or {}).get("transform") or "").strip()
    match = re.fullmatch(r"translateX\((-?\d+(?:\.\d+)?)%\)", transform)
    assert match, f"unreadable track transform {transform!r}"
    percent = float(match.group(1))
    assert percent % 100 == 0, f"track parked between cards at {transform!r}"
    step = int(-percent // 100)
    visible = _visibleCards(surface)
    assert 0 <= step < len(visible), (
        f"track is at step {step} but only {len(visible)} cards are visible "
        f"{visible} -- the carousel is showing a blank frame"
    )
    return visible[step]


def _boot(
    *,
    obdAvailable: bool = False,
    markupPath: str | None = None,
    steps: list[dict[str, Any]] | None = None,
    routes: dict[str, Any] | None = None,
) -> rh.Surface:
    dom = rh.runDashboard(
        routes=_routes(obdAvailable) if routes is None else routes,
        markupPath=markupPath,
        steps=steps,
    )
    return rh.dashboardSurface(dom["tree"])


def _clickDot(index: int) -> list[dict[str, Any]]:
    """Boot, settle, then tap the dot at ABSOLUTE card index `index`.

    Indexed over every dot including hidden ones, so a test can also tap where a
    gated card's dot would be and prove the navigation guard refuses it."""
    return [{"flush": 4}, {"clickNth": {"selector": ".dot", "index": index}}]


# ---------------------------------------------------------------------------
# The recorded pass -- Atlas punch-list 1.9 on the shipped surface.
# ---------------------------------------------------------------------------


@_NODE_ONLY
class TestShippedSurface:
    """Six cards, six dots, and each dot reaching its own card."""

    def test_everyCardOwnsExactlyOneDot(self):
        """
        Given: the shipped dashboard booted on a bench Pi
        Then: one page dot paints per visible card, and every card is visible

        This is Atlas's observation verbatim (6 dots / 6 cards). The count is
        already asserted twice elsewhere; it is repeated here as the PREMISE the
        mapping tests below rest on, so a change to the card set fails in this
        file with a message about THIS file's subject.
        """
        surface = _boot()
        assert _visibleCards(surface) == _CARD_SET
        assert _visibleDots(surface) == [_dotLabel(i) for i in range(len(_CARD_SET))]

    def test_noDotIsHiddenWhenNoCardIs(self):
        """
        Given: the shipped dashboard, where no card carries the vehicle gate
        Then: no dot is hidden either

        The inverse of the gate tests below. Without it, "hide every dot always"
        would satisfy the negative case and nothing would catch it.
        """
        surface = _boot()
        allDots = [p[-1]["attrs"].get("aria-label") for p in surface.pathsByClass("dot")]
        assert allDots == _visibleDots(surface), "a dot is hidden with no card gated"

    @pytest.mark.parametrize("index,card", list(enumerate(_CARD_SET)))
    def test_eachDotNavigatesToItsOwnCard(self, index: int, card: str):
        """
        Given: the booted six-card carousel
        When: the operator taps the dot for `card`
        Then: that card is the one on screen, and its dot is the active one

        THE ASSERTION THE COUNT TESTS CANNOT MAKE. Six dots all wired to
        `goTo(0)` pass every dot test in the suite today: the count is right,
        every dot paints, and nothing reads where a tap lands. The two readings
        here are independent -- the landed card comes from #track's translateX
        over the visible cards, the position indicator from the `active` class --
        so a mapping that is merely self-consistent cannot satisfy both.
        """
        surface = _boot(steps=_clickDot(index))
        assert _landedCard(surface) == card
        assert _activeDot(surface) == _dotLabel(index)


# ---------------------------------------------------------------------------
# The negative case the story mandates: a gated card contributes NO dot.
# ---------------------------------------------------------------------------


@_NODE_ONLY
class TestGatedCardOwnsNoDot:
    """The branch no shipped card reaches and no rendered test has ever run.

    A dot for a card that is not there navigates to a blank frame the operator
    cannot see their way out of -- the US-495/US-496 defect. The absence has to
    be a REAL absence (no dot at all), not a dot painted in some neutral style,
    which is the "unread value shown as a settled result" class from punch-list
    2.1.
    """

    def test_trailingGatedCard_contributesNoDot(self):
        """
        Given: the Light card put behind the vehicle gate, and no vehicle
        Then: it does not paint, ITS dot does not paint, and five remain

        Asserted by NAME, not by count: `len(dots) == 5` is also satisfied by
        dropping the wrong dot, which would leave every remaining tap one card
        off with a perfectly plausible-looking row of five.
        """
        surface = _boot(markupPath=_gatedMarkup("Light"))
        assert _visibleCards(surface) == _CARD_SET[:-1]
        assert _visibleDots(surface) == [_dotLabel(i) for i in range(len(_CARD_SET) - 1)]
        assert _dotLabel(5) not in _visibleDots(surface)

    def test_midRowGatedCard_contributesNoDot(self):
        """
        Given: the Battery card (index 3, MID-ROW) gated off, and no vehicle
        Then: exactly its dot is gone; the dots on either side survive

        Mid-row is the case that separates a real mapping from a coincidence: a
        trailing gate leaves the surviving indices unchanged, so it can be
        satisfied by "drop the last dot".
        """
        surface = _boot(markupPath=_gatedMarkup("Battery"))
        assert _visibleCards(surface) == ["Home", "Alerts", "System Status", "Fuel Trim", "Light"]
        assert _visibleDots(surface) == [_dotLabel(i) for i in (0, 1, 2, 4, 5)]

    @pytest.mark.parametrize(
        "index,card",
        [(0, "Home"), (1, "Alerts"), (2, "System Status"), (4, "Fuel Trim"), (5, "Light")],
    )
    def test_midRowGate_everySurvivingDotStillLandsOnItsOwnCard(self, index: int, card: str):
        """
        Given: the Battery card gated off mid-row
        When: the operator taps each surviving dot
        Then: each still reaches its own card

        The dots keep their ABSOLUTE indices while the track has closed up
        behind the hidden card, so tapping "card 5" must move four visible cards
        but three visual steps. Get that wrong and the row still looks correct --
        five dots, five cards -- while every tap past the gap lands one card
        early. Nothing in the suite could see that before this test.
        """
        surface = _boot(markupPath=_gatedMarkup("Battery"), steps=_clickDot(index))
        assert _landedCard(surface) == card
        assert _activeDot(surface) == _dotLabel(index)

    def test_theGatedCardsDotNavigatesNowhere(self):
        """
        Given: the Battery card gated off, and its (hidden) dot tapped anyway
        Then: the carousel has not moved

        Belt and braces on the ONE outcome that must be impossible: landing on a
        card that is not there. The dot is display:none so a finger cannot reach
        it, but `goTo` refuses independently -- and it has to, because the
        keyboard, the auto-rotate and the DTC jump all call `goTo` too.
        """
        before = _boot(markupPath=_gatedMarkup("Battery"))
        after = _boot(markupPath=_gatedMarkup("Battery"), steps=_clickDot(3))
        assert _landedCard(after) == _landedCard(before) == "Home"
        assert _activeDot(after) == _dotLabel(0)

    def test_absentSystemStatus_failsClosed_soTheGatedCardOwnsNoDot(self):
        """
        Given: NO readable system-status at all (the state file is missing)
        Then: the gated card stays hidden and owns no dot

        The typed-absence case. "Is a car connected?" is UNKNOWN here, and an
        unknown must never render as a state (US-492/US-494) -- so the reveal
        fails closed and the dot row shrinks rather than offering a tap onto a
        card whose feed nobody has confirmed exists.
        """
        routes = _routes(obdAvailable=False)
        del routes["/system-status"]
        surface = _boot(markupPath=_gatedMarkup("Battery"), routes=routes)
        assert "Battery" not in _visibleCards(surface)
        assert _dotLabel(3) not in _visibleDots(surface)

    def test_aCardRevealedAtRuntimeGetsItsDotBack(self):
        """
        Given: a bench boot with the Battery card gated off
        When: a vehicle appears on a later poll
        Then: the card AND its dot come back, and the dot reaches the card

        The reveal is the half that rots silently: a gate that only ever hides
        leaves a permanently-shortened dot row, and the card behind it becomes
        unreachable for the rest of the session. `idle` is held constant across
        the flip so US-508's home navigation is not what moves the carousel.

        THE DOT ROW IS READ BEFORE THE TAP, in a separate boot, and that
        ordering is load-bearing. Any navigation re-runs `render()` and repairs a
        stale row on its way past, so a tap-then-assert would still see six dots
        even if the reveal itself never re-laid them out -- the operator would be
        the one who had to guess the card was back and swipe to it blind.
        """
        reveal: list[dict[str, Any]] = [
            {"flush": 4},
            {"setRoutes": {"/system-status": _sysState(True)}},
            {"flush": 6},
        ]
        settled = _boot(markupPath=_gatedMarkup("Battery"), steps=reveal)
        assert _visibleCards(settled) == _CARD_SET
        assert _visibleDots(settled) == [_dotLabel(i) for i in range(len(_CARD_SET))], (
            "the card came back but its dot did not -- the reveal did not "
            "re-lay-out the carousel"
        )

        tapped = _boot(
            markupPath=_gatedMarkup("Battery"),
            steps=[*reveal, {"clickNth": {"selector": ".dot", "index": 3}}],
        )
        assert _landedCard(tapped) == "Battery"
        assert _activeDot(tapped) == _dotLabel(3)


# ---------------------------------------------------------------------------
# The SSOT: one card registry, and the dots are built from it.
# ---------------------------------------------------------------------------


@_NODE_ONLY
class TestOneCardRegistry:
    """Proven by RUNNING a different card set, not by reading the source."""

    def test_anAddedCardBringsItsOwnDot_whileAGatedOneStillHasNone(self):
        """
        Given: a SEVEN-card markup whose fourth card is behind the vehicle gate,
               and no vehicle
        Then: six cards paint, six dots paint, and each dot reaches its own card

        The story's SSOT is "the carousel card registry in carousel.js", and the
        registry is the `.card` query itself -- there is no second list. This is
        what proves it: a card the registry has never heard of arrives with a
        working dot, at the same time as a gated one keeps none. A hardcoded
        count, or a second list of cards kept alongside the query, breaks one
        half or the other here while leaving both halves' own tests green.
        """
        original = '<section class="card" data-state="battery-health" aria-label="Battery">'
        html = _shippedMarkup()
        assert original in html, "the Battery card markup moved"
        html = html.replace(
            original,
            # The spare lands BEFORE Battery, as a sibling -- so the added card
            # and the gated card are at different absolute indices and the gap
            # is mid-row for both.
            '<section class="card" data-state="light" aria-label="Spare">'
            '<h2 class="card-title">Spare</h2>'
            '<div class="card-body">unavailable</div></section>'
            '<section class="card" data-vehicle-gated data-state="battery-health"'
            ' aria-label="Battery">',
            1,
        )
        markup = _writeMarkup(html)
        expected = ["Home", "Alerts", "System Status", "Spare", "Fuel Trim", "Light"]

        surface = _boot(markupPath=markup)
        assert _visibleCards(surface) == expected
        # Seven cards, so seven dots exist; the gated one (absolute index 4) is
        # the only one absent.
        assert _visibleDots(surface) == [_dotLabel(i) for i in (0, 1, 2, 3, 5, 6)]

        for index, card in zip((0, 1, 2, 3, 5, 6), expected, strict=True):
            surface = _boot(markupPath=markup, steps=_clickDot(index))
            assert _landedCard(surface) == card, f"dot {index} did not reach {card}"
            assert _activeDot(surface) == _dotLabel(index)
