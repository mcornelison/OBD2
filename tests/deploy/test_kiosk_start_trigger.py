################################################################################
# File Name: test_kiosk_start_trigger.py
# Purpose/Description: US-651-a -- the kiosk starts on a readiness event, never a
#                      sleep-poll. Static checks on the latch
#                      (eclipse-kiosk-start.service), the two .path units and the
#                      X11 autostart entry; the no-sleep/no-until scan over every
#                      kiosk unit; and the splash installer's upgrade step (the
#                      graphical.target.wants symlink is removed) on a fixture root.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-24    | Rex (US-651-a) | Initial implementation (Atlas RULED 2026-10-24,
#               |                | option a: the declarative latch).
# ================================================================================
################################################################################

"""The kiosk start trigger: latch + .path units + autostart marker (US-651-a)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "deploy"
SPLASH_DIR = REPO_ROOT / "src" / "pi" / "ui" / "splash"
DASHBOARD_DIR = REPO_ROOT / "src" / "pi" / "ui" / "dashboard"
SPLASH_INSTALL = SPLASH_DIR / "install.sh"

LATCH = DEPLOY_DIR / "eclipse-kiosk-start.service"
SOCKET_PATH = DEPLOY_DIR / "eclipse-kiosk-socket.path"
X_READY_PATH = DEPLOY_DIR / "eclipse-x-ready.path"
X_READY_DESKTOP = DEPLOY_DIR / "eclipse-x-ready.desktop"

# Every unit on the kiosk start path, both display modes, plus the trigger units.
KIOSK_START_UNITS = [
    SPLASH_DIR / "splash-boot.service.wayland",
    SPLASH_DIR / "splash-boot.service.x11",
    SPLASH_DIR / "splash-grace.service.wayland",
    SPLASH_DIR / "splash-grace.service.x11",
    DASHBOARD_DIR / "dashboard.service.wayland",
    DASHBOARD_DIR / "dashboard.service.x11",
    LATCH,
    SOCKET_PATH,
    X_READY_PATH,
]


def _codeLines(text: str) -> list[str]:
    """Every line that is not a full-line comment (continuation lines included)."""
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", ";"))]


def _sections(text: str) -> dict[str, list[str]]:
    """``section -> [key=value, ...]`` for an INI-style unit, comments dropped."""
    sections: dict[str, list[str]] = {}
    current = ""
    for line in _codeLines(text):
        stripped = line.strip()
        if not stripped:
            continue
        match = re.fullmatch(r"\[(.+)\]", stripped)
        if match:
            current = match.group(1)
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(stripped)
    return sections


def _values(text: str, key: str) -> list[str]:
    return [ln.split("=", 1)[1] for ln in (s.strip() for s in _codeLines(text))
            if ln.startswith(f"{key}=")]


# ----------------------------------------------------------------------------
# NO TIMER: no sleep, no until on the start path
# ----------------------------------------------------------------------------


def test_kioskStartUnits_discoveryIsComplete():
    """The scan's input exists: nine files, none missing (a vacuous scan passes anything)."""
    missing = [p.name for p in KIOSK_START_UNITS if not p.is_file()]
    assert missing == []
    assert len(KIOSK_START_UNITS) == 9


@pytest.mark.parametrize("unit", KIOSK_START_UNITS, ids=lambda p: p.name)
def test_kioskStartUnit_hasNoSleepAndNoUntil(unit: Path):
    """Comment lines are skipped; every other line -- Exec*= and its continuations -- is read."""
    offenders = [
        ln for ln in _codeLines(unit.read_text(encoding="utf-8"))
        if re.search(r"\b(sleep|until)\b", ln)
    ]
    assert offenders == [], f"{unit.name}: {offenders}"


def test_noSleepScan_readsContinuationLines_negativeControl():
    """A sleep hidden on a continuation line is caught; the same word in a comment is not."""
    planted = (
        "# sleep in a comment is prose\n"
        "ExecStartPre=/bin/sh -c 'true; \\\n"
        "  sleep 1'\n"
    )
    hits = [ln for ln in _codeLines(planted) if re.search(r"\b(sleep|until)\b", ln)]
    assert hits == ["  sleep 1'"]


# ----------------------------------------------------------------------------
# The one-shot readiness checks that replace the polls
# ----------------------------------------------------------------------------


def test_splashBoot_neitherModeIsWantedByAnyTarget():
    """splash-boot has no [Install]: the latch, not graphical.target, pulls it in."""
    for name in ("splash-boot.service.wayland", "splash-boot.service.x11"):
        text = (SPLASH_DIR / name).read_text(encoding="utf-8")
        assert "Install" not in _sections(text), name
        assert _values(text, "WantedBy") == [], name


def test_splashBootX11_oneShotXsetCheck():
    text = (SPLASH_DIR / "splash-boot.service.x11").read_text(encoding="utf-8")
    assert _values(text, "ExecStartPre") == ["/usr/bin/xset q"]


def test_dashboardAndGraceWayland_oneShotSocketCheck():
    for path in (DASHBOARD_DIR / "dashboard.service.wayland",
                 SPLASH_DIR / "splash-grace.service.wayland"):
        assert _values(path.read_text(encoding="utf-8"), "ExecStartPre") == [
            "/usr/bin/test -S /run/user/__PI_UID__/wayland-0"
        ], path.name


def test_splashBootWayland_keepsItsHandOffs():
    text = (SPLASH_DIR / "splash-boot.service.wayland").read_text(encoding="utf-8")
    assert _values(text, "OnFailure") == ["eclipse-dashboard.service"]
    assert _values(text, "OnSuccess") == ["eclipse-dashboard.service"]


