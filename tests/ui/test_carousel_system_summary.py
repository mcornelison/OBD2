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
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the 2-arg appendTile pin reads the
#                               battery card (the idle strip retired).
# 2026-10-23    | Ralph (Rex)  | US-894-b -- MOVED PIN: the summary line, the 2x2 grid
#                               and the per-tile dot are RETIRED (spec s3 layout A).
#                               Their honest-instrument claims move to the VERDICT
#                               line: green only on the provider's ALL OK, the
#                               token SSOT, no brand red, a neutral base, and the
#                               JS emits what the CSS styles.
# ================================================================================
################################################################################

"""US-489 / US-894-b tests: the System page's one-glance line (now the verdict)."""

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
_UI = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dashboard")
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


def _sysState(**over: object) -> dict:
    """A healthy system-status emitter payload (US-400 / Atlas A-3 schema)."""
    state = {
        # MOVED PIN (US-894-b): obdLink is retired from system-status.
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
# MOVED PIN (US-894-b): the summary line is RETIRED with the 2x2 grid it
# compressed. The page's one-glance line is now the provider's VERDICT (spec
# s4.1) -- the page counts nothing, so "green only when every source is good"
# becomes "green only on the provider's ALL OK".
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_theSummaryAndItsTileGridAreRetired():
    view = _view("systemStatusView", _sysState())
    assert "summary" not in view
    assert "obdLink" not in view["tiles"]
    proc = subprocess.run(
        [_NODE, "-e",
         "const c=require(process.argv[1]);"
         "console.log(JSON.stringify([typeof c.systemSummary, typeof c.obdLinkTile]));",
         _JS],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["undefined", "undefined"]


@_NODE_TESTS
def test_theVerdictIsGreenOnlyOnTheProvidersAllOk():
    view = _view("systemStatusView", _sysState(verdict={"issueCount": 0, "members": []}))
    assert view["verdict"] == {"text": "ALL OK", "level": "ok"}


@_NODE_TESTS
def test_aDegradedCardIsNotGreen_whenTheProviderCountsIt():
    """The F-1 fixture from US-400 (every source degraded): the provider's two
    members make the line amber -- never the one green thing on the card."""
    members = [
        {"key": "bt", "reason": "Not linked. Check the OBD dongle."},
        {"key": "pi", "reason": "Over limit: disk."},
    ]
    view = _view(
        "systemStatusView",
        _sysState(verdict={"issueCount": 2, "members": members}),
    )
    assert view["verdict"] == {"text": "2 ISSUES", "level": "amber"}


@_NODE_TESTS
def test_aCardWithNoVerdictIsNeverGreen():
    """A payload that did not say it looked is `--`, never ALL OK."""
    view = _view("systemStatusView", _sysState())
    assert view["verdict"] == {"text": "--", "level": "unavailable"}


def test_baseTileRule_staysStacked_forTheShippedCards():
    """Scope fence: the base `.tile` must keep its column/bottom-rule layout, or
    the battery card silently re-flows."""
    block = _ruleBlock(_read(_CSS), ".tile {")
    assert "flex-direction: column" in block
    assert "border-bottom: 1px solid var(--surface)" in block
    assert "grid" not in block


def test_theGridAndTheDotRulesAreGone():
    css = _read(_CSS)
    for selector in (".sys-grid", ".tile-dot", ".sys-summary"):
        assert selector not in css, f"{selector} outlived the grid it styled"


# ---------------------------------------------------------------------------
# The verdict line's hues come from the token SSOT (the summary's rules, moved).
# ---------------------------------------------------------------------------


def test_verdictOk_isTheSsotGreen_notALiteral():
    css = _read(_CSS)
    block = _ruleBlock(css, '.sys-verdict[data-level="ok"] .sys-verdict-text')
    assert "var(--green-ok)" in block
    assert _tokenValue(_read(_TOKENS), "green-ok").startswith("#")


def test_verdictAmber_isTheSsotAmber_neverRed():
    block = _ruleBlock(_read(_CSS), '.sys-verdict[data-level="amber"] .sys-verdict-text')
    assert "var(--amber-warn)" in block
    assert "var(--critical-red)" not in block


def test_verdictUnavailable_isMutedNeverGreen():
    block = _ruleBlock(_read(_CSS), '.sys-verdict[data-level="unavailable"] .sys-verdict-text')
    assert "var(--text-tertiary)" in block
    assert "var(--green-ok)" not in block


def test_verdictBase_carriesNoSeverityColour():
    """An unrecognised level must inherit no severity it has not earned."""
    block = _ruleBlock(_read(_CSS), ".sys-verdict-text")
    assert "var(--green-ok)" not in block
    assert "var(--amber-warn)" not in block
    assert "var(--critical-red)" not in block


def test_noVerdictOrRowRuleReachesForBrandRed():
    """TD-067 scope fence over the System page's rules."""
    for line in _read(_CSS).splitlines():
        if ".sys-verdict" in line or ".sys-row" in line or ".obd-step" in line:
            assert not [brand for brand in _BRAND_REDS if brand in line], line
            assert "var(--critical-red)" not in line, line


# ---------------------------------------------------------------------------
# Cross-file catch -- the CSS above styles classes the JS must actually EMIT.
# ---------------------------------------------------------------------------


def test_renderer_emitsTheVerdictAndRowMarkup():
    js = _read(_JS)
    for cls in ("sys-verdict", "sys-verdict-text", "sys-rows", "sys-row",
                "sys-row-label", "sys-row-sentence", "obd-step"):
        assert f'"{cls}"' in js, f"{cls} is styled but never rendered"


def test_renderer_tagsTheVerdictWithItsLevel():
    """The hue is [data-level]-driven, so an untagged verdict would render on
    the neutral base with no error -- silently un-levelled."""
    js = _read(_JS)
    start = js.index("function appendSysVerdict")
    body = js[start : js.index("\n    }", start)]
    assert 'line.setAttribute("data-level", verdict.level)' in body


def test_theSystemPageNeverRendersATile():
    """Spec s3: rows never use `.tile`."""
    js = _read(_JS)
    for fn in ("function renderSystemBody", "function appendSysRow",
               "function appendSysVerdict", "function renderSystemUnavailable"):
        start = js.index(fn)
        body = js[start : js.index("\n    }", start)]
        assert "appendTile" not in body and '"tile"' not in body, fn


def test_appendTileIsTheTwoArgFormForTheShippedStackedCards():
    """The opt-in dot went with the grid, its only caller."""
    js = _read(_JS)
    start = js.index("function appendTile")
    body = js[start : js.index("\n    }", start)]
    assert "withDot" not in body
    assert 'el.className = "tile"' in body
    assert "appendTile(body, view.health)" in js
    assert "appendTile(body, view.vcell)" in js
