################################################################################
# File Name: test_dashboard_fidelity_pass.py
# Purpose/Description: US-510 (F-124) tests -- the fidelity pass. Three groups,
#   one per acceptance half:
#     A-1 COPY. The built surfaces PARAPHRASED Iris's locked idle strings
#         ("ECLIPSE" for "ECLIPSE OBD-II"; a status line where a navigation hint
#         belongs). Nothing pinned them, which is precisely why they drifted --
#         so the restore ships with the pins that make the drift impossible to
#         repeat.
#         AMENDED BY US-542 (F-127, Atlas design-gate): the parked face is
#         RETIRED, so the LOCKED FOOTER -- a parked-screen navigation hint -- is
#         retired with the screen it taught, and is now pinned as an ABSENCE.
#         The wordmark stays (branding, not status) and the surviving
#         motion-fault footer keeps stating its fault. A copy loss, deliberate
#         and named; the setup affordance it described is untouched.
#     A-2 TOKENIZATION (TD-065/TD-067). Every colour literal Iris enumerated is
#         repointed at a token. Two are Atlas Rule-10 rulings (2026-07-31):
#         --bg/--surface are PROMOTED into the SSOT at their CURRENT values (a
#         diff that moves a rendered pixel FAILS the gate), and --destructive /
#         --destructive-border get real values that MUST stay distinct from
#         --critical-red -- a destructive ACTION must never read as an alarm
#         STATE. That distinctness is the load-bearing assertion of this group.
#     A-3 BRAND FACE. --font-display joins --font-mono in the SSOT and binds to
#         the brand moments ONLY (wordmark + card titles); every data/value
#         surface stays ui-monospace, which Iris explicitly did not change.
#   KNOWN-OPEN, stated not hidden: the inlined @font-face woff2 payload is NOT
#   in this story -- the asset does not exist in the repo and the face is a CIO
#   pick (Iris supplies the base64). See offices/pm/blockers/BL-027. What IS
#   pinned here is the half that must hold either way: no font is ever fetched
#   from a CDN, because the kiosk is offline and CSP-fenced.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Ralph (Rex)  | Initial -- US-510 fidelity pass (copy/tokens/font).
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the idle wordmark/footer cases
#                               retire with the idle face; the font-display
#                               set swaps .idle-wordmark for #motion-card
#                               .motion-label.
# 2026-10-20    | Ralph (Rex)  | US-898-b1 -- MOVED PIN: the ALERTS card's 'n ACTIVE'
#                               count and its tier chips join the font-display
#                               set (Warnings spec s3).
# 2026-10-20    | Ralph (Rex)  | US-898-b2 -- MOVED PIN: the empty-state words
#                               (NO WARNINGS / NOT CHECKED YET) join it.
# 2026-10-20    | Ralph (Rex)  | US-899-a2 -- MOVED PIN: the deleted takeover floods'
#                               deep-edge token pins retired.
# 2026-10-26    | Ralph (Rex)  | US-891-c -- MOVED PIN: the O2 labels and live chip
#                               join the font-display set (O2 spec s3).
# ================================================================================
################################################################################

"""US-510 tests for the dashboard fidelity pass (locked copy, tokens, brand face)."""

import os
import re
import shutil

import pytest

from tests.ui.render_harness import parseCss

_HERE = os.path.dirname(__file__)
_UI = os.path.join(_HERE, "..", "..", "src", "pi", "ui")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")
_HTML = os.path.join(_DIST, "dashboard.html")

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- carousel.js pure-logic tests need node"
)

_LOCKED_FOOTER = "swipe for details · hold or ⋮ for setup"
# The pre-drift line the build shipped instead. Named so its removal is pinned.
_DRIFTED_FOOTER = "monitoring resumes on engine start"

