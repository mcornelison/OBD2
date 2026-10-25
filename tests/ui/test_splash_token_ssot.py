################################################################################
# File Name: test_splash_token_ssot.py
# Purpose/Description: US-869-e (spec AC 12, Atlas C-Atlas-3) -- the F-103 splash
#   stylesheet renders against the visual SSOT (src/pi/ui/tokens.css), not the
#   stale palette it was born with (#888888 / #666666 / #000, 10-14 px text).
#
#   tokens.css is a DOCUMENT, not an import (src/pi/ui/README.md): index.html and
#   shutdown.html link ONLY splash/styles.css, so the splash carries a :root
#   MIRROR of the tokens it uses and this suite pins the mirror to the SSOT.
#   Modelled on tests/ui/test_dashboard_token_ssot.py (the dashboard's mirror
#   pin), and on test_dashboard_brand_font_payload.py for the inlined face.
#
#     (a) MIRROR   every :root custom property tokens.css also declares has
#                  tokens.css's value -- a drift in EITHER file re-reds it.
#     (b) LITERAL  outside :root no #hex, rgb()/hsl() or px font-size; every
#                  colour, font-size and font-family is a var(--...).
#     (c) FACE     ONE @font-face, payload byte-equal to tokens.css's.
#     (d) SUBSET   every string the splash pages set in Michroma is inside the
#                  38-glyph cut (michroma-advances.json).
#     (e) LICENCE  splash/OFL.txt is Iris's OFL-michroma.txt, byte for byte.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-24    | Ralph (Rex)  | Initial -- US-869-e splash token mirror + Michroma.
# 2026-10-25    | Ralph (Rex)  | RULED GUARD CHANGE (Atlas 2026-10-25, US-869-g
#               |              | R1): the brand face is allowed on exactly the
#               |              | named _BRAND_FACE_SELECTORS (#wordmark + the
#               |              | checklist labels); --green-ok joins _MIRRORED.
# 2026-10-25    | Ralph (Rex)  | US-870-b: --surface, --line, --accent and
#               |              | --text-primary join _MIRRORED (shutdown bar).
# 2026-10-25    | Ralph (Rex)  | RULED GUARD CHANGE (Atlas 2026-10-25, US-870-c
#               |              | R-guard): splash.svg is retired, so the motion
#               |              | test keeps only declared-once; _SPLASH_SVG gone.
# ================================================================================
################################################################################

"""US-869-e tests: splash/styles.css mirrors tokens.css, and carries Michroma."""

from __future__ import annotations

import os
import re

import tests.ui.render_harness as rh
from tests.ui.test_dashboard_brand_font_payload import (
    _SUBSET,
    _descriptor,
    _fontFaceBlocks,
    _payload,
)

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, "..", "..")
_UI = os.path.join(_ROOT, "src", "pi", "ui")
_TOKENS = os.path.join(_UI, "tokens.css")
_SPLASH = os.path.join(_UI, "splash")
_STYLES = os.path.join(_SPLASH, "styles.css")
_PAGES = ("index.html", "shutdown.html")
_SPLASH_OFL = os.path.join(_SPLASH, "OFL.txt")
_KIT_OFL = os.path.join(_ROOT, "specs", "assets", "fonts", "michroma", "OFL-michroma.txt")

# The tokens the splash renders against (spec AC 12 as Atlas reworded it). The
# motion six were promoted from the retired splash.svg (C-Atlas-3); tokens.css
# is now their only home (US-870-c).
_MOTION_TOKENS = ("t-spin", "t-fade", "bright-low", "bright-mid", "bright-hi", "bright-max")
_MIRRORED = (
    "bg",
    # US-870-b: the shutdown progress bar (track, ticks + marker, fill) and
    # its label line 1 (spec s2 / s2.2).
    "surface",
    "line",
    "accent",
    "text-primary",
    "text-secondary",
    "text-tertiary",
    "amber-warn",
    "green-ok",
    "fs-label",
    "fs-meta",
    "font-mono",
    "font-display",
) + _MOTION_TOKENS
# RULED GUARD CHANGE (Atlas 2026-10-25, US-869-g R1): the only rules that may
# bind the brand face -- the wordmark and the checklist labels ("labels
# Michroma, values mono"). Each is its own exact selector: no group selector,
# no `font:` shorthand (the guard's regex does not read the shorthand).
_BRAND_FACE_SELECTORS = ("#wordmark", "#checklist .cl-label")
# The properties whose value must be a token, never a literal (AC 12).
_TOKEN_ONLY_PROPS = ("color", "background", "background-color", "font-size", "font-family")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _stripComments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _declarations(block: str) -> dict[str, str]:
    """Every `--name: value;` in a block, value whitespace-normalised.

    Line-leading declarations only, so prose mentions of a token inside a
    comment never count (comments are stripped by the callers anyway).
    """
    return {
        name: re.sub(r"\s+", " ", value).strip()
        for name, value in re.findall(r"^\s*--([a-zA-Z0-9-]+):\s*([^;]+);", block, re.M)
    }


