################################################################################
# File Name: test_system_page_amber_equals_members.py
# Purpose/Description: US-894-f (spec specs/v030-system-page-design.md s4.0,
#   AC 7; Atlas A5 2026-10-22) -- THE page-wide colour gate: amber means
#   counted, and counted means amber.
#
#   Defined (acceptance): an amber element is any element with
#   data-level="amber" on the System page, its details AND the top bar. On
#   every fixture in tests/ui/fixtures/states/system/ except settings-*:
#     - every amber element carries data-member="<key>" naming exactly ONE
#       verdict.members[].key (no orphan key, no unmarked amber);
#     - every member has AT LEAST one amber element (the BT step + its dot +
#       the row is several elements for one member: legal).
#   The page and top bar are read with each detail open in turn (one overlay,
#   one detail at a time), so every detail screen is inside the subject.
#
#   Two belt-and-braces checks keep the definition honest:
#     - no element is painted amber by data-state without data-level="amber"
#       (an amber LOOK the gate cannot see would make it vacuous);
#     - every element the stylesheet actually resolves to the amber token
#       sits inside a member-marked element -- the one exception is the
#       verdict count (`data-level="issues"`), which is the member set itself.
#   And negative controls prove the gate bites: an orphan key and a member
#   with no amber element both fail it, on synthetic input AND on a real
#   render.
#
#   Skipped when node is not on PATH.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-f AC 7 amber = members gate.
# ================================================================================
################################################################################

"""US-894-f: the amber set equals the member set, on every System fixture."""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_ZONE = "America/Chicago"
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")
_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)
AMBER = "var(--amber-warn)"

# Each detail and the tap that opens it (parked). "pi" is the verdict's.
_DETAIL_TAPS: dict[str, dict] = {
    "pi": {"selector": ".sys-verdict", "index": 0},
    "obd": {"selector": ".sys-row", "index": 0},
    "data": {"selector": ".sys-row", "index": 1},
    "wifi": {"selector": ".sys-row", "index": 2},
    "ups": {"selector": ".sys-row", "index": 3},
}


def _fixtureNames() -> list[str]:
    """Every System fixture on disk EXCEPT settings-* (acceptance)."""
    return sorted(
        f[:-5] for f in os.listdir(_FIXTURE_DIR)
        if f.endswith(".json") and not f.startswith("settings-")
    )


def _payloads(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)["payloads"]


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _render(payloads: dict[str, Any], detail: str):
    """The page parked, with `detail` open."""
    routes: dict[str, Any] = {"/" + name: body for name, body in payloads.items()}
    routes["/gear"] = _gearParked()
    steps = [
        {"flush": 4}, {"advanceMs": 9000, "flush": 4},
        {"clickNth": _DETAIL_TAPS[detail]}, {"flush": 1},
    ]
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _descendants(path: list[dict]):
    stack = [path]
    while stack:
        cur = stack.pop()
        yield cur
        for child in cur[-1].get("children", []):
            if "text" not in child:
                stack.append(cur + [child])


def _subject(surface) -> list[list[dict]]:
    """Every element path on the System page, in #sys-detail and in #topbar."""
    roots = []
    for path in surface.paths():
        attrs = path[-1].get("attrs", {})
        if attrs.get("data-state") == "system-status" and "card" in (attrs.get("class") or ""):
            roots.append(path)
    assert len(roots) == 1, "no single System card in the rendered DOM"
    for rootId in ("sys-detail", "topbar"):
        path = surface.pathById(rootId)
        assert path is not None, rootId
        roots.append(path)
    return [p for root in roots for p in _descendants(root)]


def _attrs(path: list[dict]) -> dict:
    return path[-1].get("attrs", {})


def _memberKeys(payloads: dict[str, Any]) -> list[str]:
    verdict = payloads["system-status"].get("verdict")
    if not isinstance(verdict, dict):
        return []
    return [m["key"] for m in verdict.get("members", [])]


