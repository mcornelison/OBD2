################################################################################
# File Name: test_stale_bytecode_purge.py
# Purpose/Description: US-553 AC#1 -- deploy-pi.sh and deploy-server.sh must
#                      CLEAR stale __pycache__/*.pyc on the target after the
#                      code sync, so a fixed .py can never be masked by old
#                      bytecode. Hardening against the 2026-08-11 P0
#                      (obd-server crash-loop, ModuleNotFoundError: No module
#                      named 'common'), where the first redeploy of the fix
#                      still came up on the old code.
#
#                      These tests EXECUTE the real purge functions extracted
#                      from the deploy scripts against a fake target tree --
#                      a grep for the word "find" would pass on a purge that
#                      deletes nothing. The ghost-module test additionally
#                      proves the hazard itself: a bare .pyc with no source is
#                      importable BEFORE the purge and gone AFTER it.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-28    | Rex (US-553) | Initial -- behavioural purge tests for both
#               |              | tiers, runtime-state scoping, ordering, and
#               |              | the --delete-excluded ban.
# ================================================================================
################################################################################

"""Behavioural tests for the US-553 stale-bytecode purge in both deploy scripts.

Why the excludes already in deploy-pi.sh are NOT this fix
--------------------------------------------------------
`--exclude=__pycache__/ --exclude=*.pyc` stop stale bytecode being SENT. They do
nothing about what is already on the target, and rsync PROTECTS excluded files
from `--delete` -- so orphaned bytecode accumulates on the Pi forever.

The two mechanisms that actually mask a fix (both measured, 2026-08-28):

1. GHOST MODULE -- a bare ``foo.pyc`` where ``foo.py`` used to be is importable
   with no source present; CPython still registers ``SourcelessFileLoader`` for
   ``.pyc`` on the path hooks. ``test_*_purgeKillsTheImportableGhostModule``
   pins this end-to-end.
2. (mtime, size) COLLISION -- ``__pycache__`` entries are validated against the
   source's ``(mtime, size)`` PAIR, not a hash. rsync ``-a`` and the tar
   fallback both preserve mtime, which is what makes this reachable via deploy.

An ordinary edit (new mtime, or a changed size) invalidates correctly, so the
folklore "a stale .pyc masks any fix" is false. These two cases are the real
ones, and they are what the purge exists to close.
"""

from __future__ import annotations

import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PI_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
SERVER_SCRIPT = REPO_ROOT / "deploy" / "deploy-server.sh"

PI_FUNC = "step_purge_stale_bytecode"
SERVER_FUNC = "purge_stale_bytecode"


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


bashOnly = pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")


def _functionText(script: Path, name: str) -> str:
    """Return the full bash source of `name() { ... }` from `script`.

    Extracting the REAL function (rather than re-typing the payload into the
    test) is the point: a test that runs its own copy proves nothing about the
    script that ships.
    """
    text = script.read_text(encoding="utf-8")
    start = text.find(f"{name}() {{")
    assert start > -1, f"{name} not found in {script.name}"
    rest = text[start:]
    close = rest.find("\n}\n")
    assert close > -1, f"could not find closing brace for {name} in {script.name}"
    return rest[: close + 2]


def _withoutComments(text: str) -> str:
    """Blank out whole-line bash comments, preserving line structure.

    Both of the checks below would otherwise be satisfied -- or defeated -- by
    prose. The scripts DOCUMENT `--delete-excluded` in order to ban it, and the
    deploy-server.sh header comment narrates "systemctl restart obd-server"
    hundreds of lines before the command actually runs. Match the code.
    """
    return "\n".join("" if ln.lstrip().startswith("#") else ln for ln in text.splitlines())


def _buildTargetTree(root: Path) -> None:
    """Create a fake deploy target: shipped Python + stale bytecode + runtime state."""
    (root / "src" / "pi" / "obdii" / "__pycache__").mkdir(parents=True)
    (root / "src" / "common" / "config" / "__pycache__").mkdir(parents=True)
    (root / "scripts" / "__pycache__").mkdir(parents=True)
    (root / "data").mkdir()
    (root / "logs").mkdir()
    (root / "exports").mkdir()

    # Shipped source -- must survive.
    (root / "src" / "common" / "config" / "secrets_loader.py").write_text("VALUE = 1\n")
    (root / "scripts" / "seed.py").write_text("VALUE = 1\n")

    # Stale bytecode -- must go.
    (root / "src" / "pi" / "obdii" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"stale")
    (root / "src" / "common" / "config" / "__pycache__" / "overlay.cpython-311.pyc").write_bytes(
        b"stale"
    )
    (root / "scripts" / "__pycache__" / "seed.cpython-311.pyc").write_bytes(b"stale")
    # Bare, sourceless .pyc -- the ghost-module vector.
    (root / "src" / "common" / "config" / "ghost.pyc").write_bytes(b"stale")

    # Runtime state the car/server owns -- must NOT be touched.
    (root / "data" / "drives.db").write_text("drive-history\n")
    (root / "logs" / "app.log").write_text("log\n")
    (root / "exports" / "run.csv").write_text("csv\n")
    (root / ".env").write_text("API_KEY=secret\n")
    (root / "config.local.json").write_text("{}\n")


