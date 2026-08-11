################################################################################
# File Name: test_states_http_settings_write.py
# Purpose/Description: F-126 (US-531) tests for the token-gated settings-write
#   POST endpoint on the F-103 localhost state server. The chromium kiosk is JS
#   in a sandbox and cannot write files, so a settings toggle POSTs here to
#   persist the US-530 Pi-local overlay. This is the THIRD write route, built to
#   the US-403/US-407 pattern exactly: _tokenOk() first (401), the gate itself
#   delegated to the SSOT module (common.config.overlay), never re-implemented.
#
#   Tests assert: token-gating (401 + NO write), out-of-allow-list and
#   wrong-typed values rejected 4xx with NO write, an authenticated write
#   persisting to the overlay, the response carrying the REAL re-read effective
#   value (never an optimistic echo), honest 503 when no config is wired, and
#   that GET stays read-only. No real config.json is ever written.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Ralph (Rex)  | Initial implementation (US-531 settings write).
# ================================================================================
################################################################################

"""Tests for the US-531 POST /settings endpoint on the state server."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from common.config.overlay import (
    OVERLAY_FILENAME,
    OVERRIDABLE_KEYS,
    readEffectiveValue,
)
from pi.splash import states_http_server
from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"
_SETTINGS_PATH = "/settings"
_AUTO_ROTATE_KEY = "pi.display.carousel.autoRotateS"
_POWER_KEY = "pi.power.mode"

# Shipped defaults chosen to DIFFER from every value the tests write, so no
# assertion can pass by coincidentally matching the fallback (US-530 lesson).
_BASE_CONFIG = {
    "deviceId": "test-pi",
    "pi": {
        "display": {"carousel": {"autoRotateS": 8}},
        "power": {"mode": "car"},
        "alerts": {"audioAlerts": False},
        "calibration": {"mode": False},
        "analysis": {"triggerAfterDrive": False},
    },
}

# One valid value per allow-listed key. Deliberately keyed off OVERRIDABLE_KEYS
# (asserted below) so growing the Slice-1 allow-list forces a conscious update
# here rather than silently leaving a new writable key untested.
_VALID_VALUES = {
    _AUTO_ROTATE_KEY: 0,
    _POWER_KEY: "wall",
    "pi.calibration.mode": True,
    "pi.analysis.triggerAfterDrive": True,
}


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


def _postSetting(server, key, value, token=_TOKEN):
    return _post(server, _SETTINGS_PATH, {"key": key, "value": value}, token=token)


def _bodyOf(response) -> dict:
    return json.loads(response.read().decode("utf-8"))


@pytest.fixture
def configFile(tmp_path) -> Path:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_BASE_CONFIG), encoding="utf-8")
    return path


@pytest.fixture
def overlayFile(tmp_path) -> Path:
    return tmp_path / OVERLAY_FILENAME


def _makeServer(tmp_path, configPath) -> StatesHttpServer:
    statesDir = tmp_path / "states"
    statesDir.mkdir(exist_ok=True)
    assetsDir = tmp_path / "assets"
    assetsDir.mkdir(exist_ok=True)
    (assetsDir / "index.html").write_text("hi __SPLASH_TOKEN__", encoding="utf-8")
    return StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=str(assetsDir),
        configPath=configPath,
    )


@pytest.fixture
def server(tmp_path, configFile):
    srv = _makeServer(tmp_path, str(configFile))
    thread = _start(srv)
    yield srv
    srv.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def serverNoConfig(tmp_path):
    """A server with NO config wired -- the standalone/misconfigured case."""
    srv = _makeServer(tmp_path, None)
    thread = _start(srv)
    yield srv
    srv.shutdown()
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Token gate (US-393 SSOT -- never weakened, never bypassed)
# ---------------------------------------------------------------------------


def test_settingsWrite_requiresToken_401(server, overlayFile):
    """
    Given: a well-formed, allow-listed settings write with NO token
    When: it is POSTed
    Then: 401 and NO overlay file is created -- an un-authenticated write
          surface on the Pi is the TD-067 / Atlas BLOCK condition
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _AUTO_ROTATE_KEY, 0, token=None)

    assert exc.value.code == 401
    assert not overlayFile.exists()


