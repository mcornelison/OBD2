################################################################################
# File Name: test_warnings_page.py
# Purpose/Description: US-898-b1 (F-127; specs/v030-warnings-page-design.md s3,
#   s4.1, s4.6) tests for the ALERTS card re-keyed onto states/alerts. Guarded:
#     0. the FIXTURES -- each tests/ui/fixtures/states/alerts/ file this story
#        adds is exactly what the REAL provider `buildAlertsState` writes for the
#        episodes below (run this file as a script to rewrite them);
#     1. the VIEW -- the pure `warningsPageView(alerts, nowTs)` gives the header
#        ('n ACTIVE' + 'codes read h:mm' / 'codes not read yet') and one row per
#        entry IN THE PROVIDER'S ORDER, with the provider's words, the value
#        through displayUnits, the M7 staleness clause and agoText ages;
#     2. the DOM -- the shipped carousel.js, booted over the shipped markup,
#        paints #alerts-card from /alerts alone (rows in entries[] order, CODE
#        rows are buttons, ENGINE rows are not), LOADING then 'no warnings data'
#        with no payload, and still feeds states/dtc to the ribbon each tick;
#     3. the CSS -- chip inks per tier from tokens (AA, Atlas MEASURED), rows
#        >= 48 px and never .tile, sentences plain text (US-758);
#     4. the GATES -- no '.sort(' and no tier comparison in the Warnings render,
#        no tier copy literal in it, and the dtc-driven card body is gone.
#   US-898-b2 adds: NONE / NOT CHECKED with nothing active, the empty-state
#   body that prints only what `sources` says was assessed (898-2, 898-3), and
#   the scrolling list with its '↓ n more below' cue (898-5, Iris U9).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Ralph (Rex)  | Initial -- US-898-b1 ALERTS card from states/alerts.
# 2026-10-20    | Ralph (Rex)  | US-898-b2 -- empty / not-checked states, scroll cue.
# 2026-10-20    | Ralph (Rex)  | US-899-a2 -- MOVED PIN: the tick's states/dtc feed and
#               |              | the ribbon are deleted; DTC_TIER no longer stays.
# 2026-10-21    | Ralph (Rex)  | US-897-d -- MOVED PIN: a battery episode carries the
#               |              | provider's round (its side); every fixture entry
#               |              | gains `round` (rewritten by running this file).
# ================================================================================
################################################################################

