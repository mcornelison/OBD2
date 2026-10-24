################################################################################
# File Name: test_carousel_system_drilldown.py
# Purpose/Description: US-509 (F-124) tests -- the System-Status "N ISSUE"
#   drill-down overlay. Tapping the one-glance SYSTEM summary line opens a list
#   of the degraded source(s) so the headline stops being a dead end.
#   The tests are written around the four ways this surface could LIE:
#     1. ORDER -- the worst source must be first. A drill-down that lists an
#        unknown above a live fault buries the thing to act on.
#     2. OMISSION vs CRYING WOLF -- a genuinely-good source must NEVER appear
#        (that is a fabricated fault), and DRIVE=IDLE must never appear either:
#        the card's own severity vocabulary documents `neutral` as "nominal but
#        inactive, NOT broken". But an `unavailable` source MUST appear, or the
#        "SYSTEM . N UNAVAILABLE" headline opens an EMPTY overlay -- the exact
#        dead end this story exists to remove.
#     3. FABRICATED FRESHNESS -- no source publishes a per-source age (the
#        always-null obdLink.lastSeenS went in US-876-a). A
#        row for a source that publishes no age must say so, never "seen 0s
#        ago", which claims we just saw a source we never timed (the US-508
#        zeroed-altitude mistake in a different costume).
#     4. RE-DERIVATION -- the rows must read the SAME tile levels the grid
#        renders, so the overlay can never contradict the card behind it.
#   Pure logic runs through the shared node probe (tests/ui/carousel_probe.js);
#   the browser-only DOM wiring is pinned by reading the shipped artifacts, since
#   a correct routine the tick never calls renders nothing (US-494/US-495).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Ralph (Rex)  | Initial -- US-509 System-Status drill-down.
# 2026-10-22    | Ralph (Rex)  | US-876-a MOVED PIN: no source publishes an age;
#               |              | seen-age freshness/dedup cases reworked.
# 2026-10-23    | Ralph (Rex)  | US-894-b MOVED PIN: the summary line is the
#               |              | verdict line (parked-only tap); the OBD LINK
#               |              | tile is retired, so the view case reads POWER.
# 2026-10-23    | Ralph (Rex)  | US-894-e MOVED PIN: the POWER tile is retired
#               |              | (UPS row) and LAST STOP moved to the UPS
#               |              | detail, so systemStatusView feeds the drill no
#               |              | tiles and no diagnostics: it lists nothing and
#               |              | is not a tap target until US-894-f retires it.
#               |              | The renderer-field scan reads the whole
#               |              | function, not a fixed 2200-char window.
# 2026-10-23    | Ralph (Rex)  | US-894-f MOVED PIN: US-759 is closed by the
#               |              | design -- the issue list and its freshness pair
#               |              | are DELETED, so their tests retire; the verdict
#               |              | opens the Pi detail, and the wiring / CSS-guard
#               |              | tests read that detail.
# ================================================================================
################################################################################

"""US-509 tests for the System-Status "N ISSUE" drill-down overlay."""

import json
import os
import re
import shutil
import subprocess

import pytest

# Reuse the shared CSS primitives rather than re-implementing them: `parseCss`
# strips comments and delimits rules by their real braces, which is exactly the
# subject error US-612 removes, and `render_harness` is the SSOT home US-608
# established for helpers like these (there are already seven `_stripComments`
# copies under tests/ui -- an eighth would be TD-080 growing back).
from tests.ui.render_harness import SectionNotFound, cssSection, parseCss

# Reuse the sibling suite's comment-stripper rather than re-implementing it: an
# absence assertion that greps a name fires on its own documentation (US-507),
# and that stripper is itself pinned by tests before anything trusts it.
from tests.ui.test_carousel_source_cards import _stripJsComments

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard"
)
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CSS = os.path.join(_DIST, "dashboard.css")

