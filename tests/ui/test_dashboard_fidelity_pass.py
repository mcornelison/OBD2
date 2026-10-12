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
# ================================================================================
################################################################################

"""US-510 tests for the dashboard fidelity pass (locked copy, tokens, brand face)."""

import json
import os
import re
import shutil
import subprocess

import pytest

from tests.ui.render_harness import parseCss

_HERE = os.path.dirname(__file__)
_PROBE = os.path.join(_HERE, "carousel_probe.js")
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

# --- the locked strings (Iris, 2026-07-21-pi-idle-state-and-full-bleed.md 1.2,
# re-asserted verbatim as US-510 A-1). These are the SPEC, not a paraphrase of
# it: the PM's story text renders "·" as "." and "⋮" as "the kebab", and the AC
# says "verbatim from the locked idle spec" -- reproducing the paraphrase would
# repeat the exact drift this story exists to undo.
_LOCKED_WORDMARK = "ECLIPSE OBD-II"
_LOCKED_FOOTER = "swipe for details · hold or ⋮ for setup"
# The pre-drift line the build shipped instead. Named so its removal is pinned.
_DRIFTED_FOOTER = "monitoring resumes on engine start"

# Atlas Rule-10 ruling 2026-07-31 (design-gate PASS + rulings). Values, not
# Rex-derived: --bg/--surface are the EXISTING dashboard.css:27-28 literals
# being promoted; the destructive pair is Atlas's new definition.
_ATLAS_BG = "#000000"
_ATLAS_SURFACE = "#111111"
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


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the shared probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _idleView(motionReason: object = "sensor not detected") -> dict:
    """The assembled fallback-card view. Only the copy fields matter here, and
    they do not depend on the state fixtures.

    US-542 dropped `dtcData` from the signature, so this helper is THREE args
    now. That drop is why it has to be repointed rather than left alone: a stale
    4-arg call still runs, it just binds the motion reason to a parameter that
    no longer exists -- green, and testing nothing (the US-541 lesson)."""
    return _view("idleCardView", None, None, motionReason)


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
def test_idleWordmark_isTheLockedEclipseObdIiString():
    """Given: Iris's locked idle spec 1.2 says the wordmark is `ECLIPSE OBD-II`
    When: the idle view is assembled
    Then: it carries the locked string, not the build's `ECLIPSE` paraphrase."""
    assert _idleView()["wordmark"] == _LOCKED_WORDMARK


@_needsNode
def test_idleWordmark_survivesTheUs542Retirement():
    """The wordmark is BRANDING, not status. US-542 retired the parked screen
    around it and the LOCKED FOOTER with that screen -- this string stays,
    because a dead motion feed does not re-brand the product and the wordmark
    was never teaching the operator anything about being parked."""
    assert _idleView("no motion feed")["wordmark"] == _LOCKED_WORDMARK


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


@_needsNode
def test_theSurvivingFooterStatesTheFaultNotANavigationHint():
    """The one remaining disposition (motion feed dead) keeps its OWN footer: it
    states the fault the operator otherwise has no explanation for -- the live
    card just vanished. Replacing it with a navigation hint would delete a real
    instrument fact to make room for a tutorial."""
    footer = _idleView("sensor not detected")["footer"]
    assert footer, "the fallback disposition still needs a footer"
    assert footer != _LOCKED_FOOTER
    assert "motion feed" in footer


def test_theDriftedStatusLineIsGoneFromTheSource():
    """The pre-drift copy must not survive anywhere executable. Comments are
    stripped first: the renderer's own note NAMES this string while explaining
    why the footer became a view field, so an un-stripped grep would fail on
    the documentation of the fix rather than on the defect."""
    assert _DRIFTED_FOOTER not in _stripJsComments(_read(_JS))


def test_theRestoredCopyIsActuallyPainted():
    """A view field nobody renders is not copy -- it is a variable. Both the
    wordmark and the footer must reach the DOM from the VIEW (never a literal
    re-typed in the renderer, which is how the two drifted apart originally)."""
    js = _stripJsComments(_read(_JS))
    assert "wm.textContent = view.wordmark" in js
    assert "footer.textContent = view.footer" in js


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
    the current ones, so a diff that changes a rendered pixel FAILS. The dist
    mirror and the SSOT must agree, and both must equal the pre-story literal."""
    css, tokens = _read(_CSS), _read(_TOKENS)
    for name, expected in (("bg", _ATLAS_BG), ("surface", _ATLAS_SURFACE)):
        assert _tokenValue(css, name) == _tokenValue(tokens, name), name
        assert _tokenValue(css, name) == expected.upper(), name


def test_theBackgroundLiteralIsNeverReForkedIntoASurface():
    """The cheap way to "pass" a tokenization sweep is to inline the value again
    somewhere else. #000000 is now --bg's job; the long form must appear only in
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


def test_takeoverGradientEdges_areTokenisedNotInlined():
    """Iris A-2 offered two routes for the deep gradient edges and this takes
    the named-token one deliberately: a color-mix() would COMPUTE a new colour
    and move the rendered pixels, which the zero-visual-change rule forbids."""
    rules = dict(_surfaceRules())
    watch = rules.get('#dtc-takeover[data-severity="watch"]')
    minor = rules.get('#dtc-takeover[data-severity="minor"]')
    assert watch and minor, "the takeover severity rules moved -- re-point this"
    assert "var(--amber-deep)" in watch
    assert "var(--green-deep)" in minor and "var(--green-deepest)" in minor


def test_theDeepEdgeTokensRelocateTheExistingValues_neverNewOnes():
    """Grounding: these three tokens are NOT new colours. Each holds the exact
    literal that used to sit in the gradient, so the takeover renders
    identically -- the relocation is invisible on the panel, which is the point."""
    css = _read(_CSS)
    assert _tokenValue(css, "amber-deep") == "#7A5B00"
    assert _tokenValue(css, "green-deep") == "#12603A"
    assert _tokenValue(css, "green-deepest") == "#062617"


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
    """
    value = _tokenValue(_read(_TOKENS), "font-display")
    assert "OSWALD" in value
    assert value.index("OSWALD") < value.index("SANS-SERIF")


def test_fontDisplayBindsToTheBrandMomentsAndNothingElse():
    """"Wordmark + card titles ONLY" is a two-sided claim, so assert the SET:
    a missing binding leaves a brand moment generic, and an extra one puts a
    display face on a DATA readout -- which is the tabular honesty Iris kept
    ui-monospace for in the first place."""
    bound = {
        selector
        for selector, body in _surfaceRules()
        if "var(--font-display)" in body
    }
    assert bound == {".idle-wordmark", ".card-title"}, bound


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
