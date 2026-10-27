################################################################################
# File Name: test_system_page_data_row.py
# Purpose/Description: US-894-c (spec specs/v030-system-page-design.md s4.0,
#   s4.3, s4.6, s7, AC 7 / 13 / 14a; Atlas A4, P7, P9; Iris I3, I4, W3) -- the
#   System page's DATA row: capture and sync on one row, and its parked detail.
#
#   What is pinned here:
#     - the DATA fixtures in tests/ui/fixtures/states/system/ are exactly what
#       _generate.py builds from the REAL builders (never hand-typed);
#     - the five validationCriteria and the three A4 cases (AC 14a);
#     - `stalled` IF AND ONLY IF a `capture` verdict member exists, swept over
#       every capture state x member presence;
#     - the sync date rule in LOCAL time (same day / yesterday / older), the
#       rows-waiting words (singular, `+`, null), away-from-home;
#     - the colour rule (s4.0, AC 7): amber on the DATA row IFF the member;
#     - the parked DATA detail and the neutral sync glyph (I4);
#     - one cross-language guard for the JS copy of capture-health's
#       vocabulary, and the retirement of the three tiles and sync.rows /
#       sync.pending.
#
#   Skipped when node is not on PATH -- the source and fixture checks always
#   run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-c System page DATA row.
# 2026-10-24    | Rex (US-869-c)| the `sensor` member on the DATA row and detail;
#               |              | per-part members + data-feed; the guard extended.
# ================================================================================
################################################################################

"""US-894-c tests: the System page's DATA row (capture + sync) and its detail."""

from __future__ import annotations

import copy
import importlib.util
import inspect
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from pi.obdii import capture_health as ch  # noqa: E402
from pi.splash import system_status_emitter as sse  # noqa: E402
from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_ZONE = "America/Chicago"
_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")

GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
SECONDARY = "var(--text-secondary)"
TERTIARY = "var(--text-tertiary)"
MIDDLE_DOT = "·"

_NOW = "2026-10-22T23:10:00Z"  # the fixtures' `now`: 6:10 PM CDT, Oct 22
_NOW_MS = 1761174600000

# This story's fixtures (spec s7 + the A4 cases). The A4 "all feeds ok" case
# is US-894-b's all-ok-driving, read here rather than duplicated.
_DATA_FIXTURES = {
    "capture-stalled", "away-from-home", "rows-not-counted",
    "capture-stalled-ecu-silent", "capture-never-written-ecu-up",
    "capture-ups-feed-stalled", "sync-days-old", "sync-stale-glyph",
}


