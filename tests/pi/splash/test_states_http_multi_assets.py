################################################################################
# File Name: test_states_http_multi_assets.py
# Purpose/Description: US-399 [Atlas A-2] tests for the multi-assets-dir
#   extension of the F-103 localhost state server. The carousel dashboard kit
#   (/opt/dashboard) is served SAME-ORIGIN by the SAME eclipse-states-http
#   server that serves the splash kit (/opt/splash) so the auth token is
#   injected into the dashboard HTML too (token never lands on disk). The
#   server now accepts a list of asset dirs searched in order; the first hit
#   wins. Single-string back-compat (the US-393 call sites) is preserved.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-399 carousel shell,
#               |              | A-2 states-http full-runtime extension)
# ================================================================================
################################################################################

"""Tests for the US-399 multi-assets-dir extension of ``StatesHttpServer``."""

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


def _get(server, path, token=None):
    url = f"http://127.0.0.1:{server.actualPort}{path}"
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(req, timeout=5)


@pytest.fixture
def multiDirServer(tmp_path):
    """Server with TWO assets dirs: splash (first) + dashboard (second)."""
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    (statesDir / "boot-state").write_text(
        json.dumps({"healthy": True, "degraded": False}), encoding="utf-8"
    )

    splashDir = tmp_path / "splash"
    splashDir.mkdir()
    (splashDir / "index.html").write_text(
        "<html>splash __SPLASH_TOKEN__</html>", encoding="utf-8"
    )
    # A name present in BOTH dirs -- the first dir must win.
    (splashDir / "shared.svg").write_text("<svg>from-splash</svg>", encoding="utf-8")

    dashDir = tmp_path / "dashboard"
    dashDir.mkdir()
    (dashDir / "dashboard.html").write_text(
        "<html>dashboard __SPLASH_TOKEN__</html>", encoding="utf-8"
    )
    (dashDir / "dashboard.css").write_text(".card{}", encoding="utf-8")
    (dashDir / "shared.svg").write_text("<svg>from-dashboard</svg>", encoding="utf-8")

    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=[str(splashDir), str(dashDir)],
    )
    thread = _start(server)
    yield server
    server.shutdown()
    thread.join(timeout=5)


def test_dashboardHtml_servedFromSecondDir_withTokenInjected(multiDirServer):
    """The dashboard kit (2nd dir) is served same-origin with the token injected."""
    resp = _get(multiDirServer, "/dashboard.html", token=None)  # assets not gated
    body = resp.read().decode("utf-8")
    assert resp.status == 200
    assert "dashboard" in body
    assert _TOKEN in body
    assert "__SPLASH_TOKEN__" not in body


def test_dashboardCss_servedFromSecondDir(multiDirServer):
    resp = _get(multiDirServer, "/dashboard.css", token=None)
    assert resp.status == 200
    assert "card" in resp.read().decode("utf-8")


def test_indexServedFromFirstDir(multiDirServer):
    """`/` still serves the first dir's index (splash), token injected."""
    resp = _get(multiDirServer, "/", token=None)
    body = resp.read().decode("utf-8")
    assert "splash" in body
    assert _TOKEN in body


def test_firstAssetsDirWins_onNameCollision(multiDirServer):
    """A name present in both dirs resolves from the first dir (search order)."""
    resp = _get(multiDirServer, "/shared.svg", token=None)
    assert "from-splash" in resp.read().decode("utf-8")


def test_stateFile_stillTokenGated_withMultiDir(multiDirServer):
    """State endpoints stay token-gated regardless of how many asset dirs exist."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(multiDirServer, "/boot-state", token=None)
    assert exc.value.code == 401
    resp = _get(multiDirServer, "/boot-state", token=_TOKEN)
    assert json.loads(resp.read().decode("utf-8")) == {
        "healthy": True,
        "degraded": False,
    }


def test_singleStringAssetsDir_backCompat(tmp_path):
    """A single-string assetsDir (the US-393 call sites) keeps working."""
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    assetsDir = tmp_path / "assets"
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text("only __SPLASH_TOKEN__", encoding="utf-8")

    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=str(assetsDir),
    )
    thread = _start(server)
    try:
        resp = _get(server, "/", token=None)
        body = resp.read().decode("utf-8")
        assert "only" in body
        assert _TOKEN in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
