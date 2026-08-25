################################################################################
# File Name: test_dashboard_type_scale_values.py
# Purpose/Description: US-540-a (F-127) tests -- the type scale US-539 established
#   now carries the IN-CAR legibility VALUES: hero 44 / primary 34 / secondary 26
#   / label 20 / meta 15 px on the 480x320 stage. Iris's [FLOOR RULE] is the fact
#   worth pinning: anything the driver MUST read while moving sits at >= 34px, and
#   a tier below 26px is non-critical copy only. US-539's gate proves the sizes all
#   come from the scale; this one proves the scale is set where the operator can
#   read it at arm's length.
#
#   THE VALUES ARE PINNED, NOT BOUNDED. A pure floor test (">= 34") would stay
#   green if a later edit pushed hero to 90px and overflowed every card, and would
#   also stay green if this story never ran -- the pre-F-127 hero was 40. Pinning
#   the five numbers means the next deliberate change edits ONE line here and says
#   so, while an accidental one goes red. Iris owns the numbers; this file is only
#   their witness. THEY ARE NOT FINAL: the acceptance is in-car at arm's length,
#   and the Atlas display-pipeline finding (US-552 -- the deploy pins no KMS mode,
#   so the panel may be downsampling from 1080p) can raise the floor. Re-verify on
#   hardware AFTER the output mode is confirmed, then update this file if the
#   values move.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-540-a 3.5in legibility scale values.
# ================================================================================
################################################################################

"""US-540-a tests: the F-127 type-scale VALUES for 3.5in in-car legibility."""

from tests.ui.css_type_scale import (
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

# Iris's scale for the 480x320 panel, read seated at arm's length (US-540-a AC1).
LEGIBILITY_SCALE = {
    "fs-hero": 44,
    "fs-primary": 34,
    "fs-secondary": 26,
    "fs-label": 20,
    "fs-meta": 15,
}

# [EXACT:34]px -- Iris's floor for anything the driver MUST read while moving.
DRIVER_MUST_READ_FLOOR_PX = 34

# Below this, a tier is non-critical copy only (read parked, or glanced past).
NON_CRITICAL_CEILING_PX = 26


# ---------------------------------------------------------------------------
# AC1 -- the values, in both files (the SSOT and the sheet the panel loads).
# ---------------------------------------------------------------------------


def test_ssot_carriesTheLegibilityScaleValues():
    """
    Given: src/pi/ui/tokens.css is the visual SSOT for the type scale
    When: the F-127 legibility values are set
    Then: all five tokens read Iris's numbers
    """
    assert scaleValues(readCss(TOKENS_CSS)) == LEGIBILITY_SCALE


def test_shippedSheet_carriesTheLegibilityScaleValues():
    """
    Given: dashboard.html links ONLY dashboard.css, which mirrors the SSOT block
    When: the values are set in the SSOT alone
    Then: the panel would render at the OLD sizes with a green SSOT test -- so the
          mirror is asserted here in its own right (the BL-027 lesson)
    """
    assert scaleValues(readCss(DASHBOARD_CSS)) == LEGIBILITY_SCALE


# ---------------------------------------------------------------------------
# AC1 -- the [FLOOR RULE], stated as the rule and not as the numbers.
# ---------------------------------------------------------------------------


def test_driverMustReadTiers_meetTheThirtyFourPxFloor():
    """
    Given: hero and primary are the tiers a moving driver reads (the gear, tile
           values, the takeover code, the STOP directive)
    When: the scale is set
    Then: both sit at or above the [EXACT:34]px floor

    Stated separately from the pinned values above so the INTENT survives a
    future value edit: change the numbers and this still says what they are for.
    """
    values = scaleValues(readCss(TOKENS_CSS))
    assert values["fs-hero"] >= DRIVER_MUST_READ_FLOOR_PX
    assert values["fs-primary"] >= DRIVER_MUST_READ_FLOOR_PX


def test_subCriticalTiers_stayBelowTheDriverMustReadTiers():
    """
    Given: label and meta carry sub-labels, chips and micro-copy -- honest to
           read parked, never a fact the driver needs mid-corner
    When: the scale is set
    Then: they land under the non-critical ceiling, so nothing driver-critical
          can be styled into them by accident and still look intentional
    """
    values = scaleValues(readCss(TOKENS_CSS))
    assert values["fs-label"] < NON_CRITICAL_CEILING_PX
    assert values["fs-meta"] < NON_CRITICAL_CEILING_PX


def test_everyTier_grewOrHeldAgainstThePreF127Scale():
    """
    Given: the pre-F-127 shipped scale was 40 / 20 / 14 / 12 / 10
    When: the legibility values are set
    Then: no tier got SMALLER -- F-127 exists because the panel reads too small,
          so a tier moving down is the feature travelling backwards
    """
    preF127 = {"fs-hero": 40, "fs-primary": 20, "fs-secondary": 14, "fs-label": 12, "fs-meta": 10}
    values = scaleValues(readCss(TOKENS_CSS))
    shrank = {name: values[name] for name in SCALE_TOKENS if values[name] < preF127[name]}
    assert shrank == {}, f"tiers moved DOWN against the pre-F-127 scale: {shrank}"


# ---------------------------------------------------------------------------
# AC1 -- the values land on the surface, not just in :root.
# ---------------------------------------------------------------------------


def test_theStopDirective_resolvesToTheHeroValue():
    """
    Given: the STOP takeover directive ("PULL OVER NOW") is bound to --fs-hero
    When: hero is raised to the legibility value
    Then: the directive resolves to it -- the proof that the :root edit reaches
          the rendered surface, taken on the one rule where size is a SAFETY
          property (Spool 6d). It is also the widest line on the panel: 44px
          mono is the value to eyeball first during the in-car acceptance.
    """
    css = readCss(DASHBOARD_CSS)
    stop = _ruleBlock(css, '#dtc-takeover[data-severity="stop"] .takeover-directive {')
    assert resolveFontPx(css, stop) == LEGIBILITY_SCALE["fs-hero"]


def test_aTileValue_resolvesToTheDriverMustReadFloor():
    """
    Given: `.tile-value` is the class every card's primary number wears
    When: primary is raised to the legibility value
    Then: it resolves to >= the 34px floor -- the AC's "driver-must-read
          elements >= 34px effective", asserted where the operator meets it
    """
    css = readCss(DASHBOARD_CSS)
    assert resolveFontPx(css, _ruleBlock(css, ".tile-value")) >= DRIVER_MUST_READ_FLOOR_PX