"""US-898-b1 tests: the ALERTS card lists the provider's entries in its order."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from pi.obdii.alerts_arbiter import (  # noqa: E402
    BATTERY_HIGH_SENTENCE,
    BATTERY_HIGH_TITLE,
    BATTERY_LOW_SENTENCE,
    BATTERY_LOW_TITLE,
    CODE_UNRATED_SENTENCE,
    COOLANT_STOP_DIRECTIVE,
    COOLANT_STOP_SENTENCE,
    COOLANT_STOP_TITLE,
    RPM_OVER_REV_TITLE,
    AlertEpisode,
    _rpmSentence,
    buildAlertsState,
)
from tests.ui.css_type_scale import DASHBOARD_CSS, TOKENS_CSS, readCss  # noqa: E402

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROBE = os.path.join(_HERE, "carousel_probe.js")
_FIXTURES = os.path.join(_HERE, "fixtures", "states", "alerts")
_HTML = os.path.join(rh.DASHBOARD_DIR, "dashboard.html")
_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")

CARD_ID = "alerts-card"
PANEL = (480, 320)

# Every fixture is published at this instant; ages below are measured from it.
NOW = "2026-10-20T17:30:00Z"
NOW_MS = int(datetime(2026, 10, 20, 17, 30, tzinfo=UTC).timestamp() * 1000)
CHECKED_AT = "2026-10-20T17:20:00Z"
CODES_READ = {"assessed": True, "checkedAtTs": CHECKED_AT}

# Spool 2026-10-18 (US-754 rows): the car's two real stored codes, verbatim.
P0400_TITLE = "EGR FLOW (P0400)"
P0400_SENTENCE = "Drive gently. Get it diagnosed."
P0443_TITLE = "EVAP PURGE (P0443)"
P0443_SENTENCE = "Emissions only. Safe to drive."

# Iris G-2: tier copy is the provider's; the Warnings render carries none of it.
TIER_COPY = (
    "ENGINE OVERHEATING", "CHARGING FAULT", "OVERCHARGING", "OVER-REV",
    "GET DIAGNOSED", "Stop safely",
)

# The Warnings render functions this story adds (the scope of the G-2/G-6 gates).
WARNINGS_FUNCTIONS = (
    "warningsPageView", "warningRowView", "warningsHeaderView",
    "warningStaleText", "renderWarningsCard",
    # US-898-b2
    "warningsQuietView", "warningsQuietBlock", "warningsMoreBelow",
    "warningsBelowFromLayout", "updateWarningsMore",
)


# ---------------------------------------------------------------------------
# 0. Fixtures, from the real provider.
# ---------------------------------------------------------------------------


def _episode(**fields: Any) -> AlertEpisode:
    base: dict[str, Any] = {
        "directive": None, "unit": None, "active": True, "stale": False,
        "value": None, "last": None, "peak": None, "codeStatus": None,
    }
    base.update(fields)
    return AlertEpisode(**base)


def _coolant(**fields: Any) -> AlertEpisode:
    return _episode(
        source="engine", key="COOLANT_TEMP", tier="stop", title=COOLANT_STOP_TITLE,
        sentence=COOLANT_STOP_SENTENCE, directive=COOLANT_STOP_DIRECTIVE, unit="C",
        **fields,
    )


def _battery(side: str, value: float, firstSeenTs: str) -> AlertEpisode:
    title, sentence = (
        (BATTERY_LOW_TITLE, BATTERY_LOW_SENTENCE) if side == "low"
        else (BATTERY_HIGH_TITLE, BATTERY_HIGH_SENTENCE)
    )
    # MOVED PIN (US-897-d): the provider's round for the episode's side.
    return _episode(
        source="engine", key="BATTERY_V", tier="watch", title=title, sentence=sentence,
        unit="V", value=value, firstSeenTs=firstSeenTs, lastSeenTs=NOW,
        round="floor" if side == "low" else "ceil",
    )


def _code(code: str, tier: str, title: str, sentence: str, firstSeenTs: str) -> AlertEpisode:
    return _episode(
        source="code", key=code, tier=tier, title=title, sentence=sentence,
        firstSeenTs=firstSeenTs, lastSeenTs=CHECKED_AT, codeStatus="stored",
    )


def _p0400() -> AlertEpisode:
    # 41 whole days before NOW: Iris's example row reads '41 days ago'.
    return _code("P0400", "watch", P0400_TITLE, P0400_SENTENCE, "2026-09-09T17:00:00Z")


def _p0443() -> AlertEpisode:
    return _code("P0443", "minor", P0443_TITLE, P0443_SENTENCE, "2026-06-05T15:00:00Z")


# name -> (episodes, codeSource). The provider orders them; these lists do not.
SCENARIOS: dict[str, tuple[list[AlertEpisode], dict[str, Any] | None]] = {
    "mixed-live-and-stored": (
        [_p0443(), _p0400(), _battery("low", 11.8, "2026-10-20T17:28:00Z")], CODES_READ,
    ),
    "two-stored-codes-real": ([_p0443(), _p0400()], CODES_READ),
    "unrated-code": (
        [_code("P2187", "unrated", "P2187", CODE_UNRATED_SENTENCE, "2026-10-17T09:00:00Z")],
        CODES_READ,
    ),
    "watch-battery-low": ([_battery("low", 11.8, "2026-10-20T17:28:00Z")], CODES_READ),
    "watch-battery-high": ([_battery("high", 15.1, "2026-10-20T17:10:00Z")], CODES_READ),
    "watch-over-rev": (
        [_episode(
            source="engine", key="RPM", tier="watch", title=RPM_OVER_REV_TITLE,
            sentence=_rpmSentence(7150), firstSeenTs="2026-10-20T17:29:10Z",
            lastSeenTs="2026-10-20T17:29:12Z",
        )],
        CODES_READ,
    ),
    "stop-live-overheat": (
        [_coolant(value=112, peak=112, firstSeenTs="2026-10-20T17:29:40Z", lastSeenTs=NOW)],
        CODES_READ,
    ),
    "stop-live-stale": (
        [_coolant(
            stale=True, peak=112, firstSeenTs="2026-10-20T17:26:00Z",
            lastSeenTs="2026-10-20T17:29:48Z",
            last={"value": 112, "band": {"band": "red"}, "ts": "2026-10-20T17:29:48Z"},
        )],
        CODES_READ,
    ),
    "stop-live-cleared": (
        [_coolant(
            active=False, peak=112, firstSeenTs="2026-10-20T17:05:00Z",
            lastSeenTs="2026-10-20T17:20:00Z",
            last={"value": 110, "band": {"band": "red"}, "ts": "2026-10-20T17:19:00Z"},
        )],
        CODES_READ,
    ),
    # US-898-b2. The story's example read time (10:02 in America/Chicago).
    "checked-clean": ([], {"assessed": True, "checkedAtTs": "2026-10-20T15:02:00Z"}),
    "not-checked": ([], None),
    "system-data-not-assessed": ([], CODES_READ),
    "codes-unread-with-watch": ([_battery("low", 11.8, "2026-10-20T17:28:00Z")], None),
    "seven-entries-scroll": (
        [
            _p0443(),
            _code("P2187", "unrated", "P2187", CODE_UNRATED_SENTENCE, "2026-10-17T09:00:00Z"),
            _battery("low", 11.8, "2026-10-20T17:28:00Z"),
            _p0400(),
            _code("P0128", "unrated", "P0128", CODE_UNRATED_SENTENCE, "2026-10-18T09:00:00Z"),
            _episode(
                source="engine", key="RPM", tier="watch", title=RPM_OVER_REV_TITLE,
                sentence=_rpmSentence(7150), firstSeenTs="2026-10-20T17:29:10Z",
                lastSeenTs="2026-10-20T17:29:12Z",
            ),
            _coolant(value=112, peak=112, firstSeenTs="2026-10-20T17:29:40Z", lastSeenTs=NOW),
        ],
        CODES_READ,
    ),
}

# A fresh coolant reading is what makes the provider assess ENGINE (Q14).
FRESH_COOLANT = {"params": {"COOLANT_TEMP": {"value": 90, "unit": "C", "stale": False}}}
OBD_LIVE: dict[str, dict[str, Any]] = {"checked-clean": FRESH_COOLANT}


def buildFixture(name: str) -> dict[str, Any]:
    """The states/alerts payload the shipped provider writes for a scenario."""
    episodes, codeSource = SCENARIOS[name]
    return buildAlertsState(
        episodes, OBD_LIVE.get(name), datetime(2026, 10, 20, 17, 30, tzinfo=UTC),
        dataSource="real", bootId="boot-fixture-0001", codeSource=codeSource,
    )


def _fixturePath(name: str) -> str:
    return os.path.join(_FIXTURES, name + ".json")


def _fixture(name: str) -> Any:
    with open(_fixturePath(name), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_everyFixtureIsWhatTheShippedProviderWrites(name: str):
    """A hand-drifted fixture stays green through a provider change (US-628)."""
    assert _fixture(name) == buildFixture(name)


def test_theRealCodesFixture_carriesSpoolsRowsInTheProvidersOrder():
    entries = _fixture("two-stored-codes-real")["entries"]
    assert [(e["title"], e["tier"], e["sentence"]) for e in entries] == [
        (P0400_TITLE, "watch", P0400_SENTENCE),
        (P0443_TITLE, "minor", P0443_SENTENCE),
    ]


# ---------------------------------------------------------------------------
# 1. The pure view.
# ---------------------------------------------------------------------------


def _views(fn: str, argLists: list[list[Any]], tz: str = "UTC") -> list[Any]:
    """carousel.js `fn` over each argument list, on a pinned local time zone."""
    proc = subprocess.run(
        [_NODE or "node", _PROBE, "--map", fn],
        input=json.dumps(argLists), capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, TZ=tz),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _page(payload: Any, now: str = NOW, tz: str = "UTC") -> dict[str, Any]:
    return _views("warningsPageView", [[payload, now]], tz)[0]


def _rowFor(name: str, index: int = 0) -> dict[str, Any]:
    return _page(_fixture(name))["rows"][index]


@_NODE_ONLY
def test_mixed_rowsAreTheEntriesInTheirOrder_headerThreeActive():
    payload = _fixture("mixed-live-and-stored")
    view = _page(payload)
    assert [r["id"] for r in view["rows"]] == [e["id"] for e in payload["entries"]]
    assert view["header"] == {"text": "3 ACTIVE", "meta": "codes read 5:20", "tone": None}
    assert view["missing"] is False
    assert view["quiet"] is None, "anything active -> no empty-state block"


@_NODE_ONLY
def test_theRowOrderIsTheProvidersEvenWhenItIsNotTheTierOrder():
    """The page never re-ranks: a payload whose order no tier rule would give
    still renders in that order (Iris G-6)."""
    payload = _fixture("mixed-live-and-stored")
    payload["entries"] = list(reversed(payload["entries"]))
    view = _page(payload)
    assert [r["id"] for r in view["rows"]] == [e["id"] for e in payload["entries"]]


@_NODE_ONLY
def test_codesReadIsTheLocalTwelveHourClock_noAmPm():
    payload = _fixture("mixed-live-and-stored")
    assert _page(payload, tz="Asia/Tokyo")["header"]["meta"] == "codes read 2:20"


@_NODE_ONLY
def test_codesUnreadWithABatteryWatch_iconWatch_metaCodesNotReadYet():
    """898-10: an active WATCH outranks '?', and the meta says the codes were
    not read rather than giving a time."""
    payload = _fixture("codes-unread-with-watch")
    assert payload["sources"]["code"]["checkedAtTs"] is None
    assert _views("alertIconView", [[payload]])[0]["state"] == "watch"
    view = _page(payload)
    assert view["header"] == {"text": "1 ACTIVE", "meta": "codes not read yet", "tone": None}
    assert view["quiet"] is None and len(view["rows"]) == 1


@_NODE_ONLY
def test_anUnreadableCheckedAt_neverInventsATime():
    payload = _fixture("two-stored-codes-real")
    payload["sources"]["code"]["checkedAtTs"] = "2026-10-20T17:20:00"
    assert _page(payload)["header"]["meta"] == "codes read --"


@_NODE_ONLY
def test_activeCountExcludesClearedEntries():
    """Only a cleared entry -> nothing active: NONE (US-898-b2), and the
    cleared row is still listed under the empty state (never hidden)."""
    view = _page(_fixture("stop-live-cleared"))
    assert view["header"]["text"] == "NONE"
    assert view["quiet"]["head"] == "NO WARNINGS"
    assert len(view["rows"]) == 1 and view["rows"][0]["active"] is False


# --- US-898-b2: say only what was checked ------------------------------------

NOT_BUILT = "System and data checks are not built yet."


@_NODE_ONLY
def test_checkedClean_isTheStorysExample():
    """checked-clean at 15:02Z in America/Chicago (CDT) -> 10:02."""
    view = _page(_fixture("checked-clean"), tz="America/Chicago")
    assert view["header"] == {"text": "NONE", "meta": "codes read 10:02", "tone": None}
    assert view["rows"] == []
    assert view["quiet"] == {
        "state": "none", "mark": None, "head": "NO WARNINGS",
        "lines": [
            {"text": "Codes read at 10:02. Engine checks clear.", "tone": "primary"},
            {"text": NOT_BUILT, "tone": "secondary"},
        ],
    }


@_NODE_ONLY
def test_engineNotAssessed_dropsTheEngineClause():
    view = _page(_fixture("system-data-not-assessed"))
    assert _fixture("system-data-not-assessed")["sources"]["engine"]["assessed"] is False
    assert [line["text"] for line in view["quiet"]["lines"]] == [
        "Codes read at 5:20.", NOT_BUILT,
    ]


@_NODE_ONLY
def test_systemAndDataBothAssessed_dropsTheNotBuiltLine():
    payload = _fixture("checked-clean")
    payload["sources"]["system"] = {"assessed": True}
    payload["sources"]["data"] = {"assessed": True}
    assert [line["text"] for line in _page(payload)["quiet"]["lines"]] == [
        "Codes read at 3:02. Engine checks clear.",
    ]


@_NODE_ONLY
@pytest.mark.parametrize("which", ["system", "data"])
def test_eitherSourceUnassessed_keepsTheNotBuiltLine(which: str):
    payload = _fixture("checked-clean")
    payload["sources"]["system"] = {"assessed": True}
    payload["sources"]["data"] = {"assessed": True}
    del payload["sources"][which]
    assert _page(payload)["quiet"]["lines"][-1]["text"] == NOT_BUILT


@_NODE_ONLY
def test_notChecked_amberHeaderNoMeta_andTheQuestionMark():
    view = _page(_fixture("not-checked"))
    assert view["header"] == {"text": "NOT CHECKED", "meta": "", "tone": "amber"}
    assert view["quiet"] == {
        "state": "not-checked", "mark": "?", "head": "NOT CHECKED YET",
        "lines": [{
            "text": "Trouble codes haven't been read since key-on, so \"nothing found\" can't be claimed.",
            "tone": "primary",
        }],
    }


@_NODE_ONLY
@pytest.mark.parametrize("assessed", [None, "true", 1, False])
def test_anythingButAssessedTrue_isNotChecked(assessed: Any):
    """Only the provider's exact `true` lets the card claim a read."""
    payload = _fixture("checked-clean")
    payload["sources"]["code"]["assessed"] = assessed
    view = _page(payload)
    assert view["header"]["text"] == "NOT CHECKED"
    assert view["quiet"]["state"] == "not-checked"


