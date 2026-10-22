################################################################################
# File Name: test_alerts_ack_request_service.py
# Purpose/Description: US-897-c -- the eclipse-obd half of POST /alerts-ack: the
#                      run-loop hook that consumes the request first, checks
#                      every id all-or-nothing, records them in ONE store write,
#                      republishes states/alerts at once through emitNow (a pure
#                      rebuild, Atlas G2) and only then publishes the outcome.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-c) | Initial.
# ================================================================================
################################################################################

"""US-897-c: eclipse-obd services the alerts ack request."""

from __future__ import annotations

import ast
import inspect
import json
import textwrap
import threading
import time
import types
import urllib.request
from pathlib import Path
from typing import Any

import pytest

import pi.obdii.alerts_ack_store as store_mod
from pi.obdii.database import ObdDatabase
from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.splash import alerts_ack_channel as aac
from pi.splash.states_http_server import StatesHttpServer
from tests.pi.obdii.test_alerts_arbiter import _alertRows, _fresh, _obdLive
from tests.pi.orchestrator.test_card_state_emitters import _B2_T0, _FakeOrch

_STOP_ID = "engine:COOLANT_TEMP:stop"
_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_T_RED = "2026-10-20T15:12:27Z"


@pytest.fixture
def database(tmp_path) -> ObdDatabase:
    db = ObdDatabase(str(tmp_path / "obd.db"), walMode=False)
    db.initialize()
    return db


def _orch(tmp_path: Path, *, bootId: str = "b7", database: Any = None) -> _FakeOrch:
    (tmp_path / "var").mkdir(exist_ok=True)
    config = {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitIntervalSeconds": 0.0},
            "warnings": {"ackStorePath": str(tmp_path / "var" / "alerts-ack.json")},
        }
    }
    orch = _FakeOrch(config)
    orch._database = database
    orch._obdLiveClock = lambda: _B2_T0
    orch._initializeCardStateEmitters()
    orch._alertsBootId = bootId
    orch._maybeServiceAlertsAckRequest = types.MethodType(
        ApplicationOrchestrator._maybeServiceAlertsAckRequest, orch
    )
    orch.statesDir = str(tmp_path / "states")
    return orch


def _liveStop(orch: _FakeOrch) -> None:
    orch._emitAlertsState(_obdLive(_fresh(112.0, _T_RED)))


def _alerts(orch: _FakeOrch) -> dict[str, Any]:
    return json.loads((Path(orch.statesDir) / "alerts").read_text(encoding="utf-8"))


def _stopEntry(orch: _FakeOrch) -> dict[str, Any]:
    return next(e for e in _alerts(orch)["entries"] if e["id"] == _STOP_ID)


def _storeFile(tmp_path: Path) -> Path:
    return tmp_path / "var" / "alerts-ack.json"


def _service(orch: _FakeOrch, ids: Any, requestId: str = "r1") -> dict[str, Any]:
    aac.writeRequest(orch.statesDir, requestId, ids)
    assert orch._maybeServiceAlertsAckRequest() is True
    return aac.readOutcome(orch.statesDir)


def test_noRequest_isANoOp(tmp_path):
    orch = _orch(tmp_path)

    assert orch._maybeServiceAlertsAckRequest() is False
    assert aac.readOutcome(orch.statesDir) is None


def test_liveStop_acked_200Shape_storeRecord_statesAlertsAtOnce(tmp_path):
    """VC1: acknowledged true, pulse false, takeover still set -- with no tick."""
    orch = _orch(tmp_path)
    _liveStop(orch)
    assert _alerts(orch)["icon"]["pulse"] is True

    outcome = _service(orch, [_STOP_ID])

    assert (outcome["requestId"], outcome["ok"], outcome["error"]) == ("r1", True, None)
    assert aac.readRequest(orch.statesDir) is None  # consumed
    alerts = _alerts(orch)
    assert _stopEntry(orch)["acknowledged"] is True
    assert alerts["icon"]["pulse"] is False
    assert alerts["takeover"]["id"] == _STOP_ID
    record = json.loads(_storeFile(tmp_path).read_text(encoding="utf-8"))[_STOP_ID]
    assert record == {"bootId": "b7", "firstSeenTs": _T_RED, "ackedAt": "2026-10-20T15:12:25Z"}


