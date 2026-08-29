"""
File: tests/deploy/test_verify_pi_imports.py
Purpose: Behavioural catalog + wiring guards for deploy/verify-pi-imports.sh,
         the US-573 / F-136 gate that proves every Pi runtime entry point
         actually IMPORTS on the target before any service is restarted.
Author: Rex (Ralph Agent 1)
Created: 2026-08-29
History:
  2026-08-29 - Created for US-573. Fixture systemd units + a fixture project
               tree exercise the script behind its PI_UNIT_DIR /
               PI_PROJECT_ROOT seams; separate guards pin the deploy wiring
               that the behavioural half cannot see.

WHY THIS IS A pytest FILE AND NOT A bash CATALOG (unlike its US-620 sibling).
The behaviour under test is Python IMPORT RESOLUTION under four different
invocation shapes, so every scenario needs a real package tree plus a real
interpreter. Building those in Python is direct; building them in bash would be
an elaborate way to reach the same place.

THE FIXTURE TREE MIRRORS THE REAL PI LAYOUT, and that is load-bearing. The Pi's
units disagree about how they are invoked -- MEASURED on the current unit files:

    eclipse-powerwatch.service    python -m src.pi.power.power_watch
    eclipse-states-http.service   python -m pi.splash.states_http_server
    eclipse-obd.service           python src/pi/main.py          (no PYTHONPATH)
    drain-forensics.service       python scripts/drain_forensics.py

Two module namespaces and two script paths. A verifier that imported everything
under one blanket PYTHONPATH could pass where the unit fails and fail where the
unit works, so the tests assert the script reproduces each unit's own
WorkingDirectory, PYTHONPATH and sys.path[0].
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "deploy" / "verify-pi-imports.sh"
DEPLOY_PI = REPO_ROOT / "deploy" / "deploy-pi.sh"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _python3Available() -> bool:
    """True if the script's driver interpreter (`python3`) is resolvable."""
    return shutil.which("python3") is not None


requiresShell = pytest.mark.skipif(
    not _bashAvailable() or not _python3Available(),
    reason="needs bash and python3 on PATH",
)


def _posix(path) -> str:
    """Render a path the way a real systemd unit carries it: forward slashes.

    Unit files are POSIX text, and the script lexes ExecStart with shlex in
    POSIX mode -- where a backslash is an ESCAPE, not a separator. Writing a
    native Windows path into a fixture unit would be silently mangled by the
    lexer, which is a property of the fixture, not of the script. Python on
    Windows accepts forward slashes everywhere, so the POSIX form is both
    faithful to the Pi and correct locally.

    Args:
        path: Path or string to normalise.

    Returns:
        The path with forward slashes.
    """
    return str(path).replace("\\", "/")


def _writeUnit(
    unitDir: Path,
    name: str,
    execStart: str,
    workingDir: str | None = None,
    pythonPath: str | None = None,
) -> None:
    """Write a minimal but structurally real systemd unit fixture.

    Args:
        unitDir: Directory to write the unit into.
        name: Unit filename, e.g. "eclipse-powerwatch.service".
        execStart: The ExecStart value, verbatim.
        workingDir: Optional WorkingDirectory.
        pythonPath: Optional PYTHONPATH, set via Environment=.
    """
    lines = ["[Unit]", "Description=fixture unit", "", "[Service]", "Type=simple"]
    if workingDir is not None:
        lines.append(f"WorkingDirectory={workingDir}")
    if pythonPath is not None:
        lines.append(f"Environment=PYTHONPATH={pythonPath}")
    lines.append("Environment=PYTHONUNBUFFERED=1")
    lines.append(f"ExecStart={execStart}")
    lines += ["", "[Install]", "WantedBy=multi-user.target", ""]
    (unitDir / name).write_text("\n".join(lines), encoding="utf-8")


