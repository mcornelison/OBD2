################################################################################
# File Name: test_carousel_card_set.py
# Purpose/Description: US-540-b (F-127) tests -- the card set goes 4 -> 6 for the
#   US-540-a legibility scale, and the merged "Health" card RETIRES. At hero 44 /
#   secondary 26 a card affords ~3 facts, so a container stacking three unrelated
#   readouts is exactly the thing the scale can no longer pay for. Battery, Fuel
#   Trim and Light each become a card again; the locked order is
#   Home . Alerts . System Status . Battery . Fuel Trim . Light.
#
#   The tests are written around the four ways this change could go wrong:
#     1. RETIREMENT LEAVING A GHOST -- the Health markup goes but its composer /
#        renderer stay behind, or vice versa. A branch no card can reach is not
#        harmless: nothing executes it, so nothing proves it still resolves
#        (US-500). Both halves are asserted absent, and the three facts are
#        asserted PRESENT on their own cards -- "Health is gone" is only half a
#        deliverable, and the half that is trivially true for the wrong reason.
#     2. THE FUEL-TRIM GATE REGRESSING TO A FABRICATION. US-507 moved the gate's
#        vocabulary from HIDING to SPEAKING ("no engine data"). Splitting the
#        card back out could quietly restore either the hide (which costs a
#        screen from the 6 the story locks) or, far worse, a rendered 0%.
#     3. A CARD-COUNT ASSUMPTION. The AC calls for a carousel that is
#        count-agnostic. That is asserted by RUNNING the shipped carousel over a
#        markup carrying a DIFFERENT number of cards -- a grep for "4" cannot
#        witness geometry, and the dot/card correspondence is the one thing the
#        visible-index math can get wrong invisibly.
#     4. CAPACITY SILENTLY GROWING BACK. The whole point of 6 cards is fewer
#        facts each; a ceiling is pinned on the RENDERED tile count so a later
#        edit cannot re-stack a card past what the scale affords.
#   The DOM assertions run the SHIPPED carousel.js over the SHIPPED markup and
#   resolve the SHIPPED stylesheet (tests/ui/render_harness.py), because a
#   correct routine the tick never calls renders nothing (US-494/US-495).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-540-b card set 4 -> 6, Health out.
# ================================================================================
################################################################################

"""US-540-b tests for the 6-card set (Health retired, facts redistributed)."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

# The CIO/Iris-locked card set for the legibility scale, in carousel order.
_CARD_SET = ["Home", "Alerts", "System Status", "Battery", "Fuel Trim", "Light"]

# The AC's capacity ceiling: ~3 facts, 4 in a 2x2. Pinned against the RENDERED
# tile count, which is what an operator actually has to read.
_FACT_CEILING = 4


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _trackMarkup(html: str) -> str:
    """Just the `<div id="track">` block -- the carousel's own card list.

    Scoped deliberately: `.card` also matches nothing else today, but a future
    overlay could borrow the class, and the ORDER assertion below is only
    meaningful against the element the track actually lays out.
    """
    start = html.index('<div id="track">')
    end = html.index("</main>", start)
    return html[start:end]


def _markupCardLabels(html: str) -> list[str]:
    """The aria-labels of the track's cards, in document order."""
    track = _trackMarkup(html)
    return [
        m.group(1)
        for m in re.finditer(
            r'<section class="card"[^>]*?aria-label="([^"]+)"', track, re.S
        )
    ]


def _now() -> str:
    """A timestamp the shipped freshness rules read as LIVE.

    The dashboard probe runs on the real wall clock (runDashboard injects no
    clock), and every one of these readouts grays itself once its `ts` ages
    past its staleness window. A fixed literal here would go stale the day
    after it was written and quietly turn every reading below into a typed NA
    -- a green suite over a panel of dashes.
    """
    return datetime.now(UTC).isoformat()


