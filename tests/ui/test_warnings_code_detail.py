################################################################################
# File Name: test_warnings_code_detail.py
# Purpose/Description: US-898-c (F-127; specs/v030-warnings-page-design.md
#   s4.5, Iris U4) -- a PARKED tap on an ALERTS code row opens the existing code
#   detail, worded by the provider. The directive band is the entry's sentence
#   (never DTC_TIER's tier table), the chip is the entry's tier, the detail's
#   own states/dtc read backs the record and the clear gate, a failed read says
#   'details unavailable', and the clear stays MINOR-only and locked while not
#   parked ('stop to clear' / 'gear unknown' since US-511-b), a permanent
#   reason winning over that lock. US-511-b: parked is the gear (P or N).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Ralph (Rex)  | Initial -- US-898-c parked code-row tap + detail
#               |              | directive source.
# 2026-10-20    | Ralph (Rex)  | US-899-a2 -- MOVED PIN: DTC_TIER is deleted; the
#               |              | tier-table guard holds its former words frozen.
# 2026-10-22    | Ralph (Rex)  | US-511-b -- MOVED PIN: parked is states/gear; lock
#               |              | words 'stop to clear' / 'gear unknown'; the F2
#               |              | KOEO regression and the fail-closed gear cases.
# 2026-10-22    | Rex (US-923) | Clear stays parked-only while the MPG reset is
#               |              | offered at 5 km/h in gear 3.
# ================================================================================
################################################################################

"""US-898-c tests: a parked tap on a code row opens its detail, provider-worded."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

from tests.ui.test_carousel_dtc_clear_gate_unread import (  # noqa: E402
    _NOW_MS,
    _OPEN_DETAIL,
    _alertsFor,
    _needsNode,
    _raw,
    _readClear,
    _shippedTable,
    _state,
)
from tests.ui.test_carousel_kebab_always_visible import (  # noqa: E402
    _driving,
    _gearAbsent,
    _gearMoving,
    _gearNeutral,
    _gearParked,
    _parked,
    _systemStatus,
)
from tests.ui.test_dtc_detail_hierarchy import _probe  # noqa: E402

_JS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "pi", "ui", "dashboard",
    "carousel.js",
)
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "states", "alerts")

_LABEL_ENABLED = "CLEAR CODES"
# MOVED PIN (US-511-b, Atlas B2; spec warnings :190-195, system 4.7.2): the
# parked lock is the GEAR now, so the word says what unlocks it -- stop -- and
# an unknown gear says so rather than claiming the car is moving.
_LABEL_MOVING = "🔒 CLEAR CODES — stop to clear"
_LABEL_GEAR_UNKNOWN = "🔒 CLEAR CODES — gear unknown"
_LABEL_SEVERITY = "🔒 CLEAR CODES — a STOP/WATCH code is present"
_LABEL_UNKNOWN = "🔒 CLEAR CODES — severity could not be determined"
_UNAVAILABLE = "details unavailable"
# Not parked yet: a parked gear seen, but the 8 s hold not served.
_TAP_UNHELD = [{"flush": 4}, {"clickNth": {"selector": ".warn-row-code", "index": 0}}, {"flush": 2}]
# Parked -> not parked needs not-parked held >= parkedOffS (3 s): a tick must SEE
# it first (the hold anchors there), then the clock moves past the hold.
# MOVED PIN (US-511-b): was _START_ENGINE (system-status -> driving). Starting
# the engine stopped is N -- still parked -- so what locks it is pulling away.
_PULL_AWAY = [{"setRoutes": {"/system-status": _driving(), "/gear": _gearMoving()}},
              {"flush": 4}, {"advanceMs": 4000, "flush": 4}]


# ---------------------------------------------------------------------------
# Inputs, built by the REAL producers from the shipped severity table.
# ---------------------------------------------------------------------------


def _carPair() -> dict[str, Any]:
    """The car's two stored codes: P0400 WATCH and P0443 MINOR."""
    return _state([_raw("P0400"), _raw("P0443")], table=_shippedTable())


