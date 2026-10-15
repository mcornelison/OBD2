################################################################################
# File Name: test_display_mode.py
# Purpose/Description: US-649-a -- /etc/eclipse/display-mode is the ONLY authority
#                      for which kiosk variants (x11|wayland) are installed, and
#                      eclipse-display-mode is the one command that switches it.
#                      Covers the command (fake systemctl recorder, fake kit tree),
#                      the deploy-pi.sh step that reads the file (dry-run), and
#                      both kit installers reading it when not forced.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-649-a) | Initial implementation (Sprint 102 V0.30.1).
# ================================================================================
################################################################################

"""Display-mode SSOT + switch-command tests (US-649-a).

Desk-only: systemctl is a PATH recorder that keeps enable state in a temp dir,
the kit installers are recorders in a fake tree, and every path the command
touches is redirected by its KIOSK_* overrides. No ssh, no Pi, no root.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODE_CMD = REPO_ROOT / "deploy" / "eclipse-display-mode.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
SPLASH_INSTALL = REPO_ROOT / "src" / "pi" / "ui" / "splash" / "install.sh"
DASH_INSTALL = REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "install.sh"

INSTALL_STEP = "step_install_display_mode_command"
INSTALL_TARGET = "/usr/local/sbin/eclipse-display-mode"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")

# systemctl recorder: logs every call, keeps enable state as marker files so
# is-enabled answers from what enable/disable did, and exits 0 for the rest
# (daemon-reload, reboot, cat).
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_STATE/systemctl.log"
case "$1" in
  enable)  touch "$FAKE_STATE/enabled.$2" ;;
  disable) rm -f "$FAKE_STATE/enabled.$2" ;;
  mask)    exit 9 ;;
  is-enabled)
    if [ -f "$FAKE_STATE/enabled.$2" ]; then echo enabled; exit 0; fi
    echo disabled; exit 1 ;;
esac
exit 0
"""

# Kit-installer recorder: logs which session it was forced to and, for the
# dashboard kit, writes the variant's distinguishing Environment= line where
# the real installer would put eclipse-dashboard.service.
FAKE_SPLASH_KIT = """#!/usr/bin/env bash
echo "splash session=${SPLASH_FORCE_SESSION-unset} user=${SPLASH_FORCE_USER-unset}" >> "$FAKE_STATE/kits.log"
"""
FAKE_DASH_KIT = """#!/usr/bin/env bash
echo "dashboard session=${DASHBOARD_FORCE_SESSION-unset} user=${DASHBOARD_FORCE_USER-unset}" >> "$FAKE_STATE/kits.log"
if [ "$DASHBOARD_FORCE_SESSION" = wayland ]; then
  echo 'Environment=WAYLAND_DISPLAY=wayland-0' > "$KIOSK_SYSTEMD_DIR/eclipse-dashboard.service"
else
  echo 'Environment=DISPLAY=:0' > "$KIOSK_SYSTEMD_DIR/eclipse-dashboard.service"
fi
"""


def _posix(path: Path) -> str:
    return path.as_posix()