# --- US-898-b2: the '↓ n more below' fallback (Iris U9) ----------------------


@_NODE_ONLY
@pytest.mark.parametrize(
    "rows,header,cue,n",
    [
        (7, 40, 20, 3),    # Iris U9: (270 - 40 - 20) / 48 -> 4 visible
        (4, 40, 20, 0),
        (5, 40, 20, 1),
        (7, 0, 0, 2),      # 270 / 48 -> 5 visible
        (7, 100, 20, 4),   # a taller header shows fewer rows
        (0, 40, 20, 0),
        (2, 300, 20, 2),   # no room at all -> every row is below
    ],
)
def test_moreBelowFallback_is48pxRowsIn270MinusHeaderAndCue(rows: int, header: float, cue: float, n: int):
    assert _views("warningsMoreBelow", [[rows, header, cue]])[0] == n


@_NODE_ONLY
def test_moreBelowFromLayout_countsRowsWhoseBottomIsBelowTheVisibleBottom():
    """A wrapped (taller) row pushes more rows below than the fallback would
    report -- the layout count is the runtime one (Iris U9)."""
    bottoms = [48, 120, 168, 216, 264, 312, 360]
    assert _views("warningsBelowFromLayout", [[210, bottoms], [210.4, [210]], [400, bottoms]]) == [
        4, 0, 0,
    ]


