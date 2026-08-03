################################################################################
# File Name: test_splash_launcher_route_contract.py
# Purpose/Description: US-525 (I-042) launcher-URL <-> served-route contract.
#   I-042's strongest lead was a "route auth anomaly": GET / = 200 and
#   GET /shutdown.html = 200, but GET /boot /boot.html /dashboard /shutdown =
#   401, read as a NEW gate on bare routes. Atlas established the 401 is
#   BY-DESIGN (states_http_server serves index at `/`, static assets BY
#   EXTENSION, and treats everything else as a token-gated state-file lookup),
#   so the open question was never "why 401" but "does any launcher actually
#   REQUEST a bare route".
#
#   This module pins that contract from BOTH ends at once: it parses the URL out
#   of every REAL kiosk unit file and drives it against the REAL
#   states_http_server over the REAL shipped kit directories. Neither half can
#   drift alone -- repointing a unit at a bare route, or removing an asset the
#   unit names, turns this red. That is the specific two-correct-halves failure
#   the sprint keeps re-learning (US-494/499/502/503/505/513): the units were
#   correct and the server was correct, and nothing pinned that they AGREED.
#
#   AC5 is pinned here too: the token gate is never weakened. Bare routes MUST
#   stay 401 (TD-067 destructive-token-gate is an Atlas BLOCK), so this file
#   asserts the 401s are still 401 rather than "fixing" them.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Ralph (Rex)  | Initial implementation (US-525 / I-042 splash
#               |              | render fix -- launcher route contract)
# ================================================================================
################################################################################

"""Launcher-URL <-> served-route contract for the F-103 splash + dashboard kits."""

from __future__ import annotations

import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from pi.splash.states_http_server import StatesHttpServer

_TOKEN = "us525-token-abcdefghijklmnopqrstuvwxyz12"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SPLASH_KIT = _REPO_ROOT / "specs" / "UI" / "dist" / "splash-pi"
_DASHBOARD_KIT = _REPO_ROOT / "specs" / "UI" / "dist" / "dashboard-pi"

# Every unit that launches a chromium kiosk against the localhost state server.
# Both session variants ship, install.sh picks one (V-2) -- so BOTH must be
# pinned or a wayland-only regression hides behind a green x11 test.
_LAUNCHER_UNITS = (
    _SPLASH_KIT / "splash-boot.service.x11",
    _SPLASH_KIT / "splash-boot.service.wayland",
    _SPLASH_KIT / "splash-grace.service.x11",
    _SPLASH_KIT / "splash-grace.service.wayland",
    _DASHBOARD_KIT / "dashboard.service.x11",
    _DASHBOARD_KIT / "dashboard.service.wayland",
)

# The bare routes I-042 observed 401 on. They are NOT requested by any launcher
# and MUST remain token-gated (AC5 / TD-067).
_BARE_ROUTES_STAY_GATED = ("/boot", "/boot.html", "/dashboard", "/shutdown")

_URL_RE = re.compile(r"http://127\.0\.0\.1:9899(?P<path>\S*)")


def _stripComments(unitText: str) -> str:
    """Drop `#` comment lines.

    US-501/513/522 lesson (third sighting): a guard that greps raw unit text
    matches the explanatory COMMENTS discussing a URL, so a unit whose real
    ExecStart pointed at a bare route could stay green purely because a comment
    above it mentioned the correct one. Only executable lines may satisfy this.
    """
    return "\n".join(
        line for line in unitText.splitlines() if not line.lstrip().startswith("#")
    )


def _launcherUrlPath(unitPath: Path) -> str:
    """Extract the request PATH the unit's ExecStart hands chromium."""
    body = _stripComments(unitPath.read_text(encoding="utf-8"))
    matches = _URL_RE.findall(body)
    assert matches, f"{unitPath.name}: no localhost:9899 URL in executable lines"
    assert len(matches) == 1, f"{unitPath.name}: expected exactly one URL, got {matches}"
    path = matches[0]
    # A bare `http://127.0.0.1:9899` (no trailing slash) requests "/".
    return path or "/"