def _buildProjectTree(root: Path) -> None:
    """Create a fixture tree with the same import shapes the Pi really uses.

    Args:
        root: Project root to populate.
    """
    for pkg in ("src", "src/pi", "src/pi/power", "src/pi/splash", "src/common"):
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    # Sibling import: reachable ONLY when sys.path[0] is src/pi, which is what
    # `python src/pi/main.py` produces and what `python -c` does NOT.
    (root / "src/pi/siblingHelper.py").write_text("SIBLING = 1\n", encoding="utf-8")

    # A main guard that would be a loud failure if the probe ran it.
    (root / "src/pi/main.py").write_text(
        "import siblingHelper\n"
        "VALUE = 'main-module-body'\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit('MAIN BLOCK RAN')\n",
        encoding="utf-8",
    )
    (root / "src/pi/power/power_watch.py").write_text(
        "import src.common\nVALUE = 'powerwatch'\n", encoding="utf-8"
    )
    (root / "src/pi/splash/states_http_server.py").write_text(
        "VALUE = 'states-http'\n", encoding="utf-8"
    )
    (root / "scripts/drain_forensics.py").write_text(
        "VALUE = 'drain'\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit('MAIN BLOCK RAN')\n",
        encoding="utf-8",
    )


def _runVerifier(unitDir: Path, projectRoot: Path | str = "") -> subprocess.CompletedProcess:
    """Run verify-pi-imports.sh against fixture units.

    Args:
        unitDir: Value for the PI_UNIT_DIR seam.
        projectRoot: Value for the PI_PROJECT_ROOT scope filter.

    Returns:
        The completed process, with stdout/stderr captured as text.
    """
    env = dict(os.environ)
    env["PI_UNIT_DIR"] = str(unitDir)
    env["PI_PROJECT_ROOT"] = str(projectRoot)
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )


@pytest.fixture()
def piLike(tmp_path: Path):
    """A fixture project tree plus a unit dir wired the way the real Pi is.

    Returns:
        Tuple of (projectRoot, unitDir).
    """
    root = tmp_path / "Eclipse-01"
    root.mkdir()
    _buildProjectTree(root)
    unitDir = tmp_path / "units"
    unitDir.mkdir()

    interpreter = _posix(sys.executable)
    twoPath = f"{_posix(root)}{os.pathsep}{_posix(root / 'src')}"
    _writeUnit(
        unitDir,
        "eclipse-powerwatch.service",
        f"{interpreter} -m src.pi.power.power_watch",
        workingDir=_posix(root),
        pythonPath=twoPath,
    )
    _writeUnit(
        unitDir,
        "eclipse-states-http.service",
        f"{interpreter} -m pi.splash.states_http_server --port 9899",
        workingDir=_posix(root),
        pythonPath=twoPath,
    )
    # The real eclipse-obd.service sets NO PYTHONPATH and uses the script form.
    _writeUnit(
        unitDir,
        "eclipse-obd.service",
        f"{interpreter} src/pi/main.py",
        workingDir=_posix(root),
    )
    _writeUnit(
        unitDir,
        "drain-forensics.service",
        f"{interpreter} scripts/drain_forensics.py",
        workingDir=_posix(root),
        pythonPath=_posix(root),
    )
    return root, unitDir


# ==============================================================================
# Behaviour: the happy path and the defect it exists to catch
# ==============================================================================


@requiresShell
def test_verifyPiImports_allEntryPointsResolve_exitsZero(piLike) -> None:
    """
    Given: units covering all four real invocation shapes, tree complete
    When: the verifier runs
    Then: it exits 0 and reports all four entry points
    """
    root, unitDir = piLike
    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"expected clean pass:\n{result.stdout}\n{result.stderr}"
    assert "Discovered 4 distinct Python entry point(s)" in result.stdout, result.stdout
    assert "All 4 Pi runtime entry point(s) import cleanly." in result.stdout, result.stdout


