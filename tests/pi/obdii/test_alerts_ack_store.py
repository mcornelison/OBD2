################################################################################
# File Name: test_alerts_ack_store.py
# Purpose/Description: US-897-c -- the boot-scoped alerts acknowledgement store
#                      (episode-keyed records, honest reads, prune of the never-
#                      matchable) and Iris c1-c6 end to end through the host's
#                      states/alerts emit and the ack service.
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

"""US-897-c: the alerts ack store."""

from __future__ import annotations

import json
import logging
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import pi.obdii.alerts_ack_store as store_mod
from common.config.validator import DEFAULTS
from pi.obdii.alerts_ack_store import AlertsAckStore, ackStorePathOf, checkAckRequest
from pi.obdii.orchestrator.core import ApplicationOrchestrator
from pi.splash import alerts_ack_channel as aac
from pi.splash.states_http_server import StatesHttpServer
from tests.pi.obdii.test_alerts_arbiter import _fresh, _obdLive
from tests.pi.orchestrator.test_card_state_emitters import _B2_T0, _FakeOrch

_STOP_ID = "engine:COOLANT_TEMP:stop"
_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_T_RED = "2026-10-20T15:12:27Z"
_T_RED_AGAIN = "2026-10-20T15:20:00Z"
_ACKED_AT = "2026-10-20T15:12:40Z"


def _ep(entryId: str, firstSeenTs: str | None = _T_RED) -> SimpleNamespace:
    return SimpleNamespace(id=entryId, firstSeenTs=firstSeenTs)


def _storePath(tmp_path: Path) -> Path:
    (tmp_path / "var").mkdir(exist_ok=True)
    return tmp_path / "var" / "alerts-ack.json"


def _onDisk(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def writes(monkeypatch) -> list[tuple[str, dict, str]]:
    """Every writeAtomicJson call the store makes (still really written)."""
    calls: list[tuple[str, dict, str]] = []
    real = store_mod.writeAtomicJson

    def spy(path: str, payload: dict, *, what: str = "record") -> bool:
        calls.append((path, json.loads(json.dumps(payload)), what))
        return real(path, payload, what=what)

    monkeypatch.setattr(store_mod, "writeAtomicJson", spy)
    return calls


# ===================================================================== store


def test_path_isTheValidatorDefault_underVarLib_unlessConfigured(tmp_path):
    assert DEFAULTS["pi.warnings.ackStorePath"] == "/var/lib/eclipse-obd/alerts-ack.json"
    assert ackStorePathOf({}) == DEFAULTS["pi.warnings.ackStorePath"]
    assert ackStorePathOf({"pi": {"warnings": {}}}) == DEFAULTS["pi.warnings.ackStorePath"]
    configured = {"pi": {"warnings": {"ackStorePath": str(tmp_path / "a.json")}}}
    assert ackStorePathOf(configured) == str(tmp_path / "a.json")


def test_acknowledge_recordsTheEpisode_inOneWrite(tmp_path, writes):
    path = _storePath(tmp_path)
    store = AlertsAckStore(str(path))

    ok = store.acknowledge(
        {_STOP_ID: _T_RED, "code:P0400:watch": None}, bootId="b7", ackedAt=_ACKED_AT
    )

    assert ok is True
    expected = {
        _STOP_ID: {"bootId": "b7", "firstSeenTs": _T_RED, "ackedAt": _ACKED_AT},
        "code:P0400:watch": {"bootId": "b7", "firstSeenTs": None, "ackedAt": _ACKED_AT},
    }
    assert _onDisk(path) == expected
    assert [(w[1], w[2]) for w in writes] == [(expected, "alerts-ack")]


def test_matching_needsThisBoot_andThisEpisode(tmp_path):
    store = AlertsAckStore(str(_storePath(tmp_path)))
    store.acknowledge({_STOP_ID: _T_RED}, bootId="b7", ackedAt=_ACKED_AT)

    assert store.matchingIds([_ep(_STOP_ID)], bootId="b7") == {_STOP_ID}
    # A new episode under the same id (G1): a new firstSeenTs.
    assert store.matchingIds([_ep(_STOP_ID, _T_RED_AGAIN)], bootId="b7") == frozenset()
    # A prior boot's ack never holds.
    assert store.matchingIds([_ep(_STOP_ID)], bootId="b8") == frozenset()


def test_reAck_ofTheSameEpisode_isIdempotent_noRewrite_ackedAtKept(tmp_path, writes):
    path = _storePath(tmp_path)
    store = AlertsAckStore(str(path))
    store.acknowledge({_STOP_ID: _T_RED}, bootId="b7", ackedAt=_ACKED_AT)

    assert store.acknowledge({_STOP_ID: _T_RED}, bootId="b7", ackedAt="2026-10-20T16:00:00Z")

    assert len(writes) == 1
    assert _onDisk(path)[_STOP_ID]["ackedAt"] == _ACKED_AT


def test_firstWriteOfANewBoot_dropsThePriorBootsRecords(tmp_path):
    path = _storePath(tmp_path)
    AlertsAckStore(str(path)).acknowledge({_STOP_ID: _T_RED}, bootId="b6", ackedAt=_ACKED_AT)

    store = AlertsAckStore(str(path))
    store.acknowledge({"code:P0400:watch": None}, bootId="b7", ackedAt=_ACKED_AT)

    assert set(_onDisk(path)) == {"code:P0400:watch"}


def test_unknownBootId_recordsNothing_countsNothing_readsNothing(tmp_path, writes, caplog):
    path = _storePath(tmp_path)
    path.write_text(
        json.dumps({_STOP_ID: {"bootId": "unknown", "firstSeenTs": _T_RED, "ackedAt": "x"}}),
        encoding="utf-8",
    )
    store = AlertsAckStore(str(path))
    caplog.set_level(logging.WARNING, logger="pi.obdii.alerts_ack_store")

    assert store.acknowledge({_STOP_ID: _T_RED}, bootId="unknown", ackedAt=_ACKED_AT) is False
    assert store.matchingIds([_ep(_STOP_ID)], bootId="unknown") == frozenset()
    store.prune([], bootId="unknown", codeAssessed=True, engineAssessed=True)

    assert writes == []
    assert store.records() == {}
    assert caplog.records == []


@pytest.mark.parametrize(
    "content", [None, "", "   \n", '{"engine:COOLANT_TEMP:stop": {"bootId": "b7"', "[1, 2]"]
)
def test_missingEmptyOrTornFile_readsAsNoAcks_withOneWarn(tmp_path, caplog, content):
    path = _storePath(tmp_path)
    if content is not None:
        path.write_text(content, encoding="utf-8")
    store = AlertsAckStore(str(path))
    caplog.set_level(logging.WARNING, logger="pi.obdii.alerts_ack_store")

    for _ in range(3):
        assert store.matchingIds([_ep(_STOP_ID)], bootId="b7") == frozenset()

    warns = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warns) == 1
    assert "re-alert" in warns[0].getMessage()


