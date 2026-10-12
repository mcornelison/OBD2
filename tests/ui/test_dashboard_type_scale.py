################################################################################
# File Name: test_dashboard_type_scale.py
# Purpose/Description: US-539 (F-127) tests -- the shipped Pi dashboard sizes its
#   type from a five-step scale in the visual SSOT, not from 82 bare `px`
#   literals spread over 15 undocumented values. The DoD is a grep gate (no bare
#   `font-size: Npx` survives in dashboard.css) plus the two properties that make
#   the gate worth having: the five tokens carry ONE value across both files, and
#   the scale stays strictly descending so the two SAFETY hierarchies resting on
#   it (STOP takeover directive > base directive; DTC detail directive > base
#   copy) still mean what they say after the refactor.
#
#   THE NEGATIVE CONTROL IS NOT DECORATION. Every assertion here is an ABSENCE
#   check, and an empty result is evidence only once you know the lookup can see
#   the thing it is looking for -- so the bare-px detector is driven against a
#   synthetic stylesheet that DOES contain the drift and must report it. Without
#   that, a typo in the pattern reads as a perfectly green gate over a file full
#   of literals.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-539 type-scale tokenization.
# ================================================================================
################################################################################

"""US-539 tests for the F-127 dashboard type scale (tokens.css <-> dashboard.css)."""

import re

from tests.ui.css_type_scale import (
    BARE_PX_FONT_SIZE,
    DASHBOARD_CSS,
    SCALE_TOKENS,
    TOKENS_CSS,
    readCss,
    resolveFontPx,
    scaleValues,
)
from tests.ui.css_type_scale import (
    ruleBlock as _ruleBlock,
)

# ---------------------------------------------------------------------------
# AC2 -- the DoD grep gate, with the control that proves it can see drift.
# ---------------------------------------------------------------------------


def test_barePxDetector_reportsDriftWhenDriftIsPresent():
    """THE CONTROL for every absence check below. Run the detector against a
    stylesheet that genuinely carries the drift; if this ever goes green-quiet,
    the gate underneath it is measuring nothing."""
    drifted = ".card-title { margin: 0; font-size: 13px; font-weight: 600; }"
    assert BARE_PX_FONT_SIZE.search(drifted) is not None
    assert BARE_PX_FONT_SIZE.search(drifted).group(1) == "13"


def test_barePxDetector_doesNotMisreadAScaleTokenDeclaration():
    """The other half of the control: `--fs-hero: 40px` is the scale being
    DECLARED, not a rule sizing itself with a literal. A detector that cannot
    tell them apart would fail the file it just fixed."""
    assert BARE_PX_FONT_SIZE.search("  --fs-hero:        40px;") is None


def test_dashboardCss_hasNoBarePxFontSize():
    """AC2's DoD. Every size on the shipped surface comes from the scale, so the
    F-127 legibility fix is one edit in :root and not 82 scattered ones."""
    leftovers = BARE_PX_FONT_SIZE.findall(readCss(DASHBOARD_CSS))
    assert leftovers == [], f"bare px font-sizes still in dashboard.css: {leftovers}"


def test_everyFontSizeDeclaration_bindsTheScaleOrInheritsDeliberately():
    """Stronger than "no px": a `font-size: 1.2em` or a stray `var(--tap-min)`
    would clear the grep gate while re-forking the scale. The only two legal
    right-hand sides are a scale token and the deliberate `inherit` on
    `.detail-value` (US-491 -- the row classes cannot be tiered without it)."""
    css = readCss(DASHBOARD_CSS)
    values = [
        value.strip()
        for value in re.findall(r"(?<![-\w])font-size:\s*([^;]+);", css)
    ]
    legal = {f"var(--{name})" for name in SCALE_TOKENS} | {"inherit"}
    assert set(values) <= legal, f"off-scale font-size values: {set(values) - legal}"
    assert values.count("inherit") == 1


def test_dashboardCss_declaresNoTypeTokensBeyondTheFive():
    """The point of a scale is that it is SMALL. A sixth `--fs-*` is the sprawl
    coming back one token at a time, which is how 15 sizes happened."""
    declared = set(re.findall(r"^\s*--(fs-[a-zA-Z0-9-]+):", readCss(DASHBOARD_CSS), re.M))
    assert declared == set(SCALE_TOKENS)


