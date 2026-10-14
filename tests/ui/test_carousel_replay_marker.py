################################################################################
# File Name: test_carousel_replay_marker.py
# Purpose/Description: US-901-b (F-162) -- the panel marks itself whenever it is
#   not showing the live car. system-status.runMode (live / simulate / replay)
#   and obd-live.dataSource (US-874) are the two inputs; either one saying "not
#   live" raises a marker over the top bar's centre slot, and the wall clock
#   under it is hidden while it shows (a wall clock is wrong for replayed data).
#
#   WHAT IS GUARDED, and how:
#     1. The DECISION (`notLiveMarker`) through the node probe: every case the
#        story names, including the fault case where the two inputs disagree.
#     2. The PAINT through the render harness: the shipped carousel.js over the
#        shipped markup, the shipped stylesheet resolved over the result.
#     3. The STACKING from the stylesheet, not from a computed rect -- the
#        harness resolves the cascade and does NOT do layout (render_harness.py
#        FIDELITY LIMITS). The z-order guard is proven to fail on a planted
#        z-index 99 rule, so it is a guard and not a tautology.
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-901-b)| Initial -- decision, paint, z-order, placement.
# ================================================================================
################################################################################

"""US-901-b: the REPLAY / SIM / NOT LIVE marker over the top bar."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

import pytest

from pi.splash.system_status_emitter import buildSystemStatusState
from tests.ui import render_harness as rh
from tests.ui.css_type_scale import readCss, ruleBlock

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_CSS_PATH = os.path.join(rh.DASHBOARD_DIR, "dashboard.css")
_HTML_PATH = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")

pytestmark = pytest.mark.skipif(_NODE is None, reason="node not on PATH")

PANEL = (480, 320)
MARKER_ID = "not-live-marker"
CLOCK_ID = "topbar-clock"


def _marker(sysData: Any, obdLive: Any) -> Any:
    """Evaluate the shipped `notLiveMarker` decision via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, "notLiveMarker", json.dumps(sysData), json.dumps(obdLive)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _sys(runMode: str | None = "live") -> dict:
    """A system-status payload from the SHIPPED builder, never hand-written.

    ``runMode=None`` deletes the key, modelling an older emitter.
    """
    payload = buildSystemStatusState(
        obdLinkState="linked",
        obdRetries=0,
        obdLastSeenS=1,
        syncLastOkTs="2026-10-14T12:00:00Z",
        syncRows=10,
        syncPending=None,
        syncStale=False,
        powerSource="external",
        driveState="recording",
        driveId=7,
        nowIso="2026-10-14T12:00:01Z",
        runMode=runMode if runMode is not None else "live",
    )
    if runMode is None:
        del payload["runMode"]
    return payload


def _obdLive(dataSource: str | None) -> dict:
    """A states/obd-live payload in the US-874 shape."""
    return {"params": {}, "dataSource": dataSource, "ts": "2026-10-14T12:00:01Z"}


# --------------------------------------------------------------- the decision


class TestTheDecision:
    """`notLiveMarker(systemStatus, obdLive)` -> null or {text, tier}."""

    @pytest.mark.parametrize(
        ("runMode", "dataSource", "expected"),
        [
            ("replay", None, "REPLAY"),
            ("simulate", None, "SIM"),
            # Atlas S-3: the two inputs disagree -> a fault, still marked.
            ("live", "replay", "REPLAY"),
            ("live", "physics_sim", "SIM"),
            ("bogus", None, "NOT LIVE"),
            ("live", "fixture", "NOT LIVE"),
            # Replay rides the --simulate seam; replay still wins.
            ("replay", "physics_sim", "REPLAY"),
            ("simulate", "replay", "REPLAY"),
        ],
    )
    def test_notLive_namesTheMode(self, runMode, dataSource, expected) -> None:
        """
        Given: a runMode and/or a dataSource that says the data is not live
        When: the marker is decided
        Then: it names the mode -- REPLAY over SIM over NOT LIVE
        """
        obdLive = _obdLive(dataSource) if dataSource is not None else None
        result = _marker(_sys(runMode), obdLive)

        assert result is not None
        assert result["text"] == expected

    def test_live_andReal_raisesNoMarker(self) -> None:
        """
        Given: production -- runMode live, dataSource real
        When: the marker is decided
        Then: no marker
        """
        assert _marker(_sys("live"), _obdLive("real")) is None

    def test_neitherKey_raisesNoMarker(self) -> None:
        """
        Given: payloads that carry neither runMode nor dataSource
        When: the marker is decided
        Then: no marker (an older emitter is not a claim of non-live data)
        """
        assert _marker(_sys(None), {"params": {}}) is None
        assert _marker(None, None) is None

    def test_nullDataSource_isNotRead_notNonLive(self) -> None:
        """
        Given: obd-live with dataSource null -- the producer's "no logger has
            resolved a tag yet", which a live boot publishes before capture
        When: the marker is decided
        Then: no marker. null means not read (sprint constraint), so it makes
            no claim either way; marking it would flag the live car at boot.
        """
        assert _marker(_sys("live"), _obdLive(None)) is None

    def test_tiers_notLiveIsTheMetaSize(self) -> None:
        """
        Given: each marker text
        When: decided
        Then: REPLAY and SIM ride the label tier, NOT LIVE the meta tier
        """
        assert _marker(_sys("replay"), None)["tier"] == "label"
        assert _marker(_sys("simulate"), None)["tier"] == "label"
        assert _marker(_sys("bogus"), None)["tier"] == "meta"

    def test_noMarkerIsWiderThanReplay(self) -> None:
        """
        Given: every marker the decision can produce
        When: each is charged characters x its tier's font size
        Then: none exceeds REPLAY at --fs-label (the ~100-110 px centre slot)

        A MODEL, stated: the harness does no layout, so this charges every
        glyph the same advance per px of font size. It is what makes "NOT LIVE
        at --fs-meta fits the same box" a checked claim rather than a hope.
        """
        css = readCss(_CSS_PATH)
        px = {tier: _tokenPx(css, f"fs-{tier}") for tier in ("label", "meta")}
        budget = len("REPLAY") * px["label"]
        for runMode in ("replay", "simulate", "bogus"):
            result = _marker(_sys(runMode), None)
            charged = len(result["text"]) * px[result["tier"]]
            assert charged <= budget, (result, charged, budget)