def _rootBlock(css: str) -> str:
    match = re.search(r":root\s*\{(.*?)\}", _stripComments(css), flags=re.DOTALL)
    assert match is not None, "no :root block"
    return match.group(1)


def _outsideRoot(css: str) -> str:
    """The stylesheet minus comments, the :root mirror and the @font-face.

    The @font-face is excluded because its src is ~3,300 characters of base64
    that check (c) owns; its descriptors are not colours or sizes.
    """
    text = _stripComments(css)
    text = re.sub(r":root\s*\{.*?\}", "", text, count=1, flags=re.DOTALL)
    return re.sub(r"@font-face\s*\{.*?\}", "", text, flags=re.DOTALL)


def _mirrorDrift(stylesCss: str, tokensCss: str) -> list[str]:
    """Check (a): every :root token the SSOT also declares, at a different value.

    Returned rather than asserted so the negative case can prove this check
    actually goes red on a drifted SSOT.
    """
    ssot = _declarations(_rootBlock(tokensCss))
    mirror = _declarations(_rootBlock(stylesCss))
    return [
        f"--{name}: styles.css {value!r} != tokens.css {ssot[name]!r}"
        for name, value in mirror.items()
        if name in ssot and value.upper() != ssot[name].upper()
    ]


def _inheritedFontFamily(surface: rh.Surface, path: list) -> str | None:
    """font-family is inherited: the nearest element up the chain that declares it."""
    for depth in range(len(path), 0, -1):
        found = surface.winningDeclaration(path[:depth], "font-family")
        if found is not None and found[0] != "inherit":
            return found[0]
    return None


def _michromaStrings(page: str) -> list[str]:
    """Every text node the page sets in the brand face, AS RENDERED (upper case).

    Resolved through the stylesheet rather than a list of ids, so a future rule
    that binds --font-display to another element is guarded the day it lands.
    """
    surface = rh.splashSurface(rh.parseMarkup(os.path.join(_SPLASH, page)))
    strings = []
    for path in surface.paths():
        family = _inheritedFontFamily(surface, path)
        if family is None or "--font-display" not in family:
            continue
        for child in path[-1]["children"]:
            if "text" in child:
                strings.append(child["text"].strip().upper())
    return strings


# ---------------------------------------------------------------------------
# The motion tokens live in the SSOT (Atlas C-Atlas-3).
# ---------------------------------------------------------------------------


def test_tokensCss_declaresEachMotionTokenOnce():
    """The six motion tokens (promoted from the retired splash.svg) are declared
    exactly once in the tokens.css :root -- their only copy since US-870-c.
    The splash mirror's agreement with them is the (a) MIRROR test's job."""
    tokensRoot = _rootBlock(_read(_TOKENS))
    for name in _MOTION_TOKENS:
        assert len(re.findall(rf"^\s*--{name}:", tokensRoot, re.M)) == 1, name


# ---------------------------------------------------------------------------
# (a) MIRROR -- the splash :root carries the SSOT's values.
# ---------------------------------------------------------------------------


def test_splashRoot_declaresEveryTokenItRendersAgainst():
    """The mirror is complete: a token the splash binds but does not declare
    resolves to nothing, and the element paints unstyled."""
    declared = set(_declarations(_rootBlock(_read(_STYLES))))
    assert set(_MIRRORED) <= declared, set(_MIRRORED) - declared


def test_splashRoot_valuesEqualTokensCss_a():
    """Check (a): no mirrored token has drifted from tokens.css."""
    assert _mirrorDrift(_read(_STYLES), _read(_TOKENS)) == []


def test_splashRoot_mirrorsOnlySsotTokens_andDropsTheUnusedSoftAmber():
    """Every token in the mirror is one tokens.css declares (a splash-only name
    would be a fork), and the never-used --amber-soft is gone."""
    mirror = set(_declarations(_rootBlock(_read(_STYLES))))
    ssot = set(_declarations(_rootBlock(_read(_TOKENS))))
    assert mirror <= ssot, mirror - ssot
    assert "amber-soft" not in mirror


def test_aTokenChangedOnlyInTokensCss_turnsCheckARed():
    """Negative case: change --bg in a scratch tokens.css and not in styles.css
    -> check (a) reports it. A mirror check that cannot fail pins nothing."""
    tokens = _read(_TOKENS)
    drifted = re.sub(r"(^\s*--bg:\s*)[^;]+;", r"\g<1>#123456;", tokens, count=1, flags=re.M)
    assert drifted != tokens, "--bg is no longer declared in tokens.css"
    drift = _mirrorDrift(_read(_STYLES), drifted)
    assert len(drift) == 1 and drift[0].startswith("--bg:"), drift


# ---------------------------------------------------------------------------
# (b) LITERAL -- outside the mirror, every value is a token.
# ---------------------------------------------------------------------------


def test_noColourLiteralOutsideTheRootMirror_b():
    """The stale #888888 / #666666 / #000 were exactly this: literals a token
    change never reached."""
    body = _outsideRoot(_read(_STYLES))
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
    assert not re.search(r"\b(?:rgba?|hsla?)\s*\(", body, re.I)
    for literal in ("#888888", "#666666", "#000"):
        assert literal not in _read(_STYLES), literal


