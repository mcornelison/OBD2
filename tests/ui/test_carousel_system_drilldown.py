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
#     3. FABRICATED FRESHNESS -- only the OBD source publishes `lastSeenS`. A
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
# ================================================================================
################################################################################

"""US-509 tests for the System-Status "N ISSUE" drill-down overlay."""

import json
import os
import shutil
import subprocess

import pytest

# Reuse the sibling suite's comment-stripper rather than re-implementing it: an
# absence assertion that greps a name fires on its own documentation (US-507),
# and that stripper is itself pinned by tests before anything trusts it.
from tests.ui.test_carousel_source_cards import _stripJsComments

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
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


# --- fixtures ---------------------------------------------------------------


def _tile(level: str, label: str, value: str, detail: str = "") -> dict:
    return {"label": label, "value": value, "detail": detail, "level": level}


def _tiles(
    obd: str = "ok",
    sync: str = "ok",
    power: str = "ok",
    drive: str = "ok",
    obdDetail: str = "",
) -> dict:
    """The 4 System Status tiles, addressed by LEVEL so a test reads as a state."""
    return {
        "obdLink": _tile(obd, "OBD LINK", "LINKED", obdDetail),
        "sync": _tile(sync, "SYNC", "OK", "50 rows . 0 pending"),
        "power": _tile(power, "POWER", "CAR", "external"),
        "drive": _tile(drive, "DRIVE", "REC", "drive 27"),
    }


