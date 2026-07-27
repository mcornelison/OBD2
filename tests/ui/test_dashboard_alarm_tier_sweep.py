################################################################################
# File Name: test_dashboard_alarm_tier_sweep.py
# Purpose/Description: US-488 (TD-067) tests -- every NON-STOP alarm/degraded
#   surface in the shipped dashboard is routed to its CORRECT engine tier, and
#   the brand reds are left to the brand mark alone. Per Spool's per-surface
#   ruling (2026-07-27, TD-067): "Red = danger, one meaning only" -- no second
#   alarm-red is invented; a degraded/DOWN state is WATCH (--amber-warn), the
#   battery failsafe TRIGGER is the one terminal act-now system state
#   (--critical-red), and a destructive USER ACTION is a DIFFERENT AXIS that
#   wants its own --destructive token (NOT gated yet -- see the deferral guard
#   at the bottom of this file).
#
#   The DTC detail directive band is the load-bearing one: it painted ONE
#   blanket brand red for EVERY severity, so a WATCH code's own directive read
#   redder than the STOP tier it sits below -- a severity inversion. It is now
#   tier-driven, and because the tier tag is applied in JS, a CSS-only refactor
#   would leave every band on the neutral base with no error -- so the JS half
#   is asserted too (the same cross-file trap US-484-a/b hit twice).
#
#   Colours are compared as PARSED token references, never as hardcoded hexes,
#   so a drift in specs/UI/tokens.css or in the dist re-reds these tests.
#   The on-panel render stays a PI-RUNTIME gate (story validationCriteria).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial -- US-488 non-STOP alarm-tier sweep.
# ================================================================================
################################################################################

"""US-488 tests for the TD-067 non-STOP alarm-surface sweep."""

import os
import re

# The CSS-parsing helpers live in the US-484-b safety suite, which is the
# canonical home for this domain. Imported rather than re-implemented on
# purpose: `_ruleBlock`'s line-anchoring is load-bearing (it stops a DESCENDANT
# rule being mistaken for the base rule it overrides), and a hand-copied,
# subtly weaker matcher here would silently under-assert.
from tests.ui.test_dashboard_stop_tier_safety import _read, _ruleBlock, _tokenValue

_UI = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "UI")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dist", "dashboard-pi")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")

# tokens.css:50-57 -- RESERVED, brand mark ONLY (Spool S-2).
_BRAND_REDS = ("var(--red)", "var(--red-light)", "var(--red-dark)")

# The two surfaces US-488 deliberately did NOT sweep. Both are the Mode-04
# hard-confirm -- a DESTRUCTIVE USER ACTION, which Spool ruled is a different
# axis from the engine alarm tiers: it MUST NOT be any alarm-red and MUST NOT
# be amber, so it needs a new --destructive token (Iris owns the value, Atlas
# gates it under Rule-10). That token does not exist yet, and inventing a value
# inside this story is exactly the drift the US-484 line of work removes.
# Listed by selector so the debt cannot grow quietly: the follow-up story closes
# TD-067 by repointing these two and deleting this tuple.
_DEFERRED_DESTRUCTIVE = ("#clear-confirm .confirm-box", "#clear-confirm-ok")


def _rules(css: str) -> list:
    """Every `selector { body }` pair in the sheet, as (selector, body).

    Comments are stripped FIRST -- otherwise a prose mention of a token inside
    the file header reads as a live declaration, and the header itself gets
    glued onto the `:root` selector.

    Nested at-rules (@keyframes) surface as their inner step blocks, which is
    what we want -- a brand red hidden in an animation step is still a brand red
    on a live surface.
    """
    bare = re.sub(r"/\*[\s\S]*?\*/", "", css)
    return [
        (sel.strip(), body)
        for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", bare)
    ]


def _brandRedsIn(body: str) -> list:
    return [brand for brand in _BRAND_REDS if brand in body]


# ---------------------------------------------------------------------------
# AC1 -- the 5 degraded/DOWN surfaces become WATCH amber.
# "Degraded is not danger": a DOWN link, a stale tile, a fuel-trim drive beyond
# +/-10% and a re-set code are all "something needs attention", not "pull over".
# ---------------------------------------------------------------------------


def test_topbarDownGlyph_rendersAmber_notBrandRed():
    block = _ruleBlock(_read(_CSS), '#topbar .glyph[data-state="down"]')
    assert "var(--amber-warn)" in block
    assert not _brandRedsIn(block)


