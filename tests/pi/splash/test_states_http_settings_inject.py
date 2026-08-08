################################################################################
# File Name: test_states_http_settings_inject.py
# Purpose/Description: US-532 tests for the states server surfacing the 5 Slice-1
#   operator settings at their CURRENT EFFECTIVE values (US-530 shared resolver)
#   into the same-origin dashboard HTML as window.DISPLAY_SETTINGS -- the read
#   half of the F-126 settings band. Deliberately NOT a GET endpoint: US-531
#   ruled a read route would be a SECOND source for a fact the injected config
#   already carries, and two sources can disagree.
#
#   The load-bearing test here is the PER-REQUEST one. The value is resolved on
#   every HTML serve (the __DEPLOY_VERSION__ / US-501 pattern), NOT cached at
#   handler construction (the __DISPLAY_CAROUSEL__ / US-506 pattern): a cached
#   blob would render the PRE-SAVE value after any page reload that is not
#   preceded by a unit bounce, i.e. the band would lie about a setting the
#   operator had just written. Every other test in this file passes against a
#   construction-time cache.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Ralph (Rex)  | Initial -- US-532 effective-settings injection.
# ================================================================================
################################################################################

"""US-532 tests for states_http_server effective-settings injection."""

import json
import threading
import urllib.request

import pytest

from common.config import overlay
from pi.splash.states_http_server import StatesHttpServer, loadEffectiveSettings

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"

_INDEX = (
    "<script>\n"
    'window.SPLASH_TOKEN = "__SPLASH_TOKEN__";\n'
    'window.DISPLAY_CAROUSEL = "__DISPLAY_CAROUSEL__";\n'
    'window.DISPLAY_SETTINGS = "__DISPLAY_SETTINGS__";\n'
    "</script>"
)

# A config.json carrying every Slice-1 key at a value that is NOT the value any
# test then writes -- so an assertion can never be satisfied by the default.
_BASE_CONFIG = {
    "pi": {
        "display": {"carousel": {"autoRotateS": 8}},
        "power": {"mode": "car"},
        "alerts": {"audioAlerts": True},
        "calibration": {"mode": False},
        "analysis": {"triggerAfterDrive": True},
    }
}


def _writeConfig(tmp_path, config=None):
    """Write a config.json and return its path."""
    configPath = tmp_path / "config.json"
    configPath.write_text(
        json.dumps(_BASE_CONFIG if config is None else config), encoding="utf-8"
    )
    return str(configPath)


def _writeOverlay(configPath, mapping):
    """Write the Pi-local overlay beside config.json via the SSOT path helper."""
    with open(overlay.overlayPathFor(configPath), "w", encoding="utf-8") as fh:
        json.dump(mapping, fh)


def _serve(tmp_path, configPath):
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


def _getIndex(server):
    url = f"http://127.0.0.1:{server.actualPort}/"
    return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")


def _injectedSettings(body):
    """Parse the injected window.DISPLAY_SETTINGS object literal back out."""
    marker = "window.DISPLAY_SETTINGS = "
    start = body.index(marker) + len(marker)
    return json.loads(body[start : body.index(";", start)])


# ---------------------------------------------------------------------------
# loadEffectiveSettings -- the read seam itself.
# ---------------------------------------------------------------------------


def test_loadEffectiveSettings_readsEveryOverridableKey(tmp_path):
    """The band renders the SSOT's key set, so the read must cover it exactly.

    Asserted against overlay.OVERRIDABLE_KEYS rather than a literal list: a
    Slice-2 key added to the SSOT must flow to the band without a server edit,
    and this test is what fails if it silently does not.
    """
    settings = loadEffectiveSettings(_writeConfig(tmp_path))
    assert set(settings) == set(overlay.OVERRIDABLE_KEYS)


def test_loadEffectiveSettings_returnsShippedDefaultsWhenNoOverlay(tmp_path):
    settings = loadEffectiveSettings(_writeConfig(tmp_path))
    assert settings["pi.display.carousel.autoRotateS"] == 8
    assert settings["pi.power.mode"] == "car"
    assert settings["pi.calibration.mode"] is False
    assert settings["pi.analysis.triggerAfterDrive"] is True


def test_loadEffectiveSettings_overlayOverrideWins(tmp_path):
    """Every override value here DIFFERS from the base config's, so a reader that
    ignored the overlay entirely would fail on all four (US-530's lesson: never
    let the expected value equal the default)."""
    configPath = _writeConfig(tmp_path)
    _writeOverlay(
        configPath,
        {
            "pi.display.carousel.autoRotateS": 0,
            "pi.power.mode": "wall",
            "pi.calibration.mode": True,
            "pi.analysis.triggerAfterDrive": False,
        },
    )
    settings = loadEffectiveSettings(configPath)
    assert settings["pi.display.carousel.autoRotateS"] == 0
    assert settings["pi.power.mode"] == "wall"
    assert settings["pi.calibration.mode"] is True
    assert settings["pi.analysis.triggerAfterDrive"] is False


