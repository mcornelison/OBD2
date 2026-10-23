################################################################################
# File Name: test_system_page_obd_row.py
# Purpose/Description: US-894-b (spec specs/v030-system-page-design.md s3 layout
#   A, s4.0, s4.1, s4.2, s4.6, s7) -- the System page is a verdict line plus
#   rows, starting with the OBD chain row; obdLink is retired.
#
#   What is pinned here:
#     - the fixtures in tests/ui/fixtures/states/system/ are exactly what
#       _generate.py builds from the REAL builders (never hand-typed);
#     - the verdict line: ALL OK / n ISSUE(S) / `--` (absent verdict or an
#       unreadable file, never ALL OK);
#     - the OBD row: step looks (null DASHED, never the solid down look), the
#       sentence rule (a member's reason verbatim, else the first non-up layer
#       speaks), swept over every state the producer can publish;
#     - the colour rule (s4.0, AC 7): amber IFF a verdict member maps;
#     - the four validationCriteria fixtures, and spec AC 2 / 3 / 4 / 13;
#     - the parked accessor (one module accessor, the tick its only writer,
#       an edge registry) and the parked-only taps into #sys-detail;
#     - the OBD detail, the --row-min token, one-line ellipsis, no literal
#       px / colour in the page's CSS, rows never `.tile`;
#     - one cross-language guard for the JS copy of the provider's link-state
#       vocabulary this story introduces (the sentence table).
#
#   Skipped when node is not on PATH -- the source, CSS and fixture checks
#   always run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-b System page OBD row.
# ================================================================================
################################################################################

"""US-894-b tests: the System page's verdict line, OBD row and detail."""

from __future__ import annotations

import importlib.util
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

from pi.splash import system_status_emitter as sse  # noqa: E402
from pi.splash.system_status_emitter import (  # noqa: E402
    buildSystemStatusState,
    buildSystemVerdict,
)

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_HTML = os.path.join(_DASH, "dashboard.html")
_CSS = os.path.join(_DASH, "dashboard.css")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")

GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
SECONDARY = "var(--text-secondary)"
TERTIARY = "var(--text-tertiary)"

_ALL_STATES = (sse.LINK_UP, sse.LINK_CONNECTING, sse.LINK_RETRYING, sse.LINK_DOWN, None)

# Spec s4.2's sentence table, written out from the spec (Iris I1) -- never read
# from carousel.js. First non-up layer -> its state -> the words.
_SPEC_SENTENCE = {
    ("bt", "connecting"): "Bluetooth trying to link (key off?)",
    ("bt", "down"): "Bluetooth not linked",
    ("bt", "retrying"): "Bluetooth retrying…",
    ("bt", None): "Bluetooth not read yet",
    ("adapter", "connecting"): "adapter connecting…",
    ("adapter", "down"): "adapter not answering",
    ("adapter", "retrying"): "adapter retrying…",
    ("adapter", None): "adapter not read yet",
    ("ecu", "connecting"): "ECU not answering (key off?)",
    ("ecu", "down"): "ECU not answering (key off?)",
    ("ecu", "retrying"): "ECU not answering (key off?)",
    ("ecu", None): "ECU not read yet",
}
_SPEC_ALL_UP = "ECU answering"

# The row's step look per state when no member maps (s4.2 table).
_STEP_LOOK = {
    sse.LINK_UP: "ok",
    sse.LINK_CONNECTING: "neutral",
    sse.LINK_RETRYING: "secondary",
    sse.LINK_DOWN: "tertiary",
    None: "dashed",
}

