################################################################################
# File Name: test_warnings_takeover.py
# Purpose/Description: US-899-a1 (F-127; CIO R31, Iris brief s A + U7/U11/U12,
#   Atlas G4/Q10/Q33) -- a live coolant STOP takes over every page with the
#   provider's PULL OVER. Guarded:
#     0. the FIXTURES -- each file this story adds under
#        tests/ui/fixtures/states/alerts/ is exactly what the REAL provider
#        `buildAlertsState` writes (run this file as a script to rewrite them);
#     1. the VIEW -- `takeoverAlertView(alerts, nowTs)` renders from
#        states/alerts.takeover ALONE: the provider's directive, title, value
#        through displayUnits (last.value + the M7 clause while stale), sentence
#        and the agoText age; `brightnessAlarmActive` keys on takeover != null;
#     2. the ACK -- `alertsAckNext` is the honest write: a tap posts, only a
#        RE-READ showing acknowledged:true inside alertsAckConfirmSec settles it,
#        and anything else says "couldn't acknowledge" for alertsAckNoticeSec;
#     3. the DOM -- the shipped carousel.js over the shipped markup: the takeover
#        covers every page at full brightness, carries no button, a tap posts ONE
#        token-gated /alerts-ack and the frame keeps pulsing, null hides it with
#        the page underneath unchanged, and a code-only payload never takes over;
#     4. the CSS + GATES -- tokens only, the pulse reduced-motion aware, z-index
#        below the REPLAY marker, no 'PULL OVER' literal in the new render, and
#        one postWrite helper behind /dtc-clear, /fuel-reset and /alerts-ack.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Ralph (Rex)  | Initial -- US-899-a1 PULL OVER takeover + ack tap.
# ================================================================================
################################################################################

"""US-899-a1 tests: a live coolant STOP takes over every page with PULL OVER."""

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
    COOLANT_STOP_DIRECTIVE,
    COOLANT_STOP_SENTENCE,
    COOLANT_STOP_TITLE,
    buildAlertsState,
)
from tests.ui.css_type_scale import DASHBOARD_CSS, readCss  # noqa: E402
from tests.ui.test_carousel_kebab_always_visible import _parked  # noqa: E402
from tests.ui.test_warnings_page import (  # noqa: E402
    CODES_READ,
    NOW,
    NOW_MS,
    SCENARIOS,
    _battery,
    _coolant,
    _p0400,
    _p0443,
)

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

TAKEOVER_ID = "dtc-takeover"
MARKER_ID = "not-live-marker"
COOLANT_ID = "engine:COOLANT_TEMP:stop"
ACK_FAILED = "couldn't acknowledge"
# validator DEFAULTS (Atlas Q33 / Iris brief): the two windows the page is served.
CONFIRM_SEC = 6
NOTICE_SEC = 3
DISPLAY_STALE = {
    "imuSec": 3.0, "fuelResetConfirmSec": 6,
    "alertsAckConfirmSec": CONFIRM_SEC, "alertsAckNoticeSec": NOTICE_SEC,
}
ACK_OK = {"ok": True}
ACK_503 = {"__status": 503, "__body": {"ok": False, "error": "no states channel on this server"}}

# The stop-live-overheat fixture's coolant: 112 C through the S103 G1 helper.
OVERHEAT_VALUE = "234 °F"
# A dim but FRESH cabin: without a STOP the panel sits at this level.
DIM_LEVEL = 0.3


# ---------------------------------------------------------------------------
# 0. Fixtures, from the real provider.
# ---------------------------------------------------------------------------


def _overheat() -> list:
    return [_coolant(value=112, peak=112, firstSeenTs="2026-10-20T17:29:40Z", lastSeenTs=NOW)]


# name -> (episodes, codeSource, dataSource, acknowledgedIds).
TAKEOVER_SCENARIOS: dict[str, tuple[list, dict[str, Any] | None, str, tuple[str, ...]]] = {
    "stop-acknowledged": (_overheat(), CODES_READ, "real", (COOLANT_ID,)),
    "replay-stop-live": (_overheat(), CODES_READ, "replay", ()),
    "ack-fails-503": (_overheat(), CODES_READ, "real", ()),
    "watch-battery-red-no-takeover": (
        [_battery("low", 11.8, "2026-10-20T17:28:00Z")], CODES_READ, "real", (),
    ),
    "code-only-two-stored": ([_p0443(), _p0400()], CODES_READ, "real", ()),
}