def test_settingsWrite_wrongToken_401_andNoWrite(server, overlayFile):
    """
    Given: a settings write presenting the WRONG token
    When: it is POSTed
    Then: 401 with no write -- the gate compares, it does not merely check
          that some token header was present
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _AUTO_ROTATE_KEY, 0, token="not-the-token")

    assert exc.value.code == 401
    assert not overlayFile.exists()


def test_settingsWrite_bearerToken_isAccepted(server, overlayFile):
    """
    Given: the token presented as an Authorization: Bearer header
    When: a settings write is POSTed
    Then: it succeeds -- the endpoint reuses _tokenOk rather than reading the
          X-Splash-Token header itself (which would drop the Bearer form)
    """
    url = f"http://127.0.0.1:{server.actualPort}{_SETTINGS_PATH}"
    data = json.dumps({"key": _AUTO_ROTATE_KEY, "value": 0}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {_TOKEN}")

    resp = urllib.request.urlopen(req, timeout=5)

    assert resp.status == 200
    assert overlayFile.exists()


# ---------------------------------------------------------------------------
# Allow-list + type gate (delegated to common.config.overlay, not re-implemented)
# ---------------------------------------------------------------------------


def test_validValuesMapCoversTheWholeAllowList():
    """
    Given: the Slice-1 allow-list SSOT
    When: this suite's fixture values are compared against it
    Then: they match exactly -- so adding an overridable key cannot slip in
          without an accompanying endpoint test
    """
    assert set(_VALID_VALUES) == set(OVERRIDABLE_KEYS)


@pytest.mark.parametrize("key", OVERRIDABLE_KEYS)
def test_settingsWrite_everyAllowListedKey_isAccepted(server, overlayFile, key):
    """
    Given: each key on the US-530 allow-list in turn
    When: an authenticated write of a well-typed value is POSTed
    Then: it is accepted and persisted -- parametrizing over OVERRIDABLE_KEYS
          means an endpoint that grew its OWN copy of the allow-list would
          fail here the moment the two drifted
    """
    resp = _postSetting(server, key, _VALID_VALUES[key])

    assert resp.status == 200
    assert json.loads(overlayFile.read_text(encoding="utf-8"))[key] == _VALID_VALUES[key]


def test_settingsWrite_outOfAllowListKey_rejected_noWrite(server, overlayFile):
    """
    Given: a real config key that is NOT operator-overridable
    When: an authenticated write is POSTed
    Then: 4xx and NO overlay file -- the endpoint must not become a general
          config-write surface
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, "pi.obd.port", "/dev/rfcomm0")

    assert 400 <= exc.value.code < 500
    assert not overlayFile.exists()


def test_settingsWrite_outOfAllowListKey_doesNotCorruptExistingOverlay(
    server, overlayFile
):
    """
    Given: an overlay already holding a good operator setting
    When: a rejected out-of-allow-list write is POSTed
    Then: the existing overlay is byte-identical -- a rejection must not
          rewrite the file as a side effect of loading it
    """
    _postSetting(server, _POWER_KEY, "wall")
    before = overlayFile.read_bytes()

    with pytest.raises(urllib.error.HTTPError):
        _postSetting(server, "pi.obd.port", "/dev/rfcomm0")

    assert overlayFile.read_bytes() == before


def test_settingsWrite_wrongTypedValue_rejected_noWrite(server, overlayFile):
    """
    Given: an allow-listed key with a wrong-typed value
    When: an authenticated write is POSTed
    Then: 4xx with no write -- the value type is gated, not just the key
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _AUTO_ROTATE_KEY, "fast")

    assert 400 <= exc.value.code < 500
    assert not overlayFile.exists()


def test_settingsWrite_boolForNumericKey_rejected_noWrite(server, overlayFile):
    """
    Given: True for the numeric autoRotateS key (Python would treat it as 1)
    When: an authenticated write is POSTed
    Then: 4xx with no write
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _AUTO_ROTATE_KEY, True)

    assert 400 <= exc.value.code < 500
    assert not overlayFile.exists()


