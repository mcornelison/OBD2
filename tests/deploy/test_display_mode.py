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
# 2026-10-19    | Rex (US-649-e) | Design A: lightdm in both modes; the switch
#                               | edits [Seat:*] of a fake lightdm.conf and
#                               | records priors in display-mode.state. The
#                               | compositor-mode tests are rewritten to the
#                               | lightdm model; state-file / decoy / pre-flight
#                               | / read-only / order tests added.
# 2026-10-25    | Rex (US-652-b) | MOVED PINs: absent => wayland. Tests whose
#                               | premise is an X11 car write an explicit x11
#                               | file. The deploy's absent-file convergence
#                               | (kiosk_mode_converge) runs against the rig.
# ================================================================================
################################################################################

"""Display-mode SSOT + switch-command tests (US-649-a, US-649-e).

Desk-only: systemctl is a PATH recorder that keeps enable state in a temp dir,
the kit installers are recorders in a fake tree, lightdm.conf / the session
file / labwc / the state dir are tmp copies, and every path the command
touches is redirected by its KIOSK_* overrides. No ssh, no Pi, no root.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
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
# (daemon-reload, reboot, cat). A `unknown.<unit>` marker makes `cat` fail, as
# systemctl does for a unit it does not know.
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_STATE/systemctl.log"
case "$1" in
  cat)     [ ! -f "$FAKE_STATE/unknown.$2" ] || exit 1 ;;
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
echo "splash uid=${SPLASH_FORCE_UID-unset}" >> "$FAKE_STATE/kits.log"
"""
FAKE_DASH_KIT = """#!/usr/bin/env bash
echo "dashboard session=${DASHBOARD_FORCE_SESSION-unset} user=${DASHBOARD_FORCE_USER-unset}" >> "$FAKE_STATE/kits.log"
echo "dashboard uid=${DASHBOARD_FORCE_UID-unset}" >> "$FAKE_STATE/kits.log"
if [ "$DASHBOARD_FORCE_SESSION" = wayland ]; then
  echo 'Environment=WAYLAND_DISPLAY=wayland-0' > "$KIOSK_SYSTEMD_DIR/eclipse-dashboard.service"
else
  echo 'Environment=DISPLAY=:0' > "$KIOSK_SYSTEMD_DIR/eclipse-dashboard.service"
fi
"""

# US-651-a: `id -u mcornelison` answers 1000 on the fake Pi (the kit installers'
# uid derivation); any other user is unknown, as `id` reports it.
FAKE_ID = """#!/usr/bin/env bash
if [ "$1" = -u ] && [ "$2" = mcornelison ]; then echo 1000; exit 0; fi
echo "id: '$2': no such user" >&2
exit 1
"""

# The kiosk start trigger files eclipse-display-mode renders from the tree.
TRIGGER_FILES = (
    "eclipse-kiosk-start.target",
    "eclipse-kiosk-socket.path",
    "eclipse-x-ready.path",
    "eclipse-x-ready.desktop",
)
SOCKET_PATH = "eclipse-kiosk-socket.path"
X_READY_PATH = "eclipse-x-ready.path"
X_READY_DESKTOP = "eclipse-x-ready.desktop"


# Today's car (US-649-e acceptance): [Seat:*] autologin-user=mcornelison,
# autologin-session=rpd-x, user-session=rpd-x; a commented '#autologin-session='
# decoy inside the section and a second section holding the same keys as decoy.
LIGHTDM_CONF = """\
[LightDM]
#start-default-seat=true

[Seat:*]
#autologin-session=
autologin-user=mcornelison
autologin-session=rpd-x
user-session=rpd-x
greeter-hide-users=false

[XDMCPServer]
autologin-session=decoy-xdmcp
user-session=decoy-xdmcp
"""

KIOSK = "eclipse-kiosk"
STATE_NAME = "display-mode.state"


def _posix(path: Path) -> str:
    return path.as_posix()


