################################################################################
# File Name: test_overlay_opacity_model.py
# Purpose/Description: US-558 (F-132) tests for Iris's P-4 rule -- "an overlay you
#   NAVIGATE TO is a destination and paints solid; an overlay that INTERRUPTS you
#   is a modal and keeps its scrim". Three full-screen overlays shipped a
#   translucent black field (#setup-menu at .92, #sys-detail and #dtc-detail at
#   .95), so a bright card ghosted through the exact surface where the operator
#   reads settings and service controls.
#   The durable half is NOT "change three alphas" -- it is that the sheet now has
#   a CLASSIFICATION every full-screen layer must carry. This module DISCOVERS
#   the layers out of the stylesheet rather than hard-coding a list, so an overlay
#   added tomorrow fails the guard until somebody says which kind it is. That is
#   what stops the next overlay landing at 0.93 because the rule above it did.
#   WHAT IS NOT GUARDED, stated rather than implied: this repo's render harness
#   resolves the CASCADE but NOT compositing, so nothing here can assert "zero
#   bleed-through ON THE GLASS". That is validationCriteria #1 and #2, and both
#   are owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Ralph (Rex)  | Initial -- US-558 destination-vs-modal opacity.
# ================================================================================
################################################################################

"""US-558 tests: navigational overlays paint solid; modals keep their scrim."""

from __future__ import annotations

import re

import pytest

from tests.ui.css_type_scale import DASHBOARD_CSS, readCss, ruleBlock

# The FIELD token every solid surface on this panel already paints. #screen -- the
# letterbox frame behind the whole scaled stage -- binds it too, which is why a
# destination overlay binding the same token reads as "the panel's own black"
# rather than as a fourth opinion about what black is.
FIELD_TOKEN = "var(--bg)"

# Iris's P-4 classification, with the reason each layer is on the side it is on.
# The ROLE is the durable artefact; the alphas are just what the role implies.
DESTINATION = "destination"  # you navigated here -> it is a screen -> solid
MODAL = "modal"  # it interrupted you -> the thing underneath is still yours
ALARM = "alarm"  # neither; the DTC safety design owns its treatment

OVERLAY_ROLES = {
    "#setup-menu": (
        DESTINATION,
        "System Setup -- reached by the kebab or a long-press; service controls "
        "and settings are read here",
    ),
    "#sys-detail": (
        DESTINATION,
        "US-509 System-Status drill-down -- tapped through from the card",
    ),
    "#dtc-detail": (
        DESTINATION,
        "US-406 per-code detail -- tapped through from the Alerts list",
    ),
    "#confirm-modal": (
        MODAL,
        "US-403 confirm -- the scrim says the thing you were doing is still "
        "underneath and Cancel returns you to it",
    ),
    "#clear-confirm": (
        MODAL,
        "US-484-b Mode-04 clear confirm -- same contract, higher stakes",
    ),
    "#dtc-takeover": (
        ALARM,
        "US-405 severity takeover -- OUT OF SCOPE per AC-4; its field is set "
        "per-severity by the DTC safety design, not by this rule",
    ),
}


# ---------------------------------------------------------------------------
# Reading the sheet
# ---------------------------------------------------------------------------


def _stripComments(css: str) -> str:
    """The sheet with `/* ... */` removed, newlines preserved.

    Load-bearing for the walk below, and it is the sort of thing that fails
    QUIETLY: a comment contains no braces, so an un-stripped `/* ... */` reads as
    part of the NEXT rule's selector and that rule silently drops out of
    discovery. This sheet comments nearly every rule, so the guard would have
    found almost nothing while reporting green.

    Args:
        css: the full stylesheet text.

    Returns:
        The stylesheet with comment bodies blanked out.
    """
    return re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), css, flags=re.DOTALL)


def _rules(css: str):
    """Every top-level rule in the sheet as (selector, body).

    Anchored at column 0 so the indented bodies inside `@keyframes` are not
    mistaken for rules of their own -- and a selector may not START with `}`,
    which is the second half of the same trap: an at-rule's closing brace sits at
    column 0, so a first-character class that admits it swallows the whole
    following selector and that rule vanishes from discovery.

    Args:
        css: the full stylesheet text.

    Returns:
        A list of (selector, body) pairs in source order.
    """
    return [
        (match.group(1).strip(), match.group(2))
        for match in re.finditer(
            r"^([^\s@{}][^{}]*?)\s*\{([^{}]*)\}", _stripComments(css), re.MULTILINE
        )
    ]


