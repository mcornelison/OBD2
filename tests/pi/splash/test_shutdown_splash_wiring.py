################################################################################
# File Name: test_shutdown_splash_wiring.py
# Purpose/Description: US-498 (S5, F-103) end-to-end wiring tests for the
#   closeout (grace-period) shutdown splash. Every piece of this chain already
#   had unit tests and every piece passed; what nothing asserted was that the
#   pieces name the SAME THING:
#
#     ShutdownSequencer --phaseEmitFn--> shutdown_state_emitter
#        writes  <statesDir>/shutdown-state
#          -> splash-grace.path  PathExists=<that exact path>
#          -> splash-grace.service  loads http://127.0.0.1:9899/<entry>
#          -> eclipse-states-http serves <entry> from the kit + injects the token
#          -> shutdown-state-poll.js  fetches /<the same state name>
#
#   That is exactly the shape of the US-494 splash-handoff defect: a dependency
#   the entry point never passed, invisible to every test of the parts. So these
#   drive the REAL sequencer through a real grace transition into a real temp
#   states dir, then serve the REAL kit over the REAL http server and fetch the
#   URL taken out of the REAL unit file -- no string is asserted against a
#   literal that a rename could leave behind on both sides.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-498 closeout splash wiring.
# ================================================================================
################################################################################

