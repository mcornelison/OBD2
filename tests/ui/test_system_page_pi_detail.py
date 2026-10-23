################################################################################
# File Name: test_system_page_pi_detail.py
# Purpose/Description: US-894-f (spec specs/v030-system-page-design.md s4.1,
#   s4.6.2, s7; Iris I8/I9; Atlas P1/P2/P8) -- the Pi line under the verdict,
#   the Pi detail the verdict opens, and US-759 closed by the design.
#
#   What is pinned here:
#     - the three fixtures the story names (pi-hot, pi-multi-limit,
#       two-issues) are exactly what _generate.py builds from the REAL
#       builders (pi_health.buildPiHealthBlock inside buildSystemStatusState);
#     - the Pi detail: CPU + `limit <cpuTempLimitC> °C` (the PUBLISHED limit,
#       never a page constant), throttled now / since boot + hex, disk free
#       floored to 0.1 GiB vs diskThresholdBytes, the I9 uptime words; a
#       crossed limit is amber ONLY as the `pi` member's; each value shows
#       its OWN read time, never a block ts;
#     - the Pi line: only with a `pi` member, its reason verbatim, ` ›`
#       (space + U+203A) only while parked; the verdict and the line open the
#       Pi detail parked, nothing otherwise;
#     - the version is the #version-chip, shown only in the Pi detail;
#     - US-759: the issue list and its freshness pair are deleted, and no
#       'age not reported' anywhere;
#     - ONE cross-language guard for the JS copies of the overLimit names.
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
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-f Pi detail + Pi line.
# ================================================================================
################################################################################

"""US-894-f tests: the Pi line, the Pi detail, and US-759 closed."""

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

from pi.hardware import pi_health  # noqa: E402
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
_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)
_GIB = 2**30
MIDDLE_DOT = "·"
CHEVRON = " ›"