def _minorAlone() -> dict[str, Any]:
    return _state([_raw("P0443")], table=_shippedTable())


def _entryFor(dtcState: dict[str, Any], code: str) -> dict[str, Any]:
    for entry in _alertsFor(dtcState)["entries"]:
        if entry["key"] == code:
            return entry
    raise AssertionError(f"the provider published no entry for {code}")


def _recordFor(dtcState: dict[str, Any], code: str) -> dict[str, Any]:
    return next(c for c in dtcState["codes"] if c["code"] == code)


def _view(record: Any, entry: Any) -> Any:
    return _probe("codeDetailView", record, entry)


# ---------------------------------------------------------------------------
# The rendered panel.
# ---------------------------------------------------------------------------


def _textOf(node: dict[str, Any]) -> str:
    out = []
    for child in node.get("children", []):
        out.append(child["text"] if "text" in child else _textOf(child))
    return "".join(out)


def _boot(routes: dict[str, Any], steps: list[dict[str, Any]]) -> tuple[rh.Surface, dict]:
    out = rh.runDashboard(routes=routes, steps=steps, nowMs=_NOW_MS)
    return rh.dashboardSurface(out["tree"]), out


def _routes(
    dtcState: Any,
    system: dict[str, Any] | None = None,
    dtc: bool = True,
    gear: Any = "parked",
) -> dict:
    # MOVED PIN (US-511-b): parked is states/gear (P/N). `gear=None` serves no
    # gear file at all (the route 404s) -- boot before the first connect, or
    # pi.gear.enabled false.
    routes: dict[str, Any] = {
        "/alerts": _alertsFor(dtcState),
        "/system-status": system if system is not None else _parked(),
    }
    if gear == "parked":
        routes["/gear"] = _gearParked()
    elif gear is not None:
        routes["/gear"] = gear
    if dtc:
        routes["/dtc"] = dtcState
    return routes


def _detailOpen(surface: rh.Surface) -> bool:
    path = surface.pathById("dtc-detail")
    return path is not None and surface.rendered(path)


def _detailText(surface: rh.Surface) -> str:
    path = surface.pathById("detail-body")
    assert path is not None, "the detail body is gone from the markup"
    return _textOf(path[-1])


def _onlyRendered(surface: rh.Surface, cls: str) -> dict[str, Any]:
    paths = [p for p in surface.pathsByClass(cls) if surface.rendered(p)]
    assert len(paths) == 1, f"expected one painted .{cls}, got {len(paths)}"
    return paths[0][-1]


# ---------------------------------------------------------------------------
# Pure views (the SSOT the DOM layer paints).
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(
    ("entryId", "code"),
    [
        ("code:P0400:watch", "P0400"),
        ("code:P2187:unrated", "P2187"),
        ("engine:COOLANT:stop", None),
        ("code:P0400", None),
        (None, None),
    ],
)
def test_codeFromEntryId_parsesTheCodeOutOfCodeIdsOnly(entryId: Any, code: Any):
    assert _probe("codeFromEntryId", entryId) == code


@_needsNode
def test_codeDetailView_bandIsTheEntrysSentence_chipIsTheEntrysTier():
    """
    Given: the provider's P0400 entry and its states/dtc record
    When: the detail view is built
    Then: the band is the entry's sentence verbatim, the chip WATCH, and the
          record still supplies the short text, status and fix.
    """
    state = _carPair()
    entry = _entryFor(state, "P0400")
    view = _view(_recordFor(state, "P0400"), entry)

    assert view["directive"] == entry["sentence"] == "Drive gently. Get it diagnosed."
    assert view["chip"] == "WATCH"
    assert view["level"] == "watch"
    assert view["code"] == "P0400"
    assert view["short"] == _recordFor(state, "P0400")["short"]
    assert view["unavailable"] is None
    assert view["statusMeta"] and view["fix"] and view["freezeFrame"]


