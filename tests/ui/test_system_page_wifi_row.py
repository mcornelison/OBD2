################################################################################
# File Name: test_system_page_wifi_row.py
# Purpose/Description: US-894-d (spec specs/v030-system-page-design.md s4.0,
#   s4.4, s4.6, s7; Iris I5, W1; Atlas A6) -- the System page's WIFI row, its
#   parked detail and the top-bar WiFi glyph.
#
#   What is pinned here:
#     - the four WIFI fixtures the story names are exactly what _generate.py
#       builds from the REAL builders (never hand-typed);
#     - both validationCriteria (wifi-weak-home, wifi-nmcli-absent);
#     - the s4.4 table, row by row, keyed on (state, reason) -- including the
#       W1 associated-no-level case and the A6 `down` reading;
#     - wifiGlyphState: weak -> neutral, read_failed amber BEFORE the unread
#       return, null -> dim with no slash, down -> slashed;
#     - the colour rule (s4.0): amber on the WIFI row and glyph IFF the `wifi`
#       verdict member; the page applies no RSSI threshold;
#     - the parked WIFI detail (no IP row);
#     - ONE cross-language guard for the JS copies of the WiFi vocabulary
#       (wifi_reader.WIFI_REASON_*, REASON_WIFI_UNKNOWN, VERDICT_WIFI and the
#       deriveWifiState bands).
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
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-d System page WIFI row.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-e): the UPS row follows WIFI.
# ================================================================================
################################################################################

"""US-894-d tests: the System page's WIFI row, its detail and the WiFi glyph."""

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

from pi.network import wifi_reader  # noqa: E402
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
_DASHBOARD_HTML = os.path.join(_DASH, "dashboard.html")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")

GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
SECONDARY = "var(--text-secondary)"
TERTIARY = "var(--text-tertiary)"
MIDDLE_DOT = "·"

_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = 1761174600000

