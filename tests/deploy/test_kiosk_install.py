################################################################################
# File Name: test_kiosk_install.py
# Purpose/Description: Deploy-smoke coverage for the F-103/F-092 chromium kiosk
#                      install path (US-428). Two concerns:
#                        (1) Bug-2 proper fix -- the kit installers' V-3 chromium
#                            binary check substitutes the real chromium path
#                            (chromium vs chromium-browser) into the unit
#                            ExecStart, like they substitute User= (V-1). No
#                            /usr/bin/chromium-browser symlink shim.
#                        (2) deploy-pi.sh step_install_ui_kiosk_units is exercised,
#                            session-detects seat0, and WARN-not-BLOCKs an absent
#                            kit (A-9).
#                      Runs fully off-Pi: the installers' FORCE_* overrides
#                      short-circuit every hardware probe, so --dry-run renders the
#                      resolved ExecStart on a plain workstation (no root, no Pi).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-02    | Rex (US-428) | Initial implementation (Sprint 52 V0.29.6):
#               |              | V-3 chromium-binary substitution + kiosk-step
#               |              | deploy-smoke assertions.
# ================================================================================
################################################################################

"""Deploy-smoke tests for the chromium kiosk install path (US-428).

Split into three groups:

* Unit-template parameterization -- the 6 kiosk unit variants must reference
  ``__CHROMIUM_BIN__`` (a substitution seam), never a hardcoded
  ``/usr/bin/chromium-browser`` (the Bug-2 203/EXEC trap on Trixie).
* Installer V-3 behaviour -- each kit ``install.sh`` --dry-run renders the
  resolved ExecStart with the detected/forced chromium path, and fails loudly
  when no chromium binary is found.
* deploy-pi.sh ``step_install_ui_kiosk_units`` -- no symlink shim, still
  session-detects seat0, WARN-not-BLOCKs an absent kit, and is wired into the
  main flow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SPLASH_INSTALL = REPO_ROOT / "src" / "pi" / "ui" / "splash" / "install.sh"
DASH_INSTALL = REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "install.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"

# The 6 chromium kiosk unit templates (both session variants of all three units).
UNIT_TEMPLATES = [
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "splash-boot.service.x11",
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "splash-boot.service.wayland",
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "splash-grace.service.x11",
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "splash-grace.service.wayland",
    REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "dashboard.service.x11",
    REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "dashboard.service.wayland",
]


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _stepBody(text: str, stepName: str) -> str:
    """Return the body of a bash function `step_<stepName>() { ... }`.

    Mirrors the helper in test_deploy_pi.py -- scopes a static assertion to a
    single routine so a global grep can't leak a match from a sibling step.
    """
    needle = f"{stepName}() {{"
    start = text.find(needle)
    assert start > -1, f"function {stepName} not found in deploy-pi.sh"
    rest = text[start:]
    closeIdx = rest.find("\n}\n")
    assert closeIdx > -1, f"could not find closing brace for {stepName}"
    return rest[: closeIdx + 2]


def _runInstaller(script: Path, kitEnvPrefix: str, *, chromium: str | None) -> subprocess.CompletedProcess:
    """Run a kit install.sh --dry-run off-Pi with all FORCE_* overrides set.

    Forcing user + uid + session + chromium short-circuits every hardware probe,
    so the installer reaches its V-3 render preview on a plain workstation. When
    `chromium` is None the FORCE_CHROMIUM var is set EMPTY (simulating "can't
    find a chromium binary") to exercise the fail-loud path.

    FORCE_UID is set here for the same reason FORCE_CHROMIUM is: US-550 added a
    V-4 probe that resolves the Pi user's numeric uid with `id -u` (I-044), and
    the forced user "pi" does not exist on a dev workstation, so the installer
    would abort on the uid before reaching anything this file asserts. The V-4
    fail-loud path itself is covered in test_kiosk_runtime_dir.py.
    """
    env = dict(os.environ)
    env[f"{kitEnvPrefix}_FORCE_USER"] = "pi"
    env[f"{kitEnvPrefix}_FORCE_UID"] = "1000"
    env[f"{kitEnvPrefix}_FORCE_SESSION"] = "x11"
    env[f"{kitEnvPrefix}_FORCE_CHROMIUM"] = "" if chromium is None else chromium
    return subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )


# ----------------------------------------------------------------------------
# Group 1: unit-template parameterization (Bug-2 seam)
# ----------------------------------------------------------------------------


def test_unitTemplates_parameterizeChromiumBinary():
    """Every kiosk unit template must reference __CHROMIUM_BIN__ and must NOT
    hardcode /usr/bin/chromium-browser -- the hardcoded path is the Bug-2
    203/EXEC trap on Raspberry Pi OS Trixie (ships /usr/bin/chromium).
    """
    for tpl in UNIT_TEMPLATES:
        assert tpl.is_file(), f"missing unit template {tpl}"
        text = tpl.read_text(encoding="utf-8")
        assert "ExecStart=__CHROMIUM_BIN__" in text, (
            f"{tpl.name} must parameterize the browser as ExecStart=__CHROMIUM_BIN__ "
            f"(substituted by the installer V-3 check), not hardcode a path"
        )
        assert "ExecStart=/usr/bin/chromium-browser" not in text, (
            f"{tpl.name} still hardcodes ExecStart=/usr/bin/chromium-browser -- "
            f"that dies 203/EXEC on Trixie (Bug 2). Use __CHROMIUM_BIN__."
        )


# ----------------------------------------------------------------------------
# Group 2: installer V-3 behaviour (dry-run, off-Pi)
# ----------------------------------------------------------------------------


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
@pytest.mark.parametrize(
    "script,prefix",
    [(SPLASH_INSTALL, "SPLASH"), (DASH_INSTALL, "DASHBOARD")],
)
def test_installer_v3SubstitutesForcedChromiumPath(script: Path, prefix: str):
    """--dry-run must render the resolved ExecStart with the forced chromium
    path substituted in -- proving the real sed substitution runs end-to-end on
    the real template (no __CHROMIUM_BIN__ placeholder, no chromium-browser
    fallback leaking through).
    """
    forced = "/opt/test/chromium"
    result = _runInstaller(script, prefix, chromium=forced)
    assert result.returncode == 0, f"dry-run should exit 0; stderr={result.stderr}"
    assert f"ExecStart={forced}" in result.stdout, (
        f"dry-run must render the resolved ExecStart with the forced chromium "
        f"path; got:\n{result.stdout}"
    )
    assert "__CHROMIUM_BIN__" not in result.stdout, (
        "the __CHROMIUM_BIN__ placeholder must be substituted, not printed raw"
    )
    assert "/usr/bin/chromium-browser" not in result.stdout, (
        "the resolved ExecStart must use the detected path, not the old hardcode"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
@pytest.mark.parametrize(
    "script,prefix",
    [(SPLASH_INSTALL, "SPLASH"), (DASH_INSTALL, "DASHBOARD")],
)
def test_installer_failsLoudWhenNoChromium(script: Path, prefix: str):
    """When no chromium binary can be found (forced empty), the installer must
    fail loudly (exit 1) rather than emit a unit that 203/EXECs -- mirroring the
    V-1/V-2 fail-loud discipline.
    """
    result = _runInstaller(script, prefix, chromium=None)
    assert result.returncode == 1, (
        f"missing chromium must abort with exit 1; got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "chromium" in combined, "the abort message must name the missing chromium binary"


@pytest.mark.parametrize(
    "script,var",
    [(SPLASH_INSTALL, "SPLASH_FORCE_CHROMIUM"), (DASH_INSTALL, "DASHBOARD_FORCE_CHROMIUM")],
)
def test_installer_installUnitSubstitutesChromiumBin(script: Path, var: str):
    """Static: the installer's install_unit must sed __CHROMIUM_BIN__ -> the
    resolved CHROMIUM_BIN (the same seam it uses for __PI_USER__), and expose a
    FORCE_CHROMIUM override for off-Pi testing.
    """
    text = script.read_text(encoding="utf-8")
    assert "__CHROMIUM_BIN__" in text, (
        f"{script.name} install_unit must substitute __CHROMIUM_BIN__"
    )
    assert "CHROMIUM_BIN" in text, f"{script.name} must resolve a CHROMIUM_BIN value"
    assert var in text, f"{script.name} must honour the {var} override (off-Pi testing)"


# ----------------------------------------------------------------------------
# Group 3: deploy-pi.sh step_install_ui_kiosk_units (US-428)
# ----------------------------------------------------------------------------


def test_deployStep_citesUs428():
    """The kiosk-install hardening must cite US-428 so archaeology can trace it."""
    assert "US-428" in DEPLOY_SCRIPT.read_text(encoding="utf-8"), (
        "deploy-pi.sh must cite US-428 on the kiosk-install V-3 hardening"
    )


def test_deployStep_noChromiumSymlinkShim():
    """Bug-2 proper fix: step_install_ui_kiosk_units must NOT create a
    /usr/bin/chromium-browser symlink -- the installers' V-3 substitution
    replaces the shim entirely.
    """
    body = _stepBody(DEPLOY_SCRIPT.read_text(encoding="utf-8"), "step_install_ui_kiosk_units")
    assert "ln -sf" not in body, (
        "step_install_ui_kiosk_units must not create a symlink shim -- the kit "
        "installers substitute the real chromium path (V-3) instead"
    )


def test_deployStep_sessionDetectsSeat0():
    """The step must still detect the ACTIVE graphical seat0 session (an SSH
    session reads as 'tty'; guessing X11-vs-Wayland is the D-3 black-screen bug).
    """
    body = _stepBody(DEPLOY_SCRIPT.read_text(encoding="utf-8"), "step_install_ui_kiosk_units")
    assert "seat0" in body, "step_install_ui_kiosk_units must session-detect from seat0"
    assert "FORCE_SESSION" in body, (
        "the detected session type must be forced into the kit installers "
        "(SPLASH/DASHBOARD _FORCE_SESSION)"
    )


def test_deployStep_absentKitWarnsNotBlocks():
    """A-9: an absent UI kit must WARN and let the deploy CONTINUE (return 0),
    never BLOCK (no hard non-zero exit in the step).
    """
    body = _stepBody(DEPLOY_SCRIPT.read_text(encoding="utf-8"), "step_install_ui_kiosk_units")
    assert "WARN" in body, "absent-kit path must emit a WARN"
    assert "return 0" in body, "absent-kit guard must return 0 (continue), not exit non-zero"
    assert "exit 1" not in body, (
        "step_install_ui_kiosk_units must not BLOCK the deploy on a missing kit (A-9)"
    )


def test_deployStep_wiredIntoMainFlow():
    """The step must be CALLED from the main flow, not merely defined -- a step
    name appearing only once = defined-but-never-invoked.
    """
    assert DEPLOY_SCRIPT.read_text(encoding="utf-8").count("step_install_ui_kiosk_units") >= 2, (
        "step_install_ui_kiosk_units must be both defined AND called in the deploy flow"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployDryRun_kioskStepDetectsSeat0():
    """`deploy-pi.sh --dry-run` from the repo root (kits present on disk) must
    exercise the kiosk-install step, reach the seat0 session-detection line
    (past the absent-kit guard), announce the V-3 no-symlink substitution, and
    exit 0 -- fully offline (every remote() is a DRY-RUN print, no SSH).
    """
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=str(REPO_ROOT),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, f"repo-root dry-run must exit 0; out=\n{out}"
    assert "chromium kiosk units" in out, "the kiosk-install step banner must appear"
    assert "seat0 session" in out, (
        "with kits present the step must reach the seat0 session-detection line "
        "(not the absent-kit guard)"
    )
    assert "V-3" in out and "no symlink shim" in out, (
        "the dry-run must announce the V-3 chromium substitution replaces the shim"
    )