def buildFixture(name: str) -> dict[str, Any]:
    """The states/alerts payload the shipped provider writes for a scenario."""
    episodes, codeSource, dataSource, acked = TAKEOVER_SCENARIOS[name]
    return buildAlertsState(
        episodes, None, datetime(2026, 10, 20, 17, 30, tzinfo=UTC),
        dataSource=dataSource, bootId="boot-fixture-0001", codeSource=codeSource,
        acknowledgedIds=acked,
    )


def _fixture(name: str) -> Any:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", sorted(TAKEOVER_SCENARIOS))
def test_everyFixtureIsWhatTheShippedProviderWrites(name: str):
    """A hand-drifted fixture stays green through a provider change (US-628)."""
    assert _fixture(name) == buildFixture(name)


def test_theStopFixturesThisStoryReadsAreTheB1Generators():
    """stop-live-overheat / stop-live-stale are US-898-b1's, built there."""
    assert {"stop-live-overheat", "stop-live-stale"} <= set(SCENARIOS)
    assert _fixture("stop-live-overheat")["takeover"]["id"] == COOLANT_ID


def test_theFixturesSayWhatTheirNamesSay():
    assert _fixture("stop-acknowledged")["takeover"] is not None
    assert _fixture("stop-acknowledged")["icon"]["pulse"] is False
    assert _fixture("stop-acknowledged")["entries"][0]["acknowledged"] is True
    assert _fixture("ack-fails-503")["icon"]["pulse"] is True
    assert _fixture("replay-stop-live")["dataSource"] == "replay"
    for name in ("watch-battery-red-no-takeover", "code-only-two-stored"):
        assert _fixture(name)["takeover"] is None
        assert _fixture(name)["icon"]["state"] == "watch"


# ---------------------------------------------------------------------------
# 1. The pure views.
# ---------------------------------------------------------------------------


def _map(fn: str, argLists: list[list[Any]]) -> list[Any]:
    proc = subprocess.run(
        [_NODE or "node", _PROBE, "--map", fn],
        input=json.dumps(argLists), capture_output=True, text=True, encoding="utf-8",
        env=dict(os.environ, TZ="UTC"),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _call(fn: str, *args: Any) -> Any:
    return _map(fn, [list(args)])[0]


def _view(payload: Any, now: str = NOW) -> Any:
    return _call("takeoverAlertView", payload, now)


@_NODE_ONLY
def test_liveOverheat_isTheProvidersWords_valueInFahrenheit_justNow():
    """Validation 1: directive from the payload, 'ENGINE OVERHEATING', 234 °F."""
    view = _view(_fixture("stop-live-overheat"))
    assert view == {
        "id": COOLANT_ID,
        "directive": COOLANT_STOP_DIRECTIVE,
        "title": COOLANT_STOP_TITLE,
        "value": OVERHEAT_VALUE,
        "stale": None,
        "sentence": COOLANT_STOP_SENTENCE,
        "age": "just now",
        "colorVar": "--critical-red",
        "acknowledged": False,
    }
    assert view["title"] == "ENGINE OVERHEATING"


@_NODE_ONLY
def test_theDirectiveIsTheProviders_neverAPageLiteral():
    """Iris U11 / Atlas G4: a renamed directive is rendered as published, and
    an absent one renders NO band text (no page-side fallback)."""
    payload = _fixture("stop-live-overheat")
    payload["takeover"]["directive"] = "STOP NOW"
    assert _view(payload)["directive"] == "STOP NOW"
    payload["takeover"]["directive"] = None
    assert _view(payload)["directive"] is None


@_NODE_ONLY
def test_staleStop_lastValueAndItsOwnLastReadingLine_countingUp():
    """899-4: the takeover stays; the stale line is 'last reading n s ago' and n
    counts up; the age since firstSeenTs is agoText, unchanged."""
    payload = _fixture("stop-live-stale")
    assert payload["takeover"]["stale"] is True and payload["takeover"]["value"] is None
    first, later = _map(
        "takeoverAlertView", [[payload, NOW], [payload, "2026-10-20T17:30:05Z"]],
    )
    assert first["value"] == OVERHEAT_VALUE, "stale shows last.value (Atlas Q10)"
    assert first["stale"] == "last reading 12 s ago"
    assert later["stale"] == "last reading 17 s ago"
    assert first["age"] == "4 min ago"


@_NODE_ONLY
@pytest.mark.parametrize(
    ("lastTs", "text"),
    [
        ("2026-10-20T17:30:09Z", "last reading 0 s ago"),     # a future ts clamps to 0
        ("2026-10-20T17:29:59.400Z", "last reading 0 s ago"),  # floor, not round
        ("2026-10-20T17:13:20Z", "last reading 999+ s ago"),   # 1000 s -> capped
    ],
)
def test_staleLine_isTheM7Rule(lastTs: str, text: str):
    payload = _fixture("stop-live-stale")
    payload["takeover"]["last"]["ts"] = lastTs
    assert _view(payload)["stale"] == text


@_NODE_ONLY
@pytest.mark.parametrize(
    "payload",
    [None, {}, {"takeover": None}, {"takeover": "PULL"}, "nonsense"],
    ids=["none", "empty", "null-takeover", "string-takeover", "string"],
)
def test_noTakeover_isNoView(payload: Any):
    assert _view(payload) is None


@_NODE_ONLY
def test_theAcknowledgedFlagIsTheEntrysOnTheReRead():
    assert _view(_fixture("stop-acknowledged"))["acknowledged"] is True
    assert _view(_fixture("ack-fails-503"))["acknowledged"] is False


@_NODE_ONLY
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("stop-live-overheat", True),
        ("stop-live-stale", True),
        ("stop-acknowledged", True),
        ("watch-battery-red-no-takeover", False),
        ("code-only-two-stored", False),
    ],
)
def test_brightnessAlarmActive_keysOnTheTakeover(name: str, expected: bool):
    assert _call("brightnessAlarmActive", _fixture(name)) is expected


