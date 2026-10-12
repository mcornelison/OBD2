################################################################################
# File Name: test_states_http_service_control.py
# Purpose/Description: US-403 [Atlas A-7] tests for the service-control POST
#   endpoint on the F-103 localhost state server. The chromium kiosk's ONLY IPC
#   channel is this localhost HTTP server; US-403 extends it (read-only GET +
#   one token-gated POST /service-control) so the unprivileged kiosk can request
#   `systemctl restart/stop` on the install-fixed allow-list. The actual
#   privilege comes from the 51- polkit rule; this endpoint is a thin transport
#   that delegates the allow-list gate to pi.splash.service_control (the SSOT).
#
#   Tests assert: token-gating (401), off-list rejection (403, never executed),
#   the powerwatch-stop defense-in-depth (403), a happy-path delegate (200), and
#   that GET stays read-only. No real `systemctl` is ever invoked (the action is
#   monkeypatched / off-list paths short-circuit before exec).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-403 service control).
# ================================================================================
################################################################################

"""Tests for the US-403 POST /service-control endpoint on the state server."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from pi.splash import service_control
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


@pytest.fixture
def server(tmp_path):
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
    )
    thread = _start(srv)
    yield srv
    srv.shutdown()
    thread.join(timeout=5)


def test_serviceControl_requiresToken_401(server):
    """The action endpoint is token-gated (no token -> 401, never executed)."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/service-control", {"unit": "eclipse-obd.service", "verb": "restart"})
    assert exc.value.code == 401


def test_serviceControl_offListUnit_rejected_403(server):
    """S-6/F-13: an off-list unit is rejected (403) at the endpoint, not run."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            server,
            "/service-control",
            {"unit": "ssh.service", "verb": "stop"},
            token=_TOKEN,
        )
    assert exc.value.code == 403


def test_serviceControl_powerwatchStop_rejected_403(server):
    """A-7/D-7: a powerwatch STOP is rejected (403) -- the endpoint enforces the
    same allow-list as the polkit rule (defense-in-depth)."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(
            server,
            "/service-control",
            {"unit": "eclipse-powerwatch.service", "verb": "stop"},
            token=_TOKEN,
        )
    assert exc.value.code == 403


def test_serviceControl_allowedAction_delegatesAndReturns200(server, monkeypatch):
    """An allow-listed action delegates to service_control.runServiceAction and
    returns its honest result (no real systemctl invoked in the test)."""
    seen = {}

    def fakeRun(unit, verb, **kwargs):
        seen["call"] = (unit, verb)
        return service_control.ServiceControlResult(
            ok=True, unit=unit, verb=verb, returnCode=0, reason=""
        )

    monkeypatch.setattr(service_control, "runServiceAction", fakeRun)
    resp = _post(
        server,
        "/service-control",
        {"unit": "eclipse-obd.service", "verb": "restart"},
        token=_TOKEN,
    )
    assert resp.status == 200
    body = json.loads(resp.read().decode("utf-8"))
    assert body["ok"] is True
    assert body["unit"] == "eclipse-obd.service"
    assert body["verb"] == "restart"
    assert seen["call"] == ("eclipse-obd.service", "restart")


def test_serviceControl_unknownPostPath_404(server):
    """A POST to any path other than /service-control is 404 (no other writers)."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/boot-state", {"x": 1}, token=_TOKEN)
    assert exc.value.code == 404


def test_get_stillReadOnly_serviceControlPostOnly(server):
    """GET /service-control is not a thing -- the action is POST-only (GET 404)."""
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.actualPort}/service-control"
    )
    req.add_header("X-Splash-Token", _TOKEN)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == 404