def test_loadEffectiveSettings_noConfigPath_isNone(tmp_path):
    """Honest unavailability -- a standalone server with no config has nothing to
    report, and must not report the shipped defaults as if they were live."""
    assert loadEffectiveSettings(None) is None


def test_loadEffectiveSettings_malformedConfig_everyKeyUnknown(tmp_path):
    """Unreadable config -> every value None (unknown), never a guessed default
    and never a crash that would take the whole kiosk page down."""
    configPath = tmp_path / "config.json"
    configPath.write_text("{not json", encoding="utf-8")
    settings = loadEffectiveSettings(str(configPath))
    assert set(settings) == set(overlay.OVERRIDABLE_KEYS)
    assert all(value is None for value in settings.values())


def test_loadEffectiveSettings_unresolvableKey_isNoneNotADefault(tmp_path):
    """A key whose parent branch is not a dict cannot resolve. The honest answer
    is unknown -- the same case US-531 used to prove its response is a re-read."""
    configPath = _writeConfig(tmp_path, {"pi": {"power": "not-a-dict"}})
    settings = loadEffectiveSettings(configPath)
    assert settings["pi.power.mode"] is None


def test_loadEffectiveSettings_invalidOverlayValue_fallsBackNotForward(tmp_path):
    """A wrong-typed override is ignored by the shared resolver, so the band
    shows the shipped default -- not the junk the overlay carried."""
    configPath = _writeConfig(tmp_path)
    _writeOverlay(configPath, {"pi.calibration.mode": "yes-please"})
    assert loadEffectiveSettings(configPath)["pi.calibration.mode"] is False


def test_loadEffectiveSettings_invalidPowerMode_coercesToUnknown(tmp_path):
    """Honest-unknown contract: a corrupt mode means the deployment context is
    unknown. It must NOT fall back to the base config's confident 'car'."""
    configPath = _writeConfig(tmp_path)
    _writeOverlay(configPath, {"pi.power.mode": "moon-base"})
    assert loadEffectiveSettings(configPath)["pi.power.mode"] == "unknown"


# ---------------------------------------------------------------------------
# The injection seam.
# ---------------------------------------------------------------------------


def test_index_injectsSettingsObject(tmp_path):
    server, thread = _serve(tmp_path, _writeConfig(tmp_path))
    try:
        body = _getIndex(server)
        assert '"__DISPLAY_SETTINGS__"' not in body  # placeholder gone
        assert "window.DISPLAY_SETTINGS = {" in body  # a JS object, not a string
        assert _injectedSettings(body)["pi.power.mode"] == "car"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_noConfigPath_injectsNull(tmp_path):
    """No config -> `null`, which the band renders as five unknown rows rather
    than as five confident defaults."""
    server, thread = _serve(tmp_path, None)
    try:
        body = _getIndex(server)
        assert "window.DISPLAY_SETTINGS = null;" in body
        assert '"__DISPLAY_SETTINGS__"' not in body
        assert "__SPLASH_TOKEN__" not in body  # the token seam still works
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_settingsAreResolvedPerRequest_notCachedAtConstruction(tmp_path):
    """*** THE LOAD-BEARING TEST. ***

    The whole point of the band is that it reports what is actually stored. If
    the settings blob were resolved once at handler construction (the US-506
    carousel-config pattern), then: operator taps auto-rotate off -> POST
    /settings writes the overlay -> operator reloads the page -> the band renders
    8 again, silently discarding a save that DID happen. The value is therefore
    resolved on every HTML serve (the US-501 __DEPLOY_VERSION__ pattern, adopted
    for exactly this reason).

    Every other test in this file passes against a cached implementation.
    """
    configPath = _writeConfig(tmp_path)
    server, thread = _serve(tmp_path, configPath)
    try:
        assert _injectedSettings(_getIndex(server))["pi.power.mode"] == "car"
        # Simulate the US-531 write landing AFTER the server was constructed.
        _writeOverlay(configPath, {"pi.power.mode": "wall"})
        assert _injectedSettings(_getIndex(server))["pi.power.mode"] == "wall"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.parametrize("key", overlay.OVERRIDABLE_KEYS)
def test_index_injectsEveryOverridableKey(tmp_path, key):
    """Parametrized over the SSOT so a Slice-2 key cannot land unsurfaced."""
    server, thread = _serve(tmp_path, _writeConfig(tmp_path))
    try:
        assert key in _injectedSettings(_getIndex(server))
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_settingsKeysAreThePostBodyKeys(tmp_path):
    """The band POSTs the row's key straight back to /settings. Injecting under
    renamed/prettified keys would need a mapping table on the display side, and
    that table is exactly the thing that drifts from the allow-list."""
    server, thread = _serve(tmp_path, _writeConfig(tmp_path))
    try:
        injected = _injectedSettings(_getIndex(server))
        for key in injected:
            assert key in overlay.OVERRIDABLE_KEYS
    finally:
        server.shutdown()
        thread.join(timeout=5)