def test_statusTileDown_rendersAmber_notBrandRed():
    block = _ruleBlock(_read(_CSS), '.tile[data-level="down"]  .tile-value')
    assert "var(--amber-warn)" in block
    assert not _brandRedsIn(block)


def test_ltftBarDownValue_rendersAmber_notBrandRed():
    """A drive beyond +/-10% LTFT is a WATCH-tier fuel-trim drift, not a
    pull-over alarm (Spool per-surface ruling #4)."""
    block = _ruleBlock(_read(_CSS), '.ltft-bar[data-level="down"]  .ltft-bar-value')
    assert "var(--amber-warn)" in block
    assert not _brandRedsIn(block)


def test_ltftBarDownBorder_rendersAmber_notBrandRed():
    """The bar's BORDER is the second half of the same surface -- sweeping only
    the value would leave a red box around an amber number."""
    block = _ruleBlock(_read(_CSS), '.ltft-bar[data-level="down"]')
    assert "var(--amber-warn)" in block
    assert not _brandRedsIn(block)


def test_dtcClearResultReset_rendersAmber_notBrandRed():
    """A code that RE-SET after a clear is a hard fault worth attention, but the
    directive it needs is "get diagnosed", not "pull over" (ruling #6)."""
    block = _ruleBlock(_read(_CSS), '#dtc-clear-result[data-level="reset"]')
    assert "var(--amber-warn)" in block
    assert not _brandRedsIn(block)


# ---------------------------------------------------------------------------
# AC2 -- the battery failsafe TRIGGER is the ONE non-DTC --critical-red surface.
# ---------------------------------------------------------------------------


def test_batteryLadderTrigger_rendersCriticalRed_notBrandRed():
    """TRIGGER is terminal + act-now (the failsafe is about to halt the Pi), so
    it earns the state-alarm red -- but as a SYSTEM-critical state, not the
    engine "PULL OVER" one."""
    css = _read(_CSS)
    border = _ruleBlock(css, '.ladder[data-stage="TRIGGER"]')
    banner = _ruleBlock(css, '.ladder[data-stage="TRIGGER"] .ladder-banner')
    for block in (border, banner):
        assert "var(--critical-red)" in block
        assert not _brandRedsIn(block)


def test_batteryLadderEarlierStages_stayAmber():
    """Escalation integrity: if every ladder stage were red, TRIGGER would not
    read as worse than the stage before it."""
    css = _read(_CSS)
    assert "var(--amber-warn)" in _ruleBlock(css, ".ladder {")
    assert "var(--amber-warn)" in _ruleBlock(css, ".ladder-banner {")


def test_batteryLadderBannerCopy_staysSystemAppropriate():
    """--critical-red is shared with the DTC STOP tier, the WORDS are not: the
    ladder is a SYSTEM state (the Pi is about to halt) and must never borrow the
    engine tier's "PULL OVER" directive (AC2)."""
    match = re.search(r"banner\.textContent\s*=\s*([^;]+);", _read(_JS))
    assert match, "the ladder banner copy moved -- re-point this guard"
    copy = match.group(1).upper()
    assert "PULL OVER" not in copy
    assert "DRAINING" in copy


# ---------------------------------------------------------------------------
# AC3 -- .detail-directive is TIER-AWARE (the severity inversion this closes).
# ---------------------------------------------------------------------------


def test_detailDirectiveBase_carriesNoAlarmColour():
    """The un-tiered base must be NEUTRAL. If the base itself were red/amber, an
    `na` or untagged directive would inherit a severity it does not have."""
    block = _ruleBlock(_read(_CSS), ".detail-directive {")
    assert not _brandRedsIn(block)
    assert "var(--critical-red)" not in block
    assert "var(--amber-warn)" not in block
    assert "var(--text-primary)" in block


def test_detailDirectiveStop_rendersCriticalRed():
    block = _ruleBlock(_read(_CSS), '.detail-directive[data-level="stop"]')
    assert "var(--critical-red)" in block


def test_detailDirectiveWatch_rendersAmber_notAnyRed():
    """The inversion, stated as a test: a WATCH directive used to paint brand
    red -- REDDER than the STOP tier's own --critical-red chip beside it."""
    block = _ruleBlock(_read(_CSS), '.detail-directive[data-level="watch"]')
    assert "var(--amber-warn)" in block
    assert "var(--critical-red)" not in block
    assert not _brandRedsIn(block)