# ------------------------------------------------------------------ the paint


def _render(sysData: dict | None, obdLive: dict | None) -> rh.Surface:
    """Boot the SHIPPED carousel over the SHIPPED markup at the panel size."""
    routes: dict[str, Any] = {}
    if sysData is not None:
        routes["/system-status"] = sysData
    if obdLive is not None:
        routes["/obd-live"] = obdLive
    tree = rh.runDashboard(routes=routes, steps=[{"flush": 4}], viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _markerShown(surface: rh.Surface) -> bool:
    path = surface.pathById(MARKER_ID)
    assert path is not None, "#not-live-marker missing from the rendered DOM"
    return surface.rendered(path)


def _clockMasked(surface: rh.Surface) -> bool:
    path = surface.pathById(CLOCK_ID)
    assert path is not None, "#topbar-clock missing from the rendered DOM"
    winner = surface.winningDeclaration(path, "visibility")
    return winner is not None and winner[0] == "hidden"


def _text(path: list[dict]) -> str:
    return "".join(
        child.get("text", "") for child in path[-1].get("children", []) if "tag" not in child
    ).strip()


class TestThePaint:
    """The marker and the clock, as the shipped JS + CSS leave them."""

    def test_replay_markerPaints_clockHidden_fixedAndUntappable(self) -> None:
        """
        Given: system-status {runMode: 'replay'}
        When: the carousel renders
        Then: the marker paints REPLAY, #topbar-clock is hidden, and the
            marker's resolved style is position fixed, pointer-events none
        """
        surface = _render(_sys("replay"), None)

        assert _markerShown(surface)
        path = surface.pathById(MARKER_ID)
        assert _text(path) == "REPLAY"
        assert _clockMasked(surface)
        assert surface.winningDeclaration(path, "position")[0] == "fixed"
        assert surface.winningDeclaration(path, "pointer-events")[0] == "none"

    @pytest.mark.parametrize(
        ("sysData", "obdLive", "expected"),
        [
            (_sys("simulate"), None, "SIM"),
            (_sys("live"), _obdLive("replay"), "REPLAY"),
            (_sys("live"), _obdLive("physics_sim"), "SIM"),
            (_sys("bogus"), None, "NOT LIVE"),
        ],
    )
    def test_nonLive_markerPaintsItsText_andHidesTheClock(
        self, sysData, obdLive, expected
    ) -> None:
        """
        Given: a non-live input
        When: the carousel renders
        Then: the marker paints its text and the clock is hidden
        """
        surface = _render(sysData, obdLive)

        assert _markerShown(surface)
        assert _text(surface.pathById(MARKER_ID)) == expected
        assert _clockMasked(surface)

    @pytest.mark.parametrize(
        ("sysData", "obdLive"),
        [
            (_sys("live"), _obdLive("real")),
            (_sys(None), {"params": {}}),
            (None, None),
        ],
    )
    def test_live_noMarker_clockShows(self, sysData, obdLive) -> None:
        """
        Given: production, or payloads with neither key, or no files at all
        When: the carousel renders
        Then: no marker paints and the clock is NOT hidden -- the clock is
            hidden exactly when the marker is present
        """
        surface = _render(sysData, obdLive)

        assert not _markerShown(surface)
        assert not _clockMasked(surface)

    def test_notLive_metaTierResolvesToFsMeta(self) -> None:
        """
        Given: an unrecognised runMode
        When: the carousel renders
        Then: the marker's font size resolves to var(--fs-meta)
        """
        surface = _render(_sys("bogus"), None)

        path = surface.pathById(MARKER_ID)
        assert surface.winningDeclaration(path, "font-size")[0] == "var(--fs-meta)"

    def test_maskedClockKeepsItsBox_soNoTopbarChildMoves(self) -> None:
        """
        Given: the marker showing
        When: the clock is hidden
        Then: it is hidden by visibility, never display -- #topbar is a
            three-track grid, and a clock with no box would let the right
            cluster fall into the centre track
        """
        surface = _render(_sys("replay"), None)

        path = surface.pathById(CLOCK_ID)
        assert surface.displayOf(path)[0] != "none"


# ------------------------------------------------------------ the stylesheet


_Z_INDEX = re.compile(r"z-index\s*:\s*(-?\d+)")


def _stripComments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _zOrderViolation(css: str) -> str | None:
    """Why the marker is NOT above every other declared z-index, else None.

    Every rule in the sheet is read (comments stripped), so an overlay added
    anywhere -- setup menu, sys-detail, dtc-detail, dtc-takeover, the coming
    R31 takeover -- is covered the day it is added.
    """
    rules = rh.parseCss(_stripComments(css))
    markerZ: list[int] = []
    otherZ: list[tuple[int, str]] = []
    for rule in rules:
        for value in _Z_INDEX.findall(rule.declarations):
            if rule.selector.strip() == f"#{MARKER_ID}":
                markerZ.append(int(value))
            else:
                otherZ.append((int(value), rule.selector.strip()))
    if len(markerZ) != 1:
        return f"expected one z-index on #{MARKER_ID}, found {markerZ}"
    highest = max(otherZ)
    if markerZ[0] <= highest[0]:
        return f"#{MARKER_ID} z-index {markerZ[0]} is not above {highest[1]} ({highest[0]})"
    return None


def _tokenPx(css: str, name: str) -> float:
    match = re.search(rf"--{re.escape(name)}:\s*(\d+(?:\.\d+)?)px", css)
    assert match is not None, f"--{name} px token not found"
    return float(match.group(1))


class TestTheStylesheet:
    """Stacking, placement and look -- asserted from the sheet (no layout)."""

    def test_markerIsAboveEveryOtherDeclaredZIndex(self) -> None:
        """
        Given: the shipped dashboard.css
        When: every declared z-index is collected
        Then: the marker's is the greatest
        """
        assert _zOrderViolation(readCss(_CSS_PATH)) is None

    def test_zOrderGuard_failsOnAPlantedOverlayAbove(self) -> None:
        """
        Given: a copy of dashboard.css with a test rule at z-index 99 added
        When: the z-order guard runs
        Then: it reports the violation -- the guard is shown to FAIL when broken
        """
        planted = readCss(_CSS_PATH) + "\n#planted-overlay { z-index: 99; }\n"

        violation = _zOrderViolation(planted)

        assert violation is not None
        assert "#planted-overlay" in violation

    def test_markerIsADirectChildOfBody(self) -> None:
        """
        Given: the shipped markup
        When: the marker is located
        Then: it is a direct child of body -- a child of #topbar (z 10, a
            stacking context) could never paint above the overlays
        """
        tree = rh.parseMarkup(_HTML_PATH)
        ids = [child.get("attrs", {}).get("id") for child in rh.bodyChildren(tree)]
        assert MARKER_ID in ids

    def test_markerShipsHidden(self) -> None:
        """
        Given: the shipped markup
        When: read before any JS runs
        Then: the marker carries `hidden`; it only appears on a non-live read
        """
        tree = rh.parseMarkup(_HTML_PATH)
        marker = next(
            child
            for child in rh.bodyChildren(tree)
            if child.get("attrs", {}).get("id") == MARKER_ID
        )
        assert "hidden" in marker["attrs"]

    def test_markerSitsOverTheBarsCentreSlot(self) -> None:
        """
        Given: the marker rule
        When: read
        Then: fixed at top 0, --bar-h tall, centred on the bar's centre
        """
        block = ruleBlock(readCss(_CSS_PATH), f"#{MARKER_ID}")
        assert re.search(r"position:\s*fixed", block)
        assert re.search(r"top:\s*0\b", block)
        assert re.search(r"height:\s*var\(--bar-h\)", block)
        assert re.search(r"left:\s*50%", block)
        assert re.search(r"transform:\s*translateX\(-50%\)", block)
        assert re.search(r"pointer-events:\s*none", block)

    def test_markerLook_isAModeNotASeverity(self) -> None:
        """
        Given: the marker rule
        When: read
        Then: --text-primary on --bg, --font-display at --fs-label, and no
            state colour and no --accent
        """
        block = ruleBlock(readCss(_CSS_PATH), f"#{MARKER_ID}")
        assert re.search(r"(?<!-)color:\s*var\(--text-primary\)", block)
        assert re.search(r"background:\s*var\(--bg\)", block)
        assert re.search(r"font-family:\s*var\(--font-display\)", block)
        assert re.search(r"font-size:\s*var\(--fs-label\)", block)
        for forbidden in ("--accent", "--amber", "--red", "--green"):
            assert forbidden not in block, forbidden