def test_writeFailure_returnsFalse_recordsUnchanged_neverMkdir(tmp_path, caplog):
    path = tmp_path / "no-such-dir" / "alerts-ack.json"
    store = AlertsAckStore(str(path))
    caplog.set_level(logging.WARNING)

    assert store.acknowledge({_STOP_ID: _T_RED}, bootId="b7", ackedAt=_ACKED_AT) is False

    assert store.records() == {}
    assert store.matchingIds([_ep(_STOP_ID)], bootId="b7") == frozenset()
    assert not path.parent.exists()
    assert any("alerts-ack" in r.getMessage() for r in caplog.records)


def test_prune_dropsOnlyTheNeverMatchable(tmp_path, writes):
    path = _storePath(tmp_path)
    path.write_text(
        json.dumps({
            "engine:COOLANT_TEMP:stop": {"bootId": "b7", "firstSeenTs": _T_RED, "ackedAt": "a"},
            "engine:BATTERY_V:watch": {"bootId": "b7", "firstSeenTs": _T_RED, "ackedAt": "a"},
            "code:P0400:watch": {"bootId": "b7", "firstSeenTs": None, "ackedAt": "a"},
            "code:P0443:watch": {"bootId": "b6", "firstSeenTs": None, "ackedAt": "a"},
        }),
        encoding="utf-8",
    )
    store = AlertsAckStore(str(path))

    # Listed: the STOP (an acked cleared STOP is still listed by the arbiter).
    store.prune(
        [_ep("engine:COOLANT_TEMP:stop")], bootId="b7", codeAssessed=True, engineAssessed=True
    )

    assert set(_onDisk(path)) == {"engine:COOLANT_TEMP:stop"}
    assert len(writes) == 1


def test_prune_codesUnreadable_prunesNoCodeRecord(tmp_path):
    path = _storePath(tmp_path)
    store = AlertsAckStore(str(path))
    store.acknowledge({"code:P0400:watch": None}, bootId="b7", ackedAt=_ACKED_AT)

    store.prune([], bootId="b7", codeAssessed=False, engineAssessed=True)

    assert set(_onDisk(path)) == {"code:P0400:watch"}