@_NODE_ONLY
def test_moreText_isMonoArrowAndCount_orNothing():
    assert _views("warningsMoreText", [[3], [0], [1]]) == ["↓ 3 more below", "", "↓ 1 more below"]


@_NODE_ONLY
def test_sevenEntries_rowOneIsTheMostSevere():
    rows = _page(_fixture("seven-entries-scroll"))["rows"]
    assert len(rows) == 7
    assert rows[0]["tier"] == "stop" and rows[0]["key"] == "COOLANT_TEMP"


@_NODE_ONLY
def test_twoRealCodes_chipsTitlesAndSpoolsSentences():
    rows = _page(_fixture("two-stored-codes-real"))["rows"]
    assert [(r["chip"], r["tier"], r["title"], r["sentence"]) for r in rows] == [
        ("WATCH", "watch", P0400_TITLE, P0400_SENTENCE),
        ("MINOR", "minor", P0443_TITLE, P0443_SENTENCE),
    ]
    assert rows[0]["age"] == "41 days ago"
    assert all(r["value"] is None and r["control"] is True for r in rows)


@_NODE_ONLY
def test_unrated_neutralChipAndTheProvidersSentence():
    """898-6: the UNRATED words are the provider's, never a page literal."""
    row = _rowFor("unrated-code")
    assert (row["chip"], row["tier"], row["sentence"]) == (
        "UNRATED", "unrated", CODE_UNRATED_SENTENCE,
    )
    payload = _fixture("unrated-code")
    payload["entries"][0]["sentence"] = "provider words 123"
    assert _page(payload)["rows"][0]["sentence"] == "provider words 123"


@_NODE_ONLY
@pytest.mark.parametrize(
    "name,value,age",
    [("watch-battery-low", "11.8 V", "2 min ago"), ("watch-battery-high", "15.1 V", "20 min ago")],
)
def test_batteryWatch_valueInVoltsOneDecimal_ageIsAgoText(name: str, value: str, age: str):
    row = _rowFor(name)
    assert (row["chip"], row["title"], row["value"], row["age"]) == (
        "WATCH", BATTERY_LOW_TITLE if "low" in name else BATTERY_HIGH_TITLE, value, age,
    )
    assert row["control"] is False and row["stale"] is None


@_NODE_ONLY
def test_overRev_theSampledSentenceSurvives_noValue():
    row = _rowFor("watch-over-rev")
    assert row["sentence"] == "peak 7,150 rpm (sampled)"
    assert row["value"] is None


@_NODE_ONLY
def test_liveOverheat_valueInFahrenheit_justNow():
    row = _rowFor("stop-live-overheat")
    assert (row["chip"], row["value"], row["stale"], row["age"]) == (
        "STOP", "234 °F", None, "just now",
    )


@_NODE_ONLY
def test_staleOverheat_lastValueInFahrenheit_andItsFreshnessClause():
    row = _rowFor("stop-live-stale")
    assert row["value"] == "234 °F"
    assert row["stale"] == "last reading 12 s ago"
    assert row["age"] == "4 min ago", "the age column stays agoText(firstSeenTs)"


@_NODE_ONLY
@pytest.mark.parametrize(
    "lastTs,text",
    [
        ("2026-10-20T17:29:59.400Z", "last reading 0 s ago"),
        ("2026-10-20T17:31:00Z", "last reading 0 s ago"),
        ("2026-10-20T17:13:21Z", "last reading 999 s ago"),
        ("2026-10-20T17:13:20Z", "last reading 999+ s ago"),
        ("2026-10-19T17:30:00Z", "last reading 999+ s ago"),
    ],
    ids=["floor", "future-clamps-to-0", "999", "1000-caps", "a-day"],
)
def test_staleClause_isTheM7Rule(lastTs: str, text: str):
    payload = _fixture("stop-live-stale")
    payload["entries"][0]["last"]["ts"] = lastTs
    assert _page(payload)["rows"][0]["stale"] == text