# ----------------------------------------------------------------------------
# The latch and the two .path units (Atlas RULED 2026-10-24, option a)
# ----------------------------------------------------------------------------


def test_latch_isADeclarativeOneshotThatWantsSplashBoot():
    sections = _sections(LATCH.read_text(encoding="utf-8"))
    assert set(sections) == {"Unit", "Service"}, "the latch has NO [Install] section"
    assert "Description=Kiosk start latch: starts splash-boot once per boot" in sections["Unit"]
    assert "Wants=splash-boot.service" in sections["Unit"]
    assert sections["Service"] == [
        "Type=oneshot",
        "RemainAfterExit=yes",
        "ExecStart=/bin/true",
    ]


@pytest.mark.parametrize("path,watched", [
    (SOCKET_PATH, "/run/user/__PI_UID__/wayland-0"),
    (X_READY_PATH, "/run/user/__PI_UID__/eclipse-x-ready"),
], ids=["socket", "x-ready"])
def test_pathUnit_watchesItsMarkerAndStartsTheLatch(path: Path, watched: str):
    sections = _sections(path.read_text(encoding="utf-8"))
    assert sections["Path"] == [f"PathExists={watched}", "Unit=eclipse-kiosk-start.service"]
    assert sections["Install"] == ["WantedBy=graphical.target"]
    assert "/run/user/1000" not in path.read_text(encoding="utf-8")


def _unitFilesUnder(root: Path) -> list[Path]:
    suffixes = (".service", ".path", ".timer", ".wayland", ".x11")
    return [p for p in root.rglob("*") if p.is_file() and p.name.endswith(suffixes)]


def test_noUnitNamesSplashBootAsItsPathTarget():
    """A PathExists .path on splash-boot would re-show the splash after every hand-off."""
    units = _unitFilesUnder(DEPLOY_DIR) + _unitFilesUnder(REPO_ROOT / "src" / "pi" / "ui")
    assert len(units) > 20, "the scan found too few unit files to mean anything"
    offenders = [
        p.relative_to(REPO_ROOT).as_posix() for p in units
        if "Unit=splash-boot.service" in [ln.strip() for ln in _codeLines(
            p.read_text(encoding="utf-8"))]
    ]
    assert offenders == []


# ----------------------------------------------------------------------------
# The X11 autostart entry
# ----------------------------------------------------------------------------


def test_xReadyDesktop_writesOnlyTheMarker():
    sections = _sections(X_READY_DESKTOP.read_text(encoding="utf-8"))
    entry = sections["Desktop Entry"]
    assert "Type=Application" in entry
    assert [ln for ln in entry if ln.startswith("Exec=")] == [
        "Exec=/usr/bin/touch /run/user/__PI_UID__/eclipse-x-ready"
    ]


# ----------------------------------------------------------------------------
# install.sh upgrade (Atlas fold 1): splash-boot is disabled every deploy
# ----------------------------------------------------------------------------

# Records each call; `disable` removes the unit's .wants entries under the fixture
# root as systemctl does, and returns 0 when there are none (systemctl's own exit).
FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "$*" >> "$FAKE_STATE/systemctl.log"
if [ "$1" = disable ]; then
  rm -f "$SPLASH_ROOT"/etc/systemd/system/*.wants/"$2"
fi
exit 0
"""


def _runSplashInstall(tmp_path: Path, root: Path) -> subprocess.CompletedProcess[str]:
    binDir = tmp_path / "bin"
    binDir.mkdir(exist_ok=True)
    (binDir / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env.update({
        "PATH": binDir.as_posix() + os.pathsep + env.get("PATH", ""),
        "FAKE_STATE": tmp_path.as_posix(),
        "SPLASH_ROOT": root.as_posix(),
        "SPLASH_FORCE_USER": "pi",
        "SPLASH_FORCE_UID": "1000",
        "SPLASH_FORCE_SESSION": "wayland",
        "SPLASH_FORCE_CHROMIUM": "/usr/bin/chromium",
    })
    return subprocess.run(["bash", SPLASH_INSTALL.as_posix()], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, env=env)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_splashInstall_removesTheOldWantsLink_keepsTheUnit(tmp_path: Path):
    """
    Given: a car's fixture root holding graphical.target.wants/splash-boot.service
    When: the splash kit installs
    Then: that wants entry is gone, splash-boot.service is still installed, and the
        installer disabled (never enabled) it.
    """
    root = tmp_path / "root"
    wants = root / "etc" / "systemd" / "system" / "graphical.target.wants"
    wants.mkdir(parents=True)
    link = wants / "splash-boot.service"
    try:
        link.symlink_to("/etc/systemd/system/splash-boot.service")
    except OSError:
        link.write_text("stand-in for the symlink\n", encoding="utf-8")  # no symlink privilege

    result = _runSplashInstall(tmp_path, root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not os.path.lexists(link)
    unit = root / "etc" / "systemd" / "system" / "splash-boot.service"
    assert unit.is_file()
    assert "/run/user/1000/wayland-0" in unit.read_text(encoding="utf-8")
    log = (tmp_path / "systemctl.log").read_text(encoding="utf-8").splitlines()
    assert "disable splash-boot.service" in log
    assert "enable splash-boot.service" not in log
    assert "enable splash-grace.path" in log


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_splashInstall_freshRoot_doesNotFail(tmp_path: Path):
    """A fresh rig has no wants link: the disable is a no-op, not a failure."""
    root = tmp_path / "root"
    root.mkdir()

    result = _runSplashInstall(tmp_path, root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (root / "etc" / "systemd" / "system" / "splash-boot.service").is_file()
