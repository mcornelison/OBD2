################################################################################
# File Name: test_system_page_ups_row.py
# Purpose/Description: US-894-e (spec specs/v030-system-page-design.md s4.0,
#   s4.5, s4.6.1, s7; Atlas A1/A3/A4/P8, Iris I6/I7/W2) -- the System page's
#   UPS row and its parked UPS detail, which replace the Battery card.
#
#   What is pinned here:
#     - the two UPS fixtures the story names are exactly what _generate.py
#       builds from the REAL builders (never hand-typed);
#     - both validationCriteria (ups-on-battery row; its detail);
#     - the row: VCELL value, the SENSED source from system-status (never
#       derived from battery-health, Atlas A1), the M7 freshness age through
#       the one shared helper (I6), never amber (A4), the gauge-unreadable NA;
#     - the detail: the W2 reason words, the health verdict (never amber),
#       reason / margin / F-9 line, the SOC line, LAST STOP (I7);
#     - the words gate: the rendered System page and UPS detail for every UPS
#       fixture never say wall / car / min to cutoff / charging / crate, and
#       the row carries no '%' (rendered text, not a grep of carousel.js);
#     - the Battery card is gone (9 cards -> 8) and the tick reads
#       battery-health for the row (Atlas P8);
#     - ONE cross-language guard for the JS copy of the power-source reason
#       vocabulary (card_state_emitter.POWER_SOURCE_UNKNOWN_REASONS).
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
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-e System page UPS row.
# ================================================================================
################################################################################