@_needsNode
def test_codeDetailView_neverPrintsATierTableDirective():
    """Iris U4: no tier, with or without a record, prints DTC_TIER's words.

    MOVED PIN (US-899-a2): DTC_TIER is deleted, so its former directive words
    are frozen here and the table itself must stay gone."""
    js = open(_JS, encoding="utf-8").read()
    assert not re.search(r"\bDTC_TIER\b", js), "the tier table is back"
    tierWords = {
        "REDUCE LOAD · PULL OVER",
        "DRIVE GENTLY · GET DIAGNOSED",
        "SAFE TO CLEAR ONCE LOGGED",
        "GET DIAGNOSED",
        "not applicable to this vehicle",
    }

    for tier in ("stop", "watch", "minor", "unrated"):
        entry = {"id": f"code:P0999:{tier}", "source": "code", "key": "P0999",
                 "tier": tier, "title": "P0999", "sentence": ""}
        for record in (None, {"code": "P0999", "severity": tier, "status": "stored"}):
            view = _view(record, entry)
            assert view["directive"] is None, (tier, record, view)
            assert view["directive"] not in tierWords

    body = rh._fnBody(js, "codeDetailView")
    assert "dtcTier(" not in body and "DTC_TIER" not in body


@_needsNode
def test_codeDetailView_unratedEntry_drawsTheUnknownStyling():
    state = _state([_raw("P2187")], table=_shippedTable())
    entry = _entryFor(state, "P2187")
    assert entry["tier"] == "unrated", "the provider moved -- this test is vacuous"
    view = _view(_recordFor(state, "P2187"), entry)
    assert view["chip"] == "UNRATED"
    assert view["level"] == "unknown"
    assert view["directive"] == entry["sentence"]


@_needsNode
@pytest.mark.parametrize("record", [None, {"code": "P0443", "severity": "minor"}])
def test_codeDetailView_noRecordForThisCode_isTheEntryPlusDetailsUnavailable(record: Any):
    """
    Given: the P0400 entry and no states/dtc record for P0400 (the read failed,
           or the payload lists another code)
    When: the view is built
    Then: the entry's title, chip and sentence stand, plus 'details
          unavailable' -- and nothing the record would have supplied.
    """
    entry = _entryFor(_carPair(), "P0400")
    view = _view(record, entry)

    assert view["unavailable"] == _UNAVAILABLE
    assert view["title"] == view["short"] == "EGR FLOW (P0400)"
    assert view["chip"] == "WATCH"
    assert view["directive"] == "Drive gently. Get it diagnosed."
    for absent in ("long", "caveat", "statusMeta", "freezeFrame", "fix"):
        assert view[absent] is None, absent
    assert view["logged"] is False and view["syncAcked"] is False


@_needsNode
@pytest.mark.parametrize(
    "entry",
    [
        None,
        {"id": "engine:BATTERY_V:watch", "source": "engine", "tier": "watch", "sentence": "x"},
        {"id": "nonsense", "source": "code", "tier": "watch", "sentence": "x"},
    ],
)
def test_codeDetailView_onlyACodeEntryOpensADetail(entry: Any):
    assert _view(None, entry) is None


# --- the clear gate's parked input -----------------------------------------


def _gate(state: Any, *parked: Any) -> dict[str, Any]:
    view = _probe("clearButtonView", state, *parked)
    assert isinstance(view, dict), view
    return view


@_needsNode
def test_clearButtonView_minorParked_isEnabled():
    view = _gate(_minorAlone(), True)
    assert view == {"visible": True, "enabled": True, "reason": "ok", "label": _LABEL_ENABLED}


@_needsNode
@pytest.mark.parametrize("parked", [False, None], ids=["false", "null"])
def test_clearButtonView_minorNotParked_gearKnown_isLockedStopToClear(parked: Any):
    """MOVED PIN (US-511-b): a KNOWN gear that is not held parked says 'stop to
    clear'. Only a strict true unlocks; null is not parked (never optimistic)."""
    view = _gate(_minorAlone(), parked, True)
    assert view == {"visible": True, "enabled": False, "reason": "moving", "label": _LABEL_MOVING}
    assert "moving" not in view["label"].lower()


