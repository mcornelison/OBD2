################################################################################
# File Name: test_dashboard_brand_font_payload.py
# Purpose/Description: US-510 fast-follow (closes BL-027) -- the brand-face WOFF2
#   payload drop into the --font-display seam US-510 built.
#
#   US-510 shipped the SEAM (--font-display in the SSOT, bound to exactly the
#   wordmark + card titles) and deliberately left the PAYLOAD open: the locked
#   face was Bahnschrift, which is Microsoft-proprietary, absent from Pi OS and
#   NOT redistributable -- so naming it never put it on the panel. Iris has since
#   cut an OFL-licensed Oswald subset, so the face can finally be embedded.
#
#   What this suite pins, and why each one is a real failure mode:
#     PAYLOAD   The base64 must DECODE to Iris's delivered woff2 byte-for-byte.
#               A font blob is the one artifact in this repo nobody can
#               eyeball -- a truncated paste renders generic sans and looks
#               exactly like a paste that worked.
#     MIRROR    dashboard.html links ONLY dashboard.css, so the SSOT copy alone
#               would leave the kiosk on a fallback face while every token test
#               stayed green. The face ships TWICE, and the two copies must be
#               byte-identical, like every other token in this kit.
#     WEIGHT    The subset carries ONE weight (Oswald was 600; Michroma, since
#               US-887-b, is 400). Any brand rule asking for more gets a
#               SYNTHESISED bold -- a smear that reads as a rendering fault
#               rather than a style choice -- so face users also set
#               font-synthesis: none.
#     SUBSET    A-Z / 0-9 / space / hyphen. A brand string reaching outside that
#               falls back PER GLYPH, so one stray "·" splits a title across two
#               faces mid-word.
#     CDN       Extends US-510's no-CDN pin to the src descriptor itself: the
#               kiosk is offline in the car, so a fetched face fails only there.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- BL-027 Oswald payload drop.
# 2026-10-15    | Ralph (Rex)  | US-887-b: Michroma 400 replaces Oswald 600 (V0.30
#               |              | OEM style). Pins the md5 of the copied asset, the
#               |              | 2,896 B byte ceiling, font-synthesis: none, both
#               |              | licence copies, and derives the subset from
#               |              | Iris's michroma-advances.json.
# ================================================================================
################################################################################

"""US-887-b tests: the inlined Michroma brand face (payload, mirror, weight, subset)."""

import base64
import hashlib
import json
import os
import re

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, "..", "..")
_UI = os.path.join(_ROOT, "src", "pi", "ui")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")
_HTML = os.path.join(_DIST, "dashboard.html")
_KIT_OFL = os.path.join(_DIST, "OFL.txt")
_FONTS = os.path.join(_UI, "assets", "fonts")
_ASSET_OFL = os.path.join(_FONTS, "OFL.txt")
_DEPLOY_PI = os.path.join(_ROOT, "deploy", "deploy-pi.sh")

# The source-of-record brand face. Iris cut it on a bench whose surface is
# specs/** (specs/assets/fonts/michroma/PROVENANCE.md), and US-887-b COPIED it
# into the product tree. The .woff2 is the ORIGINAL; the CSS carries its base64.
# Keeping the binary in the repo is what makes the payload verifiable rather
# than an opaque string nobody can check.
_SOURCE_WOFF2 = os.path.join(_FONTS, "michroma-brand.woff2")
_KIT_DIR = os.path.join(_ROOT, "specs", "assets", "fonts", "michroma")

# PROVENANCE.md: "2,464 B, md5 b495a16b2b5cf974f15e52d62e914d14", reproducible
# under a fixed SOURCE_DATE_EPOCH. The md5 is the check that the copy out of
# Iris's kit is the file she measured, not a re-cut or a truncated paste.
_SOURCE_MD5 = "b495a16b2b5cf974f15e52d62e914d14"
# Atlas's rule (spec s4.3 / s6): total embedded-font bytes no larger than the
# Oswald embed it replaces (oswald-brand.woff2, 2,896 B).
_EMBED_BYTE_CEILING = 2896

# The glyph set Iris cut, read from her per-glyph advance table rather than
# retyped here: every key of michroma-advances.json is a glyph in the subset
# (38: A-Z / 0-9 / space / hyphen). A brand string outside it falls back.
with open(os.path.join(_KIT_DIR, "michroma-advances.json"), encoding="utf-8") as _fh:
    _SUBSET = set(json.load(_fh)["advanceEm"])
