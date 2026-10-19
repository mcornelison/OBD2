################################################################################
# File Name: test_compositor_unit.py
# Purpose/Description: US-649-b -- eclipse-compositor.service (labwc in the
#                      display-manager slot) hosts the Wayland kiosk. Covers the
#                      unit's directives, its ExecStartPost socket wait, the
#                      isolated labwc config, the three chromium .wayland units
#                      binding to it, and the deploy-pi.sh shipping + install
#                      step (whitelist, tar list, fail-loud on a missing rc.xml,
#                      never enabled by the deploy).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-649-b) | Initial implementation (Sprint 102 V0.30.1).
# ================================================================================
################################################################################

"""Compositor unit + labwc config + deploy tests (US-649-b).

Desk-only: the unit is parsed as text, its socket wait runs under a fake
``sleep`` against a temp runtime dir, and deploy-pi.sh runs in --dry-run.
No ssh, no Pi, no root, no labwc.
"""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-pi.sh"
COMPOSITOR_UNIT = DEPLOY_DIR / "eclipse-compositor.service"
LABWC_DIR = DEPLOY_DIR / "labwc"
RC_XML = LABWC_DIR / "rc.xml"
AUTOSTART = LABWC_DIR / "autostart"

SOCKET_PATH = "/run/user/1000/wayland-0"
RUNTIME_DIR = "/run/user/1000"
STEP = "step_install_compositor_unit"

WAYLAND_UNITS = [
    REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "dashboard.service.wayland",
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "splash-boot.service.wayland",
    REPO_ROOT / "src" / "pi" / "ui" / "splash" / "splash-grace.service.wayland",
]

needsBash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _posix(path: Path) -> str:
    return path.as_posix()


def _directives(text: str) -> dict[str, list[tuple[str, str]]]:
    """Parse a systemd unit into {section: [(key, value), ...]}.

    Comments and blank lines are dropped; backslash continuations are joined.
    Order and repeats are kept, as systemd keeps them.
    """
    sections: dict[str, list[tuple[str, str]]] = {}
    current = ""
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not pending and (not line or line.startswith("#")):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line = pending + line
        pending = ""
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, [])
            continue
        key, _, value = line.partition("=")
        sections.setdefault(current, []).append((key.strip(), value.strip()))
    return sections


def _values(text: str, section: str, key: str) -> list[str]:
    return [v for k, v in _directives(text).get(section, []) if k == key]


def _words(text: str, section: str, key: str) -> set[str]:
    """Every space-separated word of every ``key=`` line in ``section``."""
    return {w for v in _values(text, section, key) for w in v.split()}


def _unitText() -> str:
    return COMPOSITOR_UNIT.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# deploy/eclipse-compositor.service
# ----------------------------------------------------------------------------


def test_compositorUnit_carriesTheProjectFileHeader():
    """Like every sibling deploy/*.service, it opens with the header block."""
    text = _unitText()
    assert text.lstrip().startswith("#"), "no project file-header comment block"
    assert "US-649-b" in text


def test_compositorUnit_unitSection_ordersBehindPlymouthAndTheGpu():
    """
    Given: the unit file
    When:  its [Unit] section is parsed
    Then:  it orders after user sessions + both plymouth units, conflicts with
           plymouth-quit (the lightdm hand-off), and wants + orders after both
           DRM device nodes.
    """
    text = _unitText()
    after = _words(text, "Unit", "After")
    for unit in (
        "systemd-user-sessions.service",
        "plymouth-start.service",
        "plymouth-quit.service",
        "dev-dri-card0.device",
        "dev-dri-renderD128.device",
    ):
        assert unit in after, f"After= is missing {unit}"
    assert _words(text, "Unit", "Conflicts") == {"plymouth-quit.service"}
    assert {"dev-dri-card0.device", "dev-dri-renderD128.device"} <= _words(text, "Unit", "Wants")


def test_compositorUnit_serviceSection_isALoginSessionOnTty7():
    """Every [Service] line Atlas ruled, verbatim."""
    text = _unitText()
    expected = {
        "User": "mcornelison",
        "PAMName": "login",
        "TTYPath": "/dev/tty7",
        "TTYReset": "yes",
        "TTYVHangup": "yes",
        "StandardInput": "tty-fail",
        "UtmpIdentifier": "tty7",
        "ExecStart": "/usr/bin/labwc -C /etc/eclipse/labwc",
        "Restart": "on-failure",
    }
    for key, value in expected.items():
        assert _values(text, "Service", key) == [value], f"{key}= must be exactly {value!r}"
    assert "XDG_SESSION_TYPE=wayland" in _values(text, "Service", "Environment")