# The fixtures this story names (acceptance: "This story adds only the
# fixtures it names").
_WIFI_FIXTURES = {"wifi-weak-home", "wifi-not-read", "wifi-nmcli-absent", "wifi-read-failed"}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _generator():
    spec = importlib.util.spec_from_file_location(
        "system_fixture_generator_d", os.path.join(_FIXTURE_DIR, "_generate.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _status(name: str) -> dict:
    return _fixture(name)["payloads"]["system-status"]


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


def _members(status: dict) -> list[str]:
    return [m["key"] for m in status["verdict"]["members"]]


def _wifiStatus(
    *,
    available: bool,
    ssid: str | None = "DeathstarWifi",
    rssi: int | None = -55,
    home: bool | None = True,
    reason: str | None = None,
) -> dict:
    """A system-status built by the REAL builder for one WiFi reading."""
    return buildSystemStatusState(
        syncLastOkTs=_NOW, syncStale=False, powerSource="external",
        driveState="idle", driveId=None, nowIso=_NOW,
        wifiAvailable=available, wifiSsid=ssid, wifiRssiDbm=rssi, wifiHome=home,
        wifiTs=_NOW, wifiUnavailableReason=reason,
    )


# ---------------------------------------------------------------------------
# Fixtures: generated from the real builders, never hand-typed (Atlas L7).
# ---------------------------------------------------------------------------


def test_theWifiFixturesAreAllOnDisk_andTheGeneratorBuildsThem():
    names = {f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json")}
    assert _WIFI_FIXTURES <= names
    assert _WIFI_FIXTURES <= set(_generator().fixtureNames())


@pytest.mark.parametrize("name", sorted(_WIFI_FIXTURES))
def test_everyWifiFixtureOnDiskIsWhatTheGeneratorBuilds(name: str):
    gen = _generator()
    assert _read(os.path.join(_FIXTURE_DIR, f"{name}.json")) == gen.render(
        gen.buildFixture(name)
    ), f"{name}.json is stale -- re-run tests/ui/fixtures/states/system/_generate.py"


@pytest.mark.parametrize("name", sorted(_WIFI_FIXTURES))
def test_everyWifiFixtureIsTheBuildersOutputForItsStoredInputs(name: str):
    fx = _fixture(name)
    assert buildSystemStatusState(**fx["inputs"]["system-status"]) == (
        fx["payloads"]["system-status"]
    )
    assert set(fx) == {"description", "now", "zone", "inputs", "payloads"}


def test_theWifiFixturesCarryTheReadingTheirNameSays():
    assert _status("wifi-weak-home")["wifi"]["state"] == "weak"
    assert _status("wifi-weak-home")["wifi"]["home"] is True
    for name, reason in (("wifi-not-read", sse.REASON_WIFI_UNKNOWN),
                         ("wifi-nmcli-absent", wifi_reader.WIFI_REASON_NMCLI_ABSENT),
                         ("wifi-read-failed", wifi_reader.WIFI_REASON_READ_FAILED)):
        assert _status(name)["source"]["wifi"] == {"available": False, "reason": reason}
    assert _members(_status("wifi-read-failed")) == [sse.VERDICT_WIFI]
    for name in ("wifi-weak-home", "wifi-not-read", "wifi-nmcli-absent"):
        assert _status(name)["verdict"]["issueCount"] == 0, name


# ---------------------------------------------------------------------------
# validationCriteria.
# ---------------------------------------------------------------------------


@_needsNode
def test_validation_wifiWeakHome_isHomeGreen_weakSignal_glyphNeutral():
    status = _status("wifi-weak-home")
    row = _call("wifiRowView", status)
    view = _call("systemStatusView", status, None)

    assert (row["word"], row["look"]) == ("home", "ok")
    assert row["sentence"] == "DeathstarWifi " + MIDDLE_DOT + " weak signal"
    assert row["level"] == "secondary"
    assert view["glyphs"]["wifi"] == "neutral"


@_needsNode
def test_validation_wifiNmcliAbsent_isNoData_noWifiTool_uncounted():
    status = _status("wifi-nmcli-absent")
    row = _call("wifiRowView", status)
    view = _call("systemStatusView", status, None)

    assert (row["word"], row["look"]) == ("--", "tertiary")
    assert row["sentence"] == "no WiFi tool on this host"
    assert row["level"] == "secondary"
    assert status["verdict"]["issueCount"] == 0
    assert view["verdict"] == {"text": "ALL OK", "level": "ok"}
    assert view["glyphs"]["wifi"] == "dim"


# ---------------------------------------------------------------------------
# The s4.4 table, row by row (from the real builder).
# ---------------------------------------------------------------------------


_TABLE = [
    # (label, builder kwargs, word, look, sentence, glyph)
    ("up home", dict(available=True, rssi=-52, home=True),
     "home", "ok", "DeathstarWifi · good signal", "ok"),
    ("weak home", dict(available=True, rssi=-77, home=True),
     "home", "ok", "DeathstarWifi · weak signal", "neutral"),
    ("up other", dict(available=True, ssid="Starbucks", rssi=-60, home=False),
     "other network", "secondary", "Starbucks · good signal", "ok"),
    ("weak other", dict(available=True, ssid="Starbucks", rssi=-79, home=False),
     "other network", "secondary", "Starbucks · weak signal", "neutral"),
    ("up home unknown", dict(available=True, rssi=-52, home=None),
     "connected", "secondary", "DeathstarWifi · good signal", "ok"),
    # W1: associated (ssid known), no signal level -> the home word, unslashed.
    ("associated no level", dict(available=True, rssi=None, home=True),
     "home", "ok", "DeathstarWifi · no signal level", "dim"),
    ("associated no level, home null", dict(available=True, rssi=None, home=None),
     "connected", "secondary", "DeathstarWifi · no signal level", "dim"),
    # A6: not associated is a READING -- state down, reason null.
    ("not associated", dict(available=True, ssid=None, rssi=None, home=False),
     "down", "tertiary", "not connected", "down"),
    ("not read", dict(available=False, reason=sse.REASON_WIFI_UNKNOWN),
     "--", "tertiary", "not read yet", "dim"),
    ("nmcli absent", dict(available=False, reason=wifi_reader.WIFI_REASON_NMCLI_ABSENT),
     "--", "tertiary", "no WiFi tool on this host", "dim"),
]


@_needsNode
def test_theS44Table_rowByRow_fromTheRealBuilder():
    statuses = [_wifiStatus(**kw) for _l, kw, *_ in _TABLE]
    rows = _map("wifiRowView", [[s] for s in statuses])
    glyphs = _map("wifiGlyphState", [[s] for s in statuses])
    for (label, _kw, word, look, sentence, glyph), status, row, g in zip(
        _TABLE, statuses, rows, glyphs, strict=True
    ):
        assert status["verdict"]["issueCount"] == 0, label
        assert (row["word"], row["look"]) == (word, look), label
        assert row["sentence"] == sentence, label
        assert row["level"] == "secondary", label
        assert g == glyph, label
        assert row["word"] != "down" or status["wifi"]["state"] == "down", label


@_needsNode
def test_readFailed_isQuestionNotRead_amber_theMembersReasonVerbatim():
    status = _wifiStatus(available=False, reason=wifi_reader.WIFI_REASON_READ_FAILED)
    row = _call("wifiRowView", status)
    reason = status["verdict"]["members"][0]["reason"]

    assert _members(status) == ["wifi"]
    assert (row["word"], row["look"], row["level"]) == ("? not read", "amber", "amber")
    assert row["sentence"] == reason
    assert _call("wifiGlyphState", status) == "amber"


@_needsNode
def test_associatedNoLevel_isNeverDownOrNotRead_toldBySourceAvailable_notBySsid():
    """W1: the page tells associated-no-level from an unread link by
    source.wifi.available, never by a missing ssid."""
    linked = _wifiStatus(available=True, rssi=None, home=True)
    assert linked["wifi"]["state"] is None
    row = _call("wifiRowView", linked)
    assert row["word"] not in ("--", "down")
    assert "not read" not in row["sentence"]
    # Same null state, ssid planted, but the link not read: never the home word.
    unread = _wifiStatus(available=False, reason=sse.REASON_WIFI_UNKNOWN)
    unread["wifi"]["ssid"] = "DeathstarWifi"
    row = _call("wifiRowView", unread)
    assert row["word"] == "--" and row["sentence"] == "not read yet"


@_needsNode
def test_thePageAppliesNoRssiThreshold_theWordIsTheEmittersState():
    """The emitter derives state; the page prints it whatever the dBm says."""
    status = _wifiStatus(available=True, rssi=-52, home=True)
    status["wifi"]["state"] = "weak"  # a dBm the page would call strong
    assert _call("wifiRowView", status)["sentence"].endswith("weak signal")
    status["wifi"].update(state="up", rssiDbm=-85)  # a dBm the page would call weak
    assert _call("wifiRowView", status)["sentence"].endswith("good signal")
    assert _call("wifiGlyphState", status) == "ok"


# ---------------------------------------------------------------------------
# The colour rule (s4.0): amber IFF the wifi member -- swept.
# ---------------------------------------------------------------------------

_READINGS = [
    dict(available=True, rssi=-52, home=True),
    dict(available=True, rssi=-77, home=False),
    dict(available=True, rssi=-95, home=True),     # banded down while associated
    dict(available=True, rssi=None, home=None),
    dict(available=True, ssid=None, rssi=None, home=None),
    dict(available=False, reason=sse.REASON_WIFI_UNKNOWN),
    dict(available=False, reason=wifi_reader.WIFI_REASON_NMCLI_ABSENT),
    dict(available=False, reason=wifi_reader.WIFI_REASON_READ_FAILED),
]


def _withMember(status: dict, member: bool) -> dict:
    members = [m for m in status["verdict"]["members"] if m["key"] != "wifi"]
    if member:
        members.append({"key": "wifi", "reason": "WiFi couldn't be read."})
    status["verdict"] = {"issueCount": len(members), "members": members}
    return status


@_needsNode
def test_amberIffTheWifiMember_sweptOverEveryReadingAndMemberPresence():
    cases = list(itertools.product(range(len(_READINGS)), (False, True)))
    statuses = [_withMember(_wifiStatus(**_READINGS[i]), m) for i, m in cases]
    rows = _map("wifiRowView", [[s] for s in statuses])
    glyphs = _map("wifiGlyphState", [[s] for s in statuses])
    for (i, member), row, glyph in zip(cases, rows, glyphs, strict=True):
        label = (_READINGS[i], member)
        assert (row["look"] == "amber") is member, label
        assert (row["level"] == "amber") is member, label
        assert (glyph == "amber") is member, label
        if member:
            assert row["sentence"] == "WiFi couldn't be read.", label
        # weak is never amber of itself: only the member paints it.
        if _READINGS[i].get("rssi") == -77 and not member:
            assert glyph == "neutral" and row["look"] != "amber", label


@_needsNode
def test_readFailedWithNoMember_isNeverAmber():
    """A verdict-absent file over a failed read: nothing counted it, so
    nothing is amber (s4.0) -- the words still say it was not read."""
    status = _wifiStatus(available=False, reason=wifi_reader.WIFI_REASON_READ_FAILED)
    status.pop("verdict")
    row = _call("wifiRowView", status)
    assert row["word"] == "? not read"
    assert row["look"] != "amber" and row["level"] != "amber"
    assert _call("wifiGlyphState", status) != "amber"


@_needsNode
def test_wifiGlyph_noPayload_isDim_neverAClaim():
    assert _map("wifiGlyphState", [[None], [{}], [{"wifi": {"state": "up"}}]]) == [
        "dim", "dim", "dim",
    ]


# ---------------------------------------------------------------------------
# The WIFI detail (s4.6, parked).
# ---------------------------------------------------------------------------


@_needsNode
def test_detail_weakHome_ssidStrengthDbmHome_noIp():
    detail = _call("wifiDetailView", _status("wifi-weak-home"))

    assert detail["head"] == "WIFI"
    assert (detail["state"]["text"], detail["state"]["look"]) == ("home", "ok")
    assert detail["network"] == "DeathstarWifi"
    assert detail["strength"] == "weak " + MIDDLE_DOT + " -77 dBm"
    assert detail["home"] == "yes"
    assert detail["link"] is None
    assert detail["reason"] is None
    assert not any("ip" in k.lower() for k in detail), detail


@_needsNode
@pytest.mark.parametrize(("reading", "strength", "link", "home", "reason"), [
    (dict(available=True, rssi=-52, home=False), "good · -52 dBm", None, "no", None),
    (dict(available=True, rssi=None, home=None), "no signal level", None, "unknown", None),
    (dict(available=True, ssid=None, rssi=None, home=None), "--",
     "not connected to any network", "unknown", None),
    (dict(available=False, reason=sse.REASON_WIFI_UNKNOWN), "--", None, "unknown",
     "not read yet"),
    (dict(available=False, reason=wifi_reader.WIFI_REASON_NMCLI_ABSENT), "--", None,
     "unknown", "no WiFi tool on this host"),
    (dict(available=False, reason=wifi_reader.WIFI_REASON_READ_FAILED), "--", None,
     "unknown", "WiFi couldn't be read."),
])
def test_detail_everyReading(reading, strength, link, home, reason):
    status = _wifiStatus(**reading)
    detail = _call("wifiDetailView", status)
    assert detail["strength"] == strength
    assert detail["link"] == link
    assert detail["home"] == home
    assert detail["reason"] == reason
    assert (detail["reasonLevel"] == "amber") is ("wifi" in _members(status))


# ---------------------------------------------------------------------------
# The rendered page (DOM).
# ---------------------------------------------------------------------------


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _render(status: dict, *, parked: bool = False, steps: list[dict] | None = None):
    routes: dict[str, Any] = {"/system-status": status}
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


def _wifiRowPath(surface):
    rows = [p for p in surface.pathsByClass("sys-row")
            if p[-1]["attrs"].get("data-row") == "wifi"]
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
@pytest.mark.parametrize("name", sorted(_WIFI_FIXTURES))
def test_dom_theAmberOnTheWifiRowAndGlyphIsExactlyTheWifiMember(name: str, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    status = _status(name)
    surface = _render(status)
    row = _wifiRowPath(surface)
    member = "wifi" in _members(status)

    ambers = []
    for path in _descendants(row):
        cls = set((path[-1].get("attrs", {}).get("class") or "").split())
        if {"sys-row-word", "sys-row-sentence"} & cls:
            colour = surface.winningDeclaration(path, "color")
            if colour and colour[0] == AMBER:
                ambers.append(_text(path[-1]))
    glyph = surface.pathById("glyph-wifi")
    glyphColour = surface.winningDeclaration(glyph, "color")
    if member:
        assert sorted(ambers) == sorted(["? not read", "WiFi couldn't be read."]), ambers
        assert glyphColour[0] == AMBER
    else:
        assert ambers == [], ambers
        assert glyphColour is None or glyphColour[0] != AMBER
    assert _text(row[-1]).startswith("WIFI")


@_needsNode
def test_dom_theRowsAreObdDataWifi_inOrder(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_status("wifi-weak-home"))
    rows = surface.pathsByClass("sys-row")
    # MOVED PIN (US-894-e): the UPS row follows the WIFI row.
    assert [r[-1]["attrs"]["data-row"] for r in rows] == ["obd", "data", "wifi", "ups"]


@_needsNode
def test_dom_weakHome_isGreenHome_andTheGlyphIsNeutralSecondary(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_status("wifi-weak-home"))
    row = _wifiRowPath(surface)
    assert ("DeathstarWifi " + MIDDLE_DOT + " weak signal") in _text(row[-1])
    word = [p for p in _descendants(row)
            if "sys-row-word" in (p[-1].get("attrs", {}).get("class") or "")][0]
    assert _text(word[-1]) == "home"
    assert surface.winningDeclaration(word, "color")[0] == GREEN
    glyph = surface.pathById("glyph-wifi")
    assert glyph[-1]["attrs"]["data-state"] == "neutral"
    assert surface.winningDeclaration(glyph, "color")[0] == SECONDARY


@_needsNode
@pytest.mark.parametrize(("reading", "state", "colour", "slashed"), [
    (dict(available=False, reason=sse.REASON_WIFI_UNKNOWN), "dim", TERTIARY, False),
    (dict(available=True, rssi=None, home=True), "dim", TERTIARY, False),
    (dict(available=True, ssid=None, rssi=None, home=None), "down", TERTIARY, True),
    (dict(available=True, rssi=-52, home=True), "ok", GREEN, False),
])
def test_dom_theGlyph_dimHasNoSlash_downIsSlashed_neitherIsAmber(
    reading, state, colour, slashed, monkeypatch
):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_wifiStatus(**reading))
    glyph = surface.pathById("glyph-wifi")
    assert glyph[-1]["attrs"]["data-state"] == state
    assert surface.winningDeclaration(glyph, "color")[0] == colour
    slash = surface.pathsByClass("wifi-slash")
    assert len(slash) == 1
    assert surface.rendered(slash[0]) is slashed


def test_theGlyphSlashIsInTheMarkup_relativeUnitsOnly():
    html = _read(_DASHBOARD_HTML)
    m = re.search(r'<span [^>]*id="glyph-wifi"[^>]*>(.*?)</span>', html, re.DOTALL)
    assert m is not None
    inner = m.group(1)
    assert len(re.findall(r'class="wifi-slash"', inner)) == 1
    assert "px" not in inner


@_needsNode
def test_dom_parked_theWifiRowOpensTheWifiDetail(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(
        _status("wifi-read-failed"), parked=True,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 2}}, {"flush": 1}],
    )
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None
    assert _text(surface.pathById("sys-detail-head")[-1]) == "WIFI"
    body = _text(surface.pathById("sys-detail-body")[-1])
    for words in ("STATE", "? not read", "NETWORK", "STRENGTH", "HOME NETWORK", "unknown",
                  "REASON", "WiFi couldn't be read."):
        assert words in body, words
    assert "IP" not in body.replace("SHIP", "")
    reason = [p for p in surface.pathsByClass("wifi-reason")]
    assert len(reason) == 1
    text = [p for p in _descendants(reason[0])
            if "sys-diag-text" in (p[-1].get("attrs", {}).get("class") or "")][0]
    assert surface.winningDeclaration(text, "color")[0] == AMBER
    chip = surface.pathById("version-chip")
    assert chip[-1]["attrs"].get("hidden") is not None


@_needsNode
def test_dom_notParked_theWifiRowOpensNothing(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(
        _status("wifi-weak-home"), parked=False,
        steps=[{"clickNth": {"selector": ".sys-row", "index": 2}}, {"flush": 1}],
    )
    assert surface.pathsByClass("sys-chevron") == []
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is not None


# ---------------------------------------------------------------------------
# Cross-language guard (source check; always runs). Atlas A6: no literal
# twins -- the page's reason keys are the producer's constants.
# ---------------------------------------------------------------------------


def _jsLiteral(name: str) -> str:
    source = _read(_CAROUSEL_JS)
    m = re.search(r"var " + name + r" = (.*?);\n", source, flags=re.S)
    assert m, name
    return m.group(1)


def test_theJsCopyOfTheWifiVocabularyIsTheProducers():
    assert _jsLiteral("WIFI_REASON_NOT_READ") == '"' + sse.REASON_WIFI_UNKNOWN + '"'
    assert _jsLiteral("WIFI_REASON_NMCLI_ABSENT") == (
        '"' + wifi_reader.WIFI_REASON_NMCLI_ABSENT + '"'
    )
    assert _jsLiteral("WIFI_REASON_READ_FAILED") == (
        '"' + wifi_reader.WIFI_REASON_READ_FAILED + '"'
    )
    assert _jsLiteral("WIFI_MEMBER_KEY") == '"' + sse.VERDICT_WIFI + '"'
    # The reason words cover the two absences, and nothing outside the
    # producer's vocabulary (read_failed speaks through its member).
    words = set(re.findall(r"(\w+):", _jsLiteral("WIFI_REASON_WORDS")))
    assert words == {sse.REASON_WIFI_UNKNOWN, wifi_reader.WIFI_REASON_NMCLI_ABSENT}
    # The band words are exactly the linked bands deriveWifiState publishes.
    bands = {
        sse.deriveWifiState(associated=a, rssiDbm=r)
        for a, r in itertools.product((None, False, True), (None, -40, -75, -95))
    }
    assert bands == {None, "up", "weak", "down"}
    for name in ("WIFI_SIGNAL_WORD", "WIFI_STRENGTH_WORD"):
        assert set(re.findall(r"(\w+):", _jsLiteral(name))) == {"up", "weak"}, name
    assert _jsLiteral("WIFI_STATE_DOWN") == '"down"'
    assert "down" in bands
