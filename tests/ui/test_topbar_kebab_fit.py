################################################################################
# File Name: test_topbar_kebab_fit.py
# Purpose/Description: US-556 (F-132) tests for the ⋮ kebab fitting the bar it
#   sits in, and for the two controls that carry the SAME pattern. The defect is
#   a VISUAL box larger than the BAND that paints behind it: #menu-btn shipped a
#   `--tap-min` (40px) box holding a `--fs-primary` (34px) glyph inside a #topbar
#   that is `--bar-h` tall, so the third dot painted outside the header fill.
#   THREE things are guarded here and they fail for three different reasons:
#     1. THE VISUAL BOX (AC-1/AC-3) -- the painted box and the glyph both fit the
#        band, and the glyph took the CHROME tier rather than being shrunk below
#        Iris's non-critical floor. Cut chrome, not size.
#     2. THE HIT BOX (AC-2) -- >= --tap-min on BOTH axes, extended by a
#        transparent pseudo-element that costs no layout. Asserted as a derived
#        identity that holds at ANY bar height, not as the design note's
#        `inset: -6px -7px` -- those two literals were arithmetic against the
#        PRE-US-557 28px bar.
#     3. THE AUDIT (AC-4) -- #menu-close and #sys-detail-back run through ONE
#        band-vs-control model with the kebab, so "audited in-story" is a
#        checkable claim rather than a sentence in a close note.
#   WHAT IS NOT GUARDED, stated rather than implied: this repo's render harness
#   resolves the CASCADE but NOT LAYOUT, so no bench test here can assert "no
#   glyph paints outside its header ON THE GLASS". That is validationCriteria #1
#   and #2, and both are owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Ralph (Rex)  | Initial -- US-556 kebab visual box vs hit box.
# ================================================================================
################################################################################

"""US-556 tests: the ⋮ fits its bar, and keeps a thumb-sized tap target."""

from __future__ import annotations

import ast
import operator
import re

import pytest

# The arithmetic `calc()` can express, evaluated over a WHITELISTED AST rather
# than with eval(): the input is a repo-local stylesheet, but a resolver that
# would run whatever it was handed is a bad shape to leave in a shared helper
# that later tests will copy.
_CALC_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}

from tests.ui.css_type_scale import DASHBOARD_CSS, readCss, ruleBlock, scaleValues

# The three (control, band) pairs AC-4 puts in one audit. The kebab is the story;
# the other two are named in the acceptance line precisely so this does not
# become "fix one and close the story". Each carries the reason it is here.
CONTROL_BANDS = {
    "#menu-btn": (
        "#topbar",
        "the story's subject -- a --tap-min box in a --bar-h band",
    ),
    "#menu-close": (
        ".menu-head",
        "US-403 setup-menu dismiss: a --tap-min box in a head that declared a "
        "FIXED height",
    ),
    "#sys-detail-back": (
        ".detail-head",
        "US-509 drill-down Back, sharing the per-code overlay's head shell that "
        "US-491 already sized against --tap-min",
    ),
}

# Iris's F-127 floor rule, the half that governs chrome: anything below 26px must
# be non-critical. The kebab IS non-critical, so it may sit AT that floor -- but
# dropping it below would be shrinking type to make the arithmetic work, which is
# the fix F-127 spent a whole sprint ruling out.
CHROME_TIER_TOKEN = "fs-secondary"

# The tier the kebab must NOT wear. --fs-primary is the driver-must-read value
# tier; binding chrome to it is what tied the glyph to a size F-127 then raised.
VALUE_TIER_TOKEN = "fs-primary"


# ---------------------------------------------------------------------------
# CSS reading + a very small length resolver
# ---------------------------------------------------------------------------


def _tokenPx(css: str, name: str) -> float:
    """The px magnitude declared for a custom property, read not assumed.

    Args:
        css: the full stylesheet text.
        name: the custom-property name without its leading `--`.

    Returns:
        The declared magnitude in px.
    """
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([0-9.]+)px;", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared as a px value"
    return float(match.group(1))


