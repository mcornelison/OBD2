################################################################################
# File Name: test_version_chip_deployed_chain.py
# Purpose/Description: US-634 -- RECORD THE PASS for the dashboard header version
#   chip. Atlas observed V0.29.31 on the panel (punch list H5): a real build, not
#   the "V?.?.?" sentinel. US-501 already pins the two ENDS of that chain -- the
#   markup carries __DEPLOY_VERSION__ (tests/ui/test_dashboard_version_chip.py)
#   and the server substitutes it from a .deploy-version handed in as an ABSOLUTE
#   path (tests/pi/splash/test_states_http_deploy_version.py). What NOTHING pinned
#   is the link that actually makes it true ON THE PI: the unit file passes no
#   --deploy-version-path at all, so the chip depends on the argparse default
#   ".deploy-version" resolving against WorkingDirectory, which must therefore
#   equal the PI_PATH where deploy-pi.sh stamps the file. That is a three-way
#   agreement across three files, and every existing test hands the server an
#   absolute path, which is precisely the resolution this chain does NOT use.
#   Break any one of the three and the chip degrades to the sentinel forever --
#   honestly, but silently, and the observed pass would be gone with nothing red.
#   This file pins the whole chain: RELEASE_VERSION -> composeReleaseRecord ->
#   .deploy-version -> WorkingDirectory-relative read -> the REAL dashboard.html
#   served by the REAL server, plus the negative case through that same real kit.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-634 verify/record the version chip.
# ================================================================================
################################################################################

"""US-634 tests recording that the version chip renders the DEPLOYED build."""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from pi.splash.states_http_server import StatesHttpServer, main

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEPLOY_DIR = _REPO_ROOT / "deploy"
_DASHBOARD_DIR = _REPO_ROOT / "src" / "pi" / "ui" / "dashboard"
_UNIT_PATH = _DEPLOY_DIR / "eclipse-states-http.service"
_DEPLOY_SH = _DEPLOY_DIR / "deploy-pi.sh"
_ADDRESSES_SH = _DEPLOY_DIR / "addresses.sh"
_RELEASE_VERSION = _DEPLOY_DIR / "RELEASE_VERSION"
_HELPERS_PATH = _REPO_ROOT / "scripts" / "version_helpers.py"

# The record filename deploy-pi.sh stamps, as a bare relative name. This is the
# string the argparse default carries; it is load-bearing, not cosmetic.
_RECORD_NAME = ".deploy-version"

# The honest "the build could not be read" sentinel.
_SENTINEL = "V?.?.?"

_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _loadHelpers():
    """Import scripts/version_helpers.py by path (it is not a package module)."""
    spec = spec_from_file_location("versionHelpersUs634", _HELPERS_PATH)
    assert spec and spec.loader, f"cannot import {_HELPERS_PATH}"
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _execStart() -> str:
    """The unit's ExecStart line, with systemd line continuations folded."""
    unit = _read(_UNIT_PATH).replace("\\\n", " ")
    for line in unit.splitlines():
        if line.startswith("ExecStart="):
            return line[len("ExecStart=") :]
    raise AssertionError("eclipse-states-http.service has no ExecStart")


def _unitDirective(name: str) -> str | None:
    for line in _read(_UNIT_PATH).splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{name}="):
            return stripped.split("=", 1)[1].strip()
    return None


def _addressDefault(name: str) -> str | None:
    """The committed default for a deploy address (B-044 SSOT, addresses.sh).

    Shape is `NAME="${NAME:-value}"`. deploy.conf can override it per operator,
    but deploy.conf is gitignored -- addresses.sh is the value the repo ships and
    the only one a test may bind to.
    """
    escaped = re.escape(name)
    match = re.search(
        r"^" + escaped + r'="\$\{' + escaped + r':-([^}]*)\}"',
        _read(_ADDRESSES_SH),
        re.MULTILINE,
    )
    return match.group(1) if match else None


def _chipText(body: str) -> str:
    """What the header chip actually paints in a served response."""
    match = re.search(r'<span id="version-chip">(.*?)</span>', body, re.DOTALL)
    assert match is not None, "the served dashboard lost its #version-chip span"
    return match.group(1).strip()


@pytest.fixture()
def realDashboard(tmp_path):
    """A running server over the SHIPPED dashboard kit.

    Yields a `start(deployVersionPath) -> fetch()` factory. The states dir is
    resolved to an absolute path up front so a test that chdir's to exercise the
    relative version path does not also move the states dir out from under the
    server.
    """
    statesDir = (tmp_path / "states").resolve()
    statesDir.mkdir()

    servers: list = []

    def start(deployVersionPath: str | None):
        server = StatesHttpServer(
            statesDir=str(statesDir),
            token=_TOKEN,
            host="127.0.0.1",
            port=0,
            assetsDir=str(_DASHBOARD_DIR),
            deployVersionPath=deployVersionPath,
        )
        thread = threading.Thread(target=server.serveForever, daemon=True)
        thread.start()
        servers.append((server, thread))

        def fetch() -> str:
            url = f"http://127.0.0.1:{server.actualPort}/dashboard.html"
            return urllib.request.urlopen(url, timeout=5).read().decode("utf-8")

        return fetch

    try:
        yield start
    finally:
        for server, thread in servers:
            server.shutdown()
            thread.join(timeout=5)


