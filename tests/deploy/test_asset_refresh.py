################################################################################
# File Name: test_asset_refresh.py
# Purpose/Description: US-495 (S2, F-111) behavioural tests for the /opt asset
#   force-refresh guard (deploy/asset-refresh.sh). The Pi was rendering a
#   surface that no longer exists anywhere in the repo ("Eclipse ODB2" against a
#   repo that says "ECLIPSE OBD-II"), because the two asset steps only ever
#   installed ON TOP of /opt -- nothing was ever REMOVED. A file from a retired
#   kit generation therefore lives in /opt forever, and because the server
#   searches /opt/splash BEFORE /opt/dashboard, one stale copy in the first dir
#   silently shadows the real asset in the second no matter how many times the
#   deploy "succeeds".
#
#   These drive the REAL shell function that runs on the Pi -- deploy-pi.sh
#   sources this same library over the rsynced tree -- against temp dirs, rather
#   than grepping deploy-pi.sh for a magic string. `ASSET_SUDO=` runs it
#   unprivileged; everything else is the shipped code path.
#   Skipped when bash is not on PATH.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-495 /opt force-refresh guard.
# ================================================================================
################################################################################

"""US-495 behavioural tests for the deploy-side /opt stale-asset guard."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LIB = REPO_ROOT / "deploy" / "asset-refresh.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not on PATH")


def _run(tmpPath: Path, args: str, *, pathPrefix: str | None = None) -> subprocess.CompletedProcess:
    """Source the shipped library and invoke refresh_asset_dir with `args`.

    ASSET_SUDO is EXPORTED empty (not unset) so the library's `${ASSET_SUDO-sudo}`
    resolves to nothing -- the same code path, minus privilege escalation. It has
    to be a standalone `export`, not an `ASSET_SUDO= . lib` prefix: bash scopes a
    prefix assignment to that one command, so the later function call would not
    see it and would shell out to a sudo this box does not have.
    """
    prefix = f'export PATH="{pathPrefix}:$PATH"; ' if pathPrefix else ""
    script = f'{prefix}export ASSET_SUDO=; . "{LIB.as_posix()}"; refresh_asset_dir {args}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(tmpPath),
        timeout=60,
    )


@pytest.fixture()
def kit(tmp_path: Path) -> tuple[Path, Path]:
    """A source kit dir + an installed dir, both populated and out of date."""
    src = tmp_path / "src"
    dst = tmp_path / "opt"
    src.mkdir()
    dst.mkdir()
    (src / "index.html").write_text("ECLIPSE OBD-II\n", encoding="utf-8")
    (src / "styles.css").write_text("body{}\n", encoding="utf-8")
    (dst / "index.html").write_text("Eclipse ODB2\n", encoding="utf-8")
    return src, dst


def test_refreshAssetDir_overwritesTheStaleInstalledAsset(tmp_path, kit):
    """
    Given: /opt holds a previous generation of a manifest asset
    When: the refresh runs
    Then: the installed copy is byte-identical to the repo's

    The 'ODB2' -> 'OBD-II' proof from the story's validation criteria.
    """
    src, dst = kit
    result = _run(tmp_path, f'"{src.as_posix()}" "{dst.as_posix()}" "index.html styles.css"')
    assert result.returncode == 0, result.stderr
    assert (dst / "index.html").read_text(encoding="utf-8") == "ECLIPSE OBD-II\n"
    assert (dst / "styles.css").read_text(encoding="utf-8") == "body{}\n"


def test_refreshAssetDir_prunesAFileTheManifestDoesNotClaim(tmp_path, kit):
    """
    Given: a retired-generation file squatting in the installed dir
    When: the refresh runs
    Then: it is REMOVED, and the removal is reported

    This is the shadowing bug: /opt/splash is searched before /opt/dashboard, so
    one forgotten dashboard.html in /opt/splash serves forever and no amount of
    installing into /opt/dashboard can dislodge it.
    """
    src, dst = kit
    (dst / "dashboard.html").write_text("<!-- a retired generation -->\n", encoding="utf-8")
    result = _run(tmp_path, f'"{src.as_posix()}" "{dst.as_posix()}" "index.html styles.css"')
    assert result.returncode == 0, result.stderr
    assert not (dst / "dashboard.html").exists(), (
        "an unmanifested file must not survive a refresh -- it shadows the real asset"
    )
    assert "dashboard.html" in result.stdout, "a pruned asset must be reported, not silently deleted"


def test_refreshAssetDir_keepsTheFilesTheKeepListProtects(tmp_path, kit):
    """
    Given: files this step does not install but must not delete
    When: the refresh runs
    Then: they survive

    /opt/splash is written by TWO installers -- this step (3 served assets +
    version.txt) and the kit's own install.sh (the SVGs + the shutdown surface).
    Pruning to only what THIS step installs would delete the other installer's
    work mid-deploy and leave a broken splash if the kit step then skips.
    """
    src, dst = kit
    (dst / "version.txt").write_text("V0.29.20\n", encoding="utf-8")
    (dst / "splash.svg").write_text("<svg/>\n", encoding="utf-8")
    result = _run(
        tmp_path,
        f'"{src.as_posix()}" "{dst.as_posix()}" "index.html styles.css" "version.txt splash.svg"',
    )
    assert result.returncode == 0, result.stderr
    assert (dst / "version.txt").exists()
    assert (dst / "splash.svg").exists()


def test_refreshAssetDir_prunesAManifestAssetTheSourceCannotVouchFor(tmp_path, kit):
    """
    Given: a manifest asset that is MISSING from the source kit but stale in /opt
    When: the refresh runs
    Then: the unvouched copy is pruned rather than left serving

    Serving a file the repo no longer ships is the exact failure this story
    exists to kill. An honest 404 beats a confident stale render.
    """
    src, dst = kit
    (dst / "carousel.js").write_text("// last year's carousel\n", encoding="utf-8")
    result = _run(
        tmp_path, f'"{src.as_posix()}" "{dst.as_posix()}" "index.html styles.css carousel.js"'
    )
    assert result.returncode == 0, result.stderr
    assert not (dst / "carousel.js").exists()


def test_refreshAssetDir_absentSourceDirWarnsAndDoesNotBlock(tmp_path):
    """
    Given: no kit in the source tree at all
    Then: WARN on stderr, exit 0, and do not touch the installed dir (A-9)

    A Pi deploy without the UI kit must still ship the rest of the tier.
    """
    dst = tmp_path / "opt"
    dst.mkdir()
    (dst / "index.html").write_text("keep me\n", encoding="utf-8")
    result = _run(tmp_path, f'"{tmp_path.as_posix()}/nope" "{dst.as_posix()}" "index.html"')
    assert result.returncode == 0
    assert "WARN" in result.stderr
    assert (dst / "index.html").read_text(encoding="utf-8") == "keep me\n"


def test_refreshAssetDir_createsTheInstalledDirWhenAbsent(tmp_path, kit):
    """
    Given: /opt/<kit> does not exist yet (a first deploy)
    Then: it is created and populated
    """
    src, _ = kit
    dst = tmp_path / "fresh"
    result = _run(tmp_path, f'"{src.as_posix()}" "{dst.as_posix()}" "index.html"')
    assert result.returncode == 0, result.stderr
    assert (dst / "index.html").read_text(encoding="utf-8") == "ECLIPSE OBD-II\n"


def test_refreshAssetDir_failsLoudWhenTheWriteDidNotTake(tmp_path, kit):
    """
    Given: the copy silently does not happen (read-only /opt, full disk, ...)
    When: the refresh verifies what it installed
    Then: it FAILS non-zero with the offending filename

    Without this, a deploy that wrote nothing still prints 'Deploy OK' and the
    operator debugs the UI instead of the deploy -- the A-16 lesson.
    `install` is shimmed to a no-op through PATH, so the production code path is
    unchanged; only the system tool underneath it is neutered.
    """
    src, dst = kit
    shim = tmp_path / "shim"
    shim.mkdir()
    stub = shim / "install"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    result = _run(
        tmp_path,
        f'"{src.as_posix()}" "{dst.as_posix()}" "index.html"',
        # Relative, because the subprocess runs with cwd=tmp_path: a Windows-style
        # `C:/...` entry is inert in a git-bash PATH and the shim would be skipped.
        pathPrefix="./shim",
    )
    assert result.returncode != 0, "a failed write must not be reported as a successful refresh"
    assert "index.html" in result.stderr
    assert "ERROR" in result.stderr


# --- the wiring --------------------------------------------------------------
# US-494's lesson, one story old: a correct routine nobody calls is worth
# nothing, and no test of the routine can tell you it is not called. These
# assert on deploy-pi.sh's actual step bodies.


@pytest.mark.parametrize(
    "step, kitDir",
    [
        ("step_install_splash_assets", "splash-pi"),
        ("step_install_dashboard_assets", "dashboard-pi"),
    ],
)
def test_deployPiSh_assetStep_callsTheRefreshGuard(step, kitDir):
    """
    Given: the two Pi asset-install steps
    Then: each sources the guard library and calls refresh_asset_dir

    Pinning both the source path and the call: a step that sources the library
    and then hand-rolls its own install loop is the bug all over again.
    """
    from tests.deploy.test_deploy_pi import _scriptText, _stepBody

    body = _stepBody(_scriptText(), step)
    assert "deploy/asset-refresh.sh" in body, f"{step} must source the refresh guard library"
    assert "refresh_asset_dir" in body, f"{step} must delegate the install to refresh_asset_dir"
    assert kitDir in body, f"{step} must refresh from the {kitDir} kit"


@pytest.fixture(scope="module")
def splashRefreshArgs() -> tuple[set[str], set[str]]:
    """The manifest + keep-list the splash step ACTUALLY passes, from a dry run.

    Drives the shipped `deploy-pi.sh --dry-run` (offline, no SSH) and reads the
    resolved arguments off its own preview line, rather than re-implementing the
    step's variable expansion in the test. What the deploy says it would do is
    the thing under test.
    """
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "deploy" / "deploy-pi.sh"), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(
        r"refresh_asset_dir \S*splash-pi \S+ '([^']*)' '([^']*)'", result.stdout
    )
    assert match, "no splash refresh_asset_dir preview in the dry-run output"
    return set(match.group(1).split()), set(match.group(2).split())


SHUTDOWN_SURFACE = ("shutdown.html", "shutdown-state-poll.js", "splash-shutdown.svg")


def test_deployPiSh_splashStep_forceRefreshesTheShutdownSurface(splashRefreshArgs):
    """
    Given: US-495 gave /opt/splash a prune-and-verify refresh
    Then: the CLOSEOUT surface is in the manifest, not parked on the keep-list

    US-498. A keep-listed asset is never installed, never pruned and never
    byte-verified by the deploy -- it is refreshed only as a side effect of the
    kit's own install.sh, which is the A-9 step allowed to WARN and skip. So the
    exact failure US-495 fixed for the boot surface was still live for the
    shutdown one: the deploy can report success over a shutdown.html from a
    retired generation and never touch it. The operator only finds out during a
    shutdown, when there is no one watching and no way to re-run it.
    """
    manifest, keep = splashRefreshArgs
    for asset in SHUTDOWN_SURFACE:
        assert asset in manifest, f"{asset} is not force-refreshed by the deploy"
        assert asset not in keep, f"{asset} is keep-listed -- it will never be verified"


def test_deployPiSh_splashStep_accountsForEveryAssetTheKitShips(splashRefreshArgs):
    """
    Given: /opt/splash is written by TWO installers (deploy + the kit's install.sh)
    Then: every asset install.sh ships is either refreshed here or keep-listed

    The two-installer hazard cuts both ways and this pins both edges at once: an
    asset in NEITHER list is pruned mid-deploy (a Pi with no splash), and an
    asset the deploy does not own is never verified. Data-driven from install.sh
    so a new asset added to the kit lands in this test the day it is added.
    """
    installSh = (REPO_ROOT / "specs" / "UI" / "dist" / "splash-pi" / "install.sh").read_text(
        encoding="utf-8"
    )
    loop = re.search(r"for asset in (.*?); do", installSh, flags=re.DOTALL)
    assert loop, "could not find the asset loop in the splash kit's install.sh"
    kitAssets = loop.group(1).replace("\\\n", " ").split()

    manifest, keep = splashRefreshArgs
    for asset in kitAssets:
        assert asset in manifest or asset in keep, (
            f"{asset} is shipped by install.sh but the deploy refresh neither owns "
            "nor keeps it -- it gets PRUNED mid-deploy"
        )


def test_deployPiSh_splashStep_keepListsOnlyWhatItCannotOwn(splashRefreshArgs):
    """
    Given: the keep-list suppresses both the prune AND the byte-verify
    Then: nothing sits on it but version.txt, which the deploy writes itself

    A keep-list entry is an asset the guard cannot vouch for, so it is a cost,
    not a safety net -- the smaller it is, the more of /opt/splash the deploy
    actually verifies. version.txt earns its place: it is generated from
    deploy/RELEASE_VERSION after the refresh, not copied from the kit.
    """
    _, keep = splashRefreshArgs
    assert keep == {"version.txt"}, f"unexpected unverified assets in /opt/splash: {keep}"


def test_assetRefreshLibrary_isShippedToThePi():
    """
    Given: the remote step sources the library from the rsynced tree
    Then: the library is a real file at the path deploy-pi.sh names

    sync_tree copies the whole repo, so this holds as long as the file exists
    where the step points -- which is exactly what this asserts.
    """
    assert LIB.is_file(), f"missing {LIB}"
    from tests.deploy.test_deploy_pi import _scriptText

    assert "deploy/asset-refresh.sh" in _scriptText()