@_NODE_ONLY
def test_cleared_isListedAsClearedInTheAgeColumn():
    row = _rowFor("stop-live-cleared")
    assert (row["active"], row["age"], row["chip"]) == (False, "cleared", "STOP")


@_NODE_ONLY
@pytest.mark.parametrize(
    "payload", [None, "garbage", {}, {"entries": None}], ids=["null", "string", "no-entries", "entries-null"]
)
def test_noReadablePayload_isDashDash_andNoWarningsData(payload: Any):
    view = _page(payload)
    assert view["missing"] is True
    assert view["header"] == {"text": "--", "meta": "", "tone": None}
    assert view["quiet"] is None, "no payload is never an empty-state claim"
    assert view["rows"] == []
    assert view["empty"] == "no warnings data"


@_NODE_ONLY
def test_engineRowsAreNotControls_codeRowsAre():
    rows = _page(_fixture("mixed-live-and-stored"))["rows"]
    assert [(r["source"], r["control"]) for r in rows] == [
        ("engine", False), ("code", True), ("code", True),
    ]


# ---------------------------------------------------------------------------
# 2. The DOM the shipped JS leaves.
# ---------------------------------------------------------------------------


def _systemStatus() -> dict[str, Any]:
    return {
        "wifi": {"state": "up", "ssid": "bench", "rssiDbm": -50},
        # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
        "obdLink": {"state": "linked", "retries": 0},
        "sync": {"lastOkTs": NOW, "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "idle", "driveId": None},
        "source": {"obd": {"available": True}},
        "idle": True,
        "ts": NOW,
    }


def _routes(alerts: Any) -> dict[str, Any]:
    routes: dict[str, Any] = {"/system-status": _systemStatus()}
    if alerts is not None:
        routes["/alerts"] = alerts
    return routes


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out).strip()


def _classes(node: dict[str, Any]) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


def _cardDom(alerts: Any, steps: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], rh.Surface, dict[str, Any]]:
    dom = rh.runDashboard(routes=_routes(alerts), steps=steps, viewport=PANEL, nowMs=NOW_MS)
    surface = rh.dashboardSurface(dom["tree"], viewport=PANEL)
    path = surface.pathById(CARD_ID)
    assert path is not None, f"#{CARD_ID} is not in the DOM"
    return path, surface, dom


def _rowPaths(surface: rh.Surface) -> list[list[dict[str, Any]]]:
    return [p for p in surface.pathsByClass("warn-row") if any(n.get("attrs", {}).get("id") == CARD_ID for n in p)]


def test_theCardIsFoundById_keepsItsNames_andLosesTheDtcState():
    html = open(_HTML, encoding="utf-8").read()
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    tag = re.search(r'<section[^>]*id="alerts-card"[^>]*>', html)
    assert tag is not None, "no #alerts-card section"
    assert 'aria-label="Alerts"' in tag.group(0)
    assert 'data-page-name="ALERTS"' in tag.group(0)
    assert "data-state" not in tag.group(0)
    assert 'data-state="dtc"' not in html


def test_theCarouselFindsTheCardByIdAlone():
    js = open(_JS, encoding="utf-8").read()
    assert "dtcCardIndex" not in js
    assert re.search(r'getAttribute\("id"\) === "alerts-card"', js)
    assert 'data-page-name") === "ALERTS"' not in js, "the icon re-keys by id too (US-898-b1)"


@_NODE_ONLY
def test_dom_rowsAreTheEntriesInTheirOrder():
    payload = _fixture("mixed-live-and-stored")
    _, surface, _ = _cardDom(payload)
    rows = _rowPaths(surface)
    assert [p[-1]["attrs"]["data-id"] for p in rows] == [e["id"] for e in payload["entries"]]


@_NODE_ONLY
def test_dom_headerAndRowTexts():
    _, surface, _ = _cardDom(_fixture("two-stored-codes-real"))
    head = surface.pathsByClass("warn-count")
    assert [_textOf(p[-1]) for p in head] == ["2 ACTIVE"]
    rows = _rowPaths(surface)
    texts = [_textOf(p[-1]) for p in rows]
    assert P0400_TITLE in texts[0] and P0400_SENTENCE in texts[0] and "41 days ago" in texts[0]
    assert P0443_TITLE in texts[1] and P0443_SENTENCE in texts[1]


@_NODE_ONLY
def test_dom_staleRow_showsLastValueInFahrenheitAndTheClause():
    _, surface, _ = _cardDom(_fixture("stop-live-stale"))
    text = _textOf(_rowPaths(surface)[0][-1])
    assert "234 °F" in text and "last reading 12 s ago" in text


@_NODE_ONLY
def test_dom_overRevRow_containsSampled():
    _, surface, _ = _cardDom(_fixture("watch-over-rev"))
    assert "(sampled)" in _textOf(_rowPaths(surface)[0][-1])


@_NODE_ONLY
def test_dom_codeRowsAreButtons_engineRowsAreNot():
    _, surface, _ = _cardDom(_fixture("mixed-live-and-stored"))
    rows = _rowPaths(surface)
    assert [p[-1]["tag"].lower() for p in rows] == ["div", "button", "button"]
    assert all("tile" not in _classes(p[-1]) for p in rows), "the fact-ceiling test: never .tile"


@_NODE_ONLY
def test_dom_clearedRow_isMarkedInactive():
    _, surface, _ = _cardDom(_fixture("stop-live-cleared"))
    row = _rowPaths(surface)[0][-1]
    assert row["attrs"]["data-active"] == "false"
    assert "cleared" in _textOf(row)


@_NODE_ONLY
def test_dom_whileTheFirstReadIsPending_theCardIsLoading():
    path, _, _ = _cardDom(None, steps=[{"flush": 1}])
    assert "LOADING" in _textOf(path[-1])