@requiresShell
def test_verifyPiImports_whitelistOmission_failsAndNamesTheModule(piLike) -> None:
    """
    Given: a module the whitelist failed to ship is ABSENT from the tree
    When: the verifier runs
    Then: it exits 1, names the entry point, and says it is a deploy-scope bug

    This is the US-573 AC-2 failure mode: a whitelist omission fails by
    SILENCE, so the gate has to be the thing that makes it loud.
    """
    root, unitDir = piLike
    (root / "src/pi/power/power_watch.py").unlink()

    result = _runVerifier(unitDir, root)
    assert result.returncode == 1, f"missing module must fail:\n{result.stdout}"
    assert "FAIL  -m src.pi.power.power_watch" in result.stdout, result.stdout
    assert "DEPLOY SCOPE bug" in result.stderr, result.stderr
    assert "Patch the WHITELIST" in result.stderr, result.stderr


@requiresShell
def test_verifyPiImports_transitiveDependencyMissing_fails(piLike) -> None:
    """
    Given: the entry point ships but something it imports does not
    When: the verifier runs
    Then: it exits 1

    This is the a94c88a8 lesson: a path list checks the names its author
    remembered; an import exercises the whole dependency graph.
    """
    root, unitDir = piLike
    shutil.rmtree(root / "src/common")

    result = _runVerifier(unitDir, root)
    assert result.returncode == 1, f"missing transitive dep must fail:\n{result.stdout}"
    assert "FAIL  -m src.pi.power.power_watch" in result.stdout, result.stdout


# ==============================================================================
# Behaviour: refusing to pass vacuously
# ==============================================================================


@requiresShell
def test_verifyPiImports_noEntryPointsDiscovered_failsLoudly(tmp_path: Path) -> None:
    """
    Given: a unit directory with no Python units in it
    When: the verifier runs
    Then: it exits 1 rather than reporting a clean pass

    THE MOST IMPORTANT GUARD IN THIS FILE. A verifier that finds nothing to
    verify and prints success is an inert guard -- present, green, and blind to
    the thing it was installed for.
    """
    unitDir = tmp_path / "units"
    unitDir.mkdir()
    _writeUnit(unitDir, "eclipse-rfkill-unblock.service", "/usr/sbin/rfkill unblock all")

    result = _runVerifier(unitDir, tmp_path)
    assert result.returncode == 1, f"empty verification must fail:\n{result.stdout}"
    assert "no Python entry points were discovered" in result.stderr, result.stderr
    assert "Refusing to report success" in result.stderr, result.stderr


@requiresShell
def test_verifyPiImports_missingUnitDir_failsLoudly(tmp_path: Path) -> None:
    """
    Given: PI_UNIT_DIR does not exist
    When: the verifier runs
    Then: it exits 1 and says nothing was verified
    """
    result = _runVerifier(tmp_path / "does-not-exist", tmp_path)
    assert result.returncode == 1
    assert "does not exist" in result.stderr, result.stderr


@requiresShell
def test_verifyPiImports_nonPythonUnitsIgnoredNotCounted(piLike) -> None:
    """
    Given: non-Python units alongside the Python ones
    When: the verifier runs
    Then: they are neither probed nor counted, and the run still passes

    /bin/true, rfkill and `/bin/sh -c` units are real entries in the Pi's unit
    dir. Treating one as a Python entry point would be a false failure.
    """
    root, unitDir = piLike
    _writeUnit(unitDir, "boot-progress-finalize.service", "/bin/true", workingDir=_posix(root))
    _writeUnit(unitDir, "eclipse-rfkill-unblock.service", "/usr/sbin/rfkill unblock all")
    _writeUnit(unitDir, "rfcomm-bind.service", "/bin/sh -c 'echo hi'", workingDir=_posix(root))

    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "Discovered 4 distinct Python entry point(s)" in result.stdout, result.stdout


# ==============================================================================
# Behaviour: fidelity to each unit's own import environment
# ==============================================================================


