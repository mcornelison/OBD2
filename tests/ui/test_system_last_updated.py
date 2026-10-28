################################################################################
# File Name: test_system_last_updated.py
# Purpose/Description: US-894-g (spec specs/v030-system-page-design.md s4.6.3;
#   Iris X-1 = (a), Iris S119 review; Atlas S119 gate Q1 + re-gate 2026-10-27)
#   -- System's UPDATED link, the LAST UPDATED detail, and the shared
#   page-detail kit (the sibling host of #sys-detail, its '‹ BACK', the R1
#   closer and the detail button) that Engine, Fuel and Motion reuse next.
#
#   What is pinned here:
#     - UPDATED sits LEFT of SETTINGS › on the verdict line in every system
#       fixture, in the .sys-settings type WITHOUT margin-left:auto; ' ›' and
#       the tap only while parked;
#     - LAST UPDATED lists OBD, IMU, LIGHT, UPS, WIFI, SYNC in that order, each
#       '<age> · <time>' (the M7 age, fmtTimeOfDay with seconds) or '--' when
#       undated; WIFI only while source.wifi.available is true; no line carries
#       data-state / data-level / data-member, and the colours are neutral;
#     - the age grows while the file is unchanged (advanceMs);
#     - the host: head 34 px (border-box, its rule inside), host padding 0,
#       body 270 = 320 - 34 - 8 - 8 from the DECLARED properties; '‹ BACK' hit
#       box >= --tap-min and its bottom at or above the first body child;
#     - the shared open helper's ONLY gate is currentParked(): it opens with no
#       system-status loaded; R1 closes an open detail on gear D and on
#       link_down (parked unknown);
#     - the detail button's cascade (Michroma --fs-label label, mono ' ›',
#       --text-primary, 1px --text-secondary border, --radius, 12 px each side,
#       --tap-min tall, hidden while not parked, no state colour);
#     - Q1: a MODELLED height budget (6 x 44 = 264 of 270) and width budget
#       (the widest value '999+ s ago · 12:59:59 PM') read from the declared
#       CSS/tokens, each with a planted-overflow negative control that FAILS.
#
#   Skipped when node is not on PATH -- the CSS models always run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-27    | Ralph (Rex)  | Initial -- US-894-g LAST UPDATED + page-detail kit.
# ================================================================================
################################################################################

"""US-894-g tests: UPDATED ›, LAST UPDATED and the shared page-detail kit."""

from __future__ import annotations

import copy
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

from tests.ui.test_topbar_three_column_grid import (  # noqa: E402
    PI_MONO_ADVANCE_EM,
    michromaWidthPx,
)

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_ZONE = "America/Chicago"
_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_CSS = os.path.join(_DASH, "dashboard.css")
_HTML = os.path.join(_DASH, "dashboard.html")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")
_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)

