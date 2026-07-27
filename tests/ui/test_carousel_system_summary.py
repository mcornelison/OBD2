################################################################################
# File Name: test_carousel_system_summary.py
# Purpose/Description: US-489 (Iris polish P-1) tests for the System Status
#   card's glanceability pass: an honest top SUMMARY line, the 2x2 tile grid,
#   and the per-tile status dot. Presentation-only over the SHIPPED US-400
#   state -- no new emitter data, no new contract.
#
#   The load-bearing invariant is honest-instrument F-1 restated at the CARD
#   level: the summary is green ONLY when every source is genuinely good. A
#   summary line is a lossy compression of four tiles, so it is exactly the
#   place a "green when broken" lie gets introduced -- these tests pin every
#   path that must NOT reach `ok`, including a level the mapper does not
#   recognise (which resolves to unavailable, never to green).
#
#   The colour half is compared as PARSED token references (never hardcoded
#   hexes) and the dot mapping is asserted to MIRROR the existing
#   `.tile[data-level] .tile-value` mapping -- notably `down`, which US-488
#   (TD-067) just swept to amber. A red dot here would re-open that debt one
#   sprint after it was closed.
#
#   The DOM half is asserted against the carousel.js source: the grid + dot are
#   CSS classes the JS must actually emit, so a CSS-only change would style
#   markup that never renders (the cross-file trap US-484-a/b and US-488 all hit).
#   The on-panel 480x320 render stays a PI-RUNTIME gate (story validationCriteria).
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial -- US-489 System Status glanceability.
# ================================================================================
################################################################################

"""US-489 tests for the System Status summary line, 2x2 grid and status dots."""

import json
import os
import shutil
import subprocess

import pytest

# Reuse the canonical CSS parsers rather than re-implementing them: `_ruleBlock`
# is line-anchored so a descendant rule can never be mistaken for the base rule
# it overrides, and `_tokenValue` reads real declarations only (not a token
# named in a prose comment).
from tests.ui.test_dashboard_stop_tier_safety import _read, _ruleBlock, _tokenValue

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_UI = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "UI")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dist", "dashboard-pi")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")

