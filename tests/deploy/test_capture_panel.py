################################################################################
# File Name: test_capture_panel.py
# Purpose/Description: US-650 -- eclipse-capture-panel screenshots the running
#                      panel in either display mode: it reads
#                      /etc/eclipse/display-mode (absent -> wayland since
#                      US-652-b) and runs grim
#                      (wayland) or scrot (x11) as the kiosk user, writes
#                      /tmp/eclipse-panel-<utc>.png and prints that path.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-650) | Initial implementation (Sprint 102 V0.30.1).
# 2026-10-25    | Rex (US-652-b) | MOVED PIN: an absent mode file is wayland
#               |                | (grim); the x11 row is unchanged.
# ================================================================================
################################################################################

"""Panel-capture command tests (US-650).

Desk-only: grim, scrot and sudo are PATH recorders, the mode file and the
runtime root are redirected by the command's KIOSK_* overrides. No ssh, no Pi.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CAPTURE_CMD = REPO_ROOT / "deploy" / "eclipse-capture-panel.sh"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"

INSTALL_STEP = "step_install_capture_panel_command"
INSTALL_TARGET = "/usr/local/bin/eclipse-capture-panel"
OUTPUT_RE = re.compile(r"^/tmp/eclipse-panel-\d{8}T\d{6}Z\.png$")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")

# Capture-tool recorder: logs its argv and the display env it was handed, then
# writes a non-empty file at its last argument (the output path), as the real
# tool would. FAKE_CAPTURE_FAIL makes it exit non-zero and write nothing.
FAKE_TOOL = """#!/usr/bin/env bash
name="$(basename "$0")"
{
  echo "argv=$name $*"
  echo "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR-unset}"
  echo "WAYLAND_DISPLAY=${WAYLAND_DISPLAY-unset}"
  echo "DISPLAY=${DISPLAY-unset}"
} >> "$FAKE_STATE/$name.log"
[ -z "${FAKE_CAPTURE_FAIL:-}" ] || exit 1
for out; do :; done
printf 'PNG' > "$out"
"""

# sudo recorder: logs the call, then runs what follows `-u <user>`.
FAKE_SUDO = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_STATE/sudo.log"
[ "$1" = "-u" ] && shift 2
exec "$@"
"""


def _posix(path: Path) -> str:
    return path.as_posix()


@pytest.fixture()
def rig(tmp_path: Path) -> dict:
    """A fake Pi: PATH bin with grim/scrot/sudo recorders, runtime root, mode file."""
    state = tmp_path / "state"
    binDir = tmp_path / "bin"
    runtimeRoot = tmp_path / "run" / "user"
    for d in (state, binDir, runtimeRoot / "1000"):
        d.mkdir(parents=True)
    for name, body in (("grim", FAKE_TOOL), ("scrot", FAKE_TOOL), ("sudo", FAKE_SUDO)):
        (binDir / name).write_text(body, encoding="utf-8", newline="\n")
    return {
        "state": state,
        "bin": binDir,
        "runtimeRoot": runtimeRoot,
        "modeFile": tmp_path / "etc" / "eclipse" / "display-mode",
        "outputs": [],
    }


def _setMode(rig: dict, mode: str) -> None:
    rig["modeFile"].parent.mkdir(parents=True, exist_ok=True)
    rig["modeFile"].write_text(mode + "\n", encoding="utf-8")


def _addSocket(rig: dict) -> None:
    # The bench has no AF_UNIX; the command checks the path EXISTS (a stale
    # non-socket there makes grim fail -> capture_failed, still loud).
    (rig["runtimeRoot"] / "1000" / "wayland-0").write_text("", encoding="utf-8")


