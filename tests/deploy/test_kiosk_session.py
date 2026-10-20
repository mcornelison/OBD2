################################################################################
# File Name: test_kiosk_session.py
# Purpose/Description: US-649-d -- the Wayland kiosk is a lightdm session (design
#                      A, CIO 2026-10-16). Covers the eclipse-kiosk.desktop
#                      session file, the isolated labwc config it runs, the
#                      three chromium .wayland units' ordering, and the
#                      deploy-pi.sh shipping + install step (whitelist, tar list,
#                      fail-loud on a missing rc.xml, the retired compositor unit
#                      never named).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-649-b) | The labwc, .wayland-unit and deploy tests began
#               |              | in tests/deploy/test_compositor_unit.py.
# 2026-10-19    | Rex (US-649-d) | Replaces test_compositor_unit.py: the labwc,
#               |              | .wayland-unit, sync and fail-loud tests MOVED here;
#               |              | the step tests rewritten for
#               |              | step_install_kiosk_session; the .desktop content
#               |              | and dry-run session-path tests added. The
#               |              | compositor unit-content and socket-wait tests
#               |              | retired with deploy/eclipse-compositor.service.
# ================================================================================
################################################################################

"""Kiosk session file + labwc config + deploy tests (US-649-d).

Desk-only: files are parsed as text and deploy-pi.sh runs in --dry-run from an
isolated temp copy. No ssh, no Pi, no root, no labwc.
"""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-pi.sh"
LABWC_DIR = DEPLOY_DIR / "labwc"
RC_XML = LABWC_DIR / "rc.xml"
AUTOSTART = LABWC_DIR / "autostart"
SESSION_FILE = DEPLOY_DIR / "wayland-sessions" / "eclipse-kiosk.desktop"

# Where lightdm looks for Wayland sessions (design note 2026-10-16, part 1).
SESSION_TARGET = "/usr/share/wayland-sessions/eclipse-kiosk.desktop"
STEP = "step_install_kiosk_session"
OLD_STEP = "step_install_compositor_unit"

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


# ----------------------------------------------------------------------------
# deploy/wayland-sessions/eclipse-kiosk.desktop
# ----------------------------------------------------------------------------


def test_sessionFile_hasExactlyTheFourDesignALines():
    """
    Given: the session file
    When:  comments and blank lines are dropped
    Then:  exactly the [Desktop Entry] header, Name, Exec and Type -- the Exec
           runs labwc on the isolated kiosk config, with no systemd-cat wrapper.
    """
    text = SESSION_FILE.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert lines == [
        "[Desktop Entry]",
        "Name=Eclipse kiosk",
        "Exec=/usr/bin/labwc -C /etc/eclipse/labwc",
        "Type=Application",
    ]
    assert "systemd-cat" not in text


def test_sessionFile_commentsCiteDesignA():
    """Any leading comment names its source: CIO 2026-10-16 design A."""
    comments = [ln for ln in SESSION_FILE.read_text(encoding="utf-8").splitlines() if ln.startswith("#")]
    assert comments, "the session file should cite its design ruling"
    assert any("2026-10-16" in ln for ln in comments)


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
# The three chromium .wayland units: not queued behind graphical.target
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
# deploy-pi.sh: ship deploy/labwc + deploy/wayland-sessions, install both
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


def _code(body: str) -> str:
    """The step body without its comment lines -- prose is not behaviour."""
    return "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))


@pytest.mark.parametrize("subdir", ["labwc", "wayland-sessions"])
def test_rsyncWhitelist_shipsTheDirAndItsContents(subdir: str):
    block = _rsyncBlock()
    finalExclude = block.index("--exclude=* ")
    for rule in (f"--include=deploy/{subdir}/ ", f"--include=deploy/{subdir}/*** "):
        assert rule in block, f"rsync whitelist lacks {rule.strip()}"
        assert block.index(rule) < finalExclude, f"{rule.strip()} must precede --exclude=*"


def test_tarFallback_namesLabwcAndWaylandSessionsBeforeDeploy():
    text = _deployText()
    assert "./deploy/labwc ./deploy/wayland-sessions ./deploy )" in text


def test_deployScript_neverNamesTheRetiredCompositor():
    """The car's existing unit is left for US-649-e's mode switch to retire."""
    text = _deployText()
    assert "eclipse-compositor" not in text
    assert f"{OLD_STEP}" not in text


def test_kioskSessionStep_installsTheSessionFileSyncIfChanged():
    """cmp -s, then install -m 644 -- the step_install_journald_persistent pattern."""
    body = _stepBody(STEP)
    assert SESSION_TARGET in body
    assert "deploy/wayland-sessions/eclipse-kiosk.desktop" in body
    assert "cmp -s" in body
    assert "install -m 644" in body
    assert "/etc/eclipse/labwc" in body


def test_kioskSessionStep_startsEnablesAndRemovesNothing():
    """No systemctl call on the car from this step (scope fence)."""
    body = _code(_stepBody(STEP))
    assert "systemctl" not in body
    assert "eclipse-compositor" not in body
    assert "sudo rm" not in body


def test_kioskSessionStep_hasNoWorkstationCheckForTheSessionFile():
    """
    Only rc.xml fails loud on the workstation; the .desktop is checked on the Pi
    after the sync, so isolated --dry-run trees without it keep working.
    """
    body = _code(_stepBody(STEP))
    local = body[: body.index("if $DRY_RUN")]
    checks = [ln.strip() for ln in local.splitlines() if "[ ! -f" in ln or "[ -f" in ln]
    assert checks == ['if [ ! -f "$rcXml" ]; then'], checks


def test_kioskSessionStep_isWiredBeforeTheKioskUnits():
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
    Then:  exit 12; an ERROR names the missing path; no later step ran.
    """
    result = _isolatedDeploy(tmp_path, withLabwc=False)
    out = result.stdout
    assert result.returncode == 12, out[-2000:]
    # bash prints the path in its own form (/tmp/... under msys), so match the
    # line by its prefix and its tail inside THIS test's tmp dir.
    errors = [ln for ln in out.splitlines() if ln.startswith("ERROR: labwc config not found: ")]
    assert errors, out[-2000:]
    assert f"{tmp_path.name}/deploy/labwc/rc.xml" in errors[0]
    assert "chromium kiosk units" not in out, "the deploy carried on past the kiosk-session step"


@needsBash
def test_deployDryRun_namesTheSessionPath_andNeverTheCompositor(tmp_path: Path):
    """
    Given: an isolated tree carrying deploy/labwc but NOT deploy/wayland-sessions
    When:  deploy-pi.sh --dry-run runs
    Then:  exit 0; the step's section names the labwc config dir and the session
           install path; no line anywhere names eclipse-compositor.
    """
    result = _isolatedDeploy(tmp_path, withLabwc=True)
    out = result.stdout
    assert result.returncode == 0, out[-2000:]
    start = out.index("--- Step: Installing the eclipse-kiosk Wayland session")
    section = out[start : out.index("--- Step:", start + 1)]
    assert "/etc/eclipse/labwc" in section
    assert any(SESSION_TARGET in ln and ln.startswith("DRY-RUN") for ln in section.splitlines())
    assert "systemctl" not in section
    assert "eclipse-compositor" not in out