SIX_DEVICES = ["OBD", "IMU", "LIGHT", "UPS", "WIFI", "SYNC"]
NO_DATA = "--"
TITLE = "LAST UPDATED"
WIDEST_VALUE = "999+ s ago · 12:59:59 PM"
STATE_ATTRS = ("data-state", "data-level", "data-member")
STATE_TOKENS = ("--amber-warn", "--green-ok", "--critical-red")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fixtureNames() -> list[str]:
    return sorted(f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json"))


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _payloads(name: str) -> dict[str, Any]:
    return copy.deepcopy(_fixture(name)["payloads"])


def _map(fn: str, argLists: list[list[Any]]) -> list[Any]:
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


def _values(view: dict) -> dict[str, str]:
    return {r["label"]: r["value"] for r in view["rows"]}


# ---------------------------------------------------------------------------
# The view (pure, node): order, the M7 age, the time form, the undated rule.
# ---------------------------------------------------------------------------


@_needsNode
def test_theViewListsTheSixDevicesInOrder_underLastUpdated():
    p = _payloads("all-ok-driving")
    view = _call("lastUpdatedView", p["system-status"], p["capture-health"], _NOW_MS)
    assert view["head"] == TITLE
    assert [r["label"] for r in view["rows"]] == SIX_DEVICES
    assert [r["key"] for r in view["rows"]] == ["obd", "imu", "light", "ups", "wifi", "sync"]


@_needsNode
def test_theStoryExample_imuTwoSecondsBeforeTheFile():
    """IMU capture-health ts 21:20:14 local with lastSampleSecondsAgo 2 ->
    'IMU  2 s ago · 9:20:12 PM' (the age is the M7 rule, the time has no date)."""
    p = _payloads("all-ok-driving")
    capture = p["capture-health"]
    capture["ts"] = "2026-10-23T02:20:14Z"  # 21:20:14 CDT
    capture["feeds"]["imu"]["lastSampleSecondsAgo"] = 2
    nowMs = int(datetime(2026, 10, 23, 2, 20, 14, tzinfo=UTC).timestamp() * 1000)
    values = _values(_call("lastUpdatedView", p["system-status"], capture, nowMs))
    assert values["IMU"] == "2 s ago · 9:20:12 PM"
    assert "Oct" not in values["IMU"] and "2026" not in values["IMU"]


@_needsNode
def test_feedAge_isNowMinusTheFileTsMinusTheFeedsSecondsAgo():
    p = _payloads("all-ok-driving")
    capture = p["capture-health"]
    capture["feeds"]["obd"]["lastSampleSecondsAgo"] = 3
    # The file was written 10 s before now: the OBD row is 13 s old.
    values = _values(_call("lastUpdatedView", p["system-status"], capture, _NOW_MS + 10_000))
    assert values["OBD"] == "13 s ago · 6:09:57 PM"


@_needsNode
def test_syncAndWifi_areNowMinusTheirOwnStamps():
    p = _payloads("all-ok-driving")
    status = p["system-status"]
    values = _values(_call("lastUpdatedView", status, p["capture-health"], _NOW_MS))
    # sync.lastOkTs 22:55:12Z is 888 s before now; wifi.ts is now.
    assert status["sync"]["lastOkTs"] == "2026-10-22T22:55:12Z"
    assert values["SYNC"] == "888 s ago · 5:55:12 PM"
    assert values["WIFI"] == "0 s ago · 6:10:00 PM"


@_needsNode
def test_theWidestAge_isCappedAt999Plus():
    p = _payloads("all-ok-driving")
    p["system-status"]["sync"]["lastOkTs"] = "2026-10-22T05:59:59Z"
    values = _values(_call("lastUpdatedView", p["system-status"], p["capture-health"], _NOW_MS))
    assert values["SYNC"] == "999+ s ago · 12:59:59 AM"


@_needsNode
def test_undated_isTwoHyphens_everyWay():
    """(a) Undated -> '--': a null lastOkTs, a feed with no seconds-ago, a
    capture file with no ts, and no file at all."""
    p = _payloads("all-ok-driving")
    p["system-status"]["sync"]["lastOkTs"] = None
    p["capture-health"]["feeds"]["imu"]["lastSampleSecondsAgo"] = None
    values = _values(_call("lastUpdatedView", p["system-status"], p["capture-health"], _NOW_MS))
    assert values["SYNC"] == NO_DATA
    assert values["IMU"] == NO_DATA
    assert values["OBD"] != NO_DATA
    undatedFile = copy.deepcopy(p["capture-health"])
    undatedFile.pop("ts")
    values = _values(_call("lastUpdatedView", p["system-status"], undatedFile, _NOW_MS))
    assert [values[k] for k in ("OBD", "IMU", "LIGHT", "UPS")] == [NO_DATA] * 4
    nothing = _values(_call("lastUpdatedView", None, None, _NOW_MS))
    assert list(nothing.values()) == [NO_DATA] * 6


@_needsNode
@pytest.mark.parametrize("name", ["wifi-read-failed", "wifi-nmcli-absent", "wifi-not-read"])
def test_wifi_isTwoHyphens_unlessTheReadSucceeded(name):
    """Atlas RULED: a failed read also stamps wifi.ts, and a failed read is
    not a report."""
    status = _payloads(name)["system-status"]
    assert status["wifi"]["ts"] == _NOW and status["source"]["wifi"]["available"] is False
    assert _values(_call("lastUpdatedView", status, None, _NOW_MS))["WIFI"] == NO_DATA


@_needsNode
def test_theViewCarriesNoStateLevelOrMember():
    p = _payloads("capture-stalled")
    view = _call("lastUpdatedView", p["system-status"], p["capture-health"], _NOW_MS)
    for row in view["rows"]:
        assert set(row) == {"key", "label", "value"}, row


# ---------------------------------------------------------------------------
# The DOM (render harness): the link, the detail, the host, R1.
# ---------------------------------------------------------------------------


def _gear(parked: bool | None) -> dict:
    """parked True -> P; False -> an engaged gear (D); None -> link_down."""
    from pi.obdii.gear_derivation import (
        GEAR_PARK,
        REASON_ENGAGED,
        REASON_LINK_DOWN,
        REASON_PARK,
        GearReading,
    )
    from pi.obdii.gear_state_emitter import buildGearState

    if parked is True:
        reading = GearReading(True, GEAR_PARK, REASON_PARK)
    elif parked is False:
        reading = GearReading(True, 3, REASON_ENGAGED)
    else:
        reading = GearReading(False, None, REASON_LINK_DOWN)
    return buildGearState(reading, nowIso=_NOW)


def _render(routes: dict[str, Any], *, parked: bool, steps: list[dict] | None = None):
    routes = dict(routes)
    if parked:
        routes["/gear"] = _gear(True)
    allSteps = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}] + (steps or [])
    tree = rh.runDashboard(routes=routes, steps=allSteps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _routes(name: str) -> dict[str, Any]:
    return {"/" + k: v for k, v in _payloads(name).items()}


def _text(node: dict) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _text(child))
    return "".join(out)