def test_unknownId_409Shape_namesOnlyTheBadOnes_nothingRecorded(tmp_path, monkeypatch):
    """VC2: all or nothing."""
    orch = _orch(tmp_path)
    orch._alertsArbiter.observeDtc({
        "checkedAtTs": "2026-10-20T15:12:20Z",
        "source": {"dtc": {"available": True}},
        "codes": [{"code": "P0400", "status": "stored", "severity": "watch",
                   "title": "EGR FLOW (P0400)", "sentence": "s", "firstSeenTs": "f1"}],
    })
    _liveStop(orch)
    emits: list[int] = []
    monkeypatch.setattr(orch, "emitNow", lambda: emits.append(1))

    outcome = _service(orch, ["code:P0400:watch", "nope"])

    assert (outcome["ok"], outcome["error"], outcome["ids"]) == (False, "unknown_id", ["nope"])
    assert not _storeFile(tmp_path).exists()
    assert emits == []
    assert aac.readRequest(orch.statesDir) is None


def test_bootIdUnknown_notAckable_nothingRecorded(tmp_path):
    orch = _orch(tmp_path, bootId="unknown")
    _liveStop(orch)

    outcome = _service(orch, [_STOP_ID])

    assert (outcome["ok"], outcome["error"], outcome["ids"]) == (False, "not_ackable", [_STOP_ID])
    assert not _storeFile(tmp_path).exists()
    assert _stopEntry(orch)["acknowledged"] is False


@pytest.mark.parametrize("missing", ["_alertsArbiter", "_alertsEmitter"])
def test_noArbiterOrNoEmitter_notAckable(tmp_path, missing):
    orch = _orch(tmp_path)
    _liveStop(orch)
    setattr(orch, missing, None)

    outcome = _service(orch, [_STOP_ID])

    assert (outcome["ok"], outcome["error"]) == (False, "not_ackable")
    assert not _storeFile(tmp_path).exists()


def test_cardEmittersDisabled_notAckable(tmp_path):
    orch = _FakeOrch({
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitEnabled": False},
        }
    })
    orch._initializeCardStateEmitters()
    orch._maybeServiceAlertsAckRequest = types.MethodType(
        ApplicationOrchestrator._maybeServiceAlertsAckRequest, orch
    )
    (tmp_path / "states").mkdir()
    orch.statesDir = str(tmp_path / "states")

    outcome = _service(orch, [_STOP_ID])

    assert (outcome["ok"], outcome["error"]) == (False, "not_ackable")


def test_storeWriteFails_storeWriteFailed_nothingAcknowledged(tmp_path):
    orch = _orch(tmp_path)
    _liveStop(orch)
    _storeFile(tmp_path).parent.rmdir()  # /var/lib/eclipse-obd missing: never mkdir

    outcome = _service(orch, [_STOP_ID])

    assert (outcome["ok"], outcome["error"]) == (False, "store_write_failed")
    assert not _storeFile(tmp_path).parent.exists()
    assert _stopEntry(orch)["acknowledged"] is False


def test_twoIds_oneStoreWrite(tmp_path, monkeypatch):
    orch = _orch(tmp_path)
    orch._alertsArbiter.observeDtc({
        "checkedAtTs": "2026-10-20T15:12:20Z",
        "source": {"dtc": {"available": True}},
        "codes": [{"code": "P0400", "status": "stored", "severity": "watch",
                   "title": "EGR FLOW (P0400)", "sentence": "s", "firstSeenTs": "f1"}],
    })
    _liveStop(orch)
    writes: list[dict] = []
    real = store_mod.writeAtomicJson

    def spy(path: str, payload: dict, *, what: str = "record") -> bool:
        writes.append(dict(payload))
        return real(path, payload, what=what)

    monkeypatch.setattr(store_mod, "writeAtomicJson", spy)

    assert _service(orch, [_STOP_ID, "code:P0400:watch"])["ok"] is True

    assert [set(w) for w in writes] == [{_STOP_ID, "code:P0400:watch"}]


def test_reAck_isOkTrue_idempotent(tmp_path):
    orch = _orch(tmp_path)
    _liveStop(orch)
    assert _service(orch, [_STOP_ID], "r1")["ok"] is True
    before = _storeFile(tmp_path).read_bytes()

    outcome = _service(orch, [_STOP_ID], "r2")

    assert (outcome["requestId"], outcome["ok"], outcome["error"]) == ("r2", True, None)
    assert _storeFile(tmp_path).read_bytes() == before


