################################################################################
# File Name: test_states_http_alerts_ack.py
# Purpose/Description: US-897-c -- POST /alerts-ack on eclipse-states-http: the
#                      5th explicit write route, token-gated, body {ids: [...]},
#                      carried to eclipse-obd over alerts_ack_channel; every
#                      status, 400 before any file, all-or-nothing 409.
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

"""US-897-c: the POST /alerts-ack route."""

from __future__ import annotations

import inspect
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from common.config.validator import DEFAULTS
from pi.splash import alerts_ack_channel as aac
from pi.splash import states_http_server as shs
from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_STOP_ID = "engine:COOLANT_TEMP:stop"


def _status(
    server: StatesHttpServer,
    path: str,
    body: Any = None,
    *,
    token: str | None = _TOKEN,
    raw: bytes | None = None,
):
    """(status, json body) for a POST, HTTP errors included."""
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.actualPort}{path}", data=data, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Splash-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


class _Responder:
    """Plays eclipse-obd: answers each request file with ``answer(ids)``."""

    def __init__(self, statesDir: str, answer: Callable[[list[str]], dict[str, Any]]):
        self.statesDir = statesDir
        self.answer = answer
        self.seen: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            request = aac.readRequest(self.statesDir)
            if request is not None:
                aac.consumeRequest(self.statesDir)
                self.seen.append(request)
                aac.writeOutcome(
                    self.statesDir, requestId=request["requestId"], **self.answer(request["ids"])
                )
            time.sleep(0.01)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


@pytest.fixture
def statesDir(tmp_path) -> str:
    d = tmp_path / "states"
    d.mkdir()
    return str(d)


def _serve(statesDir: str, runner: Any) -> Iterator[StatesHttpServer]:
    srv = StatesHttpServer(
        statesDir=statesDir, token=_TOKEN, host="127.0.0.1", port=0,
        alertsAckRunner=runner,
    )
    thread = threading.Thread(target=srv.serveForever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def bridged(statesDir) -> Iterator[StatesHttpServer]:
    """A server wired to the REAL bridge runner (short budget for the tests)."""
    yield from _serve(statesDir, aac.makeBridgeAckRunner(statesDir, timeoutSeconds=1.0))


def _answered(statesDir: str, bridged: StatesHttpServer, answer, body: Any):
    responder = _Responder(statesDir, answer)
    try:
        return (*_status(bridged, "/alerts-ack", body), responder.seen)
    finally:
        responder.stop()


# ------------------------------------------------------------------ statuses


def test_acked_200_okTrue_theIdsReachTheOrchestrator(statesDir, bridged):
    status, body, seen = _answered(
        statesDir, bridged, lambda ids: {"ok": True, "error": None, "ids": []},
        {"ids": [_STOP_ID, "code:P0400:watch"]},
    )

    assert (status, body) == (200, {"ok": True})
    assert [r["ids"] for r in seen] == [[_STOP_ID, "code:P0400:watch"]]
    assert isinstance(seen[0]["requestedAtEpoch"], float)


@pytest.mark.parametrize("error", ["unknown_id", "not_ackable"])
def test_refused_409_namesTheErrorAndTheBadIds(statesDir, bridged, error):
    status, body, _ = _answered(
        statesDir, bridged, lambda ids: {"ok": False, "error": error, "ids": ["nope"]},
        {"ids": ["code:P0400:watch", "nope"]},
    )

    assert (status, body) == (409, {"ok": False, "error": error, "ids": ["nope"]})


def test_storeWriteFailed_503(statesDir, bridged):
    status, body, _ = _answered(
        statesDir, bridged,
        lambda ids: {"ok": False, "error": "store_write_failed", "ids": list(ids)},
        {"ids": [_STOP_ID]},
    )

    assert (status, body) == (503, {"ok": False, "error": "store_write_failed"})


def test_badToken_401_checkedFirst_noRequestFileWritten(statesDir, bridged):
    for token in (None, "wrong-token"):
        for body in ({"ids": [_STOP_ID]}, {"ids": []}):
            status, _ = _status(bridged, "/alerts-ack", body, token=token)
            assert status == 401
            assert aac.readRequest(statesDir) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        b"[]",
        b'"ids"',
        b"{}",
        b'{"ids": "engine:COOLANT_TEMP:stop"}',
        b'{"ids": []}',
        b'{"ids": [1]}',
        b'{"ids": [""]}',
        b'{"ids": ["engine:COOLANT_TEMP:stop", null]}',
        b'{"id": "engine:COOLANT_TEMP:stop"}',
        b'{"ids": ["engine:COOLANT_TEMP:stop"], "all": true}',
        b"\xff\xfe",
    ],
)
def test_malformedBody_400_beforeAnyFileIsWritten(statesDir, bridged, raw):
    status, body = _status(bridged, "/alerts-ack", raw=raw)

    assert status == 400
    assert body == {"ok": False, "error": "bad request"}
    assert aac.readRequest(statesDir) is None