# US-869-c: the sensor-member fixtures (one UPS-row fixture gains a feed fault).
_SENSOR_FIXTURES = {
    "imu-faulted", "imu-ups-faulted", "imu-faulted-ecu-down", "ups-gauge-unreadable",
}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _generator():
    spec = importlib.util.spec_from_file_location(
        "system_fixture_generator_c", os.path.join(_FIXTURE_DIR, "_generate.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _payloads(name: str) -> tuple[dict, dict | None]:
    fx = _fixture(name)["payloads"]
    return fx["system-status"], fx.get("capture-health")


def _map(fn: str, argLists: list[list[Any]]) -> list[Any]:
    """Batch-evaluate a carousel.js export in the fixtures' zone."""
    proc = subprocess.run(
        [_NODE, _PROBE, "--map", fn],
        input=json.dumps(argLists),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, TZ=_ZONE),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _call(fn: str, *args: Any) -> Any:
    return _map(fn, [list(args)])[0]


def _row(name: str) -> dict:
    status, capture = _payloads(name)
    return _call("dataRowView", status, capture)


def _members(status: dict) -> list[str]:
    return [m["key"] for m in status["verdict"]["members"]]


# ---------------------------------------------------------------------------
# Fixtures: generated from the real builders, never hand-typed (Atlas L7).
# ---------------------------------------------------------------------------


def test_theDataFixturesAreAllOnDisk_andTheGeneratorBuildsThem():
    names = {f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json")}
    assert _DATA_FIXTURES <= names
    assert _DATA_FIXTURES <= set(_generator().fixtureNames())


@pytest.mark.parametrize("name", sorted(_DATA_FIXTURES))
def test_everyDataFixtureOnDiskIsWhatTheGeneratorBuilds(name: str):
    gen = _generator()
    assert _read(os.path.join(_FIXTURE_DIR, f"{name}.json")) == gen.render(
        gen.buildFixture(name)
    ), f"{name}.json is stale -- re-run tests/ui/fixtures/states/system/_generate.py"


@pytest.mark.parametrize("name", sorted(_DATA_FIXTURES))
def test_everyDataFixtureIsTheBuildersOutputForItsStoredInputs(name: str):
    """Rebuilt from the fixture's OWN stored inputs, independently of the
    script: system-status from buildSystemStatusState, capture-health as
    makeCaptureHealthEmitter.emit composes it."""
    fx = _fixture(name)
    inputs = fx["inputs"]
    capIn = inputs["capture-health"]
    capture = ch.buildCaptureHealthState(
        lastRowSecondsAgo=capIn["lastRowSecondsAgo"],
        freshnessReason=capIn["freshnessReason"],
        powerSource=capIn["powerSource"],
        stallSeconds=capIn["stallSeconds"],
        nowIso=fx["now"],
    )
    capture["feeds"] = ch.buildCaptureFeedsState(
        feedSamples={k: tuple(v) for k, v in capIn["feedSamples"].items()},
        powerSource=capIn["powerSource"],
        stallSeconds=capIn["stallSeconds"],
        feedFaults=capIn.get("feedFaults"),  # US-869-c
    )
    assert capture == fx["payloads"]["capture-health"]
    assert buildSystemStatusState(**inputs["system-status"], captureHealth=capture) == (
        fx["payloads"]["system-status"]
    )
    assert set(fx) == {"description", "now", "zone", "inputs", "payloads"}
    assert fx["zone"] == _ZONE


def test_theRetiredSyncKeysAreInNoFixture():
    for name in _generator().fixtureNames():
        fx = _fixture(name)
        sync = fx["payloads"]["system-status"]["sync"]
        assert "rows" not in sync and "pending" not in sync, name
        assert not {"syncRows", "syncPending"} & set(fx["inputs"]["system-status"]), name


# ---------------------------------------------------------------------------
# validationCriteria + the three A4 cases (spec AC 14a).
# ---------------------------------------------------------------------------


@_needsNode
def test_validation_rowsNotCounted_thePlusSitsOnTheNumber_andTheDetailNamesTheTables():
    status, capture = _payloads("rows-not-counted")
    row = _call("dataRowView", status, capture)
    detail = _call("dataDetailView", status, capture)

    assert "12,345+ rows waiting" in row["sentence"]
    assert detail["notCounted"] == "not counted: profiles, startup_log, vehicle_info"
    assert detail["rowsWaiting"] == "12,345"  # never folded in: the count alone


@_needsNode
def test_validation_lastOkTsTwoDaysAgo_isTheDate_neverABareTime():
    when = _call("syncWhenText", "2026-10-17T18:00:00Z", "2026-10-19T18:00:00Z")
    assert when == "synced Oct 17"
    assert not re.search(r"\d:\d\d", when)


@_needsNode
def test_validation_neverWrittenEcuUp_isNotStalled_zeroMembers_noEcuWords():
    status, _capture = _payloads("capture-never-written-ecu-up")
    row = _row("capture-never-written-ecu-up")

    assert status["verdict"] == {"issueCount": 0, "members": []}
    assert row["word"] == "no rows" and row["word"] != "stalled"
    assert row["look"] == "secondary"
    assert row["sentence"].startswith("no row logged this session")
    assert "ECU" not in row["sentence"]


@_needsNode
def test_validation_upsFeedStalled_topLevelOk_isStalled_oneMember_amberOnTheDataRow():
    status, capture = _payloads("capture-ups-feed-stalled")
    row = _row("capture-ups-feed-stalled")

    assert capture["state"] == "ok"
    assert capture["feeds"]["ups"]["state"] == "stalled"
    assert status["verdict"] == {
        "issueCount": 1, "members": [{"key": "capture", "reason": "UPS feed stalled."}],
    }
    assert (row["word"], row["look"], row["level"]) == ("stalled", "amber", "amber")
    # MOVED PIN (US-869-c): each part names its own member and feeds.
    assert row["parts"][0] == {
        "text": "UPS feed stalled.", "level": "amber", "member": "capture", "feed": "ups",
    }


@_needsNode
def test_validation_lastOkTsYesterday_isYesterday_withNoTime():
    row = _row("sync-stale-glyph")

    assert row["value"] == "recording " + MIDDLE_DOT + " synced yesterday"
    assert not re.search(r"\d:\d\d", row["value"])


@_needsNode
def test_a4_allFeedsOk_isRecording_zeroMembers():
    status, _ = _payloads("all-ok-driving")
    row = _row("all-ok-driving")

    assert status["verdict"]["issueCount"] == 0
    assert (row["word"], row["look"]) == ("recording", "ok")
    assert row["sentence"] == "all 4 feeds writing " + MIDDLE_DOT + " 0 rows waiting"


# ---------------------------------------------------------------------------
# The other DATA fixtures (spec s7).
# ---------------------------------------------------------------------------


@_needsNode
def test_fixture_captureStalled_isTheMemberReasonVerbatim():
    status, _ = _payloads("capture-stalled")
    row = _row("capture-stalled")
    reason = status["verdict"]["members"][0]["reason"]

    assert _members(status) == ["capture"]
    assert row["word"] == "stalled"
    assert row["sentence"] == reason + " " + MIDDLE_DOT + " 482 rows waiting"


@_needsNode
def test_fixture_awayFromHome_isNeutralAndUncounted():
    status, _ = _payloads("away-from-home")
    row = _row("away-from-home")

    assert status["verdict"]["issueCount"] == 0
    assert row["level"] == "secondary"
    assert "away from home " + MIDDLE_DOT + " 3,880 rows waiting" in row["sentence"]
    assert all(p["level"] == "secondary" for p in row["parts"])


@_needsNode
def test_fixture_captureStalledEcuSilent_isStopped_namesTheEcu_uncounted():
    status, _ = _payloads("capture-stalled-ecu-silent")
    row = _row("capture-stalled-ecu-silent")

    assert status["verdict"]["issueCount"] == 0
    assert (row["word"], row["look"]) == ("stopped", "secondary")
    assert row["sentence"].startswith("ECU not answering " + MIDDLE_DOT)


@_needsNode
def test_fixture_syncDaysOld_readsOct12_neverABareTime():
    row = _row("sync-days-old")

    assert row["value"].endswith("synced Oct 12")
    assert "91,234 rows waiting" in row["sentence"]


@_needsNode
def test_fixture_syncStaleGlyph_theGlyphIsNeutral_noMember():
    status, capture = _payloads("sync-stale-glyph")
    view = _call("systemStatusView", status, capture)

    assert status["sync"]["stale"] is True
    assert status["verdict"]["issueCount"] == 0
    assert view["glyphs"]["sync"] == "neutral"


# ---------------------------------------------------------------------------
# A4: `stalled` IF AND ONLY IF a capture member -- swept.
# ---------------------------------------------------------------------------

_CAPTURE_SHAPES = [
    None,
    {"state": "ok", "lastRowSecondsAgo": 0.4, "reason": None},
    {"state": "idle", "lastRowSecondsAgo": None, "reason": None},
    {"state": "unknown", "lastRowSecondsAgo": None, "reason": "logger_absent"},
    {"state": "stalled", "lastRowSecondsAgo": None, "reason": "never_written"},
    {"state": "stalled", "lastRowSecondsAgo": 300.0, "reason": "stalled"},
]
_ECU_STATES = (sse.LINK_UP, sse.LINK_CONNECTING, sse.LINK_RETRYING, sse.LINK_DOWN, None)


def _sweepStatus(ecu: str | None, member: bool) -> dict:
    layer = {"state": "up", "ts": _NOW, "lastOkTs": None}
    status = buildSystemStatusState(
        syncLastOkTs=_NOW, syncStale=False, powerSource="external",
        driveState="idle", driveId=None, nowIso=_NOW,
        link={"bt": dict(layer), "adapter": dict(layer),
              "ecu": {"state": ecu, "ts": _NOW if ecu else None, "lastOkTs": None}},
    )
    if member:
        status["verdict"]["members"].append({"key": "capture", "reason": "OBD feed stalled."})
        status["verdict"]["issueCount"] = 1
    return status


@_needsNode
def test_stalledIffMember_sweptOverEveryCaptureStateEcuStateAndMember():
    cases = list(itertools.product(range(len(_CAPTURE_SHAPES)), _ECU_STATES, (False, True)))
    args = [[_sweepStatus(ecu, member), _CAPTURE_SHAPES[i]] for i, ecu, member in cases]
    rows = _map("dataRowView", args)
    for (i, ecu, member), row in zip(cases, rows, strict=True):
        capture = _CAPTURE_SHAPES[i]
        label = (capture and capture["state"], capture and capture["reason"], ecu, member)
        assert (row["word"] == "stalled") is member, label
        assert (row["look"] == "amber") is member, label
        assert (row["level"] == "amber") is member, label
        amberParts = [p for p in row["parts"] if p["level"] == "amber"]
        assert len(amberParts) == (1 if member else 0), label
        silent = ecu in (sse.LINK_DOWN, sse.LINK_RETRYING, sse.LINK_CONNECTING)
        stall = capture is not None and capture["state"] == "stalled"
        if not member and stall:
            assert row["word"] in ("no rows", "stopped"), label
            assert ("ECU not answering" in row["sentence"]) is silent, label
        if not stall or member:
            assert "ECU not answering" not in row["sentence"], label


# ---------------------------------------------------------------------------
# The sync date rule (I3): local time, today / yesterday / older.
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(("lastOk", "expected"), [
    # Same LOCAL day though the UTC day differs: 12:30 AM CDT on the 22nd.
    ("2026-10-22T05:30:00Z", "synced 12:30 AM"),
    ("2026-10-22T22:55:12Z", "synced 5:55 PM"),
    # 11:30 PM CDT on the 21st: the local day before, by 1 hour of UTC.
    ("2026-10-22T04:30:00Z", "synced yesterday"),
    ("2026-10-21T05:10:00Z", "synced yesterday"),
    ("2026-10-21T04:59:00Z", "synced Oct 20"),
    ("2026-10-03T12:00:00Z", "synced Oct 03"),
    ("2025-10-22T12:00:00Z", "synced Oct 22"),
    (None, "no sync on record"),
    ("not-a-time", "synced --"),
    ("2026-10-22T05:30:00", "synced --"),  # zoneless: no instant
])
def test_syncWhen_isLocalTime_andABareTimeIsOnlyEverToday(lastOk, expected):
    assert _call("syncWhenText", lastOk, _NOW) == expected


@_needsNode
def test_syncWhen_withNoUsableNow_neverPrintsABareTime():
    for now in (None, "garbage"):
        assert _call("syncWhenText", "2026-10-22T22:55:12Z", now) == "synced Oct 22"


@_needsNode
def test_syncWhen_neverPrintsTheEpochOrARawIso():
    for junk in ("0", "412", "", "2026-10-22T22:55:12Z extra"):
        when = _call("syncWhenText", junk, _NOW)
        assert "1970" not in when and "T" not in when.replace("synced", ""), when


# ---------------------------------------------------------------------------
# The sentence words (s4.3).
# ---------------------------------------------------------------------------


def _syncStatus(**sync: Any) -> dict:
    block = {"lastOkTs": _NOW, "stale": False, "rowsWaiting": 0,
             "edrRowsWaiting": 0, "notCounted": []}
    block.update(sync)
    return {"sync": block, "wifi": {"home": True},
            "verdict": {"issueCount": 0, "members": []}, "ts": _NOW}


@_needsNode
@pytest.mark.parametrize(("sync", "words", "absent"), [
    ({"rowsWaiting": 1}, ["1 row waiting"], ["rows waiting"]),
    ({"rowsWaiting": 1, "notCounted": ["profiles"]}, ["1+ rows waiting"], ["1 row waiting"]),
    ({"rowsWaiting": 12345, "notCounted": ["a", "b"]}, ["12,345+ rows waiting"], []),
    ({"rowsWaiting": 12345, "notCounted": []}, ["12,345 rows waiting"], ["+"]),
    ({"rowsWaiting": None}, ["rows not read"], ["0 rows"]),
    ({"edrRowsWaiting": 1}, ["1 event row"], ["event rows"]),
    ({"edrRowsWaiting": 1771}, ["1,771 event rows"], []),
    ({"edrRowsWaiting": 0}, [], ["event row"]),
    ({"edrRowsWaiting": None}, [], ["event row"]),
])
def test_rowsWords(sync, words, absent):
    sentence = _call("dataRowView", _syncStatus(**sync), None)["sentence"]
    for w in words:
        assert w in sentence, sentence
    for w in absent:
        assert w not in sentence, sentence


@_needsNode
@pytest.mark.parametrize(("home", "away"), [(False, True), (True, False), (None, False)])
def test_awayFromHome_onlyWhenHomeIsFalse_neverGuessed(home, away):
    status = _syncStatus()
    status["wifi"]["home"] = home
    sentence = _call("dataRowView", status, None)["sentence"]
    assert ("away from home" in sentence) is away


@_needsNode
def test_stopped_lastRowAge_isTheHistoryAgeVocabulary():
    status = _sweepStatus(sse.LINK_UP, False)
    for secs, words in ((30.0, "just now"), (300.0, "5 min ago"), (7300.0, "2 h ago"),
                        (90000.0, "1 day ago")):
        row = _call("dataRowView", status,
                    {"state": "stalled", "lastRowSecondsAgo": secs, "reason": "stalled"})
        assert row["sentence"].startswith("last row " + words), (secs, row)
    row = _call("dataRowView", status,
                {"state": "stalled", "lastRowSecondsAgo": None, "reason": "stalled"})
    assert row["word"] == "stopped"
    assert row["sentence"].startswith("rows not read"), row  # no age, nothing printed


# ---------------------------------------------------------------------------
# The DATA detail (s4.6).
# ---------------------------------------------------------------------------


@_needsNode
def test_detail_feeds_inOrder_withWordsAndFreshnessAges():
    status, capture = _payloads("capture-ups-feed-stalled")
    detail = _call("dataDetailView", status, capture)

    assert detail["head"] == "DATA"
    assert [(f["label"], f["state"], f["look"], f["age"]) for f in detail["feeds"]] == [
        ("OBD", "writing", "ok", "0 s ago"),
        ("LIGHT", "writing", "ok", "0 s ago"),
        ("IMU", "writing", "ok", "0 s ago"),
        ("UPS", "stalled", "amber", "140 s ago"),  # the member's amber on its feed
    ]
    assert detail["lastStored"] == "Oct 22, 2026 5:55:12 PM"
    assert detail["atHome"] == "yes"


@_needsNode
def test_detail_aStalledFeedWithNoMember_isNeverAmber():
    status, capture = _payloads("capture-stalled-ecu-silent")
    detail = _call("dataDetailView", status, capture)
    obd = detail["feeds"][0]

    assert (obd["state"], obd["look"]) == ("stalled", "secondary")


@_needsNode
def test_detail_noFeeds_everyFeedIsNoData_andAtHomeUnknown():
    detail = _call("dataDetailView", {"sync": None, "wifi": {"home": None}}, None)

    assert [(f["state"], f["age"], f["look"]) for f in detail["feeds"]] == [
        ("--", "--", "tertiary")
    ] * 4
    assert detail["lastStored"] == "no sync on record"
    assert detail["rowsWaiting"] == "rows not read"
    assert detail["eventRows"] == "--"
    assert detail["notCounted"] is None
    assert detail["atHome"] == "unknown"


@_needsNode
def test_freshAge_isTheM7Rule():
    assert _map("freshAgeText", [[0.4], [12.9], [-3], [999], [1000], [None], ["5"]]) == [
        "0 s ago", "12 s ago", "0 s ago", "999 s ago", "999+ s ago", None, None,
    ]


# ---------------------------------------------------------------------------
# The rendered page (DOM): AC 7 on every DATA fixture, the parked detail.
# ---------------------------------------------------------------------------


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _render(name: str, *, parked: bool = False, steps: list[dict] | None = None):
    status, capture = _payloads(name)
    routes: dict[str, Any] = {"/system-status": status}
    if capture is not None:
        routes["/capture-health"] = capture
    if parked:
        routes["/gear"] = _gearParked()
    allSteps = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}] + (steps or [])
    tree = rh.runDashboard(routes=routes, steps=allSteps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _text(node: dict) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _text(child))
    return "".join(out)


def _dataRowPath(surface):
    rows = [p for p in surface.pathsByClass("sys-row")
            if p[-1]["attrs"].get("data-row") == "data"]
    assert len(rows) == 1
    return rows[0]


def _descendants(path: list[dict]):
    stack = [path]
    while stack:
        cur = stack.pop()
        yield cur
        for child in cur[-1].get("children", []):
            if "text" not in child:
                stack.append(cur + [child])


@_needsNode
@pytest.mark.parametrize("name", sorted(_DATA_FIXTURES | {"all-ok-driving"}))
def test_dom_theAmberOnTheDataRowIsExactlyTheCaptureMember(name: str, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(name)
    row = _dataRowPath(surface)
    status, _ = _payloads(name)
    member = "capture" in _members(status)

    ambers = []
    for path in _descendants(row):
        cls = (path[-1].get("attrs", {}).get("class") or "").split()
        if {"sys-row-word", "sys-row-part", "sys-row-tail"} & set(cls):
            colour = surface.winningDeclaration(path, "color")
            if colour and colour[0] == AMBER:
                ambers.append((cls, _text(path[-1])))
    if member:
        assert len(ambers) == 2, ambers  # the word `stalled` + the member's reason
        assert ambers[0][1] == "stalled" or ambers[1][1] == "stalled", ambers
    else:
        assert ambers == [], ambers
    # The whole row reads value + sentence, one line each.
    text = _text(row[-1])
    assert text.startswith("DATA")


@_needsNode
def test_dom_theDataRowPrintsItsValueAndSentence(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("rows-not-counted")
    row = _dataRowPath(surface)
    text = _text(row[-1])

    assert ("recording " + MIDDLE_DOT + " synced 5:55 PM") in text
    assert ("all 4 feeds writing " + MIDDLE_DOT + " 12,345+ rows waiting "
            + MIDDLE_DOT + " 1,771 event rows") in text
    word = [p for p in surface.pathsByClass("sys-row-word")
            if p[-1]["attrs"].get("data-state") == "ok"]
    assert word and surface.winningDeclaration(word[0], "color")[0] == GREEN
    tail = surface.pathsByClass("sys-row-tail")[0]
    assert surface.winningDeclaration(tail, "color")[0] == SECONDARY


@_needsNode
def test_dom_aMemberlessStallIsSecondary_andNoDataIsTertiary(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    stopped = _render("capture-stalled-ecu-silent")
    word = [p for p in stopped.pathsByClass("sys-row-word")][0]
    assert _text(word[-1]) == "stopped"
    assert stopped.winningDeclaration(word, "color")[0] == SECONDARY
    # No capture-health file at all: `--`, tertiary.
    status, _ = _payloads("all-ok-driving")
    tree = rh.runDashboard(routes={"/system-status": status},
                           steps=[{"flush": 4}], viewport=PANEL, nowMs=_NOW_MS)["tree"]
    surface = rh.dashboardSurface(tree, viewport=PANEL)
    word = surface.pathsByClass("sys-row-word")[0]
    assert _text(word[-1]) == "--"
    assert surface.winningDeclaration(word, "color")[0] == TERTIARY


@_needsNode
def test_dom_parked_theDataRowOpensTheDataDetail(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(
        "rows-not-counted", parked=True,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 1}}, {"flush": 1}],
    )
    detail = surface.pathById("sys-detail")
    assert detail[-1]["attrs"].get("hidden") is None, "the DATA detail did not open"
    assert _text(surface.pathById("sys-detail-head")[-1]) == "DATA"
    feeds = surface.pathsByClass("data-feed-row")
    assert [p[-1]["attrs"]["data-feed"] for p in feeds] == ["obd", "light", "imu", "ups"]
    body = _text(surface.pathById("sys-detail-body")[-1])
    for words in ("LAST DATA STORED", "Oct 22, 2026 5:55:12 PM", "ROWS WAITING", "12,345",
                  "EVENT ROWS WAITING", "1,771", "NOT COUNTED",
                  "not counted: profiles, startup_log, vehicle_info", "AT HOME", "yes",
                  "last row 0 s ago"):
        assert words in body, words
    chip = surface.pathById("version-chip")
    assert chip[-1]["attrs"].get("hidden") is not None


@_needsNode
def test_dom_notParked_theDataRowOpensNothing(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(
        "rows-not-counted", parked=False,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 1}}, {"flush": 1}],
    )
    assert surface.pathsByClass("sys-chevron") == []
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is not None