def test_compositorUnit_quitsPlymouthRetainingTheSplash():
    """The Plymouth hand-off: quit (keeping the last frame), failure tolerated."""
    text = _unitText()
    assert _values(text, "Service", "ExecStartPre") == ["-/usr/bin/plymouth quit --retain-splash"]


def test_compositorUnit_takesTheDisplayManagerSlot():
    """[Install] Alias=display-manager.service -- graphical.target pulls it."""
    text = _unitText()
    assert _values(text, "Install", "Alias") == ["display-manager.service"]
    assert not _values(text, "Install", "WantedBy"), (
        "the display-manager alias is the pull-in; a WantedBy= would start it in x11 mode too"
    )


def test_compositorUnit_userAndUidAreLiteral_noPlaceholders():
    """
    deploy/*.service convention (Atlas G1): deploy-pi.sh substitutes nothing,
    so the user and uid are literal and no __PI_ token may appear.
    """
    text = _unitText()
    assert "__PI_" not in text
    assert "User=mcornelison" in text
    assert SOCKET_PATH in text


# ----------------------------------------------------------------------------
# ExecStartPost: the wayland-0 socket wait
# ----------------------------------------------------------------------------

FAKE_SLEEP = """#!/usr/bin/env bash
echo "$1" >> "$FAKE_SLEEP_LOG"
"""


def _socketWaitArgv() -> list[str]:
    """The ExecStartPost command as systemd would exec it ($$ -> $)."""
    posts = _values(_unitText(), "Service", "ExecStartPost")
    assert len(posts) == 1, f"expected exactly one ExecStartPost, got {posts}"
    return shlex.split(posts[0].replace("$$", "$"))