# Michroma has ONE weight (PROVENANCE.md: "400 only ... never synthesise bold").
_SUBSET_WEIGHT = "400"
_FAMILY = "Michroma"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _stripComments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _fontFaceBlocks(css: str) -> list:
    """The body of every @font-face rule, comments stripped.

    Comments FIRST -- this kit documents the literals and faces it removed, so a
    grep for a face name fires on the note explaining the change (US-507/509/511,
    the greps-a-defect's-name family, fifth occurrence).
    """
    return re.findall(r"@font-face\s*\{(.*?)\}", _stripComments(css), flags=re.DOTALL)


def _descriptor(block: str, name: str) -> str:
    """A SHORT descriptor's value (font-family / -weight / -style / -display)."""
    match = re.search(rf"(?:^|;)\s*{re.escape(name)}\s*:\s*([^;]+)", block, re.DOTALL)
    assert match is not None, f"@font-face carries no {name} descriptor"
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _srcDescriptor(block: str) -> str:
    """`src` needs its OWN reader: a data: URI CONTAINS a semicolon
    (`data:font/woff2;base64,`), so the generic `[^;]+` value grab above stops
    dead at `url(data:font/woff2` and every assertion about the src would then
    be made against a truncated string. Read it to end-of-line instead -- the
    src is one (very long) line by construction.
    """
    match = re.search(r"^\s*src\s*:\s*(.+?);?\s*$", block, re.MULTILINE)
    assert match is not None, "@font-face carries no src descriptor"
    return match.group(1).strip()


def _payload(block: str) -> str:
    """The base64 out of the src data: URI."""
    match = re.search(r"base64,\s*([A-Za-z0-9+/=]+)\s*\)", block)
    assert match is not None, "@font-face src is not an inlined base64 data: URI"
    return match.group(1)


def _tokenValue(css: str, name: str) -> str:
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([^;]+);", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared"
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _brandStrings() -> list:
    """Every string the brand face actually renders, AS RENDERED.

    Brand strings are uppercase, so the glyphs REQUESTED are the uppercase ones
    -- which is the whole reason an uppercase-only subset is a legitimate cut
    here. Compare what the panel asks for, not what the DOM holds.

    MOVED PIN (US-887-c): the card titles are gone; the brand face now paints
    the top-bar PAGE NAMES, which each card carries as `data-page-name`.
    """
    titles = re.findall(r'data-page-name="([^"]+)"', _read(_HTML))
    wordmark = re.findall(r'wordmark:\s*"([^"]+)"', _read(_JS))
    assert titles, "no page names found -- the attribute moved"
    assert wordmark, "the wordmark literal moved out of carousel.js"
    return [text.strip().upper() for text in titles + wordmark]


# ---------------------------------------------------------------------------
# PAYLOAD -- the blob is real, and it is the blob Iris shipped.
# ---------------------------------------------------------------------------


def test_theBrandFaceIsEmbeddedAsAnInlinedDataUri():
    """CSP-safe + offline-safe. A `url(...)` pointing anywhere else -- a CDN, a
    sibling file, an absolute path -- fails only IN THE CAR, where nobody is
    watching a devtools network tab."""
    for path in (_TOKENS, _CSS):
        blocks = _fontFaceBlocks(_read(path))
        assert len(blocks) == 1, f"{path}: expected exactly one @font-face, got {len(blocks)}"
        src = _srcDescriptor(blocks[0])
        assert src.startswith("url(data:font/woff2;base64,"), src[:60]
        assert 'format("woff2")' in src


def test_theEmbeddedPayloadDecodesToIrisDeliveredWoff2():
    """THE anti-fabrication pin. A font blob cannot be eyeballed, so a truncated
    or hand-edited paste is invisible in review and renders as a plain fallback
    -- i.e. it looks exactly like the bug this drop exists to fix. Decode it and
    compare against the delivered binary."""
    delivered = open(_SOURCE_WOFF2, "rb").read()
    assert delivered[:4] == b"wOF2", "the source asset is not a WOFF2"
    for path in (_TOKENS, _CSS):
        decoded = base64.b64decode(_payload(_fontFaceBlocks(_read(path))[0]))
        assert decoded == delivered, f"{path}: embedded payload != michroma-brand.woff2"


def test_theCopiedAssetIsTheFileIrisMeasured():
    """The md5 Iris published with the cut. A copy that drifted from her kit --
    a re-cut without the fixed epoch, a re-encode -- would still decode and
    still render, so only the hash shows it is not the file she measured."""
    delivered = open(_SOURCE_WOFF2, "rb").read()
    assert hashlib.md5(delivered).hexdigest() == _SOURCE_MD5