def test_settingsWrite_invalidPowerMode_rejected_noWrite(server, overlayFile):
    """
    Given: a power mode outside {car, wall, unknown}
    When: an authenticated write is POSTed
    Then: 4xx with no write -- an invalid mode is refused at the door rather
          than stored and quietly coerced later
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _POWER_KEY, "garage")

    assert 400 <= exc.value.code < 500
    assert not overlayFile.exists()


def test_settingsWrite_negativeAutoRotateS_rejected_noWrite(server, overlayFile):
    """
    Given: a negative auto-rotate period (meaningless as seconds)
    When: an authenticated write is POSTed
    Then: 4xx with no write
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _AUTO_ROTATE_KEY, -5)

    assert 400 <= exc.value.code < 500
    assert not overlayFile.exists()


# ---------------------------------------------------------------------------
# Malformed requests
# ---------------------------------------------------------------------------


def test_settingsWrite_malformedJsonBody_400_noWrite(server, overlayFile):
    """
    Given: a body that is not JSON
    When: it is POSTed with a valid token
    Then: 400 with no write
    """
    url = f"http://127.0.0.1:{server.actualPort}{_SETTINGS_PATH}"
    req = urllib.request.Request(url, data=b"{not json", method="POST")
    req.add_header("X-Splash-Token", _TOKEN)

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)

    assert exc.value.code == 400
    assert not overlayFile.exists()


def test_settingsWrite_missingKeyField_400_noWrite(server, overlayFile):
    """
    Given: a JSON body with no `key` field
    When: it is POSTed with a valid token
    Then: 400 with no write
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, _SETTINGS_PATH, {"value": 0}, token=_TOKEN)

    assert exc.value.code == 400
    assert not overlayFile.exists()


def test_settingsWrite_missingValueField_400_noWrite(server, overlayFile):
    """
    Given: a JSON body with no `value` field
    When: it is POSTed with a valid token
    Then: 400 with no write -- an absent value must not be read as null/false
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, _SETTINGS_PATH, {"key": _AUTO_ROTATE_KEY}, token=_TOKEN)

    assert exc.value.code == 400
    assert not overlayFile.exists()


def test_settingsWrite_nonObjectBody_400_noWrite(server, overlayFile):
    """
    Given: a JSON body that is a list rather than an object
    When: it is POSTed with a valid token
    Then: 400 with no write
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, _SETTINGS_PATH, ["pi.power.mode", "wall"], token=_TOKEN)

    assert exc.value.code == 400
    assert not overlayFile.exists()


# ---------------------------------------------------------------------------
# Honest response: the REAL stored effective value, never an optimistic echo
# ---------------------------------------------------------------------------


def test_settingsWrite_returnsRealStoredEffectiveValue(server, configFile):
    """
    Given: an accepted write of autoRotateS=0 (default is 8)
    When: the response body is compared against an INDEPENDENT re-read of the
          effective config from disk
    Then: they agree -- the endpoint reports what the readers will see
    """
    body = _bodyOf(_postSetting(server, _AUTO_ROTATE_KEY, 0))

    found, effective = readEffectiveValue(str(configFile), _AUTO_ROTATE_KEY)
    assert found is True
    assert body["value"] == effective == 0
    assert body["ok"] is True
    assert body["key"] == _AUTO_ROTATE_KEY


def test_settingsWrite_writeFailure_reportsFailureAndTheRealValue(
    server, monkeypatch, overlayFile
):
    """
    Given: an allow-listed write whose persistence FAILS (read-only media, a
           full disk -- the real-world save failure)
    When: it is POSTed
    Then: the response is NOT a success and carries the REAL effective value
          (the unchanged default 8), never the requested 0. An optimistic
          endpoint would echo 0 and the UI would show a setting that is not
          stored -- exactly the dishonest-instrument failure to prevent
    """
    monkeypatch.setattr(
        states_http_server.overlay, "writeOverlayValue", lambda *a, **k: False
    )

    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(server, _AUTO_ROTATE_KEY, 0)

    assert exc.value.code == 500
    body = json.loads(exc.value.read().decode("utf-8"))
    assert body["ok"] is False
    assert body["value"] == 8
    assert not overlayFile.exists()


def test_settingsWrite_storedButUnresolvable_reportsNullNotTheRequest(tmp_path):
    """
    Given: a config.json whose `pi.power` branch is a STRING, not a dict (a
           hand-edited or corrupted file), so an overlay override cannot be
           resolved onto it
    When: an otherwise-valid power-mode write is POSTed
    Then: the response value is null, NOT the requested 'wall'. This is the
          one SUCCESS-path case where an echo and an honest re-read differ --
          the write-failure test only pins the failure path, so without this
          an echoing endpoint would pass every other test here
    """
    configPath = tmp_path / "config.json"
    configPath.write_text(json.dumps({"pi": {"power": "car"}}), encoding="utf-8")
    srv = _makeServer(tmp_path, str(configPath))
    thread = _start(srv)
    try:
        body = _bodyOf(_postSetting(srv, _POWER_KEY, "wall"))
    finally:
        srv.shutdown()
        thread.join(timeout=5)

    assert body["value"] is None


def test_settingsWrite_noConfigWired_503_honestUnavailable(serverNoConfig, tmp_path):
    """
    Given: a server with no config path wired (nothing to overlay)
    When: a settings write is POSTed with a valid token
    Then: an honest 503 -- never a fabricated success, matching the US-407
          clearRunner-absent posture
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _postSetting(serverNoConfig, _AUTO_ROTATE_KEY, 0)

    assert exc.value.code == 503
    assert not (tmp_path / OVERLAY_FILENAME).exists()