@requiresShell
def test_verifyPiImports_scriptFormUsesScriptDirAsSysPathZero(piLike) -> None:
    """
    Given: eclipse-obd.service runs `python src/pi/main.py` with NO PYTHONPATH,
           and main.py imports a SIBLING module
    When: the verifier runs
    Then: it passes

    A naive `python -c "import ..."` probe puts the CWD on sys.path[0], not the
    script's directory, so the sibling import would fail and the gate would
    report a defect that does not exist. Deleting the sibling must be the only
    thing that turns this red.
    """
    root, unitDir = piLike
    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"script-form fidelity broken:\n{result.stdout}\n{result.stderr}"
    assert "OK    src/pi/main.py" in result.stdout, result.stdout

    (root / "src/pi/siblingHelper.py").unlink()
    broken = _runVerifier(unitDir, root)
    assert broken.returncode == 1, "sibling removal must be detected"
    assert "FAIL  src/pi/main.py" in broken.stdout, broken.stdout


@requiresShell
def test_verifyPiImports_bothModuleNamespacesResolve(piLike) -> None:
    """
    Given: one unit uses `-m src.pi.*` and another `-m pi.*`
    When: the verifier runs
    Then: both import, because each is probed under its unit's own PYTHONPATH
    """
    root, unitDir = piLike
    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "OK    -m src.pi.power.power_watch" in result.stdout, result.stdout
    assert "OK    -m pi.splash.states_http_server" in result.stdout, result.stdout


@requiresShell
def test_verifyPiImports_doesNotRunTheMainBlock(piLike) -> None:
    """
    Given: entry points whose __main__ block raises SystemExit
    When: the verifier imports them
    Then: it still passes -- the guard block never ran

    The probe proves the module RESOLVES; it must not start the service.
    """
    root, unitDir = piLike
    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "MAIN BLOCK RAN" not in result.stdout, result.stdout
    assert "MAIN BLOCK RAN" not in result.stderr, result.stderr


@requiresShell
def test_verifyPiImports_parsesLineContinuationExecStart(piLike) -> None:
    """
    Given: an ExecStart split across lines with trailing backslashes
    When: the verifier runs
    Then: the entry point is still discovered

    eclipse-kiosk-watchdog.service really does this. Reading the unit
    line-by-line would truncate the ExecStart and silently miss the module --
    under-verification that looks exactly like success.
    """
    root, unitDir = piLike
    (unitDir / "eclipse-kiosk-watchdog.service").write_text(
        "[Unit]\nDescription=fixture\n\n[Service]\n"
        f"WorkingDirectory={_posix(root)}\n"
        f"Environment=PYTHONPATH={_posix(root)}{os.pathsep}{_posix(root / 'src')}\n"
        f"ExecStart={_posix(sys.executable)} -m pi.splash.states_http_server \\\n"
        "    --states-dir /run/eclipse-obd/states \\\n"
        "    --port 9899\n",
        encoding="utf-8",
    )
    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "eclipse-kiosk-watchdog.service" in result.stdout, result.stdout


@requiresShell
def test_verifyPiImports_outOfScopeUnitReportedNotSilentlyDropped(piLike, tmp_path) -> None:
    """
    Given: a Python unit whose WorkingDirectory is outside PI_PROJECT_ROOT
    When: the verifier runs
    Then: it is skipped but REPORTED by name

    A silent skip is how a real entry point goes unverified forever.
    """
    root, unitDir = piLike
    other = tmp_path / "SomeOtherProject"
    other.mkdir()
    _writeUnit(
        unitDir,
        "unrelated-thing.service",
        f"{_posix(sys.executable)} -m json.tool",
        workingDir=_posix(other),
    )

    result = _runVerifier(unitDir, root)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "unrelated-thing.service" in result.stdout, result.stdout
    assert "not verified" in result.stdout, result.stdout
    assert "Discovered 4 distinct Python entry point(s)" in result.stdout, result.stdout


# ==============================================================================
# Wiring guards -- the half the behavioural catalog cannot see
# ==============================================================================


def test_verifyPiImports_scriptExistsAndIsBash() -> None:
    """The production script exists and is a bash script."""
    assert SCRIPT.exists(), f"missing script: {SCRIPT}"
    firstLine = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert "bash" in firstLine, f"expected a bash shebang, got: {firstLine}"