def fullScreenLayers(css: str) -> set:
    """Every STACKED full-screen layer declared in the sheet.

    DISCOVERED, not listed. The predicate is the shape that makes something an
    overlay rather than a citation of the six that exist today: pinned to the
    viewport (`position: fixed`), covering it (`inset: 0`), and placed in the
    stacking order (`z-index`). #screen satisfies the first two and deliberately
    declines the third -- it is the frame everything else stacks ON, not a layer
    over anything -- so the predicate excludes it on a real distinction rather
    than by name.

    Args:
        css: the full stylesheet text.

    Returns:
        The set of selectors that declare a stacked full-screen layer.
    """
    found = set()
    for selector, body in _rules(css):
        if not re.search(r"(?<![-\w])position:\s*fixed", body):
            continue
        if not re.search(r"(?<![-\w])inset:\s*0", body):
            continue
        if not re.search(r"(?<![-\w])z-index:", body):
            continue
        found.add(selector)
    return found


def _declaration(css: str, selector: str, prop: str) -> str:
    """The raw value of one declaration, or "" when it is not declared."""
    block = ruleBlock(css, selector)
    match = re.search(rf"(?<![-\w]){re.escape(prop)}:\s*([^;]+)", block)
    return match.group(1).strip() if match is not None else ""


def _colorToken(css: str, name: str) -> str:
    """The value declared for a custom property, read out of `:root`."""
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([^;]+);", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared"
    return match.group(1).strip()


def fieldAlpha(css: str, value: str) -> float:
    """The alpha a background value paints at, following one `var()` hop.

    This is the model the whole story rests on, so it RESOLVES rather than
    pattern-matches: `var(--bg)` has to be followed to `#000000` and reported as
    1.0, or "solid" would be a claim about spelling instead of about opacity.

    Args:
        css: the full stylesheet, used to resolve a token reference.
        value: a background value, e.g. `var(--bg)` or `rgba(0, 0, 0, 0.92)`.

    Returns:
        The alpha in 0..1.

    Raises:
        AssertionError: on a value this subset cannot resolve -- deliberately
            loud, because an unresolvable field silently treated as opaque is
            the exact false-green this story removes.
    """
    resolved = re.sub(
        r"var\(\s*--([a-zA-Z0-9-]+)\s*\)",
        lambda m: _colorToken(css, m.group(1)),
        value.strip(),
    )
    functional = re.fullmatch(r"(?:rgba?|hsla?)\(([^)]*)\)", resolved)
    if functional is not None:
        parts = [part.strip() for part in re.split(r"[,/]", functional.group(1)) if part.strip()]
        if len(parts) < 4:
            return 1.0
        alpha = parts[3]
        return float(alpha.rstrip("%")) / 100 if alpha.endswith("%") else float(alpha)
    if re.fullmatch(r"#[0-9a-fA-F]{6}", resolved):
        return 1.0
    if re.fullmatch(r"#[0-9a-fA-F]{8}", resolved):
        return int(resolved[7:9], 16) / 255
    raise AssertionError(f"{value!r} resolves to {resolved!r}, whose alpha is not readable")


def _byRole(role: str) -> list:
    return sorted(sel for sel, (kind, _) in OVERLAY_ROLES.items() if kind == role)


# ---------------------------------------------------------------------------
# The classification is complete -- the durable half of the story.
# ---------------------------------------------------------------------------


def test_everyFullScreenLayerCarriesARole():
    """AC-2's rule, made structural. A new overlay cannot be added to this sheet
    without somebody deciding whether it is a destination or an interruption --
    which is the only thing that stops the next one landing at 0.93 because the
    rule above it did.

    Both directions are asserted. An UNCLASSIFIED layer is the drift this
    guards; a classified selector that no longer EXISTS is a dead entry, and a
    stale allowlist is a gate quietly widened for a rule that is gone."""
    discovered = fullScreenLayers(readCss(DASHBOARD_CSS))
    classified = set(OVERLAY_ROLES)
    assert discovered - classified == set(), (
        f"unclassified full-screen overlay(s): {sorted(discovered - classified)} -- "
        f"decide whether each is a DESTINATION (solid) or a MODAL (scrim) and add "
        f"it to OVERLAY_ROLES with the reason"
    )
    assert classified - discovered == set(), (
        f"OVERLAY_ROLES names {sorted(classified - discovered)}, which the sheet no "
        f"longer declares as a full-screen layer"
    )