_NOW_MS = 1761174600000  # 2026-10-22T23:10:00Z, the fixtures' `now`.


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _generator():
    spec = importlib.util.spec_from_file_location(
        "system_fixture_generator", os.path.join(_FIXTURE_DIR, "_generate.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _status(name: str) -> dict[str, Any]:
    return _fixture(name)["payloads"]["system-status"]


def _payload(
    bt: str | None, adapter: str | None, ecu: str | None, *, driveState: str = "idle"
) -> dict:
    """A system-status payload from the SHIPPED builder -- its verdict included."""
    link = {
        layer: {"state": state, "ts": "2026-10-22T23:08:30Z" if state else None,
                "lastOkTs": None}
        for layer, state in (("bt", bt), ("adapter", adapter), ("ecu", ecu))
    }
    return buildSystemStatusState(
        syncLastOkTs=None,
        syncRows=0,
        syncPending=None,
        syncStale=False,
        powerSource="external",
        driveState=driveState,
        driveId=7 if driveState == "recording" else None,
        nowIso="2026-10-22T23:10:00Z",
        link=link,
    )


def _map(fn: str, argLists: list[list[Any]]) -> list[Any]:
    proc = subprocess.run(
        [_NODE, _PROBE, "--map", fn],
        input=json.dumps(argLists),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _call(fn: str, *args: Any) -> Any:
    return _map(fn, [list(args)])[0]


def _node(script: str) -> Any:
    proc = subprocess.run(
        [_NODE, "-e", script, _CAROUSEL_JS],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Fixtures: generated from the real builders, never hand-typed (Atlas L7).
# ---------------------------------------------------------------------------

_STORY_FIXTURES = {
    "arch061-during-attempt", "arch061-between-attempts", "all-ok-driving",
    "bt-connecting", "bt-retrying", "adapter-silent", "link-not-read",
    "verdict-absent", "ecu-retrying-after-keyoff", "adapter-down-bt-down",
}


def test_theFixtureDirectoryHoldsExactlyThisStorysFixtures():
    names = {f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json")}
    assert names == _STORY_FIXTURES
    assert set(_generator().fixtureNames()) == _STORY_FIXTURES


@pytest.mark.parametrize("name", sorted(_STORY_FIXTURES))
def test_everyFixtureOnDiskIsWhatTheGeneratorBuilds(name: str):
    gen = _generator()
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        onDisk = fh.read()
    assert onDisk == gen.render(gen.buildFixture(name)), (
        f"{name}.json is stale -- re-run tests/ui/fixtures/states/system/_generate.py"
    )


@pytest.mark.parametrize("name", sorted(_STORY_FIXTURES))
def test_everyFixtureHasTheSystemShape(name: str):
    fx = _fixture(name)
    assert set(fx) == {"description", "now", "zone", "inputs", "payloads"}
    assert fx["description"]
    assert "system-status" in fx["payloads"]
    assert "obdLink" not in fx["payloads"]["system-status"]


@pytest.mark.parametrize("name", sorted(_STORY_FIXTURES - {"verdict-absent"}))
def test_everyBuiltFixtureIsTheBuildersOutputForItsInputs(name: str):
    """Rebuilt here from the fixture's OWN stored inputs, independently of the
    script, so the stored inputs and the payload cannot drift apart."""
    fx = _fixture(name)
    inputs = fx["inputs"]
    capture = fx["payloads"].get("capture-health")
    assert buildSystemStatusState(**inputs["system-status"], captureHealth=capture) == (
        fx["payloads"]["system-status"]
    )


def test_verdictAbsent_isTheGeneratedPayloadWithOnlyTheVerdictPopped():
    absent = _status("verdict-absent")
    base = _status("all-ok-driving")
    assert "verdict" not in absent
    assert {k: v for k, v in base.items() if k != "verdict"} == absent


# ---------------------------------------------------------------------------
# validationCriteria (the four named fixtures) + spec AC 2, 3, 4.
# ---------------------------------------------------------------------------


def _views(names: list[str]) -> dict[str, dict]:
    views = _map("systemStatusView", [[_status(n)] for n in names])
    return dict(zip(names, views))


@_needsNode
def test_validation_arch061BetweenAttempts_allOk_nnn_tryingToLink():
    view = _views(["arch061-between-attempts"])["arch061-between-attempts"]
    assert view["verdict"] == {"text": "ALL OK", "level": "ok"}
    row = view["rows"][0]
    assert row["steps"] == ["neutral", "neutral", "neutral"]
    assert row["sentence"] == "Bluetooth trying to link (key off?)"
    assert row["level"] != "amber"
    flat = json.dumps(view, ensure_ascii=False)
    assert "Bluetooth down" not in flat
    assert "takes ~1 min" not in flat


@_needsNode
def test_validation_btRetrying_oneIssue_btAmber_theMemberReasonByteForByte():
    status = _status("bt-retrying")
    members = status["verdict"]["members"]
    assert [m["key"] for m in members] == ["bt"]
    view = _views(["bt-retrying"])["bt-retrying"]
    assert view["verdict"] == {"text": "1 ISSUE", "level": "amber"}
    row = view["rows"][0]
    assert row["steps"][0] == "amber"
    assert row["sentence"] == members[0]["reason"]
    assert row["level"] == "amber"


@_needsNode
def test_validation_arch061DuringAttempt_allOk_ggn_ecuNotAnswering():
    view = _views(["arch061-during-attempt"])["arch061-during-attempt"]
    assert view["verdict"] == {"text": "ALL OK", "level": "ok"}
    assert view["rows"][0]["steps"] == ["ok", "ok", "neutral"]
    assert view["rows"][0]["sentence"] == "ECU not answering (key off?)"
    assert "Bluetooth down" not in json.dumps(view)


@_needsNode
def test_validation_linkNotRead_dashedSteps_btNotReadYet():
    """AC 4: ALL OK (nothing read is no issue -- the provider counted nothing),
    every step DASHED, never the solid `down` look."""
    view = _views(["link-not-read"])["link-not-read"]
    assert view["verdict"] == {"text": "ALL OK", "level": "ok"}
    assert view["rows"][0]["steps"] == ["dashed", "dashed", "dashed"]
    assert "tertiary" not in view["rows"][0]["steps"]
    assert view["rows"][0]["sentence"] == "Bluetooth not read yet"


@_needsNode
def test_theOtherFixtures_readAsTheSpecSays():
    views = _views([
        "all-ok-driving", "bt-connecting", "adapter-silent",
        "ecu-retrying-after-keyoff", "adapter-down-bt-down", "verdict-absent",
    ])
    assert views["all-ok-driving"]["verdict"]["text"] == "ALL OK"
    assert views["all-ok-driving"]["rows"][0]["sentence"] == _SPEC_ALL_UP
    assert views["all-ok-driving"]["rows"][0]["steps"] == ["ok", "ok", "ok"]

    assert views["bt-connecting"]["verdict"]["text"] == "ALL OK"
    assert views["bt-connecting"]["rows"][0]["steps"] == ["neutral", "dashed", "dashed"]
    assert views["bt-connecting"]["rows"][0]["sentence"] == (
        "Bluetooth trying to link (key off?)"
    )

    adapter = views["adapter-silent"]["rows"][0]
    assert views["adapter-silent"]["verdict"]["text"] == "1 ISSUE"
    assert adapter["steps"][:2] == ["ok", "amber"]
    assert adapter["sentence"] == _status("adapter-silent")["verdict"]["members"][0]["reason"]
    assert adapter["level"] == "amber"

    ecu = views["ecu-retrying-after-keyoff"]
    assert ecu["verdict"]["text"] == "ALL OK"
    assert ecu["rows"][0]["steps"] == ["ok", "ok", "secondary"]
    assert ecu["rows"][0]["sentence"] == "ECU not answering (key off?)"

    both = views["adapter-down-bt-down"]["rows"][0]
    assert both["steps"] == ["amber", "tertiary", "dashed"]
    assert both["sentence"] == _status("adapter-down-bt-down")["verdict"]["members"][0]["reason"]

    assert views["verdict-absent"]["verdict"] == {"text": "--", "level": "unavailable"}
    # The row still reads the link: only the verdict is unknown.
    assert views["verdict-absent"]["rows"][0]["sentence"] == _SPEC_ALL_UP


# ---------------------------------------------------------------------------
# The verdict line (s4.1).
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ({"issueCount": 0, "members": []}, {"text": "ALL OK", "level": "ok"}),
        ({"issueCount": 1, "members": []}, {"text": "1 ISSUE", "level": "amber"}),
        ({"issueCount": 2, "members": []}, {"text": "2 ISSUES", "level": "amber"}),
        ({"issueCount": 12, "members": []}, {"text": "12 ISSUES", "level": "amber"}),
    ],
)
def test_theVerdictLine_isTheProvidersCount(verdict, expected):
    assert _call("systemVerdictView", {"verdict": verdict}) == expected


@_needsNode
@pytest.mark.parametrize(
    "data",
    [
        None, "x", [], {}, {"verdict": None}, {"verdict": {}},
        {"verdict": {"issueCount": None}}, {"verdict": {"issueCount": "0"}},
        {"verdict": {"issueCount": -1}}, {"verdict": {"issueCount": 1.5}},
        {"verdict": {"issueCount": False}},
    ],
)
def test_anAbsentOrMalformedVerdict_isTwoHyphens_neverAllOk(data):
    assert _call("systemVerdictView", data) == {"text": "--", "level": "unavailable"}


# ---------------------------------------------------------------------------
# The OBD row, swept over every state the REAL producer can publish.
# ---------------------------------------------------------------------------


def _expectedSentence(payload: dict) -> str:
    members = {m["key"]: m["reason"] for m in payload["verdict"]["members"]}
    for key in ("bt", "adapter"):
        if key in members:
            return members[key]
    for layer in sse.LINK_LAYERS:
        state = payload["link"][layer]["state"]
        if state != sse.LINK_UP:
            return _SPEC_SENTENCE[(layer, state)]
    return _SPEC_ALL_UP


@_needsNode
def test_theRow_overEveryStateTheProducerCanEmit():
    """Sentence: a member's reason verbatim, else the first non-up layer speaks
    (later layers never do). Steps: amber IFF the layer is a member, else the
    s4.2 look -- a null layer DASHED. AC 7: the amber set equals the member
    set, sentence included."""
    cases = [
        (combo, drive)
        for combo in itertools.product(_ALL_STATES, repeat=3)
        for drive in ("idle", "recording")
    ]
    payloads = [_payload(*combo, driveState=drive) for combo, drive in cases]
    rows = _map("obdRowView", [[p] for p in payloads])
    assert len(rows) == 250
    for (combo, drive), payload, row in zip(cases, payloads, rows):
        members = {m["key"] for m in payload["verdict"]["members"]} & set(sse.LINK_LAYERS)
        assert row["sentence"] == _expectedSentence(payload), (combo, drive, row)
        assert (row["level"] == "amber") == bool(members), (combo, drive, row)
        for layer, state, look in zip(sse.LINK_LAYERS, combo, row["steps"]):
            expected = "amber" if layer in members else _STEP_LOOK[state]
            assert look == expected, (combo, drive, layer, row)


@_needsNode
def test_anAdapterFaultWhileBtIsDown_neverSpeaks():
    payload = _payload("down", "retrying", None)
    row = _call("obdRowView", payload)
    assert row["sentence"] == payload["verdict"]["members"][0]["reason"]
    assert "adapter" not in row["sentence"]


@_needsNode
def test_aStateWordTheProviderHasNotPublished_isNotRead_dashedAndNotReadYet():
    payload = _payload("up", "up", "up")
    payload["link"]["ecu"]["state"] = "someFutureState"
    row = _call("obdRowView", payload)
    assert row["steps"][2] == "dashed"
    assert row["sentence"] == "ECU not read yet"


@_needsNode
def test_theRowsStepsAreTheTopBarDots_exceptNullIsDashedNotHollow():
    payloads = [_payload(*c) for c in itertools.product(_ALL_STATES, repeat=3)]
    rows = _map("obdRowView", [[p] for p in payloads])
    dots = _map("linkChainGlyph", [[p] for p in payloads])
    for row, dot in zip(rows, dots):
        bar = [dot[layer] for layer in sse.LINK_LAYERS]
        assert row["steps"] == ["dashed" if d == "hollow" else d for d in bar]


@_needsNode
def test_theSentenceTableIsTheSpecs_andItsKeysAreTheProvidersStates():
    """Cross-language guard (one per JS copy of a Python vocabulary): the
    table's layers are LINK_LAYERS, and each layer's state keys are exactly the
    provider's non-up states plus "null" (not read)."""
    js = _node(
        "const c = require(process.argv[1]);"
        "console.log(JSON.stringify({t: c.OBD_LAYER_SENTENCE, up: c.OBD_ALL_UP_SENTENCE}));"
    )
    table = js["t"]
    assert list(table) == list(sse.LINK_LAYERS)
    nonUp = {sse.LINK_CONNECTING, sse.LINK_RETRYING, sse.LINK_DOWN}
    for layer in sse.LINK_LAYERS:
        assert set(table[layer]) == nonUp | {"null"}, layer
        for state, words in table[layer].items():
            assert words == _SPEC_SENTENCE[(layer, None if state == "null" else state)]
    assert js["up"] == _SPEC_ALL_UP


# ---------------------------------------------------------------------------
# Words (spec AC 2, 3, 13; Iris G1).
# ---------------------------------------------------------------------------


def _s109Reasons() -> set[str]:
    """Every reason the S109 verdict can publish, from the REAL buildSystemVerdict."""
    reasons: set[str] = set()
    for combo in itertools.product(_ALL_STATES, repeat=3):
        for drive in ("idle", "recording"):
            link = {layer: {"state": s} for layer, s in zip(sse.LINK_LAYERS, combo)}
            verdict = buildSystemVerdict(
                link=link, wifiSource=None, captureHealth=None, piHealth=None,
                driveState=drive,
            )
            reasons.update(m["reason"] for m in verdict["members"])
    feeds = ("obd", "light", "imu", "ups")
    for n in range(1, len(feeds) + 1):
        for stalled in itertools.combinations(feeds, n):
            capture = {"feeds": {f: {"state": "stalled" if f in stalled else "ok"} for f in feeds}}
            verdict = buildSystemVerdict(
                link={"ecu": {"state": "up"}}, wifiSource=None, captureHealth=capture,
                piHealth=None, driveState="recording",
            )
            reasons.update(m["reason"] for m in verdict["members"])
    reasons.update(
        m["reason"]
        for m in buildSystemVerdict(
            link=None, wifiSource={"reason": "read_failed"}, captureHealth=None,
            piHealth=None, driveState="idle",
        )["members"]
    )
    piCases = [
        {"overLimit": ["cpuTemp"], "cpuTempC": 80.2, "cpuTempLimitC": 80},
        {"overLimit": ["throttled"], "throttledHex": "0x1"},
        {"overLimit": ["throttled"], "throttledHex": "0x4"},
        {"overLimit": ["disk"], "diskFreeBytes": 10 * 2**30, "diskThresholdBytes": 20 * 2**30},
        {"overLimit": ["cpuTemp", "throttled", "disk"]},
    ]
    for pi in piCases:
        reasons.update(
            m["reason"]
            for m in buildSystemVerdict(
                link=None, wifiSource=None, captureHealth=None, piHealth=pi,
                driveState="idle",
            )["members"]
        )
    return reasons


def test_ac13_carouselJsContainsNoneOfTheS109ReasonStrings_commentsIncluded():
    reasons = _s109Reasons()
    assert len(reasons) >= 12, reasons
    source = _read(_CAROUSEL_JS)
    leaked = sorted(r for r in reasons if r in source)
    assert leaked == [], f"carousel.js composes provider reason text: {leaked}"


def test_noElementAnywhereReadsTakesAboutOneMinute():
    for path in (_CAROUSEL_JS, _HTML, _CSS):
        assert "takes ~1 min" not in _read(path), path


# ---------------------------------------------------------------------------
# The OBD detail (s4.6).
# ---------------------------------------------------------------------------


@_needsNode
def test_theObdDetail_perLayerStateSinceAndLastSuccess():
    status = _status("bt-connecting")
    detail = _call("obdDetailView", status)
    assert detail["head"] == "OBD"
    layers = {entry["layer"]: entry for entry in detail["layers"]}
    assert [entry["label"] for entry in detail["layers"]] == ["BT", "ADAPTER", "ECU"]
    assert layers["bt"]["state"] == "connecting"
    assert layers["bt"]["since"] not in ("--", status["link"]["bt"]["ts"])
    assert layers["bt"]["lastOk"] == "--"  # never up this session
    for layer in ("adapter", "ecu"):
        assert (layers[layer]["state"], layers[layer]["since"], layers[layer]["lastOk"]) == (
            "--", "--", "--",
        )
    assert detail["sentence"] == "Bluetooth trying to link (key off?)"


@_needsNode
def test_theObdDetail_lastSuccessIsTheLayersLastOkTs_throughFmtStamp():
    status = _status("all-ok-driving")
    detail = _call("obdDetailView", status)
    for entry in detail["layers"]:
        assert entry["state"] == "up"
        assert entry["lastOk"] not in ("--", status["link"][entry["layer"]]["lastOkTs"])
        assert re.match(r"^[A-Z][a-z]{2} \d{2}, \d{4} ", entry["lastOk"]), entry


@_needsNode
def test_theObdDetail_drawsNoMacAndNoRetryCount():
    detail = _call("obdDetailView", _status("bt-retrying"))
    flat = json.dumps(detail).lower()
    assert "mac" not in flat
    assert "retries" not in flat and "retry " not in flat
    assert set(detail["layers"][0]) == {"layer", "label", "look", "state", "since", "lastOk"}


# ---------------------------------------------------------------------------
# The parked accessor (Atlas B9 + A1 2026-10-22).
# ---------------------------------------------------------------------------


@_needsNode
def test_theParkedAccessor_failsClosed_andFiresOnAnEdgeOfEitherValue():
    out = _node(
        "const c = require(process.argv[1]);"
        "const seen = [];"
        "const r = {start: c.currentParked()};"
        "c.onParkedChange(function (f) { seen.push(f); });"
        "r.a = c.publishParked(false, false);"
        "r.b = c.publishParked(false, true);"
        "r.c = c.publishParked(false, true);"
        "r.d = c.publishParked(true, true);"
        "r.e = c.publishParked('true', 1);"
        "r.after = c.currentParked();"
        "r.copy = (function () { var x = c.currentParked(); x.parked = true;"
        " return c.currentParked().parked; })();"
        "r.seen = seen;"
        "console.log(JSON.stringify(r));"
    )
    assert out["start"] == {"parked": False, "gearKnown": False}
    assert out["a"] is False  # no change, no edge
    assert out["b"] is True and out["c"] is False
    assert out["d"] is True
    assert out["e"] is True  # only a strict true counts: back to false/false
    assert out["after"] == {"parked": False, "gearKnown": False}
    assert out["copy"] is False  # a reader cannot write through the accessor
    assert out["seen"] == [
        {"parked": False, "gearKnown": True},
        {"parked": True, "gearKnown": True},
        {"parked": False, "gearKnown": False},
    ]


def test_theTickIsTheAccessorsOnlyWriter_withTheDebouncedAndTheRawFacts():
    source = _read(_CAROUSEL_JS)
    assert len(re.findall(r"function publishParked\(", source)) == 1
    writes = [
        m.start() for m in re.finditer(r"\bpublishParked\(", source)
        if source[max(0, m.start() - 9):m.start()] != "function "
    ]
    assert len(writes) == 1, "publishParked has a writer besides the tick"
    line = source[writes[0]:source.index("\n", writes[0])]
    assert "engineParked.parked" in line
    assert "lastGear.available === true" in line
    # It follows the tick's debounce advance (the 8 s hold), a few lines up.
    assert "engineParked = parkedNext(engineParked, gearParked(lastGear)" in (
        source[writes[0] - 400:writes[0]]
    )


def test_theAccessorNamesAvoidTheKebabPins():
    source = _read(_CAROUSEL_JS)
    block = source[source.index("var parkedFact ="):source.index("function publishParked(")]
    for banned in ("menuAccess", "tapVisible", "menuBtn.hidden"):
        assert banned not in block
    for name in ("currentParked", "onParkedChange", "publishParked"):
        for banned in ("menuAccess", "tapVisible"):
            assert banned not in name


def test_theAccessorNeverReadsTheRawPredicate():
    source = _read(_CAROUSEL_JS)
    start = source.index("var parkedFact =")
    end = source.index("return true;\n  }", source.index("function publishParked("))
    assert "gearParked" not in source[start:end].replace("gearParked here", "")


# ---------------------------------------------------------------------------
# The rendered page (DOM) -- parked-only taps, #sys-detail, the chevron.
# ---------------------------------------------------------------------------


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso="2026-10-22T23:10:00Z")


def _render(status: dict | None, *, parked: bool, steps: list[dict] | None = None):
    routes: dict[str, Any] = {}
    if status is not None:
        routes["/system-status"] = status
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


def _allText(node: dict) -> list[str]:
    out = [str(v) for v in node.get("attrs", {}).values()]
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"])
        else:
            out.extend(_allText(child))
    return out


def _systemCard(surface) -> dict:
    for path in surface.paths():
        attrs = path[-1].get("attrs", {})
        if attrs.get("data-state") == "system-status" and "card" in (attrs.get("class") or ""):
            return path[-1]
    raise AssertionError("no System card in the rendered DOM")


def _hasGearBuilder() -> bool:
    try:
        _gearParked()
    except Exception:  # noqa: BLE001 -- a missing builder skips, never fakes
        return False
    return True


@_needsNode
def test_thePage_rendersTheVerdictLineAndTheObdRow_neverATile():
    surface = _render(_status("arch061-during-attempt"), parked=False)
    card = _systemCard(surface)
    text = _text(card)
    assert text.startswith("ALL OK")
    assert "ECU not answering (key off?)" in text
    assert "SYSTEM ·" not in text
    classes = " ".join(_allText(card))
    assert "tile" not in re.findall(r"[\w-]+", classes)
    rows = surface.pathsByClass("sys-row")
    assert len(rows) == 1
    steps = surface.pathsByClass("obd-step")
    assert [p[-1]["attrs"]["data-state"] for p in steps] == ["ok", "ok", "neutral"]
    assert [_text(p[-1]) for p in steps] == ["BT", "ADAPTER", "ECU"]
    everything = " ".join(_allText(surface.tree)).lower()
    assert "bluetooth down" not in everything
    assert "takes ~1 min" not in everything


@_needsNode
def test_thePage_aNullStepIsDashed_neverTheSolidDownLook():
    surface = _render(_status("link-not-read"), parked=False)
    steps = surface.pathsByClass("obd-step")
    for path in steps:
        assert path[-1]["attrs"]["data-state"] == "dashed"
        style = surface.winningDeclaration(path, "border-style")
        assert style is not None and style[0] == "dashed", style
    down = steps[0]
    down[-1]["attrs"]["data-state"] = "tertiary"
    solid = surface.winningDeclaration(down, "border-style")
    assert solid is None or solid[0] != "dashed"


@_needsNode
def test_thePage_stepLooksResolveToTheSpecColours_amberOnlyOnTheMember():
    surface = _render(_status("adapter-down-bt-down"), parked=False)
    steps = surface.pathsByClass("obd-step")
    colours = [surface.winningDeclaration(p, "color")[0] for p in steps]
    assert colours == [AMBER, TERTIARY, TERTIARY]
    sentence = surface.pathsByClass("sys-row-sentence")[0]
    assert surface.winningDeclaration(sentence, "color")[0] == AMBER
    resolved = {}
    for look in ("ok", "neutral", "secondary", "tertiary", "amber", "dashed"):
        steps[0][-1]["attrs"]["data-state"] = look
        resolved[look] = surface.winningDeclaration(steps[0], "color")[0]
    assert resolved == {
        "ok": GREEN, "neutral": SECONDARY, "secondary": SECONDARY,
        "tertiary": TERTIARY, "amber": AMBER, "dashed": TERTIARY,
    }


@_needsNode
def test_thePage_aNonMemberSentenceIsNeverAmber():
    surface = _render(_status("ecu-retrying-after-keyoff"), parked=False)
    sentence = surface.pathsByClass("sys-row-sentence")[0]
    assert surface.winningDeclaration(sentence, "color")[0] == SECONDARY


@_needsNode
def test_thePage_unreadableSystemStatus_isTheVerdictTwoHyphens_neverAllOk():
    surface = _render(None, parked=False)
    card = _systemCard(surface)
    assert _text(card) == "--"
    assert surface.pathsByClass("sys-row") == []
    verdict = surface.pathsByClass("sys-verdict")[0]
    assert verdict[-1]["attrs"]["data-level"] == "unavailable"


@_needsNode
def test_thePage_aFileThatVanishes_dropsBackToTwoHyphens():
    status = _status("all-ok-driving")
    surface = _render(
        status, parked=False,
        steps=[{"setRoutes": {"/system-status": None}}, {"flush": 4}],
    )
    assert _text(_systemCard(surface)) == "--"


@_needsNode
def test_thePage_verdictAbsent_isTwoHyphens_withTheRowStillRead():
    surface = _render(_status("verdict-absent"), parked=False)
    text = _text(_systemCard(surface))
    assert text.startswith("--")
    assert "ALL OK" not in text
    assert "ECU answering" in text


@_needsNode
def test_notParked_noChevronAndATapOpensNothing():
    surface = _render(
        _status("bt-retrying"), parked=False,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 0}}, {"flush": 1},
               {"clickNth": {"selector": ".sys-verdict", "index": 0}}, {"flush": 1}],
    )
    assert surface.pathsByClass("sys-chevron") == []
    detail = surface.pathById("sys-detail")
    assert detail[-1]["attrs"].get("hidden") is not None