@_NODE_ONLY
@pytest.mark.parametrize(
    "payload",
    [None, {"codes": [{"code": "P0300", "severity": "stop"}]}, {"takeover": None}],
    ids=["none", "a-dtc-stop-code", "null-takeover"],
)
def test_brightnessAlarmActive_isFalseWithoutATakeover(payload: Any):
    """No longer on the states/dtc ribbon level: a dtc STOP code alone is not
    the PULL OVER alarm."""
    assert _call("brightnessAlarmActive", payload) is False


@_NODE_ONLY
def test_tierColorVar_isTheOneMap():
    assert _call("tierColorVar", "stop") == "--critical-red"
    assert _call("tierColorVar", "watch") == "--amber-warn"
    assert _call("tierColorVar", "minor") == "--green-ok"
    assert _call("tierColorVar", "unrated") == "--neutral-chip-bg"
    assert _call("tierColorVar", "nonsense") is None


@_NODE_ONLY
def test_theAckBodyIsIdsOnly():
    """Atlas Q26: {ids: [...]} is the one shape."""
    assert _call("alertsAckBody", COOLANT_ID) == {"ids": [COOLANT_ID]}


# ---------------------------------------------------------------------------
# 2. The honest ack.
# ---------------------------------------------------------------------------


def _steps(*events: dict[str, Any]) -> list[dict[str, Any]]:
    """Every state alertsAckNext passes through, one per event."""
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "let s = c.alertsAckInit(); const out = [];"
        "for (const ev of a.events) { s = c.alertsAckNext(s, ev); out.push(s); }"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script],
        input=json.dumps({"js": _JS, "events": list(events)}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _tap(name: str = "stop-live-overheat", confirm: Any = CONFIRM_SEC, notice: Any = NOTICE_SEC):
    view = _view(_fixture(name))
    return {"type": "tap", "view": view, "confirmSec": confirm, "noticeSec": notice}


def _read(name: str, nowMs: int) -> dict[str, Any]:
    return {"type": "read", "alerts": _fixture(name), "nowMs": nowMs,
            "confirmSec": CONFIRM_SEC, "noticeSec": NOTICE_SEC}


def _notice(state: dict[str, Any]) -> str:
    return _call("alertsAckNoticeText", state)


@_NODE_ONLY
def test_ack_confirmedByTheReRead_settlesWithNoNotice():
    states = _steps(
        _tap(),
        {"type": "answer", "status": 200, "body": ACK_OK, "nowMs": NOW_MS},
        _read("stop-live-overheat", NOW_MS + 250),
        _read("stop-acknowledged", NOW_MS + 500),
    )
    assert [s["phase"] for s in states] == ["posting", "awaiting", "awaiting", "idle"]
    assert states[0]["id"] == COOLANT_ID
    assert all(_notice(s) == "" for s in states)


@_NODE_ONLY
def test_ack_200ButNoReRead_insideTheWindow_isCouldntAcknowledge():
    """Never optimistic: a 200 is not the proof; the re-read is."""
    states = _steps(
        _tap(),
        {"type": "answer", "status": 200, "body": ACK_OK, "nowMs": NOW_MS},
        _read("stop-live-overheat", NOW_MS + CONFIRM_SEC * 1000),
        _read("stop-live-overheat", NOW_MS + CONFIRM_SEC * 1000 + 250),
    )
    assert states[2]["phase"] == "awaiting", "the window is inclusive"
    assert states[3]["phase"] == "idle"
    assert _notice(states[3]) == ACK_FAILED


@_NODE_ONLY
@pytest.mark.parametrize("status", [409, 503, 504, 401, 400, 500])
def test_ack_anyRefusal_isCouldntAcknowledge_forTheNoticeWindow(status: int):
    states = _steps(
        _tap(),
        {"type": "answer", "status": status, "body": {"ok": False}, "nowMs": NOW_MS},
        _read("ack-fails-503", NOW_MS + NOTICE_SEC * 1000),
        _read("ack-fails-503", NOW_MS + NOTICE_SEC * 1000 + 250),
    )
    assert states[1]["phase"] == "idle"
    assert _notice(states[1]) == ACK_FAILED
    assert _notice(states[2]) == ACK_FAILED, "the notice window is inclusive"
    assert _notice(states[3]) == "", "the notice lasts alertsAckNoticeSec, then goes"


@_NODE_ONLY
def test_ack_noAnswerAtAll_isCouldntAcknowledge():
    states = _steps(_tap(), {"type": "failure", "nowMs": NOW_MS})
    assert states[1]["phase"] == "idle" and _notice(states[1]) == ACK_FAILED


@_NODE_ONLY
def test_ack_a504ThatLandedAfterAll_theReReadClearsTheNotice():
    states = _steps(
        _tap(),
        {"type": "answer", "status": 504, "body": {"ok": None}, "nowMs": NOW_MS},
        _read("stop-acknowledged", NOW_MS + 250),
    )
    assert _notice(states[1]) == ACK_FAILED
    assert _notice(states[2]) == "", "the read speaks"


@_NODE_ONLY
def test_ack_aTapWhilePosting_orOnAnAcknowledgedTakeover_postsNothingMore():
    states = _steps(_tap(), _tap())
    assert [s["phase"] for s in states] == ["posting", "posting"]
    assert _steps(_tap("stop-acknowledged"))[0]["phase"] == "idle"
    assert _steps({"type": "tap", "view": None, "confirmSec": 6, "noticeSec": 3})[0]["phase"] == "idle"


@_NODE_ONLY
@pytest.mark.parametrize(
    ("confirm", "notice"), [(None, NOTICE_SEC), (CONFIRM_SEC, None), (0, 3), ("6", 3)],
)
def test_ack_withoutBothInjectedWindows_isNotOffered(confirm: Any, notice: Any):
    """No mirrored default (the fuelResetConfirmSec pattern): with no window an
    acknowledging state would be unbounded, so the tap posts nothing."""
    assert _steps(_tap(confirm=confirm, notice=notice))[0]["phase"] == "idle"


@_NODE_ONLY
def test_resolveAlertsAckWindows_readTheInjection():
    assert _call("resolveAlertsAckConfirmSec", DISPLAY_STALE) == CONFIRM_SEC
    assert _call("resolveAlertsAckNoticeSec", DISPLAY_STALE) == NOTICE_SEC
    for bad in (None, {}, {"alertsAckConfirmSec": -1, "alertsAckNoticeSec": "3"}):
        assert _call("resolveAlertsAckConfirmSec", bad) is None
        assert _call("resolveAlertsAckNoticeSec", bad) is None


# ---------------------------------------------------------------------------
# 3. The DOM (the SHIPPED carousel.js over the SHIPPED markup).
# ---------------------------------------------------------------------------


def _light() -> dict[str, Any]:
    return {"lux": 4.0, "ts": NOW, "brightnessLevel": DIM_LEVEL, "brightnessMode": "auto"}


def _routes(alerts: Any, **extra: Any) -> dict[str, Any]:
    routes: dict[str, Any] = {"/system-status": _parked(), "/light": _light()}
    if alerts is not None:
        routes["/alerts"] = alerts
    routes.update(extra)
    return routes


def _boot(routes: dict[str, Any], steps: list[dict[str, Any]] | None = None,
          displayStale: Any = DISPLAY_STALE) -> tuple[rh.Surface, dict[str, Any]]:
    out = rh.runDashboard(
        routes=routes, steps=steps or [{"flush": 4}], nowMs=NOW_MS, displayStale=displayStale,
        viewport=(480, 320),
    )
    return rh.Surface(out["tree"], readCss(DASHBOARD_CSS), (480, 320)), out


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out)