@pytest.fixture()
def rig(tmp_path: Path) -> dict:
    """A fake Pi: state dir, PATH bin with systemctl, kit tree, systemd dir,
    lightdm.conf, the kiosk session file, labwc and the eclipse-obd state dir."""
    state = tmp_path / "state"
    binDir = tmp_path / "bin"
    tree = tmp_path / "tree"
    systemdDir = tmp_path / "systemd"
    lightdmDir = tmp_path / "etc" / "lightdm"
    obdStateDir = tmp_path / "var" / "lib" / "eclipse-obd"
    for d in (state, binDir, systemdDir, tree / "src/pi/ui/splash", tree / "src/pi/ui/dashboard",
              lightdmDir, obdStateDir):
        d.mkdir(parents=True)
    (binDir / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8", newline="\n")
    (binDir / "id").write_text(FAKE_ID, encoding="utf-8", newline="\n")
    (tree / "deploy").mkdir()
    for name in TRIGGER_FILES:
        shutil.copyfile(REPO_ROOT / "deploy" / name, tree / "deploy" / name)
    (tree / "src/pi/ui/splash/install.sh").write_text(FAKE_SPLASH_KIT, encoding="utf-8", newline="\n")
    (tree / "src/pi/ui/dashboard/install.sh").write_text(FAKE_DASH_KIT, encoding="utf-8", newline="\n")
    # Production today: X11 kiosk, lightdm is the display manager.
    (state / "enabled.lightdm.service").touch()
    (systemdDir / "eclipse-dashboard.service").write_text("Environment=DISPLAY=:0\n", encoding="utf-8")
    conf = lightdmDir / "lightdm.conf"
    conf.write_text(LIGHTDM_CONF, encoding="utf-8", newline="\n")
    sessionFile = tmp_path / "usr" / "share" / "wayland-sessions" / f"{KIOSK}.desktop"
    sessionFile.parent.mkdir(parents=True)
    sessionFile.write_text("[Desktop Entry]\nName=Eclipse kiosk\n", encoding="utf-8", newline="\n")
    labwc = binDir / "labwc"
    labwc.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
    labwc.chmod(0o755)
    return {
        "root": tmp_path,
        "state": state,
        "bin": binDir,
        "tree": tree,
        "systemd": systemdDir,
        "modeFile": tmp_path / "etc" / "eclipse" / "display-mode",
        "conf": conf,
        "sessionFile": sessionFile,
        "labwc": labwc,
        "obdState": obdStateDir,
        "stateFile": obdStateDir / STATE_NAME,
        "autostart": tmp_path / "etc" / "xdg" / "autostart",
    }


def _runMode(rig: dict, *args: str, extraEnv: dict[str, str] | None = None
             ) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("KIOSK_UID", None)
    env["KIOSK_AUTOSTART_DIR"] = _posix(rig["autostart"])
    env["PATH"] = _posix(rig["bin"]) + os.pathsep + env.get("PATH", "")
    env["FAKE_STATE"] = _posix(rig["state"])
    env["KIOSK_MODE_FILE"] = _posix(rig["modeFile"])
    env["KIOSK_TREE"] = _posix(rig["tree"])
    env["KIOSK_SYSTEMD_DIR"] = _posix(rig["systemd"])
    env["KIOSK_USER"] = "mcornelison"
    env["KIOSK_LIGHTDM_CONF"] = _posix(rig["conf"])
    env["KIOSK_SESSION_FILE"] = _posix(rig["sessionFile"])
    env["KIOSK_LABWC_BIN"] = _posix(rig["labwc"])
    env["KIOSK_STATE_DIR"] = _posix(rig["obdState"])
    env.update(extraEnv or {})
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


def _confText(rig: dict) -> str:
    return rig["conf"].read_text(encoding="utf-8")


def _withSeatKeys(autologin: str | None, user: str | None) -> str:
    """LIGHTDM_CONF with [Seat:*]'s two session keys set (None = line removed)."""
    text = LIGHTDM_CONF
    for key, value in (("autologin-session", autologin), ("user-session", user)):
        old = f"\n{key}=rpd-x\n"
        new = "\n" if value is None else f"\n{key}={value}\n"
        text = text.replace(old, new, 1)
    return text


def _setConf(rig: dict, text: str) -> None:
    rig["conf"].write_text(text, encoding="utf-8", newline="\n")


def _writeMode(rig: dict, mode: str) -> None:
    """An EXPLICIT mode file (US-652-b: absent now means wayland)."""
    rig["modeFile"].parent.mkdir(parents=True, exist_ok=True)
    rig["modeFile"].write_text(mode + "\n", encoding="utf-8", newline="\n")


def _snapshot(rig: dict) -> dict[str, bytes]:
    """Every file under the rig except the systemctl call log."""
    log = rig["state"] / "systemctl.log"
    return {
        str(p): p.read_bytes()
        for p in rig["root"].rglob("*")
        if p.is_file() and p != log
    }


def _modeChanges(rig: dict) -> list[str]:
    return [ln for ln in _systemctlLog(rig) if ln.split()[0] in ("enable", "disable", "reboot")]


# ----------------------------------------------------------------------------
# eclipse-display-mode x11|wayland|status
# ----------------------------------------------------------------------------


def test_waylandThenX11_noReboot_restoresTheX11Kiosk(rig):
    """
    Given: production X11 (lightdm enabled at rpd-x, x11 dashboard, no mode file)
    When: eclipse-display-mode wayland --no-reboot, then x11 --no-reboot
    Then: wayland sets both [Seat:*] keys to eclipse-kiosk, records the rpd-x
        priors and keeps lightdm enabled; x11 restores both rpd-x values,
        deletes the state file, installs the x11 dashboard; lightdm stays
        enabled throughout, the compositor never is, and reboot never ran.
    """
    wayland = _runMode(rig, "wayland", "--no-reboot")
    assert wayland.returncode == 0, wayland.stdout + wayland.stderr
    assert rig["modeFile"].read_text(encoding="utf-8").strip() == "wayland"
    assert _confText(rig) == _withSeatKeys(KIOSK, KIOSK)
    assert rig["stateFile"].read_text(encoding="utf-8") == (
        "autologin-session=rpd-x\nuser-session=rpd-x\n"
    )
    assert _enabled(rig, "lightdm.service")
    assert not _enabled(rig, "eclipse-compositor.service")

    x11 = _runMode(rig, "x11", "--no-reboot")

    assert x11.returncode == 0, x11.stdout + x11.stderr
    assert rig["modeFile"].read_text(encoding="utf-8").strip() == "x11"
    assert _confText(rig) == LIGHTDM_CONF
    assert not rig["stateFile"].exists()
    assert _enabled(rig, "lightdm.service")
    assert not _enabled(rig, "eclipse-compositor.service")
    dash = (rig["systemd"] / "eclipse-dashboard.service").read_text(encoding="utf-8")
    assert "Environment=DISPLAY=:0" in dash
    log = _systemctlLog(rig)
    assert "daemon-reload" in log
    assert not any("reboot" in line for line in log), log
    assert not any(line.startswith("mask") for line in log), "lightdm is never masked"
    assert "disable lightdm.service" not in log, "lightdm stays enabled in both modes"


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


@pytest.mark.parametrize("mode", ["wayland", "x11"])
def test_switch_retiresAnEnabledCompositorBeforeEnablingLightdm(rig, mode):
    """
    Given: a car switched to Wayland before US-649-e (compositor enabled and
        installed, lightdm disabled)
    When: either switch
    Then: the compositor is disabled BEFORE lightdm is enabled (both claim
        display-manager.service), its unit file is deleted, lightdm is enabled.
    """
    (rig["state"] / "enabled.lightdm.service").unlink()
    (rig["state"] / "enabled.eclipse-compositor.service").touch()
    (rig["systemd"] / "eclipse-compositor.service").write_text("[Unit]\n", encoding="utf-8")

    result = _runMode(rig, mode, "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    log = _systemctlLog(rig)
    assert log.index("disable eclipse-compositor.service") < log.index("enable lightdm.service")
    assert not (rig["systemd"] / "eclipse-compositor.service").exists()
    assert not _enabled(rig, "eclipse-compositor.service")
    assert _enabled(rig, "lightdm.service")


def test_switch_compositorAbsent_disablesNothing(rig):
    """No compositor enabled: no disable call, lightdm is still (re)enabled."""
    result = _runMode(rig, "wayland", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    log = _systemctlLog(rig)
    assert not any(ln.startswith("disable") for ln in log), log
    assert "enable lightdm.service" in log


# ---- the kiosk start trigger (US-651-a) ---------------------------------------


def _enabledPaths(rig: dict) -> list[str]:
    return [u for u in (SOCKET_PATH, X_READY_PATH) if _enabled(rig, u)]


def test_switchX11WaylandX11_exactlyOnePathEnabled_autostartOnlyInX11(rig):
    """
    Given: today's car
    When: x11, then wayland, then x11 (all --no-reboot)
    Then: after each switch exactly one .path is enabled -- the mode's -- and the
        autostart entry exists only in x11; the latch and both .path units are
        installed every time.
    """
    expected = {"x11": X_READY_PATH, "wayland": SOCKET_PATH}
    for mode in ("x11", "wayland", "x11"):
        result = _runMode(rig, mode, "--no-reboot")

        assert result.returncode == 0, result.stdout + result.stderr
        assert _enabledPaths(rig) == [expected[mode]], mode
        assert (rig["autostart"] / X_READY_DESKTOP).exists() == (mode == "x11"), mode
        for unit in ("eclipse-kiosk-start.target", SOCKET_PATH, X_READY_PATH):
            assert (rig["systemd"] / unit).is_file(), f"{mode}: {unit}"


def test_switch_disablesTheOtherPathOnlyWhenEnabled(rig):
    """wayland -> x11 disables the socket .path; a first x11 switch disables nothing."""
    first = _runMode(rig, "x11", "--no-reboot")
    assert first.returncode == 0, first.stdout + first.stderr
    assert not [ln for ln in _systemctlLog(rig) if ln.startswith("disable")]

    _runMode(rig, "wayland", "--no-reboot")
    _runMode(rig, "x11", "--no-reboot")

    assert _systemctlLog(rig).count(f"disable {SOCKET_PATH}") == 1
    assert _systemctlLog(rig).count(f"disable {X_READY_PATH}") == 1


def test_trigger_appliesTheModesSwap_noLightdmEditNoKitsNoReboot(rig):
    """
    Given: the mode file says wayland, lightdm.conf still holds rpd-x
    When: eclipse-display-mode trigger
    Then: the socket .path is enabled, the x-ready one is not, no autostart
        entry; lightdm.conf, the mode file and the kits are untouched; no reboot.
    """
    rig["modeFile"].parent.mkdir(parents=True)
    rig["modeFile"].write_text("wayland\n", encoding="utf-8")
    (rig["state"] / f"enabled.{X_READY_PATH}").touch()
    (rig["autostart"]).mkdir(parents=True)
    (rig["autostart"] / X_READY_DESKTOP).write_text("stale\n", encoding="utf-8")
    confBefore = rig["conf"].read_bytes()

    result = _runMode(rig, "trigger")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _enabledPaths(rig) == [SOCKET_PATH]
    assert not (rig["autostart"] / X_READY_DESKTOP).exists()
    assert rig["conf"].read_bytes() == confBefore
    assert rig["modeFile"].read_text(encoding="utf-8") == "wayland\n"
    assert not (rig["state"] / "kits.log").exists()
    log = _systemctlLog(rig)
    assert "reboot" not in log
    assert not [ln for ln in log if ln.startswith("start")], "nothing is started live"
    assert not [ln for ln in log if "lightdm" in ln]


def test_trigger_absentModeFile_isWayland(rig):
    """MOVED PIN (US-652-b): absent was x11; it is the lib's default, wayland."""
    result = _runMode(rig, "trigger")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _enabledPaths(rig) == [SOCKET_PATH]
    assert not (rig["autostart"] / X_READY_DESKTOP).exists()


def test_trigger_explicitX11File_isX11(rig):
    _writeMode(rig, "x11")

    result = _runMode(rig, "trigger")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _enabledPaths(rig) == [X_READY_PATH]
    assert (rig["autostart"] / X_READY_DESKTOP).exists()


def test_trigger_rendersTheUidFromIdOfTheKioskUser(rig):
    """The .path names /run/user/<id -u KIOSK_USER>/wayland-0 and starts the latch."""
    _runMode(rig, "trigger")

    socketPath = (rig["systemd"] / SOCKET_PATH).read_text(encoding="utf-8")
    assert "PathExists=/run/user/1000/wayland-0\n" in socketPath
    assert "Unit=eclipse-kiosk-start.target\n" in socketPath
    assert "__PI_UID__" not in socketPath
    xReady = (rig["systemd"] / X_READY_PATH).read_text(encoding="utf-8")
    assert "PathExists=/run/user/1000/eclipse-x-ready\n" in xReady


def test_trigger_autostartEntry_writesOnlyTheMarker(rig):
    _writeMode(rig, "x11")  # MOVED PIN (US-652-b): x11 is explicit now
    _runMode(rig, "trigger")

    desktop = (rig["autostart"] / X_READY_DESKTOP).read_text(encoding="utf-8")
    execs = [ln for ln in desktop.splitlines() if ln.startswith("Exec")]
    assert execs == ["Exec=/usr/bin/touch /run/user/1000/eclipse-x-ready"]


def test_kioskUidOverride_isHonouredByTheSwapAndTheKits(rig):
    """
    Given: KIOSK_UID=4242 (desk override)
    When: a wayland switch
    Then: the .path watches /run/user/4242 AND both kits were forced to uid 4242,
        so the .path and the kiosk units name the same runtime dir.
    """
    result = _runMode(rig, "wayland", "--no-reboot", extraEnv={"KIOSK_UID": "4242"})

    assert result.returncode == 0, result.stdout + result.stderr
    socketPath = (rig["systemd"] / SOCKET_PATH).read_text(encoding="utf-8")
    assert "PathExists=/run/user/4242/wayland-0\n" in socketPath
    kits = (rig["state"] / "kits.log").read_text(encoding="utf-8")
    assert "splash uid=4242" in kits
    assert "dashboard uid=4242" in kits


def test_switch_withoutKioskUid_leavesTheKitsTheirOwnIdDerivation(rig):
    """Unset KIOSK_UID: the kits get no forced uid -- they run the same `id -u`."""
    _runMode(rig, "wayland", "--no-reboot")

    kits = (rig["state"] / "kits.log").read_text(encoding="utf-8")
    assert "splash uid=unset" in kits
    assert "dashboard uid=unset" in kits


@pytest.mark.parametrize("verb", [("trigger",), ("wayland", "--no-reboot"), ("x11", "--no-reboot")])
def test_unresolvableUid_exitsNonZero_nothingChanged(rig, verb):
    """An unknown kiosk user is never rendered as /run/user/0 (I-044)."""
    before = _snapshot(rig)

    result = _runMode(rig, *verb, extraEnv={"KIOSK_USER": "nobody-here"})

    assert result.returncode != 0
    assert "nothing changed" in (result.stdout + result.stderr).lower()
    assert _snapshot(rig) == before
    assert _modeChanges(rig) == []


def test_trigger_garbageModeFile_exitsNonZero_nothingChanged(rig):
    rig["modeFile"].parent.mkdir(parents=True)
    rig["modeFile"].write_text("1920x1080\n", encoding="utf-8")
    before = _snapshot(rig)

    result = _runMode(rig, "trigger")

    assert result.returncode != 0
    assert _snapshot(rig) == before
    assert _modeChanges(rig) == []


@pytest.mark.parametrize("args", [("bogus",), ("bogus", "--no-reboot"), ("x11", "--bogus"), ()])
def test_unknownMode_exitsNonZero_andChangesNothing(rig, args):
    """
    Given: any unknown mode / flag (or none)
    When: eclipse-display-mode is run
    Then: non-zero exit; no mode file, no systemctl call, no installer run,
        lightdm.conf untouched.
    """
    result = _runMode(rig, *args)

    assert result.returncode != 0
    assert not rig["modeFile"].exists()
    assert _systemctlLog(rig) == []
    assert not (rig["state"] / "kits.log").exists()
    assert _enabled(rig, "lightdm.service")
    assert _confText(rig) == LIGHTDM_CONF


# ---- the lightdm.conf edit -------------------------------------------------


def test_wayland_editsOnlyTheTwoSeatKeys_decoysByteIdentical(rig):
    """The commented '#autologin-session=', autologin-user, greeter-hide-users
    and the [LightDM] / [XDMCPServer] sections come through byte-identical."""
    before = rig["conf"].read_bytes()

    result = _runMode(rig, "wayland", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    after = rig["conf"].read_bytes()
    expected = before.replace(
        b"\nautologin-session=rpd-x\nuser-session=rpd-x\n",
        b"\nautologin-session=eclipse-kiosk\nuser-session=eclipse-kiosk\n",
    )
    assert expected != before
    assert after == expected
    assert b"#autologin-session=\n" in after
    assert b"autologin-session=decoy-xdmcp\nuser-session=decoy-xdmcp\n" in after


@pytest.mark.parametrize("mode", ["wayland", "x11"])
def test_switch_leavesNoTempFileBehind(rig, mode):
    if mode == "x11":
        _runMode(rig, "wayland", "--no-reboot")

    result = _runMode(rig, mode, "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    for d in (rig["conf"].parent, rig["obdState"]):
        leftovers = [p.name for p in d.iterdir() if ".tmp" in p.name]
        assert leftovers == [], leftovers


def test_wayland_missingKey_isAppendedUnderSeatAndRecordedAbsent_revertDeletesIt(rig):
    """
    Given: [Seat:*] has no user-session line
    When: wayland, then x11
    Then: wayland appends user-session=eclipse-kiosk directly under [Seat:*] and
        records 'user-session=absent'; x11 deletes the line again, so the file
        is byte-identical to where it started.
    """
    original = _withSeatKeys("rpd-x", None)
    _setConf(rig, original)

    wayland = _runMode(rig, "wayland", "--no-reboot")

    assert wayland.returncode == 0, wayland.stdout + wayland.stderr
    conf = _confText(rig)
    assert "[Seat:*]\nuser-session=eclipse-kiosk\n" in conf
    assert "\nautologin-session=eclipse-kiosk\n" in conf
    assert rig["stateFile"].read_text(encoding="utf-8") == (
        "autologin-session=rpd-x\nuser-session=absent\n"
    )

    x11 = _runMode(rig, "x11", "--no-reboot")

    assert x11.returncode == 0, x11.stdout + x11.stderr
    assert _confText(rig) == original
    assert not rig["stateFile"].exists()


def test_waylandTwice_secondSwitchRecordsNothing(rig):
    """wayland -> wayland: the priors are eclipse-kiosk now and never recorded."""
    _runMode(rig, "wayland", "--no-reboot")
    stateBefore = rig["stateFile"].read_bytes()

    again = _runMode(rig, "wayland", "--no-reboot")

    assert again.returncode == 0, again.stdout + again.stderr
    assert rig["stateFile"].read_bytes() == stateBefore
    assert _confText(rig) == _withSeatKeys(KIOSK, KIOSK)


def test_wayland_priorsAlreadyEclipseKiosk_noStateFileWritten(rig):
    _setConf(rig, _withSeatKeys(KIOSK, KIOSK))

    result = _runMode(rig, "wayland", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not rig["stateFile"].exists()


def test_wayland_recordedLineIsNeverRewritten_onlyMissingKeysAppended(rig):
    """
    Given: the state file already records autologin-session (a custom prior)
    When: wayland
    Then: that line is kept byte-identical; only user-session is appended.
    """
    rig["stateFile"].write_text("autologin-session=lightdm-xsession\n", encoding="utf-8",
                                newline="\n")

    result = _runMode(rig, "wayland", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    assert rig["stateFile"].read_text(encoding="utf-8") == (
        "autologin-session=lightdm-xsession\nuser-session=rpd-x\n"
    )


def test_x11_noStateFile_kioskKeysFallBackToRpdX_withExactlyOneWarn(rig):
    """os-trim fixed-inverse pattern: no recorded priors -> rpd-x, ONE WARN."""
    _setConf(rig, _withSeatKeys(KIOSK, KIOSK))

    result = _runMode(rig, "x11", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _confText(rig) == LIGHTDM_CONF
    out = result.stdout + result.stderr
    assert len(re.findall(r"^WARN", out, flags=re.MULTILINE)) == 1, out


def test_x11_oneKeyRecorded_otherFallsBack_withOneWarn(rig):
    rig["stateFile"].write_text("autologin-session=lightdm-xsession\n", encoding="utf-8",
                                newline="\n")
    _setConf(rig, _withSeatKeys(KIOSK, KIOSK))

    result = _runMode(rig, "x11", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _confText(rig) == _withSeatKeys("lightdm-xsession", "rpd-x")
    out = result.stdout + result.stderr
    assert len(re.findall(r"^WARN", out, flags=re.MULTILINE)) == 1, out
    assert not rig["stateFile"].exists()


def test_x11_unrecordedKeyWithAnotherValue_isLeftAlone(rig):
    _setConf(rig, _withSeatKeys(KIOSK, "LXDE-pi-x"))

    result = _runMode(rig, "x11", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _confText(rig) == _withSeatKeys("rpd-x", "LXDE-pi-x")


def test_x11_onTodaysCar_leavesLightdmConfByteIdentical(rig):
    before = rig["conf"].read_bytes()

    result = _runMode(rig, "x11", "--no-reboot")

    assert result.returncode == 0, result.stdout + result.stderr
    assert rig["conf"].read_bytes() == before
    assert "WARN" not in result.stdout + result.stderr


# ---- pre-flight and failure ------------------------------------------------


def _breakStateDir(rig: dict) -> None:
    rig["obdState"].rmdir()


def _breakSessionFile(rig: dict) -> None:
    rig["sessionFile"].unlink()


def _breakLabwc(rig: dict) -> None:
    rig["labwc"].unlink()


def _breakConfMissing(rig: dict) -> None:
    rig["conf"].unlink()


def _breakNoSeatSection(rig: dict) -> None:
    _setConf(rig, LIGHTDM_CONF.replace("[Seat:*]", "[Seat:seat0]"))


def _breakLightdmUnknown(rig: dict) -> None:
    (rig["state"] / "unknown.lightdm.service").touch()


PREFLIGHT_FAILURES = [
    ("wayland", _breakStateDir),
    ("x11", _breakStateDir),
    ("wayland", _breakSessionFile),
    ("wayland", _breakLabwc),
    ("wayland", _breakConfMissing),
    ("x11", _breakConfMissing),
    ("wayland", _breakNoSeatSection),
    ("wayland", _breakLightdmUnknown),
    ("x11", _breakLightdmUnknown),
]


@pytest.mark.parametrize(
    "mode,breaker", PREFLIGHT_FAILURES,
    ids=[f"{m}-{b.__name__.removeprefix('_break')}" for m, b in PREFLIGHT_FAILURES],
)
def test_preflightFailure_exitsNonZero_nothingChanged_everyFileByteIdentical(rig, mode, breaker):
    breaker(rig)
    if mode == "x11" and rig["conf"].exists():
        # A switch that got past pre-flight would rewrite these keys.
        _setConf(rig, _withSeatKeys(KIOSK, KIOSK))
    before = _snapshot(rig)

    result = _runMode(rig, mode, "--no-reboot")

    assert result.returncode != 0
    assert "nothing changed" in (result.stdout + result.stderr).lower()
    assert _snapshot(rig) == before
    assert not rig["obdState"].exists() or not rig["stateFile"].exists()
    assert _modeChanges(rig) == []


def test_preflight_neverCreatesTheStateDir(rig):
    _breakStateDir(rig)

    _runMode(rig, "wayland", "--no-reboot")

    assert not rig["obdState"].exists()


def test_wayland_lightdmConfReadOnly_confByteIdentical_priorsRecorded_nonZero(rig):
    """
    Given: lightdm.conf cannot be written (read-only)
    When: wayland
    Then: non-zero exit; lightdm.conf byte-identical; display-mode.state holds
        both priors (recorded BEFORE the edit, Atlas G2); no mode file, no kit
        run, no systemctl enable.
    """
    before = rig["conf"].read_bytes()
    rig["conf"].chmod(stat.S_IREAD)
    try:
        result = _runMode(rig, "wayland", "--no-reboot")
        after = rig["conf"].read_bytes()
    finally:
        rig["conf"].chmod(stat.S_IREAD | stat.S_IWRITE)

    assert result.returncode != 0
    assert after == before
    assert rig["stateFile"].read_text(encoding="utf-8") == (
        "autologin-session=rpd-x\nuser-session=rpd-x\n"
    )
    assert not rig["modeFile"].exists()
    assert not (rig["state"] / "kits.log").exists()
    assert _modeChanges(rig) == []
    assert [p.name for p in rig["conf"].parent.iterdir() if ".tmp" in p.name] == []


# ---- static checks on the script --------------------------------------------


def _functionBody(name: str) -> str:
    text = MODE_CMD.read_text(encoding="utf-8")
    start = text.index(f"\n{name}() {{")
    return text[start : text.index("\n}\n", start)]


def test_script_neverUsesSedInPlace():
    assert not re.search(r"\bsed\b[^\n]*\s-i", MODE_CMD.read_text(encoding="utf-8"))


def test_script_tempFileTakesTheOriginalsModeAndOwner():
    body = _functionBody("edit_lightdm_conf")
    assert re.search(r'tmp="\$LIGHTDM_CONF\.tmp', body), "temp file in lightdm.conf's own dir"
    assert re.search(r'chmod --reference="\$LIGHTDM_CONF" "\$tmp"', body)
    assert re.search(r'chown --reference="\$LIGHTDM_CONF" "\$tmp"', body)
    assert re.search(r'\bmv\b[^\n]*"\$tmp" "\$LIGHTDM_CONF"', body), "installed by rename"


def test_script_stateFileIsWrittenViaTempThenRename():
    body = _functionBody("record_priors")
    assert re.search(r'tmp="\$STATE_FILE\.tmp', body)
    assert re.search(r'\bmv\b[^\n]*"\$tmp" "\$STATE_FILE"', body)


def test_cmdSwitch_recordsPriorsBeforeTheLightdmConfEdit():
    """os-trim order (Atlas G2): the state-file write precedes the rename."""
    body = _functionBody("cmd_switch")
    assert body.index("record_priors") < body.index("edit_lightdm_conf")
    assert body.index("preflight") < body.index("record_priors")
    assert body.index("edit_lightdm_conf") < body.index('> "$MODE_FILE"')
    assert body.index("run_kit") < body.index("systemctl enable")


# ---- status ------------------------------------------------------------------


def test_status_consistentWayland_printsOkAndExitsZero(rig):
    _runMode(rig, "wayland", "--no-reboot")

    result = _runMode(rig, "status")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == (
        "mode file: wayland | display-manager: lightdm.service "
        "| lightdm session: eclipse-kiosk | dashboard variant: wayland | OK"
    )


def test_status_absentFile_readsWayland(rig):
    """MOVED PIN (US-652-b): an absent file means wayland, so an X11 car with
    no file is a mismatch until the deploy converges it."""
    result = _runMode(rig, "status")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "mode file: wayland" in result.stdout
    assert "MISMATCH: lightdm session is rpd-x, mode wayland needs eclipse-kiosk" in result.stdout


def test_status_explicitX11File_onTodaysX11Car_isOk(rig):
    _writeMode(rig, "x11")

    result = _runMode(rig, "status")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "mode file: x11" in result.stdout
    assert "display-manager: lightdm.service" in result.stdout
    assert "dashboard variant: x11" in result.stdout
    assert "lightdm session: rpd-x" in result.stdout


def test_status_waylandAfterSwitch_compositorStillEnabled_isAMismatch(rig):
    _runMode(rig, "wayland", "--no-reboot")
    (rig["state"] / "enabled.eclipse-compositor.service").touch()

    result = _runMode(rig, "status")

    assert result.returncode == 1
    assert result.stdout.strip().endswith("| MISMATCH: eclipse-compositor.service still enabled")


def test_status_waylandFileButX11Session_exitsNonZeroNamingTheMismatch(rig):
    """
    Given: the file says wayland but lightdm still autologins rpd-x
    When: status
    Then: exit 1, and the output names the session mismatch.
    """
    rig["modeFile"].parent.mkdir(parents=True)
    rig["modeFile"].write_text("wayland\n", encoding="utf-8")
    (rig["systemd"] / "eclipse-dashboard.service").write_text(
        "Environment=WAYLAND_DISPLAY=wayland-0\n", encoding="utf-8")

    result = _runMode(rig, "status")

    assert result.returncode == 1
    assert result.stdout.strip() == (
        "mode file: wayland | display-manager: lightdm.service | lightdm session: rpd-x "
        "| dashboard variant: wayland "
        "| MISMATCH: lightdm session is rpd-x, mode wayland needs eclipse-kiosk"
    )


def test_status_x11FileButKioskSession_isAMismatch(rig):
    _writeMode(rig, "x11")  # MOVED PIN (US-652-b): x11 is explicit now
    _setConf(rig, _withSeatKeys(KIOSK, KIOSK))

    result = _runMode(rig, "status")

    assert result.returncode == 1
    assert "lightdm session: eclipse-kiosk" in result.stdout
    assert "MISMATCH: lightdm session is eclipse-kiosk" in result.stdout


def test_status_lightdmConfMissing_showsMissing(rig):
    rig["conf"].unlink()

    result = _runMode(rig, "status")

    assert result.returncode == 1
    assert "lightdm session: <missing>" in result.stdout
    assert "MISMATCH: lightdm.conf missing" in result.stdout


def test_status_autologinSessionUnset_showsUnset(rig):
    _setConf(rig, _withSeatKeys(None, "rpd-x"))

    result = _runMode(rig, "status")

    assert result.returncode == 1
    assert "lightdm session: <unset>" in result.stdout
    assert "MISMATCH: autologin-session unset" in result.stdout


def test_status_lightdmNotEnabled_andSeveralReasons_joinedByComma(rig):
    _writeMode(rig, "x11")  # MOVED PIN (US-652-b): x11 is explicit now
    (rig["state"] / "enabled.lightdm.service").unlink()
    (rig["state"] / "enabled.eclipse-compositor.service").touch()

    result = _runMode(rig, "status")

    assert result.returncode == 1
    assert result.stdout.strip().endswith(
        "| MISMATCH: lightdm.service not enabled, eclipse-compositor.service still enabled"
    )


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
    # MOVED PIN (US-652-b): the absent row was x11.
    [(None, "wayland"), ("x11\n", "x11"), ("wayland\n", "wayland")],
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


SWITCH_LINE = "eclipse-display-mode wayland --no-reboot"


@pytest.mark.parametrize("content", [None, "x11\n", "wayland\n"], ids=["absent", "x11", "wayland"])
def test_deployDryRun_runsTheSwitchOnlyWhenTheFileIsAbsent(tmp_path, content):
    """
    US-652-b (replaces test_deployNeverEnablesWaylandItself): the deploy runs
    `eclipse-display-mode wayland --no-reboot` exactly once for an ABSENT file
    and never for an explicit one, which it reports as present, no switch.
    """
    modeFile = tmp_path / "display-mode"
    if content is not None:
        modeFile.write_text(content, encoding="utf-8")

    section = _kioskSection(_deployDryRun({"KIOSK_MODE_FILE": _posix(modeFile),
                                           "KIOSK_DETECTED_SESSION": ""}))

    if content is None:
        assert section.count(SWITCH_LINE) == 1, section
        assert "no switch" not in section, section
    else:
        assert SWITCH_LINE not in section, section
        assert f"mode file present: {content.strip()}, no switch" in section, section


def test_deployDryRun_garbageFile_skipsWithNoSwitch(tmp_path):
    modeFile = tmp_path / "display-mode"
    modeFile.write_text("1920x1080\n", encoding="utf-8")

    section = _kioskSection(_deployDryRun({"KIOSK_MODE_FILE": _posix(modeFile),
                                           "KIOSK_DETECTED_SESSION": ""}))

    assert "WARN" in section and "skip the kiosk-unit install" in section, section
    assert "--no-reboot" not in section and "no switch" not in section, section


def test_deployNeverEnablesTheCompositorOrDisablesLightdm_andNeverReboots():
    """The switch is the only thing that swaps the display manager; the
    deploy only ever calls it with --no-reboot, and never restarts lightdm."""
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "enable eclipse-compositor" not in text
    assert "disable lightdm" not in text
    assert not re.search(r"systemctl\s+(--\S+\s+)*(restart|reload-or-restart|try-restart|stop)\s+lightdm", text)
    body = _shellFunctionBody(text, "kiosk_mode_converge")
    calls = re.findall(r"bash '\$MODE_CMD' (\S+)( --no-reboot)?", body)
    assert calls == [("$DISPLAY_MODE_DEFAULT", " --no-reboot")], calls


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
# MOVED PIN (US-652-b): the absent row was x11.
@pytest.mark.parametrize("mode,expected", [(None, "wayland"), ("x11", "x11"), ("wayland", "wayland")])
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


# ----------------------------------------------------------------------------
# US-652-a: the absent-mode-file default lives in deploy/lib/display-mode-default.sh
# ----------------------------------------------------------------------------

DEFAULT_LIB_REL = "deploy/lib/display-mode-default.sh"
DEFAULT_LIB = REPO_ROOT / DEFAULT_LIB_REL
CAPTURE_CMD = REPO_ROOT / "deploy" / "eclipse-capture-panel.sh"

# The FIVE shell readers of /etc/eclipse/display-mode; each sources the lib.
SHELL_READERS = (MODE_CMD, DEPLOY_SCRIPT, SPLASH_INSTALL, DASH_INSTALL, CAPTURE_CMD)

# A read_mode-style branch: an `-f "$MODE_FILE"` test whose else-branch is a
# literal x11 (`printf 'x11'`, or an assignment such as `SESS=x11`).
_MODE_FILE_TEST = re.compile(r'\[\[?\s+-f\s+"\$MODE_FILE"\s+\]\]?')
_LITERAL_X11_ELSE = re.compile(r"\belse\b\s*\n\s*(printf\s+['\"]?x11['\"]?|\w+=['\"]?x11['\"]?)\s*\n")
_FI_LINE = re.compile(r"\n[ \t]*fi\b[^\n]*\n")
_PRINTF_X11 = re.compile(r"printf\s+['\"]x11['\"]")


def _shellFiles() -> list[Path]:
    files = []
    for root in (REPO_ROOT / "deploy", REPO_ROOT / "src" / "pi" / "ui"):
        files.extend(p for p in root.rglob("*") if p.is_file() and p.suffix == ".sh")
    return sorted(p for p in files if p != DEFAULT_LIB)


def _shellFunctionBody(text: str, name: str) -> str:
    start = text.index(f"{name}() {{")
    return text[start : text.index("\n}\n", start)]


def test_defaultLib_definesWaylandAndNothingElseRuns():
    """
    Given: deploy/lib/display-mode-default.sh
    When:  it is sourced under set -euo pipefail
    Then:  DISPLAY_MODE_DEFAULT is wayland (US-652-b; was x11) and its only
           statement is that assignment.
    """
    statements = [
        ln.strip() for ln in DEFAULT_LIB.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert statements == ["DISPLAY_MODE_DEFAULT=wayland"], statements

    result = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; . "$1"; printf "%s" "$DISPLAY_MODE_DEFAULT"',
         "_", _posix(DEFAULT_LIB)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "wayland"
    assert result.stderr == ""


def test_grepGate_noAbsentFileDefaultOutsideTheLib():
    """
    Given: every shell file in deploy/ and src/pi/ui/ except the lib
    When:  scanned for a read_mode-style absent-file default
    Then:  none remains; the only printf 'x11' is installed_dashboard_variant's
           (a unit-variant DETECTION, exempt by name); each of the FIVE shell
           readers names deploy/lib/display-mode-default.sh.
    """
    branches = []
    for path in _shellFiles():
        text = path.read_text(encoding="utf-8")
        for match in _MODE_FILE_TEST.finditer(text):
            # The if-block the test opens: up to its first `fi` line.
            end = _FI_LINE.search(text, match.end())
            block = text[match.start() : end.end() if end else len(text)]
            if _LITERAL_X11_ELSE.search(block):
                branches.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {block.strip()[:80]}")
    assert branches == [], branches

    printfs = []
    for path in _shellFiles():
        text = path.read_text(encoding="utf-8")
        exempt = ""
        if path == MODE_CMD:
            exempt = _shellFunctionBody(text, "installed_dashboard_variant")
        rest = text.replace(exempt, "") if exempt else text
        printfs.extend(f"{path.relative_to(REPO_ROOT).as_posix()}: {m.group(0)}"
                       for m in _PRINTF_X11.finditer(rest))
    assert printfs == [], printfs

    for reader in SHELL_READERS:
        assert DEFAULT_LIB_REL in reader.read_text(encoding="utf-8"), (
            f"{reader.relative_to(REPO_ROOT).as_posix()} does not name {DEFAULT_LIB_REL}"
        )


DRIVE_CONSOLE = REPO_ROOT / "tools" / "imu" / "drive_console.py"


def test_grepGate_driveConsoleReadDisplayMode_keepsNoDefault():
    """
    US-652-b extends the gate (Atlas Q1 (c)): tools/imu/drive_console.py
    readDisplayMode is not a reader of the lib -- tools/ is not deployed -- so
    its absent branch returns NO literal mode; it raises naming the command.
    """
    text = DRIVE_CONSOLE.read_text(encoding="utf-8")
    start = text.index("def readDisplayMode(")
    body = text[start : text.index("\ndef ", start + 1)]
    absent = body[body.index("if not path.exists():") :]
    absent = absent[: absent.index("\n    mode = ")]

    assert not re.search(r"""return\s+['"](x11|wayland)['"]""", absent), absent
    assert "raise ValueError(" in absent and "sudo eclipse-display-mode x11|wayland" in absent


def test_grepGate_catchesTheOldReadModeBranch():
    """The gate's own pattern matches the pre-US-652-a read_mode shape."""
    old = ('    if [ -f "$MODE_FILE" ]; then\n'
           "        tr -d '[:space:]' < \"$MODE_FILE\"\n"
           "    else\n"
           "        printf 'x11'\n"
           "    fi\n")
    assert _MODE_FILE_TEST.search(old)
    assert _LITERAL_X11_ELSE.search(old)
    assert _LITERAL_X11_ELSE.search("        else\n            SESS=x11\n        fi\n")


@pytest.mark.parametrize("args", [("status",), ("trigger",), ("wayland", "--no-reboot")],
                         ids=["status", "trigger", "wayland"])
def test_modeCommand_libAbsent_exitsNonZeroNamingTheLib_nothingChanged(rig, args):
    """
    Given: eclipse-display-mode.sh in a tree with no deploy/lib/display-mode-default.sh
    When:  any verb runs
    Then:  non-zero, stderr names the lib; no unit, mode file or lightdm.conf is
           touched and systemctl is never called.
    """
    lonely = rig["root"] / "lonely" / "deploy" / "eclipse-display-mode.sh"
    lonely.parent.mkdir(parents=True)
    shutil.copyfile(MODE_CMD, lonely)
    before = _snapshot(rig)

    env = dict(os.environ)
    env["PATH"] = _posix(rig["bin"]) + os.pathsep + env.get("PATH", "")
    env.update({
        "FAKE_STATE": _posix(rig["state"]),
        "KIOSK_MODE_FILE": _posix(rig["modeFile"]),
        "KIOSK_TREE": _posix(rig["tree"]),
        "KIOSK_SYSTEMD_DIR": _posix(rig["systemd"]),
        "KIOSK_USER": "mcornelison",
        "KIOSK_AUTOSTART_DIR": _posix(rig["autostart"]),
        "KIOSK_LIGHTDM_CONF": _posix(rig["conf"]),
        "KIOSK_SESSION_FILE": _posix(rig["sessionFile"]),
        "KIOSK_LABWC_BIN": _posix(rig["labwc"]),
        "KIOSK_STATE_DIR": _posix(rig["obdState"]),
    })
    result = subprocess.run(["bash", _posix(lonely), *args], capture_output=True,
                            text=True, encoding="utf-8", timeout=60, env=env)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "lib/display-mode-default.sh" in result.stderr, result.stderr
    assert "nothing changed" in result.stderr, result.stderr
    assert _snapshot(rig) == before
    assert _systemctlLog(rig) == []
    assert not rig["modeFile"].exists()


@pytest.mark.parametrize("script,prefix", KITS)
def test_kitInstaller_libAbsent_exitsNonZeroNamingTheLib(tmp_path, script, prefix):
    """A kit outside a tree that carries deploy/lib refuses loudly, never a silent x11."""
    kitDir = tmp_path / "tree" / script.relative_to(REPO_ROOT).parent
    kitDir.mkdir(parents=True)
    lonely = kitDir / "install.sh"
    shutil.copyfile(script, lonely)

    result = _runKit(lonely, prefix, tmp_path, mode=None)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "lib/display-mode-default.sh" in result.stderr, result.stderr
    assert "nothing changed" in result.stderr, result.stderr
    assert "session type" not in result.stdout


def _resolverShell(libPath: str) -> str:
    """deploy-pi.sh's kiosk_mode_resolver, defined and called with libPath."""
    func = _shellFunctionBody(DEPLOY_SCRIPT.read_text(encoding="utf-8"), "kiosk_mode_resolver")
    return f"{func}\n}}\nkiosk_mode_resolver '{libPath}'\n"


def _runResolver(tmp_path: Path, libPath: str, modeFile: Path) -> subprocess.CompletedProcess:
    script = tmp_path / "resolver.sh"
    script.write_text(_resolverShell(libPath), encoding="utf-8", newline="\n")
    emitted = subprocess.run(["bash", _posix(script)], capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
    assert emitted.returncode == 0, emitted.stderr
    env = dict(os.environ)
    env["KIOSK_MODE_FILE"] = _posix(modeFile)
    env["KIOSK_DETECTED_SESSION"] = ""
    return subprocess.run(["bash", "-c", emitted.stdout + '\nprintf "SESS=%s" "$SESS"\n'],
                          capture_output=True, text=True, encoding="utf-8", timeout=30, env=env)


def test_deployResolver_absentFile_readsTheLibDefault(tmp_path):
    result = _runResolver(tmp_path, _posix(DEFAULT_LIB), tmp_path / "display-mode")

    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("SESS=wayland"), result.stdout  # MOVED PIN (US-652-b)


def test_deployResolver_libAbsent_exitsNonZeroNamingTheLib(tmp_path):
    missing = tmp_path / "deploy" / "lib" / "display-mode-default.sh"

    result = _runResolver(tmp_path, _posix(missing), tmp_path / "display-mode")

    assert result.returncode != 0, result.stdout
    assert "lib/display-mode-default.sh" in result.stderr, result.stderr
    assert "nothing changed" in result.stderr, result.stderr
    assert "SESS=" not in result.stdout


def test_deployKioskStep_passesTheDeployedLibToTheResolver():
    """On the Pi the resolver sources the SYNCED tree's lib; the dry-run the local one."""
    body = _stepBody("step_install_ui_kiosk_units")
    assert '$(kiosk_mode_resolver "${PI_PATH}/' + DEFAULT_LIB_REL + '")' in body
    assert '$(kiosk_mode_resolver "$REPO_ROOT/' + DEFAULT_LIB_REL + '")' in body


# ----------------------------------------------------------------------------
# US-652-b: deploy-pi.sh converges a car with NO mode file (kiosk_mode_converge)
# ----------------------------------------------------------------------------

# On the desk rig `sudo` just runs its arguments (the env passes straight through).
FAKE_SUDO = '#!/usr/bin/env bash\nexec "$@"\n'


def _runConverge(rig: dict) -> subprocess.CompletedProcess:
    """deploy-pi.sh's resolver + converge shell, emitted as the kiosk step emits
    them on the Pi, run against the rig with the REAL eclipse-display-mode.sh."""
    convBin = rig["root"] / "converge-bin"
    convBin.mkdir(exist_ok=True)
    (convBin / "sudo").write_text(FAKE_SUDO, encoding="utf-8", newline="\n")
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    emitter = convBin / "emit.sh"
    emitter.write_text(
        _shellFunctionBody(text, "kiosk_mode_resolver") + "\n}\n"
        + _shellFunctionBody(text, "kiosk_mode_converge") + "\n}\n"
        + f"kiosk_mode_resolver '{_posix(DEFAULT_LIB)}'\n"
        + f"kiosk_mode_converge '{_posix(MODE_CMD)}' 'mcornelison'\n",
        encoding="utf-8", newline="\n",
    )
    emitted = subprocess.run(["bash", _posix(emitter)], capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
    assert emitted.returncode == 0, emitted.stderr
    env = dict(os.environ)
    env.pop("KIOSK_UID", None)
    env.pop("KIOSK_USER", None)
    env.update({
        "PATH": os.pathsep.join([_posix(convBin), _posix(rig["bin"]), os.environ.get("PATH", "")]),
        "FAKE_STATE": _posix(rig["state"]),
        "KIOSK_MODE_FILE": _posix(rig["modeFile"]),
        "KIOSK_TREE": _posix(rig["tree"]),
        "KIOSK_SYSTEMD_DIR": _posix(rig["systemd"]),
        "KIOSK_AUTOSTART_DIR": _posix(rig["autostart"]),
        "KIOSK_LIGHTDM_CONF": _posix(rig["conf"]),
        "KIOSK_SESSION_FILE": _posix(rig["sessionFile"]),
        "KIOSK_LABWC_BIN": _posix(rig["labwc"]),
        "KIOSK_STATE_DIR": _posix(rig["obdState"]),
        "KIOSK_DETECTED_SESSION": "",
    })
    return subprocess.run(["bash", "-c", emitted.stdout + '\nprintf "SESS=%s" "$SESS"\n'],
                          capture_output=True, text=True, encoding="utf-8", timeout=120, env=env)


def _rigSnapshot(rig: dict) -> dict[str, bytes]:
    """_snapshot without the converge harness's own fake sudo + emitter."""
    harness = str(rig["root"] / "converge-bin")
    return {k: v for k, v in _snapshot(rig).items() if not k.startswith(harness)}


def test_deployConverge_absentFile_switchesOnceToWayland_noReboot(rig):
    """
    Given: a fresh card -- NO mode file, lightdm.conf at rpd-x, X11 units
    When:  the deploy's kiosk step resolves the mode
    Then:  `eclipse-display-mode wayland --no-reboot` runs once: priors rpd-x
           recorded, both [Seat:*] keys eclipse-kiosk, file = wayland, the kits
           forced to wayland; nothing reboots or restarts lightdm.
    """
    result = _runConverge(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.endswith("SESS=wayland"), result.stdout
    assert result.stdout.count(SWITCH_LINE) == 1, result.stdout
    assert rig["modeFile"].read_text(encoding="utf-8") == "wayland\n"
    assert rig["conf"].read_text(encoding="utf-8") == _withSeatKeys(KIOSK, KIOSK)
    assert rig["stateFile"].read_text(encoding="utf-8") == (
        "autologin-session=rpd-x\nuser-session=rpd-x\n")
    kits = (rig["state"] / "kits.log").read_text(encoding="utf-8")
    assert "splash session=wayland user=mcornelison" in kits
    assert "dashboard session=wayland user=mcornelison" in kits
    log = _systemctlLog(rig)
    assert "reboot" not in log, log
    assert not [ln for ln in log if ln.split()[0] in ("restart", "stop", "start")], log
    assert _enabledPaths(rig) == [SOCKET_PATH]


@pytest.mark.parametrize("mode", ["x11", "wayland"])
def test_deployConverge_explicitFile_isNeverChanged(rig, mode):
    """
    Given: an EXPLICIT mode file (x11 = the CIO's revert; wayland = today's car)
           and lightdm.conf at rpd-x
    When:  the deploy's kiosk step resolves the mode
    Then:  no switch: the mode file and lightdm.conf are byte-identical, nothing
           is recorded or enabled, and the file's mode is what the kits get.
    """
    _writeMode(rig, mode)
    modeBefore = rig["modeFile"].read_bytes()
    confBefore = rig["conf"].read_bytes()

    result = _runConverge(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.endswith(f"SESS={mode}"), result.stdout
    assert f"mode file present: {mode}, no switch" in result.stdout
    assert "--no-reboot" not in result.stdout
    assert rig["modeFile"].read_bytes() == modeBefore
    assert rig["conf"].read_bytes() == confBefore
    assert not rig["stateFile"].exists()
    assert not (rig["state"] / "kits.log").exists()
    assert _systemctlLog(rig) == []


def test_deployConverge_garbageFile_warnsAndSkips_noSwitch(rig):
    _writeMode(rig, "1920x1080")
    before = _rigSnapshot(rig)

    result = _runConverge(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.endswith("SESS="), result.stdout
    assert "WARN" in result.stderr and "skipping kiosk-unit install" in result.stderr
    assert "--no-reboot" not in result.stdout
    assert _rigSnapshot(rig) == before
    assert _systemctlLog(rig) == []


@pytest.mark.parametrize("breaker", [_breakLabwc, _breakNoSeatSection],
                         ids=["labwc-missing", "no-seat-section"])
def test_deployConverge_switchPreflightFails_printsTheError_noKioskChange(rig, breaker):
    """
    Given: no mode file, and the switch's own pre-flight cannot pass
    When:  the deploy's kiosk step converges
    Then:  the error is printed, the deploy continues (exit 0) with SESS empty --
           so no kiosk unit is installed -- and nothing on the rig changed.
    """
    breaker(rig)
    before = _rigSnapshot(rig)

    result = _runConverge(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.endswith("SESS="), result.stdout
    assert "nothing changed" in result.stderr, result.stderr
    assert "--no-reboot failed -- deploy continues with no kiosk change" in result.stderr
    assert _rigSnapshot(rig) == before
    assert not rig["modeFile"].exists()
    assert _modeChanges(rig) == []


def test_deployKioskStep_convergesRightAfterTheResolver_onThePi():
    body = _stepBody("step_install_ui_kiosk_units")
    resolver = body.index('$(kiosk_mode_resolver "${PI_PATH}/')
    converge = body.index('$(kiosk_mode_converge "${PI_PATH}/${modeCmd}" "${PI_USER}")')
    assert resolver < converge < body.index("SPLASH_FORCE_SESSION=")
