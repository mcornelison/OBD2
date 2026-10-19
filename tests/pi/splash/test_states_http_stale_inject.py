################################################################################
# File Name: test_states_http_stale_inject.py
# Purpose/Description: US-882-c (F-159, Atlas gap 6) -- eclipse-states-http
#   injects window.DISPLAY_STALE = {"imuSec": <effective value>} into the served
#   dashboard HTML, resolved PER REQUEST through overlay.readEffectiveValue
#   (the US-533 B1 carousel pattern), so the IMU card's stale window is tunable
#   in config.json with no code change and no unit restart. imuSec is a
#   config.json engineering key, NOT operator-overridable (Atlas ruled B): a
#   value placed in config.local.json is ignored.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-14    | Ralph (Rex)  | Initial -- US-882-c per-request DISPLAY_STALE.
# 2026-10-14    | Ralph (Rex)  | Atlas ruled B: overlay value IGNORED (flipped).
# 2026-10-18    | Rex (US-890-f) | PIN CHANGE: the injected-dict equalities gain
#               |              | fuelResetConfirmSec (via _stale); its own
#               |              | default / configured / invalid / overlay cases.
# ================================================================================
################################################################################
"""US-882-c tests: window.DISPLAY_STALE is injected per request."""

import inspect
import json
import threading
import urllib.request
from pathlib import Path

import pytest

from common.config import overlay
from common.config.validator import DEFAULTS
from pi.splash import states_http_server
from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_IMU_SEC_KEY = "pi.display.stale.imuSec"
_CONFIRM_KEY = "pi.display.stale.fuelResetConfirmSec"

_INDEX = "<script>\n" 'window.DISPLAY_STALE = "__DISPLAY_STALE__";\n' "</script>"

_DASHBOARD = (
    Path(__file__).resolve().parents[3] / "src" / "pi" / "ui" / "dashboard" / "dashboard.html"
)


def _writeJson(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _startServer(tmp_path, configPath):
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
        configPath=configPath,
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture
def served(tmp_path):
    """A running server wired to a real config.json (no stale section)."""
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"obdLiveSec": 5}}}})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        yield server, configPath
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _index(server) -> str:
    url = f"http://127.0.0.1:{server.actualPort}/"
    return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")


def _injectedStale(body: str):
    marker = "window.DISPLAY_STALE = "
    start = body.index(marker) + len(marker)
    return json.loads(body[start : body.index(";", start)])


def _stale(imuSec, fuelResetConfirmSec=None) -> dict:
    """The whole injected dict. US-890-f PIN CHANGE: it gains fuelResetConfirmSec,
    the validator default unless a test configures it."""
    if fuelResetConfirmSec is None:
        fuelResetConfirmSec = DEFAULTS[_CONFIRM_KEY]
    return {"imuSec": imuSec, "fuelResetConfirmSec": fuelResetConfirmSec}


def test_configJsonChange_appliesWithoutARestart(tmp_path):
    """
    Given: config.json sets pi.display.stale.imuSec 3.5
    When: GET /, then config.json changes to 4.0, then GET / again
    Then: the first serve carries 3.5 and the second 4.0 on the SAME server
    """
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"imuSec": 3.5}}}})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        assert _injectedStale(_index(server)) == _stale(3.5)

        _writeJson(configPath, {"pi": {"display": {"stale": {"imuSec": 4.0}}}})
        assert _injectedStale(_index(server)) == _stale(4.0)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_overlayImuSec_isIgnored_theAllowListHolds(served):
    """
    Given: config.local.json sets pi.display.stale.imuSec 3.5 (config.json has none)
    When: GET /
    Then: the served value stays the validator default -- imuSec is a config.json
          engineering key, not operator-overridable (Atlas ruled B)
    """
    server, configPath = served
    overlayPath = Path(overlay.overlayPathFor(str(configPath)))
    _writeJson(overlayPath, {_IMU_SEC_KEY: 3.5})

    assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])


def test_overlayImuSec_isIgnored_configJsonValueStands(tmp_path):
    """An overlay value never displaces the config.json value either."""
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"imuSec": 6}}}})
    _writeJson(Path(overlay.overlayPathFor(str(configPath))), {_IMU_SEC_KEY: 3.5})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        assert _injectedStale(_index(server)) == _stale(6)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_configJsonValue_isServed(tmp_path):
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"imuSec": 6}}}})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        assert _injectedStale(_index(server)) == _stale(6)
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_keyAbsent_servesTheValidatorDefault(served):
    """The effective value of an absent key is the validator default (3.0).

    MOVED PIN (US-896-b): US-896-a raised the imuSec default 2.0 -> 3.0."""
    server, _ = served
    assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])
    assert DEFAULTS[_IMU_SEC_KEY] == 3.0


@pytest.mark.parametrize("bad", [0, -1, "3.5", True, None])
def test_invalidConfiguredValue_servesTheValidatorDefault(tmp_path, bad):
    """A value the validator would refuse never reaches the page."""
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"imuSec": bad}}}})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_unreadableConfig_servesTheValidatorDefault_notACrash(served):
    server, configPath = served
    configPath.unlink()
    assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])


def test_noConfigPath_servesTheValidatorDefault(tmp_path):
    server, thread = _startServer(tmp_path, None)
    try:
        assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fuelResetConfirmSec_absent_servesTheValidatorDefaultOfSix(served):
    """US-890-f: the key is validator-default only (config.json is not edited)."""
    server, _ = served
    assert _injectedStale(_index(server))["fuelResetConfirmSec"] == DEFAULTS[_CONFIRM_KEY] == 6


def test_fuelResetConfirmSec_configJsonValue_isServed_perRequest(tmp_path):
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"fuelResetConfirmSec": 8.5}}}})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY], 8.5)
        _writeJson(configPath, {"pi": {"display": {"stale": {"fuelResetConfirmSec": 9}}}})
        assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY], 9)
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("bad", [0, -1, "6", True, None])
def test_fuelResetConfirmSec_invalid_servesTheValidatorDefault(tmp_path, bad):
    configPath = tmp_path / "config.json"
    _writeJson(configPath, {"pi": {"display": {"stale": {"fuelResetConfirmSec": bad}}}})
    server, thread = _startServer(tmp_path, str(configPath))
    try:
        assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_fuelResetConfirmSec_overlayValue_isIgnored(served):
    """Not operator-overridable (Atlas ruling B), exactly as imuSec."""
    server, configPath = served
    _writeJson(Path(overlay.overlayPathFor(str(configPath))), {_CONFIRM_KEY: 30})
    assert _injectedStale(_index(server)) == _stale(DEFAULTS[_IMU_SEC_KEY])


def test_staleConfigIsNotSerializedAtConstruction():
    """Mechanism guard: a value resolved before the handler class exists cannot
    be per-request (the US-533 B1 guard, applied to DISPLAY_STALE)."""
    source = inspect.getsource(states_http_server.makeStatesHandler)
    prologue = source[: source.index("class _StatesHandler")]
    assert "loadDisplayStaleConfig" not in prologue
    assert "staleJson" not in prologue


def test_dashboardHtml_carriesTheQuotedPlaceholder():
    """The shipped dashboard declares window.DISPLAY_STALE via the quoted
    placeholder, so an un-substituted file:// preview stays valid JS."""
    html = _DASHBOARD.read_text(encoding="utf-8")
    assert 'window.DISPLAY_STALE = "__DISPLAY_STALE__";' in html
