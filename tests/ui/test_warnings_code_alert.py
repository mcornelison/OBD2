################################################################################
# File Name: test_warnings_code_alert.py
# Purpose/Description: US-899-b (F-127; spec s4.4b, Iris brief s B + U5-U7,
#   Atlas Q26/Q32) -- stored codes get a dismissable TROUBLE CODES screen while
#   parked. Guarded:
#     0. the FIXTURES -- each file this story adds under
#        tests/ui/fixtures/states/alerts/ is exactly what the REAL provider
#        `buildAlertsState` writes (ack-prior-boot through the real
#        AlertsAckStore); run this file as a script to rewrite them;
#     1. the VIEW -- `codeAlertView(alerts, parked)` renders from
#        states/alerts.codeAlert + entries[] ALONE: up to 3 rows, '+n more on
#        ALERTS', the frame from TIER_COLOR_VAR[codeAlert.tier]; null while not
#        parked and under PULL OVER;
#     2. the DISMISS -- `codeDismissNext` is the honest write: ONE POST of every
#        id, only a RE-READ with codeAlert null settles it inside
#        alertsAckConfirmSec, anything else says "couldn't dismiss" for
#        alertsAckNoticeSec;
#     3. the DOM -- the shipped carousel.js over the shipped markup (899-7,
#        899-8, 899-10);
#     4. the CSS + GATES -- tokens only, Michroma only on upper-case words, no
#        pulse, below PULL OVER and the REPLAY marker, /alerts-ack only through
#        postWrite.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Ralph (Rex)  | Initial -- US-899-b key-on TROUBLE CODES screen.
# 2026-10-22    | Ralph (Rex)  | US-511-b MOVED PIN: parked is states/gear (P/N);
#               |              | the DOM routes serve a gear, moving is gear 3.
# ================================================================================
################################################################################