@_NODE_ONLY
def test_dom_afterTheGrace_noPayloadIsDashDashAndNoWarningsData():
    path, surface, _ = _cardDom(None, steps=[{"flush": 2}, {"advanceMs": 7000}, {"flush": 4}])
    text = _textOf(path[-1])
    assert "LOADING" not in text
    assert [_textOf(p[-1]) for p in surface.pathsByClass("warn-count")] == ["--"]
    assert "no warnings data" in text


@_NODE_ONLY
def test_dom_theTickReadsNoStatesDtc_andNoRibbonPaints():
    """MOVED PIN (US-899-a2): the tick's states/dtc feed and the ribbon are
    deleted (Iris G-7) -- with no code detail open, a stored code costs no
    /dtc read, while /gear is still read every tick."""
    dtc = {
        "ts": NOW, "newSinceTs": None, "mil": True,
        "source": {"dtc": {"available": True}},
        "codes": [{"code": "P0443", "status": "stored", "severity": "minor",
                   "short": "EVAP purge", "logged": True, "syncAcked": True}],
    }
    routes = _routes(_fixture("two-stored-codes-real"))
    routes["/dtc"] = dtc
    dom = rh.runDashboard(routes=routes, steps=[{"flush": 4}], viewport=PANEL, nowMs=NOW_MS)
    dtcReads = [f for f in dom["fetches"] if f["url"] == "/dtc"]
    gearReads = [f for f in dom["fetches"] if f["url"] == "/gear"]
    assert gearReads, "the tick did not run -- this test is vacuous"
    assert dtcReads == [], len(dtcReads)
    surface = rh.dashboardSurface(dom["tree"], viewport=PANEL)
    assert surface.pathById("dtc-ribbon") is None


@_NODE_ONLY
def test_dom_batteryRed_redDrivingTileBesideAnAmberWatchIcon():
    """898-8: the Driving tile reads its BAND (red) and the icon reads the
    provider's TIER (watch, amber) -- both correct at once, never reconciled."""
    with open(os.path.join(_HERE, "fixtures", "states", "driving", "coolant-red.json"),
              encoding="utf-8") as fh:
        driving = json.load(fh)
    obdLive = driving["obd-live"]
    obdLive["params"]["COOLANT_TEMP"].update(
        value=90, band={"band": "green", "since": driving["now"], "reason": "coolant green"},
    )
    obdLive["params"]["BATTERY_V"].update(
        value=11.8, band={"band": "red", "since": driving["now"], "reason": "battery low"},
    )
    nowMs = int(datetime.fromisoformat(driving["now"].replace("Z", "+00:00")).timestamp() * 1000)
    routes = _routes(_fixture("watch-battery-low"))
    routes.update({"/obd-live": obdLive, "/gear": driving["gear"]})
    dom = rh.runDashboard(routes=routes, viewport=PANEL, nowMs=nowMs)
    surface = rh.dashboardSurface(dom["tree"], viewport=PANEL)
    battery = [p for p in surface.pathsByClass("drv-reading")
               if p[-1]["attrs"].get("data-pid") == "BATTERY_V"]
    assert len(battery) == 1 and battery[0][-1]["attrs"]["data-band"] == "red"
    icon = surface.pathById("glyph-warnings")
    assert icon is not None and icon[-1]["attrs"]["data-state"] == "watch"
    color = surface.winningDeclaration(icon, "color")
    assert color is not None and color[0] == "var(--amber-warn)", color


@_NODE_ONLY
def test_dom_theCardReadsNoStatesDtc():
    """G-7: with /alerts present and /dtc absent, the card still renders rows
    -- it never needed states/dtc."""
    _, surface, _ = _cardDom(_fixture("two-stored-codes-real"))
    assert len(_rowPaths(surface)) == 2


# --- US-898-b2 DOM: 898-2, 898-3, 898-5 ---------------------------------------


def _cardElementTexts(surface: rh.Surface) -> list[str]:
    """The text of EVERY element under #alerts-card (the card itself included)."""
    return [
        _textOf(p[-1]) for p in surface.paths()
        if any(n.get("attrs", {}).get("id") == CARD_ID for n in p)
    ]


def _textsByClass(surface: rh.Surface, cls: str) -> list[str]:
    return [_textOf(p[-1]) for p in surface.pathsByClass(cls)]


@_NODE_ONLY
def test_dom_checkedClean_noneNoWarningsAndTheNotBuiltLine():
    """The browser harness runs in the machine's zone, so the hour is free here;
    the view tests pin it per zone."""
    _, surface, _ = _cardDom(_fixture("checked-clean"))
    assert _textsByClass(surface, "warn-count") == ["NONE"]
    [meta] = _textsByClass(surface, "warn-meta")
    assert re.fullmatch(r"codes read \d{1,2}:02", meta), meta
    assert _textsByClass(surface, "warn-quiet-head") == ["NO WARNINGS"]
    lines = _textsByClass(surface, "warn-quiet-line")
    assert len(lines) == 2 and lines[1] == NOT_BUILT
    assert re.fullmatch(r"Codes read at \d{1,2}:02\. Engine checks clear\.", lines[0]), lines[0]
    assert _rowPaths(surface) == [] and surface.pathsByClass("warn-more") == []


@_NODE_ONLY
def test_dom_898_2_notChecked_noElementClaimsAnything():
    _, surface, _ = _cardDom(_fixture("not-checked"))
    texts = _cardElementTexts(surface)
    for text in texts:
        for word in ("NONE", "NO WARNINGS", "clear"):
            assert word not in text, (word, text)
    assert _textsByClass(surface, "warn-count") == ["NOT CHECKED"]
    # Raw text nodes: _textOf strips each child, which would eat the space.
    [head] = surface.pathsByClass("warn-quiet-head")
    raw = "".join(c["children"][0]["text"] for c in head[-1]["children"])
    assert raw == "? NOT CHECKED YET"
    assert surface.pathsByClass("warn-meta") == []
    count = surface.pathsByClass("warn-count")[0]
    assert surface.winningDeclaration(count, "color")[0] == "var(--amber-warn)"