def test_prune_engineUnassessed_prunesNoEngineRecord(tmp_path):
    path = _storePath(tmp_path)
    store = AlertsAckStore(str(path))
    store.acknowledge({_STOP_ID: _T_RED}, bootId="b7", ackedAt=_ACKED_AT)

    store.prune([], bootId="b7", codeAssessed=True, engineAssessed=False)

    assert set(_onDisk(path)) == {_STOP_ID}


def test_prune_withNothingToDrop_writesNothing(tmp_path, writes):
    store = AlertsAckStore(str(_storePath(tmp_path)))
    store.acknowledge({_STOP_ID: _T_RED}, bootId="b7", ackedAt=_ACKED_AT)

    for _ in range(3):
        store.prune([_ep(_STOP_ID)], bootId="b7", codeAssessed=True, engineAssessed=True)

    assert len(writes) == 1


# ============================================================ checkAckRequest


def test_check_unknownIds_areNamed_allOrNothing():
    episodes = [_ep("code:P0400:watch")]

    assert checkAckRequest(
        ["code:P0400:watch", "nope"], episodes, bootId="b7", ackable=True
    ) == ("unknown_id", ["nope"])
    assert checkAckRequest(["code:P0400:watch"], episodes, bootId="b7", ackable=True) == (
        None,
        [],
    )


def test_check_listedButBootUnknown_isNotAckable():
    assert checkAckRequest(
        [_STOP_ID], [_ep(_STOP_ID)], bootId="unknown", ackable=True
    ) == ("not_ackable", [_STOP_ID])


def test_check_nothingToAckInto_isNotAckable():
    assert checkAckRequest([_STOP_ID], [], bootId="b7", ackable=False) == (
        "not_ackable",
        [_STOP_ID],
    )


# ================================================= Iris c1-c6, end to end