@_needsNode
def test_dom_theDetailsUpsFeedIsAmber_onlyWithTheMember(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(
        "capture-ups-feed-stalled", parked=True,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 1}}, {"flush": 1}],
    )
    states = surface.pathsByClass("data-feed-state")
    colours = [surface.winningDeclaration(p, "color")[0] for p in states]
    assert colours == [GREEN, GREEN, GREEN, AMBER]


@_needsNode
def test_dom_theSyncGlyphIsNeutral_onTheStaleFixture(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("sync-stale-glyph")
    glyph = surface.pathById("glyph-sync")
    assert glyph[-1]["attrs"]["data-state"] == "neutral"
    colour = surface.winningDeclaration(glyph, "color")
    assert colour is None or colour[0] not in (AMBER, GREEN)


# ---------------------------------------------------------------------------
# Cross-language guard + retirement (source checks; always run).
# ---------------------------------------------------------------------------


def _jsLiteral(name: str) -> str:
    source = _read(_CAROUSEL_JS)
    m = re.search(r"var " + name + r" = (.*?);\n", source, flags=re.S)
    assert m, name
    return m.group(1)


def test_theJsCopyOfCaptureHealthsVocabularyIsTheProducers():
    word = _jsLiteral("CAPTURE_STATE_WORD")
    assert set(re.findall(r"(\w+):", word)) == {ch.STATE_OK, ch.STATE_IDLE}
    feedWord = _jsLiteral("CAPTURE_FEED_WORD")
    # MOVED PIN (US-869-c): `faulted` joins the feed words (Iris C-Iris-2).
    assert set(re.findall(r"(\w+):", feedWord)) == {
        ch.STATE_OK, ch.STATE_STALLED, ch.STATE_IDLE, ch.STATE_FAULTED,
    }
    feeds = re.findall(r'\["(\w+)", "\w+"\]', _jsLiteral("CAPTURE_FEEDS"))
    assert sorted(feeds) == sorted(ch.FEED_NAMES)
    assert _jsLiteral("CAPTURE_STATE_STALLED") == '"' + ch.STATE_STALLED + '"'
    assert _jsLiteral("CAPTURE_REASON_NEVER_WRITTEN") == '"' + ch.REASON_NEVER_WRITTEN + '"'
    assert _jsLiteral("CAPTURE_MEMBER_KEY") == '"' + sse.VERDICT_CAPTURE + '"'
    silent = set(re.findall(r'"(\w+)"', _jsLiteral("DATA_ECU_SILENT_STATES")))
    assert silent == {sse.LINK_DOWN, sse.LINK_RETRYING, sse.LINK_CONNECTING}
    # US-869-c: the faulted word, the faulted state and the sensor member key.
    assert re.search(r"\b" + ch.STATE_FAULTED + r': "fault"', feedWord), feedWord
    assert _jsLiteral("CAPTURE_STATE_FAULTED") == '"' + ch.STATE_FAULTED + '"'
    assert _jsLiteral("SENSOR_MEMBER_KEY") == '"' + sse.VERDICT_SENSOR + '"'


@_needsNode
@pytest.mark.parametrize("name", sorted(_SENSOR_FIXTURES | _DATA_FIXTURES))
def test_everySysRowPartDataFeedValueIsAProducerFeedName(name: str, monkeypatch):
    """US-869-c cross-language guard: data-feed on a .sys-row-part names only
    capture_health.FEED_NAMES (space-separated when a member names several)."""
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(name)
    seen = 0
    for path in surface.pathsByClass("sys-row-part"):
        value = path[-1]["attrs"].get("data-feed")
        if value is not None:
            seen += 1
            assert value.split() and set(value.split()) <= set(ch.FEED_NAMES), (name, value)
    status, _ = _payloads(name)
    if {"capture", "sensor"} & set(_members(status)):
        assert seen > 0, name  # non-vacuous: a member part carries data-feed


def test_ac13_carouselJsHoldsNoCaptureMemberReasonText():
    """The page prints the member's reason verbatim and composes none."""
    code = re.sub(r"/\*.*?\*/", "", _read(_CAROUSEL_JS), flags=re.S)
    code = re.sub(r"(?m)^\s*//.*$", "", code)
    assert "feed stalled" not in code
    assert "feeds stalled" not in code


def test_theThreeTilesAndTheirDrillRowsAreRetired():
    source = _read(_CAROUSEL_JS)
    for fn in ("syncTile", "driveTile", "captureTile", "captureDetail", "captureReasonText"):
        assert not re.search(r"\bfunction " + fn + r"\b", source), fn
        assert not re.search(r"\b" + fn + r"\(", source), fn
    assert "CAPTURE_REASON_TEXT" not in source
    assert "sync.counts" not in source and "s.pending" not in source


def test_syncRowsAndPendingAreRetiredFromTheProducer():
    """Atlas P7: neither key is published, neither builder input exists."""
    status = buildSystemStatusState(
        syncLastOkTs=None, syncStale=False, powerSource="external",
        driveState="idle", driveId=None, nowIso=_NOW,
    )
    assert set(status["sync"]) == {
        "lastOkTs", "stale", "rowsWaiting", "edrRowsWaiting", "notCounted",
        # MOVED PIN (US-917-a): the lock-backed sync.inProgress.
        "inProgress",
    }
    params = inspect.signature(buildSystemStatusState).parameters
    emitParams = inspect.signature(sse.makeSystemStatusEmitter(".", syncStaleThresholdS=1)).parameters
    for retired in ("syncRows", "syncPending"):
        assert retired not in params and retired not in emitParams


def test_aStatusWithAMemberAddedIsStillAMemberOnly():
    """Non-vacuity for the sweep: the member is what moves the word, so a
    payload copied with the member removed reads the top-level word again."""
    status, capture = _payloads("capture-stalled")
    plain = copy.deepcopy(status)
    plain["verdict"] = {"issueCount": 0, "members": []}
    if _NODE is None:
        pytest.skip("node not on PATH")
    rows = _map("dataRowView", [[status, capture], [plain, capture]])
    assert rows[0]["word"] == "stalled"
    assert rows[1]["word"] == "stopped"


# ---------------------------------------------------------------------------
# US-869-c: a faulted feed is ONE `sensor` member (Atlas R1-R8).
# ---------------------------------------------------------------------------


def _rowPath(surface, key: str):
    rows = [p for p in surface.pathsByClass("sys-row") if p[-1]["attrs"].get("data-row") == key]
    assert len(rows) == 1, key
    return rows[0]


def _amberUnder(path) -> list[dict]:
    return [p[-1]["attrs"] for p in _descendants(path)
            if p[-1].get("attrs", {}).get("data-level") == "amber"]


def _parts(surface) -> list[dict]:
    return [p[-1] for p in surface.pathsByClass("sys-row-part")]


@_needsNode
def test_validation_imuFaulted_withAStalledLightFeed_eachPartIsItsOwnMember(monkeypatch):
    """VC: faulted part data-member=sensor data-feed=imu; stalled part
    data-member=capture; UPS row not amber."""
    monkeypatch.setenv("TZ", _ZONE)
    status, _ = _payloads("imu-faulted")
    assert _members(status) == ["capture", "sensor"]
    surface = _render("imu-faulted")

    members = [(_text(p), p["attrs"].get("data-member"), p["attrs"].get("data-feed"))
               for p in _parts(surface) if p["attrs"].get("data-level") == "amber"]
    assert members == [
        ("Light feed stalled.", "capture", "light"),
        (" " + MIDDLE_DOT + " IMU sensor not found.", "sensor", "imu"),
    ]
    assert _amberUnder(_rowPath(surface, "ups")) == []


@_needsNode
def test_validation_imuAndUpsFaulted_oneSensorPart_neverAllFeedsWriting(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    status, capture = _payloads("imu-ups-faulted")
    row = _call("dataRowView", status, capture)

    assert (row["word"], row["look"]) == ("recording", "ok")
    assert "all 4 feeds writing" not in row["sentence"]
    assert row["parts"][0] == {
        "text": "IMU sensor not found. UPS gauge read failed.", "level": "amber",
        "member": "sensor", "feed": "imu ups",
    }
    assert [p["level"] for p in row["parts"][1:]] == ["secondary"]
    assert (row["level"], row["member"]) == ("amber", "sensor")
    surface = _render("imu-ups-faulted")
    assert _amberUnder(_rowPath(surface, "ups")) == []


@_needsNode
def test_validation_imuFaultedEcuDown_sensorPartPresent_noCapturePart(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    status, capture = _payloads("imu-faulted-ecu-down")
    assert _members(status) == ["sensor"]
    row = _call("dataRowView", status, capture)

    assert [(p["member"], p["feed"]) for p in row["parts"] if p["level"] == "amber"] == [
        ("sensor", "imu")
    ]
    assert row["word"] != "stalled"


@_needsNode
def test_upsGaugeUnreadable_isAmberOnTheDataRowOnly_neverOnTheUpsRow(monkeypatch):
    """Atlas R7: a gauge read fault is amber through the sensor member on the
    DATA row, never on the UPS row."""
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("ups-gauge-unreadable")

    assert _amberUnder(_rowPath(surface, "ups")) == []
    dataAmber = _amberUnder(_rowPath(surface, "data"))
    assert dataAmber and {a.get("data-member") for a in dataAmber} == {"sensor"}
    assert [a.get("data-feed") for a in dataAmber if "sys-row-part" in a.get("class", "")] == [
        "ups"
    ]


@_needsNode
def test_detail_eachFeedRowIsItsOwnMember_faultedReadsFault(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    status, capture = _payloads("imu-faulted")
    detail = _call("dataDetailView", status, capture)
    assert [(f["label"], f["state"], f["look"], f["member"]) for f in detail["feeds"]] == [
        ("OBD", "writing", "ok", None),
        ("LIGHT", "stalled", "amber", "capture"),
        ("IMU", "fault", "amber", "sensor"),
        ("UPS", "writing", "ok", None),
    ]
    surface = _render(
        "imu-faulted", parked=True,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 1}}, {"flush": 1}],
    )
    states = surface.pathsByClass("data-feed-state")
    assert [(p[-1]["attrs"].get("data-member"), surface.winningDeclaration(p, "color")[0])
            for p in states] == [
        (None, GREEN), ("capture", AMBER), ("sensor", AMBER), (None, GREEN),
    ]
    feeds = surface.pathsByClass("data-feed-row")
    assert [p[-1]["attrs"]["data-feed"] for p in feeds] == ["obd", "light", "imu", "ups"]


@_needsNode
def test_aFaultedFeedNamedByNoSensorMember_isNeverAmber():
    status, capture = _payloads("imu-faulted")
    plain = copy.deepcopy(status)
    plain["verdict"] = {"issueCount": 0, "members": []}
    detail = _call("dataDetailView", plain, capture)
    imu = detail["feeds"][2]
    assert (imu["state"], imu["look"], imu["member"]) == ("fault", "secondary", None)
    row = _call("dataRowView", plain, capture)
    assert all(p["level"] == "secondary" for p in row["parts"])


@_needsNode
def test_aPartIsNeverBothStalledAndFaulted():
    """A feed has one state, so no feed is in both a capture part and a sensor part."""
    for name in sorted(_SENSOR_FIXTURES):
        status, capture = _payloads(name)
        row = _call("dataRowView", status, capture)
        named = {}
        for part in row["parts"]:
            for feed in (part["feed"] or "").split():
                named.setdefault(feed, set()).add(part["member"])
        assert all(len(m) == 1 for m in named.values()), (name, named)


@_needsNode
def test_allFeedsOk_noSensorPart_andTheRowIsUnchanged():
    status, capture = _payloads("all-ok-driving")
    row = _call("dataRowView", status, capture)
    assert all(p["member"] is None and p["feed"] is None for p in row["parts"])
    assert row["sentence"] == "all 4 feeds writing " + MIDDLE_DOT + " 0 rows waiting"