def _sysState(obdAvailable: bool = False) -> dict:
    """A system-status payload (US-400 / Atlas A-3 schema) + the US-496 gate."""
    return {
        "obdLink": {"state": "linked" if obdAvailable else "down", "retries": 0, "lastSeenS": 2},
        "sync": {"lastOkTs": _now(), "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "idle", "driveId": None},
        "source": {"obd": {"available": obdAvailable}},
        "idle": not obdAvailable,
        "ts": _now(),
    }


def _routes(obdAvailable: bool = False) -> dict:
    """A bench Pi with a live UPS + light feed and no stored codes."""
    return {
        "/system-status": _sysState(obdAvailable),
        # The US-401 emitter's schema (`vcellV`, `health`), not a paraphrase of
        # it: a payload with the wrong key names renders a card full of dashes
        # that still "paints", which is indistinguishable from a broken split.
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


def _visibleCards(surface: rh.Surface) -> list[str]:
    return [
        (path[-1]["attrs"].get("aria-label") or "?")
        for path in surface.pathsByClass("card")
        if surface.rendered(path)
    ]


def _visibleDots(surface: rh.Surface) -> int:
    return sum(1 for path in surface.pathsByClass("dot") if surface.rendered(path))


def _text(node: dict) -> str:
    """All text under a DOM node. Text lives in child `{"text": ...}` nodes, so
    reading `node["text"]` alone returns None for every element that has any --
    i.e. silently empty, which an absence assertion reads as a pass."""
    out = node.get("text") or ""
    for child in node.get("children") or []:
        out += _text(child)
    return out


def _cardText(surface: rh.Surface, className: str, card: str) -> str:
    """The rendered text of every `className` element inside one named card."""
    return "".join(
        _text(path[-1])
        for path in surface.pathsByClass(className)
        if surface.rendered(path) and _cardOf(path) == card
    )


def _cardOf(path: list[dict]) -> str | None:
    """The aria-label of the nearest `.card` ancestor of a rendered element."""
    for node in reversed(path[:-1]):
        classes = (node.get("attrs", {}).get("class") or "").split()
        if "card" in classes:
            return node["attrs"].get("aria-label")
    return None


# --- the card set itself ----------------------------------------------------


class TestCardSet:
    """The locked 6-card set, read off the shipped markup."""

    def test_theTrackCarriesTheSixLockedCardsInOrder(self):
        """
        Given: the shipped dashboard markup
        Then: exactly the 6 locked cards, in the locked order

        Pinned as an ORDERED LIST rather than a set + a count, because the order
        IS half the deliverable (Alerts moves to second) and a set assertion
        would go green on a carousel that opens on Light.
        """
        assert _markupCardLabels(_read(_HTML)) == _CARD_SET

    def test_theHealthCardIsGoneFromTheMarkup(self):
        """
        Given: the shipped dashboard markup
        Then: no Health card, and no multi-source `data-states` card at all

        `data-states` was introduced BY the merge and consumed by nothing else,
        so its absence is the structural half of the retirement -- a Health card
        renamed to something else would still trip this.
        """
        html = _read(_HTML)
        assert "Health" not in _markupCardLabels(html)
        assert "data-states" not in _trackMarkup(html), (
            "a multi-source card survived the retirement"
        )

    def test_theThreeRetiredFactsEachDeclareTheirOwnStateFile(self):
        """
        Given: the shipped dashboard markup
        Then: Battery / Fuel Trim / Light each carry their own `data-state`

        "Health is gone" is trivially true if the facts went with it. The
        redistribution is what makes the retirement honest, so it is asserted
        POSITIVELY, per source file.
        """
        track = _trackMarkup(_read(_HTML))
        for label, state in [
            ("Battery", "battery-health"),
            ("Fuel Trim", "ltft-trend"),
            ("Light", "light"),
        ]:
            pattern = r'<section class="card"[^>]*?aria-label="' + label + r'"'
            match = re.search(pattern, track, re.S)
            assert match is not None, f"no {label} card"
            assert 'data-state="' + state + '"' in match.group(0), (
                f"the {label} card does not consume states/{state}"
            )


class TestNoOrphanedHealthCode:
    """The renderer half of the retirement (US-500: unreachable != harmless)."""

    def test_theMergedHealthComposerAndRendererAreGone(self):
        """
        Given: the shipped carousel.js
        Then: no healthCardView / renderHealthCard / renderHealthSection left

        US-507's own notes make this the rule: the ltft-trend branch was DELETED
        rather than left unreachable, because nothing executes dead code and so
        nothing proves it still resolves. Retiring the card has to take its
        composer with it.
        """
        js = _read(_JS)
        for gone in ["healthCardView", "renderHealthCard", "renderHealthSection"]:
            assert gone not in js, f"{gone} outlived the card it served"

    def test_theTickHasNoMultiSourceCardBranch(self):
        """
        Given: the shipped carousel.js
        Then: the tick no longer reads a `data-states` group

        The group branch existed for exactly one card. Left in place it is a
        path no markup can enter -- and it is the path that used to bypass the
        per-card availability handling, so a future `data-states` typo would
        silently take it.
        """
        assert 'getAttribute("data-states")' not in _read(_JS)


# --- the rendered surface ---------------------------------------------------


@_NODE_ONLY
class TestRenderedCardSet:
    """Six cards through the real cascade, with the real carousel booted."""

    def test_sixCardsPaintOnABench(self):
        """
        Given: a bench Pi (no vehicle), every Pi-local feed live
        Then: all six cards paint, in the locked order

        The markup test above proves the order was AUTHORED; this proves it
        SURVIVES the boot -- the vehicle gate, the home-slot face swap and the
        [hidden] guard all get a vote before an operator sees a card.
        """
        dom = rh.runDashboard(routes=_routes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        assert _visibleCards(surface) == _CARD_SET

    def test_oneDotPerVisibleCard(self):
        """
        Given: the booted six-card carousel
        Then: exactly one page dot paints per visible card

        A dot that navigates nowhere is a dead affordance. This is the geometry
        assertion the AC's "carousel handles N cards (no nav rework)" rests on,
        and it is invisible to every pure-function test.
        """
        dom = rh.runDashboard(routes=_routes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        cards = _visibleCards(surface)
        assert cards, "no cards painted at all"
        assert _visibleDots(surface) == len(cards), (
            f"{_visibleDots(surface)} dots for {len(cards)} visible cards {cards}"
        )

    def test_noCardExceedsTheFactCeiling(self):
        """
        Given: the booted six-card carousel on a bench
        Then: no card renders more than 4 fact tiles

        The REASON for six cards. Without a ceiling the split is cosmetic: a
        later story re-stacks a card and the legibility the scale bought is
        spent again, with a green suite the whole way.
        """
        dom = rh.runDashboard(routes=_routes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        counts: dict[str, int] = {}
        for path in surface.pathsByClass("tile"):
            if not surface.rendered(path):
                continue
            owner = _cardOf(path)
            if owner is not None:
                counts[owner] = counts.get(owner, 0) + 1
        assert counts, "no tiles painted at all -- the probe is not seeing the cards"
        over = {k: v for k, v in counts.items() if v > _FACT_CEILING}
        assert not over, f"cards over the {_FACT_CEILING}-fact ceiling: {over}"


@_NODE_ONLY
class TestFuelTrimGateSurvivesTheSplit:
    """The gate keeps SPEAKING; it neither hides nor fabricates."""

    def test_aBenchPaintsTheFuelTrimCardGatedNotAReading(self):
        """
        Given: a bench Pi -- system-status reports source.obd.available false
        Then: the Fuel Trim CARD paints, carrying `data-gated="true"`

        US-507 moved this gate from hiding to speaking, and that stays: the
        story locks SIX cards, so a card that vanishes on the bench (which is
        where the CIO reads the panel most days) breaks the set. Asserted
        POSITIVELY on the surface that carries it -- "no trim is shown" would
        be true for the wrong reason if the card disappeared entirely.
        """
        dom = rh.runDashboard(routes=_routes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        assert "Fuel Trim" in _visibleCards(surface)
        gated = [
            path[-1]["attrs"].get("data-gated")
            for path in surface.pathsByClass("card")
            if surface.rendered(path)
            and path[-1]["attrs"].get("aria-label") == "Fuel Trim"
        ]
        assert gated == ["true"], f"the fuel-trim gate did not paint: {gated}"

    def test_theGatedFuelTrimCardShowsNoPercentage(self):
        """
        Given: a bench Pi with a stale ltft-trend file left from the last drive
        Then: the Fuel Trim card renders no percent reading at all

        The failure this gate exists to prevent is a confident trim painted for
        an engine that is not running. `data-gated` proves the gate FIRED; this
        proves nothing leaked past it.
        """
        routes = _routes(obdAvailable=False)
        # A payload the view WOULD render (the US-420 emitter's schema, fresh
        # enough to clear the staleness guard) -- the point is that the gate,
        # not the data's age, is what withholds it.
        routes["/ltft-trend"] = {
            "sufficient": True,
            "level": "ok",
            "trend": "improving",
            "minDrives": 2,
            "current": {"ltftAvg": -2.5},
            "points": [{"driveId": 31, "ltftAvg": -2.5, "level": "ok"}],
            "ts": _now(),
        }
        dom = rh.runDashboard(routes=routes)
        surface = rh.dashboardSurface(dom["tree"])
        # An absence check is only evidence once the thing it looks at exists:
        # with no Fuel Trim card the text below is "" and passes for the wrong
        # reason, which is precisely how a retired card reads as a fixed gate.
        assert "Fuel Trim" in _visibleCards(surface), "nothing to look at"
        text = _cardText(surface, "card-body", "Fuel Trim")
        assert "%" not in text, f"a gated fuel trim leaked a reading: {text!r}"
        assert "2.5" not in text, f"a gated fuel trim leaked its trend: {text!r}"
        assert "no engine data" in text, f"the gate did not speak: {text!r}"

    def test_theBatteryAndLightCardsStayLiveBesideTheGate(self):
        """
        Given: the same bench (fuel trim gated)
        Then: Battery and Light still render real readings

        Independence was the merged card's hardest property to keep; splitting
        must not lose it in the other direction, where one card's gate is
        allowed to speak for its neighbours.
        """
        dom = rh.runDashboard(routes=_routes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        live = {
            owner: _cardText(surface, "tile-value", owner)
            for owner in ("Battery", "Light")
        }
        assert "4.02" in live["Battery"], f"battery reading absent: {live['Battery']!r}"
        assert "120" in live["Light"], f"light reading absent: {live['Light']!r}"


# --- count-agnosticism (the Atlas gate DoD) ---------------------------------


@_NODE_ONLY
class TestCarouselIsCountAgnostic:
    """Proven by RUNNING a different card count, not by reading the source."""

    def _withExtraCards(self, tmpPath: str, extra: int) -> str:
        """The shipped markup with `extra` more cards spliced into the track."""
        html = _read(_HTML)
        clone = "".join(
            f'<section class="card" data-state="light" aria-label="Spare {i}">'
            f'<h2 class="card-title">Spare {i}</h2>'
            '<div class="card-body">unavailable</div></section>'
            for i in range(extra)
        )
        anchor = "    </div>\n  </main>"
        assert anchor in html, "the track's closing tag moved -- fixture is stale"
        out = html.replace(anchor, clone + anchor, 1)
        with open(tmpPath, "w", encoding="utf-8") as fh:
            fh.write(out)
        return tmpPath

    @pytest.mark.parametrize("extra", [1, 3])
    def test_dotsFollowTheCardCount(self, tmp_path, extra):
        """
        Given: the shipped carousel booted over a markup with N+extra cards
        Then: it builds one dot per card and paints every one of them

        The AC asks for a carousel that "scales to N cards (verified
        count-agnostic)". Reading the source for a literal 4 cannot verify
        that -- a hard-coded count could just as easily live in the CSS, the
        dot loop or the translate math. Booting a different count does.
        """
        markup = self._withExtraCards(str(tmp_path / "many.html"), extra)
        dom = rh.runDashboard(routes=_routes(), markupPath=markup)
        surface = rh.Surface(dom["tree"], _read(_CSS))
        cards = _visibleCards(surface)
        assert len(cards) == len(_CARD_SET) + extra, cards
        assert _visibleDots(surface) == len(cards), (
            f"{_visibleDots(surface)} dots for {len(cards)} cards"
        )

    @pytest.mark.parametrize("count", [4, 6, 7, 9])
    def test_theNavMathHasNoBuiltInCardCount(self, count):
        """
        Given: the pure nav helpers at several card counts
        Then: every helper derives its range from `count`, never from a literal

        The DOM test above proves the wiring; this proves the arithmetic under
        it, at counts either side of the 4 that shipped and the 6 that lands.
        The two helpers deliberately differ and BOTH are pinned: `clampIndex`
        CLAMPS at the ends (it is the goTo/dot-tap guard, where a wrap would
        turn a mis-tap into a jump across the carousel), while
        `nextVisibleIndex` WRAPS (US-506 -- a swipe off the last card returns
        to the first). Asserting one contract for both would have hidden a real
        break in whichever helper was not being described.
        """
        flags = [False] * count
        assert _view("clampIndex", count - 1, count) == count - 1
        assert _view("clampIndex", count, count) == count - 1, "must clamp, not wrap"
        assert _view("clampIndex", -1, count) == 0
        assert _view("nextVisibleIndex", count - 1, 1, flags) == 0, "forward wrap"
        assert _view("nextVisibleIndex", 0, -1, flags) == count - 1, "backward wrap"
        assert _view("visualPosition", count - 1, flags) == count - 1


@_NODE_ONLY
class TestStylesheetHasNoCardCountCap:
    """The Iris presentation-lane half of the Atlas gate DoD."""

    def test_theTrackAndCardsCarryNoFourCardAssumption(self):
        """
        Given: the shipped stylesheet
        Then: no `#track` width and no `.card` nth-child rule

        The flex row sizes itself from `.card { flex: 0 0 100% }`. A `#track`
        width (the classic `400%`) or an nth-child rule would each cap the set
        at whatever count was current when it was written, and the failure is
        silent: the 5th card simply never gets a slot.
        """
        css = _read(_CSS)
        block = css[css.index("#track {") : css.index("}", css.index("#track {"))]
        assert "width" not in block, f"#track pins a width: {block!r}"
        assert not re.search(r"\.card[^{,]*:nth-child", css), (
            "an nth-child rule caps the card set"
        )

    def test_everyCardTakesAFullSlot(self):
        """
        Given: the shipped stylesheet
        Then: `.card` is `flex: 0 0 100%`

        This single declaration is what makes the track count-agnostic. Pinned
        because the count-agnosticism above is a CONSEQUENCE of it, and a test
        that only asserts the consequence cannot say what broke.
        """
        css = _read(_CSS)
        block = css[css.index("\n.card {") : css.index("}", css.index("\n.card {"))]
        assert "flex: 0 0 100%" in block, f".card lost its full-width slot: {block!r}"