# ---------------------------------------------------------------------------
# Persistence semantics + blast radius
# ---------------------------------------------------------------------------


def test_settingsWrite_secondWrite_preservesTheFirst(server, overlayFile):
    """
    Given: two different settings written in sequence
    When: the overlay is inspected
    Then: BOTH survive -- each save merges, so toggling one control cannot
          silently reset another
    """
    _postSetting(server, _POWER_KEY, "wall")
    _postSetting(server, _AUTO_ROTATE_KEY, 0)

    stored = json.loads(overlayFile.read_text(encoding="utf-8"))
    assert stored[_POWER_KEY] == "wall"
    assert stored[_AUTO_ROTATE_KEY] == 0


def test_settingsWrite_autoRotateS_roundTripsOffAndOn(server, configFile):
    """
    Given: the GAP 3a contract (autoRotateS 0=off, >0=on; no autoRotate bool)
    When: off then on is written through the endpoint
    Then: each is reported as the real effective value
    """
    assert _bodyOf(_postSetting(server, _AUTO_ROTATE_KEY, 0))["value"] == 0
    assert _bodyOf(_postSetting(server, _AUTO_ROTATE_KEY, 20))["value"] == 20
    assert readEffectiveValue(str(configFile), _AUTO_ROTATE_KEY) == (True, 20)


def test_settingsWrite_neverWritesConfigJson(server, configFile):
    """
    Given: the US-530 contract that config.json is the read-only shipped
           default and nothing writes it at runtime
    When: a setting is saved
    Then: config.json is byte-identical
    """
    before = configFile.read_bytes()

    _postSetting(server, _POWER_KEY, "wall")

    assert configFile.read_bytes() == before


def test_settingsWrite_writesOverlayBesideConfigJson(server, configFile, overlayFile):
    """
    Given: the deploy-exclude is keyed to the overlay's fixed sibling name
    When: a setting is saved
    Then: the file lands at config.json's sibling path -- writing it anywhere
          else would put operator settings outside the rsync exclude and they
          would be destroyed by the next deploy
    """
    _postSetting(server, _POWER_KEY, "wall")

    assert overlayFile.parent == configFile.parent
    assert overlayFile.exists()


# ---------------------------------------------------------------------------
# The other routes stay exactly as they were
# ---------------------------------------------------------------------------


def test_get_settingsPath_stillReadOnly_404(server):
    """
    Given: the settings route is POST-only
    When: it is fetched with GET and a valid token
    Then: 404 -- GET remains read-only (no settings read surface added here)
    """
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.actualPort}{_SETTINGS_PATH}"
    )
    req.add_header("X-Splash-Token", _TOKEN)

    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)

    assert exc.value.code == 404


def test_unknownPostPath_still404(server):
    """
    Given: the server now has THREE write routes and no more
    When: an unrelated path is POSTed
    Then: 404 -- adding /settings did not open a catch-all writer
    """
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post(server, "/boot-state", {"x": 1}, token=_TOKEN)

    assert exc.value.code == 404