def test_detailDirectiveMinor_isNotAnyRed():
    """A MINOR gas-cap code must not shout. Green/neutral only."""
    block = _ruleBlock(_read(_CSS), '.detail-directive[data-level="minor"]')
    assert "var(--critical-red)" not in block
    assert not _brandRedsIn(block)


def test_detailDirectiveUnknown_rendersAmber():
    """An uncurated code is honestly "get diagnosed" -- amber, never green and
    never the pull-over red (honest-instrument F-1)."""
    block = _ruleBlock(_read(_CSS), '.detail-directive[data-level="unknown"]')
    assert "var(--amber-warn)" in block


def test_detailDirective_hasNoTierPaintedRedderThanTheTierAboveIt():
    """Severity ramp over the whole band: STOP is the only --critical-red tier,
    and no tier reaches for a brand red."""
    critical = [
        sel
        for sel, body in _rules(_read(_CSS))
        if sel.startswith(".detail-directive") and "var(--critical-red)" in body
    ]
    assert critical == ['.detail-directive[data-level="stop"]']


def test_carouselJs_detailDirective_isTaggedWithTheTier():
    """The CROSS-FILE half: the tier tag is applied by the DOM builder, so a
    CSS-only refactor leaves EVERY directive on the neutral base -- no error, no
    styling, silently un-tiered. Same trap as US-484-a's TAKEOVER_STYLE."""
    js = _read(_JS)
    match = re.search(r'"detail-directive"[\s\S]{0,400}?detailBody\.appendChild', js)
    assert match, "the detail-directive render block moved -- re-point this guard"
    assert 'setAttribute("data-level", view.level)' in match.group(0)


# ---------------------------------------------------------------------------
# AC5 -- whole-file guard: no brand red outside the brand mark, save the two
# documented, deliberately-deferred --destructive surfaces.
# ---------------------------------------------------------------------------


def test_noAlarmSurfaceRendersABrandRed_exceptTheDeferredDestructivePair():
    """TD-067's closing assertion, minus its gated tail. Every OTHER rule in the
    sheet is now off the brand reds."""
    offenders = {
        sel: _brandRedsIn(body)
        for sel, body in _rules(_read(_CSS))
        if _brandRedsIn(body)
    }
    assert set(offenders) == set(_DEFERRED_DESTRUCTIVE), offenders


def test_theDestructiveTokenIsNotInventedLocally():
    """SCOPE FENCE (the US-484-a pattern): --destructive has no gated value yet,
    so neither file may DECLARE or RENDER it. This test is what stops a
    well-meaning half-landing -- a locally-guessed hex in the dist would be
    exactly the SSOT fork the US-484 line of work exists to remove.

    Prose is fine and expected: both files carry a comment explaining WHY the
    token is missing. Only a real declaration (`--destructive:`) or a real
    consumer (`var(--destructive)`) is the violation -- asserting on the bare
    string would fail on the explanation itself."""
    for path in (_TOKENS, _CSS):
        text = _read(path)
        assert not re.search(r"^\s*--destructive\s*:", text, re.MULTILINE), path
        assert "var(--destructive)" not in text, path


def test_brandRedTokensAreStillDeclared_andStillMatchTheSsot():
    """The sweep repoints CONSUMERS; it must not delete the brand tier itself
    (the brand mark still needs it) or fork its values."""
    css, tokens = _read(_CSS), _read(_TOKENS)
    for name in ("red", "red-light", "red-dark"):
        assert _tokenValue(css, name) == _tokenValue(tokens, name)


def test_theSweepRepointedOntoTokens_notOntoBareRedLiterals():
    """The cheap way to "pass" the guard above is to inline a red hex instead of
    a var() -- which is the SAME drift wearing a different hat. So: outside
    :root, no rule body may carry a dominant-red literal."""
    for sel, body in _rules(_read(_CSS)):
        if sel.startswith(":root"):
            continue
        for hexLit in re.findall(r"#[0-9a-fA-F]{6}\b", body):
            r, g, b = (int(hexLit[i : i + 2], 16) for i in (1, 3, 5))
            assert not (r > 120 and r > g * 2 and r > b * 2), (
                f"bare red literal {hexLit} on {sel} -- use a token"
            )