def test_totalEmbeddedFontBytesStayUnderTheOswaldCeiling():
    """Atlas's byte rule: the new face may not make the sheet heavier than the
    Oswald embed it replaces. Michroma alone fits; Michroma plus Oswald (5,364 B,
    Iris measured) does not, so this is also the check that Oswald LEFT."""
    for path in (_TOKENS, _CSS):
        total = sum(
            len(base64.b64decode(_payload(block)))
            for block in _fontFaceBlocks(_read(path))
        )
        assert total <= _EMBED_BYTE_CEILING, f"{path}: {total} B of embedded fonts"


def test_theRetiredFaceIsGoneFromBothSheetsAndTheAssets():
    """Oswald retires with this swap (spec s4.3): no sheet names it, even in a
    stack tail, and its binary is not left behind as an unreferenced asset."""
    for path in (_TOKENS, _CSS):
        assert "oswald" not in _stripComments(_read(path)).lower(), path
    assert not os.path.exists(os.path.join(_FONTS, "oswald-brand.woff2"))


def test_theKitMirrorCarriesTheExactSsotPayload():
    """dashboard.html links ONLY dashboard.css, so the dist sheet is a RUNTIME
    mirror, not a redundant copy -- the face must be declared twice and the two
    copies must agree, exactly like every colour token in this kit."""
    assert "tokens.css" not in _read(_HTML), (
        "if the kit ever links the SSOT directly, the mirror rule changes"
    )
    assert _payload(_fontFaceBlocks(_read(_TOKENS))[0]) == _payload(
        _fontFaceBlocks(_read(_CSS))[0]
    )


def test_theKiosksOwnStylesheetCarriesTheFace_notJustTheToken():
    """The failure this drop is most likely to ship: land the @font-face in the
    SSOT only. Every token test stays green, the stack still names Oswald, and
    the Pi renders DejaVu Sans -- the CIO's original "it looks generic"
    complaint, now with a passing suite on top of it."""
    assert _fontFaceBlocks(_read(_CSS)), (
        "dashboard.css is the ONLY sheet dashboard.html links; without the "
        "@font-face here the face never reaches the panel"
    )


# ---------------------------------------------------------------------------
# STACK + WEIGHT -- what the browser is asked for matches what the subset has.
# ---------------------------------------------------------------------------


def test_theEmbeddedFamilyLeadsTheDisplayStack():
    """An embedded face the stack never names is dead weight; a stack whose lead
    is not the embedded face resolves to whatever the HOST happens to have --
    which is why a Windows dev box and the Pi would disagree."""
    for path in (_TOKENS, _CSS):
        text = _read(path)
        family = _descriptor(_fontFaceBlocks(text)[0], "font-family").strip('"\' ')
        assert family == _FAMILY
        stack = _tokenValue(text, "font-display")
        assert stack.split(",")[0].strip().strip('"\'') == _FAMILY, stack


def test_theFaceDeclaresTheWeightTheSubsetActuallyHas():
    """Michroma has weight 400 only. Declaring the @font-face as anything else
    misdescribes the file, and the browser then picks or SYNTHESISES against
    the wrong number."""
    for path in (_TOKENS, _CSS):
        block = _fontFaceBlocks(_read(path))[0]
        assert _descriptor(block, "font-weight") == _SUBSET_WEIGHT


def test_everyBrandMomentAsksForTheWeightTheSubsetActuallyHas():
    """Marcus's step 3. The wordmark shipped at 700 against a 600-only Oswald
    subset, so the ONE place the product says its own name would have rendered
    synth-bolded. Michroma is 400-only, so every bound rule asks for 400.
    Asserted over the SET of bound rules, so a future brand surface cannot
    reintroduce a heavier weight quietly."""
    css = _stripComments(_read(_CSS))
    bound = re.findall(r"([^{}]+)\{([^{}]*var\(--font-display\)[^{}]*)\}", css)
    assert bound, "no rule binds --font-display any more"
    for selector, body in bound:
        weight = re.search(r"font-weight:\s*([^;]+)", body)
        assert weight is not None, f"{selector.strip()} binds the face but sets no weight"
        assert weight.group(1).strip() == _SUBSET_WEIGHT, (
            f"{selector.strip()} asks for {weight.group(1).strip()} from a "
            f"{_SUBSET_WEIGHT}-only subset -> synthesised bold"
        )


def test_everyBrandMomentForbidsSynthesis():
    """Belt to the weight check's braces: `font-synthesis: none` on every rule
    that uses the face, so even an inherited or future heavier weight renders
    the real 400 outlines instead of a smeared faux bold (PROVENANCE.md)."""
    css = _stripComments(_read(_CSS))
    bound = re.findall(r"([^{}]+)\{([^{}]*var\(--font-display\)[^{}]*)\}", css)
    assert bound, "no rule binds --font-display any more"
    for selector, body in bound:
        synthesis = re.search(r"font-synthesis:\s*([^;]+)", body)
        assert synthesis is not None, f"{selector.strip()} binds the face but allows synthesis"
        assert synthesis.group(1).strip() == "none", selector.strip()


