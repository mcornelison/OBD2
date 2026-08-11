################################################################################
# File Name: test_splash_kit.py
# Purpose/Description: Synthetic (CI-runnable) acceptance tests for the F-103
#   splash kit defect fixes + install-time checks (US-396). Covers spec
#   2026-05-26-b103-splash-animation-design.md §9 synthetic criteria S-1..S-4
#   plus the §7 defects (D-1 wrong-SVG, D-2 self-cancel, D-3 X11/Wayland) and
#   the V-1/V-2 install-time user/session detection. Pure static-content greps
#   over the dist kit + a subprocess drive of `install.sh --dry-run` (detection
#   overridable via SPLASH_FORCE_USER / SPLASH_FORCE_SESSION so the report is
#   deterministic off-Pi). No Pi hardware required.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-396) | Initial implementation (F-103 render-side
#               |              | defects D-1/D-2/D-3 + V-1/V-2 install checks).
# ================================================================================
################################################################################

"""Static + dry-run acceptance tests for the F-103 splash kit (US-396)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KIT_DIR = REPO_ROOT / "specs" / "UI" / "dist" / "splash-pi"
INSTALL_SH = KIT_DIR / "install.sh"
UNINSTALL_SH = KIT_DIR / "uninstall.sh"


def _read(name: str) -> str:
    return (KIT_DIR / name).read_text(encoding="utf-8")


def _serviceFiles() -> list[Path]:
    """Every splash-* unit/template file shipped in the kit."""
    return sorted(KIT_DIR.glob("splash-*.service*")) + sorted(KIT_DIR.glob("splash-*.path"))


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


# ---------------------------------------------------------------------------
# D-1 / S-1 -- shutdown.html must load the REVERSE svg, not the boot svg.
# ---------------------------------------------------------------------------


def test_shutdownHtml_loadsShutdownSvg_d1():
    """S-1/D-1: shutdown.html embeds splash-shutdown.svg, never splash.svg."""
    html = _read("shutdown.html")
    assert "splash-shutdown.svg" in html
    assert 'data="splash.svg"' not in html


def test_shutdownHtml_wiresStateMachine_renderSide():
    """shutdown.html is a real render page: token placeholder + poll script."""
    html = _read("shutdown.html")
    assert "__SPLASH_TOKEN__" in html
    assert "shutdown-state-poll.js" in html


def test_shutdownStatePollJs_present_and_handlesPhases():
    """shutdown-state-poll.js exists and renders the spec §6 phase contract."""
    js = _read("shutdown-state-poll.js")
    for phase in ("grace", "cancelled", "flushing", "powering_off"):
        assert phase in js, f"shutdown-state-poll.js missing phase {phase!r}"
    assert "/shutdown-state" in js


# ---------------------------------------------------------------------------
# D-2 / S-2 -- the self-cancelling splash-shutdown.service is gone; no unit
#             carries a Conflicts= directive; the grace pair replaces it.
# ---------------------------------------------------------------------------


def test_splashShutdownService_retired_d2():
    """D-2: the original self-cancelling unit is deleted from the kit."""
    assert not (KIT_DIR / "splash-shutdown.service").exists()


def test_noServiceFile_containsConflicts_d2():
    """S-2: no splash-* unit declares Conflicts= (the D-2 root cause)."""
    offenders = [p.name for p in _serviceFiles() if "Conflicts=" in p.read_text(encoding="utf-8")]
    assert offenders == [], f"Conflicts= still present in: {offenders}"


def test_graceUnits_present():
    """The replacement grace pair (.path + wayland/x11 service variants) ships."""
    assert (KIT_DIR / "splash-grace.path").exists()
    assert (KIT_DIR / "splash-grace.service.wayland").exists()
    assert (KIT_DIR / "splash-grace.service.x11").exists()


def test_gracePath_watchesShutdownState():
    """splash-grace.path watches the shutdown-state SSOT + fires the grace svc."""
    path_unit = _read("splash-grace.path")
    assert "PathExists=/run/eclipse-obd/states/shutdown-state" in path_unit
    assert "Unit=splash-grace.service" in path_unit


def test_graceService_loadsShutdownEntry():
    """Both grace variants render the shutdown entry via the token-injecting
    HTTP server (same-origin), Type=simple, JS-driven exit (no pkill)."""
    for variant in ("splash-grace.service.wayland", "splash-grace.service.x11"):
        unit = _read(variant)
        assert "Type=simple" in unit
        assert "shutdown.html" in unit
        assert "127.0.0.1:9899" in unit
        assert "pkill" not in unit


# ---------------------------------------------------------------------------
# D-3 / S-3 -- the original DISPLAY=:0/Before=graphical splash-boot.service is
#             retired; the wayland/x11 variants carry the right display env.
# ---------------------------------------------------------------------------


def test_originalSplashBootService_retired_d3():
    """D-3: the X11/Before=graphical original boot unit is deleted from the kit."""
    assert not (KIT_DIR / "splash-boot.service").exists()


def test_waylandVariants_referenceWayland_s3():
    """S-3: wayland variants use WAYLAND_DISPLAY; x11 variants use DISPLAY=:0."""
    for wl in ("splash-boot.service.wayland", "splash-grace.service.wayland"):
        unit = _read(wl)
        assert "WAYLAND_DISPLAY" in unit
        assert "ozone-platform=wayland" in unit
    for x11 in ("splash-boot.service.x11", "splash-grace.service.x11"):
        unit = _read(x11)
        assert "DISPLAY=:0" in unit


def test_bootVariants_orderAfterGraphical_d3():
    """D-3: variants defer until the display server is up (After=, not Before=)."""
    for variant in ("splash-boot.service.wayland", "splash-boot.service.x11"):
        unit = _read(variant)
        assert "After=graphical.target" in unit
        assert "Before=graphical.target" not in unit


# ---------------------------------------------------------------------------
# V-1 / V-2 / S-4 -- install.sh detects the Pi user + session type, picks the
#                   matching variants, fails loudly on the unknowns, and
#                   --dry-run reports its picks without installing.
# ---------------------------------------------------------------------------


def _runInstall(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    # V-3 (US-428): the installer now also resolves a chromium binary and aborts
    # loudly if none is found (mirrors the V-1/V-2 gates). These off-Pi
    # user/session previews are orthogonal to the browser path, and a dev box has
    # no chromium -- default it so the preview reaches the report, unless a test
    # overrides SPLASH_FORCE_CHROMIUM explicitly (e.g. to simulate "none").
    env.setdefault("SPLASH_FORCE_CHROMIUM", "/usr/bin/chromium")
    # V-4 (US-550 / I-044): the installer also resolves the Pi user's numeric uid
    # via `id -u` for XDG_RUNTIME_DIR, and aborts if it can't. The forced users
    # here ("tunerbox") do not exist on a dev box, so default it for the same
    # reason as the chromium path above -- unless a test overrides it explicitly.
    env.setdefault("SPLASH_FORCE_UID", "1000")
    return subprocess.run(
        ["bash", str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_reportsUserAndSession_s4():
    """S-4/V-1/V-2: --dry-run reports the user + session it WOULD pick, no install."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "wayland"},
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "tunerbox" in out
    assert "wayland" in out
    # It must name the variant it would pick so the report is actionable.
    assert "splash-boot.service.wayland" in out
    # Dry run never touches the live system.
    assert "DRY" in out.upper()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_picksX11Variant_whenSessionX11():
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "x11"},
    )
    assert result.returncode == 0, result.stderr
    assert "splash-boot.service.x11" in result.stdout


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_failsLoudly_onUnknownSession_v2():
    """V-2: an unresolvable session type aborts loudly (no X11 default-guess)."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "mystery"},
    )
    assert result.returncode != 0
    assert "session" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_failsLoudly_onIndeterminateUser_v1():
    """V-1: an unresolvable Pi user aborts loudly."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "", "SPLASH_FORCE_SESSION": "wayland",
                   "SPLASH_USER_HOME_GLOB": "/nonexistent-home-root/*"},
    )
    assert result.returncode != 0
    assert "user" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_doesNotRequireRoot():
    """--dry-run must run unprivileged (it only reports); the root gate is for
    the real install path only."""
    result = _runInstall(
        "--dry-run",
        env_extra={"SPLASH_FORCE_USER": "tunerbox", "SPLASH_FORCE_SESSION": "wayland"},
    )
    assert "must be run as root" not in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# uninstall.sh -- removes the grace pair + legacy units (migration cleanup).
# ---------------------------------------------------------------------------


def test_uninstall_removesGraceAndLegacyUnits():
    sh = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "splash-grace.service" in sh
    assert "splash-grace.path" in sh
    # Legacy units are still swept so an upgrade-in-place leaves nothing behind.
    assert "splash-shutdown.service" in sh
