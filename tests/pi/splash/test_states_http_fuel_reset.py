################################################################################
# File Name: test_states_http_fuel_reset.py
# Purpose/Description: US-881-d -- POST /fuel-reset on eclipse-states-http: the
#                      4th explicit write route, token-gated, carried to
#                      eclipse-obd over fuel_reset_channel, with /dtc-clear's
#                      status-code mapping.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Rex (US-881-d) | Initial.
# ================================================================================
################################################################################

"""US-881-d: the POST /fuel-reset route."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from common.config.validator import DEFAULTS
from pi.splash import fuel_reset_channel as frc
from pi.splash import states_http_server as shs
from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_RESET_AT = "2026-10-20T15:10:00Z"


def _post(server: StatesHttpServer, path: str, token: str | None = _TOKEN):
    url = f"http://127.0.0.1:{server.actualPort}{path}"
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(req, timeout=10)


def _status(server: StatesHttpServer, path: str, token: str | None = _TOKEN):
    """(status, json body) for a POST, HTTP errors included."""
    try:
        with _post(server, path, token) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


class _Responder:
    """Plays eclipse-obd: answers each request file with ``answer(requestId)``."""

    def __init__(self, statesDir: str, answer: Callable[[str], dict[str, Any]] | None):
        self.statesDir = statesDir
        self.answer = answer
        self.seen: list[str] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            request = frc.readRequest(self.statesDir)
            if request is not None and self.answer is not None:
                frc.consumeRequest(self.statesDir)
                self.seen.append(request["requestId"])
                frc.writeOutcome(
                    self.statesDir, requestId=request["requestId"],
                    **self.answer(request["requestId"]),
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
        fuelResetRunner=runner,
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
    yield from _serve(statesDir, frc.makeBridgeResetRunner(statesDir, timeoutSeconds=1.0))


def test_parked_200_okWithResetAtTs(statesDir, bridged):
    responder = _Responder(
        statesDir, lambda rid: {"ok": True, "reason": None, "resetAtTs": _RESET_AT}
    )
    try:
        status, body = _status(bridged, "/fuel-reset")
    finally:
        responder.stop()

    assert (status, body) == (200, {"ok": True, "resetAtTs": _RESET_AT})
    assert len(responder.seen) == 1


def test_driving_409_reasonDriving(statesDir, bridged):
    responder = _Responder(
        statesDir, lambda rid: {"ok": False, "reason": "driving", "resetAtTs": None}
    )
    try:
        status, body = _status(bridged, "/fuel-reset")
    finally:
        responder.stop()

    assert (status, body) == (409, {"ok": False, "reason": "driving"})


def test_badToken_401_noRequestFileWritten(statesDir, bridged):
    for token in (None, "wrong-token"):
        status, _ = _status(bridged, "/fuel-reset", token=token)
        assert status == 401
        assert frc.readRequest(statesDir) is None


def test_noOutcomeWithinTheBudget_504_requestWithdrawn(statesDir, bridged):
    status, body = _status(bridged, "/fuel-reset")

    assert status == 504
    assert body["ok"] is None
    assert frc.readRequest(statesDir) is None


def test_noStatesChannel_503(statesDir):
    for srv in _serve(statesDir, None):
        status, body = _status(srv, "/fuel-reset")
        assert status == 503
        assert body["ok"] is False


def test_requestCannotBePublished_503(tmp_path):
    runner = frc.makeBridgeResetRunner(str(tmp_path / "missing"), timeoutSeconds=1.0)
    for srv in _serve(str(tmp_path), runner):
        status, _ = _status(srv, "/fuel-reset")
        assert status == 503


@pytest.mark.parametrize("path", ["/fuel-resetx", "/fuel-reset/", "/fuel"])
def test_nearMissPaths_404_noCatchAll(statesDir, bridged, path):
    status, _ = _status(bridged, path)

    assert status == 404
    assert frc.readRequest(statesDir) is None


def test_get_fuelReset_isNotAWrite(statesDir, bridged):
    req = urllib.request.Request(
        f"http://127.0.0.1:{bridged.actualPort}/fuel-reset", method="GET"
    )
    req.add_header("X-Splash-Token", _TOKEN)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)

    assert exc.value.code == 404
    assert frc.readRequest(statesDir) is None


# ============================================== pi.fuel.resetTimeoutSec resolve


def _config(tmp_path, fuel: dict[str, Any] | None) -> str:
    path = tmp_path / "config.json"
    cfg: dict[str, Any] = {"pi": {}}
    if fuel is not None:
        cfg["pi"]["fuel"] = fuel
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def test_resetTimeout_fromConfig(tmp_path):
    assert shs.loadFuelResetTimeoutSec(_config(tmp_path, {"resetTimeoutSec": 3})) == 3


@pytest.mark.parametrize("bad", [None, 0, -1, "5", True, float("nan")])
def test_resetTimeout_absentOrInvalid_isTheValidatorDefault(tmp_path, bad):
    fuel = None if bad is None else {"resetTimeoutSec": bad}
    expected = DEFAULTS["pi.fuel.resetTimeoutSec"]

    assert shs.loadFuelResetTimeoutSec(_config(tmp_path, fuel)) == expected
    assert shs.loadFuelResetTimeoutSec(None) == expected
    assert shs.loadFuelResetTimeoutSec(str(tmp_path / "absent.json")) == expected


def test_main_wiresTheBridgeRunner_withTheConfiguredBudget(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}
    budgets: list[float] = []
    realFactory = frc.makeBridgeResetRunner

    def factory(statesDir: str, *, timeoutSeconds: float, **kw: Any):
        budgets.append(timeoutSeconds)
        return realFactory(statesDir, timeoutSeconds=timeoutSeconds, **kw)

    class _FakeServer:
        def __init__(self, **kw: Any) -> None:
            captured.update(kw)

        def serveForever(self) -> None:
            pass

    monkeypatch.setattr(frc, "makeBridgeResetRunner", factory)
    monkeypatch.setattr(shs, "StatesHttpServer", _FakeServer)
    configPath = _config(tmp_path, {"resetTimeoutSec": 2.5})

    shs.main([
        "--states-dir", str(tmp_path / "states"),
        "--token-path", str(tmp_path / "states" / ".http-token"),
        "--config", configPath,
        "--deploy-version-path", str(tmp_path / ".deploy-version"),
    ])

    assert budgets == [2.5]
    assert callable(captured["fuelResetRunner"])