_PI_FIXTURES = {"pi-hot", "pi-multi-limit", "two-issues"}


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _generator():
    spec = importlib.util.spec_from_file_location(
        "system_fixture_generator_f_pi", os.path.join(_FIXTURE_DIR, "_generate.py")
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


def _rows(detail: dict) -> dict[str, dict]:
    return {r["key"]: r for r in detail["rows"]}


# ---------------------------------------------------------------------------
# Fixtures: generated from the real builders, never hand-typed (Atlas L7).
# ---------------------------------------------------------------------------


def test_thePiFixturesAreAllOnDisk_andTheGeneratorBuildsThem():
    names = {f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json")}
    assert _PI_FIXTURES <= names
    assert _PI_FIXTURES <= set(_generator().fixtureNames())


@pytest.mark.parametrize("name", sorted(_PI_FIXTURES))
def test_everyPiFixtureOnDiskIsWhatTheGeneratorBuilds(name: str):
    gen = _generator()
    assert _read(os.path.join(_FIXTURE_DIR, f"{name}.json")) == gen.render(
        gen.buildFixture(name)
    ), f"{name}.json is stale -- re-run tests/ui/fixtures/states/system/_generate.py"


@pytest.mark.parametrize("name", sorted(_PI_FIXTURES))
def test_everyPiFixtureIsTheBuildersOutputForItsStoredInputs(name: str):
    fx = _fixture(name)
    assert set(fx) == {"description", "now", "zone", "inputs", "payloads"}
    assert buildSystemStatusState(**fx["inputs"]["system-status"]) == fx["payloads"]["system-status"]


def test_thePiFixturesCarryTheMembersTheirNamesSay():
    assert _status("pi-hot")["verdict"] == {
        "issueCount": 1, "members": [{"key": "pi", "reason": "CPU 80.2 °C, limit 80 °C."}],
    }
    multi = _status("pi-multi-limit")
    assert multi["verdict"]["members"] == [
        {"key": "pi", "reason": "Over limit: CPU temp, throttling, disk."}
    ]
    assert multi["pi"]["overLimit"] == ["cpuTemp", "throttled", "disk"]
    assert [m["key"] for m in _status("two-issues")["verdict"]["members"]] == ["bt", "pi"]


# ---------------------------------------------------------------------------
# The Pi detail view (s4.6.2).
# ---------------------------------------------------------------------------


@_needsNode
def test_piHot_theCpuRowIsTheExample_andOnlyItIsAmber():
    detail = _call("piDetailView", _status("pi-hot"))
    assert detail["head"] == "PI"
    assert [r["label"] for r in detail["rows"]] == ["CPU", "THROTTLING", "DISK", "UPTIME"]
    cpu = _rows(detail)["cpuTemp"]
    assert {k: cpu[k] for k in ("label", "value", "note", "level", "member")} == {
        "label": "CPU", "value": "80.2 °C", "note": "limit 80 °C",
        "level": "amber", "member": "pi",
    }
    for key in ("throttled", "disk", "uptime"):
        assert _rows(detail)[key]["level"] == "neutral", key
        assert _rows(detail)[key]["member"] is None


@_needsNode
def test_piMultiLimit_theThreeCrossedValuesAreAmber_uptimeNever():
    rows = _rows(_call("piDetailView", _status("pi-multi-limit")))
    assert [rows[k]["level"] for k in ("cpuTemp", "throttled", "disk", "uptime")] == [
        "amber", "amber", "amber", "neutral",
    ]
    assert rows["cpuTemp"]["value"] == "81.4 °C"
    assert rows["throttled"]["value"] == "throttled now " + MIDDLE_DOT + " throttled since boot"
    assert rows["throttled"]["note"] == "0x50005"
    # 19.97 GiB floored to 0.1 -- toward the breach, never up to the limit --
    # by the same integer floor the emitter's disk reason uses.
    assert rows["disk"]["value"] == "19.9 GiB"
    free = _status("pi-multi-limit")["pi"]["diskFreeBytes"]
    assert rows["disk"]["value"] == sse._floorTenthsOfGib(free) + " GiB"
    assert rows["disk"]["note"] == "limit 20 GiB"
    assert rows["uptime"]["value"] == "3 h 2 min"


@_needsNode
def test_theCpuLimitIsThePublishedOne_neverAPageConstant():
    status = copy.deepcopy(_status("pi-hot"))
    status["pi"]["cpuTempLimitC"] = 85
    assert _rows(_call("piDetailView", status))["cpuTemp"]["note"] == "limit 85 °C"
    status["pi"]["cpuTempLimitC"] = None
    assert _rows(_call("piDetailView", status))["cpuTemp"]["note"] is None
    body = rh._fnBody(_read(_CAROUSEL_JS), "piDetailView")
    assert re.search(r"\b80\b", body) is None


@_needsNode
def test_aHealthyBlock_notThrottled_diskAboveItsLimit_nothingAmber():
    rows = _rows(_call("piDetailView", _status("all-ok-driving")))
    # all-ok-driving publishes no pi block reading (unwired): every value --.
    assert [rows[k]["value"] for k in ("cpuTemp", "throttled", "disk", "uptime")] == [
        "--", "--", "--", "--",
    ]
    assert all(r["note"] is None for r in rows.values())
    assert all(r["level"] == "neutral" for r in rows.values())
    healthy = _rows(_call("piDetailView", _status("two-issues")))
    assert healthy["throttled"]["value"] == "not throttled now " + MIDDLE_DOT + " not since boot"
    # The emitter's own floor (integer arithmetic), so page and reason agree.
    free = _status("two-issues")["pi"]["diskFreeBytes"]
    assert healthy["disk"]["value"] == sse._floorTenthsOfGib(free) + " GiB"
    assert healthy["disk"]["level"] == "neutral"


@_needsNode
def test_overLimitWithNoPiMember_isNeverAmber():
    """s4.0: amber is the member's. A verdict-absent file counted nothing."""
    status = copy.deepcopy(_status("pi-multi-limit"))
    status.pop("verdict")
    rows = _call("piDetailView", status)["rows"]
    assert [r["level"] for r in rows] == ["neutral"] * 4
    assert _call("piLineView", status) is None


@_needsNode
def test_eachValueShowsItsOwnReadTime_neverABlockTs():
    status = copy.deepcopy(_status("pi-multi-limit"))
    status["pi"]["diskTs"] = "2026-10-22T20:00:00Z"
    status["ts"] = "2026-10-22T23:59:59Z"
    rows = _rows(_call("piDetailView", status))
    stamps = {k: _call("fmtStamp", status["pi"][k + "Ts"]) for k in ("cpuTemp", "throttled", "disk", "uptime")}
    for key, stamp in stamps.items():
        assert rows[key]["read"] == "read " + stamp, key
    assert rows["disk"]["read"] != rows["cpuTemp"]["read"]
    assert _call("fmtStamp", status["ts"]) not in json.dumps(rows, ensure_ascii=False)
    status["pi"]["uptimeTs"] = None
    assert _rows(_call("piDetailView", status))["uptime"]["read"] == "read --"


@_needsNode
@pytest.mark.parametrize(("seconds", "words"), [
    (0, "under 1 min"),
    (59, "under 1 min"),
    (60, "1 min"),
    (2520, "42 min"),
    (3599, "59 min"),
    (3600, "1 h 0 min"),
    (10920, "3 h 2 min"),
    (86400 + 3 * 3600, "1 day 3 h"),
    (2 * 86400 + 3 * 3600 + 59, "2 days 3 h"),
    (None, "--"),
    (-1, "--"),
    ("10920", "--"),
])
def test_uptimeWords_I9(seconds, words):
    assert _call("uptimeText", seconds) == words


# ---------------------------------------------------------------------------
# The Pi line (s4.1, I9).
# ---------------------------------------------------------------------------


@_needsNode
def test_thePiLine_onlyWithAPiMember_itsReasonVerbatim():
    assert _call("piLineView", _status("pi-hot")) == {
        "text": "CPU 80.2 °C, limit 80 °C.", "level": "amber", "member": "pi",
    }
    assert _call("piLineView", _status("bt-retrying")) is None
    assert _call("piLineView", None) is None
    view = _call("systemStatusView", _status("two-issues"))
    assert view["piLine"]["text"] == "CPU 80.2 °C, limit 80 °C."
    assert view["piDetail"] == _call("piDetailView", _status("two-issues"))


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _render(name: str, *, parked: bool, steps: list[dict] | None = None, status=None):
    routes: dict[str, Any] = {"/" + k: v for k, v in _fixture(name)["payloads"].items()}
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


def _tap(selector: str, index: int = 0) -> list[dict]:
    return [{"clickNth": {"selector": selector, "index": index}}, {"flush": 1}]


def _overlayOpen(surface) -> bool:
    return surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None


@_needsNode
def test_dom_parked_thePiLineIsTheReasonPlusSpaceChevron_amber_andOpensThePiDetail(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("pi-hot", parked=True)
    (line,) = surface.pathsByClass("sys-pi-line")
    assert _text(line[-1]) == "CPU 80.2 °C, limit 80 °C." + CHEVRON
    (chevron,) = surface.pathsByClass("sys-pi-chevron")
    assert chevron[-1]["children"][0]["text"] == " ›"
    assert line[-1]["attrs"]["data-level"] == "amber"
    assert line[-1]["attrs"]["data-member"] == "pi"
    assert surface.winningDeclaration(line, "color")[0] == "var(--amber-warn)"
    # It sits directly under the verdict.
    body = line[-2]["children"]
    order = [(c.get("attrs", {}).get("class") or "").split()[0] for c in body if "attrs" in c]
    assert order[:3] == ["sys-verdict", "sys-pi-line", "sys-rows"]

    opened = _render("pi-hot", parked=True, steps=_tap(".sys-pi-line"))
    assert _overlayOpen(opened)
    assert _text(opened.pathById("sys-detail-head")[-1]) == "PI"


@_needsNode
def test_dom_notParked_thePiLineHasNoChevron_andNoTapOpensAnything(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("pi-hot", parked=False, steps=_tap(".sys-pi-line") + _tap(".sys-verdict"))
    (line,) = surface.pathsByClass("sys-pi-line")
    assert _text(line[-1]) == "CPU 80.2 °C, limit 80 °C."
    assert "›" not in _text(line[-1])
    assert surface.pathsByClass("sys-pi-chevron") == []
    assert not _overlayOpen(surface)


@_needsNode
def test_dom_noPiMember_noPiLine(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    assert _render("bt-retrying", parked=True).pathsByClass("sys-pi-line") == []


@_needsNode
@pytest.mark.parametrize("name", ["all-ok-driving", "pi-multi-limit"])
def test_dom_parked_theVerdictTapOpensThePiDetail_withTheVersionChip(name, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render(name, parked=True, steps=_tap(".sys-verdict"))
    assert _overlayOpen(surface)
    assert _text(surface.pathById("sys-detail-head")[-1]) == "PI"
    body = _text(surface.pathById("sys-detail-body")[-1])
    for label in ("CPU", "THROTTLING", "DISK", "UPTIME"):
        assert label in body
    assert "age not reported" not in body
    chip = surface.pathById("version-chip")
    assert chip[-1]["attrs"].get("hidden") is None
    # The verdict carries the ` ›` while parked (the tap works).
    assert _text(surface.pathsByClass("sys-verdict")[0][-1]).endswith(CHEVRON)


@_needsNode
def test_dom_piDetail_amberOnlyOnTheCrossedValues(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("pi-hot", parked=True, steps=_tap(".sys-verdict"))
    rows = {p[-1]["attrs"]["data-row"]: p for p in surface.pathsByClass("pi-row")}
    assert set(rows) == {"cpuTemp", "throttled", "disk", "uptime"}
    for key, path in rows.items():
        value = [path + [c] for c in path[-1]["children"][0]["children"]
                 if "pi-value" in (c.get("attrs", {}).get("class") or "")]
        colour = surface.winningDeclaration(value[0], "color")[0]
        if key == "cpuTemp":
            assert path[-1]["attrs"]["data-member"] == "pi"
            assert colour == "var(--amber-warn)"
        else:
            assert "data-member" not in path[-1]["attrs"]
            assert colour == "var(--text-primary)"
    text = _text(rows["cpuTemp"][-1])
    assert "80.2 °C" in text and "limit 80 °C" in text and text.count("read ") == 1


@_needsNode
@pytest.mark.parametrize(("tap", "index"), [(".sys-row", 0), (".sys-row", 3)])
def test_dom_theVersionChipShowsOnlyInThePiDetail(tap, index, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    surface = _render("pi-hot", parked=True, steps=_tap(tap, index))
    assert _overlayOpen(surface)
    assert surface.pathById("version-chip")[-1]["attrs"].get("hidden") is not None


# ---------------------------------------------------------------------------
# US-759 closed by the design; the version's one reader (source checks).
# ---------------------------------------------------------------------------


def test_us759_theIssueListAndItsFreshnessPairAreDeleted():
    source = _read(_CAROUSEL_JS)
    for name in ("systemIssueRows", "systemDrill", "systemDiagnostics", "sysRowFreshness",
                 "SYS_NO_AGE", "sysLevelRank", "SYS_LEVEL_RANK", "SYS_ROW_FLOOR",
                 "renderSysDiagnostics"):
        assert re.search(r"\b" + name + r"\b", source) is None, name


def test_validation_noAgeNotReportedAnywhereInTheDashboard():
    for fname in os.listdir(_DASH):
        path = os.path.join(_DASH, fname)
        if os.path.isfile(path) and fname.endswith((".js", ".html", ".css")):
            assert "age not reported" not in _read(path), fname


def test_theVersionHasOneReader_theChip_neverASecondRead():
    from tests.ui.test_carousel_source_cards import _stripJsComments

    source = _stripJsComments(_read(_CAROUSEL_JS))
    assert ".deploy-version" not in source and "DEPLOY_VERSION" not in source
    assert source.count('getElementById("version-chip")') == 1


# ---------------------------------------------------------------------------
# Cross-language guard: no literal twins of the overLimit vocabulary.
# ---------------------------------------------------------------------------


def _jsString(name: str) -> str:
    m = re.search(r"var " + name + r' = "([^"]*)";', _read(_CAROUSEL_JS))
    assert m, name
    return m.group(1)


def test_theJsCopiesOfTheOverLimitNamesAreTheProducers():
    assert _jsString("PI_OVER_CPU_TEMP") == pi_health.OVER_LIMIT_CPU_TEMP
    assert _jsString("PI_OVER_THROTTLED") == pi_health.OVER_LIMIT_THROTTLED
    assert _jsString("PI_OVER_DISK") == pi_health.OVER_LIMIT_DISK
    assert _jsString("PI_MEMBER_KEY") == sse.VERDICT_PI
    m = re.search(r"var PI_BYTES_PER_GIB = (\d+);", _read(_CAROUSEL_JS))
    assert m and int(m.group(1)) == _GIB
