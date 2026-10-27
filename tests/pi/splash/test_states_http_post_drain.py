################################################################################
# File Name: test_states_http_post_drain.py
# Purpose/Description: The POST body drain on eclipse-states-http: an over-bound
#                      body is drained (bounded, chunked) before the answer, so
#                      the answer is never a connection reset; past the drain
#                      bound, 413 + close; a stalled client cannot hang the
#                      single-threaded server (socket timeout).
# Author: Atlas (architect)
# Creation Date: 2026-10-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-22    | Atlas (ARCH) | Initial (alerts-ack drain chore, rulings B1-B4).
# 2026-10-27    | Rex (US-870-d) | A5: POST /shutdown-splash-done -- 403 and no
#               |              | file without a valid token; with one, an atomic
#               |              | {bootId, ts}, bootId stamped server-side.
# ================================================================================
################################################################################

"""The POST body drain, the 413 bound and the socket timeout."""

from __future__ import annotations

import inspect
import io
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from common.config.validator import DEFAULTS
from pi.power.power_watch.splash_done import (
    SHUTDOWN_SPLASH_DONE_FILENAME,
    makeSplashDoneReader,
)
from pi.splash import states_http_server as shs
from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_STATE_NAME = "probe"


def _neverRun(*args: Any) -> dict[str, Any]:
    raise AssertionError("an over-bound body must never reach a runner")