def _run(rig: dict, *, uid: str = "1000",
         extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = _posix(rig["bin"]) + os.pathsep + env.get("PATH", "")
    env["FAKE_STATE"] = _posix(rig["state"])
    env["KIOSK_MODE_FILE"] = _posix(rig["modeFile"])
    env["KIOSK_RUNTIME_ROOT"] = _posix(rig["runtimeRoot"])
    env["KIOSK_USER"] = "mcornelison"
    env["KIOSK_UID"] = uid
    for var in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "FAKE_CAPTURE_FAIL"):
        env.pop(var, None)
    env.update(extra or {})
    result = subprocess.run(
        ["bash", _posix(CAPTURE_CMD)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )
    printed = result.stdout.strip()
    if OUTPUT_RE.match(printed):
        rig["outputs"].append(printed)
    return result


@pytest.fixture(autouse=True)
def _cleanupCaptures(request):
    yield
    rig = request.node.funcargs.get("rig")
    for out in (rig or {}).get("outputs", []):
        subprocess.run(["bash", "-c", f"rm -f '{out}'"], timeout=30)


def _log(rig: dict, name: str) -> str:
    log = rig["state"] / f"{name}.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


def _currentUid() -> str:
    return subprocess.run(["bash", "-c", "id -u"], capture_output=True, text=True,
                          encoding="utf-8", timeout=30).stdout.strip()


# ----------------------------------------------------------------------------
# Happy paths
# ----------------------------------------------------------------------------


def test_wayland_runsGrimAsTheKioskUser_withTheWaylandEnv_andPrintsThePath(rig):
    """
    Given: mode wayland, the wayland-0 socket present, a fake grim
    When: eclipse-capture-panel runs
    Then: grim runs as the kiosk user with XDG_RUNTIME_DIR=/run/user/<uid> and
        WAYLAND_DISPLAY=wayland-0, writing the /tmp/eclipse-panel-<utc>.png it prints.
    """
    _setMode(rig, "wayland")
    _addSocket(rig)

    result = _run(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    printed = result.stdout.strip()
    assert OUTPUT_RE.match(printed), printed
    grim = _log(rig, "grim")
    assert f"argv=grim {printed}\n" in grim
    assert f"XDG_RUNTIME_DIR={_posix(rig['runtimeRoot'])}/1000\n" in grim
    assert "WAYLAND_DISPLAY=wayland-0\n" in grim
    assert _log(rig, "sudo").startswith("-u mcornelison ")
    assert _log(rig, "scrot") == ""


def test_absentFile_isWayland_runsGrim(rig):
    """MOVED PIN (US-652-b): the absent row of the x11 test below; an absent
    mode file means the lib's default, wayland -> grim, never scrot."""
    _addSocket(rig)

    result = _run(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    printed = result.stdout.strip()
    assert OUTPUT_RE.match(printed), printed
    grim = _log(rig, "grim")
    assert f"argv=grim {printed}\n" in grim
    assert "WAYLAND_DISPLAY=wayland-0\n" in grim
    assert _log(rig, "scrot") == ""


@pytest.mark.parametrize("mode", ["x11"], ids=["x11"])
def test_x11_orAbsentFile_runsScrotWithDisplay0(rig, mode):
    """An x11 mode file: scrot with DISPLAY=:0, as the kiosk user. (Its absent
    row moved to test_absentFile_isWayland_runsGrim, US-652-b.)"""
    if mode is not None:
        _setMode(rig, mode)

    result = _run(rig)

    assert result.returncode == 0, result.stdout + result.stderr
    printed = result.stdout.strip()
    assert OUTPUT_RE.match(printed), printed
    scrot = _log(rig, "scrot")
    assert f"argv=scrot {printed}\n" in scrot
    assert "DISPLAY=:0\n" in scrot
    assert "WAYLAND_DISPLAY=unset\n" in scrot
    assert _log(rig, "sudo").startswith("-u mcornelison ")
    assert _log(rig, "grim") == ""


def test_alreadyTheKioskUser_runsTheToolWithoutSudo(rig):
    uid = _currentUid()
    (rig["runtimeRoot"] / uid).mkdir(exist_ok=True)
    (rig["runtimeRoot"] / uid / "wayland-0").write_text("", encoding="utf-8")
    _setMode(rig, "wayland")

    result = _run(rig, uid=uid)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "argv=grim " in _log(rig, "grim")
    assert _log(rig, "sudo") == ""


# ----------------------------------------------------------------------------
# Named failure reasons
# ----------------------------------------------------------------------------


def test_wayland_noSocket_exitsNonZero_reasonNoSocket(rig):
    _setMode(rig, "wayland")

    result = _run(rig)

    assert result.returncode != 0
    assert "no_socket" in result.stderr
    assert result.stdout.strip() == ""
    assert _log(rig, "grim") == ""


@pytest.mark.parametrize("mode,tool", [("wayland", "grim"), ("x11", "scrot")])
def test_missingTool_exitsNonZero_reasonNoModeTool(rig, mode, tool):
    if shutil.which(tool) is not None:
        pytest.skip(f"a real {tool} is on PATH")
    _setMode(rig, mode)
    _addSocket(rig)
    (rig["bin"] / tool).unlink()

    result = _run(rig)

    assert result.returncode != 0
    assert "no_mode_tool" in result.stderr
    assert tool in result.stderr


def test_unknownModeFile_exitsNonZero_reasonNoModeTool(rig):
    """A mode with no capture tool (e.g. the HDMI WxH value) is refused, not defaulted."""
    _setMode(rig, "1920x1080")

    result = _run(rig)

    assert result.returncode != 0
    assert "no_mode_tool" in result.stderr
    assert _log(rig, "grim") == "" and _log(rig, "scrot") == ""


def test_toolFails_exitsNonZero_reasonCaptureFailed(rig):
    _setMode(rig, "x11")

    result = _run(rig, extra={"FAKE_CAPTURE_FAIL": "1"})

    assert result.returncode != 0
    assert "capture_failed" in result.stderr
    assert result.stdout.strip() == ""


def test_defaultLibAbsent_exitsNonZero_reasonNoDefaultLib(rig, tmp_path):
    """
    US-652-a: the absent-file default lives in deploy/lib/display-mode-default.sh.
    Given: no mode file, and a copy of the command with no deploy/lib beside it
    When:  it runs
    Then:  non-zero, reason no_default_lib naming the lib; no tool ran -- never a
           silent x11.
    """
    lonely = tmp_path / "lonely" / "deploy" / "eclipse-capture-panel.sh"
    lonely.parent.mkdir(parents=True)
    shutil.copyfile(CAPTURE_CMD, lonely)
    env = dict(os.environ)
    env["PATH"] = _posix(rig["bin"]) + os.pathsep + env.get("PATH", "")
    env["FAKE_STATE"] = _posix(rig["state"])
    env["KIOSK_MODE_FILE"] = _posix(rig["modeFile"])
    env["KIOSK_RUNTIME_ROOT"] = _posix(rig["runtimeRoot"])
    env["KIOSK_UID"] = "1000"

    result = subprocess.run(["bash", _posix(lonely)], capture_output=True, text=True,
                            encoding="utf-8", timeout=60, env=env)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "no_default_lib" in result.stderr
    assert "lib/display-mode-default.sh" in result.stderr
    assert result.stdout.strip() == ""
    assert _log(rig, "grim") == "" and _log(rig, "scrot") == ""


def test_captureCommand_namesTheDefaultLib():
    assert "deploy/lib/display-mode-default.sh" in CAPTURE_CMD.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# Read-only, and the deploy installs it
# ----------------------------------------------------------------------------


def test_captureCommand_isReadOnly():
    """It never writes the mode file, swaps units or touches the resolution pin."""
    text = CAPTURE_CMD.read_text(encoding="utf-8")
    assert "systemctl" not in text
    assert not re.search(r">\s*\"?\$MODE_FILE", text)
    assert "ECLIPSE_DISPLAY_MODE" not in text


def _stepBody(stepName: str) -> str:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = text.index(f"{stepName}() {{")
    return text[start : text.index("\n}\n", start)]


def test_deployInstallsTheCaptureCommandToUsrLocalBin():
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    calls = [ln for ln in text.splitlines() if ln.strip() == INSTALL_STEP]
    assert calls, f"{INSTALL_STEP} is defined but never invoked"
    body = _stepBody(INSTALL_STEP)
    assert INSTALL_TARGET in body
    assert "deploy/eclipse-capture-panel.sh" in body


def test_deployDryRun_announcesTheCaptureCommandInstall():
    result = subprocess.run(
        ["bash", _posix(DEPLOY_SCRIPT), "--dry-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=120,
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, result.stdout
    assert f"DRY-RUN would install wrapper -> {INSTALL_TARGET}" in result.stdout