def _runPiPurge(target: Path) -> subprocess.CompletedProcess:
    """Execute deploy-pi.sh's purge function with `remote` stubbed to run locally."""
    harness = "\n".join(
        [
            "set -e",
            f"PI_PATH='{target.as_posix()}'",
            # deploy-pi.sh routes every remote command through `remote`, which is
            # what makes --dry-run safe. Stub it to run locally.
            'remote() { bash -c "$1"; }',
            _functionText(PI_SCRIPT, PI_FUNC),
            PI_FUNC,
        ]
    )
    return subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=60
    )


def _runServerPurge(target: Path) -> subprocess.CompletedProcess:
    """Execute deploy-server.sh's purge function with `ssh` stubbed to run locally."""
    harness = "\n".join(
        [
            "set -e",
            f"PROJECT='{target.as_posix()}'",
            "HOST='fake@host'",
            # deploy-server.sh calls `ssh $HOST "<payload>"` -- $2 is the payload.
            'ssh() { bash -c "$2"; }',
            _functionText(SERVER_SCRIPT, SERVER_FUNC),
            SERVER_FUNC,
        ]
    )
    return subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=60
    )


PURGE_RUNNERS = [
    pytest.param(_runPiPurge, id="deploy-pi.sh"),
    pytest.param(_runServerPurge, id="deploy-server.sh"),
]


# ---------------------------------------------------------------------------
# AC#1 -- the purge actually removes stale bytecode on the target
# ---------------------------------------------------------------------------


@bashOnly
@pytest.mark.parametrize("runPurge", PURGE_RUNNERS)
def test_purgeRemovesStaleBytecodeUnderShippedPythonDirs(runPurge, tmp_path):
    """
    Given: a target carrying stale __pycache__ and a bare .pyc under src/ + scripts/
    When: the deploy script's purge runs
    Then: every stale bytecode path is gone and the .py sources survive
    """
    _buildTargetTree(tmp_path)
    result = runPurge(tmp_path)
    assert result.returncode == 0, f"purge failed: {result.stdout}\n{result.stderr}"

    survivors = sorted(p.name for p in tmp_path.rglob("*.pyc"))
    assert survivors == [], f"stale bytecode survived the purge: {survivors}"
    assert list(tmp_path.rglob("__pycache__")) == [], "a __pycache__ directory survived"

    # The fix itself must still be on the target.
    assert (tmp_path / "src" / "common" / "config" / "secrets_loader.py").exists()
    assert (tmp_path / "scripts" / "seed.py").exists()


@bashOnly
@pytest.mark.parametrize("runPurge", PURGE_RUNNERS)
def test_purgeKillsTheImportableGhostModule(runPurge, tmp_path):
    """
    Given: a bare .pyc on the target whose .py no longer exists anywhere
    When: the purge runs
    Then: the module is importable BEFORE and un-importable AFTER

    This is the hazard itself, not a proxy for it. rsync's `--delete` cannot
    reach this file (excluded files are protected from deletion), so without
    the purge the target keeps importing a module that left the repo.
    """
    pkg = tmp_path / "src" / "ghostpkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    source = pkg / "ghost.py"
    source.write_text("VALUE = 'DELETED_UPSTREAM'\n")
    py_compile.compile(str(source), cfile=str(pkg / "ghost.pyc"), doraise=True)
    source.unlink()
    shutil.rmtree(pkg / "__pycache__", ignore_errors=True)

    probe = [sys.executable, "-c", "import ghost; print(ghost.VALUE)"]
    before = subprocess.run(probe, cwd=pkg, capture_output=True, text=True, timeout=60)
    assert before.returncode == 0, (
        "PREMISE FAILED: a sourceless .pyc was expected to be importable. "
        "If CPython dropped SourcelessFileLoader this test needs revisiting.\n"
        f"{before.stdout}{before.stderr}"
    )
    assert "DELETED_UPSTREAM" in before.stdout

    assert runPurge(tmp_path).returncode == 0

    after = subprocess.run(probe, cwd=pkg, capture_output=True, text=True, timeout=60)
    assert after.returncode != 0, "the ghost module is STILL importable after the purge"
    assert "ModuleNotFoundError" in after.stderr