def _sysState(**over: object) -> dict:
    """A healthy system-status emitter payload (US-400 / Atlas A-3 schema)."""
    state: dict = {
        "obdLink": {"state": "linked", "retries": 0, "lastSeenS": 2},
        "sync": {"lastOkTs": "2026-07-31T11:41:50Z", "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "recording", "driveId": 27},
        "ts": "2026-07-31T12:00:00Z",
    }
    state.update(over)
    return state


def _labels(rows: list) -> list:
    return [r["label"] for r in rows]


# ---------------------------------------------------------------------------
# AC1 -- WORST-FIRST. The drill-down exists to say "look at THIS one". An order
# that buries the live fault under an unknown defeats the whole surface.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemIssueRows_worstSourceIsListedFirst():
    """
    Given: SYNC is amber while POWER is down (the worse state)
    When: the drill-down rows are built
    Then: POWER leads, even though SYNC comes first in display order
    """
    rows = _view("systemIssueRows", _tiles(sync="amber", power="down"), _sysState())

    assert _labels(rows) == ["POWER", "SYNC"]


@_NODE_TESTS
def test_systemIssueRows_ordersDownThenAmberThenUnavailable():
    """
    Given: one source at each degraded level
    When: the rows are built
    Then: they descend by severity -- a known-UNKNOWN never outranks a real fault
    """
    rows = _view(
        "systemIssueRows",
        _tiles(obd="unavailable", sync="amber", power="down"),
        _sysState(),
    )

    assert _labels(rows) == ["POWER", "SYNC", "OBD LINK"]


@_NODE_TESTS
def test_systemIssueRows_equalSeverityKeepsTheCardsDisplayOrder():
    """
    Given: two sources degraded to the SAME level
    When: the rows are built
    Then: they follow the 2x2 grid order, so the list never reshuffles between
          polls while the operator is reading it
    """
    rows = _view("systemIssueRows", _tiles(obd="amber", power="amber"), _sysState())

    assert _labels(rows) == ["OBD LINK", "POWER"]


# ---------------------------------------------------------------------------
# AC3 -- honest-instrument: only ACTUALLY-degraded sources appear. Two opposite
# failures are pinned here, because the surface can lie in both directions.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemIssueRows_healthySourceIsNeverListed():
    """
    Given: only SYNC is degraded
    When: the rows are built
    Then: SYNC is the only row -- listing a green source is a fabricated fault
    """
    rows = _view("systemIssueRows", _tiles(sync="amber"), _sysState())

    assert _labels(rows) == ["SYNC"]


@_NODE_TESTS
def test_systemIssueRows_allSourcesGood_listsNothing():
    """
    Given: every source is genuinely good
    When: the rows are built
    Then: there is nothing to drill into
    """
    rows = _view("systemIssueRows", _tiles(), _sysState())

    assert rows == []


@_NODE_TESTS
def test_systemIssueRows_driveIdleIsNominal_neverListedAsDegraded():
    """
    Given: DRIVE is `neutral` (IDLE -- not recording), everything else good
    When: the rows are built
    Then: nothing is listed. `neutral` means "nominal but inactive", NOT broken;
          listing it would report a fault in the commonest state there is
    """
    rows = _view("systemIssueRows", _tiles(drive="neutral"), _sysState())

    assert rows == []


@_NODE_TESTS
def test_systemIssueRows_unavailableSourceIsListed_soTheHeadlineIsNotADeadEnd():
    """
    Given: a source is `unavailable` and nothing is amber/down
    When: the rows are built
    Then: it IS listed. The summary line reads "SYSTEM . 1 UNAVAILABLE" in this
          state, and a tappable headline that opens an empty overlay is the very
          dead end this story removes
    """
    rows = _view("systemIssueRows", _tiles(obd="unavailable"), _sysState())

    assert _labels(rows) == ["OBD LINK"]
    assert rows[0]["level"] == "unavailable"


@_NODE_TESTS
def test_systemIssueRows_unrecognisedLevel_isListedNeverSilentlyDropped():
    """
    Given: a tile carries a level this mapper has not been taught
    When: the rows are built
    Then: it is listed (the card ranks an unknown level as `unavailable`), so a
          future tile level cannot vanish from the drill-down by being new
    """
    rows = _view("systemIssueRows", _tiles(sync="banana"), _sysState())

    assert _labels(rows) == ["SYNC"]


@_NODE_TESTS
def test_systemIssueRows_nonObjectTiles_listNothingRatherThanCrash():
    """
    Given: a malformed tiles payload
    When: the rows are built
    Then: an empty list -- a broken read is never a fabricated fault list
    """
    for bad in (None, "x", []):
        assert _view("systemIssueRows", bad, _sysState()) == []


# ---------------------------------------------------------------------------
# AC1 -- each row = label + state chip + honest reason + freshness.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemIssueRows_rowCarriesLabelChipAndLevel():
    """
    Given: OBD LINK is reconnecting (amber)
    When: the row is built
    Then: it carries the source label, the state chip text and the level that
          colours the chip
    """
    tiles = _tiles(obd="amber")
    tiles["obdLink"]["value"] = "RECONNECTING"
    row = _view("systemIssueRows", tiles, _sysState())[0]

    assert row["label"] == "OBD LINK"
    assert row["value"] == "RECONNECTING"
    assert row["level"] == "amber"


@_NODE_TESTS
def test_systemIssueRows_reasonIsTheTilesOwnDetail_notReWorded():
    """
    Given: a degraded tile whose detail explains WHY
    When: the row is built
    Then: the row repeats the emitter's own words -- the drill-down explains, it
          does not re-diagnose
    """
    tiles = _tiles(sync="amber")
    tiles["sync"]["detail"] = "50 rows . 12 pending"
    row = _view("systemIssueRows", tiles, _sysState())[0]

    assert row["reason"] == "50 rows . 12 pending"


@_NODE_TESTS
def test_systemIssueRows_freshnessReadsSeenSecondsAgoWhenThePublisherReportsIt():
    """
    Given: the OBD source published `lastSeenS`
    When: the row is built
    Then: the freshness reads "seen Ns ago"
    """
    rows = _view(
        "systemIssueRows",
        _tiles(obd="down"),
        _sysState(obdLink={"state": "down", "retries": 3, "lastSeenS": 42}),
    )

    assert rows[0]["freshness"] == "seen 42s ago"


@_NODE_TESTS
def test_systemIssueRows_freshnessIsTypedAbsent_whenTheSourceReportsNoAge():
    """
    Given: SYNC is degraded, and no source but OBD publishes an age at all
    When: the row is built
    Then: the freshness says the age was not reported. "seen 0s ago" would claim
          we just saw a source we never timed -- a fabricated reading, and the
          exact shape of the zeroed-altitude lie US-508 pinned against
    """
    row = _view("systemIssueRows", _tiles(sync="amber"), _sysState())[0]

    assert row["freshness"] == "age not reported"
    assert "0s" not in row["freshness"]


@_NODE_TESTS
def test_systemIssueRows_freshnessIsTypedAbsent_whenLastSeenIsNull():
    """
    Given: the OBD source is present but its `lastSeenS` is null (never seen)
    When: the row is built
    Then: the freshness is the typed absence, never a fabricated zero
    """
    row = _view(
        "systemIssueRows",
        _tiles(obd="down"),
        _sysState(obdLink={"state": "down", "retries": 0, "lastSeenS": None}),
    )[0]

    assert row["freshness"] == "age not reported"


@_NODE_TESTS
def test_systemIssueRows_reasonIsDroppedWhenItOnlyRepeatsTheFreshness():
    """
    Given: a DOWN OBD tile, whose detail IS the seen-age string
    When: the row is built
    Then: the reason is empty rather than printing the same sentence twice in
          one row -- the freshness column already carries that fact
    """
    tiles = _tiles(obd="down", obdDetail="seen 42s ago")
    row = _view(
        "systemIssueRows",
        tiles,
        _sysState(obdLink={"state": "down", "retries": 3, "lastSeenS": 42}),
    )[0]

    assert row["freshness"] == "seen 42s ago"
    assert row["reason"] == ""


# ---------------------------------------------------------------------------
# AC4 -- the rows READ the rendered tile levels; they never recompute a state.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemIssueRows_levelsMatchTheTilesTheGridRenders():
    """
    Given: a mixed state
    When: the rows are built
    Then: every row's level is the level of the tile it names, so the overlay
          can never contradict the card behind it
    """
    tiles = _tiles(obd="down", sync="amber", power="unavailable")
    rows = _view("systemIssueRows", tiles, _sysState())

    byLabel = {r["label"]: r["level"] for r in rows}
    assert byLabel == {"OBD LINK": "down", "SYNC": "amber", "POWER": "unavailable"}


@_NODE_TESTS
def test_systemStatusView_carriesTheDrillDownAlongsideTheSummary():
    """
    Given: a real degraded emitter payload
    When: the full card view is built
    Then: the drill rows travel WITH the view, derived from the same tiles --
          no second read of the state file
    """
    view = _view(
        "systemStatusView",
        _sysState(obdLink={"state": "down", "retries": 5, "lastSeenS": 900}),
    )

    assert view["drill"]["rows"][0]["label"] == "OBD LINK"
    assert view["drill"]["rows"][0]["level"] == view["tiles"]["obdLink"]["level"]


# ---------------------------------------------------------------------------
# AC2 -- the summary is a tap target ONLY when there is something behind it.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_systemStatusView_allGood_summaryIsNotATapTarget():
    """
    Given: every source is good
    When: the card view is built
    Then: the summary is not tappable -- an affordance that opens an empty list
          is a misleading tap target
    """
    view = _view("systemStatusView", _sysState())

    assert view["drill"]["tappable"] is False
    assert view["drill"]["rows"] == []


@_NODE_TESTS
def test_systemStatusView_degradedSource_summaryBecomesATapTarget():
    """
    Given: the sync source has gone stale
    When: the card view is built
    Then: the summary is tappable
    """
    view = _view(
        "systemStatusView",
        _sysState(sync={"lastOkTs": None, "rows": 50, "pending": 9, "stale": True}),
    )

    assert view["drill"]["tappable"] is True


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
    Then: it gates the tap affordance on `drill.tappable`, so an all-good card
          never advertises a drill-down that would open empty
    """
    js = _stripJsComments(_read(_JS))
    start = js.index("function renderSystemStatusCard(")
    body = js[start : start + 2600]

    assert "drill.tappable" in body


def test_carouselJs_summaryTapOpensTheDrillDown():
    """
    Given: the System Status card renderer
    When: its source is read
    Then: the summary element's handler opens the overlay -- a computed row list
          nobody can reach is not a drill-down
    """
    js = _stripJsComments(_read(_JS))
    start = js.index("function renderSystemStatusCard(")
    body = js[start : start + 2600]

    assert "openSysDetail" in body


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
    Given: the drill-down row renderer
    When: its source is read
    Then: it paints the label, the chip, the reason and the freshness. A field
          the view computes but nobody paints is not a readout (US-508)
    """
    js = _stripJsComments(_read(_JS))
    start = js.index("function renderSysDetail(")
    body = js[start : start + 2200]

    for field in (".label", ".value", ".reason", ".freshness", ".level"):
        assert field in body, f"renderSysDetail never paints row{field}"


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


def test_dashboardCss_drillDownOverlayCarriesNoRawColourLiteral():
    """
    Given: the drill-down overlay styling
    When: the CSS is inspected
    Then: it holds no raw hex -- every colour is a tokens.css var (the fork this
          project has repeatedly paid for; US-510 is cleaning the last of it)
    """
    css = _read(_CSS)
    start = css.index("#sys-detail")
    block = css[start : start + 1800]

    assert "#" not in block.replace("#sys-detail", "").replace("#sys-", "")
