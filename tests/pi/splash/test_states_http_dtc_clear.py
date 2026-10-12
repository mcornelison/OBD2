################################################################################
# File Name: test_states_http_dtc_clear.py
# Purpose/Description: US-407 (F-111) tests for the POST /dtc-clear action route
#   on the F-103 localhost state server -- the privileged action path for the
#   Mode-04 clear (same transport pattern as US-403's /service-control; the kiosk
#   stays unprivileged, HTTP-only). The endpoint RE-CHECKS the authoritative clear
#   gate against the server's OWN copy of the `dtc` state (never the request body)
#   before it ever delegates to the injected clear runner -- a tampered/stale UI
#   that asks to clear while a STOP code is stored is REJECTED (403) and the
#   vehicle-write runner is never called (S-10 / F-3). The read routes stay
#   read-only (POST /dtc -> 404).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-407 POST /dtc-clear action route.
# ================================================================================
################################################################################

"""Tests for the US-407 POST /dtc-clear endpoint on the state server."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"


def _start(server: StatesHttpServer) -> threading.Thread:
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    return thread


def _post(server, path, payload, token=None):
    url = f"http://127.0.0.1:{server.actualPort}{path}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(req, timeout=5)


def _codeObj(code, severity, *, logged=True, syncAcked=True):
    return {
        "code": code,
        "severity": severity,
        "status": "stored",
        "logged": logged,
        "syncAcked": syncAcked,
    }


def _writeDtc(statesDir, codes, *, sessionResetLock=None):
    payload = {
        "mil": True,
        "codes": codes,
        "newSinceTs": None,
        # Deliberately claims clearable; the endpoint must re-derive, not trust it.
        "clearGate": {"enabled": True, "reason": "ok"},
        "sessionResetLock": list(sessionResetLock or []),
        "ts": "2026-06-30T19:42:00Z",
    }
    (statesDir / "dtc").write_text(json.dumps(payload), encoding="utf-8")


def _makeServer(tmp_path, *, clearRunner):
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    assetsDir = tmp_path / "assets"
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text("hi __SPLASH_TOKEN__", encoding="utf-8")
    srv = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=str(assetsDir),
        clearRunner=clearRunner,
    )
    return srv, statesDir


@pytest.fixture
def okRunner():
    """A clear runner that reports a clean wipe (0 stored / 0 pending / MIL off)."""
    calls = []

    def runner():
        calls.append(True)
        return {"stored": [], "pending": [], "mil": False}

    runner.calls = calls
    return runner


def test_dtcClear_requiresToken_401(tmp_path, okRunner):
    srv, statesDir = _makeServer(tmp_path, clearRunner=okRunner)
    _writeDtc(statesDir, [_codeObj("P0443", "minor")])
    thread = _start(srv)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/dtc-clear", {"confirm": True})
        assert exc.value.code == 401
        assert okRunner.calls == [], "no token -> the runner never runs"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_dtcClear_gateFailsServerSide_rejected403_runnerNeverCalled(tmp_path, okRunner):
    """S-10 / F-3 (load-bearing): the server re-derives the gate from ITS OWN dtc
    state. A STOP code is stored, so even though the UI requests a clear (and the
    state's clearGate.enabled says True), the action path REJECTS it (403) and the
    Mode-04 runner is never invoked."""
    srv, statesDir = _makeServer(tmp_path, clearRunner=okRunner)
    _writeDtc(statesDir, [_codeObj("P0443", "minor"), _codeObj("P0301", "stop")])
    thread = _start(srv)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/dtc-clear", {"confirm": True}, token=_TOKEN)
        assert exc.value.code == 403
        assert okRunner.calls == [], "gate failed -> the vehicle-write runner never runs"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_dtcClear_sessionLocked_rejected403(tmp_path, okRunner):
    """S-8: a re-set code (in sessionResetLock) locks the clear at the action path."""
    srv, statesDir = _makeServer(tmp_path, clearRunner=okRunner)
    _writeDtc(statesDir, [_codeObj("P0443", "minor")], sessionResetLock=["P0443"])
    thread = _start(srv)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/dtc-clear", {"confirm": True}, token=_TOKEN)
        assert exc.value.code == 403
        assert okRunner.calls == []
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_dtcClear_gateOk_delegatesAndReturnsProof_200(tmp_path, okRunner):
    """Gate ok -> the runner issues the clear + re-read; the endpoint returns the
    honest proof (issued, cleared, storedAfter, MIL)."""
    srv, statesDir = _makeServer(tmp_path, clearRunner=okRunner)
    _writeDtc(statesDir, [_codeObj("P0443", "minor")])
    thread = _start(srv)
    try:
        resp = _post(srv, "/dtc-clear", {"confirm": True}, token=_TOKEN)
        assert resp.status == 200
        body = json.loads(resp.read().decode("utf-8"))
        assert body["issued"] is True
        assert body["cleared"] is True
        assert body["storedAfter"] == []
        assert body["milAfter"] is False
        assert okRunner.calls == [True], "the runner ran exactly once"
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_dtcClear_noRunnerConfigured_503_honest(tmp_path):
    """When no clear runner is wired (the standalone server has no OBD connection),
    the endpoint returns an honest 503 -- never a fabricated success."""
    srv, statesDir = _makeServer(tmp_path, clearRunner=None)
    _writeDtc(statesDir, [_codeObj("P0443", "minor")])
    thread = _start(srv)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/dtc-clear", {"confirm": True}, token=_TOKEN)
        assert exc.value.code == 503
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_dtcClear_missingDtcState_409(tmp_path, okRunner):
    """No `dtc` state file -> nothing to clear -> honest 409, runner not called."""
    srv, statesDir = _makeServer(tmp_path, clearRunner=okRunner)
    thread = _start(srv)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/dtc-clear", {"confirm": True}, token=_TOKEN)
        assert exc.value.code == 409
        assert okRunner.calls == []
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def test_dtcState_readStaysReadOnly_postDtc404(tmp_path, okRunner):
    """The read routes stay read-only: POST /dtc is 404 (only /service-control and
    /dtc-clear are write routes)."""
    srv, statesDir = _makeServer(tmp_path, clearRunner=okRunner)
    _writeDtc(statesDir, [_codeObj("P0443", "minor")])
    thread = _start(srv)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(srv, "/dtc", {"x": 1}, token=_TOKEN)
        assert exc.value.code == 404
    finally:
        srv.shutdown()
        thread.join(timeout=5)