# tokens.css -- RESERVED for the brand mark alone (Spool S-2 / TD-067).
_BRAND_REDS = ("var(--red)", "var(--red-light)", "var(--red-dark)")


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against N fixtures via the node probe.

    `encoding` is pinned to utf-8 on purpose: node writes UTF-8, but `text=True`
    alone decodes with the Windows locale codepage, which turns the summary
    line's "·" separator into "Â·" and silently corrupts any non-ASCII copy
    under test. (The sibling probe helpers share the omission -- see TD-068.)
    """
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _tile(level: str, label: str = "OBD LINK", value: str = "LINKED") -> dict:
    return {"label": label, "value": value, "detail": "", "level": level}


def _tiles(obd: str = "ok", sync: str = "ok", power: str = "ok", drive: str = "ok") -> dict:
    """The 4 System Status tiles, addressed by level so a test reads as a state."""
    return {
        "obdLink": _tile(obd, "OBD LINK", "LINKED"),
        "sync": _tile(sync, "SYNC", "OK"),
        "power": _tile(power, "POWER", "CAR"),
        "drive": _tile(drive, "DRIVE", "REC"),
    }


def _sysState(**over: object) -> dict:
    """A healthy system-status emitter payload (US-400 / Atlas A-3 schema)."""
    state = {
        "obdLink": {"state": "linked", "retries": 0, "lastSeenS": 2},
        "sync": {"lastOkTs": "2026-07-27T19:41:50Z", "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "recording", "driveId": 27},
        "ts": "2026-07-27T19:42:00Z",
    }
    state.update(over)
    return state


_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


# ---------------------------------------------------------------------------
# AC1 -- the summary line is GREEN only when every source is genuinely good.
# This is honest-instrument F-1 hoisted to the card level: the one-glance line
# is a lossy compression of 4 tiles, so it is precisely where a green-when-
# broken lie would enter.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemSummary_allSourcesGood_readsSystemOk():
    """The positive control -- green IS reachable, or the line means nothing."""
    summary = _view("systemSummary", _tiles())
    assert summary["text"] == "SYSTEM · OK"
    assert summary["level"] == "ok"
    assert summary["issues"] == 0


@_NODE_TESTS
def test_systemSummary_driveIdleIsNominal_stillReadsOk():
    """DRIVE=IDLE is the ONLY `neutral` tile the card produces, and it means
    "not recording", not "something is wrong". Counting it as a fault would make
    the green summary unreachable in the single most common state -- key on,
    no drive started -- which is its own dishonesty (crying wolf)."""
    summary = _view("systemSummary", _tiles(drive="neutral"))
    assert summary["level"] == "ok"
    assert summary["issues"] == 0


@_NODE_TESTS
def test_systemSummary_oneAmberSource_neverGreen():
    """A reconnecting OBD link -> the summary reports the ISSUE COUNT (the
    glanceable fact) and NAMES the worst source in its detail."""
    tiles = _tiles(obd="amber")
    tiles["obdLink"]["value"] = "RECONNECTING"
    summary = _view("systemSummary", tiles)
    assert summary["text"] == "SYSTEM · 1 ISSUE"
    assert summary["level"] == "amber"
    assert summary["issues"] == 1
    assert "RECONNECTING" in summary["detail"]
    assert "OBD LINK" in summary["detail"]


@_NODE_TESTS
def test_systemSummary_twoDegradedSources_countsBothAndPluralises():
    summary = _view("systemSummary", _tiles(obd="amber", sync="amber"))
    assert summary["text"] == "SYSTEM · 2 ISSUES"
    assert summary["issues"] == 2
    assert summary["level"] != "ok"


@_NODE_TESTS
def test_systemSummary_downSource_isAnIssueAndNeverGreen():
    """A DOWN link is a genuine issue. Its LEVEL stays `down` so the card keeps
    one level->hue mapping (US-488 renders `down` amber; the summary does not
    re-decide that hue for itself)."""
    summary = _view("systemSummary", _tiles(obd="down"))
    assert summary["issues"] == 1
    assert summary["level"] == "down"
    assert summary["level"] != "ok"


@_NODE_TESTS
def test_systemSummary_worstStateWins_notTheFirstOne():
    """With an amber ahead of a down in display order, the summary must still
    report the DOWN -- "worst", not "first"."""
    summary = _view("systemSummary", _tiles(obd="amber", power="down"))
    assert summary["level"] == "down"
    assert "POWER" in summary["detail"]
    assert summary["issues"] == 2


@_NODE_TESTS
def test_systemSummary_unavailableOnly_isNotGreenAndNotAnIssue():
    """Parked with the car off: the OBD source is honestly UNREADABLE. That is a
    known-unknown -- it must not read green (we cannot claim OK over a source we
    cannot see) and must not read as a fault (nothing is broken)."""
    summary = _view("systemSummary", _tiles(obd="unavailable", drive="neutral"))
    assert summary["level"] == "unavailable"
    assert summary["level"] != "ok"
    assert summary["issues"] == 0
    assert "UNAVAILABLE" in summary["text"]


@_NODE_TESTS
def test_systemSummary_realIssueOutranksAnUnknown():
    """An unreadable source must never mask a known fault."""
    summary = _view("systemSummary", _tiles(obd="unavailable", sync="amber"))
    assert summary["level"] == "amber"
    assert summary["issues"] == 1
    assert "SYNC" in summary["detail"]


@_NODE_TESTS
def test_systemSummary_unrecognisedLevel_resolvesUnavailableNeverOk():
    """Fail-closed on an unknown vocabulary: a level this mapper does not know
    is an unknown, NOT a pass. The alternative (default ok) is the exact shape
    of a green-when-broken bug introduced by a future tile level."""
    summary = _view("systemSummary", _tiles(sync="banana"))
    assert summary["level"] != "ok"
    assert summary["level"] == "unavailable"


@_NODE_TESTS
def test_systemSummary_nonObject_isUnavailableNeverOk():
    """A missing/malformed state -> the summary is unavailable, never green."""
    for bad in (None, "x", []):
        summary = _view("systemSummary", bad)
        assert summary["level"] == "unavailable"
        assert summary["issues"] == 0


# ---------------------------------------------------------------------------
# AC1 (wiring) -- the assembled view carries the summary, computed from the
# SAME tiles it renders, so the line and the grid can never disagree.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemStatusView_healthyState_carriesGreenSummary():
    view = _view("systemStatusView", _sysState())
    assert view["summary"]["text"] == "SYSTEM · OK"
    assert view["summary"]["level"] == "ok"


@_NODE_TESTS
def test_systemStatusView_degradedState_summaryIsNotGreen():
    """The F-1 fixture from US-400: every source degraded. The new summary line
    must not become the one green thing on a fully-degraded card."""
    view = _view(
        "systemStatusView",
        _sysState(
            obdLink={"state": "down", "retries": 0, "lastSeenS": None},
            sync={"lastOkTs": None, "rows": 0, "pending": 12, "stale": True},
            power={"mode": "car", "source": "battery"},
            drive={"state": "idle", "driveId": None},
        ),
    )
    assert view["summary"]["level"] != "ok"
    assert view["summary"]["issues"] == 3


@_NODE_TESTS
def test_systemStatusView_obdSourceUnavailable_summaryNotGreen():
    """US-429 honest-availability: a typed-NA OBD tile must pull the summary off
    green -- the card cannot claim OK while a source is unreadable."""
    view = _view(
        "systemStatusView",
        _sysState(source={"obd": {"available": False, "reason": "OBD: off"}}),
    )
    assert view["tiles"]["obdLink"]["value"] == "NA"
    assert view["summary"]["level"] != "ok"


@_NODE_TESTS
def test_systemStatusView_summaryMatchesItsOwnTiles():
    """SSOT proof: the summary is derived from the rendered tiles, not from a
    second read of the state -- so the headline can never contradict the grid."""
    state = _sysState(power={"mode": "car", "source": "battery"})
    view = _view("systemStatusView", state)
    assert view["summary"] == _view("systemSummary", view["tiles"])


@_NODE_TESTS
def test_systemStatusView_preservesEveryTileValueAndDetail():
    """AC2 guard: the 2x2 regrouping is PRESENTATION -- all 4 tiles survive with
    their value AND their detail (nothing is dropped to make room)."""
    view = _view("systemStatusView", _sysState())
    assert set(view["tiles"].keys()) == {"obdLink", "sync", "power", "drive"}
    for tile in view["tiles"].values():
        assert tile["value"]
        assert tile["detail"]
        assert tile["level"]


# ---------------------------------------------------------------------------
# AC2 -- the 2x2 grid. Two columns, and the shipped stacked tile users (the
# idle card's fact strip, the battery card) must NOT be regridded.
# ---------------------------------------------------------------------------


def test_sysGrid_isTwoColumnGrid():
    block = _ruleBlock(_read(_CSS), ".sys-grid")
    assert "display: grid" in block
    assert "grid-template-columns: 1fr 1fr" in block


def test_sysGrid_tilesAreBoxedNotBottomRuled():
    """The stacked layout separated tiles with a bottom rule; in a 2x2 that rule
    reads as a stray underline, so grid tiles get a box instead."""
    block = _ruleBlock(_read(_CSS), ".sys-grid .tile, .sys-grid .tile:last-child")
    assert "border: 1px solid var(--surface)" in block


def test_baseTileRule_staysStacked_forTheShippedCards():
    """Scope fence: the base `.tile` must keep its column/bottom-rule layout, or
    the idle card's fact strip and the battery card silently re-flow."""
    block = _ruleBlock(_read(_CSS), ".tile {")
    assert "flex-direction: column" in block
    assert "border-bottom: 1px solid var(--surface)" in block
    assert "grid" not in block