def _evalArithmetic(expr: str) -> float:
    """Evaluate a pure-arithmetic expression over a whitelisted AST.

    Args:
        expr: an expression containing only numbers, `+ - * /` and parentheses.

    Returns:
        The value as a float.

    Raises:
        AssertionError: on any node outside the whitelist -- loud rather than
            permissive, so an unresolvable expression cannot quietly become a
            number the model then trusts.
    """

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = walk(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in _CALC_BINARY_OPS:
            return _CALC_BINARY_OPS[type(node.op)](walk(node.left), walk(node.right))
        raise AssertionError(f"{expr!r} contains {type(node).__name__}, which is not arithmetic")

    return walk(ast.parse(expr, mode="eval"))


def _resolveLength(css: str, expr: str) -> float:
    """Resolve a CSS length expression to px, following `var()` and `calc()`.

    This exists so the hit-box assertions can be COMPUTED from the shipped
    declaration rather than restating the number the declaration is supposed to
    produce. A test that hard-codes `40` cannot tell the difference between a
    correct derivation and a coincidence.

    Args:
        css: the full stylesheet, used to resolve token references.
        expr: a length expression, e.g. `var(--bar-h)` or
            `calc((var(--bar-h) - var(--tap-min)) / 2)`.

    Returns:
        The resolved magnitude in px.

    Raises:
        AssertionError: when the expression is not resolvable by this subset --
            deliberately loud, because a silently-unresolvable expression would
            let a real geometry change slip past the model.
    """
    resolved = re.sub(
        r"var\(\s*--([a-zA-Z0-9-]+)\s*\)",
        lambda m: repr(_tokenPx(css, m.group(1))),
        expr,
    )
    resolved = re.sub(r"(?<![-\w])calc\s*\(", "(", resolved)
    resolved = resolved.replace("px", "")
    assert re.fullmatch(r"[0-9+\-*/(). ]+", resolved), (
        f"{expr!r} resolves to {resolved!r}, which this subset cannot evaluate"
    )
    return _evalArithmetic(resolved)


def _declaration(css: str, selector: str, prop: str) -> str:
    """The raw value of one declaration, or "" when it is not declared."""
    block = ruleBlock(css, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*([^;]+)", block)
    return match.group(1).strip() if match is not None else ""


def _boxHeightPx(css: str, selector: str) -> float:
    """The height a rule actually asks for: `height` if given, else `min-height`.

    Both properties are read because the two sides of this defect express
    themselves differently -- a control states a FLOOR (`min-height`) while a
    band historically stated a FIXED height. The overflow is the same either way,
    so the model must not care which one it finds.

    Args:
        css: the full stylesheet.
        selector: the exact selector.

    Returns:
        The resolved height in px.
    """
    for prop in ("height", "min-height"):
        value = _declaration(css, selector, prop)
        if value and value not in ("auto", "100%"):
            return _resolveLength(css, value)
    raise AssertionError(f"{selector} declares no resolvable height")


def _fontSizeToken(css: str, selector: str) -> str:
    """The type-scale token a rule's `font-size` binds, without its `--`."""
    block = ruleBlock(css, selector)
    match = re.search(r"(?<![-\w])font-size:\s*var\(--([a-zA-Z0-9-]+)\)", block)
    assert match is not None, f"{selector} does not bind font-size to a token"
    return match.group(1)


class _KebabBoxes:
    """The kebab's two boxes -- painted and touchable -- from the shipped sheet.

    The whole story is that these are DIFFERENT boxes. Modelling them as one
    object keeps that distinction in the test's vocabulary instead of leaving it
    implicit in two unrelated assertions.
    """

    def __init__(self, css: str) -> None:
        self.css = css
        self.barH = _tokenPx(css, "bar-h")
        self.tapMin = _tokenPx(css, "tap-min")
        self.boxW = _resolveLength(css, _declaration(css, "#menu-btn", "width"))
        self.boxH = _boxHeightPx(css, "#menu-btn")
        self.glyphPx = scaleValues(css)[_fontSizeToken(css, "#menu-btn")]
        self.lineHeight = float(_declaration(css, "#menu-btn", "line-height") or 1.0)
        self.inset = _resolveLength(css, _declaration(css, "#menu-btn::after", "inset"))

    @property
    def glyphLineBox(self) -> float:
        """The vertical space the ⋮ itself occupies inside the button."""
        return self.glyphPx * self.lineHeight

    def _hitExtent(self, boxExtent: float) -> float:
        """The touchable extent on one axis.

        A negative `inset` grows the pseudo-element OUTSIDE the button, which is
        what extends the target. A positive inset shrinks it back inside, in
        which case the BUTTON is still the target -- so the reachable extent is
        the larger of the two, never the pseudo alone.
        """
        return max(boxExtent, boxExtent - 2 * self.inset)

    @property
    def hitW(self) -> float:
        return self._hitExtent(self.boxW)

    @property
    def hitH(self) -> float:
        return self._hitExtent(self.boxH)


# ---------------------------------------------------------------------------
# AC-1 -- the painted box is the band.
# ---------------------------------------------------------------------------


def test_kebabVisualBox_derivesFromTheBandRatherThanTheTapMinimum():
    """AC-1. `min-width`/`min-height` no longer inflate the painted box to
    `--tap-min`, and both painted dimensions read `--bar-h`.

    Asserted as a TOKEN BINDING, not as a magnitude: the failure this sprint
    exists to remove is a correct number written somewhere it cannot be forced
    to reconcile when the band moves. `width: 28px` would satisfy an
    equals-34-today check the day US-557 moved the bar and nothing else."""
    css = readCss(DASHBOARD_CSS)
    for prop in ("width", "height"):
        assert _declaration(css, "#menu-btn", prop) == "var(--bar-h)", (
            f"#menu-btn {prop} must derive from --bar-h, not restate a magnitude"
        )
    for prop in ("min-width", "min-height"):
        assert _declaration(css, "#menu-btn", prop) == "0", (
            f"#menu-btn still carries a {prop} floor, which is what made the "
            f"painted box outgrow the header fill"
        )


def test_kebabPaintedBoxAndGlyph_bothFitTheHeaderFill():
    """THE DEFECT, STATED AS ARITHMETIC. #topbar paints `--surface` for exactly
    its own height; anything taller shows outside the fill. Both the button box
    and the glyph's line box are checked, because the shipped defect was BOTH --
    a 40px box AND a 34px glyph in a band that was neither."""
    boxes = _KebabBoxes(readCss(DASHBOARD_CSS))
    assert boxes.boxH <= boxes.barH, (
        f"painted box {boxes.boxH}px exceeds the {boxes.barH}px header fill"
    )
    assert boxes.glyphLineBox < boxes.barH, (
        f"the ⋮ line box is {boxes.glyphLineBox}px in a {boxes.barH}px bar -- "
        f"this is the third dot painting outside the header. STRICTLY less, not "
        f"merely equal: at --fs-primary the line box exactly FILLS today's band, "
        f"and glyph ink is not bound by a `line-height: 1` box, so flush is not "
        f"the same as safely inside"
    )


def test_thePreUs556Shape_stillDoesNotFitTodaysBar():
    """THE NEGATIVE SELF-TEST, and it carries a MEASURED CORRECTION to this
    story's own acceptance line.

    AC-1 describes the defect as `40px box + 34px glyph inside a 28px bar`. The
    28 is stale: US-557 moved the bar to 34 one story earlier in this sprint, and
    re-reading the arithmetic against 34 splits the premise in two.

      - THE GLYPH HALF IS ALREADY GONE. `--fs-primary` is 34px and `--bar-h` is
        now 34px, so the pre-US-556 glyph's line box exactly FILLS the band --
        it no longer strictly spills. What it has instead is ZERO margin, and
        glyph ink is not bound by a `line-height: 1` box, so "exactly flush" is
        not the same as "safely inside".
      - THE BOX HALF SURVIVED. `--tap-min` (40px) still exceeds the band, which
        is the overflow this story actually removes.

    Both are asserted, so if a later band change cures the box half too, this
    goes red and whoever moved it re-reads the story rather than inheriting it."""
    css = readCss(DASHBOARD_CSS)
    barH = _tokenPx(css, "bar-h")
    assert _tokenPx(css, "tap-min") > barH, (
        "the tap minimum no longer exceeds the bar -- the tension this story "
        "resolves is gone, so re-read the fix before trusting these tests"
    )
    assert scaleValues(css)[VALUE_TIER_TOKEN] >= barH, (
        "the value tier now fits the bar with room; the pre-US-556 glyph would "
        "be comfortable and this self-test proves nothing"
    )


# ---------------------------------------------------------------------------
# AC-3 -- the kebab is CHROME, not a value.
# ---------------------------------------------------------------------------


def test_kebabTakesTheChromeTier_notTheDriverReadValueTier():
    """AC-3. F-127's 34px floor is for anything the driver must read TO ACT. A
    menu affordance is not that, and it is `hidden` while driving anyway
    (US-490), so binding it to `--fs-primary` tied chrome to a tier F-127 then
    raised -- the tokenization was right, the tier was wrong."""
    token = _fontSizeToken(readCss(DASHBOARD_CSS), "#menu-btn")
    assert token == CHROME_TIER_TOKEN
    assert token != VALUE_TIER_TOKEN


def test_theValueTierItselfWasNotTouched():
    """The re-tier is scoped to ONE chrome control. If `--fs-primary` had been
    lowered to make the kebab fit, every driver-read number on the panel would
    have shrunk with it -- reversing F-127 to fix a cosmetic overflow. Pinned
    here so the cheap wrong fix cannot pass this file."""
    css = readCss(DASHBOARD_CSS)
    assert scaleValues(css)[VALUE_TIER_TOKEN] == 34
    assert re.search(r"(?<![-\w])font-size:\s*var\(--fs-primary\)", ruleBlock(css, ".tile-value"))


def test_theKebabWasNotSimplyShrunkBelowTheNonCriticalFloor():
    """Iris's rule has two halves and the second is easy to lose: anything below
    26px must be NON-CRITICAL. The kebab qualifies, so it may sit AT 26 -- but
    dropping it to `--fs-label` or `--fs-meta` to buy headroom would be shrinking
    type to fit a band, which is the fix F-127 ruled out. Cut chrome, not size."""
    css = readCss(DASHBOARD_CSS)
    scale = scaleValues(css)
    assert scale[_fontSizeToken(css, "#menu-btn")] >= scale[CHROME_TIER_TOKEN]


# ---------------------------------------------------------------------------
# AC-2 -- the hit box is extended, not grown.
# ---------------------------------------------------------------------------


def test_hitAreaIsATransparentPseudoElement_soItCostsNoLayoutAndNoPaint():
    """AC-2's mechanism. The extension must be invisible and must not enter
    layout, otherwise it is just a bigger button wearing a different name.

    `position: relative` on the button is load-bearing and is the quiet way this
    breaks: without it the absolutely-positioned pseudo anchors to the nearest
    positioned ancestor instead -- #topbar, which IS positioned -- and the hit
    area silently lands somewhere else entirely while every other assertion here
    still passes."""
    css = readCss(DASHBOARD_CSS)
    assert _declaration(css, "#menu-btn", "position") == "relative"
    after = ruleBlock(css, "#menu-btn::after")
    assert re.search(r'content:\s*""', after), "the pseudo-element never generates"
    assert "position: absolute" in after, "an in-flow pseudo would move the bar's layout"
    for painted in ("background", "border", "box-shadow", "outline"):
        assert not re.search(rf"(?<![-\w]){painted}(-[a-z]+)?:", after), (
            f"the hit-area extension declares {painted} -- it must paint nothing"
        )


def test_hitBoxMeetsTheTapMinimumOnBothAxes():
    """AC-2. COMPUTED from the shipped declarations, so it measures the
    derivation rather than restating its intended answer."""
    boxes = _KebabBoxes(readCss(DASHBOARD_CSS))
    assert boxes.hitW >= boxes.tapMin, f"hit width {boxes.hitW} < {boxes.tapMin}"
    assert boxes.hitH >= boxes.tapMin, f"hit height {boxes.hitH} < {boxes.tapMin}"


@pytest.mark.parametrize("barHeight", [16, 20, 28, 34, 40, 48])
def test_theHitBoxHoldsTheTapMinimumAtAnyBandHeight(barHeight):
    """WHY THE INSET IS DERIVED RATHER THAN THE NOTE'S `-6px -7px`.

    Those two literals were arithmetic against the pre-US-557 28px bar; US-557
    moved the bar to 34 one story earlier in this same sprint, and re-landing
    them would ship exactly the value-changed-here / measurement-left-behind
    defect F-132 exists to close. Half the signed shortfall holds the target at
    the minimum at EVERY band height -- including heights above the minimum,
    where the inset turns positive and the button itself carries the target."""
    css = re.sub(r"(--bar-h:\s*)[0-9.]+px", rf"\g<1>{barHeight}px", readCss(DASHBOARD_CSS))
    boxes = _KebabBoxes(css)
    assert boxes.barH == barHeight, "the --bar-h substitution did not fire"
    assert boxes.hitW >= boxes.tapMin
    assert boxes.hitH >= boxes.tapMin


def test_theHitBoxCheckGoesRedWithoutTheExtension():
    """The hit-box model's negative self-test: with the pseudo-element's inset
    neutralised, the painted box alone is smaller than the tap minimum. This is
    what makes the assertion above evidence that the ::after is doing the work,
    rather than a check the button would pass on its own."""
    css = readCss(DASHBOARD_CSS)
    neutralised = _KebabBoxes(css)
    neutralised.inset = 0.0
    assert neutralised.hitH < neutralised.tapMin
    assert neutralised.hitW < neutralised.tapMin


# ---------------------------------------------------------------------------
# AC-4 -- the same pattern, audited across all three controls.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("control", sorted(CONTROL_BANDS))
def test_noControlOutgrowsTheBandThatPaintsBehindIt(control):
    """AC-4 as ONE model over all three controls, which is what stops this being
    'fix the kebab and mention the others in prose'.

    The two overlay controls resolve the SAME tension differently, and that is
    deliberate rather than inconsistent: #topbar cannot afford to be 40px tall
    (US-557's budget already pays 6px for it and takes 29 back from three other
    bands), so there the CONTROL shrinks to the band and the target is extended.
    A full-screen overlay head has no such budget, so there the BAND grows to
    the control -- which is what US-491 already did for `.detail-head`."""
    css = readCss(DASHBOARD_CSS)
    band, reason = CONTROL_BANDS[control]
    controlH = _boxHeightPx(css, control)
    bandH = _boxHeightPx(css, band)
    assert controlH <= bandH, (
        f"{control} is {controlH}px inside a {bandH}px {band} ({reason}) -- it "
        f"paints outside the fill"
    )


def test_theAuditGoesRedOnTheDefectItWasWrittenToFind():
    """The audit's negative self-test, run against the two REAL pre-US-556
    shapes rather than an invented one: a `--tap-min` control in a `--bar-h`
    bar, and a `--tap-min` control in a fixed 36px head. Both must fail the
    model, or the sweep above is passing for some unrelated reason."""
    css = readCss(DASHBOARD_CSS)
    tapMin = _tokenPx(css, "tap-min")
    assert tapMin > _tokenPx(css, "bar-h"), "pre-US-556 #menu-btn would have fit"
    assert tapMin > 36, "pre-US-556 .menu-head at a fixed 36px would have fit"


def test_thePageDots_areThePrecedentForVisualBoxVsHitBox_andStayCorrect():
    """THE THIRD INSTANCE OF THE PATTERN, found while auditing and left ALONE.

    `.dot` is a `--tap-min` (40px) control inside a `#dots` band of `--dots-h`
    (16px) -- numerically a worse mismatch than the kebab's. It is nonetheless
    NOT a defect, and why not is the rule AC-4 is really about: what may not
    exceed the band is what the control PAINTS, not the box it reserves. `.dot`'s
    own box is transparent and border-less, and its visible mark lives in a
    `::before` that fits the band with room. Iris's P-3 note says the dots
    "ride the same invisible-hit-area pattern as P-2" -- this checks that claim
    instead of repeating it.

    So this sheet already contained a working answer to the kebab's tension, and
    #menu-btn takes the OTHER half of the same idea: shrink the painted box and
    extend the target, rather than keep a big transparent box and shrink the
    mark. The kebab needs its glyph to stay a real text node (it is the
    affordance, not decoration), and the bar's width budget charges the box that
    is actually in the grid -- 34px, not 40."""
    css = readCss(DASHBOARD_CSS)
    dotsBand = _boxHeightPx(css, "#dots")
    assert _boxHeightPx(css, ".dot") > dotsBand, (
        "the dots no longer over-reserve -- re-read this precedent before "
        "citing it for the kebab"
    )
    dot = ruleBlock(css, ".dot")
    assert "background: transparent" in dot and "border: 0" in dot, (
        ".dot's own box now paints something, so exceeding its band stopped "
        "being harmless"
    )
    mark = ruleBlock(css, ".dot::before")
    markHeight = _resolveLength(css, re.search(r"(?<![-\w])height:\s*([^;]+)", mark).group(1))
    assert markHeight <= dotsBand, f"the {markHeight}px dot mark exceeds its {dotsBand}px band"


def test_everyAuditedBandIsDerivedOrProvenAboveTheTapMinimum():
    """The durable half of AC-4. A band that CONTAINS a --tap-min control must
    not be free to drift back under it -- which is precisely how `.menu-head`
    ended up at a fixed 36px while `#menu-close` asked for 40.

    `.detail-head` is deliberately NOT rewritten: it declares a bare 44px, which
    is already above the minimum with room, and shrinking it to `--tap-min`
    would move two shipped overlays for no defect. It is GUARDED here instead --
    an audit that finds a compliant case adds a check, it does not add an edit."""
    css = readCss(DASHBOARD_CSS)
    tapMin = _tokenPx(css, "tap-min")
    assert _declaration(css, ".menu-head", "min-height") == "var(--tap-min)"
    assert _declaration(css, ".menu-head", "height") == "", (
        ".menu-head declares a FIXED height again -- a fixed band cannot grow to "
        "hold the control it contains, which is the whole defect"
    )
    assert _boxHeightPx(css, ".detail-head") >= tapMin
