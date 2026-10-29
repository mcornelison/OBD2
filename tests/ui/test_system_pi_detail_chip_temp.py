################################################################################
# File Name: test_system_pi_detail_chip_temp.py
# Purpose/Description: US-894-i (spec specs/v030-system-page-design.md s4.6.2;
#   Iris S119 review item 3 + item 5; Atlas review F7) -- the IMU CHIP TEMP row
#   of the System Pi detail.
#
#   What is pinned here:
#     - the row sits DIRECTLY below CPU: [CPU, IMU CHIP TEMP, THROTTLING, DISK,
#       UPTIME];
#     - its value is the ALREADY-POLLED states/imu chipTempC in the CPU row's
#       form, its read line is the states/imu ts, it has no note, and it is
#       neutral with no member -- ALWAYS, even beside an amber CPU;
#     - `--` by the four absence rules: no payload, no finite chipTempC,
#       available !== true, stale under the ONE states/imu window;
#     - the verdict is untouched by the imu payload (systemStatusView with and
#       without it);
#     - the DOM: the parked Pi detail paints .pi-row[data-row=chipTemp];
#     - no banned word (cabin / interior / ambient) in the lines this story
#       adds -- a SCOPED scan, never the whole file.
#
#   Skipped when node is not on PATH -- the source checks always run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-28    | Ralph (Rex)  | Initial -- US-894-i IMU CHIP TEMP row.
# ================================================================================
################################################################################