@pytest.fixture()
def rig(tmp_path: Path) -> dict:
    """A fake Pi: state dir, PATH bin with systemctl, kit tree, systemd dir."""
    state = tmp_path / "state"
    binDir = tmp_path / "bin"
    tree = tmp_path / "tree"
    systemdDir = tmp_path / "systemd"
    for d in (state, binDir, systemdDir, tree / "src/pi/ui/splash", tree / "src/pi/ui/dashboard"):
        d.mkdir(parents=True)
    (binDir / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8", newline="\n")
    (tree / "src/pi/ui/splash/install.sh").write_text(FAKE_SPLASH_KIT, encoding="utf-8", newline="\n")
    (tree / "src/pi/ui/dashboard/install.sh").write_text(FAKE_DASH_KIT, encoding="utf-8", newline="\n")
    # Production today: X11 kiosk, lightdm is the display manager.
    (state / "enabled.lightdm.service").touch()
    (systemdDir / "eclipse-dashboard.service").write_text("Environment=DISPLAY=:0\n", encoding="utf-8")
    return {
        "state": state,
        "bin": binDir,
        "tree": tree,
        "systemd": systemdDir,
        "modeFile": tmp_path / "etc" / "eclipse" / "display-mode",
    }


def _runMode(rig: dict, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = _posix(rig["bin"]) + os.pathsep + env.get("PATH", "")
    env["FAKE_STATE"] = _posix(rig["state"])
    env["KIOSK_MODE_FILE"] = _posix(rig["modeFile"])
    env["KIOSK_TREE"] = _posix(rig["tree"])
    env["KIOSK_SYSTEMD_DIR"] = _posix(rig["systemd"])
    env["KIOSK_USER"] = "mcornelison"
    return subprocess.run(
        ["bash", _posix(MODE_CMD), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )


def _systemctlLog(rig: dict) -> list[str]:
    log = rig["state"] / "systemctl.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _enabled(rig: dict, unit: str) -> bool:
    return (rig["state"] / f"enabled.{unit}").exists()


# ----------------------------------------------------------------------------
# eclipse-display-mode x11|wayland|status
# ----------------------------------------------------------------------------


def test_waylandThenX11_noReboot_restoresTheX11Kiosk(rig):
    """
    Given: production X11 (lightdm enabled, x11 dashboard installed, no mode file)
    When: eclipse-display-mode wayland --no-reboot, then x11 --no-reboot
    Then: after x11 lightdm is enabled, eclipse-compositor disabled, the x11
        dashboard variant installed, the file says x11, and reboot never ran.
    """
    wayland = _runMode(rig, "wayland", "--no-reboot")
    assert wayland.returncode == 0, wayland.stdout + wayland.stderr
    assert rig["modeFile"].read_text(encoding="utf-8").strip() == "wayland"
    assert _enabled(rig, "eclipse-compositor.service")
    assert not _enabled(rig, "lightdm.service")

    x11 = _runMode(rig, "x11", "--no-reboot")

    assert x11.returncode == 0, x11.stdout + x11.stderr
    assert rig["modeFile"].read_text(encoding="utf-8").strip() == "x11"
    assert _enabled(rig, "lightdm.service")
    assert not _enabled(rig, "eclipse-compositor.service")
    dash = (rig["systemd"] / "eclipse-dashboard.service").read_text(encoding="utf-8")
    assert "Environment=DISPLAY=:0" in dash
    log = _systemctlLog(rig)
    assert "daemon-reload" in log
    assert not any("reboot" in line for line in log), log
    assert not any(line.startswith("mask") for line in log), "lightdm is disabled, never masked"


def test_switch_forcesBothKitInstallersToTheChosenMode(rig):
    """The command runs BOTH kit installers from the tree, forced to the new mode."""
    result = _runMode(rig, "wayland", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    kits = (rig["state"] / "kits.log").read_text(encoding="utf-8")
    assert "splash session=wayland user=mcornelison" in kits
    assert "dashboard session=wayland user=mcornelison" in kits


def test_switch_withoutNoReboot_reboots(rig):
    """Without --no-reboot the switch ends in a reboot (it takes effect at boot)."""
    result = _runMode(rig, "x11")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _systemctlLog(rig)[-1] == "reboot"


def test_switch_x11_disablesTheCompositorBeforeEnablingLightdm(rig):
    """Both claim display-manager.service: the old one goes before the new one."""
    _runMode(rig, "wayland", "--no-reboot")
    (rig["state"] / "systemctl.log").unlink()

    _runMode(rig, "x11", "--no-reboot")

    log = _systemctlLog(rig)
    assert log.index("disable eclipse-compositor.service") < log.index("enable lightdm.service")


@pytest.mark.parametrize("args", [("bogus",), ("bogus", "--no-reboot"), ("x11", "--bogus"), ()])
def test_unknownMode_exitsNonZero_andChangesNothing(rig, args):
    """
    Given: any unknown mode / flag (or none)
    When: eclipse-display-mode is run
    Then: non-zero exit; no mode file, no systemctl call, no installer run.
    """
    result = _runMode(rig, *args)

    assert result.returncode != 0
    assert not rig["modeFile"].exists()
    assert _systemctlLog(rig) == []
    assert not (rig["state"] / "kits.log").exists()
    assert _enabled(rig, "lightdm.service")


def test_status_consistentWayland_printsOkAndExitsZero(rig):
    _runMode(rig, "wayland", "--no-reboot")

    result = _runMode(rig, "status")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "mode file: wayland | display-manager: eclipse-compositor.service "
        "| dashboard variant: wayland | OK"
    )


def test_status_absentFile_readsX11_onTodaysCar(rig):
    """An absent file means x11 this sprint -- today's car is consistent."""
    result = _runMode(rig, "status")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode file: x11" in result.stdout
    assert "display-manager: lightdm.service" in result.stdout
    assert "dashboard variant: x11" in result.stdout


def test_status_waylandFileButLightdmEnabled_exitsNonZeroNamingTheMismatch(rig):
    """
    Given: the file says wayland but lightdm is still the enabled display manager
    When: status
    Then: non-zero exit, and the output names the display-manager mismatch.
    """
    rig["modeFile"].parent.mkdir(parents=True)
    rig["modeFile"].write_text("wayland\n", encoding="utf-8")

    result = _runMode(rig, "status")

    assert result.returncode != 0
    out = result.stdout + result.stderr
    assert "MISMATCH" in out
    assert "lightdm.service" in out


def test_status_wrongDashboardVariant_isAMismatch(rig):
    (rig["state"] / "enabled.lightdm.service").unlink()
    (rig["state"] / "enabled.eclipse-compositor.service").touch()
    rig["modeFile"].parent.mkdir(parents=True)
    rig["modeFile"].write_text("wayland\n", encoding="utf-8")

    result = _runMode(rig, "status")

    assert result.returncode != 0
    assert "dashboard variant" in result.stdout + result.stderr


def test_status_garbageModeFile_exitsNonZero(rig):
    rig["modeFile"].parent.mkdir(parents=True)
    rig["modeFile"].write_text("1920x1080\n", encoding="utf-8")

    assert _runMode(rig, "status").returncode != 0


def test_modeCommand_neverTouchesTheResolutionPin():
    """NAME CLASH: ECLIPSE_DISPLAY_MODE is set-display-mode.sh's HDMI WxH pin."""
    assert "ECLIPSE_DISPLAY_MODE" not in MODE_CMD.read_text(encoding="utf-8")


def test_modeCommand_neverMasksOrPurgesLightdm():
    text = MODE_CMD.read_text(encoding="utf-8")
    assert not re.search(r"systemctl\s+(--\S+\s+)*mask\b", text)
    assert not re.search(r"\bapt(-get)?\s+(\S+\s+)*(purge|remove)\b", text)


# ----------------------------------------------------------------------------
# deploy-pi.sh: the step reads the file; detection is WARN-only; command install
# ----------------------------------------------------------------------------


def _deployDryRun(env_extra: dict[str, str]) -> str:
    env = dict(os.environ)
    env.update(env_extra)
    # stderr merged INTO stdout so a WARN lands inside the step it belongs to.
    result = subprocess.run(
        ["bash", _posix(DEPLOY_SCRIPT), "--dry-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(REPO_ROOT),
        env=env,
    )
    out = result.stdout
    assert result.returncode == 0, out
    return out


def _kioskSection(out: str) -> str:
    start = out.index("chromium kiosk units")
    end = out.index("--- Step:", start)
    return out[start:end]


@pytest.mark.parametrize(
    "content,expected",
    [(None, "x11"), ("x11\n", "x11"), ("wayland\n", "wayland")],
    ids=["absent", "x11", "wayland"],
)
def test_deployDryRun_forcesTheSessionFromTheModeFile(tmp_path, content, expected):
    modeFile = tmp_path / "display-mode"
    if content is not None:
        modeFile.write_text(content, encoding="utf-8")

    out = _deployDryRun({"KIOSK_MODE_FILE": _posix(modeFile), "KIOSK_DETECTED_SESSION": ""})

    section = _kioskSection(out)
    assert f"_FORCE_SESSION={expected} " in section, section
    assert "WARN" not in section, section


def test_deployDryRun_disagreeingRunningSession_printsExactlyOneWarn(tmp_path):
    modeFile = tmp_path / "display-mode"
    modeFile.write_text("wayland\n", encoding="utf-8")

    out = _deployDryRun({"KIOSK_MODE_FILE": _posix(modeFile), "KIOSK_DETECTED_SESSION": "x11"})

    section = _kioskSection(out)
    assert "_FORCE_SESSION=wayland " in section, "the file decides, never the detection"
    assert len(re.findall(r"^WARN", section, flags=re.MULTILINE)) == 1, section


def _stepBody(stepName: str) -> str:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = text.index(f"{stepName}() {{")
    return text[start : text.index("\n}\n", start)]


def test_deployInstallsTheModeCommandToSbin():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    calls = [ln for ln in text.splitlines() if ln.strip() == INSTALL_STEP]
    assert calls, f"{INSTALL_STEP} is defined but never invoked"
    body = _stepBody(INSTALL_STEP)
    assert INSTALL_TARGET in body
    assert "deploy/eclipse-display-mode.sh" in body


def test_deployNeverEnablesWaylandItself():
    """The car stays on X11: only eclipse-display-mode swaps the display manager."""
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "enable eclipse-compositor" not in text
    assert "disable lightdm" not in text


# ----------------------------------------------------------------------------
# Kit installers: unforced, they read the file; detection only WARNs
# ----------------------------------------------------------------------------


def _runKit(script: Path, prefix: str, tmp_path: Path, *, mode: str | None,
            detected: str | None = None) -> subprocess.CompletedProcess:
    modeFile = tmp_path / "display-mode"
    if mode is not None:
        modeFile.write_text(mode + "\n", encoding="utf-8")
    env = dict(os.environ)
    env.pop(f"{prefix}_FORCE_SESSION", None)
    env.pop("XDG_SESSION_ID", None)
    env[f"{prefix}_FORCE_USER"] = "pi"
    env[f"{prefix}_FORCE_UID"] = "1000"
    env[f"{prefix}_FORCE_CHROMIUM"] = "/usr/bin/chromium"
    env["KIOSK_MODE_FILE"] = _posix(modeFile)
    if detected is not None:
        binDir = tmp_path / "bin"
        binDir.mkdir()
        (binDir / "loginctl").write_text(
            f"#!/usr/bin/env bash\necho {detected}\n", encoding="utf-8", newline="\n"
        )
        env["PATH"] = _posix(binDir) + os.pathsep + env.get("PATH", "")
        env["XDG_SESSION_ID"] = "c1"
    return subprocess.run(
        ["bash", _posix(script), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )


KITS = [(SPLASH_INSTALL, "SPLASH"), (DASH_INSTALL, "DASHBOARD")]


@pytest.mark.parametrize("script,prefix", KITS)
@pytest.mark.parametrize("mode,expected", [(None, "x11"), ("x11", "x11"), ("wayland", "wayland")])
def test_kitInstaller_unforced_takesTheSessionFromTheModeFile(tmp_path, script, prefix, mode, expected):
    result = _runKit(script, prefix, tmp_path, mode=mode)

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(rf"session type:\s+{expected}\b", result.stdout), result.stdout
    assert "WARN" not in result.stderr


@pytest.mark.parametrize("script,prefix", KITS)
def test_kitInstaller_disagreeingDetection_onlyWarns(tmp_path, script, prefix):
    result = _runKit(script, prefix, tmp_path, mode="wayland", detected="x11")

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"session type:\s+wayland\b", result.stdout), result.stdout
    assert result.stderr.count("WARN") == 1, result.stderr


@pytest.mark.parametrize("script,prefix", KITS)
def test_kitInstaller_garbageModeFile_abortsLoud(tmp_path, script, prefix):
    result = _runKit(script, prefix, tmp_path, mode="1920x1080")

    assert result.returncode == 1
    assert "display-mode" in result.stderr


@pytest.mark.parametrize("script,prefix", KITS)
def test_kitInstaller_forcedSession_stillWinsOverTheFile(tmp_path, script, prefix):
    """The deploy and eclipse-display-mode force the session; the force wins."""
    modeFile = tmp_path / "display-mode"
    modeFile.write_text("wayland\n", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        f"{prefix}_FORCE_USER": "pi",
        f"{prefix}_FORCE_UID": "1000",
        f"{prefix}_FORCE_CHROMIUM": "/usr/bin/chromium",
        f"{prefix}_FORCE_SESSION": "x11",
        "KIOSK_MODE_FILE": _posix(modeFile),
    })
    result = subprocess.run(["bash", _posix(script), "--dry-run"], capture_output=True,
                            text=True, encoding="utf-8", timeout=30, env=env)

    assert result.returncode == 0, result.stderr
    assert re.search(r"session type:\s+x11\b", result.stdout), result.stdout