def test_consumeFirst_aFailureIsPublished_andNeverPropagates(tmp_path, monkeypatch):
    orch = _orch(tmp_path)
    _liveStop(orch)

    def boom(*a: Any, **kw: Any) -> bool:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(orch._alertsAckStore, "acknowledge", boom)

    outcome = _service(orch, [_STOP_ID])

    assert outcome["ok"] is False
    assert "disk on fire" in outcome["error"]
    assert aac.readRequest(orch.statesDir) is None


def test_emitNow_isCalledAfterTheWrite_andBeforeTheOutcome(tmp_path, monkeypatch):
    orch = _orch(tmp_path)
    _liveStop(orch)
    seen: list[tuple[bool, Any]] = []
    realEmitNow = orch.emitNow

    def emitNow() -> Any:
        seen.append((_storeFile(tmp_path).exists(), aac.readOutcome(orch.statesDir)))
        return realEmitNow()

    monkeypatch.setattr(orch, "emitNow", emitNow)

    _service(orch, [_STOP_ID])

    assert seen == [(True, None)]


# ------------------------------------------------- emitNow (Atlas G2)


def test_emitNow_twice_episodesByteIdentical_noAlertLogRow(tmp_path, database, monkeypatch):
    """VC7: a PURE rebuild -- no observe, no hold-timer step, no INSERT."""
    orch = _orch(tmp_path, database=database)
    _liveStop(orch)
    rows = _alertRows(database)
    assert len(rows) == 1  # the open row
    episodes = repr(orch._alertsArbiter.episodes())
    observed: list[str] = []
    for name in ("observe", "observeDtc", "observeRpmReading"):
        monkeypatch.setattr(
            orch._alertsArbiter, name, lambda *a, _n=name, **kw: observed.append(_n)
        )

    first = orch.emitNow()
    second = orch.emitNow()

    assert observed == []
    assert repr(orch._alertsArbiter.episodes()) == episodes
    assert _alertRows(database) == rows
    assert first == second
    assert first["ts"] == "2026-10-20T15:12:25Z"  # the cached tick's inputs


def test_emitNow_withNoArbiter_publishesNothing(tmp_path):
    orch = _orch(tmp_path)
    orch._alertsArbiter = None

    assert orch.emitNow() is None


# ------------------------------------------------- end to end + hook order


def test_postAlertsAck_endToEnd_200_andTheEntryIsAcknowledged(tmp_path):
    """The route, the real bridge and the real hook in a service thread."""
    orch = _orch(tmp_path)
    _liveStop(orch)
    stop = threading.Event()

    def obdLoop() -> None:
        while not stop.is_set():
            orch._maybeServiceAlertsAckRequest()
            time.sleep(0.01)

    service = threading.Thread(target=obdLoop, daemon=True)
    service.start()
    srv = StatesHttpServer(
        statesDir=orch.statesDir, token=_TOKEN, port=0,
        alertsAckRunner=aac.makeBridgeAckRunner(orch.statesDir, timeoutSeconds=5.0),
    )
    http = threading.Thread(target=srv.serveForever, daemon=True)
    http.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.actualPort}/alerts-ack",
            data=json.dumps({"ids": [_STOP_ID]}).encode("utf-8"), method="POST",
        )
        req.add_header("X-Splash-Token", _TOKEN)
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, body = resp.status, json.loads(resp.read())
    finally:
        srv.shutdown()
        http.join(timeout=5)
        stop.set()
        service.join(timeout=5)

    assert (status, body) == (200, {"ok": True})
    assert _stopEntry(orch)["acknowledged"] is True


def _selfCalls(func: Any) -> list[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    return [
        attr
        for _, attr in sorted(
            (node.lineno, node.func.attr)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        )
    ]


def test_runLoop_callsTheHook_afterFuelReset_beforeTheCardEmit():
    called = _selfCalls(ApplicationOrchestrator.runLoop)

    assert called.index("_maybeServiceAlertsAckRequest") == (
        called.index("_maybeServiceFuelResetRequest") + 1
    )
    assert called.index("_maybeServiceAlertsAckRequest") < called.index("_maybeEmitCardStates")


def test_theService_consumesBeforeItDecides():
    called = _selfCalls(ApplicationOrchestrator._maybeServiceAlertsAckRequest)
    source = inspect.getsource(ApplicationOrchestrator._maybeServiceAlertsAckRequest)

    assert source.index("consumeRequest(") < source.index("checkAckRequest(")
    assert "emitNow" in called