def _painted(surface: rh.Surface, elementId: str) -> bool:
    path = surface.pathById(elementId)
    return path is not None and surface.rendered(path)


def _paintedText(surface: rh.Surface, path: list[dict[str, Any]]) -> str:
    """The text of the painted descendants of `path` only."""
    node = path[-1]
    if not surface.rendered(path):
        return ""
    out = []
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"])
        elif "tag" in child:
            out.append(_paintedText(surface, [*path, child]))
    return "".join(out)


def _takeoverText(surface: rh.Surface) -> str:
    path = surface.pathById(TAKEOVER_ID)
    assert path is not None, "#dtc-takeover is gone from the markup"
    return _paintedText(surface, path)


def _brightness(out: dict[str, Any]) -> float:
    surface = rh.Surface(out["tree"], "")
    path = surface.pathById("screen")
    assert path is not None
    return float(path[-1]["style"]["--display-brightness"])


def _animation(surface: rh.Surface) -> str | None:
    found = surface.winningDeclaration(surface.pathById(TAKEOVER_ID), "animation")
    return found[0] if found else None


def _activeDot(surface: rh.Surface) -> int:
    dots = surface.pathsByClass("dot")
    active = [i for i, p in enumerate(dots) if "active" in (p[-1]["attrs"].get("class") or "")]
    assert len(active) == 1, active
    return active[0]