def test_theLetterboxFrameIsNotCountedAsAnOverlay():
    """The discovery predicate's own boundary case, pinned so it is not a
    coincidence. #screen is `position: fixed; inset: 0` and paints `var(--bg)`,
    so a laxer predicate would sweep it in and it would pass the destination
    check for entirely the wrong reason -- it is the frame the overlays stack
    ON, not one of them."""
    css = readCss(DASHBOARD_CSS)
    assert "#screen" not in fullScreenLayers(css)
    assert _declaration(css, "#screen", "z-index") == "", (
        "#screen now declares a z-index, so it reads as a stacked layer -- "
        "re-read the discovery predicate before trusting this module"
    )


# ---------------------------------------------------------------------------
# AC-1 -- destinations paint solid.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("selector", _byRole(DESTINATION))
def test_navigationalOverlaysPaintAnOpaqueField(selector):
    """AC-1. Computed through the token, so this measures OPACITY rather than
    the spelling of a declaration."""
    css = readCss(DASHBOARD_CSS)
    value = _declaration(css, selector, "background")
    assert value, f"{selector} declares no background at all -- it would show the card behind"
    alpha = fieldAlpha(css, value)
    _, reason = OVERLAY_ROLES[selector]
    assert alpha == 1.0, (
        f"{selector} paints at alpha {alpha} -- {(1 - alpha) * 100:.0f}% of the live "
        f"carousel bleeds through a surface you navigated to ({reason})"
    )


@pytest.mark.parametrize("selector", _byRole(DESTINATION))
def test_navigationalOverlaysBindTheFieldToken_ratherThanRestatingBlack(selector):
    """A second, DIFFERENT failure. `rgba(0, 0, 0, 1)` is opaque and would pass
    the check above while landing a fresh literal in a sheet US-557 spent a story
    clearing of them. The field is a token because #screen, the takeover's STOP
    field and these three overlays are all the same black by intent -- four
    literals would only look identical until one moved."""
    assert _declaration(readCss(DASHBOARD_CSS), selector, "background") == FIELD_TOKEN


@pytest.mark.parametrize("selector", _byRole(DESTINATION))
def test_navigationalOverlaysDoNotReintroduceTranslucencyByAnotherRoute(selector):
    """`background` is not the only way to make a layer see-through, and an
    opacity fix that only guards the property it happened to find is the same
    fix-one-and-close the sprint keeps rejecting. `opacity` fades the overlay AND
    its content; `backdrop-filter` deliberately samples what is behind it."""
    block = ruleBlock(readCss(DASHBOARD_CSS), selector)
    assert not re.search(r"(?<![-\w])opacity:", block), (
        f"{selector} declares opacity -- a solid field faded by the layer above it "
        f"is still translucent"
    )
    assert not re.search(r"(?<![-\w])(-webkit-)?backdrop-filter:", block), (
        f"{selector} declares a backdrop-filter, which exists to show what is behind"
    )
    assert not re.search(r"(?<![-\w])background-(color|image):", block), (
        f"{selector} declares a second background property, which can override the "
        f"field this module reads"
    )


# ---------------------------------------------------------------------------
# AC-3 -- the modals keep their scrim. This is the regression guard.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("selector", _byRole(MODAL))
def test_interruptingModalsKeepTheirScrim(selector):
    """AC-3, and it is the half most likely to be lost: a sweep that reads
    "make the overlays opaque" takes these two with it. The translucency is
    DOING WORK here -- it is what says the thing you were doing is still
    underneath and Cancel returns you to it.

    Bounded on both sides. Fully transparent would be no scrim at all; fully
    opaque would be the destination treatment on a surface that is not one."""
    css = readCss(DASHBOARD_CSS)
    _, reason = OVERLAY_ROLES[selector]
    alpha = fieldAlpha(css, _declaration(css, selector, "background"))
    assert 0 < alpha < 1, (
        f"{selector} paints at alpha {alpha} -- it must keep a scrim ({reason})"
    )


def test_bothModalsScrimAtTheSameStrength():
    """Two confirms that dim the panel by different amounts would teach the
    operator that one interruption is more real than the other, when the only
    difference between them is what they are confirming. Read out of the sheet
    rather than asserted as 0.6, so this stays true if the value is ever tuned
    -- what it forbids is the two DRIFTING."""
    css = readCss(DASHBOARD_CSS)
    alphas = {sel: fieldAlpha(css, _declaration(css, sel, "background")) for sel in _byRole(MODAL)}
    assert len(set(alphas.values())) == 1, f"the two scrims have diverged: {alphas}"


# ---------------------------------------------------------------------------
# AC-4 -- the alarm is out of scope, and that is checkable.
# ---------------------------------------------------------------------------