"""US-498 end-to-end wiring tests for the F-103 closeout shutdown splash."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pi.power.power_watch.controller import ShutdownSequencer
from pi.splash.shutdown_state_emitter import (
    PHASE_GRACE,
    SHUTDOWN_STATE_FILENAME,
    makeShutdownPhaseEmitter,
)
from pi.splash.states_http_server import StatesHttpServer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
KIT_DIR = REPO_ROOT / "src" / "pi" / "ui" / "splash"
CONFIG_PATH = REPO_ROOT / "config.json"

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"

GRACE_UNITS = ("splash-grace.service.x11", "splash-grace.service.wayland")


def _kitFile(name: str) -> str:
    return (KIT_DIR / name).read_text(encoding="utf-8")


def _splashConfig() -> dict:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return config["pi"]["splash"]


def _graceEntryPath(unitName: str) -> str:
    """The URL path the grace unit actually hands chromium (e.g. /shutdown.html)."""
    match = re.search(r"http://127\.0\.0\.1:(\d+)(/\S*)", _kitFile(unitName))
    assert match, f"{unitName} does not launch a 127.0.0.1 URL"
    return match.group(2)


def _get(server: StatesHttpServer, path: str, token: str | None = None):
    request = urllib.request.Request(f"http://127.0.0.1:{server.actualPort}{path}")
    if token is not None:
        request.add_header("X-Splash-Token", token)
    return urllib.request.urlopen(request, timeout=5)


# ---------------------------------------------------------------------------
# Producer: a real grace transition writes the file the .path unit watches
# ---------------------------------------------------------------------------


@pytest.fixture()
def statesDir(tmp_path: Path) -> Path:
    directory = tmp_path / "states"
    directory.mkdir()
    return directory


def _runGrace(statesDir: Path) -> None:
    """Drive the REAL ShutdownSequencer through a grace transition.

    Power "returns" on the second read, so the sequencer emits grace and then
    cancels -- the shortest real path that exercises the emit hook without
    running a pipeline or a poweroff.
    """
    reads = iter([True, False, False, False])
    sequencer = ShutdownSequencer(
        isOnBattery=lambda: next(reads, False),
        vcell=lambda: 4.0,
        runPipelineFn=lambda: None,
        powerOffFn=lambda: pytest.fail("poweroff must not fire on a cancelled grace"),
        vcellFloor=3.45,
        totalCapSec=1.0,
        smoothingSec=1.0,
        smoothingPollSec=0.01,
        sleepFn=lambda _s: None,
        phaseEmitFn=makeShutdownPhaseEmitter(str(statesDir)),
    )
    sequencer.handleOnBattery()


def test_graceTransition_writesTheFileThePathUnitWatches(statesDir):
    """
    Given: a real power-lost signal reaching the real ShutdownSequencer
    When: the grace phase is emitted through the wired shutdown_state_emitter
    Then: the file that appears is the one splash-grace.path triggers on

    The trigger is a filesystem path agreed on by two modules that never import
    each other. This asserts the agreement against the SHIPPED unit + the
    SHIPPED config rather than against a literal repeated in the test.
    """
    _runGrace(statesDir)

    written = statesDir / SHUTDOWN_STATE_FILENAME
    assert written.is_file(), "the grace transition wrote no shutdown-state at all"

    watched = re.search(r"PathExists=(\S+)", _kitFile("splash-grace.path"))
    assert watched, "splash-grace.path declares no PathExists trigger"
    expected = f"{_splashConfig()['statesDir']}/{SHUTDOWN_STATE_FILENAME}"
    assert watched.group(1) == expected, (
        "splash-grace.path watches a path the emitter never writes: "
        f"{watched.group(1)} vs {expected}"
    )


def test_graceTransition_emitsGraceBeforeSmoothingResolves(statesDir):
    """
    Given: the splash animation IS the grace countdown
    Then: `grace` is on disk from the first emit, not after smoothing resolves

    If the file only appeared once smoothing confirmed, the .path unit would
    fire after the window it is meant to cover -- the operator would get a
    closeout splash for the tail of the shutdown, or none at all.
    """
    emitted = []
    sequencer = ShutdownSequencer(
        isOnBattery=lambda: True,
        vcell=lambda: 4.0,
        runPipelineFn=lambda: emitted.append(
            json.loads((statesDir / SHUTDOWN_STATE_FILENAME).read_text(encoding="utf-8"))
        ),
        powerOffFn=lambda: None,
        vcellFloor=3.45,
        totalCapSec=1.0,
        smoothingSec=0.0,
        smoothingPollSec=0.01,
        sleepFn=lambda _s: None,
        phaseEmitFn=makeShutdownPhaseEmitter(str(statesDir)),
    )
    sequencer._beginGraceAndEmit()

    state = json.loads((statesDir / SHUTDOWN_STATE_FILENAME).read_text(encoding="utf-8"))
    assert state["phase"] == PHASE_GRACE
    assert state["tGraceTotalS"] == 0.0
    assert state["tGraceStartedAt"], "the grace window has no start stamp to count from"


# ---------------------------------------------------------------------------
# Render: the real kit, served by the real server, at the unit's real URL
# ---------------------------------------------------------------------------


@pytest.fixture()
def shutdownServer(statesDir):
    """The real states server, serving the real splash kit + a live grace state."""
    _runGrace(statesDir)
    server = StatesHttpServer(
        statesDir=str(statesDir),
        token=_TOKEN,
        host="127.0.0.1",
        port=0,
        assetsDir=[str(KIT_DIR)],
    )
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    thread.join(timeout=5)


@pytest.mark.parametrize("unitName", GRACE_UNITS)
def test_graceUnitUrl_servesTheShutdownPage_tokenInjected(shutdownServer, unitName):
    """
    Given: the URL path baked into the shipped splash-grace unit
    When: chromium fetches it from the state server over the real kit
    Then: it is a 200 with the token substituted -- not a 404, not a placeholder

    Taking the path out of the unit is the point: a renamed asset breaks this
    even though both the unit and the kit would still "look right" in isolation.
    """
    response = _get(shutdownServer, _graceEntryPath(unitName))
    body = response.read().decode("utf-8")

    assert response.status == 200
    assert _TOKEN in body, "the closeout page was served without a usable token"
    assert "__SPLASH_TOKEN__" not in body


def test_shutdownPage_referencesLoadOverTheSameServer(shutdownServer):
    """
    Given: shutdown.html's own src/data references
    Then: every one of them resolves 200 over the same origin

    The D-1 class of bug (loading the boot SVG) is already pinned by the kit
    tests; this is the wider version -- whatever the page asks for, the server
    must actually have. A reference the deploy no longer ships is a blank frame
    in the middle of a shutdown.
    """
    html = _kitFile("shutdown.html")
    references = re.findall(r'(?:src|data|href)="([^":]+)"', html)
    assert references, "shutdown.html references no assets at all"

    for reference in references:
        response = _get(shutdownServer, f"/{reference}")
        assert response.status == 200, f"{reference} is referenced but not served"


def test_shutdownStateRoute_feedsThePollScript(shutdownServer):
    """
    Given: the route shutdown-state-poll.js fetches
    Then: it is token-gated and returns the state the sequencer just emitted

    Closes the loop: the phase the JS branches on is the phase the emitter
    wrote, over the route the JS names, through the server the unit points at.
    """
    route = re.search(r'fetch\("(/[\w-]+)"', _kitFile("shutdown-state-poll.js"))
    assert route, "shutdown-state-poll.js fetches no state route"
    assert route.group(1) == f"/{SHUTDOWN_STATE_FILENAME}"

    served = json.loads(_get(shutdownServer, route.group(1), token=_TOKEN).read())
    assert served["phase"] in ("grace", "cancelled", "flushing", "powering_off")
    assert served["ts"], "the served state carries no timestamp to age it against"


def test_shutdownStateRoute_isTokenGated(shutdownServer):
    """
    Given: the state feed is read-only but private (token SSOT, US-393)
    Then: an untokened fetch is 401 while the PAGE itself stays public

    The page must load before it can authenticate -- that asymmetry is the
    design, and inverting either half breaks the closeout (a gated page never
    renders; an ungated state feed leaks the shutdown timeline to any local
    process).
    """
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        _get(shutdownServer, f"/{SHUTDOWN_STATE_FILENAME}")
    assert excinfo.value.code == 401


# ---------------------------------------------------------------------------
# Deployment: the closeout surface has to actually be on the Pi
# ---------------------------------------------------------------------------


def test_closeoutSurface_isInstalledByTheDeploy():
    """
    Given: the kit files the closeout page needs at runtime
    Then: deploy/deploy-pi.sh installs each into /opt/splash

    US-498's deploy half. The render side cannot be trusted until the bytes it
    renders are the bytes the repo has -- the same lesson US-495 paid for on the
    boot surface. Asserted against the step body so a manifest edit that drops
    an asset fails here rather than on a Pi mid-shutdown.
    """
    from tests.deploy.test_deploy_pi import _scriptText, _stepBody

    body = _stepBody(_scriptText(), "step_install_splash_assets")
    manifest = re.search(r'local assets="([^"]*)"', body)
    assert manifest, "the splash step declares no asset manifest"
    installed = manifest.group(1).split()

    html = _kitFile("shutdown.html")
    needed = ["shutdown.html", *re.findall(r'(?:src|data)="([^":]+)"', html)]
    for asset in needed:
        assert asset in installed, (
            f"{asset} is needed to render the closeout but the deploy does not install it"
        )