def _get(server: StatesHttpServer, path: str, token: str | None = None):
    url = f"http://127.0.0.1:{server.actualPort}{path}"
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(req, timeout=5)


def _status(server: StatesHttpServer, path: str, token: str | None = None) -> int:
    try:
        return _get(server, path, token=token).status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.fixture
def realKitServer(tmp_path):
    """The REAL server over the REAL shipped kits, in production dir order.

    Order matters and is the production contract (eclipse-states-http.service:
    `--assets-dir /opt/splash --assets-dir /opt/dashboard`): the splash kit is
    searched FIRST, so its index.html owns `/`. Reversing it would silently hand
    `/` to whatever the dashboard kit ships and the boot splash would launch into
    the wrong page -- so the fixture encodes the real order deliberately.
    """
    statesDir = tmp_path / "states"
    statesDir.mkdir()
    # A real state file so the token-gated branch can return 200 when authorized
    # -- otherwise a 404 would be indistinguishable from a working gate.
    (statesDir / "boot-state").write_text('{"healthy":true}', encoding="utf-8")

    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=[str(_SPLASH_KIT), str(_DASHBOARD_KIT)],
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


class TestLauncherRouteContract:
    """Every launcher URL must be a route the real server actually serves."""

    @pytest.mark.parametrize("unitPath", _LAUNCHER_UNITS, ids=lambda p: p.name)
    def test_launcherUrl_againstRealServer_returns200(self, realKitServer, unitPath):
        """
        Given: the URL a real kiosk unit hands chromium
        When: it is requested from the real state server over the real kits
        Then: it returns 200 (never the 401 state-file fall-through of I-042)
        """
        path = _launcherUrlPath(unitPath)

        status = _status(realKitServer, path)

        assert status == 200, (
            f"{unitPath.name} launches chromium at {path!r}, which the state "
            f"server answers {status}. A kiosk cannot render a non-200 -- this "
            f"is the I-042 bare-route class."
        )

    @pytest.mark.parametrize("unitPath", _LAUNCHER_UNITS, ids=lambda p: p.name)
    def test_launcherUrl_servedHtml_hasTokenSubstituted(self, realKitServer, unitPath):
        """
        Given: a launcher URL that resolves to an HTML page
        When: it is served
        Then: the token is injected same-origin and no placeholder survives

        AC6 wants proof the launcher's routes "return 200 with the token". A 200
        carrying an un-substituted `__SPLASH_TOKEN__` would render, then every
        state poll would 401 -- a blank/degraded splash with a green status code.
        """
        path = _launcherUrlPath(unitPath)

        body = _get(realKitServer, path).read().decode("utf-8")

        assert "__SPLASH_TOKEN__" not in body, (
            f"{unitPath.name}: {path!r} served an un-substituted token "
            f"placeholder -- the page loads but every state poll will 401."
        )
        assert _TOKEN in body, f"{unitPath.name}: {path!r} served no injected token"

    def test_bootSplashAndGrace_requestDistinctServedPages(self):
        """
        Given: the boot and grace launchers
        When: their URLs are compared
        Then: they are different pages (the boot splash is not the reverse splash)

        Cheap but load-bearing: both units are near-identical, so a copy-paste
        that pointed grace at `/` would show the FORWARD splash on shutdown and
        every 200/token assertion above would still pass.
        """
        boot = _launcherUrlPath(_SPLASH_KIT / "splash-boot.service.x11")
        grace = _launcherUrlPath(_SPLASH_KIT / "splash-grace.service.x11")

        assert boot == "/", f"boot splash should own `/`, requests {boot!r}"
        assert grace == "/shutdown.html", f"grace requests {grace!r}"
        assert boot != grace

    def test_bothSessionVariants_requestTheSameRoute(self):
        """
        Given: the x11 and wayland variant of each launcher
        When: their URLs are compared
        Then: they match

        install.sh picks ONE variant by detected session type, so a URL fixed in
        only one variant is a latent defect on the other session -- invisible
        until the Pi's session type changes.
        """
        for stem in (
            _SPLASH_KIT / "splash-boot.service",
            _SPLASH_KIT / "splash-grace.service",
            _DASHBOARD_KIT / "dashboard.service",
        ):
            x11 = _launcherUrlPath(Path(f"{stem}.x11"))
            wayland = _launcherUrlPath(Path(f"{stem}.wayland"))
            assert x11 == wayland, (
                f"{stem.name}: x11 requests {x11!r} but wayland requests "
                f"{wayland!r} -- one session type would get a different page"
            )