def test_everyColourSizeAndFamilyIsAVar_b():
    """Check (b): each colour, font-size and font-family declaration outside
    :root is exactly one var(--...). Layout offsets may stay px (AC 12)."""
    body = _outsideRoot(_read(_STYLES))
    found = re.findall(r"(?:^|[;{\s])(" + "|".join(_TOKEN_ONLY_PROPS) + r")\s*:\s*([^;}]+)", body)
    assert found, "no colour / size / family declarations found -- the parse is broken"
    for prop, value in found:
        assert re.fullmatch(r"var\(--[a-zA-Z0-9-]+\)", value.strip()), f"{prop}: {value.strip()}"


def test_borderColoursAreTokensToo_b():
    """A border may keep its px width, but its colour is a token."""
    body = _outsideRoot(_read(_STYLES))
    for value in re.findall(r"(?:^|[;{\s])border\s*:\s*([^;}]+)", body):
        for part in value.split():
            assert re.fullmatch(r"\d+px|0|solid|none|var\(--[a-zA-Z0-9-]+\)", part), value


def test_everyVarTheSheetUsesIsDeclaredInItsMirror():
    """dashboard.html's lesson, for the splash: the page links ONLY styles.css,
    so a var() the mirror does not declare resolves to nothing on the panel."""
    css = _stripComments(_read(_STYLES))
    used = set(re.findall(r"var\(--([a-zA-Z0-9-]+)\)", css))
    declared = set(_declarations(_rootBlock(css)))
    assert used <= declared, used - declared


# ---------------------------------------------------------------------------
# (c) FACE -- Michroma, the dashboard's inline payload.
# ---------------------------------------------------------------------------


def test_theSplashCarriesOneFace_byteEqualToTokensCss_c():
    """Check (c): ONE @font-face, the same base64 as the SSOT's, weight 400,
    font-display: swap -- the face the dashboard already ships."""
    blocks = _fontFaceBlocks(_read(_STYLES))
    assert len(blocks) == 1, f"expected exactly one @font-face, got {len(blocks)}"
    block = blocks[0]
    assert "url(data:font/woff2;base64," in block
    assert _payload(block) == _payload(_fontFaceBlocks(_read(_TOKENS))[0])
    assert _descriptor(block, "font-family").strip("\"' ") == "Michroma"
    assert _descriptor(block, "font-weight") == "400"
    assert _descriptor(block, "font-display") == "swap"


def test_theWordmarkIsTheBrandFace_andEveryOtherTextIsMono():
    """Each _BRAND_FACE_SELECTORS rule binds var(--font-display) at the subset's
    one weight with synthesis off; every other text rule binds var(--font-mono).

    RULED GUARD CHANGE (Atlas 2026-10-25, US-869-g R1): was `#wordmark` alone."""
    css = _outsideRoot(_read(_STYLES))
    rules = re.findall(r"([^{}]+)\{([^{}]*font-family[^{}]*)\}", css)
    assert rules, "no rule sets a font-family"
    for selector, body in rules:
        family = re.search(r"font-family:\s*([^;]+)", body).group(1).strip()
        if selector.strip() in _BRAND_FACE_SELECTORS:
            assert family == "var(--font-display)", selector.strip()
            assert re.search(r"font-weight:\s*400\s*;", body), f"{selector.strip()} must ask for 400"
            assert re.search(r"font-synthesis:\s*none\s*;", body), selector.strip()
        else:
            assert family == "var(--font-mono)", selector.strip()
    present = [selector.strip() for selector, _ in rules]
    for member in _BRAND_FACE_SELECTORS:
        assert member in present, f"{member} no longer binds a font-family"


# ---------------------------------------------------------------------------
# (d) SUBSET -- the splash copy stays inside the glyphs that were cut.
# ---------------------------------------------------------------------------


def test_everyMichromaStringInTheSplashPagesIsInsideTheSubset_d():
    """Check (d): a glyph outside the 38-glyph cut falls back for THAT GLYPH
    ONLY, splitting the wordmark across two faces."""
    for page in _PAGES:
        strings = _michromaStrings(page)
        assert "ECLIPSE OBD-II" in strings, f"{page}: the wordmark is not a guarded string"
        for text in strings:
            outside = sorted(set(text) - _SUBSET)
            assert not outside, f"{page}: {text!r} needs glyphs outside the subset: {outside}"


# ---------------------------------------------------------------------------
# (e) LICENCE -- SIL OFL 1.1 travels with the font.
# ---------------------------------------------------------------------------


def test_theSplashKitCarriesIrisOflBytewise_e():
    """Check (e): the face now travels inside styles.css, so the kit carries
    the licence -- the same file as the dashboard kit's copy."""
    with open(_SPLASH_OFL, "rb") as fh, open(_KIT_OFL, "rb") as kit:
        assert fh.read() == kit.read()
