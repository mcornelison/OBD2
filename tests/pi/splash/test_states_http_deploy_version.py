################################################################################
# File Name: test_states_http_deploy_version.py
# Purpose/Description: US-501 tests for the states server injecting the REAL
#   deployed version into the dashboard header chip. The chip shipped the literal
#   "V?.?.?" forever because nothing ever wrote a version into the markup; the
#   fix substitutes the "__DEPLOY_VERSION__" placeholder from .deploy-version at
#   serve time (the same _injectHtml seam as __SPLASH_TOKEN__ / __DISPLAY_AUTODIM__).
#   The load-bearing case is the PER-REQUEST read: deploy-pi.sh restarts
#   eclipse-states-http (step_install_state_server_units) BEFORE it writes
#   .deploy-version (step_write_deploy_version, deliberately last so a failed
#   restart cannot bump the stamp), so a version cached at handler-construction
#   would show the PREVIOUS deploy's version until the next restart -- a stale
#   literal, which is exactly what AC#3 forbids.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-01    | Ralph (Rex)  | Initial -- US-501 version-chip wiring.
# ================================================================================
################################################################################

"""US-501 tests for states_http_server .deploy-version injection."""

import json
import threading
import urllib.request

from pi.splash.states_http_server import StatesHttpServer, readDeployVersion

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"

# The header chip as the shipped dashboard carries it (US-501 markup).
_INDEX = '<header><span id="version-chip">__DEPLOY_VERSION__</span></header>'

# The honest "the version could not be read" sentinel -- the SAME string the
# splash chip already uses, so one glyph means "unknown build" on both surfaces.
_UNKNOWN = "V?.?.?"


def _writeVersionFile(path, version):
    """Write a .deploy-version record shaped like the one deploy-pi.sh stamps."""
    path.write_text(
        json.dumps(
            {
                "version": version,
                "releasedAt": "2026-08-01T22:11:41Z",
                "gitHash": "a0d549d",
                "description": "test record",
            }
        ),
        encoding="utf-8",
    )


def _serve(tmp_path, deployVersionPath):
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
        deployVersionPath=deployVersionPath,
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    return server, thread


def _get_index(server):
    url = f"http://127.0.0.1:{server.actualPort}/"
    return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")


# ---------------------------------------------------------------------------
# AC#1/AC#2 -- the chip carries the REAL version, sourced from .deploy-version
# ---------------------------------------------------------------------------


def test_index_injectsRealVersionFromDeployVersionFile(tmp_path):
    """
    Given: a .deploy-version stamped V0.29.24
    When: the dashboard HTML is served
    Then: the chip carries V0.29.24 and the placeholder is gone
    """
    versionFile = tmp_path / ".deploy-version"
    _writeVersionFile(versionFile, "V0.29.24")
    server, thread = _serve(tmp_path, str(versionFile))
    try:
        body = _get_index(server)
        assert "__DEPLOY_VERSION__" not in body  # placeholder substituted
        assert '<span id="version-chip">V0.29.24</span>' in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_readsVersionPerRequest_notCachedAtStartup(tmp_path):
    """
    Given: a server started while .deploy-version still reads the OLD version
    When: .deploy-version is re-stamped (as deploy-pi.sh does AFTER the restart)
          and the dashboard is fetched again
    Then: the chip shows the NEW version without a service restart

    This is the deploy-ordering guard: step_write_deploy_version runs after
    step_install_state_server_units, so a start-time cache is stale by construction.
    """
    versionFile = tmp_path / ".deploy-version"
    _writeVersionFile(versionFile, "V0.29.23")
    server, thread = _serve(tmp_path, str(versionFile))
    try:
        assert "V0.29.23" in _get_index(server)
        _writeVersionFile(versionFile, "V0.29.24")
        body = _get_index(server)
        assert "V0.29.24" in body
        assert "V0.29.23" not in body  # no stale carry-over
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# AC#3 -- honest degrade: never a fabricated or stale literal
# ---------------------------------------------------------------------------