# Atlas Rule-10 ruling 2026-07-31 (design-gate PASS + rulings). Values, not
# Rex-derived: the destructive pair is Atlas's definition. --bg/--surface were
# promoted at their shipped #000000/#111111 and US-887-a moved them to the V0.30
# OEM values (specs/v030-frame-and-style-design.md s4.2, Atlas Rule-10
# 2026-10-13). --bg is written lower-case so the re-fork scan below, which
# lower-cases each rule body, still matches it.
_ATLAS_BG = "#0a0a0a"
_ATLAS_SURFACE = "#141414"
_ATLAS_DESTRUCTIVE = "#C62828"
_ATLAS_DESTRUCTIVE_BORDER = "#7F1D1D"

# The A-2 literals that must no longer appear in any surface rule. Every one is
# a RELOCATION: the value is unchanged, it just moves behind a name.
_SWEPT_LITERALS = ("#2a2f37", "#7a5b00", "#12603a", "#062617")

# The ONE deferral, enumerated so the debt cannot grow quietly (the
# _DEFERRED_DESTRUCTIVE pattern from test_dashboard_alarm_tier_sweep.py).
# `#fff`/`#000` on a tiered chip/ribbon/takeover are CONTRAST PAIRS chosen
# against that tier's fill, not palette entries -- naming them would mean
# inventing --on-amber/--on-critical tokens, which is a design decision in
# Iris's lane and a Rule-10 token addition in Atlas's. Neither is US-510's.
# Tracked as TD-071.
_ALLOWED_CONTRAST_HEX = frozenset({"#fff", "#000"})


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _tokenValue(css: str, name: str) -> str:
    """The declared value of a custom property, normalised + uppercased.

    Line-leading match only, so a token NAMED in a comment block is never read
    as a declaration (the SSOT file is mostly prose).

    Internal whitespace is COLLAPSED: --font-display is long enough to wrap, and
    the two files wrap it at different indents. Whitespace runs are not semantic
    in a CSS value, so comparing them raw would fail the mirror test on the
    prettiness of the indentation rather than on a real drift -- a test that
    cries wolf gets its assertion loosened later by someone in a hurry.
    """
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([^;]+);", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared"
    return re.sub(r"\s+", " ", match.group(1)).strip().upper()


def _surfaceRules() -> list:
    """Every dashboard.css rule that is NOT a token-definition block.

    Comments are stripped by parseCss before parsing -- US-507's lesson, third
    occurrence: this sheet DOCUMENTS the literals it removed, so a grep that
    hunts a defect's own name fires on the note explaining the fix.
    """
    return [
        (rule.selector, rule.declarations)
        for rule in parseCss(_read(_CSS))
        if not rule.selector.startswith(":root")
    ]