"""US-899-b tests: a dismissable TROUBLE CODES screen while parked."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from pi.obdii.alerts_ack_store import AlertsAckStore  # noqa: E402
from pi.obdii.alerts_arbiter import CODE_UNRATED_SENTENCE, buildAlertsState  # noqa: E402
from tests.ui.css_type_scale import DASHBOARD_CSS, readCss  # noqa: E402
from tests.ui.test_carousel_kebab_always_visible import (  # noqa: E402
    _driving,
    _gearMoving,
    _gearParked,
    _parked,
)
from tests.ui.test_warnings_page import (  # noqa: E402
    CODES_READ,
    NOW_MS,
    P0400_SENTENCE,
    P0400_TITLE,
    P0443_SENTENCE,
    P0443_TITLE,
    _battery,
    _code,
    _p0400,
    _p0443,
)
from tests.ui.test_warnings_takeover import _overheat  # noqa: E402

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

SURFACE_ID = "code-alert"
DISMISS_ID = "code-alert-dismiss"
TAKEOVER_ID = "dtc-takeover"
MARKER_ID = "not-live-marker"
HEAD = "TROUBLE CODES"
DISMISS_FAILED = "couldn't dismiss"
P0400_ID = "code:P0400:watch"
P0443_ID = "code:P0443:minor"
BOOT_ID = "boot-fixture-0001"
PRIOR_BOOT_ID = "boot-prior-0000"
# validator DEFAULTS (Atlas Q33): the two windows the page is served.
CONFIRM_SEC = 6
NOTICE_SEC = 3
DISPLAY_STALE = {
    "imuSec": 3.0, "fuelResetConfirmSec": 6,
    "alertsAckConfirmSec": CONFIRM_SEC, "alertsAckNoticeSec": NOTICE_SEC,
}
ACK_OK = {"ok": True}
ACK_409 = {"__status": 409, "__body": {"ok": False, "error": "unknown_id", "ids": [P0400_ID]}}
# engineParked (US-511): the parked GEAR (US-511-b; was idle) must be HELD
# parkedOnS (8 s) before it is parked.
PARK_HOLD = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}]


# ---------------------------------------------------------------------------
# 0. Fixtures, from the real provider.
# ---------------------------------------------------------------------------


def _twoCodes() -> list:
    return [_p0443(), _p0400()]


def _fiveCodes() -> list:
    # Beyond the car's two rated codes, three UNRATED ones (the provider's
    # unrated title is the code and its sentence is Spool's UNRATED line).
    return [
        *_twoCodes(),
        *(_code(code, "unrated", code, CODE_UNRATED_SENTENCE, ts) for code, ts in (
            ("P2187", "2026-10-17T09:00:00Z"),
            ("P0171", "2026-10-16T09:00:00Z"),
            ("P0420", "2026-10-15T09:00:00Z"),
        )),
    ]


def _priorBootAcked(episodes: list) -> frozenset[str]:
    """The REAL ack store holding a PRIOR boot's record for every episode."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "alerts-ack.json")
        records = {
            e.id: {"bootId": PRIOR_BOOT_ID, "firstSeenTs": e.firstSeenTs,
                   "ackedAt": "2026-10-19T08:00:00Z"}
            for e in episodes
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(records, fh)
        return AlertsAckStore(path).matchingIds(episodes, bootId=BOOT_ID)


def _priorBootEpisodes() -> list:
    return [_battery("low", 11.8, "2026-10-20T17:28:00Z"), *_twoCodes()]


# name -> (episodes, acknowledgedIds).
CODE_ALERT_SCENARIOS: dict[str, tuple[list, tuple[str, ...]]] = {
    "code-alert-keyon": (_twoCodes(), ()),
    # The same provider payload: 'moving' is the gear side (US-511-b; was
    # system-status).
    "code-alert-moving": (_twoCodes(), ()),
    "code-alert-and-stop": ([*_overheat(), *_twoCodes()], ()),
    "code-alert-five-codes": (_fiveCodes(), ()),
    "code-alert-dismissed": (_twoCodes(), (P0400_ID, P0443_ID)),
    "ack-prior-boot": (_priorBootEpisodes(), ()),
}


def buildFixture(name: str) -> dict[str, Any]:
    """The states/alerts payload the shipped provider writes for a scenario."""
    episodes, acked = CODE_ALERT_SCENARIOS[name]
    if name == "ack-prior-boot":
        acked = tuple(sorted(_priorBootAcked(episodes)))
    return buildAlertsState(
        episodes, None, datetime(2026, 10, 20, 17, 30, tzinfo=UTC),
        dataSource="real", bootId=BOOT_ID, codeSource=CODES_READ, acknowledgedIds=acked,
    )


def _fixture(name: str) -> Any:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", sorted(CODE_ALERT_SCENARIOS))
def test_everyFixtureIsWhatTheShippedProviderWrites(name: str):
    """A hand-drifted fixture stays green through a provider change (US-628)."""
    assert _fixture(name) == buildFixture(name)


def test_theFixturesSayWhatTheirNamesSay():
    keyon = _fixture("code-alert-keyon")
    assert keyon["codeAlert"] == {
        "ids": [P0400_ID, P0443_ID], "tier": "watch", "dismissable": True,
    }
    assert keyon["takeover"] is None
    assert _fixture("code-alert-moving") == keyon
    both = _fixture("code-alert-and-stop")
    assert both["takeover"] is not None and both["codeAlert"] is not None
    assert len(_fixture("code-alert-five-codes")["codeAlert"]["ids"]) == 5
    assert _fixture("code-alert-dismissed")["codeAlert"] is None


def test_aPriorBootsAck_holdsNothing_thePulseAndTheCodeAlertAreBack():
    """899-8, on the provider side: the store's old-boot records match nothing."""
    assert _priorBootAcked(_priorBootEpisodes()) == frozenset()
    prior = _fixture("ack-prior-boot")
    assert prior["icon"]["pulse"] is True
    assert prior["codeAlert"] is not None
    assert not any(e["acknowledged"] for e in prior["entries"])


# ---------------------------------------------------------------------------
# 1. The pure view.
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


def _view(payload: Any, parked: Any = True) -> Any:
    return _call("codeAlertView", payload, parked)


@_NODE_ONLY
def test_keyonParked_isTwoProviderRows_amberFrame():
    """Validation 1: EGR FLOW (P0400) + EVAP PURGE (P0443), amber frame."""
    assert _view(_fixture("code-alert-keyon")) == {
        "ids": [P0400_ID, P0443_ID],
        "colorVar": "--amber-warn",
        "rows": [
            {"id": P0400_ID, "tier": "watch", "chip": "WATCH",
             "title": P0400_TITLE, "sentence": P0400_SENTENCE},
            {"id": P0443_ID, "tier": "minor", "chip": "MINOR",
             "title": P0443_TITLE, "sentence": P0443_SENTENCE},
        ],
        "more": None,
    }


@_NODE_ONLY
@pytest.mark.parametrize(
    ("tier", "colorVar"),
    [("watch", "--amber-warn"), ("minor", "--green-ok"), ("unrated", "--neutral-chip-bg"),
     ("nonsense", None)],
)
def test_theFrameIsTheProvidersTier_throughTheOneMap(tier: str, colorVar: str | None):
    """Atlas Q32: the page compares nothing -- a minor first row under a watch
    tier still frames watch; the tier field alone decides."""
    payload = _fixture("code-alert-keyon")
    payload["codeAlert"]["tier"] = tier
    assert _view(payload)["colorVar"] == colorVar


@_NODE_ONLY
def test_fiveCodes_threeRows_inIdsOrder_plusTwoMoreOnAlerts():
    payload = _fixture("code-alert-five-codes")
    view = _view(payload)
    assert [r["id"] for r in view["rows"]] == payload["codeAlert"]["ids"][:3]
    assert view["more"] == "+2 more on ALERTS"


@_NODE_ONLY
@pytest.mark.parametrize("parked", [False, None, "true", 1])
def test_notParked_isNotDrawn(parked: Any):
    """Iris U6: only a strict parked true draws it (engineParked starts false)."""
    assert _view(_fixture("code-alert-keyon"), parked) is None


@_NODE_ONLY
def test_pullOverWins_bothSet_noCodeAlert():
    """899-10, pure: with a takeover up the code alert is not drawn."""
    assert _view(_fixture("code-alert-and-stop")) is None


@_NODE_ONLY
@pytest.mark.parametrize(
    "payload",
    [None, {}, {"codeAlert": None}, {"codeAlert": {"ids": []}}, {"codeAlert": "x"}, "nonsense"],
    ids=["none", "empty", "null", "no-ids", "string-alert", "string"],
)
def test_noCodeAlert_isNoView(payload: Any):
    assert _view(payload) is None


@_NODE_ONLY
def test_theBodyIsEveryIdInOneShape():
    """Atlas Q26: {ids: [...]} -- every id, one request."""
    assert _call("codeDismissBody", [P0400_ID, P0443_ID]) == {"ids": [P0400_ID, P0443_ID]}


# ---------------------------------------------------------------------------
# 2. The honest dismiss.
# ---------------------------------------------------------------------------


def _steps(*events: dict[str, Any]) -> list[dict[str, Any]]:
    """Every state codeDismissNext passes through, one per event."""
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "let s = c.codeDismissInit(); const out = [];"
        "for (const ev of a.events) { s = c.codeDismissNext(s, ev); out.push(s); }"
        "process.stdout.write(JSON.stringify(out));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script],
        input=json.dumps({"js": _JS, "events": list(events)}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _tap(confirm: Any = CONFIRM_SEC, notice: Any = NOTICE_SEC) -> dict[str, Any]:
    view = _view(_fixture("code-alert-keyon"))
    return {"type": "tap", "view": view, "confirmSec": confirm, "noticeSec": notice}


def _read(name: str | None, nowMs: int) -> dict[str, Any]:
    return {"type": "read", "alerts": _fixture(name) if name else None, "nowMs": nowMs,
            "confirmSec": CONFIRM_SEC, "noticeSec": NOTICE_SEC}


def _notice(state: dict[str, Any]) -> str:
    return _call("codeDismissNoticeText", state)


@_NODE_ONLY
def test_dismiss_settledOnlyByAReReadWithCodeAlertNull():
    states = _steps(
        _tap(),
        {"type": "answer", "status": 200, "body": ACK_OK, "nowMs": NOW_MS},
        _read("code-alert-keyon", NOW_MS + 250),
        _read(None, NOW_MS + 500),
        _read("code-alert-dismissed", NOW_MS + 750),
    )
    assert [s["phase"] for s in states] == ["posting", "awaiting", "awaiting", "awaiting", "idle"]
    assert states[0]["ids"] == [P0400_ID, P0443_ID]
    assert all(_notice(s) == "" for s in states)


@_NODE_ONLY
def test_dismiss_200ButCodeAlertStillSet_pastTheWindow_isCouldntDismiss():
    states = _steps(
        _tap(),
        {"type": "answer", "status": 200, "body": ACK_OK, "nowMs": NOW_MS},
        _read("code-alert-keyon", NOW_MS + CONFIRM_SEC * 1000),
        _read("code-alert-keyon", NOW_MS + CONFIRM_SEC * 1000 + 250),
    )
    assert states[2]["phase"] == "awaiting", "the window is inclusive"
    assert states[3]["phase"] == "idle"
    assert _notice(states[3]) == DISMISS_FAILED


@_NODE_ONLY
@pytest.mark.parametrize("status", [409, 503, 504, 401, 400, 500])
def test_dismiss_anyRefusal_isCouldntDismiss_forTheNoticeWindow(status: int):
    states = _steps(
        _tap(),
        {"type": "answer", "status": status, "body": {"ok": False}, "nowMs": NOW_MS},
        _read("code-alert-keyon", NOW_MS + NOTICE_SEC * 1000),
        _read("code-alert-keyon", NOW_MS + NOTICE_SEC * 1000 + 250),
    )
    assert states[1]["phase"] == "idle"
    assert _notice(states[1]) == DISMISS_FAILED
    assert _notice(states[2]) == DISMISS_FAILED, "the notice window is inclusive"
    assert _notice(states[3]) == ""


@_NODE_ONLY
def test_dismiss_noAnswer_isCouldntDismiss():
    states = _steps(_tap(), {"type": "failure", "nowMs": NOW_MS})
    assert states[1]["phase"] == "idle" and _notice(states[1]) == DISMISS_FAILED


@_NODE_ONLY
def test_dismiss_aTapWhilePosting_orWithNoView_postsNothingMore():
    assert [s["phase"] for s in _steps(_tap(), _tap())] == ["posting", "posting"]
    assert _steps({"type": "tap", "view": None, "confirmSec": 6, "noticeSec": 3})[0]["phase"] == "idle"


@_NODE_ONLY
@pytest.mark.parametrize(("confirm", "notice"), [(None, NOTICE_SEC), (CONFIRM_SEC, None), (0, 3)])
def test_dismiss_withoutBothInjectedWindows_isNotOffered(confirm: Any, notice: Any):
    assert _steps(_tap(confirm=confirm, notice=notice))[0]["phase"] == "idle"


@_NODE_ONLY
def test_thePullOverAck_stillSettlesOnItsOwnEntry():
    """The shared ack half (ackFlowStep) did not change alertsAckNext: a
    codeAlert-null payload is no proof for the PULL OVER ack."""
    script = (
        'const a = JSON.parse(require("fs").readFileSync(0, "utf-8"));'
        "const c = require(a.js);"
        "let s = c.alertsAckNext(c.alertsAckInit(), {type: 'tap', view: {id: 'engine:COOLANT_TEMP:stop'},"
        " confirmSec: 6, noticeSec: 3});"
        "s = c.alertsAckNext(s, {type: 'answer', status: 200, body: {ok: true}, nowMs: 0});"
        "s = c.alertsAckNext(s, {type: 'read', alerts: a.alerts, nowMs: 100, confirmSec: 6, noticeSec: 3});"
        "process.stdout.write(JSON.stringify(s));"
    )
    proc = subprocess.run(
        [_NODE or "node", "-e", script],
        input=json.dumps({"js": _JS, "alerts": _fixture("code-alert-dismissed")}),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["phase"] == "awaiting"


# ---------------------------------------------------------------------------
# 3. The DOM (the SHIPPED carousel.js over the SHIPPED markup).
# ---------------------------------------------------------------------------


def _routes(
    alerts: Any, system: dict[str, Any] | None = None, gear: Any = None, **extra: Any
) -> dict[str, Any]:
    # MOVED PIN (US-511-b): parked is states/gear (P or N), so every boot serves
    # a gear route -- parked unless the caller says otherwise.
    routes: dict[str, Any] = {
        "/system-status": system if system is not None else _parked(),
        "/gear": gear if gear is not None else _gearParked(),
    }
    if alerts is not None:
        routes["/alerts"] = alerts
    routes.update(extra)
    return routes


def _boot(routes: dict[str, Any], steps: list[dict[str, Any]],
          displayStale: Any = DISPLAY_STALE) -> tuple[rh.Surface, dict[str, Any]]:
    out = rh.runDashboard(
        routes=routes, steps=steps, nowMs=NOW_MS, displayStale=displayStale,
        viewport=(480, 320),
    )
    return rh.Surface(out["tree"], readCss(DASHBOARD_CSS), (480, 320)), out


def _painted(surface: rh.Surface, elementId: str) -> bool:
    path = surface.pathById(elementId)
    return path is not None and surface.rendered(path)


def _paintedText(surface: rh.Surface, path: list[dict[str, Any]]) -> str:
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


def _surfaceText(surface: rh.Surface) -> str:
    path = surface.pathById(SURFACE_ID)
    assert path is not None, "#code-alert is gone from the markup"
    return _paintedText(surface, path)


def _posts(out: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in out["fetches"] if f["url"] == "/alerts-ack" and f["method"] == "POST"]


def _brightness(out: dict[str, Any]) -> float:
    path = rh.Surface(out["tree"], "").pathById("screen")
    assert path is not None
    return float(path[-1]["style"]["--display-brightness"])


@_NODE_ONLY
def test_dom_899_7_keyonParked_visible_twoRows_amberFrame_dismiss():
    """Validation 1."""
    surface, out = _boot(_routes(_fixture("code-alert-keyon")), PARK_HOLD)
    assert _painted(surface, SURFACE_ID)
    node = surface.pathById(SURFACE_ID)[-1]
    assert node["attrs"].get("data-surface") == "code-alert"
    assert "data-severity" not in node["attrs"], "Iris U7: never a data-severity"
    assert node["style"].get("--code-alert-frame") == "var(--amber-warn)"
    text = _surfaceText(surface)
    assert HEAD in text and "CHECK ENGINE" not in text
    for words in (P0400_TITLE, P0400_SENTENCE, P0443_TITLE, P0443_SENTENCE):
        assert words in text, words
    assert text.index(P0400_TITLE) < text.index(P0443_TITLE), "rows in ids order"
    assert _painted(surface, DISMISS_ID)
    assert surface.pathById(DISMISS_ID)[-1]["tag"] == "button"
    assert not _painted(surface, "code-alert-more")
    assert not _painted(surface, TAKEOVER_ID)
    assert _posts(out) == []


@_NODE_ONLY
def test_dom_noFullBrightnessOverride_theCabinLevelHolds():
    light = {"lux": 4.0, "ts": "2026-10-20T17:30:09Z", "brightnessLevel": 0.3,
             "brightnessMode": "auto"}
    _, out = _boot(_routes(_fixture("code-alert-keyon"), **{"/light": light}), PARK_HOLD)
    assert _brightness(out) == pytest.approx(0.3)


@_NODE_ONLY
def test_dom_899_7_dismiss_onePostWithBothIds_reReadNull_hidden():
    """Validation 2: screen hidden; one POST with both ids."""
    routes = _routes(_fixture("code-alert-keyon"), **{"/alerts-ack": ACK_OK})
    surface, out = _boot(routes, [
        *PARK_HOLD,
        {"click": DISMISS_ID},
        {"flush": 2},
    ])
    assert _painted(surface, SURFACE_ID), "a 200 alone never closes it"
    posts = _posts(out)
    assert len(posts) == 1, posts
    assert json.loads(posts[0]["body"]) == {"ids": [P0400_ID, P0443_ID]}
    assert posts[0]["token"] == "test-token", "the dismiss is token-gated"

    surface, out = _boot(routes, [
        *PARK_HOLD,
        {"click": DISMISS_ID},
        {"flush": 2},
        {"setRoutes": {"/alerts": _fixture("code-alert-dismissed")}},
        {"advanceMs": 500, "flush": 4},
    ])
    assert len(_posts(out)) == 1
    assert not _painted(surface, SURFACE_ID)
    assert DISMISS_FAILED not in _surfaceText(surface)


@_NODE_ONLY
def test_dom_dismissRefused_staysUp_couldntDismiss_thenTheNoticeGoes():
    routes = _routes(_fixture("code-alert-keyon"), **{"/alerts-ack": ACK_409})
    shown, out = _boot(routes, [*PARK_HOLD, {"click": DISMISS_ID}, {"flush": 3}])
    assert len(_posts(out)) == 1
    assert _painted(shown, SURFACE_ID)
    assert DISMISS_FAILED in _surfaceText(shown)
    gone, _ = _boot(routes, [
        *PARK_HOLD, {"click": DISMISS_ID}, {"flush": 3},
        {"advanceMs": NOTICE_SEC * 1000 + 500, "flush": 3},
    ])
    assert _painted(gone, SURFACE_ID)
    assert DISMISS_FAILED not in _surfaceText(gone)


@_NODE_ONLY
def test_dom_200ButNoNullReRead_isCouldntDismissAfterTheConfirmWindow():
    routes = _routes(_fixture("code-alert-keyon"), **{"/alerts-ack": ACK_OK})
    late, _ = _boot(routes, [
        *PARK_HOLD, {"click": DISMISS_ID}, {"flush": 3},
        {"advanceMs": CONFIRM_SEC * 1000 + 500, "flush": 3},
    ])
    assert _painted(late, SURFACE_ID)
    assert DISMISS_FAILED in _surfaceText(late)


@_NODE_ONLY
def test_dom_899_7_moving_notDrawn_noPost():
    """Validation 3: code-alert-moving -- not drawn; a DISMISS click posts nothing."""
    routes = _routes(
        _fixture("code-alert-moving"), _driving(), gear=_gearMoving(), **{"/alerts-ack": ACK_OK}
    )
    surface, out = _boot(routes, [*PARK_HOLD, {"click": DISMISS_ID}, {"flush": 2}])
    assert not _painted(surface, SURFACE_ID)
    assert _posts(out) == []


@_NODE_ONLY
def test_dom_beforeTheParkedHold_notDrawn():
    """Iris U6: engineParked starts not-parked -- >= 8 s after boot."""
    surface, _ = _boot(_routes(_fixture("code-alert-keyon")), [{"flush": 4}])
    assert not _painted(surface, SURFACE_ID)


@_NODE_ONLY
def test_dom_hidingWhileMovingIsNotADismiss_itReturnsWhenParked():
    routes = _routes(_fixture("code-alert-keyon"))
    surface, out = _boot(routes, [
        *PARK_HOLD,
        {"setRoutes": {"/system-status": _driving(), "/gear": _gearMoving()}}, {"flush": 4},
        {"advanceMs": 4000, "flush": 4},
    ])
    assert not _painted(surface, SURFACE_ID), "drawn while moving"
    assert _posts(out) == []
    back, out = _boot(routes, [
        *PARK_HOLD,
        {"setRoutes": {"/system-status": _driving(), "/gear": _gearMoving()}}, {"flush": 4},
        {"advanceMs": 4000, "flush": 4},
        {"setRoutes": {"/system-status": _parked(), "/gear": _gearParked()}}, {"flush": 4},
        {"advanceMs": 9000, "flush": 4},
    ])
    assert _painted(back, SURFACE_ID), "the code alert did not come back when parked"
    assert _posts(out) == []


@_NODE_ONLY
def test_dom_899_8_ackPriorBoot_theCodeAlertShowsAgain():
    """The provider's icon.pulse is true (asserted on the fixture above; the
    page animates the icon only for STOP, US-898-a); the code alert is back."""
    surface, _ = _boot(_routes(_fixture("ack-prior-boot")), PARK_HOLD)
    assert _painted(surface, SURFACE_ID)
    assert HEAD in _surfaceText(surface)
    assert surface.pathById("glyph-warnings")[-1]["attrs"].get("data-state") == "watch"


@_NODE_ONLY
def test_dom_899_10_bothSet_onlyPullOverDrawn_theCodeAlertReturnsAfter():
    """Validation 4."""
    routes = _routes(_fixture("code-alert-and-stop"))
    surface, _ = _boot(routes, PARK_HOLD)
    assert _painted(surface, TAKEOVER_ID)
    assert not _painted(surface, SURFACE_ID)
    after, _ = _boot(routes, [
        *PARK_HOLD,
        {"setRoutes": {"/alerts": _fixture("code-alert-keyon")}},
        {"advanceMs": 250, "flush": 3},
    ])
    assert not _painted(after, TAKEOVER_ID)
    assert _painted(after, SURFACE_ID)


@_NODE_ONLY
def test_dom_fiveCodes_threeRows_andTheMoreLine():
    surface, _ = _boot(_routes(_fixture("code-alert-five-codes")), PARK_HOLD)
    rows = surface.pathsByClass("code-alert-row")
    assert len(rows) == 3
    assert "+2 more on ALERTS" in _surfaceText(surface)


@_NODE_ONLY
def test_dom_withoutTheInjectedWindows_dismissPostsNothing():
    routes = _routes(_fixture("code-alert-keyon"), **{"/alerts-ack": ACK_OK})
    _, out = _boot(routes, [*PARK_HOLD, {"click": DISMISS_ID}, {"flush": 2}], displayStale=None)
    assert _posts(out) == []


# ---------------------------------------------------------------------------
# 4. CSS + gates.
# ---------------------------------------------------------------------------


def _css() -> str:
    return readCss(DASHBOARD_CSS)


def _js() -> str:
    with open(_JS, encoding="utf-8") as fh:
        return fh.read()


def _rules() -> list[rh.Rule]:
    return [r for r in rh.parseCss(_css()) if "code-alert" in r.selector]


def test_theCodeAlertRulesAreTokensOnly():
    assert _rules(), "no #code-alert rules"
    for rule in _rules():
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rule.declarations), rule.selector
        assert not re.search(r"font-size\s*:[^;]*\d+px", rule.declarations), rule.selector
        assert "inherit" not in rule.declarations, rule.selector
        assert "animation" not in rule.declarations, "no pulse on a stored code"


def test_michromaOnlyOnTheUpperCaseWords():
    """Michroma carries A-Z, 0-9, space and hyphen: the head, chips and DISMISS."""
    display = {r.selector for r in _rules() if "var(--font-display)" in r.declarations}
    assert display == {
        "#code-alert .code-alert-head", "#code-alert .code-alert-chip", "#code-alert-dismiss",
    }
    for word in (HEAD, "DISMISS", "WATCH", "MINOR", "UNRATED", "STOP"):
        assert re.fullmatch(r"[A-Z0-9 \-]+", word), word


def test_theHeadAndDismissAreAtTheirSizes():
    rules = {r.selector: r for r in _rules()}
    assert rh.declarationOf(rules["#code-alert .code-alert-head"].declarations, "font-size") == (
        "var(--fs-secondary)", False)
    dismiss = rules["#code-alert-dismiss"].declarations
    assert rh.declarationOf(dismiss, "font-size") == ("var(--fs-label)", False)
    assert rh.declarationOf(dismiss, "min-height") == ("var(--tap-min)", False)
    assert "border:" in dismiss, "DISMISS is a control: bordered (US-758)"


def test_theSurfaceSitsBelowPullOverAndTheMarker():
    z = re.compile(r"z-index\s*:\s*(-?\d+)")
    found = {}
    for rule in rh.parseCss(_css()):
        m = z.search(rule.declarations)
        if m and rule.selector in ("#code-alert", "#dtc-takeover", f"#{MARKER_ID}"):
            found[rule.selector] = int(m.group(1))
    assert found["#code-alert"] < found["#dtc-takeover"] < found[f"#{MARKER_ID}"]


def test_theMarkup_ownContainer_head_oneButton():
    with open(_HTML, encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(r'<div id="code-alert".*?\n  </div>\n', html, re.S)
    assert m, "no #code-alert container"
    block = m.group(0)
    assert 'data-surface="code-alert"' in block
    assert "data-severity" not in block
    assert block.count("<button") == 1
    assert f">{HEAD}<" in block


def test_alertsAckIsPostedOnlyThroughPostWrite():
    """Validation 5: no postAction("/alerts-ack" -- one write helper."""
    js = _js()
    assert not re.search(r"postAction\(\s*[\"']/alerts-ack", js)
    assert 'postWrite("/alerts-ack", codeDismissBody(' in js


def test_theViewDerivesNoTierAndSortsNothing():
    """Rule 0 / Atlas Q32: the frame is the provider's tier; nothing compared."""
    body = rh._fnBody(_js(), "codeAlertView")
    assert ".sort(" not in body
    assert "codeAlert.tier" in body
    for literal in ("--amber-warn", "--green-ok", "watch", "minor"):
        assert literal not in body, literal


def test_brightnessIgnoresTheCodeAlert():
    assert "codeAlert" not in rh._fnBody(_js(), "brightnessAlarmActive")


if __name__ == "__main__":
    for _name in sorted(CODE_ALERT_SCENARIOS):
        with open(os.path.join(_FIXTURES, _name + ".json"), "w", encoding="utf-8",
                  newline="\n") as _fh:
            json.dump(buildFixture(_name), _fh, indent=2, ensure_ascii=False)
            _fh.write("\n")
        print("wrote", _name)