# ---------------------------------------------------------------------------
# AC3 -- the per-tile dot MIRRORS the existing level mapping. It introduces no
# new severity vocabulary: whatever hue the tile VALUE takes for a level, the
# dot takes too.
# ---------------------------------------------------------------------------


def _dotColour(css: str, level: str) -> str:
    return _ruleBlock(css, f'.tile[data-level="{level}"] .tile-dot')


def test_dotOk_isTheSsotGreen():
    assert "var(--green-ok)" in _dotColour(_read(_CSS), "ok")


def test_dotAmber_isTheSsotAmber():
    assert "var(--amber-warn)" in _dotColour(_read(_CSS), "amber")


def test_dotDown_mirrorsTheValue_amberNotRed():
    """US-488 (TD-067) swept `.tile[data-level=down] .tile-value` to amber --
    "degraded is not danger". A red DOWN dot would re-open that debt one sprint
    after it was closed, and would contradict the number beside it."""
    css = _read(_CSS)
    block = _dotColour(css, "down")
    assert "var(--amber-warn)" in block
    assert "var(--critical-red)" not in block
    assert not [brand for brand in _BRAND_REDS if brand in block]
    # Mirror proof, not a coincidence: the dot and the value resolve to the SAME
    # token as each other for this level.
    assert "var(--amber-warn)" in _ruleBlock(css, '.tile[data-level="down"]  .tile-value')