def test_theFaceSwapsRatherThanBlockingTheFirstPaint():
    """A data: URI is available immediately so this is belt-and-braces -- but
    `block` on a splash-to-dashboard handoff is an invisible-text window on a
    surface whose whole job is being readable at a glance."""
    for path in (_TOKENS, _CSS):
        assert _descriptor(_fontFaceBlocks(_read(path))[0], "font-display") == "swap"


# ---------------------------------------------------------------------------
# SUBSET -- the copy stays inside the glyphs that were actually cut.
# ---------------------------------------------------------------------------


def test_everyBrandStringStaysInsideTheSubset():
    """A 2,464-byte subset is only safe while the brand copy stays inside it.
    Miss by one glyph and the browser falls back FOR THAT GLYPH ONLY, so a
    single "·" splits a title across two faces mid-word -- which reads as a
    corrupted render, not a missing character."""
    for text in _brandStrings():
        outside = sorted(set(text) - _SUBSET)
        assert not outside, f"{text!r} needs glyphs outside the cut subset: {outside}"


def test_theWordmarkIsStillTheLockedString():
    """The subset assertion above is only meaningful while it guards the REAL
    wordmark -- if the locked string drifted, this suite would be cheerfully
    validating the drift's glyph coverage."""
    assert "ECLIPSE OBD-II" in _brandStrings()


# ---------------------------------------------------------------------------
# LICENSE + CDN
# ---------------------------------------------------------------------------


def test_theOflLicenseShipsInsideTheKit():
    """SIL OFL 1.1 requires the licence to travel with the font, and the font
    now travels INSIDE dashboard.css -- so the kit that carries the sheet must
    carry the licence. BOTH copies (the deployed kit's and the source-of-record
    beside the binary) must be MICHROMA's: Oswald's licence left with Oswald,
    and a correct-looking OFL naming the wrong font is no licence for this one.
    """
    kitText = _read(os.path.join(_KIT_DIR, "OFL-michroma.txt"))
    for path in (_KIT_OFL, _ASSET_OFL):
        assert os.path.exists(path), f"{path} is missing"
        text = _read(path)
        assert "SIL OPEN FONT LICENSE" in text.upper()
        assert "Version 1.1" in text
        assert "Michroma Project Authors" in text, path
        assert "Oswald" not in text, path
        assert text == kitText, f"{path} is not Iris's OFL-michroma.txt"


def test_theLicenceIsVouchedForDeploymentNotSilentlyPruned():
    """deploy-pi.sh installs a VOUCHED file list into /opt/dashboard and PRUNES
    everything else. An unvouched OFL.txt sits in the repo looking compliant
    while the deployed artifact ships the font without its licence.

    ANCHOR the search on the dashboard kit's OWN assetSrc: deploy-pi.sh
    declares more than one `local assets=` list (the F-103 splash has one too),
    so an unanchored grab reads whichever appears FIRST and would have happily
    reported the splash list's contents as the dashboard's.
    """
    script = _read(_DEPLOY_PI)
    start = script.index('assetSrc="$REPO_ROOT/src/pi/ui/dashboard"')
    match = re.search(r'local assets="([^"]+)"', script[start:])
    assert match is not None, "the dashboard asset list moved"
    assert "OFL.txt" in match.group(1).split(), match.group(1)


def test_bothSheetsCreditTheFaceAndItsLicence():
    """The @font-face is ~3,300 characters of opaque base64; without a credit
    comment the next reader has no way to learn what face it is or that it
    carries obligations."""
    for path in (_TOKENS, _CSS):
        text = _read(path)
        comments = " ".join(re.findall(r"/\*.*?\*/", text, flags=re.DOTALL))
        assert "Michroma" in comments, path
        assert "OFL" in comments, path


def test_noFontIsFetchedFromAnywhere():
    """US-510's no-CDN pin, extended to the src descriptor now that there IS a
    src. The most plausible future 'fix' when someone thinks the face is broken
    is a Google Fonts @import -- which works on every machine except the one in
    the car."""
    for path in (_TOKENS, _CSS, _HTML):
        text = _read(path).lower()
        assert "@import" not in text, path
        assert "fonts.googleapis" not in text, path
        assert "fonts.gstatic" not in text, path
        assert not re.search(r"url\(\s*[\"']?https?://", text), path
        assert not re.search(r"url\(\s*[\"']?[^)\"']*\.woff2?[\"']?\s*\)", text), (
            f"{path}: the face must be inlined, never referenced as a file"
        )