# ---------------------------------------------------------------------------
# AC1 -- the scale lives in the SSOT, and the dist mirror agrees with it.
# ---------------------------------------------------------------------------


def test_scaleTokens_areDeclaredInTheSsot():
    """AC1: the type scale is a tokens.css fact. Adding it only to the dist
    sheet would leave the SSOT unable to describe the surface it governs."""
    assert set(scaleValues(readCss(TOKENS_CSS))) == set(SCALE_TOKENS)


def test_scaleTokens_areDeclaredInTheShippedSheet():
    """dashboard.html links ONLY dashboard.css, so an SSOT-only scale would
    leave the panel unsized with a fully green suite -- the BL-027 lesson, in
    the same file, one token family later."""
    assert set(scaleValues(readCss(DASHBOARD_CSS))) == set(SCALE_TOKENS)


def test_scaleValues_agreeAcrossBothFiles():
    """The SSOT rule is only real if something enforces it: a drift in EITHER
    file re-reds this. US-540-a edits both together."""
    assert scaleValues(readCss(DASHBOARD_CSS)) == scaleValues(readCss(TOKENS_CSS))


def test_scale_isStrictlyDescending():
    """hero > primary > secondary > label > meta. Not cosmetic -- the safety
    hierarchies below are expressed as "a higher tier than", so an inverted or
    collapsed pair would let a STOP directive render no larger than the body
    copy while every other test stayed green. This survives US-540-a's value
    change by construction, because it asserts the ORDER and not the numbers."""
    values = scaleValues(readCss(TOKENS_CSS))
    ordered = [values[name] for name in SCALE_TOKENS]
    assert ordered == sorted(ordered, reverse=True), ordered
    assert len(set(ordered)) == len(ordered), f"two tiers collapsed onto one size: {ordered}"


# ---------------------------------------------------------------------------
# AC3 -- the refactor moved no hierarchy, and broke no load-bearing rule.
# ---------------------------------------------------------------------------


def test_stopTakeoverDirective_outranksTheBaseDirective():
    """Spool 6d AREA channel, re-asserted THROUGH the tokens: on a STOP the
    "PULL OVER" band is the biggest thing on the panel. The dedicated guard in
    test_dashboard_stop_tier_safety.py reads the same fact; this one fails first
    if the tokenization itself is what broke it."""
    css = readCss(DASHBOARD_CSS)
    base = resolveFontPx(css, _ruleBlock(css, ".takeover-directive {"))
    stop = resolveFontPx(
        css, _ruleBlock(css, '#dtc-takeover[data-severity="stop"] .takeover-directive {')
    )
    assert base > 0 and stop > 0, (base, stop)
    assert stop > base, f"STOP directive {stop}px <= base {base}px"


def test_detailDirective_outranksItsBaseCopy():
    """US-491 AC1 ("what do I do" lands first from arm's length), re-asserted
    through the tokens: the directive band sits a full tier above the base copy,
    not a token 1px above it."""
    css = readCss(DASHBOARD_CSS)
    band = resolveFontPx(css, _ruleBlock(css, ".detail-directive {"))
    base = resolveFontPx(css, _ruleBlock(css, ".detail-fix-text"))
    assert base > 0, "base copy size moved -- re-point this guard"
    assert band > base, f"directive {band}px is not above base copy {base}px"


def test_detailValue_stillDeclaresInheritAndNotAScaleToken():
    """THE LOAD-BEARING ONE, carried across the refactor. `.detail-value` wraps
    every detail row's text, and a child's own declaration beats an inherited
    one however specific the parent is -- so binding a scale token here would
    re-break exactly what US-491 fixed, and would look tidier while doing it."""
    block = _ruleBlock(readCss(DASHBOARD_CSS), ".detail-value {")
    assert "inherit" in block
    assert "var(--fs-" not in block
    assert resolveFontPx(readCss(DASHBOARD_CSS), block) == -1


def test_noRuleShrank_theScaleFloorIsTheOldSmallestSize():
    """AC3's direction of travel. The refactor rounds every off-scale size UP to
    its tier, so nothing on the panel got smaller -- the old floor was the 8px
    IMU tape furniture, and `--fs-meta` sits at or above it. A future edit that
    drops the floor below the pre-F-127 smallest size is moving AWAY from the
    legibility this feature exists to deliver."""
    values = scaleValues(readCss(TOKENS_CSS))
    assert values["fs-meta"] >= 8