def _visibleDots(surface: rh.Surface) -> list[int]:
    return [i for i, p in enumerate(surface.pathsByClass("dot")) if "hidden" not in p[-1]["attrs"]]


def _posts(out: dict[str, Any], path: str = "/alerts-ack") -> list[dict[str, Any]]:
    return [f for f in out["fetches"] if f["url"] == path and f["method"] == "POST"]


def _descendants(node: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for child in node.get("children", []):
        if "tag" in child:
            out.append(child)
            out.extend(_descendants(child))
    return out


@_NODE_ONLY
def test_dom_899_1_onEveryPage_visibleDirectiveValueUnitPulseAndFullBrightness():
    """899-1: stop-live-overheat, opened on each page in turn."""
    base, _ = _boot(_routes(_fixture("stop-live-overheat")))
    pages = _visibleDots(base)
    assert len(pages) >= 5, f"only {len(pages)} pages -- the gate hid the vehicle cards"
    for index in pages:
        surface, out = _boot(
            _routes(_fixture("stop-live-overheat")),
            [{"flush": 4}, {"clickNth": {"selector": ".dot", "index": index}}, {"flush": 2}],
        )
        assert _activeDot(surface) == index, f"page {index} never opened"
        assert _painted(surface, TAKEOVER_ID), f"no takeover on page {index}"
        text = _takeoverText(surface)
        assert COOLANT_STOP_DIRECTIVE in text, (index, text)
        assert COOLANT_STOP_TITLE in text and OVERHEAT_VALUE in text, (index, text)
        assert COOLANT_STOP_SENTENCE in text and "just now" in text, (index, text)
        assert _animation(surface) and "stop-alarm-pulse" in _animation(surface), index
        assert _brightness(out) == pytest.approx(1.0), index


@_NODE_ONLY
def test_dom_theStaticHeadAndTheOldButtonsAreNotShown():
    """Iris U7: no 'CHECK ENGINE', no View detail, no Dismiss on this surface."""
    surface, _ = _boot(_routes(_fixture("stop-live-overheat")))
    text = _takeoverText(surface)
    assert "CHECK ENGINE" not in text
    for gone in ("takeover-detail", "takeover-dismiss"):
        assert not _painted(surface, gone), gone


@_NODE_ONLY
def test_dom_899_2_noButtonInside_aTapPostsOnce_reReadAcknowledged_takeoverStays():
    """899-2 / validation 2: tap, re-read acknowledged true -> icon pulse false;
    the takeover still visible; the entry still listed."""
    surface, _ = _boot(_routes(_fixture("stop-live-overheat")))
    takeover = surface.pathById(TAKEOVER_ID)[-1]
    inside = _descendants(takeover)
    painted = [n for n in inside if surface.rendered(_pathTo(surface, n))]
    assert all(n["tag"] != "button" for n in painted), "a button inside the PULL OVER"
    assert not any("onclick" in n.get("attrs", {}) for n in inside)

    routes = _routes(_fixture("stop-live-overheat"), **{"/alerts-ack": ACK_OK})
    surface, out = _boot(routes, [
        {"flush": 4},
        {"click": TAKEOVER_ID},
        {"flush": 2},
        {"setRoutes": {"/alerts": _fixture("stop-acknowledged")}},
        {"advanceMs": 500, "flush": 4},
    ])
    posts = _posts(out)
    assert len(posts) == 1, posts
    assert posts[0]["token"] == "test-token", "the ack is token-gated"
    assert _painted(surface, TAKEOVER_ID), "an acknowledged PULL OVER stays up"
    assert "stop-alarm-pulse" in (_animation(surface) or ""), "the frame keeps pulsing"
    icon = surface.pathById("glyph-warnings")[-1]
    assert icon["attrs"].get("data-pulse") != "true", "the icon pulse stopped on the re-read"
    assert ACK_FAILED not in _takeoverText(surface)
    rows = [p for p in surface.pathsByClass("warn-row")]
    assert any(p[-1]["attrs"].get("data-id") == COOLANT_ID for p in rows), "the entry is listed"


def _pathTo(surface: rh.Surface, node: dict[str, Any]) -> list[dict[str, Any]]:
    for path in surface.paths():
        if path[-1] is node:
            return path
    raise AssertionError("node not in the surface")


@_NODE_ONLY
def test_dom_899_11_ackFails503_couldntAcknowledge_forTheNoticeWindow_pulseContinues():
    """899-11 / validation 3: 'couldn't acknowledge' for alertsAckNoticeSec."""
    routes = _routes(_fixture("ack-fails-503"), **{"/alerts-ack": ACK_503})
    shown, out = _boot(routes, [{"flush": 4}, {"click": TAKEOVER_ID}, {"flush": 3}])
    assert len(_posts(out)) == 1
    assert ACK_FAILED in _takeoverText(shown)
    icon = shown.pathById("glyph-warnings")[-1]
    assert icon["attrs"].get("data-pulse") == "true", "the icon keeps pulsing"
    assert "stop-alarm-pulse" in (_animation(shown) or "")

    gone, _ = _boot(routes, [
        {"flush": 4}, {"click": TAKEOVER_ID}, {"flush": 3},
        {"advanceMs": NOTICE_SEC * 1000 + 500, "flush": 3},
    ])
    assert ACK_FAILED not in _takeoverText(gone), "the notice outlived its window"
    assert _painted(gone, TAKEOVER_ID)


@_NODE_ONLY
def test_dom_200WithoutAMatchingReRead_isCouldntAcknowledgeAfterTheConfirmWindow():
    routes = _routes(_fixture("stop-live-overheat"), **{"/alerts-ack": ACK_OK})
    early, _ = _boot(routes, [{"flush": 4}, {"click": TAKEOVER_ID}, {"flush": 3}])
    assert ACK_FAILED not in _takeoverText(early), "inside the window it is not failed yet"
    late, _ = _boot(routes, [
        {"flush": 4}, {"click": TAKEOVER_ID}, {"flush": 3},
        {"advanceMs": CONFIRM_SEC * 1000 + 500, "flush": 3},
    ])
    assert ACK_FAILED in _takeoverText(late)


@_NODE_ONLY
def test_dom_899_3_flipTakeoverToNull_hidden_thePageUnderneathUnchanged():
    routes = _routes(_fixture("stop-live-overheat"))
    before, _ = _boot(routes, [{"flush": 4}])
    after, _ = _boot(routes, [
        {"flush": 4},
        {"setRoutes": {"/alerts": _fixture("stop-live-cleared")}},
        {"advanceMs": 250, "flush": 3},
    ])
    assert _painted(before, TAKEOVER_ID)
    assert not _painted(after, TAKEOVER_ID)
    assert "data-severity" not in after.pathById(TAKEOVER_ID)[-1]["attrs"]
    assert _animation(after) is None, "no alarm motion without the alarm"
    assert _activeDot(after) == _activeDot(before), "the card index moved"


@_NODE_ONLY
def test_dom_899_4_staleStop_takeoverStays_lastReadingCountsUp():
    routes = _routes(_fixture("stop-live-stale"))
    surface, _ = _boot(routes, [{"flush": 4}, {"advanceMs": 3000, "flush": 2}])
    text = _takeoverText(surface)
    assert _painted(surface, TAKEOVER_ID)
    assert OVERHEAT_VALUE in text
    assert "last reading 15 s ago" in text, text


@_NODE_ONLY
@pytest.mark.parametrize("name", ["watch-battery-red-no-takeover", "watch-over-rev"])
def test_dom_899_5_watchOnly_noTakeover_iconWatch_dimmedAsUsual(name: str):
    """899-5 / validation 4: no takeover in the DOM; icon watch; the cabin
    level still applies (only a STOP forces full)."""
    surface, out = _boot(_routes(_fixture(name)))
    assert not _painted(surface, TAKEOVER_ID)
    assert "data-severity" not in surface.pathById(TAKEOVER_ID)[-1]["attrs"]
    assert surface.pathById("glyph-warnings")[-1]["attrs"].get("data-state") == "watch"
    assert _brightness(out) == pytest.approx(DIM_LEVEL)


@_NODE_ONLY
def test_dom_899_6_codeOnlyEntries_neverAStopTakeover_evenWithADtcStopCode():
    """899-6: a code-only states/alerts never shows #dtc-takeover stop -- and a
    states/dtc STOP code no longer drives it either (one driver)."""
    dtc = {"codes": [{"code": "P0301", "severity": "stop", "short": "Misfire"}],
           "newSinceTs": "2026-10-20T17:29:00Z", "ts": NOW}
    surface, out = _boot(_routes(_fixture("code-only-two-stored"), **{"/dtc": dtc}))
    node = surface.pathById(TAKEOVER_ID)[-1]
    assert not _painted(surface, TAKEOVER_ID)
    assert node["attrs"].get("data-severity") != "stop"
    assert _brightness(out) == pytest.approx(DIM_LEVEL)


@_NODE_ONLY
def test_dom_noAlertsPayload_noTakeover():
    surface, _ = _boot(_routes(None))
    assert not _painted(surface, TAKEOVER_ID)


@_NODE_ONLY
def test_dom_899_9_replayStopLive_theMarkerPaintsAboveTheTakeover():
    """899-9: the REPLAY marker stays readable over a live replayed STOP."""
    system = dict(_parked(), runMode="replay")
    routes = _routes(_fixture("replay-stop-live"), **{"/system-status": system})
    surface, _ = _boot(routes)
    assert _painted(surface, TAKEOVER_ID) and _painted(surface, MARKER_ID)
    assert _textOf(surface.pathById(MARKER_ID)[-1]).strip() == "REPLAY"
    assert _zOf(surface, MARKER_ID) > _zOf(surface, TAKEOVER_ID)


def _zOf(surface: rh.Surface, elementId: str) -> int:
    found = surface.winningDeclaration(surface.pathById(elementId), "z-index")
    assert found is not None, f"#{elementId} declares no z-index"
    return int(found[0])


@_NODE_ONLY
def test_dom_withoutTheInjectedWindows_aTapPostsNothing():
    routes = _routes(_fixture("stop-live-overheat"), **{"/alerts-ack": ACK_OK})
    _, out = _boot(routes, [{"flush": 4}, {"click": TAKEOVER_ID}, {"flush": 2}],
                   displayStale=None)
    assert _posts(out) == []


# ---------------------------------------------------------------------------
# 4. CSS + gates.
# ---------------------------------------------------------------------------


def _css() -> str:
    return readCss(DASHBOARD_CSS)


def _js() -> str:
    with open(_JS, encoding="utf-8") as fh:
        return fh.read()


def _newRules() -> list[rh.Rule]:
    return [r for r in rh.parseCss(_css()) if "takeover-" in r.selector and re.search(
        r"#takeover-(title|value|stale|sentence|age|notice)\b", r.selector)]


def test_theNewTakeoverLinesAreTokensOnly_atTheirSizes():
    sizes = {
        "#takeover-title": "var(--fs-secondary)",
        "#takeover-value": "var(--fs-primary)",
        "#takeover-stale": "var(--fs-label)",
        "#takeover-sentence": "var(--fs-label)",
        "#takeover-age": "var(--fs-meta)",
        "#takeover-notice": "var(--fs-meta)",
    }
    rules = {r.selector: r for r in _newRules()}
    for selector, size in sizes.items():
        rule = next((r for s, r in rules.items() if s.endswith(selector)), None)
        assert rule is not None, f"no rule for {selector}"
        assert rh.declarationOf(rule.declarations, "font-size") == (size, False), selector
    for rule in _newRules():
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rule.declarations), rule.selector
        assert not re.search(r"\d+px", rule.declarations), rule.selector
        assert "inherit" not in rule.declarations, rule.selector
        assert "font-display" not in rule.declarations, "lower-case copy is mono"