def gateFindings(amberMembers: list[str | None], memberKeys: list[str]) -> list[str]:
    """AC 7 as a pure check: the reasons the amber set is NOT the member set.

    Args:
        amberMembers: The data-member of every amber element (None = unmarked).
        memberKeys: verdict.members[].key, in order.

    Returns:
        One finding per orphan / unmarked element and per member with none;
        empty when the amber set equals the member set.
    """
    findings = []
    keys = set(memberKeys)
    for member in amberMembers:
        if member is None:
            findings.append("an amber element carries no data-member")
        elif member not in keys:
            findings.append(f"orphan: amber element names {member!r}, not a member")
    for key in memberKeys:
        if key not in amberMembers:
            findings.append(f"member {key!r} has no amber element")
    return findings


def _ambers(surface) -> list[str | None]:
    return [_attrs(p).get("data-member") for p in _subject(surface)
            if _attrs(p).get("data-level") == "amber"]


# ---------------------------------------------------------------------------
# The gate's own negative controls (synthetic).
# ---------------------------------------------------------------------------


def test_gate_passesWhenTheSetsAreEqual_severalElementsPerMemberIsLegal():
    assert gateFindings(["bt", "bt", "bt", "pi"], ["bt", "pi"]) == []
    assert gateFindings([], []) == []


def test_gate_failsOnAnOrphanKey():
    assert gateFindings(["bt", "sync"], ["bt"]) == [
        "orphan: amber element names 'sync', not a member"
    ]


def test_gate_failsOnAnUnmarkedAmberElement():
    assert gateFindings([None], []) == ["an amber element carries no data-member"]


def test_gate_failsOnAMemberWithNoAmberElement():
    assert gateFindings(["bt"], ["bt", "pi"]) == ["member 'pi' has no amber element"]


def test_theSubjectIsEveryFixtureExceptSettings_andIsNotEmpty():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "system_fixture_generator_f", os.path.join(_FIXTURE_DIR, "_generate.py")
    )
    gen = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(gen)
    names = _fixtureNames()
    # Every generated fixture is in the subject (an empty or partial
    # directory listing cannot pass the gate vacuously).
    assert set(names) == {n for n in gen.fixtureNames() if not n.startswith("settings-")}
    assert len(names) == 27
    assert not [n for n in names if n.startswith("settings-")]
    for named in ("two-issues", "pi-hot", "pi-multi-limit", "verdict-absent"):
        assert named in names


# ---------------------------------------------------------------------------
# AC 7 on every fixture, with every detail open in turn.
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize("name", _fixtureNames())
def test_ac7_theAmberSetEqualsTheMemberSet_onThePageEveryDetailAndTheTopBar(
    name: str, monkeypatch
):
    monkeypatch.setenv("TZ", _ZONE)
    payloads = _payloads(name)
    members = _memberKeys(payloads)
    seen: list[str | None] = []
    for detail in _DETAIL_TAPS:
        surface = _render(payloads, detail)
        assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None, detail
        ambers = _ambers(surface)
        # No orphan and no unmarked amber in ANY view.
        assert [f for f in gateFindings(ambers, members) if "has no amber" not in f] == [], (
            name, detail
        )
        # An amber LOOK always carries data-level="amber" (else the gate is blind).
        for path in _subject(surface):
            if _attrs(path).get("data-state") == "amber":
                assert _attrs(path).get("data-level") == "amber", (name, detail, _attrs(path))
        seen.extend(ambers)
    # Every member shows amber somewhere on the page, a detail or the bar.
    assert gateFindings(seen, members) == [], name


@_needsNode
@pytest.mark.parametrize("name", ["two-issues", "pi-multi-limit", "capture-ups-feed-stalled",
                                  "wifi-read-failed", "adapter-silent", "all-ok-driving"])