@_NODE_ONLY
def test_dom_898_3_systemDataNotAssessed_neverPairedWithClear():
    _, surface, _ = _cardDom(_fixture("system-data-not-assessed"))
    for text in _cardElementTexts(surface):
        if "clear" in text:
            assert "system" not in text and "data" not in text, text
            assert "System" not in text, text
    assert NOT_BUILT in _textsByClass(surface, "warn-quiet-line")
    assert "Engine checks clear." not in " ".join(_cardElementTexts(surface))


@_NODE_ONLY
def test_dom_898_5_sevenEntries_allRendered_cueThreeMoreBelow_rowOneStop():
    payload = _fixture("seven-entries-scroll")
    _, surface, _ = _cardDom(payload)
    rows = _rowPaths(surface)
    assert len(rows) == 7, "no silent clip: every entry is in the DOM"
    assert [p[-1]["attrs"]["data-id"] for p in rows] == [e["id"] for e in payload["entries"]]
    assert rows[0][-1]["attrs"]["data-tier"] == "stop"
    cue = surface.pathsByClass("warn-more")
    assert len(cue) == 1 and surface.rendered(cue[0])
    assert _textOf(cue[0][-1]) == "↓ 3 more below"


@_NODE_ONLY
def test_dom_fewRows_cueLineIsLaidOutButEmpty():
    _, surface, _ = _cardDom(_fixture("two-stored-codes-real"))
    cue = surface.pathsByClass("warn-more")
    assert len(cue) == 1 and _textOf(cue[0][-1]) == ""


@_NODE_ONLY
def test_dom_theListScrollsWithAVisibleTokenScrollbar():
    _, surface, _ = _cardDom(_fixture("seven-entries-scroll"))
    path = surface.pathsByClass("warn-list")[0]
    assert surface.winningDeclaration(path, "overflow-y")[0] in ("auto", "scroll")
    assert surface.winningDeclaration(path, "scrollbar-width")[0] == "thin"
    assert surface.winningDeclaration(path, "scrollbar-color")[0] == (
        "var(--warn-scroll-thumb) var(--warn-scroll-track)"
    )
    assert surface.winningDeclaration(path, "min-height")[0] == "0"
    row = _rowPaths(surface)[0]
    assert surface.winningDeclaration(row, "flex")[0] == "0 0 auto", "a row never shrinks"


@_NODE_ONLY
@pytest.mark.parametrize(
    "name,cls,face",
    [
        ("not-checked", "warn-quiet-mark", "var(--font-mono)"),
        ("not-checked", "warn-quiet-word", "var(--font-display)"),
        ("seven-entries-scroll", "warn-more", "var(--font-mono)"),
    ],
)
def test_dom_theQuestionMarkAndTheCueAreMono_theWordsMichroma(name: str, cls: str, face: str):
    _, surface, _ = _cardDom(_fixture(name))
    path = surface.pathsByClass(cls)[0]
    assert surface.winningDeclaration(path, "font-family")[0] == face


# ---------------------------------------------------------------------------
# 3. CSS -- chips, rows, sentences.
# ---------------------------------------------------------------------------


def _rgb(hexColor: str) -> tuple[int, int, int]:
    h = hexColor.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _luminance(hexColor: str) -> float:
    def _lin(channel: int) -> float:
        v = channel / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = _rgb(hexColor)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _token(name: str) -> str:
    match = re.search(rf"--{re.escape(name)}:\s*(#[0-9A-Fa-f]{{3,6}})", readCss(TOKENS_CSS))
    assert match is not None, f"--{name} is not a hex token in tokens.css"
    return match.group(1)


def _colour(value: str) -> str:
    var = re.fullmatch(r"var\(--([\w-]+)\)", value.strip())
    return _token(var.group(1)) if var else value.strip()


# tier -> (background token, ink) -- Atlas 2026-10-16, Iris brief.
CHIP_LOOK = {
    "stop": ("var(--critical-red)", "#fff"),
    "watch": ("var(--amber-warn)", "var(--bg)"),
    "minor": ("var(--green-ok)", "var(--bg)"),
    "unrated": ("var(--neutral-chip-bg)", "var(--text-primary)"),
}
CHIP_FIXTURE = {
    "stop": "stop-live-overheat",
    "watch": "watch-battery-low",
    "minor": "two-stored-codes-real",
    "unrated": "unrated-code",
}


def _chipPath(surface: rh.Surface, tier: str) -> list[dict[str, Any]]:
    for path in surface.pathsByClass("warn-chip"):
        if path[-1]["attrs"].get("data-tier") == tier:
            return path
    raise AssertionError(f"no {tier} chip rendered")


@_NODE_ONLY
@pytest.mark.parametrize("tier", sorted(CHIP_LOOK))
def test_chipColoursAndInks_perTier_meetAA(tier: str):
    """898-9: #fff on red, var(--bg) on amber and green, --text-primary on
    the neutral chip -- each at least AA (4.5:1)."""
    _, surface, _ = _cardDom(_fixture(CHIP_FIXTURE[tier]))
    path = _chipPath(surface, tier)
    background = surface.winningDeclaration(path, "background")
    color = surface.winningDeclaration(path, "color")
    assert background is not None and color is not None, tier
    assert (background[0], color[0]) == CHIP_LOOK[tier]
    assert _contrast(_colour(background[0]), _colour(color[0])) >= 4.5


def _warningsRules() -> list[rh.Rule]:
    return [r for r in rh.parseCss(readCss(DASHBOARD_CSS)) if "#alerts-card" in r.selector]


def _rule(selector: str) -> rh.Rule:
    for rule in _warningsRules():
        if rule.selector.strip() == selector:
            return rule
    raise AssertionError(f"no rule {selector}")