def test_theStopPulse_livesInsideReducedMotionNoPreference():
    """Iris U8: the alarm motion is reduced-motion aware; the frame stays."""
    for rule in rh.parseCss(_css()):
        if re.search(r"(?:^|;)\s*animation\s*:[^;]*stop-alarm-pulse", rule.declarations):
            assert "prefers-reduced-motion: no-preference" in rule.media, rule.selector
    stop = [r for r in rh.parseCss(_css()) if r.selector == '#dtc-takeover[data-severity="stop"]']
    assert any("border:" in r.declarations and not r.media for r in stop), (
        "the 8 px frame must hold with motion reduced"
    )
    assert _css().count("@keyframes stop-alarm-pulse") == 1


def test_theTakeoverStaysAt60_belowTheMarkerAt70():
    z = re.compile(r"z-index\s*:\s*(-?\d+)")
    found = {}
    for rule in rh.parseCss(_css()):
        m = z.search(rule.declarations)
        if m and rule.selector in ("#dtc-takeover", f"#{MARKER_ID}"):
            found[rule.selector] = int(m.group(1))
    assert found == {"#dtc-takeover": 60, f"#{MARKER_ID}": 70}


def test_theNewRenderHasNoPullOverLiteral_andNoThresholdOrTierCopy():
    """Iris U11 / G-1 / G-2, on the functions this story adds."""
    for name in ("takeoverAlertView", "renderAlertsTakeover", "alertsAckNext"):
        body = rh._fnBody(_js(), name)
        assert "PULL OVER" not in body, name
        for literal in ("110", "104", "101", "7000", "12.0", "15.0", "ENGINE OVERHEATING",
                        "Stop safely", "redC", "clearBelow"):
            assert literal not in body, (name, literal)
        assert ".sort(" not in body, name