def test_dotUnavailable_isMutedNeverGreen():
    block = _dotColour(_read(_CSS), "unavailable")
    assert "var(--text-tertiary)" in block
    assert "var(--green-ok)" not in block


def test_dotDefault_isNeverGreen():
    """The un-levelled base dot: an unrecognised/absent level must render muted,
    never inheriting green from the healthy case."""
    block = _ruleBlock(_read(_CSS), ".tile-dot")
    assert "var(--green-ok)" not in block
    assert "var(--amber-warn)" not in block
    assert "var(--text-tertiary)" in block


def test_noDotOrSummaryRuleReachesForBrandRed():
    """TD-067 scope fence over everything this story added."""
    css = _read(_CSS)
    for line in css.splitlines():
        if ".tile-dot" in line or ".sys-summary" in line or ".sys-grid" in line:
            assert not [brand for brand in _BRAND_REDS if brand in line], line


# ---------------------------------------------------------------------------
# AC1 (colour) -- the summary line's hues come from the token SSOT and follow
# the same level vocabulary as the tiles.
# ---------------------------------------------------------------------------


def test_summaryOk_isTheSsotGreen_notALiteral():
    css = _read(_CSS)
    block = _ruleBlock(css, '.sys-summary[data-level="ok"] .sys-summary-text')
    assert "var(--green-ok)" in block
    # The token must actually exist in the SSOT (drift there re-reds this test).
    assert _tokenValue(_read(_TOKENS), "green-ok").startswith("#")


def test_summaryAmberAndDown_bothRenderAmber():
    """`down` shares the WATCH hue with `amber` per TD-067 -- the summary must
    not invent a third severity colour the tiles below it do not use."""
    css = _read(_CSS)
    for level in ("amber", "down"):
        block = _ruleBlock(css, f'.sys-summary[data-level="{level}"] .sys-summary-text')
        assert "var(--amber-warn)" in block
        assert "var(--critical-red)" not in block


def test_summaryUnavailable_isMutedNeverGreen():
    block = _ruleBlock(_read(_CSS), '.sys-summary[data-level="unavailable"] .sys-summary-text')
    assert "var(--text-tertiary)" in block
    assert "var(--green-ok)" not in block


def test_summaryBase_carriesNoSeverityColour():
    """An unrecognised level must inherit no severity it has not earned (the
    same neutral-base rule US-488 established for .detail-directive)."""
    block = _ruleBlock(_read(_CSS), ".sys-summary-text")
    assert "var(--green-ok)" not in block
    assert "var(--amber-warn)" not in block
    assert "var(--critical-red)" not in block


# ---------------------------------------------------------------------------
# Cross-file catch -- the CSS above styles classes the JS must actually EMIT.
# A CSS-only change here fails silently: correct-looking rules, no markup.
# ---------------------------------------------------------------------------


def test_renderer_emitsTheSummaryAndGridMarkup():
    js = _read(_JS)
    for cls in ("sys-summary", "sys-summary-text", "sys-summary-detail", "sys-grid"):
        assert f'"{cls}"' in js, f"{cls} is styled but never rendered"


def test_renderer_tagsTheSummaryWithItsLevel():
    """The hue is [data-level]-driven, so an untagged summary would render on the
    neutral base with no error -- silently un-levelled."""
    js = _read(_JS)
    assert 'summary.setAttribute("data-level"' in js


def test_renderer_appendsTheFourTilesIntoTheGrid_notTheCardBody():
    """AC2 wiring: if the tiles still go straight into `.card-body`, the grid
    element renders empty and the card silently stays a 1-column stack."""
    js = _read(_JS)
    start = js.index("function renderSystemStatusCard")
    body = js[start : js.index("\n    }", start)]
    assert body.count("appendTile(grid,") == 4
    assert "appendTile(body," not in body


def test_dotIsOptIn_soTheShippedStackedCardsAreUnchanged():
    """Scope fence: `appendTile` is shared with the idle card, the battery card
    and the LTFT card. The dot must be opt-in, or three shipped cards change
    appearance in a story that promised presentation-only on ONE card."""
    js = _read(_JS)
    start = js.index("function appendTile")
    body = js[start : js.index("\n    }", start)]
    assert "withDot" in body
    assert 'el.className = "tile"' in body
    # The other three cards keep calling the 2-arg form (no dot).
    assert "appendTile(strip," in js
    assert "appendTile(strip, view.facts.lastDrive)" in js