# ---------------------------------------------------------------------------
# The DEPLOYED wiring -- the link no existing test covers
# ---------------------------------------------------------------------------


def test_deployedRecord_landsWhereTheServerActuallyLooksForIt():
    """
    Given: deploy-pi.sh stamps ${PI_PATH}/.deploy-version and the unit runs the
           states server with some (or no) --deploy-version-path
    When: the two are compared
    Then: the path the server reads resolves to the file the deploy writes

    THE load-bearing assertion of this story. Atlas saw a real build on the
    panel only because the unit passes NO --deploy-version-path, so the argparse
    default (a bare relative name) resolves against WorkingDirectory, which
    happens to equal PI_PATH. That is agreement across three separate files with
    nothing holding it together. Written as a disjunction so either wiring is
    legal -- an explicit absolute argument would be an improvement, not a
    regression -- but the silent third option (relative default + a
    WorkingDirectory that is not PI_PATH) fails here instead of on the car.

    RECORDED, not asserted: the deploy takes PI_PATH from a variable while the
    unit hardcodes WorkingDirectory, so an operator who overrides PI_PATH in the
    (gitignored) deploy.conf moves the stamp WITHOUT moving the reader, and the
    chip falls to the sentinel on that operator's Pi only. Binding this test to
    a gitignored file would make the suite env-dependent, so the committed
    addresses.sh default is what is pinned here.
    """
    piPath = _addressDefault("PI_PATH")
    assert piPath, "deploy/addresses.sh must define the PI_PATH default (B-044)"
    assert "${PI_PATH}/.deploy-version" in _read(_DEPLOY_SH), (
        "deploy-pi.sh must stamp the record under PI_PATH"
    )

    explicit = re.search(r"--deploy-version-path[= ](\S+)", _execStart())
    if explicit is not None:
        resolved = explicit.group(1)
        assert os.path.isabs(resolved), (
            "an explicit --deploy-version-path in the unit must be absolute: a "
            "relative one silently re-introduces the WorkingDirectory coupling "
            "while LOOKING explicit"
        )
        assert resolved == f"{piPath}/.deploy-version"
    else:
        workingDir = _unitDirective("WorkingDirectory")
        assert workingDir == piPath, (
            "the unit passes no --deploy-version-path, so the server reads "
            f"'{_RECORD_NAME}' relative to WorkingDirectory ({workingDir}); "
            f"deploy-pi.sh stamps it under PI_PATH ({piPath}). They must be the "
            "same directory or the chip degrades to the sentinel forever"
        )


def test_cliWithNoFlag_handsTheServerTheBareNameDeployStamps(tmp_path, monkeypatch):
    """
    Given: the states server started exactly as the unit starts it -- with no
           --deploy-version-path argument
    When: main() constructs the server
    Then: it is handed '.deploy-version', the bare name deploy-pi.sh stamps

    Asserted on what main() PASSES rather than on the argparse default, because
    a default that never reaches StatesHttpServer buys nothing. The server class
    is stubbed so nothing binds a port.
    """
    captured: dict = {}

    class _CapturingServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def serveForever(self) -> None:
            return None

    monkeypatch.setattr(
        "pi.splash.states_http_server.StatesHttpServer", _CapturingServer
    )
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "--states-dir",
                str(tmp_path / "states"),
                "--token-path",
                str(tmp_path / "states" / ".http-token"),
                "--assets-dir",
                str(_DASHBOARD_DIR),
            ]
        )
        == 0
    )
    assert captured["deployVersionPath"] == _RECORD_NAME


def test_relativeRecordPath_resolvesAgainstTheWorkingDirectory(
    realDashboard, tmp_path, monkeypatch
):
    """
    Given: a .deploy-version in the process CWD, addressed by its BARE name
    When: the real dashboard is served
    Then: the chip carries that build

    This is the production resolution and the one every other test skips: they
    all hand the server an absolute path, which cannot detect a relative default
    that never resolves.
    """
    workingDir = tmp_path / "Eclipse-01"
    workingDir.mkdir()
    (workingDir / _RECORD_NAME).write_text(
        json.dumps({"version": "V0.29.31", "gitHash": "a0d549d"}), encoding="utf-8"
    )
    monkeypatch.chdir(workingDir)
    assert _chipText(realDashboard(_RECORD_NAME)()) == "V0.29.31"


# ---------------------------------------------------------------------------
# The SSOT end to end -- RELEASE_VERSION is what lands in the chip
# ---------------------------------------------------------------------------