@_needsNode
@pytest.mark.parametrize(
    "args",
    [(False, False), (False, None), (False,), (), (False, "true"), (None, 1)],
    ids=["gear-unknown", "gear-null", "gear-absent", "both-absent", "string-true", "number"],
)
def test_clearButtonView_minorNotParked_gearUnknown_isLockedGearUnknown(args: tuple):
    """US-511-b (Atlas B2): no gear file / `available` not strictly true ->
    'parked_unknown', worded 'gear unknown'. Only a strict true is known."""
    view = _gate(_minorAlone(), *args)
    assert view == {
        "visible": True, "enabled": False, "reason": "parked_unknown",
        "label": _LABEL_GEAR_UNKNOWN,
    }
    assert "moving" not in view["label"].lower()


@_needsNode
def test_clearButtonView_parked_ignoresGearKnown_soOnlyTheGateDecides():
    """A parked car is unlocked whatever the raw gear word would have been."""
    for known in (True, False):
        assert _gate(_minorAlone(), True, known)["reason"] == "ok"


@_needsNode
@pytest.mark.parametrize(
    ("state", "reason"),
    [
        (lambda: _carPair(), "severity_present"),
        (lambda: _state([_raw("P2187")], table=_shippedTable()), "severity_unknown"),
        (lambda: _state([_raw("P0443", syncAcked=False)], table=_shippedTable()), "sync_pending"),
        (lambda: _state([_raw("P0443")], table=_shippedTable(), lock=["P0443"]),
         "session_locked"),
    ],
    ids=["watch", "unrated", "sync", "session-lock"],
)
def test_clearButtonView_aPermanentReasonWinsOverNotParked(state: Any, reason: str):
    """A WATCH code seen while driving must not imply that parking unlocks it."""
    payload = state()
    assert _gate(payload, False)["reason"] == reason
    assert _gate(payload, True)["reason"] == reason
    assert _gate(payload, False)["enabled"] is False
    # US-511-b: neither lock word (gear known or not) outranks a permanent one.
    assert _gate(payload, False, True)["reason"] == reason
    assert _gate(payload, False, False)["reason"] == reason


@_needsNode
def test_clearButtonView_nothingToClear_staysHiddenWhetherParkedOrNot():
    for parked in (True, False):
        assert _gate(_state([]), parked)["visible"] is False


# ---------------------------------------------------------------------------
# The panel (the SHIPPED carousel.js over the SHIPPED markup).
# ---------------------------------------------------------------------------


@_needsNode
def test_parkedTapOnEgrFlow_opensTheDetailWithTheProviderBand_clearDisabledWatch():
    """
    Validation 1: a parked tap on 'EGR FLOW (P0400)' opens the detail; the band
    reads 'Drive gently. Get it diagnosed.'; the clear button is visible but
    disabled (WATCH).
    """
    surface, out = _boot(_routes(_carPair()), _OPEN_DETAIL)
    rows = surface.pathsByClass("warn-row-code")
    assert rows and rows[0][-1]["attrs"].get("data-id") == "code:P0400:watch"

    assert _detailOpen(surface), "a parked tap did not open the detail"
    band = _onlyRendered(surface, "detail-directive")
    assert _textOf(band).strip() == "Drive gently. Get it diagnosed."
    assert band["attrs"].get("data-level") == "watch"
    chip = _onlyRendered(surface, "dtc-chip")
    assert _textOf(chip).strip() == "WATCH"
    assert _UNAVAILABLE not in _detailText(surface)

    clear = _readClear(out)
    assert clear["buttonPaints"] and clear["disabled"] is True, clear
    assert clear["reason"] == "severity_present" and clear["label"] == _LABEL_SEVERITY, clear


@_needsNode
@pytest.mark.parametrize(
    ("system", "gear", "steps"),
    [
        (_driving(), _gearMoving(), _OPEN_DETAIL),
        (_parked(), _gearParked(), _TAP_UNHELD),
    ],
    ids=["driving", "parked-gear-not-yet-held"],
)
def test_notParkedTapOnACodeRow_opensNothing(system: dict, gear: dict, steps: list):
    """Validation 2: while not parked (driving, or inside the 8 s hold) nothing opens.

    MOVED PIN (US-511-b): the driving case is an engaged gear; the unheld case
    is a parked GEAR seen for one tick (page load with gear P, VC 6).
    """
    surface, _ = _boot(_routes(_carPair(), system=system, gear=gear), steps)
    assert surface.pathsByClass("warn-row-code"), "no code row was painted -- vacuous"
    assert not _detailOpen(surface)


