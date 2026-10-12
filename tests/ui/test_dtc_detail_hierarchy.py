################################################################################
# File Name: test_dtc_detail_hierarchy.py
# Purpose/Description: US-491 (Iris polish P-3) tests for the DTC detail
#   overlay's visual hierarchy pass: directive-first, carded sections, a
#   consistent spacing scale and a Back control that actually meets the S-2 tap
#   minimum. PRESENTATION ONLY -- the severity gating, the S-4 fix-replacement
#   rule, the trust badge and the Mode-04 clear gate are asserted UNCHANGED at
#   the bottom of this file, because "make it prettier" is exactly the kind of
#   story that quietly loosens a safety gate.
#
#   The load-bearing finding this story closes: `detailLine()` wraps EVERY row's
#   text in a `.detail-value` span, and that span declared its OWN font-size and
#   color. A child's own rule beats an inherited value regardless of the parent
#   selector's specificity, so every severity colour and every type size the row
#   classes declared was INERT -- including the whole tier ramp US-488 built for
#   `.detail-directive` one story ago. Making the band "larger" per AC-1 is
#   impossible without fixing that, so the inheritance is pinned here.
#
#   Colours/sizes are compared as PARSED declarations, never eyeballed, and the
#   DOM half is asserted against the carousel.js source -- a CSS-only change
#   would style markup that never renders (the cross-file trap US-484-a/b,
#   US-488, US-489 and US-490 all hit). The on-panel 480x320 render stays a
#   PI-RUNTIME gate (story validationCriteria).
#   Skipped where node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-27    | Ralph (Rex)  | Initial -- US-491 DTC detail overlay hierarchy.
# ================================================================================
################################################################################

"""US-491 tests for the DTC detail overlay hierarchy pass."""

import json
import os
import re
import shutil
import subprocess

import pytest

from tests.ui.css_type_scale import resolveFontPx

# Reuse the canonical parsers rather than re-implementing them: `_ruleBlock` is
# line-anchored, so a DESCENDANT rule can never be mistaken for the base rule it
# overrides -- which is the exact distinction this story turns on.
from tests.ui.test_dashboard_stop_tier_safety import _read, _ruleBlock, _tokenValue

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_UI = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui")
_DIST = os.path.join(_UI, "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")
_HTML = os.path.join(_DIST, "dashboard.html")