def test_oneDriver_updateDtcSurfacesNoLongerDrivesTheTakeover():
    body = rh._fnBody(_js(), "updateDtcSurfaces")
    for gone in ("showTakeover", "hideTakeover", "takeoverView"):
        assert gone not in body, gone


def test_brightnessReadsTheAlertsPayload_neverStatesDtc():
    js = _js()
    assert 'brightnessAlarmActive(await stateOnce("dtc"))' not in js
    assert "brightnessAlarmActive(dtcData)" not in js
    assert "brightnessAlarmActive(" in rh._fnBody(js, "tick")


def test_onePostHelper_behindEveryWrite():
    """Iris U12: postWrite is the one fetch for /dtc-clear, /fuel-reset and
    /alerts-ack; postAction stays the /service-control helper."""
    js = _js()
    assert "function postWrite(path, body)" in js
    for path in ("/dtc-clear", "/fuel-reset", "/alerts-ack"):
        assert f'postWrite("{path}"' in js, path
        assert not re.search(rf'fetch\(\s*"{re.escape(path)}"', js), f"a second fetch of {path}"
    assert "function postAction(unit, verb, statusEl)" in js
    assert "ok: true" not in rh._fnBody(js, "postWrite"), "the helper never reports success"


def test_theMarkupHoldsTheNewLines_andHidesTheOldHead():
    with open(_HTML, encoding="utf-8") as fh:
        html = fh.read()
    for lineId in ("takeover-title", "takeover-value", "takeover-stale",
                   "takeover-sentence", "takeover-age", "takeover-notice"):
        assert f'id="{lineId}"' in html, lineId
    assert re.search(r'<span class="takeover-head"[^>]*\bhidden\b', html)
    assert re.search(r'<div class="takeover-actions"[^>]*\bhidden\b', html)


if __name__ == "__main__":
    for _name in sorted(TAKEOVER_SCENARIOS):
        with open(os.path.join(_FIXTURES, _name + ".json"), "w", encoding="utf-8",
                  newline="\n") as _fh:
            json.dump(buildFixture(_name), _fh, indent=2, ensure_ascii=False)
            _fh.write("\n")
        print("wrote", _name)
