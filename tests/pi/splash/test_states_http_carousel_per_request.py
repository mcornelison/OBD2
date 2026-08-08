################################################################################
# File Name: test_states_http_carousel_per_request.py
# Purpose/Description: US-533 B1 (CIO-ratified path #3, 2026-08-08) -- the
#   injected carousel navigation config (__DISPLAY_CAROUSEL__) is resolved PER
#   REQUEST instead of once at handler construction, so a settings-band write to
#   pi.display.carousel.autoRotateS takes effect on the next PAGE RELOAD with NO
#   eclipse-states-http restart. The restart remedy was unavailable by design:
#   the unit runs User=mcornelison and polkit's manage-units grant deliberately
#   excludes the state server (BL-030 B1), so a restart-based toggle would have
#   been a SILENT NO-OP on the Pi while passing every dev-box test.
#
#   This is US-501's __DEPLOY_VERSION__ pattern and US-532's __DISPLAY_SETTINGS__
#   pattern applied to the last resolved-at-construction value in _injectHtml.
#
#   The load-bearing test is test_autoRotateSWrite_isServedWithoutARestart: the
#   SAME running server instance must serve the NEW value. Everything else here
#   passes against the cached implementation.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-08    | Ralph (Rex)  | Initial -- US-533 B1 per-request carousel config.
# ================================================================================
################################################################################
"""US-533 B1 tests: the carousel config is resolved per request, not cached."""

import json
import threading
import urllib.error
import urllib.request

import pytest

from pi.splash.states_http_server import StatesHttpServer, loadDisplayCarouselConfig

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_AUTO_ROTATE = "pi.display.carousel.autoRotateS"

_INDEX = (
    "<script>\n"
    'window.DISPLAY_CAROUSEL = "__DISPLAY_CAROUSEL__";\n'
    'window.DISPLAY_SETTINGS = "__DISPLAY_SETTINGS__";\n'
    "</script>"
)

# The shipped default is 8s (US-536 ships 0, but a fixture that EQUALS the value
# under test can be satisfied by a broken reader -- US-530's lesson). Every
# assertion below writes a value that differs from whatever the base carries.
_BASE_CONFIG = {
    "pi": {
        "display": {
            "carousel": {"autoRotateS": 8, "resumeIdleS": 45, "swipeMinPx": 40}
        },
        "power": {"mode": "car"},
        "calibration": {"mode": False},
        "analysis": {"triggerAfterDrive": True},
    }
}


def _writeConfig(tmp_path, config=None):
    configPath = tmp_path / "config.json"
    configPath.write_text(
        json.dumps(_BASE_CONFIG if config is None else config), encoding="utf-8"
    )
    return str(configPath)


@pytest.fixture
def served(tmp_path):
    """A running server wired to a real config.json, with a real assets dir."""
    configPath = _writeConfig(tmp_path)
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
        # Exactly what main() passes: the value read ONCE at startup...
        carouselConfig=loadDisplayCarouselConfig(configPath),
        # ...alongside the path that lets the handler re-read it per request.
        configPath=configPath,
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    try:
        yield server, configPath
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _index(server):
    url = f"http://127.0.0.1:{server.actualPort}/"
    return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")


def _injected(body, name):
    marker = f"window.{name} = "
    start = body.index(marker) + len(marker)
    return json.loads(body[start : body.index(";", start)])


def _postSetting(server, key, value):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.actualPort}/settings",
        data=json.dumps({"key": key, "value": value}).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Splash-Token": _TOKEN},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# B1 -- the toggle applies on RELOAD, with no unit restart.
# ---------------------------------------------------------------------------


def test_autoRotateSWrite_isServedWithoutARestart(served):
    """THE story test. One running server, no bounce, no re-construction:

    serve -> POST autoRotateS=0 -> serve again -> the injected carousel config
    carries 0. Against the construction-cached implementation the second serve
    still says 8, which is the silent no-op that made this a blocker.
    """
    server, _ = served
    assert _injected(_index(server), "DISPLAY_CAROUSEL")["autoRotateS"] == 8

    status, body = _postSetting(server, _AUTO_ROTATE, 0)
    assert (status, body["ok"], body["value"]) == (200, True, 0)

    assert _injected(_index(server), "DISPLAY_CAROUSEL")["autoRotateS"] == 0