def test_index_missingDeployVersion_degradesToUnknownSentinel(tmp_path):
    """
    Given: no .deploy-version on disk
    When: the dashboard HTML is served
    Then: the chip reads the honest unknown sentinel, never a version number
    """
    server, thread = _serve(tmp_path, str(tmp_path / ".deploy-version"))
    try:
        body = _get_index(server)
        assert f'<span id="version-chip">{_UNKNOWN}</span>' in body
        assert "__DEPLOY_VERSION__" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_noVersionSourceConfigured_degradesToUnknownSentinel(tmp_path):
    """
    Given: the server was constructed with no deploy-version path at all
    When: the dashboard HTML is served
    Then: the placeholder is still substituted -- a raw __DEPLOY_VERSION__ must
          never reach the panel
    """
    server, thread = _serve(tmp_path, None)
    try:
        body = _get_index(server)
        assert f'<span id="version-chip">{_UNKNOWN}</span>' in body
        assert "__DEPLOY_VERSION__" not in body
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_index_malformedDeployVersion_degradesToUnknownSentinel(tmp_path):
    """
    Given: a .deploy-version that is not valid JSON
    When: the dashboard HTML is served
    Then: the chip degrades to the sentinel -- no crash, no fabricated version
    """
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text("{not json at all", encoding="utf-8")
    server, thread = _serve(tmp_path, str(versionFile))
    try:
        assert f'<span id="version-chip">{_UNKNOWN}</span>' in _get_index(server)
    finally:
        server.shutdown()
        thread.join(timeout=5)


# ---------------------------------------------------------------------------
# readDeployVersion -- the fail-safe reader itself
# ---------------------------------------------------------------------------


def test_readDeployVersion_returnsVersionString(tmp_path):
    versionFile = tmp_path / ".deploy-version"
    _writeVersionFile(versionFile, "V0.29.24")
    assert readDeployVersion(str(versionFile)) == "V0.29.24"


def test_readDeployVersion_stripsSurroundingWhitespace(tmp_path):
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text(json.dumps({"version": "  V0.29.24 \n"}), encoding="utf-8")
    assert readDeployVersion(str(versionFile)) == "V0.29.24"


def test_readDeployVersion_noneWhenPathNotConfigured():
    assert readDeployVersion(None) is None


def test_readDeployVersion_noneWhenFileAbsent(tmp_path):
    assert readDeployVersion(str(tmp_path / "nope")) is None


def test_readDeployVersion_noneWhenMalformedJson(tmp_path):
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text("{not json", encoding="utf-8")
    assert readDeployVersion(str(versionFile)) is None


def test_readDeployVersion_noneWhenVersionKeyAbsent(tmp_path):
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text(json.dumps({"gitHash": "abc1234"}), encoding="utf-8")
    assert readDeployVersion(str(versionFile)) is None


def test_readDeployVersion_noneWhenVersionEmpty(tmp_path):
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text(json.dumps({"version": "   "}), encoding="utf-8")
    assert readDeployVersion(str(versionFile)) is None


def test_readDeployVersion_noneWhenVersionNotAString(tmp_path):
    """A numeric/None version is a malformed record, not a version to render."""
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text(json.dumps({"version": 29}), encoding="utf-8")
    assert readDeployVersion(str(versionFile)) is None


# ---------------------------------------------------------------------------
# The other _injectHtml seams must survive the new substitution
# ---------------------------------------------------------------------------


def test_versionInjection_doesNotBreakTokenSeam(tmp_path):
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    assetsDir = tmp_path / "assets"
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text(
        '<span id="version-chip">__DEPLOY_VERSION__</span>'
        '<script>window.SPLASH_TOKEN = "__SPLASH_TOKEN__";</script>',
        encoding="utf-8",
    )
    versionFile = tmp_path / ".deploy-version"
    _writeVersionFile(versionFile, "V0.29.24")
    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=str(assetsDir),
        deployVersionPath=str(versionFile),
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    try:
        body = _get_index(server)
        assert f'window.SPLASH_TOKEN = "{_TOKEN}"' in body
        assert "V0.29.24" in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