@bashOnly
@pytest.mark.parametrize("runPurge", PURGE_RUNNERS)
def test_purgeLeavesRuntimeStateUntouched(runPurge, tmp_path):
    """
    Given: a target carrying the drive history, logs, exports, .env and local config
    When: the purge runs
    Then: all of it survives byte-for-byte

    The scope fence matters more than the deletion. `--delete-excluded` would
    also clear the bytecode -- and take data/ with it, because the rsync
    whitelist ends in `--exclude=*`.
    """
    _buildTargetTree(tmp_path)
    assert runPurge(tmp_path).returncode == 0

    assert (tmp_path / "data" / "drives.db").read_text() == "drive-history\n"
    assert (tmp_path / "logs" / "app.log").read_text() == "log\n"
    assert (tmp_path / "exports" / "run.csv").read_text() == "csv\n"
    assert (tmp_path / ".env").read_text() == "API_KEY=secret\n"
    assert (tmp_path / "config.local.json").read_text() == "{}\n"


@bashOnly
@pytest.mark.parametrize("runPurge", PURGE_RUNNERS)
def test_purgeIsScopedAndSpareTheVenv(runPurge, tmp_path):
    """
    Given: bytecode OUTSIDE the shipped-Python dirs (a sibling venv, and data/)
    When: the purge runs
    Then: it is left alone -- the purge targets src/ and scripts/ only

    Both tiers keep the venv outside the project dir ($HOME/obd2-venv on the Pi,
    /home/<user>/obd2-server-venv on the server), so site-packages bytecode is
    never recompiled by a deploy. Pin that, or a future widening to the whole
    target silently adds minutes of import cost to every restart.
    """
    _buildTargetTree(tmp_path)
    # Sibling of the project dir, mirroring $HOME/obd2-venv and
    # /home/<user>/obd2-server-venv. tmp_path.parent is shared between the two
    # parametrised runs, so name it per-run.
    venvCache = (
        tmp_path.parent / f"obd2-venv-{tmp_path.name}" / "lib" / "site-packages" / "__pycache__"
    )
    venvCache.mkdir(parents=True)
    (venvCache / "numpy.cpython-311.pyc").write_bytes(b"dependency-bytecode")
    dataCache = tmp_path / "data" / "__pycache__"
    dataCache.mkdir()
    (dataCache / "cached.cpython-311.pyc").write_bytes(b"not-shipped-python")

    assert runPurge(tmp_path).returncode == 0

    assert (venvCache / "numpy.cpython-311.pyc").exists(), "the purge reached into the venv"
    assert (dataCache / "cached.cpython-311.pyc").exists(), "the purge escaped src/ + scripts/"


@bashOnly
@pytest.mark.parametrize("runPurge", PURGE_RUNNERS)
def test_purgeIsIdempotentAndToleratesAFreshTarget(runPurge, tmp_path):
    """
    Given: a target with no src/ or scripts/ at all (first --init deploy)
    When: the purge runs, then runs again on a populated-then-purged tree
    Then: it exits 0 every time and reports zero on the second pass

    `set -e` is on in both scripts, so a `find` against a missing directory
    would abort the whole deploy.
    """
    fresh = runPurge(tmp_path)
    assert fresh.returncode == 0, f"purge failed on a fresh target: {fresh.stderr}"

    _buildTargetTree(tmp_path)
    assert runPurge(tmp_path).returncode == 0
    second = runPurge(tmp_path)
    assert second.returncode == 0
    assert "purged: 0 path(s)" in second.stdout, (
        f"second pass should find nothing left to purge; got: {second.stdout!r}"
    )