def test_verifyPiImports_isShippedByThePiWhitelist() -> None:
    """The Pi rsync whitelist must actually carry this script to the target.

    THE WHITELIST IS THE POINT OF THE STORY, and it would be an unusually
    embarrassing bug for the whitelist-omission gate to be omitted by the
    whitelist. `--include=deploy/*.sh` is what ships it, and it only ships a
    `.sh` -- a `verify-pi-imports.py` would never arrive.
    """
    text = DEPLOY_PI.read_text(encoding="utf-8")
    assert SCRIPT.name.endswith(".sh"), "a non-.sh verifier would not be synced to the Pi"
    assert "--include=deploy/*.sh" in text, "deploy/*.sh include rule is gone; the script would not ship"
    assert f"--exclude=deploy/{SCRIPT.name}" not in text, "a later exclude rule cancels the include"

    # The tar fallback must ship the same tree; it sends ./deploy wholesale.
    assert f"--exclude=\"./deploy/{SCRIPT.name}\"" not in text, (
        "the tar fallback excludes the verifier, so which sync path ran would "
        "silently change whether the gate exists on the car"
    )


def test_verifyPiImports_stepIsDefinedAndCalledUngated() -> None:
    """deploy-pi.sh defines the step and calls it at column 0 (every deploy)."""
    lines = DEPLOY_PI.read_text(encoding="utf-8").splitlines()
    assert any(
        line.startswith("step_verify_pi_imports() {") for line in lines
    ), "step_verify_pi_imports is not defined at column 0"
    callSites = [
        index for index, line in enumerate(lines) if line == "step_verify_pi_imports"
    ]
    assert callSites, "step_verify_pi_imports is defined but never called"


def test_verifyPiImports_runsBeforeTheServiceRestart() -> None:
    """The gate must run BEFORE services are restarted, not after.

    Verifying after the restart would still report the fault, but only once the
    Pi had already been bounced into a crash loop -- and `set -e` ordering is
    also what keeps .deploy-version from being bumped on a Pi that cannot
    import its own code.
    """
    lines = DEPLOY_PI.read_text(encoding="utf-8").splitlines()
    verifyAt = [i for i, line in enumerate(lines) if line == "step_verify_pi_imports"]
    restartAt = [i for i, line in enumerate(lines) if line == "step_restart_service"]
    assert verifyAt and restartAt, "expected both call sites at column 0"
    assert min(verifyAt) < min(restartAt), (
        "step_verify_pi_imports must be called before step_restart_service"
    )


def test_verifyPiImports_runsAfterTheUnitInstalls() -> None:
    """The gate derives entry points from installed units, so it must follow them."""
    lines = DEPLOY_PI.read_text(encoding="utf-8").splitlines()
    verifyAt = min(i for i, line in enumerate(lines) if line == "step_verify_pi_imports")
    lastUnitInstall = max(
        i
        for i, line in enumerate(lines)
        if line.startswith("step_install_") and line.strip() == line
    )
    assert verifyAt > lastUnitInstall, (
        "step_verify_pi_imports runs before the last unit install, so it would "
        "derive its entry points from units that are not on the box yet"
    )


def test_verifyPiImports_hasADryRunBranch() -> None:
    """--dry-run must not ssh to the Pi, matching every sibling step."""
    text = DEPLOY_PI.read_text(encoding="utf-8")
    start = text.index("step_verify_pi_imports() {")
    body = text[start : text.index("\nstep_restart_service() {", start)]
    assert "$DRY_RUN" in body, "step_verify_pi_imports has no DRY-RUN branch"
    assert "DRY-RUN would" in body, "DRY-RUN branch does not say what it would do"


def test_verifyPiImports_passesProjectRootScope() -> None:
    """The deploy step must scope the scan to PI_PATH, not the whole box."""
    text = DEPLOY_PI.read_text(encoding="utf-8")
    start = text.index("step_verify_pi_imports() {")
    body = text[start : text.index("\nstep_restart_service() {", start)]
    assert "PI_PROJECT_ROOT" in body, "the step does not pass the project-root scope filter"
    assert "verify-pi-imports.sh" in body, "the step does not invoke the verifier"