@_needsNode
def test_parkedTap_statesDtcReadFails_titleChipSentencePlusDetailsUnavailable():
    """
    Validation 3: the detail's states/dtc read fails (the route 404s) -> the
    entry's own title, chip and sentence plus 'details unavailable'; no
    freeze-frame, fix or clear drawn from anything cached.
    """
    surface, out = _boot(_routes(_carPair(), dtc=False), _OPEN_DETAIL)

    assert _detailOpen(surface)
    text = _detailText(surface)
    assert "EGR FLOW (P0400)" in text
    assert _textOf(_onlyRendered(surface, "dtc-chip")).strip() == "WATCH"
    assert _textOf(_onlyRendered(surface, "detail-directive")).strip() == (
        "Drive gently. Get it diagnosed."
    )
    assert _textOf(_onlyRendered(surface, "detail-unavailable")).strip() == _UNAVAILABLE
    for absent in ("detail-freeze", "detail-fix", "detail-footer", "detail-meta"):
        assert not surface.pathsByClass(absent), absent

    clear = _readClear(out)
    assert clear["zonePaints"] is False and clear["buttonPaints"] is False, clear


@_needsNode
@pytest.mark.parametrize(
    ("logged", "syncAcked", "footer"),
    [
        (True, True, "✓ logged · ✓ synced"),
        (True, False, "✓ logged · not synced"),
        (False, False, "not logged · not synced"),
        (False, True, "not logged · ✓ synced"),
    ],
    ids=["logged-synced", "logged-unsynced", "unlogged-unsynced", "unlogged-synced"],
)
def test_dtcDetailFooter_oneSeparator_forEveryLoggedAndSyncState(
    logged: bool, syncAcked: bool, footer: str
):
    """
    US-759 (Iris S120 batch; review F1): the log/sync footer is two plain facts
    joined by exactly one ' · '. Each half renders its own field, so an
    impossible record (not logged, synced) shows as it is, never masked. Was
    '✓ logged · · sync pending' on the car (CIO 2026-09-14).
    """
    state = _state([_raw("P0443", logged=logged, syncAcked=syncAcked)], table=_shippedTable())
    surface, _ = _boot(_routes(state), _OPEN_DETAIL)

    assert _detailOpen(surface), "a parked tap did not open the detail -- vacuous"
    text = _textOf(_onlyRendered(surface, "detail-footer")).strip()
    assert text == footer
    assert text.count("·") == 1
    assert "· ·" not in text


@_needsNode
def test_engineRow_isNotAControl_andATapOpensNothing():
    alerts = json.load(open(os.path.join(_FIXTURES, "watch-battery-low.json"), encoding="utf-8"))
    assert alerts["entries"][0]["source"] == "engine", "fixture moved -- vacuous"
    surface, _ = _boot(
        {"/alerts": alerts, "/system-status": _parked(), "/gear": _gearParked()},
        [{"flush": 4}, {"advanceMs": 9000, "flush": 4},
         {"clickNth": {"selector": ".warn-row", "index": 0}}, {"flush": 2}],
    )
    assert not surface.pathsByClass("warn-row-code")
    assert not _detailOpen(surface)


@_needsNode
def test_minorOpenParked_thenTheCarPullsAway_theClearLocksStopToClear():
    """
    MOVED PIN (US-511-b): was ..._thenTheEngineStarts_theClearLocksEngineOffToClear.

    Given: the detail open on a lone, logged, acked MINOR code while parked
    When: the car pulls away under it (gear 3 held past parkedOffS)
    Then: the button stays visible but disabled, reason `moving`, label
          'stop to clear'; the detail stays open.
    """
    _, before = _boot(_routes(_minorAlone()), _OPEN_DETAIL)
    opened = _readClear(before)
    assert opened["disabled"] is False and opened["reason"] == "ok", opened

    surface, after = _boot(_routes(_minorAlone()), [*_OPEN_DETAIL, *_PULL_AWAY])
    assert _detailOpen(surface)
    got = _readClear(after)
    assert got["buttonPaints"] and got["disabled"] is True, got
    assert got["reason"] == "moving" and got["label"] == _LABEL_MOVING, got