def test_autoRotateSCanBeTurnedBackOn_withoutARestart(served):
    """Both directions, on the same instance -- an implementation that re-reads
    only once (e.g. memoising after the first miss) fails here."""
    server, _ = served
    _postSetting(server, _AUTO_ROTATE, 0)
    assert _injected(_index(server), "DISPLAY_CAROUSEL")["autoRotateS"] == 0

    _postSetting(server, _AUTO_ROTATE, 20)
    assert _injected(_index(server), "DISPLAY_CAROUSEL")["autoRotateS"] == 20


def test_injectedCarouselAndSettingsAgreeOnAutoRotateS(served):
    """US-532 deliberately did NOT pin these two together, because back then
    DISPLAY_SETTINGS reported what was STORED while DISPLAY_CAROUSEL reported
    what was RUNNING -- a real and honest disagreement.

    B1 DELETES that gap: both are now resolved per request from the same file
    through the same overlay seam, so they must agree. If they ever diverge
    again the band's "applies on reload" label becomes a lie.
    """
    server, _ = served
    for value in (0, 12, 8):
        _postSetting(server, _AUTO_ROTATE, value)
        body = _index(server)
        assert _injected(body, "DISPLAY_CAROUSEL")["autoRotateS"] == value
        assert _injected(body, "DISPLAY_SETTINGS")[_AUTO_ROTATE] == value


def test_theRestOfTheCarouselSectionSurvivesTheReRead(served):
    """The section is passed through WHOLESALE (US-506) -- re-reading must not
    quietly narrow it to the overridable key and strip the swipe thresholds."""
    server, _ = served
    _postSetting(server, _AUTO_ROTATE, 0)
    injected = _injected(_index(server), "DISPLAY_CAROUSEL")
    assert injected["resumeIdleS"] == 45
    assert injected["swipeMinPx"] == 40


def test_anEditToConfigJsonItselfIsAlsoPickedUp(served):
    """Same property, other direction: a deploy that ships a new shipped default
    reaches the kiosk on the next page load, not the next unit restart."""
    server, configPath = served
    config = json.loads(open(configPath, encoding="utf-8").read())
    config["pi"]["display"]["carousel"]["autoRotateS"] = 30
    with open(configPath, "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    assert _injected(_index(server), "DISPLAY_CAROUSEL")["autoRotateS"] == 30


# ---------------------------------------------------------------------------
# Honest degradation -- the per-request read must not be able to blank the kiosk.
# ---------------------------------------------------------------------------


def test_unreadableConfig_fallsBackToGroundedDefaults_notACrash(tmp_path):
    """An unreadable config.json injects `null`, which the carousel answers with
    its built-in grounded defaults. The page must still serve (a 500 here would
    take the whole dashboard down over a config typo)."""
    configPath = _writeConfig(tmp_path)
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
        carouselConfig=loadDisplayCarouselConfig(configPath),
        configPath=configPath,
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    try:
        import os

        os.remove(configPath)
        assert _injected(_index(server), "DISPLAY_CAROUSEL") is None
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_noConfigPath_stillServesTheConstructorValue(tmp_path):
    """A server with no config wired (the standalone/test call sites) keeps the
    US-506 behaviour exactly: the explicitly-supplied section is injected. The
    per-request read is an UPGRADE where a config path exists, not a new
    requirement that breaks servers without one."""
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
        carouselConfig={"autoRotateS": 17},
        configPath=None,
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    try:
        assert _injected(_index(server), "DISPLAY_CAROUSEL")["autoRotateS"] == 17
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_carouselConfigIsNotSerializedAtConstruction(tmp_path):
    """Mechanism guard, not behaviour: a value JSON-encoded in the closure is a
    value that CANNOT be per-request. Pins the seam so a future refactor cannot
    quietly re-cache it and re-arm the polkit blocker.
    """
    import inspect

    from pi.splash import states_http_server

    source = inspect.getsource(states_http_server.makeStatesHandler)
    prologue = source[: source.index("class _StatesHandler")]
    assert "carouselConfigJson" not in prologue, (
        "carousel config is serialized at handler construction -- "
        "a page reload can then never pick up a new autoRotateS"
    )
