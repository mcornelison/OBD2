################################################################################
# File Name: test_states_http_autodim.py
# Purpose/Description: US-483-b tests for the states server injecting the
#   pi.display.autoDim config into the same-origin dashboard index -- the seam
#   that makes the auto-dim curve "a config change, not a code change" (CIO
#   2026-07-22). The server substitutes the quoted "__DISPLAY_AUTODIM__"
#   placeholder with the JSON config object (mirroring the __SPLASH_TOKEN__ seam);
#   with no config it substitutes `null` so the carousel falls back to its
#   built-in grounded defaults (honest -- never a fabricated curve).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-22    | Ralph (Rex)  | Initial -- US-483-b autoDim config injection.
# ================================================================================
################################################################################

"""US-483-b tests for states_http_server display-autoDim config injection."""

import json
import threading
import urllib.request

from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_AUTODIM = {"luxMin": 3.0, "luxFull": 1000.0, "minLevel": 0.15, "curve": "logarithmic"}

_INDEX = (
    "<script>\n"
    'window.SPLASH_TOKEN = "__SPLASH_TOKEN__";\n'
    'window.DISPLAY_AUTODIM = "__DISPLAY_AUTODIM__";\n'
    "</script>"
)


def _serve(tmp_path, displayConfig):
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    assetsDir = tmp_path / "assets"
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text(_INDEX, encoding="utf-8")
    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=str(assetsDir),
        displayConfig=displayConfig,
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    return server, thread


def _get_index(server):
    url = f"http://127.0.0.1:{server.actualPort}/"
    return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")


def test_index_injectsAutodimConfigObject(tmp_path):
    server, thread = _serve(tmp_path, _AUTODIM)
    try:
        body = _get_index(server)
        assert '"__DISPLAY_AUTODIM__"' not in body  # placeholder gone
        assert "window.DISPLAY_AUTODIM = {" in body  # a JS object, not a string
        assert '"luxMin": 3.0' in body
        # Extract the injected object literal and confirm it parses as our config.
        start = body.index("window.DISPLAY_AUTODIM = ") + len("window.DISPLAY_AUTODIM = ")
        end = body.index(";", start)
        assert json.loads(body[start:end]) == _AUTODIM
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_noConfig_injectsNull(tmp_path):
    server, thread = _serve(tmp_path, None)
    try:
        body = _get_index(server)
        assert "window.DISPLAY_AUTODIM = null;" in body
        assert '"__DISPLAY_AUTODIM__"' not in body
        assert "__SPLASH_TOKEN__" not in body  # token seam still works
    finally:
        server.shutdown()
        thread.join(timeout=5)