def test_bodyOverTheActionBound_400(statesDir, bridged):
    ids = [f"code:P{n:04d}:watch" for n in range(shs._MAX_ACTION_BODY // 10)]
    raw = json.dumps({"ids": ids}).encode("utf-8")
    assert len(raw) > shs._MAX_ACTION_BODY

    status, _ = _status(bridged, "/alerts-ack", raw=raw)

    assert status == 400
    assert aac.readRequest(statesDir) is None


def test_noRunner_503_noFileWritten(statesDir):
    for srv in _serve(statesDir, None):
        status, body = _status(srv, "/alerts-ack", {"ids": [_STOP_ID]})
        assert status == 503
        assert body["ok"] is False
        assert aac.readRequest(statesDir) is None


def test_requestCannotBePublished_503(tmp_path):
    runner = aac.makeBridgeAckRunner(str(tmp_path / "missing"), timeoutSeconds=1.0)
    for srv in _serve(str(tmp_path), runner):
        status, body = _status(srv, "/alerts-ack", {"ids": [_STOP_ID]})
        assert status == 503
        assert body["ok"] is False
    assert not (tmp_path / "missing").exists()  # never mkdir


def test_noOutcomeWithinTheBudget_504_requestWithdrawn(statesDir, bridged):
    status, body = _status(bridged, "/alerts-ack", {"ids": [_STOP_ID]})

    assert status == 504
    assert body["ok"] is None
    assert aac.readRequest(statesDir) is None


@pytest.mark.parametrize("path", ["/alerts-ackx", "/alerts-ack/", "/alerts", "/alerts-acks"])
def test_nearMissPaths_404_noCatchAll(statesDir, bridged, path):
    status, _ = _status(bridged, path, {"ids": [_STOP_ID]})

    assert status == 404
    assert aac.readRequest(statesDir) is None


def test_get_alertsAck_isNotAWrite(statesDir, bridged):
    req = urllib.request.Request(
        f"http://127.0.0.1:{bridged.actualPort}/alerts-ack", method="GET"
    )
    req.add_header("X-Splash-Token", _TOKEN)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)

    assert exc.value.code == 404
    assert aac.readRequest(statesDir) is None


# ------------------------------------------------------ the runner parameter


@pytest.mark.parametrize("target", [shs.makeStatesHandler, StatesHttpServer.__init__])
def test_alertsAckRunner_isTheLastParameter(target):
    assert list(inspect.signature(target).parameters)[-1] == "alertsAckRunner"


def test_handlerPositionalPassThrough_reachesTheRoute(statesDir, monkeypatch):
    """StatesHttpServer hands the runner to makeStatesHandler POSITIONALLY, last."""
    captured: list[tuple] = []
    real = shs.makeStatesHandler

    def spy(*args: Any, **kwargs: Any):
        captured.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(shs, "makeStatesHandler", spy)

    def runner(ids):
        return {"ok": True, "error": None, "ids": []}

    srv = StatesHttpServer(statesDir=statesDir, token=_TOKEN, port=0, alertsAckRunner=runner)
    srv._httpd.server_close()  # never served: shutdown() would wait on serve_forever

    args, kwargs = captured[0]
    assert kwargs == {}
    assert args[-1] is runner


# =========================================== pi.warnings.ackTimeoutSec resolve


def _config(tmp_path, warnings: dict[str, Any] | None) -> str:
    path = tmp_path / "config.json"
    cfg: dict[str, Any] = {"pi": {}}
    if warnings is not None:
        cfg["pi"]["warnings"] = warnings
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def test_ackTimeout_fromConfig(tmp_path):
    assert shs.loadAlertsAckTimeoutSec(_config(tmp_path, {"ackTimeoutSec": 3})) == 3.0


@pytest.mark.parametrize("bad", [None, 0, -1, "5", True, float("nan"), float("inf")])
def test_ackTimeout_absentOrInvalid_isTheValidatorDefault(tmp_path, bad):
    warnings = None if bad is None else {"ackTimeoutSec": bad}
    expected = DEFAULTS["pi.warnings.ackTimeoutSec"]

    assert shs.loadAlertsAckTimeoutSec(_config(tmp_path, warnings)) == expected
    assert shs.loadAlertsAckTimeoutSec(None) == expected
    assert shs.loadAlertsAckTimeoutSec(str(tmp_path / "absent.json")) == expected


def test_main_wiresTheBridgeRunner_withTheConfiguredBudget(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}
    budgets: list[float] = []
    realFactory = aac.makeBridgeAckRunner

    def factory(statesDir: str, *, timeoutSeconds: float, **kw: Any):
        budgets.append(timeoutSeconds)
        return realFactory(statesDir, timeoutSeconds=timeoutSeconds, **kw)

    class _FakeServer:
        def __init__(self, **kw: Any) -> None:
            captured.update(kw)

        def serveForever(self) -> None:
            pass

    monkeypatch.setattr(aac, "makeBridgeAckRunner", factory)
    monkeypatch.setattr(shs, "StatesHttpServer", _FakeServer)
    configPath = _config(tmp_path, {"ackTimeoutSec": 2.5})

    shs.main([
        "--states-dir", str(tmp_path / "states"),
        "--token-path", str(tmp_path / "states" / ".http-token"),
        "--config", configPath,
        "--deploy-version-path", str(tmp_path / ".deploy-version"),
    ])

    assert budgets == [2.5]
    assert callable(captured["alertsAckRunner"])
    assert callable(captured["fuelResetRunner"])  # the fourth route keeps its wiring
