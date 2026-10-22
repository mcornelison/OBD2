################################################################################
# File Name: test_dtc_pending_carry.py
# Purpose/Description: US-897-e [F-161] -- the carried pending set is replaced
#   ONLY when Mode 07 answered (the same predicate that advances
#   pendingCheckedAtTs). A key-on read whose Mode 07 raised or answered null
#   keeps publishing the carried pending codes under the unchanged time, so the
#   alerts arbiter never deletes a live pending-code entry (ARCH-062: not
#   checked must never read as clear).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-21    | Ralph (Rex)  | Initial -- US-897-e VCs 1, 2, 4 + post-clear.
# ================================================================================
################################################################################

"""US-897-e: pending codes are carried until Mode 07 answers."""

from __future__ import annotations

import json
import types
from types import SimpleNamespace

import pytest

from pi.obdii.alerts_arbiter import AlertsArbiter
from pi.obdii.dtc_client import DiagnosticCode, Mode07ProbeResult
from pi.obdii.dtc_logger import KeyOnDtcResult
from pi.obdii.orchestrator.event_router import EventRouterMixin
from pi.splash import dtc_emitter
from pi.splash.dtc_emitter import DTC_FILENAME, makeDtcEmitter

_T0 = "2026-10-21T18:00:00Z"
_T1 = "2026-10-21T18:05:00Z"

# Minimal severity table in the loader's output shape: P0400 is a WATCH so a
# lost entry would be a lost alert, P0443 a MINOR stored beside it.
_TABLE = {
    "P0400": {
        "severity": "watch", "severityCaveat": None, "short": "EGR flow",
        "long": "EGR flow", "suggestedFix": None, "fixProvenance": "none",
        "clearEligible": False,
    },
    "P0443": {
        "severity": "minor", "severityCaveat": None, "short": "Purge valve",
        "long": "Purge valve", "suggestedFix": None, "fixProvenance": "none",
        "clearEligible": True,
    },
}

# The two failed-Mode-07 shapes DtcLogger.logKeyOnDtcs returns: a raise is
# caught and reported as not_probed; a null frame as unsupported (dtc_client
# readPendingDtcs). Both are supported=False.
_MODE07_RAISED = Mode07ProbeResult(supported=False, reason="not_probed")
_MODE07_NULL = Mode07ProbeResult(supported=False, reason="unsupported")
_MODE07_ANSWERED = Mode07ProbeResult(supported=True, reason="supported")


class _Host(EventRouterMixin):
    """Just what _emitDtcState touches: the real emitter and the real arbiter."""

    def __init__(self, statesDir: str):
        self._dtcEmitter = makeDtcEmitter(statesDir, severityTable=_TABLE)
        self._alertsArbiter = AlertsArbiter({}, driveIdProvider=lambda: None)
        self._database = None
        self._dtcCarriedPending = []
        self._dtcCheckedAtTs = None
        self._dtcPendingCheckedAtTs = None


def _keyOn(codes, probe):
    return KeyOnDtcResult(
        storedCount=sum(c.status == "stored" for c in codes),
        pendingCount=sum(c.status == "pending" for c in codes),
        mode07Probe=probe,
        codes=list(codes),
    )


@pytest.fixture()
def clock(monkeypatch):
    now = {"iso": _T0}
    monkeypatch.setattr(dtc_emitter, "dtcNowIso", lambda: now["iso"])
    return now


@pytest.fixture()
def carrying(tmp_path, clock):
    """A host whose answered key-on read published pending P0400 at T0."""
    host = _Host(str(tmp_path))
    host._emitDtcState(
        _keyOn([DiagnosticCode("P0400", "EGR flow", "pending")], _MODE07_ANSWERED)
    )
    clock["iso"] = _T1
    return host


def _dtc(tmp_path):
    return json.loads((tmp_path / DTC_FILENAME).read_text(encoding="utf-8"))


def _activeCodeKeys(host):
    return sorted(
        e.key for e in host._alertsArbiter.episodes() if e.source == "code" and e.active
    )


@pytest.mark.parametrize("probe", [_MODE07_RAISED, _MODE07_NULL], ids=["raised", "null"])
def test_failedMode07_keepsTheCarriedPendingCode_andItsTime(tmp_path, carrying, probe):
    """VC 1 / VC 2: carried pending P0400, then a key-on read whose Mode 07 failed."""
    carrying._emitDtcState(_keyOn([DiagnosticCode("P0443", "", "stored")], probe))

    dtc = _dtc(tmp_path)
    assert [(c["code"], c["status"]) for c in dtc["codes"]] == [
        ("P0443", "stored"), ("P0400", "pending"),
    ]
    assert dtc["checkedAtTs"] == _T1
    assert dtc["pendingCheckedAtTs"] == _T0
    assert [c.code for c in carrying._dtcCarriedPending] == ["P0400"]
    assert _activeCodeKeys(carrying) == ["P0400", "P0443"]


def test_failedMode07_codeNowStored_isListedOnce(tmp_path, carrying):
    """A carried pending code that the read found STORED is listed once, stored."""
    carrying._emitDtcState(
        _keyOn([DiagnosticCode("P0400", "", "stored")], _MODE07_RAISED)
    )

    assert [(c["code"], c["status"]) for c in _dtc(tmp_path)["codes"]] == [
        ("P0400", "stored"),
    ]


def test_answeredEmptyMode07_clearsTheSet_andAdvancesTheTime(tmp_path, carrying):
    """VC 4 (today's behaviour, pinned): Mode 07 answered empty."""
    carrying._emitDtcState(_keyOn([], _MODE07_ANSWERED))

    dtc = _dtc(tmp_path)
    assert dtc["codes"] == []
    assert dtc["pendingCheckedAtTs"] == _T1
    assert carrying._dtcCarriedPending == []
    assert _activeCodeKeys(carrying) == []


def test_postClear_failedMode07_carriesNothingPastMode04(tmp_path, carrying):
    """Mode 04 wiped the pending codes: a re-read whose Mode 07 failed carries none."""
    from pi.obdii.orchestrator.core import ApplicationOrchestrator
    from pi.splash.dtc_clear_channel import writeRequest

    carrying._connection = SimpleNamespace(isConnected=lambda: True)
    carrying._config = {"pi": {"splash": {"statesDir": str(tmp_path)}}}
    carrying._dtcClearClientFactory = lambda: SimpleNamespace(
        clearDtcs=lambda connection: SimpleNamespace(
            stored=[], pending=[], frameNull=False, mode07Probe=_MODE07_NULL,
        )
    )
    for name in ("_maybeServiceDtcClearRequest", "_publishDtcClearOutcome"):
        setattr(
            carrying, name, types.MethodType(getattr(ApplicationOrchestrator, name), carrying)
        )
    writeRequest(str(tmp_path), "req-1", nowFn=lambda: 1.0)

    carrying._maybeServiceDtcClearRequest()

    assert _dtc(tmp_path)["codes"] == []
    assert carrying._dtcCarriedPending == []