def _classes(node: dict) -> list[str]:
    return (node.get("attrs", {}).get("class") or "").split()


_OPEN_UPDATED = [{"clickNth": {"selector": ".sys-updated", "index": 0}}, {"flush": 2}]


def _detailOpen(surface) -> bool:
    return surface.pathById("page-detail")[-1]["attrs"].get("hidden") is None


def _lines(surface) -> list[list[dict]]:
    return surface.pathsByClass("page-detail-row")


def _lineParts(surface, path: list[dict]) -> tuple[list[dict], list[dict]]:
    label = [path + [c] for c in path[-1]["children"] if "page-detail-label" in _classes(c)]
    value = [path + [c] for c in path[-1]["children"] if "page-detail-value" in _classes(c)]
    assert len(label) == 1 and len(value) == 1
    return label[0], value[0]


@_needsNode
def test_last_updated_detail_lists_six_devices_in_order(monkeypatch):
    """The exit test: parked tap -> title LAST UPDATED, labels exactly the six
    in order; unparked -> no open."""
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_routes("all-ok-driving"), parked=True, steps=_OPEN_UPDATED)
    assert _detailOpen(surface)
    assert _text(surface.pathById("page-detail-title")[-1]) == TITLE
    labels = [_text(_lineParts(surface, p)[0][-1]) for p in _lines(surface)]
    assert labels == SIX_DEVICES
    values = [_text(_lineParts(surface, p)[1][-1]) for p in _lines(surface)]
    assert all(" · " in v and v.endswith(("AM", "PM")) for v in values), values
    # The System overlay stays shut: the link's tap stops at the link.
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is not None

    unparked = _render(_routes("all-ok-driving"), parked=False, steps=_OPEN_UPDATED)
    assert not _detailOpen(unparked)
    assert unparked.pathById("sys-detail")[-1]["attrs"].get("hidden") is not None


