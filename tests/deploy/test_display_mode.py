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
    "eclipse-kiosk-start.service",
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
        for unit in ("eclipse-kiosk-start.service", SOCKET_PATH, X_READY_PATH):
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


def test_trigger_absentModeFile_isX11(rig):
    result = _runMode(rig, "trigger")

    assert result.returncode == 0, result.stdout + result.stderr
    assert _enabledPaths(rig) == [X_READY_PATH]
    assert (rig["autostart"] / X_READY_DESKTOP).exists()


def test_trigger_rendersTheUidFromIdOfTheKioskUser(rig):
    """The .path names /run/user/<id -u KIOSK_USER>/wayland-0 and starts the latch."""
    _runMode(rig, "trigger")

    socketPath = (rig["systemd"] / SOCKET_PATH).read_text(encoding="utf-8")
    assert "PathExists=/run/user/1000/wayland-0\n" in socketPath
    assert "Unit=eclipse-kiosk-start.service\n" in socketPath
    assert "__PI_UID__" not in socketPath
    xReady = (rig["systemd"] / X_READY_PATH).read_text(encoding="utf-8")
    assert "PathExists=/run/user/1000/eclipse-x-ready\n" in xReady


def test_trigger_autostartEntry_writesOnlyTheMarker(rig):
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


def test_status_absentFile_readsX11_onTodaysCar(rig):
    """An absent file means x11 this sprint -- today's car is consistent."""
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