@_needsNode
@pytest.mark.skipif(not _hasGearBuilder(), reason="gear builder unavailable")
def test_parked_theObdRowOpensTheObdDetail_inSysDetail_withoutTheVersionChip():
    surface = _render(
        _status("bt-connecting"), parked=True,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 0}}, {"flush": 1}],
    )
    assert len(surface.pathsByClass("sys-chevron")) == 2  # verdict + OBD row
    detail = surface.pathById("sys-detail")
    assert detail[-1]["attrs"].get("hidden") is None, "the OBD detail did not open"
    assert _text(surface.pathById("sys-detail-head")[-1]) == "OBD"
    layers = surface.pathsByClass("obd-layer-row")
    assert [p[-1]["attrs"]["data-layer"] for p in layers] == ["bt", "adapter", "ecu"]
    body = _text(surface.pathById("sys-detail-body")[-1])
    assert "last success --" in body
    assert "Bluetooth trying to link (key off?)" in body
    chip = surface.pathById("version-chip")
    assert chip[-1]["attrs"].get("hidden") is not None


@_needsNode
@pytest.mark.skipif(not _hasGearBuilder(), reason="gear builder unavailable")
def test_parked_theVerdictOpensTheDrill_whichKeepsTheVersionChip():
    surface = _render(
        _status("all-ok-driving"), parked=True,
        steps=[{"clickNth": {"selector": ".sys-verdict", "index": 0}}, {"flush": 1}],
    )
    detail = surface.pathById("sys-detail")
    assert detail[-1]["attrs"].get("hidden") is None
    assert _text(surface.pathById("sys-detail-head")[-1]) == "ALL OK"
    chip = surface.pathById("version-chip")
    assert chip[-1]["attrs"].get("hidden") is None