"""US-894-i tests: the IMU CHIP TEMP row of the System Pi detail."""

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
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_STATES = os.path.join(os.path.dirname(__file__), "fixtures", "states")
_SYSTEM_DIR = os.path.join(_STATES, "system")
_NOW = "2026-10-22T23:10:00Z"
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)
# tests/ui/test_system_page_pi_detail.py::_render's second step (render_harness
# documents the advanceMs step): the clock at the tap.
_ADVANCE_MS = 9000
_STALE_SEC = 3
_LABELS = ["CPU", "IMU CHIP TEMP", "THROTTLING", "DISK", "UPTIME"]
_BANNED = re.compile(r"cabin|interior|ambient", re.IGNORECASE)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _status(name: str) -> dict:
    with open(os.path.join(_SYSTEM_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)["payloads"]["system-status"]


def _imu(name: str) -> dict:
    """A COPY of a read-only tests/ui/fixtures/states/imu.json case."""
    with open(os.path.join(_STATES, "imu.json"), encoding="utf-8") as fh:
        return copy.deepcopy(json.load(fh)[name])


def _tsMs(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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


def _chip(detail: dict) -> dict:
    (row,) = [r for r in detail["rows"] if r["key"] == "chipTemp"]
    return row


def _detailAt(status: Any, imu: Any, offsetSec: float) -> dict:
    nowMs = (_tsMs(imu["ts"]) if isinstance(imu, dict) else _NOW_MS) + int(offsetSec * 1000)
    return _call("piDetailView", status, imu, nowMs, _STALE_SEC)


# ---------------------------------------------------------------------------
# The exit test (cases a-g).
# ---------------------------------------------------------------------------


def _gearParked() -> dict:
    from pi.obdii.gear_derivation import GEAR_PARK, REASON_PARK, GearReading
    from pi.obdii.gear_state_emitter import buildGearState

    return buildGearState(GearReading(True, GEAR_PARK, REASON_PARK), nowIso=_NOW)


def _renderPiDetail(imu: dict | None):
    with open(os.path.join(_SYSTEM_DIR, "pi-hot.json"), encoding="utf-8") as fh:
        payloads = json.load(fh)["payloads"]
    routes: dict[str, Any] = {"/" + k: v for k, v in payloads.items()}
    routes["/gear"] = _gearParked()
    if imu is not None:
        routes["/imu"] = imu
    steps = [
        {"flush": 4}, {"advanceMs": _ADVANCE_MS, "flush": 4},
        {"clickNth": {"selector": ".sys-verdict", "index": 0}}, {"flush": 1},
    ]
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _text(node: dict) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _text(child))
    return "".join(out)


@_needsNode
def test_pi_detail_shows_imu_chip_temp_row(monkeypatch):
    """
    Given: the Pi detail over states/imu cases (driving 41.3, fresh-boot null)
    When:  piDetailView / systemStatusView run, and the parked page opens it
    Then:  IMU CHIP TEMP sits below CPU, '41.3 °C' or '--' by the four absence
           rules, always neutral with no member, the verdict untouched
    """
    status = _status("all-ok-driving")
    driving = _imu("driving")

    # (a) fresh driving payload: the row, in the CPU row's form, below CPU.
    a = _detailAt(status, driving, 1)
    assert [r["label"] for r in a["rows"]] == _LABELS
    chip = _chip(a)
    assert chip["value"] == "41.3 °C"
    assert chip["note"] is None
    assert chip["read"] == _call("piReadText", driving["ts"])
    assert chip["read"] != "read --"
    assert chip["level"] == "neutral"
    assert chip["member"] is None

    # (b) fresh-boot: chipTempC null (reasons.chipTempC no_reading).
    freshBoot = _imu("fresh-boot")
    assert freshBoot["chipTempC"] is None
    assert _chip(_detailAt(status, freshBoot, 1))["value"] == "--"

    # (c) 4 s old against the 3 s window: stale.
    assert _chip(_detailAt(status, driving, 4))["value"] == "--"
    # The boundary is motionView's: age > staleSec is stale, age == staleSec is not.
    assert _chip(_detailAt(status, driving, 3))["value"] == "41.3 °C"
    undated = _imu("driving")
    undated.pop("ts")
    assert _call("piDetailView", status, undated, _NOW_MS, _STALE_SEC)["rows"][1]["value"] == "--"

    # (d) available false.
    unavailable = _imu("driving")
    unavailable["available"] = False
    assert _chip(_detailAt(status, unavailable, 1))["value"] == "--"

    # (e) no payload: '--' and 'read --'; renderPiDetail's fallback too.
    for e in (_call("piDetailView", status, None, _NOW_MS, _STALE_SEC), _call("piDetailView", None)):
        assert [r["label"] for r in e["rows"]] == _LABELS
        assert _chip(e)["value"] == "--"
        assert _chip(e)["read"] == "read --"
        assert _chip(e)["level"] == "neutral"

    # (f) pi-hot + a chip temp of 85.0: CPU amber as the pi member, chip neutral.
    hot = _status("pi-hot")
    hotImu = _imu("driving")
    hotImu["chipTempC"] = 85.0
    f = _detailAt(hot, hotImu, 1)
    cpu = f["rows"][0]
    assert (cpu["key"], cpu["level"], cpu["member"]) == ("cpuTemp", "amber", "pi")
    assert _chip(f)["value"] == "85.0 °C"
    assert (_chip(f)["level"], _chip(f)["member"]) == ("neutral", None)
    nowMs = _tsMs(hotImu["ts"]) + 1000
    withImu = _call("systemStatusView", hot, None, None, nowMs, hotImu, _STALE_SEC)
    without = _call("systemStatusView", hot, None, None, nowMs)
    assert withImu["verdict"] == without["verdict"]
    assert withImu["piLine"] == without["piLine"]
    assert _chip(withImu["piDetail"])["value"] == "85.0 °C"
    assert _chip(without["piDetail"])["value"] == "--"
    assert [r["level"] for r in withImu["piDetail"]["rows"]] == [
        r["level"] for r in without["piDetail"]["rows"]
    ]

    # (g) the DOM, parked: the imu copy re-stamped to the harness clock at the tap.
    monkeypatch.setenv("TZ", _ZONE)
    stamped = _imu("driving")
    stamped["ts"] = _iso(_NOW_MS + _ADVANCE_MS)
    surface = _renderPiDetail(stamped)
    assert surface.pathById("sys-detail")[-1]["attrs"].get("hidden") is None
    (row,) = [p for p in surface.pathsByClass("pi-row")
              if p[-1]["attrs"].get("data-row") == "chipTemp"]
    head = row[-1]["children"][0]
    assert [_text(c) for c in head["children"]] == ["IMU CHIP TEMP", "41.3 °C"]
    assert "data-member" not in row[-1]["attrs"]
    assert row[-1]["attrs"]["data-level"] == "neutral"
    order = [p[-1]["attrs"]["data-row"] for p in surface.pathsByClass("pi-row")]
    assert order == ["cpuTemp", "chipTemp", "throttled", "disk", "uptime"]


@_needsNode
def test_dom_theImuReadAtTheHarnessStartIsStale_andPaintsDashes(monkeypatch):
    """The negative control for (g): a ts stamped at _NOW_MS is 9 s old at the tap."""
    monkeypatch.setenv("TZ", _ZONE)
    old = _imu("driving")
    old["ts"] = _iso(_NOW_MS)
    surface = _renderPiDetail(old)
    (row,) = [p for p in surface.pathsByClass("pi-row")
              if p[-1]["attrs"].get("data-row") == "chipTemp"]
    assert _text(row[-1]["children"][0]["children"][1]) == "--"


# ---------------------------------------------------------------------------
# Banned words, over the lines this story adds only (Atlas review F7).
# ---------------------------------------------------------------------------


def _chipTempSource() -> str:
    source = _read(_CAROUSEL_JS)
    helper = rh._fnBody(source, "piChipTempValue")
    body = rh._fnBody(source, "piDetailView")
    rowCall = body[body.index('row("chipTemp"'): body.index('row("throttled"')]
    return helper + rowCall


def _cssRule(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    return css[start: css.index("}", start)]


def test_theAddedLinesCarryNoBannedWord():
    css = _read(_CSS)
    scoped = {
        "chipTemp row": _chipTempSource(),
        "#sys-detail": _cssRule(css, "#sys-detail"),
        "#sys-detail-body": _cssRule(css, "#sys-detail-body"),
    }
    for where, text in scoped.items():
        assert "chipTemp" in text or where.startswith("#"), where
        assert _BANNED.search(text) is None, where
    # The scan is live: a planted word is found.
    assert _BANNED.search(scoped["chipTemp row"] + " ambient") is not None


def test_theChipRowIsNeverLookedUpInOverLimit():
    """Never amber: no PI_OVER_* name for it, and the row passes 'neutral'."""
    source = _read(_CAROUSEL_JS)
    assert re.search(r"var PI_OVER_\w*CHIP\w* =", source, re.IGNORECASE) is None
    rowCall = _chipTempSource()
    assert '"neutral")' in rowCall
    assert "level(" not in rowCall and "overLimit" not in rowCall
