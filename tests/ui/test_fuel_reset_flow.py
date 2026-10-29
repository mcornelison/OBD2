################################################################################
# File Name: test_fuel_reset_flow.py
# Purpose/Description: US-890-f (F-127) tests for the Fuel card's SINCE RESET
#   reset (specs/v030-fuel-page-design.md s4.3, CIO F-6, Iris G-6, Atlas G3/Q4):
#   a parked-only 2 s hold -> in-page "Reset average MPG?" -> token-gated POST
#   /fuel-reset -> "resetting…" from Yes until a states/fuel-economy read whose
#   sinceReset.resetAtTs equals the 200's resetAtTs (bounded by
#   pi.display.stale.fuelResetConfirmSec from the 200). Otherwise SINCE RESET
#   always shows the LATEST provider value plus an outcome line. Guarded:
#     1. the fixtures -- present, described, every read the REAL builder's;
#     2. the reducer + view (node probe, the clock on each event) for every
#        validation row and outcome;
#     3. the confirm window -- injected only, no literal in carousel.js, the
#        validator default 6;
#     4. a real toCanonicalIso stamp end to end (Iris G-5);
#     5. the SHIPPED DOM -- hold, confirm, POST (token), re-read, refusals,
#        painted by the real tick with fetch and the clock stubbed.
#   NOT GUARDED: layout on the glass (render_harness resolves the cascade, not
#   boxes); the R15 screenshot is owed on the Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-18    | Rex (US-890-f) | Initial -- SINCE RESET reset flow.
# 2026-10-22    | Ralph (Rex)  | US-511-b MOVED PIN: parked is states/gear (P/N);
#               |              | the DOM boots serve a parked or moving car.
# 2026-10-22    | Rex (US-923) | MOVED PIN: the reset follows the provider's
#               |              | resetAllowed, not engineParked; 'park to reset'
#               |              | retired for 'slow to reset' / 'speed unknown'.
# ================================================================================
################################################################################

"""US-890-f tests for the SINCE RESET parked long-press reset."""

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

from tests.ui.test_carousel_kebab_always_visible import (  # noqa: E402
    _driving,
    _gearMoving,
    _gearParked,
    _parked,
)
from tests.ui.test_engine_page import _classes, _ms, _textOf  # noqa: E402

_JS = os.path.join(rh.DASHBOARD_DIR, "carousel.js")
_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "states", "fuel")
_NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(
    _NODE is None, reason="node not on PATH -- these tests run the shipped browser JS"
)

FIXTURE_NAMES = [
    "parked-reset-available", "reset-refused-driving", "reset-write-fails",
    "reset-unknown-504", "reset-confirm-timeout",
    # US-923 (fuel spec s7): the gate as published.
    "reset-allowed-true", "reset-allowed-driving", "reset-allowed-speed-unknown",
    "reset-allowed-missing",
]

HINT = "hold to reset"
RESETTING = "resetting…"
# US-923 MOVED PIN: 'park to reset' is retired (fuel spec s4.3/s4.6).
SLOW = "slow to reset"
SPEED_UNKNOWN = "speed unknown"
FAILED = "couldn't reset"
# US-890-i MOVED PIN: the unconfirmed outcome is 'unconfirmed' (fuel spec s4.6).
UNCONFIRMED = "unconfirmed"
OLD_FIGURE = "≈24.6"
CONFIRM_SEC = 6
STALE = {"imuSec": 2.0, "fuelResetConfirmSec": CONFIRM_SEC}


def _fixture(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURES, name + ".json"), encoding="utf-8") as fh:
        return json.load(fh)


def _read(name: str, label: str) -> dict[str, Any]:
    for r in _fixture(name)["reads"]:
        if r["label"] == label:
            return r["fuel-economy"]
    raise AssertionError(f"{name} has no read {label}")