def test_everyElementTheStylesheetPaintsAmber_isInsideAMemberMarkedElement(name, monkeypatch):
    """The only amber-coloured element outside a data-member is the verdict
    count (`issues`), which is the member set itself, not one of it."""
    monkeypatch.setenv("TZ", _ZONE)
    payloads = _payloads(name)
    for detail in ("pi", "obd", "data", "wifi"):
        surface = _render(payloads, detail)
        for path in _subject(surface):
            colour = surface.winningDeclaration(path, "color")
            if colour is None or colour[0] != AMBER:
                continue
            marked = [p for p in path if p.get("attrs", {}).get("data-member")]
            verdict = [p for p in path
                       if "sys-verdict" in (p.get("attrs", {}).get("class") or "").split()]
            assert marked or (verdict and verdict[-1]["attrs"]["data-level"] == "issues"), (
                name, detail, _attrs(path)
            )


# ---------------------------------------------------------------------------
# validationCriteria: two-issues.
# ---------------------------------------------------------------------------


@_needsNode
def test_validation_twoIssues_btStepBtDotAndThePiLine_nothingElseAmber(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    payloads = _payloads("two-issues")
    assert _memberKeys(payloads) == ["bt", "pi"]
    surface = _render(payloads, "pi")
    card = _subject(surface)
    assert surface.pathsByClass("sys-verdict-text")[0][-1]["children"][0]["text"] == "2 ISSUES"
    ambers = [p for p in card if _attrs(p).get("data-level") == "amber"
              and not any(q.get("attrs", {}).get("id") == "sys-detail" for q in p)]
    described = Counter(
        (
            _attrs(p).get("data-member"),
            _attrs(p).get("data-layer")
            or _attrs(p).get("data-row")
            or (_attrs(p).get("class") or "").split()[0],
        )
        for p in ambers
    )
    # The BT step (row chain) + the BT dot (top bar) carry data-layer bt; the
    # OBD row itself is the bt member's sentence; the Pi line is pi's.
    assert described == Counter({
        ("bt", "bt"): 2,          # the BT step and the top-bar BT dot
        ("bt", "obd"): 1,         # the OBD row (its sentence is the reason)
        ("pi", "sys-pi-line"): 1,
    })
    # The adapter and ECU are retrying but no member: not amber.
    for path in card:
        if _attrs(path).get("data-layer") in ("adapter", "ecu"):
            assert _attrs(path).get("data-level") != "amber"


# ---------------------------------------------------------------------------
# The gate bites on a REAL render.
# ---------------------------------------------------------------------------


@_needsNode
def test_aRealRender_aMemberThePageCannotShow_failsTheGate(monkeypatch):
    """A member key with no element (no UPS member exists in S109) -> 'has no
    amber element': the gate is not satisfied by an empty subject."""
    monkeypatch.setenv("TZ", _ZONE)
    payloads = copy.deepcopy(_payloads("all-ok-driving"))
    payloads["system-status"]["verdict"] = {
        "issueCount": 1, "members": [{"key": "ups", "reason": "made up"}],
    }
    seen = []
    for detail in _DETAIL_TAPS:
        seen.extend(_ambers(_render(payloads, detail)))
    assert gateFindings(seen, ["ups"]) == ["member 'ups' has no amber element"]


@_needsNode
def test_aRealRender_anAmberElementWhoseMemberIsGone_isAnOrphan(monkeypatch):
    """The bt-retrying page read against a verdict that names nobody: the
    page paints no amber at all (amber is keyed to the member, never the
    state), and a doctored bt mark is caught as an orphan."""
    monkeypatch.setenv("TZ", _ZONE)
    payloads = copy.deepcopy(_payloads("bt-retrying"))
    assert _ambers(_render(payloads, "obd"))
    payloads["system-status"]["verdict"] = {"issueCount": 0, "members": []}
    assert _ambers(_render(payloads, "obd")) == []
    assert gateFindings(["bt"], []) == ["orphan: amber element names 'bt', not a member"]