@bashOnly
@pytest.mark.parametrize("runPurge", PURGE_RUNNERS)
def test_purgeReportsWhatItRemoved(runPurge, tmp_path):
    """
    Given: a target with a known number of stale bytecode paths
    When: the purge runs
    Then: it prints a non-zero count

    A silent purge is an unverifiable one -- the deploy log is the only place an
    operator can see that this step did anything.
    """
    _buildTargetTree(tmp_path)
    result = runPurge(tmp_path)
    assert "Stale bytecode purged:" in result.stdout
    assert "purged: 0 path(s)" not in result.stdout, (
        f"purge reported zero on a tree that had stale bytecode: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Ordering + safety (static assertions on the shipped scripts)
# ---------------------------------------------------------------------------


def test_deployPi_purgeRunsAfterSyncTreeAndBeforeRestart():
    """The purge must follow the sync (or the sync re-orphans it) and precede
    the restart (or the interpreter has already loaded the stale bytecode)."""
    lines = [ln.strip() for ln in PI_SCRIPT.read_text(encoding="utf-8").splitlines()]
    syncIdx = [i for i, ln in enumerate(lines) if ln == "sync_tree"]
    purgeIdx = [i for i, ln in enumerate(lines) if ln == PI_FUNC]
    restartIdx = [i for i, ln in enumerate(lines) if ln == "step_restart_service"]

    assert syncIdx, "sync_tree is never called -- ordering guard cannot be evaluated"
    assert purgeIdx, f"{PI_FUNC} is never called in deploy-pi.sh"
    assert restartIdx, "step_restart_service is never called"

    assert purgeIdx[0] > syncIdx[0], (
        f"{PI_FUNC} (line {purgeIdx[0]}) must run AFTER sync_tree (line {syncIdx[0]}) "
        "-- purging first is undone by the sync"
    )
    assert purgeIdx[0] < restartIdx[-1], (
        f"{PI_FUNC} (line {purgeIdx[0]}) must run BEFORE step_restart_service "
        f"(line {restartIdx[-1]}) -- otherwise the service already loaded stale bytecode"
    )


def test_deployServer_purgeRunsAfterGitPullAndBeforeRestart():
    """Same ordering on the server, whose sync is `git pull` rather than rsync."""
    text = _withoutComments(SERVER_SCRIPT.read_text(encoding="utf-8"))
    pullIdx = text.find("git pull")
    callIdx = text.find(f"\n    {SERVER_FUNC}\n")
    restartIdx = text.find("systemctl restart obd-server")

    assert pullIdx > -1, "git pull not found in deploy-server.sh"
    assert callIdx > -1, f"{SERVER_FUNC} is never called in deploy-server.sh"
    assert restartIdx > -1, "the obd-server restart was not found"
    assert pullIdx < callIdx < restartIdx, (
        "the purge must sit between `git pull` and the service restart "
        f"(pull={pullIdx}, purge={callIdx}, restart={restartIdx})"
    )


def test_deployServer_purgeSkippedOnRestartOnly():
    """--restart ships no new code, so there is no stale bytecode to clear and
    no reason to pay for a recompile of the whole tree on restart."""
    text = SERVER_SCRIPT.read_text(encoding="utf-8")
    callIdx = text.find(f"\n    {SERVER_FUNC}\n")
    assert callIdx > -1
    guard = text.rfind('if [ "$RESTART_ONLY" = false ]; then', 0, callIdx)
    assert guard > -1, f"{SERVER_FUNC} is not guarded by a RESTART_ONLY check"
    # The guard must be the immediately-enclosing block, not an earlier one.
    assert "fi" not in text[guard:callIdx].split("then", 1)[1], (
        f"{SERVER_FUNC} is outside the RESTART_ONLY block that appears to guard it"
    )


def test_deployPi_purgeGoesThroughRemoteSoDryRunStaysSafe():
    """deploy-pi.sh routes every remote command through `remote`, which prints
    instead of executing under --dry-run. A bare `ssh` here would make
    --dry-run mutate the car."""
    body = _functionText(PI_SCRIPT, PI_FUNC)
    assert 'remote "' in body, f"{PI_FUNC} does not dispatch through remote()"
    assert "ssh " not in body, (
        f"{PI_FUNC} calls ssh directly -- that bypasses the --dry-run guard in remote()"
    )


@pytest.mark.parametrize("script", [PI_SCRIPT, SERVER_SCRIPT], ids=lambda p: p.name)
def test_deployScripts_neverUseDeleteExcluded(script):
    """`--delete-excluded` is the obvious one-flag "fix" and it is catastrophic
    here: deploy-pi.sh's whitelist ends in `--exclude=*`, so every
    non-whitelisted path on the Pi -- data/, logs/, exports/, .env,
    config.local.json -- becomes deletable. That is the car's drive history."""
    code = _withoutComments(script.read_text(encoding="utf-8"))
    assert "--delete-excluded" not in code, (
        f"{script.name} uses --delete-excluded; with `--exclude=*` in the whitelist "
        "this deletes the target's runtime state. Purge explicitly instead."
    )


@pytest.mark.parametrize(
    "script,name",
    [(PI_SCRIPT, PI_FUNC), (SERVER_SCRIPT, SERVER_FUNC)],
    ids=["deploy-pi.sh", "deploy-server.sh"],
)
def test_purgeFunctionClearsBothPycacheDirsAndBarePycFiles(script, name):
    """Guard-the-guard: the behavioural tests above run whatever this function
    contains, so pin that it still addresses BOTH shapes. Clearing only
    __pycache__/ leaves the bare-.pyc ghost-module vector wide open."""
    body = _functionText(script, name)
    assert "__pycache__" in body, f"{name} does not clear __pycache__ directories"
    assert "*.pyc" in body, f"{name} does not clear bare .pyc files"
    assert "/src" in body and "/scripts" in body, (
        f"{name} must cover both shipped-Python directories (src/ and scripts/)"
    )