_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against N fixtures via the node probe.

    `encoding` is pinned to utf-8 (TD-068): `text=True` alone decodes with the
    Windows locale codepage, which corrupts the "." separator in any copy under
    test and turns a passing assertion into a mojibake mismatch.
    """
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# MOVED PIN (US-894-f): US-759 is CLOSED BY THE DESIGN (spec s4.1, AC 7).
#
# The issue list behind the verdict is deleted: systemIssueRows, systemDrill,
# systemDiagnostics, sysRowFreshness, SYS_NO_AGE and sysLevelRank are gone,
# and with them the four ways it could lie (order, omission / crying wolf, a
# fabricated freshness, re-derivation). There is nothing to order, omit or
# date: the amber row IS the marked, counted thing, and every amber element
# names its verdict member (tests/ui/test_system_page_amber_equals_members.py).
# The tests below pin that the list is really gone, and that the overlay the
# verdict opens is the Pi detail (tests/ui/test_system_page_pi_detail.py).
# ---------------------------------------------------------------------------


def _sysState(**over: object) -> dict:
    """A healthy system-status emitter payload (US-400 / Atlas A-3 schema)."""
    state: dict = {
        "sync": {"lastOkTs": "2026-07-31T11:41:50Z", "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "recording", "driveId": 27},
        "ts": "2026-07-31T12:00:00Z",
    }
    state.update(over)
    return state


def test_us759_theIssueListIsDeleted_notMerelyUnused():
    js = _stripJsComments(_read(_JS))
    for name in ("systemIssueRows", "systemDrill", "systemDiagnostics", "sysRowFreshness",
                 "SYS_NO_AGE", "sysLevelRank"):
        assert re.search(r"\b" + name + r"\b", js) is None, name
    assert "age not reported" not in _read(_JS)


@_NODE_TESTS
def test_us759_theDeletedExportsAreGone():
    proc = subprocess.run(
        [_NODE, "-e",
         "const c=require(process.argv[1]);"
         "console.log(JSON.stringify([typeof c.systemIssueRows, typeof c.systemDrill,"
         " typeof c.systemDiagnostics, typeof c.sysRowFreshness]));",
         _JS],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == ["undefined"] * 4


@_NODE_TESTS
def test_systemStatusView_carriesThePiDetail_noDrillNoTiles():
    """
    Given: a real degraded emitter payload
    When: the full card view is built
    Then: the detail behind the verdict (the Pi detail) travels WITH the view
          -- no second read of the state file -- and no drill or tile does.
    """
    view = _view(
        "systemStatusView",
        _sysState(power={"mode": "car", "source": "battery"}),
    )

    assert "drill" not in view and "tiles" not in view
    assert view["piDetail"]["head"] == "PI"
    assert {r["key"]: r for r in view["rows"]}["ups"]["sentence"] == "on battery"


@_NODE_TESTS
def test_systemStatusView_aDegradedSourceIsOnItsRow_neverInAList():
    """A stale sync is read on the DATA row; no list repeats it."""
    view = _view(
        "systemStatusView",
        _sysState(sync={"lastOkTs": None, "stale": True}),
    )
    assert {r["key"]: r for r in view["rows"]}["data"]["value"].endswith("no sync on record")
    assert "age not reported" not in json.dumps(view)


# ---------------------------------------------------------------------------
# Browser-only DOM wiring. A correct pure function the tick never calls renders
# nothing (US-494/US-495), so the shipped artifacts are read directly.
# ---------------------------------------------------------------------------


def test_dashboardHtml_shipsTheDrillDownOverlayWithABackControl():
    """
    Given: the shipped dashboard.html
    When: the System-Status drill-down markup is inspected
    Then: the overlay, its body and a Back control are all present, and it ships
          HIDDEN so it never covers the boot screen
    """
    html = _read(_HTML)

    assert 'id="sys-detail"' in html
    assert 'id="sys-detail-body"' in html
    assert 'id="sys-detail-back"' in html
    overlay = html[html.index('id="sys-detail"') :][:400]
    assert "hidden" in overlay


def test_dashboardHtml_backControlIsLabelledAndTapSized():
    """
    Given: the shipped Back control
    When: its markup is inspected
    Then: it reuses the shared `tap-target` sizing and carries the ‹ Back copy,
          so the operator is never trapped in the overlay (AC2)
    """
    html = _read(_HTML)
    back = html[html.index('id="sys-detail-back"') :][:260]

    assert "tap-target" in back
    assert "Back" in back


def test_carouselJs_summaryLineIsTappableOnlyWhenRowsExist():
    """
    Given: the System Status card renderer
    When: its source is read
    Then: the verdict's tap affordance is gated on parked.

          MOVED PIN (US-894-b): the verdict line is the tap target, painted by
          renderSystemBody (and gated on parked as well).
          MOVED PIN (US-894-f): `drill.tappable` is deleted with the drill; the
          verdict always has the Pi detail behind it, so parked is the gate.
    """
    js = _stripJsComments(_read(_JS))
    start = js.index("function renderSystemBody(")
    body = js[start : js.index("\n    }", start)]

    assert "drill" not in body
    assert "currentParked().parked" in body
    assert "appendSysVerdict(body, view.verdict, parked)" in body


def test_carouselJs_summaryTapOpensTheDrillDown():
    """
    Given: the System Status card renderer
    When: its source is read
    Then: the summary element's handler opens the overlay -- a computed row list
          nobody can reach is not a drill-down

          MOVED PIN (US-894-b): the verdict line's handler (appendSysVerdict).
          MOVED PIN (US-894-f): it opens the Pi detail.
    """
    js = _stripJsComments(_read(_JS))
    start = js.index("function appendSysVerdict(")
    body = js[start : js.index("\n    }", start)]

    assert 'openSysDetail("pi")' in body
    assert '"drill"' not in js


def test_carouselJs_backButtonClosesTheDrillDown():
    """
    Given: the browser wiring
    When: its source is read
    Then: the Back control is bound to a close handler (AC2 -- never traps)
    """
    js = _stripJsComments(_read(_JS))

    assert "sysDetailBack" in js
    assert "closeSysDetail" in js


def test_carouselJs_drillDownRendererPaintsEveryRowField():
    """
    Given: the detail renderer behind the verdict
    When: its source is read
    Then: it paints every field the view computes. A field the view computes
          but nobody paints is not a readout (US-508)

          MOVED PIN (US-894-f): the issue rows (label, chip, reason,
          freshness) are deleted (US-759); the verdict's detail is the Pi
          detail -- label, value, note, read time, level + member.
    """
    js = _stripJsComments(_read(_JS))
    start = js.index("function renderPiDetail(")
    body = js[start : js.index("function renderObdDetail(", start)]

    for field in (".label", ".value", ".note", ".read", ".level", ".member"):
        assert field in body, f"renderPiDetail never paints row{field}"


def test_carouselJs_openingTheOverlayPausesAutoRotateViaTheSharedSeam():
    """
    Given: US-506 hung auto-rotate pause on ONE document-level pointerdown
    When: this story adds another overlay
    Then: it inherits the pause from that seam rather than adding a call site.
          The document listener is the reason overlay #7 cannot forget to pause,
          so this test pins the seam is still there and still unconditional
    """
    js = _stripJsComments(_read(_JS))
    idx = js.index('document.addEventListener("pointerdown"')
    handler = js[idx : idx + 200]

    assert "pauseAutoRotate()" in handler


# --- US-612 (TD-084): the no-raw-colour guard --------------------------------
#
# The INTENT below is unchanged and is not being relaxed -- every colour on this
# overlay must be a `src/pi/ui/tokens.css` var. Only the SUBJECT changed, from
# raw characters to DECLARATION VALUES, because the retired form scanned a fixed
# 1800-character window and counted the character `#`. That failed in BOTH
# directions: blind to a real hex past char 1800, and red on a CSS comment or a
# non-`#sys-` ID selector that added no colour at all. It went red on a commit
# whose entire content was REMOVING a raw literal, and the stylesheet carried a
# cross-reference spelled without its leading hash purely to appease it (US-558)
# -- a guard that teaches authors to write around it. That comment is restored.
#
# It also anchored on the FIRST textual `#sys-detail` ANYWHERE in the sheet, so a
# single comment mentioning the overlay higher up relocated the whole window into
# unrelated CSS and the guard went on reporting clean. Measured 2026-09-09.

_DRILLDOWN_BANNER = "US-509 System-Status drill-down overlay"

# Hex colours are 3, 4, 6 or 8 digits. The trailing exclusion keeps `#abc-def`
# (an ID reference inside a `url()`) from reading as a colour -- the SAME
# selector-vs-literal conflation this story exists to remove, one level down.
_HEX_COLOUR = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?![0-9a-fA-F-])")

# Selectors belonging to the drill-down overlay and NOWHERE else. `.sys-summary*`
# is deliberately absent: it is legitimately split between the System Status CARD
# section and this one, so it cannot witness a rule that escaped the region.
_DRILLDOWN_ONLY = re.compile(r"[#.]sys-(?:detail|issue|diag)")


def _rawColourLiterals(css: str) -> list[str]:
    """Every raw hex colour in a DECLARATION VALUE, as readable `selector { decl }`.

    Comments are stripped and rules are delimited by their real braces (both by
    `parseCss`), so neither a `#` in prose nor a `#id` selector can be mistaken
    for a colour.
    """
    found: list[str] = []
    for rule in parseCss(css):
        for declaration in rule.declarations.split(";"):
            prop, sep, value = declaration.partition(":")
            if not sep:
                continue
            for hit in _HEX_COLOUR.findall(value):
                found.append(
                    f"{rule.selector.strip()} {{ {prop.strip()}: {value.strip()} }} -> {hit}"
                )
    return found


def _syntheticSheet(inside: str = "", padRules: int = 0) -> str:
    """A stand-in stylesheet whose neighbouring sections carry raw hex on purpose.

    `.above`/`.below` are the NEGATIVE CONTROL for the subject's bounds: a guard
    that scans the whole file -- or, as TD-084's own arithmetic did, everything
    from `#sys-detail` to EOF -- trips on them.
    """
    padding = "\n".join(
        f".sys-issue-pad{n} {{ letter-spacing: 0.06em; padding: 1px 6px; }}"
        for n in range(padRules)
    )
    return (
        "/* --- FIXTURE above ---------------------------------------------- */\n"
        ".above { color: #123456; }\n"
        f"/* --- {_DRILLDOWN_BANNER} ---------------------------- */\n"
        "#sys-detail {\n  background: var(--bg);\n}\n"
        f"{padding}\n{inside}\n"
        "/* --- FIXTURE below ---------------------------------------------- */\n"
        ".below { color: #abcdef; }\n"
    )


def test_dashboardCss_drillDownOverlayCarriesNoRawColourLiteral():
    """
    Given: the drill-down overlay styling
    When: every DECLARATION VALUE in the banner-delimited region is inspected
    Then: it holds no raw hex -- every colour is a tokens.css var (the fork this
          project has repeatedly paid for; US-510 is cleaning the last of it)
    """
    section = cssSection(_read(_CSS), _DRILLDOWN_BANNER)

    assert _rawColourLiterals(section) == []


def test_colourGuard_scansTheWholeRegion_notAFixedWindow():
    """
    Given: a drill-down region whose rules run well past 1800 characters
    When: a raw hex is declared in the LAST rule of the region
    Then: the guard still catches it

    The retired guard read `css[start : start + 1800]`. The shipped region is
    3617 characters, so roughly half of it was never looked at.
    """
    sheet = _syntheticSheet(inside=".sys-diag-text { color: #ff0000; }", padRules=40)
    section = cssSection(sheet, _DRILLDOWN_BANNER)
    assert len(section) > 1800, "fixture must exceed the retired window to be a measurement"

    offenders = _rawColourLiterals(section)

    assert len(offenders) == 1
    assert "#ff0000" in offenders[0]


def test_colourGuard_namesTheOffendingDeclaration_notJustAHashCount():
    """
    Given: a raw hex inside the drill-down region
    When: the guard reports
    Then: it names the selector and the declaration, so the failure reads as a
          finding rather than as a typo
    """
    sheet = _syntheticSheet(inside=".sys-issue-chip { color: #C62828; }")

    (offender,) = _rawColourLiterals(cssSection(sheet, _DRILLDOWN_BANNER))

    assert ".sys-issue-chip" in offender
    assert "color" in offender


def test_colourGuard_catchesEveryHexLength_notJustSixDigits():
    """
    Given: the four hex lengths CSS allows (#rgb, #rgba, #rrggbb, #rrggbbaa)
    When: each is declared in the region
    Then: every one is caught

    `dashboard.css` really does use `#fff`/`#000` shorthand elsewhere, so a guard
    that knew only six digits would wave the commonest form straight through.
    """
    for literal in ("#f00", "#f00c", "#ff0000", "#ff0000cc"):
        sheet = _syntheticSheet(inside=f".sys-issue-reason {{ color: {literal}; }}")

        offenders = _rawColourLiterals(cssSection(sheet, _DRILLDOWN_BANNER))

        assert offenders, f"{literal} escaped the guard"


def test_colourGuard_ignoresHashesInCommentsAndInSelectors():
    """
    Given: a region carrying a `#` in a COMMENT and two `#id` SELECTORS
    When: the guard runs
    Then: it passes -- neither is a colour

    Both were failures under the retired guard, which is why it needed the two
    `.replace("#sys-detail", "").replace("#sys-", "")` patches. Those patches were
    themselves the tell: a guard fighting its own subject.
    """
    sheet = _syntheticSheet(
        inside=(
            "/* see #sys-detail-back, and ticket #84, for the rationale */\n"
            "#sys-detail-back { color: var(--text-primary); }\n"
            "#detail-scrim { display: none; }\n"
        )
    )

    assert _rawColourLiterals(cssSection(sheet, _DRILLDOWN_BANNER)) == []


def test_colourGuard_subjectStopsAtTheRegionBoundaries():
    """
    Given: neighbouring sections that DO carry raw hex
    When: the drill-down region is sliced
    Then: their literals are outside the subject

    This pins the bound in the over-reaching direction. TD-084's own arithmetic
    measured the region as 8506 characters, which is exactly
    `len(css) - index("#sys-detail")` -- the tail of the FILE, not the region.
    Scanning that would drag in the US-407 DTC Clear section, whose Atlas-ruled
    `--destructive` values are recorded in prose right there.
    """
    sheet = _syntheticSheet(inside=".sys-issue-none { color: var(--text-tertiary); }")

    assert _rawColourLiterals(cssSection(sheet, _DRILLDOWN_BANNER)) == []
    assert _rawColourLiterals(sheet) != [], "the fixture's neighbours must really carry hex"


def test_colourGuard_policedRegionIsNotSilentlyEmpty():
    """
    Given: the shipped stylesheet
    When: the policed region is sliced
    Then: it holds the overlay's real rules

    An absence law is satisfied by an EMPTY subject (US-607/US-610). Without this
    pin, breaking the region slicer would leave the guard green forever.
    """
    rules = parseCss(cssSection(_read(_CSS), _DRILLDOWN_BANNER))
    selectors = {rule.selector.strip() for rule in rules}

    assert len(rules) > 10
    # MOVED PIN (US-894-f): the issue chip went with the issue list (US-759);
    # the detail layout rules the OBD / DATA / Pi details share remain.
    assert {"#sys-detail", "#sys-detail-back", ".sys-issue-head", ".pi-value"} <= selectors


def test_everyDrillDownOnlyRuleLivesInsideThePolicedRegion():
    """
    Given: the whole shipped stylesheet
    When: every rule whose selector is drill-down-ONLY is located
    Then: all of them are inside the policed region

    The blind-spot rule. Slicing by region is drift-proof against the region
    GROWING, but not against a drill-down rule being added somewhere ELSE in the
    sheet -- which would be unpoliced and silent. This makes that loud instead.
    """
    css = _read(_CSS)
    section = cssSection(css, _DRILLDOWN_BANNER)

    everywhere = {r.selector.strip() for r in parseCss(css) if _DRILLDOWN_ONLY.search(r.selector)}
    policed = {r.selector.strip() for r in parseCss(section)}

    assert everywhere, "the family matcher found nothing -- it has gone stale"
    assert everywhere <= policed, (
        "drill-down rules live outside the policed region and are unguarded: "
        f"{sorted(everywhere - policed)}"
    )


def test_cssSection_raisesWhenTheBannerIsAbsent_neverReturnsAnEmptySpan():
    """
    Given: a stylesheet with no such section
    When: the section is requested
    Then: it RAISES and names the banner -- it does not return ""

    A slicer that returns an empty string on a miss makes every absence
    assertion above pass vacuously, which is the defect class this sprint exists
    to remove.
    """
    with pytest.raises(SectionNotFound) as excinfo:
        cssSection(".above { color: #123456; }\n", _DRILLDOWN_BANNER)

    assert _DRILLDOWN_BANNER in str(excinfo.value)
