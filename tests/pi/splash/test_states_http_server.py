################################################################################
# File Name: test_states_http_server.py
# Purpose/Description: Tests for the F-103 localhost state HTTP server [Atlas
#   A-4]: 127.0.0.1 bind, token-gated state endpoints, read-only states/* with
#   path-traversal guard, no-store caching, and token-injected kiosk index.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# ================================================================================
################################################################################

"""Tests for ``pi.splash.states_http_server`` (real ephemeral-port server)."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"


@pytest.fixture
def runningServer(tmp_path):
    """Spin up a real StatesHttpServer on 127.0.0.1:<ephemeral> in a thread."""
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    (statesDir / "boot-state").write_text(
        json.dumps({"healthy": True, "degraded": False}), encoding="utf-8"
    )
    assetsDir = tmp_path / "assets"
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text(
        "<script>const TOKEN='__SPLASH_TOKEN__';</script>", encoding="utf-8"
    )
    (assetsDir / "splash.svg").write_text("<svg/>", encoding="utf-8")

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


def test_server_bindsLocalhostOnly(runningServer):
    assert runningServer.host == "127.0.0.1"


def test_bootState_withValidToken_returns200Json(runningServer):
    resp = _get(runningServer, "/boot-state", token=_TOKEN)
    body = json.loads(resp.read().decode("utf-8"))
    assert resp.status == 200
    assert body == {"healthy": True, "degraded": False}


def test_bootState_setsNoStoreCacheControl(runningServer):
    resp = _get(runningServer, "/boot-state", token=_TOKEN)
    assert "no-store" in resp.headers.get("Cache-Control", "")


def test_bootState_missingToken_returns401(runningServer):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(runningServer, "/boot-state", token=None)
    assert exc.value.code == 401


def test_bootState_wrongToken_returns401(runningServer):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(runningServer, "/boot-state", token="not-the-token")
    assert exc.value.code == 401


def test_pathTraversal_returns404_doesNotEscapeStatesDir(runningServer):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(runningServer, "/../assets/index.html", token=_TOKEN)
    assert exc.value.code == 404


def test_unknownStateFile_withToken_returns404(runningServer):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(runningServer, "/no-such-state", token=_TOKEN)
    assert exc.value.code == 404


def test_index_servesAssetWithInjectedToken_noPlaceholderLeft(runningServer):
    resp = _get(runningServer, "/", token=None)  # asset route is not token-gated
    body = resp.read().decode("utf-8")
    assert resp.status == 200
    assert _TOKEN in body
    assert "__SPLASH_TOKEN__" not in body


def test_staticAsset_servedWithoutToken(runningServer):
    resp = _get(runningServer, "/splash.svg", token=None)
    assert resp.status == 200
    assert "<svg" in resp.read().decode("utf-8")