@_needsNode
@pytest.mark.skipif(not _hasGearBuilder(), reason="gear builder unavailable")
def test_parkedButInsideTheEightSecondHold_aTapOpensNothing():
    """The accessor is the DEBOUNCED fact: gear P read for under 8 s is not
    parked yet (gearParked alone would already say yes)."""
    routes = {"/system-status": _status("bt-connecting"), "/gear": _gearParked()}
    tree = rh.runDashboard(
        routes=routes,
        steps=[{"flush": 4}, {"advanceMs": 3000, "flush": 4},
               {"clickNth": {"selector": ".sys-row", "index": 0}}, {"flush": 1}],
        viewport=PANEL, nowMs=_NOW_MS,
    )["tree"]
    surface = rh.dashboardSurface(tree, viewport=PANEL)
    assert surface.pathsByClass("sys-chevron") == []
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is not None


# ---------------------------------------------------------------------------
# CSS: --row-min, one-line ellipsis, no literal px / colour (spec s3, AC 10/11).
# ---------------------------------------------------------------------------


def _pageRules() -> list[str]:
    css = _read(_CSS)
    section = css[css.index("/* --- US-894-b System page"):]
    section = section[:section.index("/* --- ", 10)]
    section = re.sub(r"/\*.*?\*/", "", section, flags=re.S)
    return re.findall(r"[^{}]+\{[^}]*\}", section)