class TestTokenGateStillClosed:
    """AC5: the fix must not weaken _tokenOk. Bare routes stay 401."""

    @pytest.mark.parametrize("route", _BARE_ROUTES_STAY_GATED)
    def test_bareRoute_withoutToken_stillReturns401(self, realKitServer, route):
        """
        Given: a bare route I-042 flagged as a 401 "anomaly"
        When: it is requested with no token
        Then: it is STILL 401 -- by design, not a regression to repair

        This test exists to stop a well-meaning future fix from making these
        routes public to "resolve I-042". Nothing requests them; opening them
        re-opens TD-067 and is an Atlas BLOCK.
        """
        assert _status(realKitServer, route) == 401

    def test_noLauncher_requestsABareGatedRoute(self):
        """
        Given: every kiosk launcher unit
        When: its URL is compared against the known-gated bare routes
        Then: none of them request one

        This is the assertion that actually closes I-042's lead: the 401s are
        real, and irrelevant, because no launcher ever asks for those paths.
        """
        requested = {_launcherUrlPath(u) for u in _LAUNCHER_UNITS}

        overlap = requested & set(_BARE_ROUTES_STAY_GATED)

        assert not overlap, (
            f"launcher(s) request token-gated bare route(s) {sorted(overlap)} -- "
            f"a kiosk pointed at one of these renders a 401 JSON body"
        )

    def test_stateFile_withToken_returns200(self, realKitServer):
        """
        Given: a real state file and the correct token
        When: it is fetched the way the splash JS fetches it
        Then: 200 -- proving the 401s above are the GATE, not a broken route
        """
        assert _status(realKitServer, "/boot-state", token=_TOKEN) == 200
        assert _status(realKitServer, "/boot-state") == 401


class TestGuardSelfTest:
    """The parser must not be satisfiable by a comment (US-513 lesson)."""

    def test_urlInCommentOnly_isNotAcceptedAsTheLauncherUrl(self, tmp_path):
        """
        Given: a unit whose only 9899 URL is inside a `#` comment
        When: the launcher URL is parsed
        Then: it raises -- a comment can never satisfy this guard
        """
        unit = tmp_path / "commented.service"
        unit.write_text(
            "# Token SSOT: chromium loads http://127.0.0.1:9899/ same-origin\n"
            "[Service]\nExecStart=/usr/bin/chromium --kiosk\n",
            encoding="utf-8",
        )

        with pytest.raises(AssertionError, match="no localhost:9899 URL"):
            _launcherUrlPath(unit)

    def test_bareRouteUnit_isRejectedByTheParser(self, tmp_path):
        """
        Given: a unit pointing chromium at the bare `/shutdown` route
        When: its URL is parsed
        Then: the parser reports `/shutdown` (so the 200 assertion can fail)

        Proves the guard READS the ExecStart rather than trusting the filename --
        i.e. that repointing a real unit at a bare route would actually turn the
        contract test red.
        """
        unit = tmp_path / "bare.service"
        unit.write_text(
            "[Service]\nExecStart=/usr/bin/chromium --kiosk \\\n"
            "  http://127.0.0.1:9899/shutdown\n",
            encoding="utf-8",
        )

        assert _launcherUrlPath(unit) == "/shutdown"