def test_rowsAreAtLeast48px_throughAScopedProperty():
    block = _rule("#alerts-card").declarations
    assert re.search(r"--warn-row-min:\s*48px", block)
    assert rh.declarationOf(_rule("#alerts-card .warn-row").declarations, "min-height") == (
        "var(--warn-row-min)", False,
    )


@_NODE_ONLY
def test_sentencesAreNeverStyledAsControls_engineRowsNeither():
    """US-758 (898-7): no border, fill or pointer on a sentence or an ENGINE row;
    CODE rows are real controls."""
    _, surface, _ = _cardDom(_fixture("mixed-live-and-stored"))
    for path in surface.pathsByClass("warn-sentence"):
        for prop in ("border", "background", "cursor"):
            won = surface.winningDeclaration(path, prop)
            assert won is None or won[0] in ("none", "0", "transparent", "default"), (prop, won)
    rows = _rowPaths(surface)
    engine = surface.winningDeclaration(rows[0], "cursor")
    code = surface.winningDeclaration(rows[1], "cursor")
    assert engine is None or engine[0] != "pointer", engine
    assert code is not None and code[0] == "pointer", code


def test_warningsCssIsTokensOnly_noHexOrPxOutsideTheScopedProperties():
    """G-5: new geometry lives in custom properties on #alerts-card; the one
    literal colour is the STOP ink #fff (the existing copy colour)."""
    for rule in _warningsRules():
        for decl in rule.declarations.split(";"):
            decl = decl.strip()
            if not decl or decl.startswith("--"):
                continue
            prop, _, value = decl.partition(":")
            hexes = re.findall(r"#[0-9A-Fa-f]{3,6}\b", value)
            assert hexes in ([], ["#fff"]), (rule.selector, decl)
            if hexes:
                assert 'data-tier="stop"' in rule.selector and prop.strip() == "color"
            assert not re.search(r"\b\d+(\.\d+)?px\b", value), (rule.selector, decl)


def test_onlyTheCountAndTheChipsAreMichroma():
    """Michroma carries UPPER-CASE words and digits only (spec s3): the count
    and the chips. Titles, values, sentences and ages stay --font-mono."""
    display = {r.selector.strip() for r in _warningsRules() if "var(--font-display)" in r.declarations}
    assert display == {
        "#alerts-card .warn-count", "#alerts-card .warn-chip", "#alerts-card .warn-quiet-word",
    }
    for selector in display:
        block = _rule(selector).declarations
        assert rh.declarationOf(block, "font-weight") == ("400", False), selector
        assert rh.declarationOf(block, "font-synthesis") == ("none", False), selector


def test_everyWarningsAnimationIsAbsent():
    """This story animates nothing (the pulse is the icon's and the takeover's)."""
    for rule in _warningsRules():
        assert rh.declarationOf(rule.declarations, "animation") is None, rule.selector


# ---------------------------------------------------------------------------
# 4. Grep gates.
# ---------------------------------------------------------------------------


def _js() -> str:
    return open(_JS, encoding="utf-8").read()


def _body(name: str) -> str:
    return rh._fnBody(_js(), name)


def test_theWarningsFunctionsExist():
    for name in WARNINGS_FUNCTIONS:
        assert _body(name), name


def test_theWarningsRenderNeverSorts_andComparesNoTier():
    """G-6 / 898-4: the order and the tier are the provider's."""
    for name in WARNINGS_FUNCTIONS:
        body = _body(name)
        assert ".sort(" not in body, name
        assert not re.search(r"tier\s*[!=]==?|[!=]==?\s*[\w.]*tier\b", body), name
        assert not re.search(r"RANK", body), name


def test_theWarningsRenderCarriesNoTierCopy():
    """G-2 in this story's scope: the NEW render functions compose no words."""
    for name in WARNINGS_FUNCTIONS:
        body = _body(name)
        for literal in TIER_COPY:
            assert literal not in body, (name, literal)


@pytest.mark.parametrize(
    "gone",
    ["alertsCardView", "renderAlertsCard", "DTC_LIST_RANK", "dtcListSorted", "dtcRow",
     "dtcNotReadTile", "lastKnownDtcView", "renderLastKnownDtc"],
)
def test_theDtcDrivenCardBodyIsRetired(gone: str):
    assert not re.search(rf"\b{gone}\b", _js()), gone


# MOVED PIN (US-899-a2): DTC_TIER is deleted (its directives with it); only
# the code detail stays.
@pytest.mark.parametrize("kept", ["codeDetailView"])
def test_theDetailsTablesStay(kept: str):
    """US-898-c owns this."""
    assert re.search(rf"\b{kept}\b", _js()), kept


def test_noDataViewsCarryNoDtcEntry():
    body = re.search(r"var NO_DATA_VIEWS = \{(.*?)\};", _js(), re.DOTALL)
    assert body is not None
    assert not re.search(r"^\s*dtc\s*:", body.group(1), re.MULTILINE)


def test_theTickReadsStatesDtcOnlyForAnOpenDetail():
    """MOVED PIN (US-899-a2, Iris G-7): the one states/dtc read left on the
    tick is the open code detail's refresh."""
    tick = _body("tick")
    reads = re.findall(r'^.*stateOnce\("dtc"\).*$', tick, re.MULTILINE)
    assert reads == ['        if (detailEntry) refreshCodeDetail(await stateOnce("dtc"));'], reads
    assert "updateDtcSurfaces" not in _js()


if __name__ == "__main__":
    for _name in sorted(SCENARIOS):
        with open(_fixturePath(_name), "w", encoding="utf-8", newline="\n") as _fh:
            json.dump(buildFixture(_name), _fh, indent=2, ensure_ascii=False)
            _fh.write("\n")
        print("wrote", _fixturePath(_name))