@pytest.fixture
def server(tmp_path) -> Iterator[StatesHttpServer]:
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    (statesDir / _STATE_NAME).write_text('{"ok": true}', encoding="utf-8")
    srv = StatesHttpServer(
        statesDir=str(statesDir), token=_TOKEN, host="127.0.0.1", port=0,
        alertsAckRunner=_neverRun, fuelResetRunner=_neverRun,
    )
    thread = threading.Thread(target=srv.serveForever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        thread.join(timeout=5)


def _post(server: StatesHttpServer, path: str, raw: bytes, *, token: str | None = _TOKEN):
    """(status, body bytes) for a POST. A reset is NOT caught: it fails the test."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.actualPort}{path}", data=raw, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Splash-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _getState(server: StatesHttpServer) -> int:
    req = urllib.request.Request(f"http://127.0.0.1:{server.actualPort}/{_STATE_NAME}")
    req.add_header("X-Splash-Token", _TOKEN)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status


def _overBound(size: int) -> bytes:
    """Valid JSON of exactly ``size`` bytes."""
    shell = b'{"ids":[],"pad":""}'
    return shell[:-2] + b"x" * (size - len(shell)) + shell[-2:]


# ------------------------------------------------------------------ the drain


def test_overBoundBody_alertsAck_400_50of50(server):
    raw = _overBound(8192)
    for run in range(50):
        status, body = _post(server, "/alerts-ack", raw)
        assert (run, status) == (run, 400)
        assert json.loads(body) == {"ok": False, "error": "bad request"}


def test_answerFollowsTheDrain_notBeforeIt(server):
    # The deterministic form of the reset: the old code answered an over-bound
    # POST while the client was still sending. Send half the body, and no
    # answer may arrive; send the rest, and the 400 does.
    conn = socket.create_connection(("127.0.0.1", server.actualPort), timeout=10)
    try:
        conn.sendall(
            b"POST /alerts-ack HTTP/1.0\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Content-Length: 8192\r\nX-Splash-Token: " + _TOKEN.encode() + b"\r\n\r\n"
            + b"x" * 4096
        )
        conn.settimeout(0.5)
        with pytest.raises(TimeoutError):
            conn.recv(1024)

        conn.settimeout(10)
        conn.sendall(b"x" * 4096)
        answer = b""
        while chunk := conn.recv(4096):
            answer += chunk
        assert answer.startswith(b"HTTP/1.0 400 ")
    finally:
        conn.close()


def test_overBoundBody_serviceControl_400_tokenGateStillFirst(server):
    raw = _overBound(8192)
    assert _post(server, "/service-control", raw)[0] == 400
    assert _post(server, "/service-control", raw, token=None)[0] == 401


@pytest.mark.parametrize("path", ["/dtc-clear", "/fuel-reset"])
def test_overBoundBody_noBodyRoutes_answerAsForAnEmptyBody(server, path):
    # These routes read no body: after the drain they route exactly as today.
    emptyStatus = _post(server, path, b"", token=None)[0]
    assert _post(server, path, _overBound(8192), token=None)[0] == emptyStatus


def test_atBoundBody_stillParsesAndRoutes(server):
    shell = b'{"unit":"not-a-unit","verb":"start","pad":""}'
    raw = shell[:-2] + b"x" * (shs._MAX_ACTION_BODY - len(shell)) + shell[-2:]
    assert len(raw) == shs._MAX_ACTION_BODY
    json.loads(raw)

    status, _ = _post(server, "/service-control", raw)

    # Parsed (not 400), then refused by the allow-list.
    assert status == 403


def test_pastTheDrainBound_413OrClosed_thenTheServerStillAnswers(server):
    raw = _overBound(shs._MAX_DRAIN_BODY + 6 * 1024)
    started = time.monotonic()
    try:
        status, _ = _post(server, "/alerts-ack", raw)
        assert status == 413
    except (ConnectionError, urllib.error.URLError):
        pass  # 413 + close may reset a client still sending: allowed above the bound
    assert time.monotonic() - started < shs._SOCKET_TIMEOUT_SEC + 1.0
    assert _getState(server) == 200


def test_stalledBody_freesTheServer(server):
    stalled = socket.create_connection(("127.0.0.1", server.actualPort), timeout=10)
    try:
        stalled.sendall(
            b"POST /alerts-ack HTTP/1.0\r\nHost: x\r\nContent-Type: application/json\r\n"
            b"Content-Length: 8192\r\nX-Splash-Token: " + _TOKEN.encode() + b"\r\n\r\n"
            + b"x" * 1024
        )
        started = time.monotonic()

        # Queued behind the stalled request on the single-threaded server.
        assert _getState(server) == 200
        assert time.monotonic() - started < shs._SOCKET_TIMEOUT_SEC + 1.0

        # The server dropped the stalled client (EOF or reset, never an answer).
        try:
            assert stalled.recv(1024) == b""
        except ConnectionError:
            pass
    finally:
        stalled.close()


# ------------------------------------------------------------- the one reader


class _CountingStream(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.sizes: list[int] = []

    def read(self, size: int | None = -1) -> bytes:
        self.sizes.append(-1 if size is None else size)
        return super().read(size)


def test_readBoundedBody_drainsInChunks_neverHoldsMoreThanOne():
    stream = _CountingStream(b"x" * 10_000)

    assert shs._readBoundedBody(stream, 10_000) == (b"", False)
    assert stream.tell() == 10_000
    assert max(stream.sizes) <= shs._DRAIN_CHUNK


def test_readBoundedBody_pastTheBound_readsNothing():
    stream = _CountingStream(b"x" * 10)

    assert shs._readBoundedBody(stream, shs._MAX_DRAIN_BODY + 1) == (b"", True)
    assert stream.sizes == []


@pytest.mark.parametrize("length", [0, -5])
def test_readBoundedBody_noBody(length):
    assert shs._readBoundedBody(_CountingStream(b"abc"), length) == (b"", False)


def test_readBoundedBody_shortStream_drainStopsAtEof():
    stream = _CountingStream(b"x" * 5000)
    assert shs._readBoundedBody(stream, 8000) == (b"", False)


def test_rfile_isReadOnlyThroughTheHelper_calledOnceFromDoPost():
    module = inspect.getsource(shs)
    helper = inspect.getsource(shs._readBoundedBody)
    rest = module.replace(helper, "")

    assert "rfile.read" not in rest
    assert rest.count("self.rfile") == 1
    assert rest.count("_readBoundedBody(self.rfile") == 1


def test_socketTimeout_isOnTheHandler_andUnderTheStaleThreshold(server):
    handler = server._httpd.RequestHandlerClass
    assert handler.timeout == shs._SOCKET_TIMEOUT_SEC
    assert 0 < shs._SOCKET_TIMEOUT_SEC < DEFAULTS["pi.display.stale.obdLiveSec"]


# ------------------------------------------- US-870-d /shutdown-splash-done

_BOOT = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def doneServer(tmp_path, monkeypatch) -> Iterator[tuple[StatesHttpServer, Any]]:
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    # The server reads the kernel's boot id per request; this desk has none.
    monkeypatch.setattr(shs, "readCurrentBootId", lambda: _BOOT)
    srv = StatesHttpServer(
        statesDir=str(statesDir), token=_TOKEN, host="127.0.0.1", port=0,
    )
    thread = threading.Thread(target=srv.serveForever, daemon=True)
    thread.start()
    try:
        yield srv, statesDir / SHUTDOWN_SPLASH_DONE_FILENAME
    finally:
        srv.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_splashDone_withoutAValidToken_403_noFile(doneServer, token):
    server, doneFile = doneServer

    status, _ = _post(server, "/shutdown-splash-done", b"", token=token)

    assert status == 403
    assert not doneFile.exists()


def test_splashDone_withToken_writesThisBootsRecord(doneServer):
    server, doneFile = doneServer

    status, body = _post(server, "/shutdown-splash-done", b"")

    assert status == 200
    assert json.loads(body) == {"ok": True}
    record = json.loads(doneFile.read_text(encoding="utf-8"))
    assert record["bootId"] == _BOOT
    assert isinstance(record["ts"], str) and record["ts"].endswith("Z")


def test_splashDone_aClientSentBootId_isIgnored(doneServer):
    server, doneFile = doneServer

    status, _ = _post(
        server, "/shutdown-splash-done", json.dumps({"bootId": "f" * 32}).encode()
    )

    assert status == 200
    assert json.loads(doneFile.read_text(encoding="utf-8"))["bootId"] == _BOOT


def test_splashDone_isWhatTheSequencersReaderAccepts(doneServer):
    server, doneFile = doneServer
    read = makeSplashDoneReader(str(doneFile.parent), currentBootIdFn=lambda: _BOOT)
    assert read() is None

    _post(server, "/shutdown-splash-done", b"")

    assert read() == json.loads(doneFile.read_text(encoding="utf-8"))["ts"]


def test_splashDone_isAtomic_noTempFileLeft(doneServer):
    server, doneFile = doneServer

    _post(server, "/shutdown-splash-done", b"")

    assert sorted(p.name for p in doneFile.parent.iterdir()) == [doneFile.name]


def test_splashDone_getIsNotAWrite(doneServer):
    server, doneFile = doneServer
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.actualPort}/shutdown-splash-done"
    )
    req.add_header("X-Splash-Token", _TOKEN)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)

    assert exc.value.code == 404
    assert not doneFile.exists()