def test_theTakeoverFieldIsStillOwnedBySeverity_notByThisStory():
    """AC-4. `#dtc-takeover` is neither a destination nor an interruption -- it
    is an alarm, and US-484-b made its full-bleed field one of four reinforcing
    channels. Its base rule deliberately declares NO background so each severity
    owns its own; sweeping a `var(--bg)` into the base would have painted a
    near-black field under the WATCH gradient and quietly weakened the AREA
    channel the STOP tier is built on.

    Pinned as an absence, because "I did not touch it" is otherwise a claim in a
    close note rather than a property of the sheet."""
    css = readCss(DASHBOARD_CSS)
    assert _declaration(css, "#dtc-takeover", "background") == "", (
        "the takeover base rule now declares a field, which overrides nothing but "
        "does sit under every severity variant -- AC-4 puts this out of scope"
    )
    assert _declaration(css, '#dtc-takeover[data-severity="stop"]', "background") == FIELD_TOKEN
    for severity in ("watch", "minor", "unknown"):
        value = _declaration(css, f'#dtc-takeover[data-severity="{severity}"]', "background")
        assert value.startswith("radial-gradient("), (
            f"the {severity} takeover no longer paints its severity gradient"
        )


# ---------------------------------------------------------------------------
# Negative self-tests -- a check never seen to fail is not known to be a check.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "shipped",
    ["rgba(0, 0, 0, 0.92)", "rgba(0, 0, 0, 0.95)", "rgba(0,0,0,.5)", "#000000CC"],
)
def test_theOpacityModelGoesRedOnTheShippedTranslucentFields(shipped):
    """The destination check's negative self-test, run against the REAL values
    this story removes rather than an invented one. If `fieldAlpha` reported
    these as opaque, every assertion above would be green on the defect."""
    assert fieldAlpha(readCss(DASHBOARD_CSS), shipped) < 1.0


@pytest.mark.parametrize("opaque", ["var(--bg)", "#000000", "rgba(0, 0, 0, 1)"])
def test_theScrimGuardWouldGoRedIfAModalWereMadeSolid(opaque):
    """The regression guard's own negative self-test. The scrim assertion has to
    be able to SEE the sweep that would take the confirms with the destinations,
    or AC-3 is a comment."""
    assert not 0 < fieldAlpha(readCss(DASHBOARD_CSS), opaque) < 1


def test_anUnclassifiedOverlayIsDiscovered():
    """The classification guard's negative self-test: the durable claim is that a
    NEW overlay is caught, and the only way to know that is to add one. Appended
    to the real sheet so the discovery walk runs over its actual shape."""
    css = readCss(DASHBOARD_CSS) + (
        "\n#future-overlay {\n  position: fixed; inset: 0; z-index: 70;\n"
        "  background: rgba(0, 0, 0, 0.93);\n}\n"
    )
    assert fullScreenLayers(css) - set(OVERLAY_ROLES) == {"#future-overlay"}


def test_theDiscoveryWalkSeesARuleThroughTheCommentAboveIt():
    """The comment-stripping trap, pinned because it fails SILENTLY in the
    direction that reports success: an un-stripped `/* ... */` reads as part of
    the following selector, that rule drops out of discovery, and the
    classification guard goes green having looked at almost nothing. Nearly
    every rule in this sheet carries a comment, so this is the normal case, not
    an edge one."""
    commented = "/* a rule\n   with a multi-line comment above it */\n" + (
        "#late-overlay {\n  position: fixed; inset: 0; z-index: 80;\n}\n"
    )
    assert "#late-overlay" in fullScreenLayers(commented)


def test_theDiscoveryWalkSeesARuleFollowingAnAtRule():
    """The other half of the same silent trap, and the one that actually bit:
    `@keyframes` closes with a `}` at column 0, so a walk that lets a selector
    begin with `}` reads `} ... #dtc-takeover` as ONE selector and loses the rule
    entirely. The takeover is declared immediately after a keyframes block in the
    shipped sheet, which is how this surfaced."""
    afterAtRule = "@keyframes pulse {\n  0% { opacity: 1; }\n}\n" + (
        "#post-keyframes-overlay {\n  position: fixed; inset: 0; z-index: 90;\n}\n"
    )
    assert fullScreenLayers(afterAtRule) == {"#post-keyframes-overlay"}


def test_anUnresolvableFieldIsLoudRatherThanAssumedOpaque():
    """The model's failure mode is a design choice worth pinning. A background
    this subset cannot read must raise, not default -- defaulting to 1.0 would
    make every unreadable field pass the destination check, and defaulting to 0
    would make it pass the scrim check. Either default turns the guard into
    theatre for exactly the values nobody anticipated."""
    with pytest.raises(AssertionError):
        fieldAlpha(readCss(DASHBOARD_CSS), "linear-gradient(#000, #111)")