def _host(tmp_path: Path, *, bootId: str = "b7", database: Any = None) -> _FakeOrch:
    """A card-emitter host with the real arbiter, emitter, store and service."""
    config = {
        "pi": {
            "splash": {"statesDir": str(tmp_path / "states")},
            "dashboard": {"stateEmitIntervalSeconds": 0.0},
            "warnings": {"ackStorePath": str(_storePath(tmp_path))},
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
    return orch


def _tick(orch: _FakeOrch, coolant: dict[str, Any] | None) -> None:
    orch._emitAlertsState(_obdLive(coolant))


def _ack(orch: _FakeOrch, ids: list[str]) -> dict[str, Any]:
    statesDir = str(Path(orch._config["pi"]["splash"]["statesDir"]))
    aac.writeRequest(statesDir, "r1", ids)
    assert orch._maybeServiceAlertsAckRequest() is True
    return aac.readOutcome(statesDir)


def _alerts(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / "states" / "alerts").read_text(encoding="utf-8"))


def _entry(tmp_path: Path, entryId: str = _STOP_ID) -> dict[str, Any] | None:
    return next((e for e in _alerts(tmp_path)["entries"] if e["id"] == entryId), None)


def test_c1_anAckSurvivesAnOrchestratorRestart_andAKioskRestart(tmp_path):
    orch = _host(tmp_path)
    _tick(orch, _fresh(112.0, _T_RED))
    assert _ack(orch, [_STOP_ID])["ok"] is True

    restarted = _host(tmp_path)  # same boot, same store file, same tmpfs seed
    _tick(restarted, _fresh(113.0, "2026-10-20T15:12:31Z"))

    assert _entry(tmp_path)["acknowledged"] is True
    assert _alerts(tmp_path)["icon"]["pulse"] is False
    # A kiosk restart re-reads states/alerts through a NEW state server.
    srv = StatesHttpServer(statesDir=str(tmp_path / "states"), token=_TOKEN, port=0)
    thread = threading.Thread(target=srv.serveForever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{srv.actualPort}/alerts")
        req.add_header("X-Splash-Token", _TOKEN)
        with urllib.request.urlopen(req, timeout=10) as resp:
            served = json.loads(resp.read())
    finally:
        srv.shutdown()
        thread.join(timeout=5)
    assert next(e for e in served["entries"] if e["id"] == _STOP_ID)["acknowledged"] is True


def test_c2_aPriorBootsAck_neverHolds(tmp_path):
    orch = _host(tmp_path, bootId="b6")
    _tick(orch, _fresh(112.0, _T_RED))
    assert _ack(orch, [_STOP_ID])["ok"] is True
    (tmp_path / "states" / "alerts").unlink()  # tmpfs: a new boot starts empty

    nextBoot = _host(tmp_path, bootId="b7")
    _tick(nextBoot, _fresh(112.0, _T_RED))

    assert _entry(tmp_path)["acknowledged"] is False
    assert _alerts(tmp_path)["icon"]["pulse"] is True
    assert _onDisk(_storePath(tmp_path)) == {}  # the first write of b7 dropped b6's


def test_c3_anUnknownId_changesNothing(tmp_path):
    orch = _host(tmp_path)
    _tick(orch, _fresh(112.0, _T_RED))
    before = (tmp_path / "states" / "alerts").read_bytes()

    outcome = _ack(orch, [_STOP_ID, "nope"])

    assert (outcome["ok"], outcome["error"], outcome["ids"]) == (False, "unknown_id", ["nope"])
    assert not _storePath(tmp_path).exists()
    assert (tmp_path / "states" / "alerts").read_bytes() == before


def test_c4_noRunner_503(tmp_path):
    srv = StatesHttpServer(statesDir=str(tmp_path), token=_TOKEN, port=0)
    thread = threading.Thread(target=srv.serveForever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.actualPort}/alerts-ack",
            data=json.dumps({"ids": [_STOP_ID]}).encode("utf-8"), method="POST",
        )
        req.add_header("X-Splash-Token", _TOKEN)
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
    finally:
        srv.shutdown()
        thread.join(timeout=5)
    assert exc.value.code == 503


def test_c5_ackALiveStop_thenItClears_entryRemoved_recordKept_alsoAfterARestart(tmp_path):
    orch = _host(tmp_path)
    _tick(orch, _fresh(112.0, _T_RED))
    assert _ack(orch, [_STOP_ID])["ok"] is True

    _tick(orch, _fresh(95.0, "2026-10-20T15:14:00Z", band="green"))

    assert _entry(tmp_path) is None
    assert _alerts(tmp_path)["icon"] == {"state": "not_checked", "count": 0, "pulse": False}
    assert _STOP_ID in _onDisk(_storePath(tmp_path))

    _host(tmp_path)._emitAlertsState(_obdLive(None))  # orchestrator restart
    assert _entry(tmp_path) is None


def test_c5_ackingAClearedStop_removesIt(tmp_path):
    orch = _host(tmp_path)
    _tick(orch, _fresh(112.0, _T_RED))
    _tick(orch, _fresh(95.0, "2026-10-20T15:14:00Z", band="green"))
    assert _entry(tmp_path)["active"] is False

    assert _ack(orch, [_STOP_ID])["ok"] is True

    assert _entry(tmp_path) is None
    assert _ack(orch, [_STOP_ID])["ok"] is True  # still listed by the arbiter: idempotent


def test_c6_codesUnreadable_prunesNothing(tmp_path):
    orch = _host(tmp_path)
    orch._alertsArbiter.observeDtc({
        "checkedAtTs": "2026-10-20T15:12:20Z",
        "source": {"dtc": {"available": True}},
        "codes": [{"code": "P0400", "status": "stored", "severity": "watch",
                   "title": "EGR FLOW (P0400)", "sentence": "s", "firstSeenTs": "f1"}],
    })
    _tick(orch, None)
    assert _ack(orch, ["code:P0400:watch"])["ok"] is True
    assert _alerts(tmp_path)["codeAlert"] is None

    restarted = _host(tmp_path)  # codes are not seeded: unread until the next read
    _tick(restarted, None)

    assert "code:P0400:watch" in _onDisk(_storePath(tmp_path))
    restarted._alertsArbiter.observeDtc({
        "checkedAtTs": "2026-10-20T15:13:20Z",
        "source": {"dtc": {"available": True}},
        "codes": [{"code": "P0400", "status": "stored", "severity": "watch",
                   "title": "EGR FLOW (P0400)", "sentence": "s", "firstSeenTs": "f1"}],
    })
    _tick(restarted, None)
    assert _entry(tmp_path, "code:P0400:watch")["acknowledged"] is True
    assert _alerts(tmp_path)["codeAlert"] is None


def test_aNewCoolantEpisode_underTheSameId_isUnacknowledged(tmp_path):
    orch = _host(tmp_path)
    _tick(orch, _fresh(112.0, _T_RED))
    assert _ack(orch, [_STOP_ID])["ok"] is True
    _tick(orch, _fresh(95.0, "2026-10-20T15:14:00Z", band="green"))

    _tick(orch, _fresh(114.0, _T_RED_AGAIN))

    entry = _entry(tmp_path)
    assert (entry["active"], entry["firstSeenTs"], entry["acknowledged"]) == (
        True, _T_RED_AGAIN, False,
    )
    assert _alerts(tmp_path)["icon"]["pulse"] is True