"""US-894-e tests: the System page's UPS row and its parked UPS detail."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from pi.obdii.orchestrator import card_state_emitter as cse  # noqa: E402
from pi.splash.battery_health_emitter import buildBatteryHealthState  # noqa: E402
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
_DASHBOARD_HTML = os.path.join(_DASH, "dashboard.html")
_DASHBOARD_CSS = os.path.join(_DASH, "dashboard.css")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")

AMBER = "var(--amber-warn)"
PRIMARY = "var(--text-primary)"
SECONDARY = "var(--text-secondary)"
MIDDLE_DOT = "·"

_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)

# The fixtures this story names (acceptance: "This story adds only the
# fixtures it names").
_UPS_FIXTURES = {"ups-on-battery", "ups-gauge-unreadable"}

# Acceptance (words gate): never on the page or the UPS detail.
_BANNED = re.compile(r"\bwall\b|\bcar\b|min to cutoff|charging|crate", re.IGNORECASE)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _generator():
    spec = importlib.util.spec_from_file_location(
        "system_fixture_generator_e", os.path.join(_FIXTURE_DIR, "_generate.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _payloads(name: str) -> tuple[dict, dict]:
    p = _fixture(name)["payloads"]
    return p["system-status"], p["battery-health"]


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


def _status(**overrides: Any) -> dict:
    """A system-status from the REAL builder; power by keyword."""
    kwargs = dict(
        syncLastOkTs=_NOW, syncStale=False, powerSource="external",
        driveState="idle", driveId=None, nowIso=_NOW,
    )
    kwargs.update(overrides)
    return buildSystemStatusState(**kwargs)


def _battery(**overrides: Any) -> dict:
    """A battery-health payload from the REAL builder (the fixture inputs)."""
    inputs = copy.deepcopy(_fixture("ups-on-battery")["inputs"]["battery-health"])
    inputs.update(overrides)
    return buildBatteryHealthState(**inputs)


# ---------------------------------------------------------------------------
# Fixtures: generated from the real builders, never hand-typed (Atlas L7).
# ---------------------------------------------------------------------------


def test_theUpsFixturesAreAllOnDisk_andTheGeneratorBuildsThem():
    names = {f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json")}
    assert _UPS_FIXTURES <= names
    assert _UPS_FIXTURES <= set(_generator().fixtureNames())


@pytest.mark.parametrize("name", sorted(_UPS_FIXTURES))
def test_everyUpsFixtureOnDiskIsWhatTheGeneratorBuilds(name: str):
    gen = _generator()
    assert _read(os.path.join(_FIXTURE_DIR, f"{name}.json")) == gen.render(
        gen.buildFixture(name)
    ), f"{name}.json is stale -- re-run tests/ui/fixtures/states/system/_generate.py"


@pytest.mark.parametrize("name", sorted(_UPS_FIXTURES))
def test_everyUpsFixtureIsTheBuildersOutputForItsStoredInputs(name: str):
    fx = _fixture(name)
    assert set(fx) == {"description", "now", "zone", "inputs", "payloads"}
    assert buildSystemStatusState(**fx["inputs"]["system-status"]) == (
        fx["payloads"]["system-status"]
    )
    assert buildBatteryHealthState(**fx["inputs"]["battery-health"]) == (
        fx["payloads"]["battery-health"]
    )


def test_theUpsFixturesCarryTheReadingTheirNameSays():
    status, battery = _payloads("ups-on-battery")
    assert status["power"]["source"] == "battery"
    assert battery["vcellV"] == 4.02
    assert battery["draining"] is True and battery["ladder"]["runtimeRemainingS"]
    assert status["priorShutdown"]["verdict"] == "clean"
    status, battery = _payloads("ups-gauge-unreadable")
    assert battery["source"]["ups"]["available"] is False
    assert status["power"]["source"] == "external"


# ---------------------------------------------------------------------------
# validationCriteria.
# ---------------------------------------------------------------------------


@_needsNode
def test_validation_upsOnBattery_isTheCellOnBatteryThreeSecondsAgo_neutral():
    status, battery = _payloads("ups-on-battery")
    row = _call("upsRowView", status, battery, _NOW_MS)
    view = _call("systemStatusView", status, None, battery, _NOW_MS)

    assert row["value"] == "4.02 V"
    assert row["sentence"] == "on battery " + MIDDLE_DOT + " 3 s ago"
    assert row["level"] == "secondary" and row["look"] != "amber"
    # Verdict unchanged: on battery counts nothing (s4.1: no UPS member).
    external = copy.deepcopy(_fixture("ups-on-battery")["inputs"]["system-status"])
    external["powerSource"] = "external"
    assert status["verdict"] == buildSystemStatusState(**external)["verdict"]
    assert view["verdict"] == {"text": "ALL OK", "level": "ok"}
    assert view["rows"][3] == row


@_needsNode
def test_validation_upsDetailOnBattery_hasLastStop_noLadder_noMinToCutoff():
    status, battery = _payloads("ups-on-battery")
    detail = _call("upsDetailView", status, battery, _NOW_MS)

    assert detail["lastStop"]["label"] == "LAST STOP"
    assert detail["lastStop"]["text"].startswith("CLEAN " + MIDDLE_DOT + " ")
    assert detail["lastStop"]["level"] == "neutral"
    flat = json.dumps(detail, ensure_ascii=False)
    assert "ladder" not in flat.lower()
    assert "min to cutoff" not in flat
    assert "DRAINING" not in flat


# ---------------------------------------------------------------------------
# The row (s4.5).
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(("power", "words"), [
    (dict(powerSource="external"), "on external power"),
    (dict(powerSource="battery"), "on battery"),
    (dict(powerSource="unknown", powerSourceReason=cse.REASON_POWER_SOURCE_PROVIDER_ABSENT),
     "power source unknown"),
    (dict(powerSource="unknown"), "power source unknown"),
    (dict(powerSource="mystery"), "power source unknown"),
])
def test_theSentenceIsTheSensedSourceFromSystemStatus(power, words):
    row = _call("upsRowView", _status(**power), _battery(), _NOW_MS)
    assert row["sentence"] == words + " " + MIDDLE_DOT + " 3 s ago"
    assert row["level"] == "secondary"


@_needsNode
def test_theSourceIsNeverDerivedFromBatteryHealth():
    """Atlas A1: two files, two facts. A draining battery-health payload
    beside an external system-status still reads external."""
    row = _call("upsRowView", _status(powerSource="external"),
                _battery(draining=True, charging=False), _NOW_MS)
    assert row["sentence"].startswith("on external power")
    row = _call("upsRowView", None, _battery(), _NOW_MS)
    assert row["sentence"].startswith("power source unknown")


@_needsNode
@pytest.mark.parametrize(("battery_ts", "age"), [
    ("2026-10-22T23:09:48Z", "12 s ago"),
    ("2026-10-22T23:09:59.900Z", "0 s ago"),     # floor
    ("2026-10-22T23:10:05Z", "0 s ago"),         # a future ts clamps at 0
    ("2026-10-22T21:00:00Z", "999+ s ago"),      # the cap
])
def test_theAgeIsFreshness_theM7Rule_neverJustNow(battery_ts, age):
    battery = _battery()
    battery["ts"] = battery_ts
    row = _call("upsRowView", _status(), battery, _NOW_MS)
    assert row["sentence"] == "on external power " + MIDDLE_DOT + " " + age
    assert "just now" not in row["sentence"]


@_needsNode
def test_theAgeIsTheSharedHelpersWords_notASecondVocabulary():
    for secs in (0, 3, 12, 998.7, 999, 1000, 5000):
        battery = _battery()
        battery["ts"] = datetime.fromtimestamp(_NOW_MS / 1000 - secs, tz=UTC).isoformat()
        row = _call("upsRowView", _status(), battery, _NOW_MS)
        assert row["sentence"].endswith(_call("freshAgeText", secs)), secs


@_needsNode
def test_anUndatedPayloadHasNoAge_andNoClockHasNoAge():
    battery = _battery()
    battery.pop("ts")
    assert _call("upsRowView", _status(), battery, _NOW_MS)["sentence"] == "on external power"
    assert _call("upsRowView", _status(), _battery(), None)["sentence"] == "on external power"


@_needsNode
def test_gaugeUnreadable_isTheTypedNa_dashDashPlusTheReason():
    status, battery = _payloads("ups-gauge-unreadable")
    row = _call("upsRowView", status, battery, _NOW_MS)
    assert row["word"] == "--" and row["look"] == "tertiary"
    assert row["value"] == "-- " + MIDDLE_DOT + " gauge unreadable"
    assert row["sentence"].startswith("on external power")


@_needsNode
def test_aNullCellOrNoPayloadReadsDashDash_neverAZero():
    row = _call("upsRowView", _status(), _battery(vcellV=None), _NOW_MS)
    assert (row["word"], row["value"]) == ("--", "--")
    row = _call("upsRowView", _status(), None, _NOW_MS)
    assert (row["word"], row["sentence"]) == ("--", "on external power")


@_needsNode
def test_theRowNeverCarriesSocOrARuntime():
    row = _call("upsRowView", _status(powerSource="battery"),
                _battery(soc=81, socCalibrated=True), _NOW_MS)
    text = row["value"] + row["sentence"]
    assert "%" not in text and "81" not in text
    assert "min" not in text


# ---------------------------------------------------------------------------
# The UPS detail (s4.6.1).
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(("reason", "words"), [
    (cse.REASON_POWER_SOURCE_PROVIDER_ABSENT, "no power sensor running"),
    (cse.REASON_POWER_SOURCE_UNREADABLE, "power sensor unreadable"),
    (cse.REASON_POWER_SOURCE_READ_FAILED, "power sensor read failed"),
])
def test_detail_eachTypedSourceReasonInItsW2Words(reason, words):
    status = _status(powerSource="unknown", powerSourceReason=reason)
    assert status["power"]["reasons"] == {"source": reason}
    detail = _call("upsDetailView", status, _battery(), _NOW_MS)
    row = _call("upsRowView", status, _battery(), _NOW_MS)
    assert detail["source"] == "power source unknown"
    assert detail["sourceReason"] == words
    assert len(words) <= 24
    assert row["sentence"].startswith("power source unknown")
    assert words not in row["sentence"]


@_needsNode
def test_detail_noReasonBesideAResolvedSource_andNoWordsForAnUntaughtOne():
    resolved = _status(powerSource="battery")
    resolved["power"]["reasons"] = {"source": cse.REASON_POWER_SOURCE_UNREADABLE}
    assert _call("upsDetailView", resolved, _battery(), _NOW_MS)["sourceReason"] is None
    untaught = _status(powerSource="unknown")
    untaught["power"]["reasons"] = {"source": "toString"}
    assert _call("upsDetailView", untaught, _battery(), _NOW_MS)["sourceReason"] is None


@_needsNode
def test_detail_neverSaysNoUpsFitted():
    statuses = [_status(powerSource="unknown", powerSourceReason=r)
                for r in cse.POWER_SOURCE_UNKNOWN_REASONS]
    details = _map("upsDetailView", [[s, _battery(), _NOW_MS] for s in statuses])
    assert "no UPS fitted" not in json.dumps(details)


@_needsNode
@pytest.mark.parametrize(("health", "value", "level"), [
    ("good", "GOOD", "ok"),
    ("degraded", "DEGRADED", "neutral"),
    ("replace", "REPLACE", "neutral"),
    ("unknown", "--", "unavailable"),
])
def test_detail_theHealthVerdictIsNeverAmberOrRed(health, value, level):
    detail = _call("upsDetailView", _status(), _battery(health=health), _NOW_MS)
    assert detail["health"]["value"] == value
    assert detail["health"]["level"] == level
    assert detail["health"]["level"] not in ("amber", "down", "red")


@_needsNode
def test_detail_aResolvedVerdictCarriesItsMarginWithTheJobHalf():
    detail = _call("upsDetailView", _status(), _battery(health="good"), _NOW_MS)
    assert detail["health"]["note"] == "11 min vs 40 s job"
    assert detail["healthCheck"] == "last health check " + MIDDLE_DOT + " 2026-10-20 (2 days ago)"


@_needsNode
def test_detail_anUnknownVerdictCarriesItsReason_neverAMargin_andTheF9Line():
    battery = _battery(health="unknown", healthReason="no_monthly_test")
    detail = _call("upsDetailView", _status(), battery, _NOW_MS)
    assert detail["health"]["note"] == "no monthly battery test yet"
    assert "job" not in detail["health"]["note"]
    assert detail["healthCheck"].startswith("last health check " + MIDDLE_DOT)


@_needsNode
def test_detail_theF9LineIsAlwaysThere_evenWithNoCheckEver():
    detail = _call("upsDetailView", _status(), _battery(lastHealthCheckTs=None), _NOW_MS)
    assert detail["healthCheck"] == "last health check " + MIDDLE_DOT + " never"


@_needsNode
@pytest.mark.parametrize(("kw", "soc"), [
    (dict(soc=92, socCalibrated=True), "≈ 92 % (modelled)"),
    (dict(soc=92, socCalibrated=False), "≈ 92 % (modelled, uncalibrated)"),
    (dict(soc=None), None),
])
def test_detail_theSocLine_onlyForARealNumber(kw, soc):
    assert _call("upsDetailView", _status(), _battery(**kw), _NOW_MS)["soc"] == soc


@_needsNode
def test_detail_gaugeUnreadable_isTheTypedNaAlone_lastStopStays():
    status, battery = _payloads("ups-gauge-unreadable")
    detail = _call("upsDetailView", status, battery, _NOW_MS)
    assert detail["cell"] == "-- " + MIDDLE_DOT + " gauge unreadable"
    assert detail["health"] is None and detail["soc"] is None
    assert detail["healthCheck"] is None
    assert detail["lastStop"]["text"].startswith("CLEAN")


@_needsNode
def test_detail_lastStopIsTheShippedPriorShutdownTile_unchanged():
    status, battery = _payloads("ups-on-battery")
    detail = _call("upsDetailView", status, battery, _NOW_MS)
    tile = _call("priorShutdownTile", status["priorShutdown"], status["ts"])
    assert detail["lastStop"] == {
        "label": tile["label"],
        "text": tile["value"] + " " + MIDDLE_DOT + " " + tile["detail"],
        "level": "neutral",
    }


@_needsNode
def test_detail_labelIsThePiUpsBattery_neverTheVehicle():
    status, battery = _payloads("ups-on-battery")
    assert _call("upsDetailView", status, battery, _NOW_MS)["label"] == "Pi UPS battery"


# ---------------------------------------------------------------------------
# The rendered page (DOM) + the words gate.
# ---------------------------------------------------------------------------


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _render(name: str, *, parked: bool = False, steps: list[dict] | None = None):
    status, battery = _payloads(name)
    routes: dict[str, Any] = {"/system-status": status, "/battery-health": battery}
    if parked:
        routes["/gear"] = _gearParked()
    allSteps = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}] + (steps or [])
    tree = rh.runDashboard(routes=routes, steps=allSteps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _openUps() -> list[dict]:
    return [{"clickNth": {"selector": ".sys-row", "index": 3}}, {"flush": 1}]


def _text(node: dict) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _text(child))
    return "".join(out)


def _rowPath(surface, key: str):
    rows = [p for p in surface.pathsByClass("sys-row")
            if p[-1]["attrs"].get("data-row") == key]
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


def _systemCard(surface):
    cards = [p for p in surface.pathsByClass("card")
             if p[-1]["attrs"].get("data-state") == "system-status"]
    assert len(cards) == 1
    return cards[0]


@_needsNode
def test_dom_theRowsAreObdDataWifiUps_inOrder_andTheTickReadsBatteryHealth(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("ups-on-battery")
    rows = surface.pathsByClass("sys-row")
    assert [r[-1]["attrs"]["data-row"] for r in rows] == ["obd", "data", "wifi", "ups"]
    row = _text(_rowPath(surface, "ups")[-1])
    # Atlas P8: the cell came from states/battery-health, fetched by the tick.
    assert row.startswith("UPS")
    assert "4.02 V" in row
    assert ("on battery " + MIDDLE_DOT + " ") in row


@_needsNode
def test_dom_theUpsRowValueIsPrimary_theSentenceSecondary_nothingAmber(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("ups-on-battery")
    row = _rowPath(surface, "ups")
    for path in _descendants(row):
        cls = set((path[-1].get("attrs", {}).get("class") or "").split())
        colour = surface.winningDeclaration(path, "color")
        if "sys-row-word" in cls:
            assert colour[0] == PRIMARY
        if "sys-row-sentence" in cls:
            assert colour[0] == SECONDARY
        if {"sys-row-word", "sys-row-sentence", "sys-row-tail"} & cls:
            assert colour is None or colour[0] != AMBER


@_needsNode
@pytest.mark.parametrize("name", sorted(_UPS_FIXTURES))
def test_dom_wordsGate_theSystemPageAndTheUpsDetail(name: str, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(name, parked=True, steps=_openUps())
    assert _text(surface.pathById("sys-detail-head")[-1]) == "UPS"
    page = _text(_systemCard(surface)[-1])
    detail = _text(surface.pathById("sys-detail-body")[-1])
    for text in (page, detail):
        assert _BANNED.search(text) is None, _BANNED.search(text)
    assert "%" not in _text(_rowPath(surface, "ups")[-1])
    assert surface.pathsByClass("ladder") == []
    assert "LAST STOP" in detail


@_needsNode
def test_dom_parked_theUpsRowOpensTheUpsDetail(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("ups-on-battery", parked=True, steps=_openUps())
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None
    body = _text(surface.pathById("sys-detail-body")[-1])
    for words in ("Pi UPS battery", "CELL", "4.02 V", "SOURCE", "on battery", "HEALTH",
                  "GOOD", "11 min vs 40 s job", "last health check", "SOC",
                  "≈ 81 % (modelled, uncalibrated)", "LAST STOP", "CLEAN"):
        assert words in body, words
    assert "SENSOR" not in body  # a resolved source carries no reason
    chip = surface.pathById("version-chip")
    assert chip[-1]["attrs"].get("hidden") is not None


@_needsNode
def test_dom_notParked_theUpsRowOpensNothing(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("ups-on-battery", parked=False, steps=_openUps())
    assert surface.pathsByClass("sys-chevron") == []
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is not None


# ---------------------------------------------------------------------------
# The Battery card is gone (source checks; always run).
# ---------------------------------------------------------------------------


def test_theBatteryCardIsGoneFromTheMarkup():
    html = _read(_DASHBOARD_HTML)
    assert 'data-state="battery-health"' not in html
    assert 'data-page-name="BATTERY"' not in html


def test_theDeletedViewsAndTheirCssAreGone_noUnreachableBranch():
    source = _read(_CAROUSEL_JS)
    for name in ("batteryHealthView", "ladderView", "socTile", "renderBatteryHealthBody",
                 "appendLadder", "powerTile"):
        assert re.search(r"function " + name + r"\b", source) is None, name
        assert re.search(r"^\s*" + name + r":", source, flags=re.M) is None, name
    assert 'key: "battery-health"' not in source
    assert re.search(r"^\s*\.ladder", _read(_DASHBOARD_CSS), flags=re.M) is None


def test_theKeptHelpersStay():
    source = _read(_CAROUSEL_JS)
    for name in ("vcellTile", "healthValue", "healthLevel", "healthReasonText",
                 "healthMarginText", "healthCheckLine", "priorShutdownTile"):
        assert re.search(r"function " + name + r"\(", source), name
    for name in ("BATTERY_HEALTH_REASON_TEXT", "PRIOR_SHUTDOWN_WORDS"):
        assert re.search(r"var " + name + r" = ", source), name


# ---------------------------------------------------------------------------
# Cross-language guard (W2): no literal twins of the reason vocabulary.
# ---------------------------------------------------------------------------


def _jsLiteral(name: str) -> str:
    m = re.search(r"var " + name + r" = (.*?);\n", _read(_CAROUSEL_JS), flags=re.S)
    assert m, name
    return m.group(1)


def test_theJsCopyOfThePowerSourceReasonsIsTheProducers():
    keys = re.findall(r"(\w+):", _jsLiteral("POWER_SOURCE_REASON_WORDS"))
    assert tuple(keys) == cse.POWER_SOURCE_UNKNOWN_REASONS
    sources = set(re.findall(r"(\w+):", _jsLiteral("POWER_SOURCE_WORDS")))
    assert sources == {"external", "battery"}