@_needsNode
def test_slowRollingInGear3_theMpgResetIsOffered_butClearStaysParkedOnly():
    """
    US-923 VC: Clear at a fresh SPEED 5 km/h in gear 3 -> refused. The provider
    allows the MPG reset there (resetAllowed true), and the page offers it, but
    Clear stays on engineParked: one page, two gates, neither borrowing the other.
    """
    slow = {"/fuel-economy": {"thisDrive": None, "sinceReset": None, "ts": None,
                              "recent": None,
                              "resetAllowed": {"value": True, "reason": None}}}
    routes = {**_routes(_minorAlone()), **slow}
    # The reset is offered only with a real confirm window injected (fail closed).
    after = rh.runDashboard(routes=routes, steps=[*_OPEN_DETAIL, *_PULL_AWAY], nowMs=_NOW_MS,
                            displayStale={"fuelResetConfirmSec": 6})
    surface = rh.dashboardSurface(after["tree"])
    got = _readClear(after)
    assert got["disabled"] is True and got["label"] == _LABEL_MOVING, got
    slot = surface.pathById("fuel-since-reset")
    assert slot is not None and slot[-1]["attrs"]["data-pressable"] == "true"


@_needsNode
@pytest.mark.parametrize(
    "gearAfter",
    [None, _gearAbsent("engine_off_rolling"), _gearAbsent("link_down")],
    ids=["gear-file-gone", "engine-off-rolling", "link-down"],
)
def test_minorOpenParked_thenTheGearGoesUnknown_theClearLocksGearUnknown(gearAfter: Any):
    """
    US-511-b VC 4/5: the gear file disappears, or the deriver publishes a typed
    absence -> not parked (after parkedOffS) and the lock word is the CURRENT
    raw gear's: 'gear unknown', never 'stop to clear'.
    """
    steps = [*_OPEN_DETAIL, {"setRoutes": {"/gear": gearAfter}}, {"flush": 4},
             {"advanceMs": 4000, "flush": 4}]
    surface, out = _boot(_routes(_minorAlone()), steps)
    assert _detailOpen(surface)
    got = _readClear(out)
    assert got["buttonPaints"] and got["disabled"] is True, got
    assert got["reason"] == "parked_unknown" and got["label"] == _LABEL_GEAR_UNKNOWN, got


@_needsNode
def test_watchOpenParked_thenTheCarPullsAway_theWatchReasonStillWins():
    """MOVED PIN (US-511-b): was ..._thenTheEngineStarts_...; same claim."""
    surface, out = _boot(_routes(_carPair()), [*_OPEN_DETAIL, *_PULL_AWAY])
    got = _readClear(out)
    assert got["reason"] == "severity_present" and got["label"] == _LABEL_SEVERITY, got


@_needsNode
def test_unratedCodeOpenParked_chipUnratedUnknownStyling_clearDisabled():
    state = _state([_raw("P2187")], table=_shippedTable())
    surface, out = _boot(_routes(state), _OPEN_DETAIL)
    chip = _onlyRendered(surface, "dtc-chip")
    assert _textOf(chip).strip() == "UNRATED"
    assert chip["attrs"].get("data-level") == "unknown"
    got = _readClear(out)
    assert got["disabled"] is True and got["reason"] == "severity_unknown", got
    assert got["label"] == _LABEL_UNKNOWN, got


# ---------------------------------------------------------------------------
# US-511-b (Atlas B1): every parked-only control reads ONE fact -- the derived
# gear is P or N. Observed through the code-row tap, a shipped consumer of
# engineParked.parked, on the SHIPPED page.
# ---------------------------------------------------------------------------