def _runSocketWait(tmp_path: Path, runtimeDir: Path) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Run the socket wait against ``runtimeDir`` with ``sleep`` recorded, not slept."""
    argv = _socketWaitArgv()
    assert argv[:2] == ["/bin/sh", "-c"], f"ExecStartPost must be /bin/sh -c '...', got {argv[:2]}"
    script = argv[2]
    assert RUNTIME_DIR in script, "the wait must poll the literal /run/user/1000 runtime dir"
    script = script.replace(RUNTIME_DIR, _posix(runtimeDir))
    binDir = tmp_path / "bin"
    binDir.mkdir()
    (binDir / "sleep").write_text(FAKE_SLEEP, encoding="utf-8", newline="\n")
    log = tmp_path / "sleep.log"
    env = dict(os.environ)
    env["PATH"] = _posix(binDir) + os.pathsep + env.get("PATH", "")
    env["FAKE_SLEEP_LOG"] = _posix(log)
    result = subprocess.run(
        ["sh", "-c", script], capture_output=True, text=True, encoding="utf-8", timeout=60, env=env
    )
    sleeps = log.read_text(encoding="utf-8").split() if log.exists() else []
    return result, sleeps


@needsBash
def test_socketWait_noSocket_failsLoudAfterAFiveSecondBudget(tmp_path: Path):
    """
    Given: a runtime dir with no wayland-0
    When:  the ExecStartPost wait runs (sleep mocked)
    Then:  it exits non-zero, names the socket, and its sleeps total 5 s.
    """
    runtimeDir = tmp_path / "run"
    runtimeDir.mkdir()

    result, sleeps = _runSocketWait(tmp_path, runtimeDir)

    assert result.returncode != 0
    assert "wayland-0" in result.stderr
    assert sleeps, "the wait never slept -- it is not polling"
    assert abs(sum(float(s) for s in sleeps) - 5.0) < 1e-6, f"budget is {sum(map(float, sleeps))} s, not 5 s"


@needsBash
def test_socketWait_aRegularFileIsNotTheSocket(tmp_path: Path):
    """A plain file named wayland-0 is not a compositor socket (-S, not -e)."""
    runtimeDir = tmp_path / "run"
    runtimeDir.mkdir()
    (runtimeDir / "wayland-0").write_text("", encoding="utf-8")

    result, _ = _runSocketWait(tmp_path, runtimeDir)

    assert result.returncode != 0


@needsBash
@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="no AF_UNIX sockets on this platform")
def test_socketWait_socketPresent_succeedsWithoutSleeping(tmp_path: Path):
    """The socket already there -> exit 0 at once."""
    runtimeDir = tmp_path / "run"
    runtimeDir.mkdir()
    sock = socket.socket(socket.AF_UNIX)  # type: ignore[attr-defined]
    try:
        sock.bind(str(runtimeDir / "wayland-0"))
        result, sleeps = _runSocketWait(tmp_path, runtimeDir)
    finally:
        sock.close()

    assert result.returncode == 0, result.stderr
    assert sleeps == []


# ----------------------------------------------------------------------------
# deploy/labwc/rc.xml + autostart
# ----------------------------------------------------------------------------

# labwc actions that act on windows or the session; none may be keybound.
WINDOW_ACTIONS = {
    "Close", "Kill", "Iconify", "Maximize", "ToggleMaximize", "UnMaximize",
    "ToggleFullscreen", "SetDecorations", "ToggleDecorations", "NextWindow",
    "PreviousWindow", "Move", "Resize", "MoveTo", "ResizeTo", "MoveToEdge",
    "SnapToEdge", "GrowToEdge", "ShrinkToEdge", "ToggleAlwaysOnTop",
    "ToggleAlwaysOnBottom", "SendToDesktop", "GoToDesktop", "ShowMenu",
    "Exit", "Reconfigure", "Focus", "Raise", "Lower", "ToggleKeybinds",
    "VirtualOutputAdd", "VirtualOutputRemove", "ToggleSnapToRegion", "SnapToRegion",
}


def _rc() -> ET.Element:
    return ET.parse(RC_XML).getroot()


def _local(tag: str) -> str:
    """Strip any XML namespace from a tag."""
    return tag.rsplit("}", 1)[-1]


def _findAll(root: ET.Element, name: str) -> list[ET.Element]:
    return [e for e in root.iter() if _local(e.tag) == name]


def test_rcXml_parses_asALabwcConfig():
    root = _rc()
    assert _local(root.tag) == "labwc_config"


def test_rcXml_hasNoRootMenuBinding():
    """No ShowMenu anywhere, and no Root-context mouse bindings at all."""
    root = _rc()
    actions = [a.get("name") for a in _findAll(root, "action")]
    assert "ShowMenu" not in actions
    for ctx in _findAll(root, "context"):
        assert ctx.get("name") != "Root", "a Root-context binding is a desktop click target"


def test_rcXml_neverLoadsLabwcDefaultBindings():
    """
    labwc loads its DEFAULT keybinds (Alt-Tab, Super-Return, ...) and mouse binds
    (the right-click root menu) when rc.xml defines none, or on <default/>. So
    both lists must be non-empty and neither may ask for the defaults.
    """
    root = _rc()
    assert not _findAll(root, "default"), "<default/> loads labwc's stock bindings"
    assert _findAll(root, "keybind"), "zero keybinds -> labwc loads its default keybinds"
    assert _findAll(root, "mousebind"), "zero mousebinds -> labwc loads its default (root menu) binds"


def test_rcXml_hasNoWindowKeybinds():
    root = _rc()
    for kb in _findAll(root, "keybind"):
        names = {a.get("name") for a in _findAll(kb, "action")}
        assert not names & WINDOW_ACTIONS, f"keybind {kb.get('key')} drives a window: {names}"


def test_rcXml_hasNoDecorations():
    """Client-side decoration preferred AND server decorations off for every window."""
    root = _rc()
    decorations = [e.text.strip() for e in _findAll(root, "decoration") if e.text]
    assert decorations == ["client"]
    rules = [r for r in _findAll(root, "windowRule") if r.get("identifier") == "*"]
    assert rules and all(r.get("serverDecoration") == "no" for r in rules)


def test_autostart_isEmpty():
    """labwc runs autostart as a shell script; it must start nothing."""
    assert AUTOSTART.is_file()
    assert AUTOSTART.read_bytes() == b""


# ----------------------------------------------------------------------------
# The three chromium .wayland units bind to the compositor
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("unit", WAYLAND_UNITS, ids=lambda p: p.name)
def test_waylandUnit_noLongerOrdersAfterGraphicalTarget(unit: Path):
    """After=graphical.target queued the kiosk behind multi-user (18.73 s)."""
    text = unit.read_text(encoding="utf-8")
    assert "graphical.target" not in _words(text, "Unit", "After")


def test_splashBootWayland_keepsGraphicalTargetOnlyAsItsPullIn():
    text = WAYLAND_UNITS[1].read_text(encoding="utf-8")
    assert _values(text, "Install", "WantedBy") == ["graphical.target"]
    for key in ("After", "Wants", "Requires", "BindsTo"):
        assert "graphical.target" not in _words(text, "Unit", key), f"{key}= still names graphical.target"


# ----------------------------------------------------------------------------
# deploy-pi.sh: ship deploy/labwc, install it + the unit, never enable
# ----------------------------------------------------------------------------


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _rsyncBlock() -> str:
    text = _deployText()
    start = text.index("--include=config.json")
    return text[start : text.index('-e "ssh -p ${PI_PORT}"', start)]


def _stepBody(name: str) -> str:
    text = _deployText()
    start = text.index(f"{name}() {{")
    return text[start : text.index("\n}\n", start)]


def test_rsyncWhitelist_shipsTheLabwcDirAndItsContents():
    block = _rsyncBlock()
    finalExclude = block.index("--exclude=* ")
    for rule in ("--include=deploy/labwc/ ", "--include=deploy/labwc/*** "):
        assert rule in block, f"rsync whitelist lacks {rule.strip()}"
        assert block.index(rule) < finalExclude, f"{rule.strip()} must precede --exclude=*"


def test_tarFallback_namesTheLabwcDirBeforeDeploy():
    text = _deployText()
    assert "./deploy/labwc ./deploy )" in text


def test_compositorStep_neverEnablesTheCompositor():
    """Only eclipse-display-mode enables it; the deploy leaves the car on x11."""
    body = _stepBody(STEP)
    assert "systemctl enable" not in body
    assert "systemctl start" not in body and "systemctl restart" not in body
    assert "/etc/eclipse/labwc" in body
    assert "eclipse-compositor.service" in body


def test_compositorStep_isWiredBeforeTheKioskUnits():
    """The .wayland units BindsTo= it and eclipse-display-mode pre-flights it."""
    text = _deployText()
    call = f"\n{STEP}\n"
    assert call in text, f"{STEP} is defined but never called"
    assert text.rindex(call) < text.rindex("\nstep_install_ui_kiosk_units\n")


def _isolatedDeploy(tmp_path: Path, *, withLabwc: bool) -> subprocess.CompletedProcess:
    """deploy-pi.sh --dry-run from a tmp copy, as tests/deploy/test_deploy_pi.sh does."""
    deployDir = tmp_path / "deploy"
    deployDir.mkdir()
    for name in ("deploy-pi.sh", "addresses.sh", "os-trim.manifest"):
        shutil.copy(DEPLOY_DIR / name, deployDir / name)
    if withLabwc:
        shutil.copytree(LABWC_DIR, deployDir / "labwc")
    (deployDir / "deploy.conf").write_text(
        "PI_HOST=192.0.2.1\nPI_USER=nobody\nPI_PATH=/tmp/will-never-exist\nPI_PORT=22\n",
        encoding="utf-8",
        newline="\n",
    )
    return subprocess.run(
        ["bash", _posix(deployDir / "deploy-pi.sh"), "--dry-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


@needsBash
def test_deployDryRun_missingRcXml_failsLoudNamingThePath(tmp_path: Path):
    """
    Given: a tree with no deploy/labwc/rc.xml
    When:  deploy-pi.sh --dry-run runs
    Then:  non-zero exit; an ERROR names the missing path; no later step ran.
    """
    result = _isolatedDeploy(tmp_path, withLabwc=False)
    out = result.stdout
    assert result.returncode != 0, out
    # bash prints the path in its own form (/tmp/... under msys), so match the
    # line by its prefix and its tail inside THIS test's tmp dir.
    errors = [ln for ln in out.splitlines() if ln.startswith("ERROR: labwc config not found: ")]
    assert errors, out[-2000:]
    assert f"{tmp_path.name}/deploy/labwc/rc.xml" in errors[0]
    assert "chromium kiosk units" not in out, "the deploy carried on past the compositor step"


@needsBash
def test_deployDryRun_withRcXml_installsUnitAndConfig_enablesNothing(tmp_path: Path):
    result = _isolatedDeploy(tmp_path, withLabwc=True)
    out = result.stdout
    assert result.returncode == 0, out[-2000:]
    start = out.index("--- Step: Installing eclipse-compositor")
    section = out[start : out.index("--- Step:", start + 1)]
    assert "/etc/eclipse/labwc" in section
    assert "/etc/systemd/system/eclipse-compositor.service" in section
    assert "eclipse-display-mode wayland" in section, "the dry-run must say who enables it"
    assert "systemctl enable" not in section