def _stripJsComments(js: str) -> str:
    """Drop // and /* */ comments, respecting string literals.

    Same guard as US-507: carousel.js carries "http://www.w3.org/2000/svg", so a
    naive line-comment strip eats the rest of that line -- and over-stripping
    makes an ABSENCE assertion pass vacuously, which is the dangerous direction.
    """
    out = []
    i, n = 0, len(js)
    quote = None
    while i < n:
        ch = js[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(js[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "/":
            while i < n and js[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] == "*":
            end = js.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# The comment stripper is itself pinned. An over-eager stripper would silently
# turn every absence assertion below into a pass-for-the-wrong-reason.
# ---------------------------------------------------------------------------


def test_stripJsComments_keepsCodeAndStringsButDropsProse():
    src = 'var a = "http://x//y"; // gone\nvar b = 1; /* also gone */ var c = 2;'
    out = _stripJsComments(src)
    assert '"http://x//y"' in out
    assert "var b = 1;" in out and "var c = 2;" in out
    assert "gone" not in out


def test_stripJsComments_survivesTheShippedSvgNamespaceString():
    """carousel.js ships a string containing `//`; it must not be truncated."""
    assert "http://www.w3.org/2000/svg" in _stripJsComments(_read(_JS))


# ---------------------------------------------------------------------------
# A-1 -- the locked idle copy, restored and pinned.
# ---------------------------------------------------------------------------


@_needsNode
def test_theLockedNavigationHintRetiredWithTheScreenItTaught():
    """US-542 (Atlas design-gate) retires the parked face, and the locked footer
    was a PARKED-screen navigation hint. It is not relocated: the hint taught
    the two ways into setup on a screen that no longer exists, and re-hosting it
    on the motion-fault fallback would print a tutorial over an instrument
    fault. Pinned as an ABSENCE from anything executable, the same shape as
    _DRIFTED_FOOTER below -- otherwise it comes back as dead copy nobody reads.

    The AFFORDANCE it named is untouched, which is why the loss is a copy loss
    and not a capability loss: the ⋮ is still in the top bar (US-490 reveals it
    parked) and the 5s long-press still opens the menu from anywhere."""
    assert _LOCKED_FOOTER not in _stripJsComments(_read(_JS))
    assert "⋮" in _read(_HTML), "the setup affordance itself must still be there"


def test_theDriftedStatusLineIsGoneFromTheSource():
    """The pre-drift copy must not survive anywhere executable. Comments are
    stripped first: the renderer's own note NAMES this string while explaining
    why the footer became a view field, so an un-stripped grep would fail on
    the documentation of the fix rather than on the defect."""
    assert _DRIFTED_FOOTER not in _stripJsComments(_read(_JS))


# ---------------------------------------------------------------------------
# A-2 -- tokenization (TD-065) + the Atlas-ruled token values.
# ---------------------------------------------------------------------------


def test_bgAndSurface_arePromotedIntoTheSsot():
    """Atlas RULING 2 -- tokens.css said these were "not yet tokenized"; the
    SSOT now owns them."""
    tokens = _read(_TOKENS)
    assert _tokenValue(tokens, "bg") == _ATLAS_BG.upper()
    assert _tokenValue(tokens, "surface") == _ATLAS_SURFACE.upper()


def test_bgAndSurfacePromotion_isZeroVisualChange():
    """Atlas made this the DoD gate in so many words: the promoted values ARE
    the ruled ones. The dist mirror and the SSOT must agree, and both must equal
    the frame spec s4.2 value (US-887-a)."""
    css, tokens = _read(_CSS), _read(_TOKENS)
    for name, expected in (("bg", _ATLAS_BG), ("surface", _ATLAS_SURFACE)):
        assert _tokenValue(css, name) == _tokenValue(tokens, name), name
        assert _tokenValue(css, name) == expected.upper(), name


def test_theBackgroundLiteralIsNeverReForkedIntoASurface():
    """The cheap way to "pass" a tokenization sweep is to inline the value again
    somewhere else. The background is --bg's job; its literal must appear only in
    the two :root blocks. (The SHORT #000 is the contrast-pair deferral below --
    a different fact, and deliberately not conflated with the background.)"""
    for selector, body in _surfaceRules():
        assert _ATLAS_BG not in body.lower(), f"{_ATLAS_BG} re-forked onto {selector}"


def test_neutralChipBackground_isRepointedAtTheExistingSsotToken():
    """--neutral-chip-bg has existed in tokens.css since the DTC viewer landed;
    the dashboard simply was not pointing at it (Iris A-2)."""
    css = _read(_CSS)
    assert _tokenValue(css, "neutral-chip-bg") == _tokenValue(
        _read(_TOKENS), "neutral-chip-bg"
    )
    for level in ("na", "unknown"):
        assert (
            f'.dtc-chip[data-level="{level}"]' in css
        ), f"the {level} chip rule moved -- re-point this guard"
    naRule = [b for s, b in _surfaceRules() if s == '.dtc-chip[data-level="na"]']
    assert naRule and "var(--neutral-chip-bg)" in naRule[0]


# MOVED PIN (US-899-a2): the watch/minor/unknown takeover floods are deleted,
# and the three deep gradient-edge tokens (--amber-deep / --green-deep /
# --green-deepest) existed only to paint them, so they went too. Their two pins
# (the floods bind the tokens; the tokens hold US-510's values) are retired.


def test_destructiveTokens_carryTheAtlasRuledValuesInBothFiles():
    """Atlas RULING 2 gave the two destructive reds real values, which closes
    the deferral test_dashboard_alarm_tier_sweep.py fenced off."""
    css, tokens = _read(_CSS), _read(_TOKENS)
    for name, expected in (
        ("destructive", _ATLAS_DESTRUCTIVE),
        ("destructive-border", _ATLAS_DESTRUCTIVE_BORDER),
    ):
        assert _tokenValue(tokens, name) == expected.upper(), name
        assert _tokenValue(css, name) == _tokenValue(tokens, name), name


def test_destructiveIsDistinctFromCriticalRed():
    """THE load-bearing assertion of A-2, in Atlas's own words: a destructive
    ACTION (a button the operator presses) must not read as an alarm STATE (a
    condition of the vehicle). Pointing --destructive at --critical-red would
    "tokenize" the surface while destroying the distinction the split exists for."""
    tokens = _read(_TOKENS)
    critical = _tokenValue(tokens, "critical-red")
    assert _tokenValue(tokens, "destructive") != critical
    assert _tokenValue(tokens, "destructive-border") != critical


def test_theTwoConfirmSurfaces_areOffTheBrandRedsAndOntoDestructive():
    """The two surfaces US-488 deliberately could not sweep. The confirm BOX
    takes the border token, the Clear-all BUTTON takes the action fill token."""
    rules = dict(_surfaceRules())
    box = rules.get("#clear-confirm .confirm-box")
    ok = rules.get("#clear-confirm-ok")
    assert box is not None and ok is not None, "the confirm rules moved"
    assert "var(--destructive-border)" in box
    assert "var(--destructive)" in ok
    for selector, body in (("#clear-confirm .confirm-box", box), ("#clear-confirm-ok", ok)):
        for brand in ("var(--red)", "var(--red-light)", "var(--red-dark)"):
            assert brand not in body, f"{selector} still on {brand}"


def test_everySweptLiteralIsGoneFromEverySurfaceRule():
    """The enumerated A-2 literals, whole-file. Each is now a token."""
    for selector, body in _surfaceRules():
        for literal in _SWEPT_LITERALS:
            assert literal.lower() not in body.lower(), f"{literal} still on {selector}"


def test_theOnlyRawHexLeftOutsideRoot_isTheBlackWhiteContrastPair():
    """The acceptance line, with its one documented exception made explicit
    rather than left as a silent gap. If this ever fails on a NEW colour, that
    colour wants a token -- not an addition to the allow-set."""
    offenders = {}
    for selector, body in _surfaceRules():
        for hexLit in re.findall(r"#[0-9a-fA-F]{3,8}\b", body):
            if hexLit.lower() not in _ALLOWED_CONTRAST_HEX:
                offenders.setdefault(selector, []).append(hexLit)
    assert offenders == {}, offenders


# ---------------------------------------------------------------------------
# A-3 -- the brand display face (token + binding; the woff2 payload is BL-027).
# ---------------------------------------------------------------------------


def test_fontDisplayJoinsFontMonoInTheSsot():
    """Iris A-3: "add --font-display to the SSOT alongside --font-mono"."""
    tokens = _read(_TOKENS)
    assert _tokenValue(tokens, "font-mono")
    assert _tokenValue(tokens, "font-display")


def test_fontDisplayMirrorMatchesTheSsot():
    """dashboard.html links only dashboard.css, so the dist :root is the RUNTIME
    mirror of the SSOT -- the same two-file discipline every other token keeps."""
    assert "tokens.css" not in _read(_HTML), (
        "if the kit ever links the SSOT directly, the mirror rule changes"
    )
    assert _tokenValue(_read(_CSS), "font-display") == _tokenValue(
        _read(_TOKENS), "font-display"
    )


def test_fontDisplayIsTheLockedBrandStack_notAGenericSans():
    """A REAL display face leads the stack, and the generic families are the
    tail -- never the head.

    RE-AIMED by the BL-027 payload drop (2026-08-01). This pin used to name
    BAHNSCHRIFT, which was the CIO's locked pick at US-510 time. That face
    turned out to be Microsoft-proprietary, absent from Pi OS and not
    redistributable, so it could never be embedded and never actually reached
    the panel. The replacement is the OFL-licensed Oswald subset now inlined in
    both sheets. The invariant this test was really guarding is UNCHANGED and
    is kept verbatim: the brand moments must not resolve to a generic sans.
    What the face IS lives in test_dashboard_brand_font_payload.py, which
    checks the stack lead against the EMBEDDED family rather than a hardcoded
    name -- so the next face swap cannot leave the stack and the payload
    disagreeing.

    RE-AIMED again by US-887-b (2026-10-15): the V0.30 OEM style replaces
    Oswald with the OFL Michroma subset (spec s4.3). Same invariant.
    """
    value = _tokenValue(_read(_TOKENS), "font-display")
    assert "MICHROMA" in value
    assert value.index("MICHROMA") < value.index("SANS-SERIF")


def test_fontDisplayBindsToTheBrandMomentsAndNothingElse():
    """"Wordmark + card titles ONLY" is a two-sided claim, so assert the SET:
    a missing binding leaves a brand moment generic, and an extra one puts a
    display face on a DATA readout -- which is the tabular honesty Iris kept
    ui-monospace for in the first place.

    The not-live marker is the third brand moment (Iris
    specs/v030-frame-and-style-design.md s3.1, US-901-b): a mode label, not a
    data readout.

    MOVED PIN (US-887-c): `.card-title` retired with the title rows; the
    top-bar page name `#page-name` (frame spec s3.2) is its successor.

    MOVED PIN (US-888-a): the Driving card's side LABELS and its GEAR glyph
    (frame spec s4.3: "labels, page names, titles, the gear glyph" are
    Michroma; driving spec AC). Neither is a changing reading -- the readings
    stay --font-mono, pinned in tests/ui/test_driving_page.py.

    MOVED PIN (US-889-b): the Engine card's LABELS (LOAD / THR / THROTTLE /
    TIMING; frame spec s4.3). Its values, units and captions stay --font-mono,
    pinned in tests/ui/test_engine_page.py.

    MOVED PIN (US-890-d): the Fuel card's MPG-row LABELS (LAST 30 S / THIS
    DRIVE / SINCE RESET are Michroma at --fs-meta, Iris B-1). Its figures and
    reasons stay --font-mono, pinned in tests/ui/test_fuel_page.py.

    MOVED PIN (US-896-b): the NAV card's bottom-row LABELS (GRADE / THIS
    DRIVE / LAST DRIVE / SINCE; NAV spec s4.4, Iris UIDEV-004). The SINCE h:mm
    and every figure stay --font-mono, pinned in tests/ui/test_nav_page.py.

    MOVED PIN (US-892-b): the idle face's wordmark retired with that face (CIO
    2026-10-16 Q1), so `.idle-wordmark` leaves the set; the Motion card's
    LABELS join it (PITCH / GRADE  LAST 15 MIN / ACCEL / BRAKE / CORNER, spec
    s3). Its figures, the peak glyphs, the true minus and the degree sign stay
    the inherited --font-mono, pinned in tests/ui/test_motion_page.py.

    MOVED PIN (US-893-b): the Light page's WORD (DAY / DUSK / NIGHT, --fs-hero
    --font-display, light spec s3), its LABELS (AMBIENT / IR / FULL / VISIBLE /
    RANGE) and the status line's BRIGHTNESS [AUTO] label (the mockup's
    Michroma tier, in which Iris G-2's 412 px worst case was measured). The
    lux, counts, level and qualifier stay --font-mono, pinned in
    tests/ui/test_light_page.py.

    MOVED PIN (US-898-b1): the ALERTS card's header count ('n ACTIVE' / '--')
    and its tier chips (STOP / WATCH / MINOR / UNRATED) are Michroma (Warnings
    spec s3: "It carries ... n ACTIVE ... and the chips"). Titles, values,
    sentences and ages stay --font-mono, pinned in tests/ui/test_warnings_page.py.

    MOVED PIN (US-898-b2): the empty-state headline WORDS (NO WARNINGS / NOT
    CHECKED YET, Iris brief '26 px') are Michroma; the '?' beside them, the
    sentences and the '↓ n more below' cue stay --font-mono.

    MOVED PIN (US-899-b): the TROUBLE CODES screen's head, its tier chips and
    DISMISS are Michroma (spec s4.4b); its titles, sentences, '+n more on
    ALERTS' and notice stay --font-mono, pinned in
    tests/ui/test_warnings_code_alert.py.

    MOVED PIN (US-894-b): the System page's row LABELS (OBD, then DATA / WIFI /
    UPS as their rows land) are Michroma (system spec s3: "row label --fs-label
    --font-display"); the values and sentences stay --font-mono, pinned in
    tests/ui/test_system_page_obd_row.py.

    MOVED PIN (US-891-c): the O2 page's section LABELS (FRONT  BEFORE CAT /
    REAR  AFTER CAT / CATALYST) and its LIVE verdict chip (SWITCHING / STUCK
    LEAN / STUCK RICH) are Michroma (O2 spec s3). The withheld chip is lower
    case, so --font-mono; the volts and the meta line stay --font-mono, pinned
    in tests/ui/test_o2_page.py."""
    bound = {
        selector
        for selector, body in _surfaceRules()
        if "var(--font-display)" in body
    }
    assert bound == {
        "#page-name",
        "#not-live-marker",
        "#driving-card .drv-label",
        "#driving-card .drv-gear",
        "#engine-card .eng-label",
        "#fuel-card .fuel-mpg .fuel-label",
        "#nav-card .nav-label",
        "#motion-card .motion-label",
        "#o2-card .o2-label",
        '#o2-card .o2-chip[data-live="true"]',
        "#light-card .light-word",
        "#light-card .light-label",
        "#light-card .light-status-label",
        "#alerts-card .warn-count",
        "#alerts-card .warn-chip",
        "#alerts-card .warn-quiet-word",
        "#code-alert .code-alert-head",
        "#code-alert .code-alert-chip",
        "#code-alert-dismiss",
        ".sys-row-label",
    }, bound


def test_dataAndValueSurfacesStayMonospace():
    """The instrument vernacular is unchanged: the document face is the mono
    token, so every value inherits it unless a brand rule overrides."""
    rules = dict(_surfaceRules())
    body = rules.get("html") or rules.get("body")
    assert body is not None and "var(--font-mono)" in body


def test_theMonoLiteralIsNoLongerForkedOutsideRoot():
    """`ui-monospace, Menlo, Consolas, monospace` was written out longhand in
    the body rule -- a second copy of --font-mono's value, i.e. exactly the fork
    the SSOT rule exists to prevent. Same consolidation as --bg/--surface."""
    for selector, declarations in _surfaceRules():
        assert "ui-monospace" not in declarations, f"mono literal forked onto {selector}"


def test_noFontIsEverFetchedFromACdn():
    """CSP-safe + the kiosk is offline in the car: a webfont URL would render
    the brand moments in a fallback face on the road and nobody would know why.
    This holds whether or not the inlined woff2 has landed (BL-027)."""
    for path in (_TOKENS, _CSS, _HTML):
        text = _read(path).lower()
        assert "@import" not in text, path
        assert "fonts.googleapis" not in text, path
        assert "fonts.gstatic" not in text, path
        assert not re.search(r"url\(\s*[\"']?https?://", text), path