@_needsNode
def test_dom_theLinkSaysUpdated_withTheChevronOnlyWhileParked(monkeypatch):
    """Driving: 'UPDATED' with no ' ›'; a tap opens nothing."""
    monkeypatch.setenv("TZ", _ZONE)
    parked = _render(_routes("all-ok-driving"), parked=True)
    (link,) = parked.pathsByClass("sys-updated")
    assert _text(link[-1]) == "UPDATED ›"
    driving = _render(_routes("all-ok-driving"), parked=False)
    (link,) = driving.pathsByClass("sys-updated")
    assert _text(link[-1]) == "UPDATED"


@_needsNode
def test_dom_undatedLines_readTwoHyphens(monkeypatch):
    """(a) undated / null lastOkTs -> '--' on the glass."""
    monkeypatch.setenv("TZ", _ZONE)
    routes = _routes("all-ok-driving")
    routes["/system-status"]["sync"]["lastOkTs"] = None
    routes["/capture-health"]["feeds"]["imu"]["lastSampleSecondsAgo"] = None
    surface = _render(routes, parked=True, steps=_OPEN_UPDATED)
    values = {
        _text(_lineParts(surface, p)[0][-1]): _text(_lineParts(surface, p)[1][-1])
        for p in _lines(surface)
    }
    assert values["SYNC"] == NO_DATA and values["IMU"] == NO_DATA
    assert values["OBD"] != NO_DATA


@_needsNode
def test_dom_noLineCarriesAState_andTheColoursAreNeutral(monkeypatch):
    """(b) no data-state/level/member anywhere in the detail; the winning
    colour is --text-secondary (label) / --text-primary (value)."""
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_routes("capture-stalled"), parked=True, steps=_OPEN_UPDATED)
    body = surface.pathById("page-detail-body")
    for path in surface.paths():
        if path[: len(body)] == body:
            for attr in STATE_ATTRS:
                assert attr not in path[-1].get("attrs", {}), (attr, path[-1])
    assert len(_lines(surface)) == 6
    for path in _lines(surface):
        label, value = _lineParts(surface, path)
        assert surface.winningDeclaration(label, "color")[0] == "var(--text-secondary)"
        assert surface.winningDeclaration(value, "color")[0] == "var(--text-primary)"


@_needsNode
@pytest.mark.parametrize("name", _fixtureNames())
def test_dom_updatedPrecedesSettings_inEverySystemFixture(name, monkeypatch):
    """(c) UPDATED sits LEFT of SETTINGS › on the verdict line, every fixture."""
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(_routes(name), parked=False)
    (verdict,) = surface.pathsByClass("sys-verdict")
    order = [c for c in (_classes(n)[0] for n in verdict[-1]["children"] if "attrs" in n)]
    assert "sys-updated" in order and "sys-settings" in order
    assert order.index("sys-updated") == order.index("sys-settings") - 1, order


