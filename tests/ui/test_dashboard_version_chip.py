################################################################################
# File Name: test_dashboard_version_chip.py
# Purpose/Description: US-501 kit-contract tests for the dashboard header version
#   chip. The shipped markup must carry the __DEPLOY_VERSION__ substitution
#   placeholder -- NOT a baked version string and no longer the dead "V?.?.?"
#   literal that made every build on the Pi look identical. The end-to-end test
#   serves the REAL specs/UI/dist/dashboard-pi/dashboard.html through the REAL
#   states server: the markup half and the server half must agree, which a pair
#   of independently-green half-tests does not prove (US-494/US-499 lesson).
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

"""US-501 tests for the dashboard version chip markup + served substitution."""

import json
import os
import re
import threading
import urllib.request

from pi.splash.states_http_server import StatesHttpServer

_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "specs", "UI", "dist", "dashboard-pi"
)
_HTML = os.path.join(_DIST, "dashboard.html")

_PLACEHOLDER = "__DEPLOY_VERSION__"
_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _renderable(html: str) -> str:
    """The markup with HTML comments stripped.

    The comments are design prose and legitimately DISCUSS the sentinel; only
    what actually paints on the panel is what these guards are about.
    """
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)


def _chipMarkup(html: str) -> str:
    """The full <span id="version-chip">...</span> element as shipped."""
    match = re.search(r'<span id="version-chip">(.*?)</span>', html, re.DOTALL)
    assert match is not None, 'dashboard.html must keep the #version-chip span'
    return match.group(1)


# ---------------------------------------------------------------------------
# AC#1/AC#2 -- the markup carries a placeholder, never a version literal
# ---------------------------------------------------------------------------


def test_versionChip_carriesSubstitutionPlaceholder():
    """
    Given: the shipped dashboard kit
    When: the header version chip is read
    Then: it holds the __DEPLOY_VERSION__ placeholder the state server fills
    """
    assert _chipMarkup(_read(_HTML)).strip() == _PLACEHOLDER


def test_versionChip_hasNoDeadPlaceholderLiteral():
    """The old 'V?.?.?' literal must be gone from anything that renders.

    It was a hard literal in the chip, so it never updated on a deploy. The
    sentinel is now the SERVER's fallback; the markup must not re-bake it.
    """
    assert "V?.?.?" not in _renderable(_read(_HTML))


def test_dashboardHtml_hasNoHardcodedVersionString():
    """
    Given: the shipped dashboard kit
    When: it is scanned for a SemVer-shaped literal
    Then: none is present -- the version arrives at serve time, never baked in
    """
    baked = re.findall(r"\bV\d+\.\d+\.\d+\b", _renderable(_read(_HTML)))
    assert baked == [], f"dashboard.html carries a baked version literal: {baked}"


# ---------------------------------------------------------------------------
# The two halves agree: the REAL kit served by the REAL server
# ---------------------------------------------------------------------------


def test_realDashboardServed_rendersRealVersionInChip(tmp_path):
    """
    Given: the shipped dashboard.html and a .deploy-version stamped V0.29.24
    When: the state server serves /dashboard.html
    Then: the chip carries V0.29.24 -- the markup placeholder and the server's
          substitution token are the same string
    """
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    versionFile = tmp_path / ".deploy-version"
    versionFile.write_text(
        json.dumps({"version": "V0.29.24", "gitHash": "a0d549d"}), encoding="utf-8"
    )
    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=os.path.abspath(_DIST),
        deployVersionPath=str(versionFile),
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.actualPort}/dashboard.html"
        body = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
        assert _PLACEHOLDER not in body
        assert '<span id="version-chip">V0.29.24</span>' in body
    finally:
        server.shutdown()
        thread.join(timeout=5)