_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _probe(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe.

    `encoding` is pinned to utf-8: node writes UTF-8, but `text=True` alone
    decodes with the Windows locale codepage and turns the directives' "·"
    separator into "Â·" -- a one-character diff that reads exactly like a bad
    production string (TD-068).
    """
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _code(severity: str = "stop", **over: object) -> dict:
    code = {
        "code": "P0299",
        "severity": severity,
        "status": "stored",
        "short": "Turbo underboost",
        "driveId": 27,
        "logged": True,
        "syncAcked": True,
    }
    code.update(over)
    return code


def _px(block: str, prop: str) -> int:
    """The px magnitude of a LITERAL declaration in a rule body (-1 when absent).

    Still correct for the box metrics below (`height`/`min-height` are literals
    and stay literals). `font-size` moved onto the US-539 type scale, so those
    call sites use `resolveFontPx` instead -- this helper would report -1 for a
    `var(--fs-*)` ref, i.e. "absent" for a size that is plainly declared.
    """
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*(\d+)px", block)
    return int(match.group(1)) if match else -1


def _renderDetailBody(js: str) -> str:
    """The source of renderDetailBody(), bounded at the NEXT function so a guard
    can never satisfy itself on an incidental match further down the file (the
    US-490 lesson: a source slice that runs on cannot fail honestly)."""
    start = js.index("function renderDetailBody(")
    end = js.index("function openDetail(", start)
    return js[start:end]


def _tapMin() -> int:
    return int(_tokenValue(_read(_CSS), "tap-min").rstrip("PX"))


# ---------------------------------------------------------------------------
# AC1 -- directive-first: the action band leads, and it is actually LARGER.
# ---------------------------------------------------------------------------


def test_directiveBand_isRenderedDirectlyUnderTheHero():
    """"What do I do" must land before the freeze frame, the fix and the footer
    -- ordering asserted on the real DOM builder, not on intent."""
    body = _renderDetailBody(_read(_JS))
    order = [body.index(marker) for marker in ('"detail-hero"', '"detail-directive"')]
    assert order == sorted(order), "the directive no longer follows the hero"
    for later in (
        '"detail-meta"',
        '"detail-card detail-freeze"',
        '"detail-card detail-fix"',
        '"detail-footer"',
    ):
        assert body.index('"detail-directive"') < body.index(later), later


def test_directiveBand_isLargerThanTheDetailBodyBaseCopy():
    """AC1's "larger". The band is the one thing on this overlay the operator
    must read from arm's length in a moving car, so a token 1px bump is not the
    hierarchy step the story asks for -- a full step off the base copy is."""
    css = _read(_CSS)
    band = resolveFontPx(css, _ruleBlock(css, ".detail-directive {"))
    base = resolveFontPx(css, _ruleBlock(css, ".detail-fix-text"))
    assert base > 0, "base copy size moved -- re-point this guard"
    assert band >= base + 4, f"directive {band}px is not a step above base copy {base}px"


def test_directiveValueSpan_inheritsTheBandsTypographyAndTier():
    """THE LOAD-BEARING ONE. Every row's text is a `.detail-value` child, and a
    child's OWN declaration beats anything inherited from the parent no matter
    how specific the parent selector is. While `.detail-value` hardcoded its own
    font-size and color, the whole US-488 tier ramp on `.detail-directive`
    painted nothing and the band could not be made larger."""
    block = _ruleBlock(_read(_CSS), ".detail-value {")
    assert "var(--text-primary)" not in block, (
        ".detail-value still clobbers its row's colour -- the tier ramp is inert"
    )
    assert resolveFontPx(_read(_CSS), block) < 0, (
        ".detail-value still clobbers its row's size -- the band cannot be larger"
    )
    assert "inherit" in block


def test_directiveBand_isVisuallyABandNotABareLine():
    """AC1 calls it an action BAND: it has to read as a block, not as one more
    line in the column."""
    block = _ruleBlock(_read(_CSS), ".detail-directive {")
    assert "padding" in block
    assert "border-left" in block


@_NODE_TESTS
def test_stopAndWatch_directivesAreUnchanged():
    """AC4 fence: the hierarchy pass must not re-word the two tiers that carry a
    safety instruction."""
    assert _probe("codeDetailView", _code("stop"))["directive"] == "REDUCE LOAD · PULL OVER"
    assert (
        _probe("codeDetailView", _code("watch"))["directive"]
        == "DRIVE GENTLY · GET DIAGNOSED"
    )


@_NODE_TESTS
def test_minorCode_keepsItsSafeToClearDirective():
    """AC1's parenthetical, and a real gap it closes: the MINOR tier has carried
    "SAFE TO CLEAR ONCE LOGGED" since US-405 and the takeover shows it, but the
    DETAIL rendered no band at all -- so the one screen the operator opens to
    ask "what do I do" answered nothing on a gas-cap code."""
    view = _probe("codeDetailView", _code("minor"))
    assert view["directive"] == "SAFE TO CLEAR ONCE LOGGED"
    assert view["level"] == "minor"


@_NODE_TESTS
def test_uncuratedCode_getsTheHonestGetDiagnosedDirective():
    """An unrecognised severity resolves to `unknown`, and unknown is honestly
    "get diagnosed" -- the same answer the takeover already gives it. A blank
    band would read as "nothing to worry about" (honest-instrument F-1)."""
    view = _probe("codeDetailView", _code("wat"))
    assert view["level"] == "unknown"
    assert view["directive"] == "GET DIAGNOSED"


@_NODE_TESTS
def test_naCode_stillShowsNoDirectiveBand():
    """The one tier that stays blank. `na` is "not applicable to this vehicle" --
    a fact, not an action -- and it never alarms anywhere else in the system."""
    assert _probe("codeDetailView", _code("na"))["directive"] is None


def test_everyRenderedDirective_carriesItsTierTag():
    """CROSS-FILE: the band is tier-driven in CSS but tagged in JS, so widening
    which tiers render one is only safe while the tag travels with it. Untagged,
    the new MINOR/unknown bands would silently fall to the neutral base."""
    body = _renderDetailBody(_read(_JS))
    match = re.search(r'"detail-directive"[\s\S]{0,300}?appendChild', body)
    assert match, "the detail-directive render block moved -- re-point this guard"
    assert 'setAttribute("data-level", view.level)' in match.group(0)


# ---------------------------------------------------------------------------
# AC2 -- the three context sections become labelled cards.
# ---------------------------------------------------------------------------


def test_cardShell_isDeclaredOnce_withBorderAndPadding():
    block = _ruleBlock(_read(_CSS), ".detail-card")
    assert "border" in block
    assert "padding" in block
    assert "border-radius" in block


def test_freezeAndFixSections_useTheSharedCardShell():
    """One shell, not three near-identical boxes -- otherwise the "consistent
    spacing" of AC3 drifts the first time one of them is edited."""
    body = _renderDetailBody(_read(_JS))
    assert 'ff.className = "detail-card detail-freeze"' in body
    assert 'fixBox.className = "detail-card detail-fix"' in body


def test_clearZone_usesTheSharedCardShell_andCarriesALabel():
    html = _read(_HTML)
    zone = re.search(r'<div id="dtc-clear-zone"[^>]*>([\s\S]*?)</div>\s*</div>', html)
    assert zone, "the clear zone markup moved -- re-point this guard"
    assert 'class="detail-card' in html[html.index('id="dtc-clear-zone"') - 60 :][:120]
    label = re.search(r'class="detail-label">([^<]+)<', zone.group(1))
    assert label, "the clear zone has no section label"
    assert label.group(1) == label.group(1).upper()


@_NODE_TESTS
def test_fixSection_carriesAnUppercaseLabelInEveryMode():
    """AC2 wants a label on every card. The mode matters: calling a 🔴/🟡
    diagnose directive a "SUGGESTED FIX" would undo S-4 in the label while the
    body still obeys it."""
    for mode in ("fix", "directive", "na"):
        label = _probe("fixSectionLabel", mode)
        assert label and label == label.upper(), mode
    assert _probe("fixSectionLabel", "fix") == "SUGGESTED FIX"
    assert _probe("fixSectionLabel", "directive") != _probe("fixSectionLabel", "fix")


def test_fixSection_labelsEveryMode_notOnlyTheFixMode():
    """The renderer half: the label used to live INSIDE the `mode === "fix"`
    branch, so a 🔴/🟡 card rendered a bordered box with no heading at all."""
    body = _renderDetailBody(_read(_JS))
    start = body.index("fixBox.className")
    # Bounded at the mode branch on purpose: a slice that ran ON into the branch
    # would find the OLD branch-local label and pass against the very code this
    # guard exists to reject (the US-490 lesson -- a guard that cannot fail is
    # worse than no guard).
    block = body[start : body.index("if (view.fix.mode", start)]
    assert "fixSectionLabel(view.fix.mode)" in block, (
        "the fix label is still branch-local -- a directive card renders unlabelled"
    )


def test_clearZone_isHiddenWhenThereIsNothingToClear():
    """A bordered, labelled card is only an improvement while it has content --
    an empty "CLEAR CODES" box on a no-codes detail is a new visual regression.
    The GATE is untouched: visibility still comes from clearButtonView()."""
    js = _read(_JS)
    start = js.index("function renderClearButton(")
    block = js[start : js.index("function showClearResult(", start)]
    assert "clearZone.hidden = !view.visible" in block
    assert "clearButtonView(lastDtc)" in block


def test_clearZoneHidden_actuallyRemovesItFromFlow():
    """The CSS half, and a live trap this story WALKED INTO: joining the shared
    card shell gave the zone `display: flex`, which outranks the UA `[hidden]`
    rule -- so `hidden = true` would have painted an empty labelled box anyway.
    Stated explicitly, exactly as US-490 had to for #menu-btn."""
    assert "display: flex" in _ruleBlock(_read(_CSS), ".detail-card")
    assert "display: none" in _ruleBlock(_read(_CSS), "#dtc-clear-zone[hidden]")


# ---------------------------------------------------------------------------
# AC3 -- a consistent spacing scale + a Back target that really is >= 40px.
# ---------------------------------------------------------------------------


def test_detailOverlay_declaresOneSpacingScale():
    block = _ruleBlock(_read(_CSS), "#dtc-detail")
    assert "--detail-gap:" in block
    assert "--detail-pad:" in block


def test_theSectionsConsumeTheScale_ratherThanTheirOwnMagicNumbers():
    css = _read(_CSS)
    assert "var(--detail-pad)" in _ruleBlock(css, ".detail-card")
    assert "var(--detail-gap)" in _ruleBlock(css, ".detail-body")


def test_backControl_meetsTheTapMinimum():
    block = _ruleBlock(_read(_CSS), "#detail-back")
    assert "min-height: var(--tap-min)" in block
    assert _tapMin() >= 40


def test_detailHead_isTallEnoughToHoldTheBackTarget():
    """The bug AC3 actually closes: the head was a FIXED 36px around a 40px
    target, so the one control that guarantees the operator is never trapped
    overflowed its own header."""
    block = _ruleBlock(_read(_CSS), ".detail-head")
    fixed = _px(block, "height")
    assert fixed < 0, f".detail-head still pins a fixed height ({fixed}px)"
    assert _px(block, "min-height") >= _tapMin()


def test_backControl_hasAVisibleAffordance():
    """AC3: ">= 40px with clear affordance". A borderless transparent glyph is
    40px of nothing -- the operator cannot see where to press."""
    block = _ruleBlock(_read(_CSS), "#detail-back")
    assert "border: 0" not in block
    assert "background: transparent" not in block
    assert "border:" in block and "border-radius" in block


# ---------------------------------------------------------------------------
# AC4 -- presentation only. Every safety rule the overlay carries, re-asserted.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_s4_fixIsStillReplacedByADirectiveOnStopAndWatch():
    """S-4/F-1: no raw internet fix on a dangerous code, even when the state
    supplies one."""
    for sev in ("stop", "watch"):
        view = _probe("codeDetailView", _code(sev, suggestedFix="Replace the turbo"))
        assert view["fix"]["mode"] == "directive", sev
        assert view["fix"]["badge"] is None, sev
        assert "Replace the turbo" not in view["fix"]["text"], sev


@_NODE_TESTS
def test_trustBadge_isUnchangedOnAMinorFix():
    view = _probe(
        "codeDetailView",
        _code("minor", suggestedFix="Tighten the gas cap", fixProvenance="spool-validated"),
    )
    assert view["fix"]["mode"] == "fix"
    assert view["fix"]["text"] == "Tighten the gas cap"
    assert view["fix"]["badge"]["kind"] == "verified"


@_NODE_TESTS
def test_mode04ClearGate_isUnchanged():
    """The most consequential control on the dash. Re-asserted end to end after
    a story that re-boxed the zone it lives in."""
    minorOk = _code("minor", code="P0442", logged=True, syncAcked=True)
    assert _probe("clearButtonView", {"codes": [minorOk]})["enabled"] is True
    assert (
        _probe("clearButtonView", {"codes": [minorOk, _code("stop")]})["reason"]
        == "severity_present"
    )
    assert (
        _probe("clearButtonView", {"codes": [_code("minor", syncAcked=False)]})["reason"]
        == "sync_pending"
    )
    assert (
        _probe(
            "clearButtonView",
            {"codes": [minorOk], "sessionResetLock": ["P0442"]},
        )["reason"]
        == "session_locked"
    )
    assert _probe("clearButtonView", {"codes": []})["visible"] is False


@_NODE_TESTS
def test_severityChipsAndTiersAreUnchanged():
    for sev, chip in (("stop", "STOP"), ("watch", "WATCH"), ("minor", "MINOR"), ("na", "N/A")):
        view = _probe("codeDetailView", _code(sev))
        assert view["chip"] == chip, sev
        assert view["level"] == (sev if sev != "na" else "na"), sev