def test_realComposedRecord_rendersItsVersionInTheRealChip(realDashboard, tmp_path):
    """
    Given: a .deploy-version composed by the REAL deploy composer from the REAL
           deploy/RELEASE_VERSION
    When: the shipped dashboard is served by the shipped server
    Then: the chip carries exactly the release version, and nothing else

    The writer and the reader are pinned against each other here rather than
    each against a hand-written record. Two independently-green half-tests do
    not prove the key names agree (the US-494/US-499 lesson); a composer that
    renamed `version` would pass its own tests and blank the panel chip.
    """
    helpers = _loadHelpers()
    record = helpers.composeReleaseRecord(_RELEASE_VERSION, gitHash="a0d549d")
    expected = json.loads(_read(_RELEASE_VERSION))["version"]

    versionFile = tmp_path / _RECORD_NAME
    versionFile.write_text(json.dumps(record), encoding="utf-8")

    chip = _chipText(realDashboard(str(versionFile))())
    assert chip == expected
    assert chip != _SENTINEL


def test_reStampedRecord_replacesTheChipWithoutARestart(realDashboard, tmp_path):
    """
    Given: a server serving the real kit, started before the deploy re-stamps
    When: .deploy-version is rewritten with the NEW build and the page reloaded
    Then: the chip shows the new build and no trace of the old one

    deploy-pi.sh restarts this unit BEFORE it writes the stamp, so a value read
    at construction is a deploy behind by construction. "Never a stale build
    string" is this test.
    """
    versionFile = tmp_path / _RECORD_NAME
    versionFile.write_text(json.dumps({"version": "V0.29.30"}), encoding="utf-8")
    fetch = realDashboard(str(versionFile))
    assert _chipText(fetch()) == "V0.29.30"

    versionFile.write_text(json.dumps({"version": "V0.29.31"}), encoding="utf-8")
    body = fetch()
    assert _chipText(body) == "V0.29.31"
    assert "V0.29.30" not in body


# ---------------------------------------------------------------------------
# NEGATIVE CASE -- the sentinel, never a stale or invented build
# ---------------------------------------------------------------------------


def test_noRecordOnDisk_realChipRendersTheSentinel(realDashboard, tmp_path):
    """
    Given: no .deploy-version anywhere
    When: the shipped dashboard is served
    Then: the chip is exactly the sentinel -- not blank, not a version, and not
          the raw placeholder

    Through the REAL kit. The existing negative tests use a one-line synthetic
    index, so they cannot see a markup change that leaves the placeholder
    unsubstituted on the page that actually ships.
    """
    body = realDashboard(str(tmp_path / _RECORD_NAME))()
    assert _chipText(body) == _SENTINEL
    assert "__DEPLOY_VERSION__" not in body


def test_noVersionSourceConfigured_realChipRendersTheSentinel(realDashboard):
    """
    Given: the server constructed with no version source at all
    When: the shipped dashboard is served
    Then: the chip is the sentinel, and the raw placeholder never reaches the panel
    """
    assert _chipText(realDashboard(None)()) == _SENTINEL


@pytest.mark.parametrize(
    "payload,label",
    [
        ("{not json at all", "malformed json"),
        (json.dumps({"gitHash": "a0d549d"}), "no version key"),
        (json.dumps({"version": "   "}), "blank version"),
        (json.dumps({"version": 29}), "non-string version"),
        (json.dumps(["V0.29.31"]), "not an object"),
    ],
)
def test_unreadableRecord_neverBecomesAPlausibleBuild(
    realDashboard, tmp_path, payload, label
):
    """
    Given: a .deploy-version that cannot honestly yield a version
    When: the shipped dashboard is served
    Then: the chip is the sentinel and carries no digits at all

    The digit assertion is the one with teeth: coercing a broken record (29 ->
    "29", ["V0.29.31"] -> the first element) is the obvious "helpful" fix, and a
    chip reading "29" is indistinguishable from a build number on a 3.5in panel.
    """
    versionFile = tmp_path / _RECORD_NAME
    versionFile.write_text(payload, encoding="utf-8")
    chip = _chipText(realDashboard(str(versionFile))())
    assert chip == _SENTINEL, f"{label} produced a chip reading {chip!r}"
    assert not re.search(r"\d", chip), f"{label} leaked digits into the chip"


def test_sentinel_cannotBeMistakenForABuild():
    """
    Given: the sentinel the server falls back to
    When: it is matched against the build-string shape
    Then: it does not match -- an unknown build must be unmistakable

    Guards the tempting "tidier" fallback (V0.0.0, V0.29.x, the last known
    version). Any of those reads as a real build on the panel, which is the
    exact class of lie this chip was fixed to stop telling.
    """
    assert re.fullmatch(r"V\d+\.\d+\.\d+", _SENTINEL) is None
    assert "?" in _SENTINEL
