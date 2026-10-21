################################################################################
# File Name: test_warnings_code_detail.py
# Purpose/Description: US-898-c (F-127; specs/v030-warnings-page-design.md
#   s4.5, Iris U4) -- a PARKED tap on an ALERTS code row opens the existing code
#   detail, worded by the provider. The directive band is the entry's sentence
#   (never DTC_TIER's tier table), the chip is the entry's tier, the detail's
#   own states/dtc read backs the record and the clear gate, a failed read says
#   'details unavailable', and the clear stays MINOR-only and locked while not
#   parked ('engine off to clear'), a permanent reason winning over that lock.
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
from tests.ui.test_carousel_kebab_always_visible import _driving, _parked  # noqa: E402
from tests.ui.test_dtc_detail_hierarchy import _probe  # noqa: E402

_JS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "src", "pi", "ui", "dashboard",
    "carousel.js",
)
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "states", "alerts")

_LABEL_ENABLED = "CLEAR CODES"
_LABEL_MOVING = "🔒 CLEAR CODES — engine off to clear"
_LABEL_SEVERITY = "🔒 CLEAR CODES — a STOP/WATCH code is present"
_LABEL_UNKNOWN = "🔒 CLEAR CODES — severity could not be determined"
_UNAVAILABLE = "details unavailable"
# Not parked yet: idle seen, but the 8 s hold not served.
_TAP_UNHELD = [{"flush": 4}, {"clickNth": {"selector": ".warn-row-code", "index": 0}}, {"flush": 2}]
# Parked -> not parked needs not-idle held >= parkedOffS (3 s): a tick must SEE
# not-idle first (the hold anchors there), then the clock moves past the hold.
_START_ENGINE = [{"setRoutes": {"/system-status": _driving()}}, {"flush": 4},
                 {"advanceMs": 4000, "flush": 4}]


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


def _routes(dtcState: Any, system: dict[str, Any] | None = None, dtc: bool = True) -> dict:
    routes: dict[str, Any] = {
        "/alerts": _alertsFor(dtcState),
        "/system-status": system if system is not None else _parked(),
    }
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
@pytest.mark.parametrize("parked", [(False,), (None,), ()], ids=["false", "null", "absent"])
def test_clearButtonView_minorNotParked_isLockedEngineOffToClear(parked: tuple):
    """Only a strict true unlocks; absent/null is not parked (never optimistic)."""
    view = _gate(_minorAlone(), *parked)
    assert view == {"visible": True, "enabled": False, "reason": "moving", "label": _LABEL_MOVING}
    assert "moving" not in view["label"].lower()


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
    ("system", "steps"),
    [
        (_driving(), _OPEN_DETAIL),
        (_parked(), _TAP_UNHELD),
    ],
    ids=["driving", "idle-not-yet-held"],
)
def test_notParkedTapOnACodeRow_opensNothing(system: dict, steps: list):
    """Validation 2: while not parked (driving, or inside the 8 s hold) nothing opens."""
    surface, _ = _boot(_routes(_carPair(), system=system), steps)
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
def test_engineRow_isNotAControl_andATapOpensNothing():
    alerts = json.load(open(os.path.join(_FIXTURES, "watch-battery-low.json"), encoding="utf-8"))
    assert alerts["entries"][0]["source"] == "engine", "fixture moved -- vacuous"
    surface, _ = _boot(
        {"/alerts": alerts, "/system-status": _parked()},
        [{"flush": 4}, {"advanceMs": 9000, "flush": 4},
         {"clickNth": {"selector": ".warn-row", "index": 0}}, {"flush": 2}],
    )
    assert not surface.pathsByClass("warn-row-code")
    assert not _detailOpen(surface)


@_needsNode
def test_minorOpenParked_thenTheEngineStarts_theClearLocksEngineOffToClear():
    """
    Given: the detail open on a lone, logged, acked MINOR code while parked
    When: the engine starts under it (not-idle held past parkedOffS)
    Then: the button stays visible but disabled, reason `moving`, label
          'engine off to clear'; the detail stays open.
    """
    _, before = _boot(_routes(_minorAlone()), _OPEN_DETAIL)
    opened = _readClear(before)
    assert opened["disabled"] is False and opened["reason"] == "ok", opened

    surface, after = _boot(_routes(_minorAlone()), [*_OPEN_DETAIL, *_START_ENGINE])
    assert _detailOpen(surface)
    got = _readClear(after)
    assert got["buttonPaints"] and got["disabled"] is True, got
    assert got["reason"] == "moving" and got["label"] == _LABEL_MOVING, got


@_needsNode
def test_watchOpenParked_thenTheEngineStarts_theWatchReasonStillWins():
    surface, out = _boot(_routes(_carPair()), [*_OPEN_DETAIL, *_START_ENGINE])
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
