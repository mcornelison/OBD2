################################################################################
# File Name: test_states_http_dtc_endpoint.py
# Purpose/Description: US-404 (F-111) tests that eclipse-states-http serves the
#   `dtc` state file read-only. The dtc emitter writes /run/eclipse-obd/states/
#   dtc and the carousel polls GET /dtc; this locks: GET /dtc (with token) ->
#   200 JSON of the emitted state, GET without token -> 401, and POST /dtc ->
#   404 (the only write route is /service-control; the dtc endpoint is strictly
#   read-only). End-to-end: the real emitter writes, the real server serves.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 dtc endpoint read-only.
# ================================================================================
################################################################################

"""Tests that ``eclipse-states-http`` serves the `dtc` endpoint read-only."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from pi.splash.dtc_emitter import makeDtcEmitter
from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"

_TABLE = {
    "P1300": {
        "severity": "watch",
        "severityCaveat": "\U0001f534 if knock",
        "short": "Ignition Timing Adjustment circuit",
        "long": "Ignition Timing Adjustment circuit",
        "suggestedFix": "Verify base timing.",
        "fixProvenance": "spool-validated",
        "clearEligible": False,
    },
}


@pytest.fixture
def runningServer(tmp_path):
    """A real StatesHttpServer whose `dtc` file the real emitter produced."""
    statesDir = tmp_path / "states"
    statesDir.mkdir()

    # Use the production emitter to write the dtc state -> proves the seam.
    emit = makeDtcEmitter(
        str(statesDir),
        severityTable=_TABLE,
        nowIsoFn=lambda: "2026-06-30T19:42:00Z",
    )
    emit(
        codes=[
            {
                "code": "P1300",
                "status": "stored",
                "description": "",
                "driveId": None,
                "setAtTs": "2026-06-30T19:40:00Z",
                "logged": True,
                "syncAcked": False,
            }
        ],
        mil=True,
        newSinceTs=None,
        sessionResetLock=[],
    )

    assetsDir = tmp_path / "assets"
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text("<html></html>", encoding="utf-8")

    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=str(assetsDir),
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


def _get(server, path, token=None):
    url = f"http://127.0.0.1:{server.actualPort}{path}"
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(req, timeout=5)


def _post(server, path, token=None):
    url = f"http://127.0.0.1:{server.actualPort}{path}"
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(req, timeout=5)


def test_dtcEndpoint_withToken_returns200JsonState(runningServer):
    """GET /dtc with a valid token returns the emitted dtc state as JSON."""
    resp = _get(runningServer, "/dtc", token=_TOKEN)

    assert resp.status == 200
    payload = json.loads(resp.read())
    assert payload["codes"][0]["code"] == "P1300"
    assert payload["mil"] is True
    assert set(payload) >= {"mil", "codes", "clearGate", "ts"}


def test_dtcEndpoint_missingToken_returns401(runningServer):
    """The dtc state poll is token-gated like every other state file."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(runningServer, "/dtc", token=None)
    assert exc.value.code == 401


def test_dtcEndpoint_post_returns404_readOnly(runningServer):
    """POST /dtc is rejected (404): the only write route is /service-control."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(runningServer, "/dtc", token=_TOKEN)
    assert exc.value.code == 404