def _connectedIdle() -> dict[str, Any]:
    """KOEO after a connect: the link is up, so system-status idle is FALSE."""
    payload = _systemStatus(obdAvailable=True, driveState="idle")
    assert payload["idle"] is False, "fixture drifted -- a connected car is not idle"
    return payload


@_needsNode
def test_koeoGearP_connected_idleFalse_isParkedAfterTheHold_theF2Regression():
    """
    VC 1 (the F2 regression -- red before this story): gear P held 8 s with
    system-status idle FALSE (the link connected earlier) -> parked: the
    code-row tap opens, and the Clear label is not 'stop to clear'.
    """
    surface, out = _boot(_routes(_minorAlone(), system=_connectedIdle()), _OPEN_DETAIL)
    assert _detailOpen(surface), "gear P held past the hold did not unlock the tap"
    got = _readClear(out)
    assert got["reason"] == "ok" and got["label"] == _LABEL_ENABLED, got


@_needsNode
def test_idlingStoppedInNeutral_isParked():
    """VC 2: gear N held 8 s -> parked (an idling car, not only engine off)."""
    surface, _ = _boot(
        _routes(_minorAlone(), system=_connectedIdle(), gear=_gearNeutral()), _OPEN_DETAIL
    )
    assert _detailOpen(surface)


@_needsNode
def test_parkedThenGear3_isNotParkedWithinThreeSeconds():
    """VC 3: gear 3 after parked -> not parked within parkedOffS (3 s)."""
    steps = [
        {"flush": 4}, {"advanceMs": 9000, "flush": 4},
        {"setRoutes": {"/gear": _gearMoving()}}, {"flush": 1},
        {"advanceMs": 3000, "flush": 1},
        {"clickNth": {"selector": ".warn-row-code", "index": 0}}, {"flush": 2},
    ]
    surface, _ = _boot(_routes(_minorAlone(), system=_connectedIdle()), steps)
    assert surface.pathsByClass("warn-row-code"), "no code row was painted -- vacuous"
    assert not _detailOpen(surface)


@_needsNode
@pytest.mark.parametrize(
    "gear",
    [
        _gearMoving(),
        _gearAbsent("not_calibrated"),
        _gearAbsent("no_data"),
        _gearAbsent("stale"),
        _gearAbsent("link_down"),
        _gearAbsent("engine_off_rolling"),
        None,
    ],
    ids=["gear-3", "not_calibrated", "no_data", "stale", "link_down",
         "engine_off_rolling", "no-gear-file"],
)
def test_aGearThatIsNotPOrN_isNeverParked_heldOrNot(gear: Any):
    """
    Fail closed: anything but an available P or N -- an engaged gear, every
    typed absence, or no gear file at all (boot before the first connect) --
    is not parked, however long it is held. System-status says idle TRUE here
    on purpose: idle must not unlock anything any more.
    """
    surface, _ = _boot(_routes(_minorAlone(), gear=gear), _OPEN_DETAIL)
    assert surface.pathsByClass("warn-row-code"), "no code row was painted -- vacuous"
    assert not _detailOpen(surface)


@_needsNode
def test_gearDerivationDisabled_publishesNoGear_soEveryParkedOnlyControlStaysLocked():
    """
    pi.gear.enabled false (bench only): the deriver is not built, so no
    states/gear is ever written -- and with no gear file nothing parked-only
    unlocks, even held well past the hold.
    """
    from pi.obdii.gear_derivation import createGearDeriverFromConfig

    assert createGearDeriverFromConfig({"pi": {"gear": {"enabled": False}}}) is None
    steps = [{"flush": 4}, {"advanceMs": 60000, "flush": 4},
             {"clickNth": {"selector": ".warn-row-code", "index": 0}}, {"flush": 2}]
    surface, _ = _boot(_routes(_minorAlone(), gear=None), steps)
    assert surface.pathsByClass("warn-row-code"), "no code row was painted -- vacuous"
    assert not _detailOpen(surface)
    assert _probe("gearParked", None) is False