# Runs a sequence of reducer events through carousel.js and returns, after each
# one, the state and the MPG row view -- the view built from the LATEST read the
# sequence has seen, that read's own gate (US-923: fuelResetAllowed, exactly as
# the shipped tick passes it), and the injected window.
_SEQUENCE = """
const args = JSON.parse(require("fs").readFileSync(0, "utf-8"));
if (args.stale !== undefined) globalThis.DISPLAY_STALE = args.stale;
const c = require(args.js);
const confirmSec = c.resolveFuelResetConfirmSec(globalThis.DISPLAY_STALE);
let state = c.fuelResetInit();
let read = args.read;
const out = [];
for (const ev of args.events) {
  if (ev.read !== undefined) read = ev.read;
  const e = Object.assign({}, ev, {confirmSec: confirmSec, allowed: c.fuelResetAllowed(read)});
  if (e.type === "yes") e.read = read;
  state = c.fuelResetNext(state, e);
  out.push({state: state, view: c.fuelMpgResetView(read, state, confirmSec)});
}
process.stdout.write(JSON.stringify(out));
"""


def _run(events: list[dict[str, Any]], read: Any,
         stale: Any = STALE) -> list[dict[str, Any]]:
    args: dict[str, Any] = {"js": _JS, "events": events, "read": read}
    if stale is not None:
        args["stale"] = stale
    proc = subprocess.run(
        [_NODE or "node", "-e", _SEQUENCE], input=json.dumps(args),
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _since(step: dict[str, Any]) -> tuple[str, str, str]:
    s = step["view"]["sinceReset"]
    return (s["text"], s["note"], s["line"])


_T0 = _ms("2026-10-20T15:10:00Z")


def _confirmed(answer: dict[str, Any], nowMs: int = _T0) -> list[dict[str, Any]]:
    """Hold, Yes, then the POST's answer."""
    return [{"type": "hold"}, {"type": "yes"},
            {"type": "answer", "status": answer["status"], "body": answer["body"],
             "nowMs": nowMs}]


# ---------------------------------------------------------------------------
# 1. Fixtures
# ---------------------------------------------------------------------------

def test_fixturesArePresent_andDescribed():
    for name in FIXTURE_NAMES:
        fx = _fixture(name)
        assert fx["description"], name
        assert fx["reads"], name


@pytest.mark.parametrize(
    ("name", "label"),
    [(n, r["label"]) for n in FIXTURE_NAMES for r in _fixture(n)["reads"]],
)
def test_everyRead_isWhatTheRealBuilderEmits(name: str, label: str):
    """The page is tested against the provider's real shape, not a typed one."""
    from tests.ui.test_fuel_page import _buildFuelEconomy

    read = next(r for r in _fixture(name)["reads"] if r["label"] == label)
    assert _buildFuelEconomy(read["inputs"], read["now"]) == read["fuel-economy"]


def test_fixtureAnswers_areTheServersShapes():
    """Each answer's status/body pair is one _handleFuelReset can send."""
    answers = [_fixture(n)["response"] for n in FIXTURE_NAMES if "response" in _fixture(n)]
    answers += list(_fixture("reset-write-fails")["responses"].values())
    for a in answers:
        assert a["status"] in (200, 409, 503, 504), a
        if a["status"] == 200:
            assert a["body"]["ok"] is True and a["body"]["resetAtTs"]
        elif a["status"] == 409:
            assert a["body"]["ok"] is False and a["body"]["reason"]
        elif a["status"] == 504:
            assert a["body"]["ok"] is None


# ---------------------------------------------------------------------------
# 2. Reducer + view
# ---------------------------------------------------------------------------

def test_holdTime_isTwoSeconds_withProgressFromLongPressProgress():
    proc = subprocess.run(
        [_NODE or "node", "-e",
         "const c=require(process.argv[1]);process.stdout.write(JSON.stringify("
         "[c.FUEL_RESET_HOLD_MS,c.longPressProgress(1000,c.FUEL_RESET_HOLD_MS),"
         "c.longPressProgress(2500,c.FUEL_RESET_HOLD_MS)]))", _JS],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [2000, 0.5, 1]


@pytest.mark.parametrize("name", ["parked-reset-available", "reset-allowed-true"])
def test_gateOpen_showsTheHint_andTheHoldIsLive(name: str):
    """MOVED PIN (US-923): the hint follows resetAllowed.value === true."""
    label = _fixture(name)["reads"][0]["label"]
    step = _run([{"type": "read"}], _read(name, label))[0]
    assert _since(step) == (OLD_FIGURE, "", HINT)
    assert step["view"]["reset"] == {"pressable": True, "confirm": False}


@pytest.mark.parametrize(
    "name", ["reset-allowed-driving", "reset-allowed-speed-unknown", "reset-allowed-missing"])
def test_validation_gateClosed_holdGivesNoHintNoConfirmNoWord(name: str):
    """MOVED PIN (US-923, was the 'moving' case): {false, driving}, {false,
    speed_unknown} and a missing block -> no hint, no confirm, and no standing
    refusal word (spec s4.3: the words are POST outcomes only)."""
    steps = _run([{"type": "read"}, {"type": "hold"}], _read(name, "read"))
    for step in steps:
        assert _since(step) == (OLD_FIGURE, "", "")
        assert step["view"]["reset"] == {"pressable": False, "confirm": False}
    assert steps[-1]["state"]["phase"] == "idle"


@pytest.mark.parametrize(
    "gate",
    [{"value": "true", "reason": None}, {"value": 1, "reason": None}, {"value": None},
     {}, None, "true", True, [True]],
    ids=["string-true", "one", "null-value", "empty", "null", "string", "bare-true", "list"],
)
def test_onlyAStrictTrueInsideAnObject_offersTheReset(gate: Any):
    read = json.loads(json.dumps(_read("reset-allowed-true", "read")))
    read["resetAllowed"] = gate
    step = _run([{"type": "read"}], read)[0]
    assert step["view"]["reset"]["pressable"] is False
    assert _since(step)[2] == ""


def test_anUnreadableFile_offersNoReset():
    for read in (None, "garbage", []):
        assert _run([{"type": "read"}], read)[0]["view"]["reset"]["pressable"] is False


def test_hold_opensTheConfirm_andNo_changesNothing():
    before = _read("parked-reset-available", "before")
    steps = _run([{"type": "read"}, {"type": "hold"}, {"type": "no"}], before)
    assert steps[1]["view"]["reset"]["confirm"] is True
    assert steps[2]["view"] == steps[0]["view"]
    assert steps[2]["state"] == steps[0]["state"]


def test_theGateClosingUnderAnOpenConfirm_withdrawsIt():
    """MOVED PIN (US-923): the confirm is withdrawn by a read whose gate closed."""
    steps = _run([{"type": "hold"},
                  {"type": "read", "read": _read("reset-allowed-driving", "read")}],
                 _read("parked-reset-available", "before"))
    assert steps[0]["view"]["reset"]["confirm"] is True
    assert steps[1]["view"]["reset"] == {"pressable": False, "confirm": False}


def test_validation_200_resettingFromYesUntilTheMatchingRead():
    """Validation: parked, hold 2 s, Yes; 200 resetAtTs T; next read with T and
    mpg null -> 'resetting…' from Yes until that read, then '--' 'too short yet'."""
    fx = _fixture("parked-reset-available")
    stale = _read("parked-reset-available", "stale")
    after = _read("parked-reset-available", "after")
    steps = _run(
        [{"type": "hold"}, {"type": "yes"},
         {"type": "answer", **fx["response"], "nowMs": _T0},
         {"type": "read", "read": stale, "nowMs": _T0 + 2000},
         {"type": "read", "read": after, "nowMs": _T0 + 4000}],
        _read("parked-reset-available", "before"),
    )
    for step in steps[1:4]:
        assert _since(step) == ("--", RESETTING, ""), step
        assert step["view"]["reset"] == {"pressable": False, "confirm": False}
    assert _since(steps[4])[:2] == ("--", "too short yet")
    assert steps[4]["state"]["outcome"] is None


def test_validation_504_unconfirmed_thenTheLandedRead_neverTheOldFigure():
    """Validation: 504, then the next read has resetAtTs T and mpg null ->
    "unconfirmed", then '--' 'too short yet'."""
    fx = _fixture("reset-unknown-504")
    after = _read("reset-unknown-504", "after")
    steps = _run(_confirmed(fx["response"]) + [{"type": "read", "read": after,
                                                "nowMs": _T0 + 6000}],
                 _read("reset-unknown-504", "before"))
    assert _since(steps[2]) == (OLD_FIGURE, "", UNCONFIRMED)
    last = _since(steps[3])
    assert last[:2] == ("--", "too short yet")
    assert UNCONFIRMED not in last and OLD_FIGURE not in last


def test_validation_200_noMatchingReadWithinSixSeconds_unconfirmed():
    """Validation: 200, no read with resetAtTs T within 6 s -> the latest
    provider value + "unconfirmed". The clock starts AT the 200."""
    fx = _fixture("reset-confirm-timeout")
    stale = _read("reset-confirm-timeout", "stale")
    late = _read("reset-confirm-timeout", "stale-late")
    steps = _run(
        _confirmed(fx["response"], nowMs=_T0)
        + [{"type": "read", "read": stale, "nowMs": _T0 + 4000},
           {"type": "read", "read": stale, "nowMs": _T0 + CONFIRM_SEC * 1000},
           {"type": "read", "read": late, "nowMs": _T0 + CONFIRM_SEC * 1000 + 1}],
        _read("reset-confirm-timeout", "before"),
    )
    assert _since(steps[3]) == ("--", RESETTING, "")
    assert _since(steps[4]) == ("--", RESETTING, ""), "exactly 6 s is still inside"
    assert _since(steps[5]) == (OLD_FIGURE, "", UNCONFIRMED)


def test_confirmWindow_followsTheInjectedValue():
    fx = _fixture("reset-confirm-timeout")
    stale = _read("reset-confirm-timeout", "stale")
    steps = _run(_confirmed(fx["response"]) + [{"type": "read", "read": stale,
                                                "nowMs": _T0 + 8000}],
                 _read("reset-confirm-timeout", "before"),
                 stale={"fuelResetConfirmSec": 10})
    assert _since(steps[3]) == ("--", RESETTING, "")


def test_validation_409Driving_latestProviderValue_plusSlowToReset():
    """MOVED PIN (US-923): 409 driving reads 'slow to reset' (was 'park to reset')."""
    fx = _fixture("reset-refused-driving")
    steps = _run(_confirmed(fx["response"]), _read("reset-refused-driving", "before"))
    assert _since(steps[2]) == (OLD_FIGURE, "", SLOW)


def test_409SpeedUnknown_latestProviderValue_plusSpeedUnknown():
    """US-923: the predicate's other reason reaches the glass as its own word."""
    answer = {"status": 409, "body": {"ok": False, "reason": "speed_unknown"}}
    steps = _run(_confirmed(answer), _read("reset-refused-driving", "before"))
    assert _since(steps[2]) == (OLD_FIGURE, "", SPEED_UNKNOWN)


@pytest.mark.parametrize("case", sorted(_fixture("reset-write-fails")["responses"]))
def test_aRefusedOrFailedWrite_saysCouldntReset_rawTextNeverOnTheGlass(case: str):
    answer = _fixture("reset-write-fails")["responses"][case]
    steps = _run(_confirmed(answer), _read("reset-write-fails", "before"))
    assert _since(steps[2]) == (OLD_FIGURE, "", FAILED)
    raw = answer["body"].get("error") or answer["body"].get("reason")
    assert raw not in json.dumps(steps[2]["view"])


@pytest.mark.parametrize(
    "answer",
    [{"status": 200, "body": {"ok": True}}, {"status": 500, "body": {}},
     {"status": 200, "body": {"ok": True, "resetAtTs": ""}}],
    ids=["200-no-stamp", "undocumented-500", "200-empty-stamp"],
)
def test_anAnswerTheReadCannotSettle_isUnconfirmed(answer: dict[str, Any]):
    steps = _run(_confirmed(answer), _read("parked-reset-available", "before"))
    assert _since(steps[2]) == (OLD_FIGURE, "", UNCONFIRMED)


def test_noAnswerAtAll_isUnconfirmed():
    steps = _run([{"type": "hold"}, {"type": "yes"}, {"type": "failure"}],
                 _read("parked-reset-available", "before"))
    assert _since(steps[2]) == (OLD_FIGURE, "", UNCONFIRMED)


def test_theOutcomeRendersTheLatestRead_neverACachedValue():
    """After a refusal, a NEWER read (the total grew) is what the slot shows."""
    fx = _fixture("reset-refused-driving")
    newer = json.loads(json.dumps(_read("reset-refused-driving", "before")))
    newer["sinceReset"]["mpg"] = 25.04
    steps = _run(_confirmed(fx["response"]) + [{"type": "read", "read": newer,
                                                "nowMs": _T0 + 2000}],
                 _read("reset-refused-driving", "before"))
    assert _since(steps[3]) == ("≈25.0", "", SLOW)


def test_anOutcome_isNeverTheHint_andAHoldAfterItStillWorks():
    fx = _fixture("reset-refused-driving")
    steps = _run(_confirmed(fx["response"]) + [{"type": "hold"}],
                 _read("reset-refused-driving", "before"))
    assert steps[2]["view"]["reset"]["pressable"] is True
    assert steps[3]["view"]["reset"]["confirm"] is True


def test_yesWithoutAnOpenConfirm_doesNothing():
    steps = _run([{"type": "yes"}], _read("parked-reset-available", "before"))
    assert steps[0]["state"]["phase"] == "idle"
    assert _since(steps[0]) == (OLD_FIGURE, "", HINT)


@pytest.mark.parametrize("text", [HINT, RESETTING, SLOW, SPEED_UNKNOWN, FAILED, UNCONFIRMED])
def test_everyResetText_isAtMost15Chars(text: str):
    """MOVED PIN (US-890-i): the fit rule is <= 15 characters (fuel spec s4.6)."""
    assert len(text) <= 15


def test_parkToReset_appearsNowhere():
    """US-923 (fuel spec AC 8): the word is retired, comments included."""
    assert "park to reset" not in open(_JS, encoding="utf-8").read()


_RESET_FUNCTIONS = ("fuelResetAllowed", "fuelResetAnswer", "fuelResetNext",
                    "fuelMpgResetView", "fuelResetOverlay")


@pytest.mark.parametrize("name", _RESET_FUNCTIONS)
def test_theResetCode_readsNoSpeedGearOrParkedState(name: str):
    """US-923 grep gate (fuel spec AC 8): the page computes no gate of its own."""
    body = rh._fnBody(open(_JS, encoding="utf-8").read(), name)
    assert not re.search(r"SPEED|speed\b|gear|[Pp]arked", body), body


def test_theShippedTick_gatesTheResetOnTheReadsOwnResetAllowed():
    """Every fuel-reset call site passes fuelResetAllowed(...), never
    engineParked (which stays the gate for Clear, the tap and Settings)."""
    src = open(_JS, encoding="utf-8").read()
    for call in re.finditer(r"fuel(?:ResetNext|ResetOverlay|MpgResetView)\([^;]*", src):
        assert "engineParked" not in call.group(0), call.group(0)
    assert len(re.findall(r"allowed: fuelResetAllowed\(lastFuelEconomy\)", src)) == 2


# ---------------------------------------------------------------------------
# 3. The confirm window -- injected, never a literal here
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "stale",
    [None, "__DISPLAY_STALE__", {}, {"fuelResetConfirmSec": 0},
     {"fuelResetConfirmSec": -1}, {"fuelResetConfirmSec": "6"},
     {"fuelResetConfirmSec": None}, {"imuSec": 2.0}],
    ids=["absent", "placeholder", "empty", "zero", "negative", "string", "null", "imu-only"],
)
def test_noValidInjectedWindow_theResetIsNotOffered(stale: Any):
    """Without a real window "resetting…" would be unbounded: fail closed."""
    steps = _run([{"type": "read"}, {"type": "hold"}],
                 _read("parked-reset-available", "before"), stale=stale)
    for step in steps:
        assert _since(step) == (OLD_FIGURE, "", "")
        assert step["view"]["reset"] == {"pressable": False, "confirm": False}


def test_theValidatorDefault_isSix():
    from common.config.validator import DEFAULTS

    assert DEFAULTS["pi.display.stale.fuelResetConfirmSec"] == CONFIRM_SEC


def test_carouselJs_holdsNoLiteralForTheConfirmWindow():
    body = rh._fnBody(open(_JS, encoding="utf-8").read(), "resolveFuelResetConfirmSec")
    assert "fuelResetConfirmSec" in body
    assert not re.search(r"\b[1-9]\d*(\.\d+)?\b", body), body


# ---------------------------------------------------------------------------
# 4. A real toCanonicalIso stamp end to end (Iris G-5)
# ---------------------------------------------------------------------------

def test_aRealCanonicalStamp_confirmsEndToEnd():
    """The orchestrator stamps resetAtTs with toCanonicalIso and the emitter
    publishes the stored row's reset_at_ts: the SAME string must reach the 200
    and the read, or every reset reads "unconfirmed"."""
    from common.time.helper import toCanonicalIso
    from tests.ui.test_fuel_page import _buildFuelEconomy

    stamp = toCanonicalIso(datetime(2026, 10, 20, 15, 10, 0, 734512, tzinfo=UTC))
    after = _buildFuelEconomy(
        {"mafTrusted": True, "snap": None, "distanceKm": 0.0, "distanceSinceTs": None,
         "sinceReset": {"fuel_l": 0.0, "distance_km": 0.0, "reset_at_ts": stamp}},
        "2026-10-20T15:10:02Z",
    )
    steps = _run(
        _confirmed({"status": 200, "body": {"ok": True, "resetAtTs": stamp}})
        + [{"type": "read", "read": after, "nowMs": _T0 + 2000}],
        _read("parked-reset-available", "before"),
    )
    assert _since(steps[3])[:2] == ("--", "too short yet")
    assert steps[3]["state"]["outcome"] is None


# ---------------------------------------------------------------------------
# 5. The shipped DOM
# ---------------------------------------------------------------------------

# Parked is the US-511 debounce: the parked GEAR must be HELD for parkedOnS (8 s).
# MOVED PIN (US-511-b): parked is states/gear (P or N), not system-status idle,
# so each boot serves a whole car -- its system-status AND its gear.
def _parkedCar() -> dict[str, Any]:
    return {"/system-status": _parked(), "/gear": _gearParked()}


def _movingCar() -> dict[str, Any]:
    return {"/system-status": _driving(), "/gear": _gearMoving()}


_HOLD_PARKED = [{"flush": 4}, {"advanceMs": 9000, "flush": 4}]
# US-923: the provider refusing, for the boots that need the gate closed.
_GATE_DRIVING = {"/fuel-economy": _read("reset-allowed-driving", "read")}
_HOLD_2S = [{"pointer": {"id": "fuel-since-reset", "type": "pointerdown"}},
            {"advanceMs": 2100, "flush": 2},
            {"pointer": {"id": "fuel-since-reset", "type": "pointerup"}}]


def _find(node: dict[str, Any], pred) -> list[dict[str, Any]]:
    out = [node] if pred(node) else []
    for child in node.get("children", []):
        if "tag" in child:
            out += _find(child, pred)
    return out


def _byId(tree: Any, elementId: str) -> dict[str, Any]:
    roots = tree if isinstance(tree, list) else [tree]
    for root in roots:
        hits = _find(root, lambda n: n.get("attrs", {}).get("id") == elementId)
        if hits:
            return hits[0]
    raise AssertionError(f"no #{elementId}")


def _part(slot: dict[str, Any], cls: str) -> dict[str, Any]:
    hits = _find(slot, lambda n: cls in _classes(n))
    assert len(hits) == 1, cls
    return hits[0]


def _shown(node: dict[str, Any]) -> bool:
    return "hidden" not in node.get("attrs", {})


def _glass(dom: dict[str, Any]) -> tuple[str, str, str]:
    """SINCE RESET as painted: (value, note if shown, line if shown)."""
    slot = _byId(dom["tree"], "fuel-since-reset")
    note = _part(slot, "fuel-note")
    line = _part(slot, "fuel-reset-line")
    return (_textOf(_part(slot, "fuel-value")),
            _textOf(note) if _shown(note) else "",
            _textOf(line) if _shown(line) else "")


def _confirmOpen(dom: dict[str, Any]) -> bool:
    return _shown(_byId(dom["tree"], "fuel-reset-confirm"))


def _boot(steps: list[dict[str, Any]], car: dict[str, Any],
          routes: dict[str, Any] | None = None, stale: Any = STALE) -> dict[str, Any]:
    allRoutes = {**car, "/fuel-economy": _read("parked-reset-available", "before")}
    allRoutes.update(routes or {})
    return rh.runDashboard(routes=allRoutes, nowMs=_T0, steps=steps, displayStale=stale)


def test_dom_shipsTheConfirmHidden_andTheSlotNotPressable():
    dom = _boot([{"flush": 4}], _movingCar(), routes=_GATE_DRIVING)
    assert not _confirmOpen(dom)
    assert _byId(dom["tree"], "fuel-since-reset")["attrs"]["data-pressable"] == "false"


@pytest.mark.parametrize(
    "gate", ["reset-allowed-driving", "reset-allowed-speed-unknown", "reset-allowed-missing"])
def test_dom_validation_gateClosed_threeSecondHold_noHintNoConfirm(gate: str):
    """MOVED PIN (US-923): a PARKED car whose provider says no still offers
    nothing -- the page reads the gate, never engineParked."""
    steps = _HOLD_PARKED + [
        {"pointer": {"id": "fuel-since-reset", "type": "pointerdown"}},
        {"advanceMs": 3000, "flush": 3},
        {"pointer": {"id": "fuel-since-reset", "type": "pointerup"}}, {"flush": 1}]
    dom = _boot(steps, _parkedCar(), routes={"/fuel-economy": _read(gate, "read")})
    assert _glass(dom) == (OLD_FIGURE, "", "")
    assert not _confirmOpen(dom)
    assert not any(f["url"] == "/fuel-reset" for f in dom["fetches"])


def test_dom_validation_slowRollingInGear_isOffered_andAHoldOpensTheConfirm():
    """US-923 (CIO 2026-10-22): rolling <= 5 mph in gear 3 the provider allows
    it, and the page offers it although engineParked is false."""
    dom = _boot(_HOLD_PARKED + _HOLD_2S, _movingCar(),
                routes={"/fuel-economy": _read("reset-allowed-true", "read")})
    assert _glass(dom) == (OLD_FIGURE, "", HINT)
    assert _confirmOpen(dom)


def test_dom_theGateClosingUnderAnOpenConfirm_withdrawsIt():
    steps = _HOLD_PARKED + _HOLD_2S + [
        {"setRoutes": {"/fuel-economy": _read("reset-allowed-driving", "read")}},
        {"advanceMs": 1000, "flush": 2}]
    dom = _boot(steps, _parkedCar())
    assert not _confirmOpen(dom)
    assert _glass(dom) == (OLD_FIGURE, "", "")


def test_dom_parked_showsTheHint_andAHoldOpensTheConfirm():
    dom = _boot(_HOLD_PARKED + _HOLD_2S, _parkedCar())
    assert _glass(dom) == (OLD_FIGURE, "", HINT)
    assert _confirmOpen(dom)
    assert _textOf(_byId(dom["tree"], "fuel-reset-confirm")).startswith("Reset average MPG?")


def test_dom_aHoldShorterThanTwoSeconds_opensNothing():
    steps = _HOLD_PARKED + [
        {"pointer": {"id": "fuel-since-reset", "type": "pointerdown"}},
        {"advanceMs": 1500, "flush": 2},
        {"pointer": {"id": "fuel-since-reset", "type": "pointerup"}},
        {"advanceMs": 1000, "flush": 2}]
    assert not _confirmOpen(_boot(steps, _parkedCar()))


def test_dom_aHoldThatMoves_isCancelled():
    steps = _HOLD_PARKED + [
        {"pointer": {"id": "fuel-since-reset", "type": "pointerdown"}},
        {"pointer": {"id": "fuel-since-reset", "type": "pointermove", "x": 40}},
        {"advanceMs": 2100, "flush": 2}]
    assert not _confirmOpen(_boot(steps, _parkedCar()))


def test_dom_no_closesTheConfirm_andPostsNothing():
    dom = _boot(_HOLD_PARKED + _HOLD_2S + [{"click": "fuel-reset-no"}, {"flush": 1}], _parkedCar())
    assert not _confirmOpen(dom)
    assert _glass(dom) == (OLD_FIGURE, "", HINT)
    assert not any(f["url"] == "/fuel-reset" for f in dom["fetches"])


def test_dom_yes_showsResettingAtOnce_andPostsWithTheToken():
    """'resetting…' from Yes: the POST's answer has not been read yet."""
    fx = _fixture("parked-reset-available")
    dom = _boot(_HOLD_PARKED + _HOLD_2S + [{"click": "fuel-reset-yes"}], _parkedCar(),
                routes={"/fuel-reset": {"__status": 200, "__body": fx["response"]["body"]}})
    assert _glass(dom) == ("--", RESETTING, "")
    assert not _confirmOpen(dom)
    posts = [f for f in dom["fetches"] if f["url"] == "/fuel-reset"]
    assert posts == [{"url": "/fuel-reset", "method": "POST", "token": "test-token"}]


def test_dom_200_holdsResettingUntilTheMatchingRead_thenShowsThatRead():
    fx = _fixture("parked-reset-available")
    steps = _HOLD_PARKED + _HOLD_2S + [
        {"click": "fuel-reset-yes"}, {"flush": 2},
        {"advanceMs": 2000, "flush": 2},
    ]
    routes = {"/fuel-reset": {"__status": 200, "__body": fx["response"]["body"]}}
    mid = _boot(steps, _parkedCar(), routes=routes)
    assert _glass(mid) == ("--", RESETTING, "")
    done = _boot(steps + [{"setRoutes": {"/fuel-economy": _read("parked-reset-available",
                                                                  "after")}},
                          {"advanceMs": 1000, "flush": 2}], _parkedCar(), routes=routes)
    assert _glass(done) == ("--", "too short yet", HINT)


def test_dom_200_noMatchingRead_pastTheWindow_unconfirmed():
    fx = _fixture("reset-confirm-timeout")
    steps = _HOLD_PARKED + _HOLD_2S + [
        {"click": "fuel-reset-yes"}, {"flush": 2},
        {"advanceMs": CONFIRM_SEC * 1000 + 500, "flush": 2}]
    dom = _boot(steps, _parkedCar(),
                routes={"/fuel-reset": {"__status": 200, "__body": fx["response"]["body"]}})
    assert _glass(dom) == (OLD_FIGURE, "", UNCONFIRMED)


@pytest.mark.parametrize(
    ("answer", "line"),
    [(_fixture("reset-refused-driving")["response"], SLOW),
     ({"status": 409, "body": {"ok": False, "reason": "speed_unknown"}}, SPEED_UNKNOWN),
     (_fixture("reset-write-fails")["responses"]["no-channel-503"], FAILED),
     (_fixture("reset-unknown-504")["response"], UNCONFIRMED)],
    ids=["409-driving", "409-speed-unknown", "503", "504"],
)
def test_dom_refusals_paintTheLatestValue_plusTheOutcome(answer: dict[str, Any], line: str):
    steps = _HOLD_PARKED + _HOLD_2S + [{"click": "fuel-reset-yes"}, {"flush": 2}]
    dom = _boot(steps, _parkedCar(),
                routes={"/fuel-reset": {"__status": answer["status"], "__body": answer["body"]}})
    assert _glass(dom) == (OLD_FIGURE, "", line)


def test_dom_504_saysUnconfirmed_andTheRetiredWordIsGone():
    """US-890-i exit test: the 504 path reads 'unconfirmed' on the glass, and
    the retired 16-character word (it ran ~3 px past the MPG column) is in
    neither carousel.js nor dashboard.css. The retired word is assembled here
    so this file does not carry it either."""
    answer = _fixture("reset-unknown-504")["response"]
    steps = _HOLD_PARKED + _HOLD_2S + [{"click": "fuel-reset-yes"}, {"flush": 2}]
    dom = _boot(steps, _parkedCar(),
                routes={"/fuel-reset": {"__status": answer["status"], "__body": answer["body"]}})
    assert _glass(dom) == (OLD_FIGURE, "", "unconfirmed")
    retired = "couldn't" + " confirm"
    for path in (_JS, os.path.join(rh.DASHBOARD_DIR, "dashboard.css")):
        with open(path, encoding="utf-8") as fh:
            assert retired not in fh.read(), path


def test_dom_504_thenTheLandedRead_showsTheNewTotal():
    fx = _fixture("reset-unknown-504")
    steps = _HOLD_PARKED + _HOLD_2S + [
        {"click": "fuel-reset-yes"}, {"flush": 2},
        {"setRoutes": {"/fuel-economy": _read("reset-unknown-504", "after")}},
        {"advanceMs": 2000, "flush": 2}]
    dom = _boot(steps, _parkedCar(),
                routes={"/fuel-reset": {"__status": 504, "__body": fx["response"]["body"]}})
    assert _glass(dom) == ("--", "too short yet", HINT)


def test_dom_unservedPage_noInjectedWindow_offersNoReset():
    dom = _boot(_HOLD_PARKED + _HOLD_2S, _parkedCar(), stale=None)
    assert _glass(dom) == (OLD_FIGURE, "", "")
    assert not _confirmOpen(dom)