def test_theRowMinTokenIs44px_besideTapMin():
    css = _read(_CSS)
    assert re.search(r"--tap-min:\s*40px;.*\n\s*--row-min:\s*44px;", css)


def test_thePagesCssHasNoLiteralPxOrColour():
    rules = _pageRules()
    assert len(rules) >= 10
    for rule in rules:
        body = rule.split("{", 1)[1]
        assert not re.search(r"\d\s*px\b", body), rule
        assert "#" not in body and "rgb" not in body, rule


def test_rowsAreAtLeastRowMin_andTheSentenceIsOneLineEllipsis():
    rules = {r.split("{", 1)[0].strip(): r.split("{", 1)[1] for r in _pageRules()}
    assert "min-height: var(--row-min)" in rules[".sys-row"]
    for selector in (".sys-row-sentence", ".sys-row-value"):
        body = rules[selector]
        assert "white-space: nowrap" in body
        assert "overflow: hidden" in body
        assert "text-overflow: ellipsis" in body


def test_theRetiredSummaryGridAndObdLinkTileAreGone():
    """No definition or use survives (a comment may record the retirement)."""
    source = _read(_CAROUSEL_JS)
    assert not re.search(r"\bSYS_TILE_ORDER\s*[=.\[]", source)
    assert not re.search(r"\bobdLinkTile\s*[(:]", source)
    assert not re.search(r"\bfunction systemSummary\b", source)
    assert not re.search(r"[\"']SYSTEM · ", source), "a 'SYSTEM · …' string is still built"
    assert "sys-grid" not in source and "sys-grid" not in _read(_CSS)
    assert ".obdLink" not in source