@_needsNode
def test_dom_theUnavailableVerdict_stillCarriesTheLink(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render({}, parked=False)
    (verdict,) = surface.pathsByClass("sys-verdict")
    assert _text(verdict[-1]) == "--UPDATEDSETTINGS ›"


@_needsNode
def test_dom_theAgeGrows_whileTheFileIsUnchanged(monkeypatch):
    """(e) advanceMs: the same capture-health, five seconds later, reads five
    seconds older -- the open detail repaints on the tick's clock."""
    monkeypatch.setenv("TZ", _ZONE)
    routes = _routes("all-ok-driving")

    def imu(surface) -> str:
        for path in _lines(surface):
            label, value = _lineParts(surface, path)
            if _text(label[-1]) == "IMU":
                return _text(value[-1])
        raise AssertionError("no IMU line")

    before = imu(_render(routes, parked=True, steps=_OPEN_UPDATED))
    after = imu(_render(routes, parked=True,
                        steps=_OPEN_UPDATED + [{"advanceMs": 5000, "flush": 4}]))
    secondsBefore = int(before.split(" ")[0])
    secondsAfter = int(after.split(" ")[0])
    assert secondsAfter == secondsBefore + 5, (before, after)


@_needsNode
def test_dom_theHelperOpens_withNoSystemStatusLoaded(monkeypatch):
    """Host pin: the helper has NO lastSysView gate -- an ENGINE HISTORY-style
    open with no system-status loaded still opens."""
    monkeypatch.setenv("TZ", _ZONE)
    routes = {"/capture-health": _payloads("all-ok-driving")["capture-health"]}
    surface = _render(routes, parked=True, steps=_OPEN_UPDATED)
    assert _detailOpen(surface)
    values = {
        _text(_lineParts(surface, p)[0][-1]): _text(_lineParts(surface, p)[1][-1])
        for p in _lines(surface)
    }
    assert values["WIFI"] == NO_DATA and values["SYNC"] == NO_DATA
    assert values["OBD"] != NO_DATA


@_needsNode
@pytest.mark.parametrize("leave", [False, None], ids=["gear-D", "link-down"])
def test_dom_R1_leavingParkedClosesTheDetail_andThePageShows(leave, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    leaving = _OPEN_UPDATED + [{"setRoutes": {"/gear": _gear(leave)}}, {"flush": 2}]
    # The parked fact is the debounced one (US-511-b): it gives parked back
    # after the raw reading has held not-parked for parkedOffS (3 s).
    held = _render(_routes("all-ok-driving"), parked=True,
                   steps=leaving + [{"advanceMs": 1000, "flush": 4}])
    assert _detailOpen(held), "still parked 1 s in: the detail stays"
    surface = _render(_routes("all-ok-driving"), parked=True,
                      steps=leaving + [{"advanceMs": 3500, "flush": 4}])
    assert not _detailOpen(surface)
    assert surface.pathsByClass("sys-verdict"), "the System page is still painted"


@_needsNode
def test_dom_theBackButtonCloses(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(
        _routes("all-ok-driving"), parked=True,
        steps=_OPEN_UPDATED + [{"click": "page-detail-back"}, {"flush": 1}],
    )
    assert not _detailOpen(surface)
    assert _text(surface.pathById("page-detail-back")[-1]) == "‹ BACK"


def test_theCloserRunsOnTheTick_onTheOpensPredicate():
    """R1 is built ONCE and run on every render tick, not on a gear event."""
    js = _read(_CAROUSEL_JS)
    closer = rh._fnBody(js, "closePageDetailUnlessParked")
    assert "currentParked().parked !== true" in closer
    opener = rh._fnBody(js, "openPageDetail")
    assert "currentParked().parked !== true" in opener
    assert "lastSysView" not in opener
    tick = rh._fnBody(js, "tick")
    assert "closePageDetailUnlessParked()" in tick


# ---------------------------------------------------------------------------
# The host's declared geometry (Q1: read, never copied).
# ---------------------------------------------------------------------------


def _rules() -> list[tuple[str, str]]:
    return [(r.selector.strip(), r.declarations) for r in rh.parseCss(_read(_CSS))]


def _rule(selector: str) -> str:
    bodies = [body for sel, body in _rules() if sel == selector]
    assert bodies, f"no rule {selector!r}"
    return " ".join(bodies)


def _decl(body: str, prop: str) -> str | None:
    found = rh.declarationOf(body, prop)
    return None if found is None else found[0]


def _hostVars(css: str | None = None) -> dict[str, str]:
    rules = rh.parseCss(css if css is not None else _read(_CSS))
    block = " ".join(r.declarations for r in rules if r.selector.strip() == "#page-detail")
    return {n: v.strip() for n, v in re.findall(r"(--pd-[\w-]+)\s*:\s*([^;]+);", block)}


def _px(value: str, scoped: dict[str, str] | None = None) -> float:
    """Resolve a length to px: the host's scoped properties, then :root."""
    scoped = _hostVars() if scoped is None else scoped
    value = value.strip()
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if var:
        name = var.group(1)
        if name in scoped:
            return _px(scoped[name], scoped)
        root = re.search(rf"^\s*{re.escape(name)}:\s*([0-9.]+)px", _read(_CSS), re.M)
        assert root is not None, f"{name} does not resolve to px"
        return float(root.group(1))
    if value == "0":
        return 0.0
    m = re.fullmatch(r"([0-9.]+)px", value)
    assert m is not None, f"{value!r} is not a px length"
    return float(m.group(1))


def _number(value: str, scoped: dict[str, str]) -> float:
    var = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    return float(scoped[var.group(1)] if var else value)


def _stageHeight() -> float:
    m = re.search(r"#stage\s*\{[^}]*?height:\s*([0-9.]+)px", rh._stripComments(_read(_CSS)))
    assert m is not None
    return float(m.group(1))


def _sides(value: str) -> tuple[str, str, str, str]:
    parts = value.split()
    top = parts[0]
    right = parts[1] if len(parts) > 1 else top
    bottom = parts[2] if len(parts) > 2 else top
    left = parts[3] if len(parts) > 3 else right
    return top, right, bottom, left


def _geometry(scoped: dict[str, str] | None = None) -> dict[str, float]:
    """Every term the body height spends, from the declared rules."""
    scoped = _hostVars() if scoped is None else scoped
    host = _rule("#page-detail")
    hostPad = _sides(_decl(host, "padding") or "")
    head = _rule(".page-detail-head")
    assert _decl(head, "box-sizing") == "border-box"
    rule = (_decl(head, "border-bottom") or "").split()[0]
    body = _rule(".page-detail-body")
    bodyPad = _sides(_decl(body, "padding") or "")
    return {
        "stage": _stageHeight(),
        "hostPadTop": _px(hostPad[0], scoped),
        "hostPadBottom": _px(hostPad[2], scoped),
        "head": _px(_decl(head, "height") or "", scoped),
        "headRule": _px(rule, scoped),
        "bodyPadTop": _px(bodyPad[0], scoped),
        "bodyPadBottom": _px(bodyPad[2], scoped),
        "bodyPadX": _px(bodyPad[1], scoped),
        "gap": _px(_decl(body, "gap") or "0", scoped),
    }


def _bodyHeight(scoped: dict[str, str] | None = None) -> float:
    g = _geometry(scoped)
    # border-box: the head's rule is INSIDE its declared height, not added.
    return (g["stage"] - g["hostPadTop"] - g["hostPadBottom"] - g["head"]
            - g["bodyPadTop"] - g["bodyPadBottom"])


def test_host_headIs34_borderBox_withItsRuleInside():
    g = _geometry()
    assert g["head"] == 34
    assert g["head"] == _px("var(--bar-h)")
    assert 0 < g["headRule"] < g["head"]


def test_host_hasNoPadding_andTheBodyIs270():
    g = _geometry()
    assert g["hostPadTop"] == 0 and g["hostPadBottom"] == 0
    assert g["bodyPadTop"] == 8 and g["bodyPadBottom"] == 8
    assert g["gap"] == 0
    assert _bodyHeight() == 270 == 320 - 34 - 8 - 8


def _lastUpdatedHeight(rows: int, scoped: dict[str, str] | None = None) -> float:
    scoped = _hostVars() if scoped is None else scoped
    row = _rule(".page-detail-row")
    rowMin = _px(_decl(row, "min-height") or "", scoped)
    label = _rule(".page-detail-label")
    value = _rule(".page-detail-value")
    line = _number(_decl(row, "line-height") or "", scoped)
    lineBox = max(
        _px(_decl(label, "font-size") or "", scoped), _px(_decl(value, "font-size") or "", scoped)
    ) * line
    each = max(rowMin, lineBox)
    return rows * each + (rows - 1) * _geometry(scoped)["gap"]


def test_fit_lastUpdated_isSixRowMinRows_264of270():
    assert _px("var(--row-min)") == 44
    height = _lastUpdatedHeight(6)
    assert height == 264
    assert height <= _bodyHeight()


def test_fit_aPlantedOverflow_fails():
    """Q1 negative controls: a seventh line, or a host head that grew to the
    US-556 overlay rule (--tap-min + 4), no longer fits."""
    assert _lastUpdatedHeight(7) > _bodyHeight()
    planted = dict(_hostVars(), **{"--pd-head-h": "40px", "--pd-pad-y": "12px"})
    assert _lastUpdatedHeight(6, planted) > _bodyHeight(planted)


def test_backButton_hitBoxIsTapMin_andEndsAboveTheFirstBodyChild():
    back = _rule("#page-detail-back")
    after = _rule("#page-detail-back::after")
    assert _decl(back, "position") == "relative"
    assert _decl(after, "content") == '""'
    assert _decl(after, "position") == "absolute"
    top = _px(_decl(after, "top") or "")
    hit = _px(_decl(after, "height") or "")
    assert hit >= _px("var(--tap-min)")
    assert _px(_decl(back, "min-width") or "") >= _px("var(--tap-min)")
    g = _geometry()
    # The button paints in the head (it starts at the head's top, the head has
    # no vertical padding); its hit box runs 6 px into the body's padding-top.
    headPad = _sides(_decl(_rule(".page-detail-head"), "padding") or "0")
    assert _px(headPad[0]) == 0 and _px(headPad[2]) == 0
    bottom = top + hit
    assert bottom - g["head"] == 6
    assert bottom <= g["head"] + g["bodyPadTop"]


def test_theHostComment_namesTheKebabPrecedentAndTheInvertedMenuHeadRule():
    css = _read(_CSS)
    start = css.index("US-894-g shared page-detail host")
    note = css[start: css.index("#page-detail {", start)]
    assert "#menu-btn::after" in note
    assert ".menu-head" in note and "US-556" in note
    assert "270" in note


def test_theHostIsASibling_ofSysDetail_andSysDetailIsUnchanged():
    html = _read(_HTML)
    assert html.index('<div id="sys-detail"') < html.index('<div id="page-detail"')
    assert '<button id="sys-detail-back" class="tap-target" aria-label="Back to System Status">‹ Back</button>' in html
    assert "min-height: 44px;" in _rule(".detail-head")
    assert "padding: 4px 12px 10px;" in _rule("#sys-detail")


# ---------------------------------------------------------------------------
# The width model: every line's widest case against its column.
# ---------------------------------------------------------------------------


def _columns(scoped: dict[str, str] | None = None) -> tuple[float, float]:
    scoped = _hostVars() if scoped is None else scoped
    fs = _px(_decl(_rule(".page-detail-label"), "font-size") or "", scoped)
    labelBasis = (_decl(_rule(".page-detail-label"), "flex") or "").split()[-1]
    m = re.fullmatch(r"([0-9.]+)em", labelBasis)
    assert m is not None, labelBasis
    labelCol = float(m.group(1)) * fs
    gapEm = re.fullmatch(r"([0-9.]+)em", _decl(_rule(".page-detail-row"), "gap") or "")
    assert gapEm is not None
    rowFs = _px(_decl(_rule(".page-detail-row"), "font-size") or "", scoped)
    width = 480 - 2 * _geometry(scoped)["bodyPadX"]
    return labelCol, width - labelCol - float(gapEm.group(1)) * rowFs


def _monoWidth(text: str, sizePx: float) -> float:
    return len(text) * sizePx * PI_MONO_ADVANCE_EM


def test_width_everyLabelFitsItsColumn_andTheWidestValueFitsItsOwn():
    labelCol, valueCol = _columns()
    fs = _px(_decl(_rule(".page-detail-label"), "font-size") or "")
    for label in SIX_DEVICES:
        assert michromaWidthPx(label, fs) <= labelCol, label
    valueFs = _px(_decl(_rule(".page-detail-value"), "font-size") or "")
    assert _monoWidth(WIDEST_VALUE, valueFs) <= valueCol
    assert michromaWidthPx(TITLE, _px(_decl(_rule(".page-detail-title"), "font-size") or "")) <= (
        480 - 2 * _geometry()["bodyPadX"] - _px("var(--tap-min)")
    )


def test_width_aPlantedWideValue_fails():
    _, valueCol = _columns()
    valueFs = _px(_decl(_rule(".page-detail-value"), "font-size") or "")
    assert _monoWidth(WIDEST_VALUE + " · Oct 22, 2026", valueFs) > valueCol


# ---------------------------------------------------------------------------
# The link's type, and the detail button's cascade (d).
# ---------------------------------------------------------------------------


def test_theUpdatedLink_takesTheSettingsType_butNotItsAutoMargin():
    link = _rule(".sys-updated")
    settings = _rule(".sys-settings")
    for prop in ("font-size", "letter-spacing", "color", "min-height", "display"):
        assert _decl(link, prop) == _decl(settings, prop), prop
    assert _decl(settings, "margin-left") == "auto"
    assert _decl(link, "margin-left") is None


def _buttonSurface(parked: bool) -> tuple[rh.Surface, list[dict]]:
    """The factory's markup (classes read from its source) under the host."""
    body = rh._fnBody(_read(_CAROUSEL_JS), "appendPageDetailButton")
    for cls in ("page-detail-btn", "page-detail-btn-label", "page-detail-btn-chevron"):
        assert f'"{cls}"' in body, cls
    assert '"data-parked"' in body and '" ›"' in body
    button = {
        "tag": "button",
        "attrs": {"class": "page-detail-btn", "data-parked": "true" if parked else "false"},
        "children": [
            {"tag": "span", "attrs": {"class": "page-detail-btn-label"},
             "children": [{"text": "HISTORY"}]},
            {"tag": "span", "attrs": {"class": "page-detail-btn-chevron"},
             "children": [{"text": " ›"}]},
        ],
    }
    tree = {"tag": "body", "attrs": {}, "children": [
        {"tag": "section", "attrs": {"class": "card"}, "children": [button]},
    ]}
    surface = rh.Surface(tree, _read(_CSS), PANEL)
    (path,) = surface.pathsByClass("page-detail-btn")
    return surface, path


def test_theDetailButton_cascade():
    surface, btn = _buttonSurface(parked=True)
    label = btn + [btn[-1]["children"][0]]
    chevron = btn + [btn[-1]["children"][1]]

    def win(path, prop):
        found = surface.winningDeclaration(path, prop)
        return None if found is None else found[0]

    assert win(label, "font-family") == "var(--font-display)"
    assert win(label, "font-size") == "var(--fs-label)"
    assert win(chevron, "font-family") == "var(--font-mono)"
    assert win(btn, "color") == "var(--text-primary)"
    assert win(btn, "border") == "1px solid var(--text-secondary)"
    assert win(btn, "border-radius") == "var(--radius)"
    assert win(btn, "padding") == "0 12px"
    assert win(btn, "height") == "var(--tap-min)"
    assert win(btn, "box-sizing") == "border-box"
    assert win(btn, "visibility") in (None, "visible")
    # No state colour anywhere on the button.
    for selector, decls in _rules():
        if "page-detail-btn" in selector:
            for token in STATE_TOKENS:
                assert token not in decls, (selector, token)


def test_theDetailButton_isHiddenWhileNotParked_spaceKept():
    surface, btn = _buttonSurface(parked=False)
    assert surface.winningDeclaration(btn, "visibility")[0] == "hidden"
    assert surface.displayOf(btn)[0] != "none"


def test_theDetailButton_followsTheParkedEdge_andOpensThroughTheHelper():
    js = _read(_CAROUSEL_JS)
    body = rh._fnBody(js, "appendPageDetailButton")
    assert "openPageDetail(" in body and "currentParked()" in body
    painter = rh._fnBody(js, "paintPageDetailButtons")
    assert '".page-detail-btn"' in painter and '"data-parked"' in painter
    assert "onParkedChange(paintPageDetailButtons)" in js
