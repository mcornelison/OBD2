################################################################################
# File Name: test_dashboard_kit.py
# Purpose/Description: Synthetic (CI-runnable) acceptance tests for the US-399
#   carousel dashboard shell (F-092). Covers the bench validation criteria that
#   are testable off-Pi:
#     S-1  load dashboard HTML headless -> both cards render, no console errors
#          (modeled as: the two card slots + top bar + page-dot mount exist in
#          the HTML, every shipped .js passes `node --check`, no always-on
#          console.error, and the honest-instrument `unavailable` fallback is
#          present).
#     S-2  swipe L/R -> advances card + updates page dot; tap target >=40px
#          (modeled as: the pure carousel logic nextIndex/swipeDirection/
#          cardAvailability is unit-tested in node, and the CSS pins >=40px tap
#          targets on the dots + menu button).
#   Plus the A-1 splash hand-off (OnSuccess=), the A-2 multi-assets-dir runtime
#   wiring, the touch-enabled kiosk unit, and the install.sh V-1/V-2 dry-run.
#   I-1 (boot splash -> dashboard within <=3s on the OSOYOO) is a Pi bench drill
#   deferred to sprint validation -- not reproducible off-Pi.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial implementation (US-399 carousel shell).
# ================================================================================
################################################################################

"""Static + node + dry-run acceptance tests for the US-399 dashboard kit."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KIT_DIR = REPO_ROOT / "specs" / "UI" / "dist" / "dashboard-pi"
SPLASH_KIT = REPO_ROOT / "specs" / "UI" / "dist" / "splash-pi"
DEPLOY_DIR = REPO_ROOT / "deploy"
INSTALL_SH = KIT_DIR / "install.sh"
UNINSTALL_SH = KIT_DIR / "uninstall.sh"


def _read(base: Path, name: str) -> str:
    return (base / name).read_text(encoding="utf-8")


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


def _nodeAvailable() -> bool:
    return shutil.which("node") is not None


# ---------------------------------------------------------------------------
# S-1 -- the dashboard HTML renders both cards + the shell furniture.
# ---------------------------------------------------------------------------


def test_dashboardHtml_hasBothCardSlots_s1():
    """S-1: the carousel has the two card slots (System Status + Battery Health)."""
    html = _read(KIT_DIR, "dashboard.html")
    assert html.count('class="card"') == 2
    assert 'data-state="system-status"' in html
    assert 'data-state="battery-health"' in html


def test_dashboardHtml_hasPersistentTopBarGlyphs_d3():
    """D-3: the persistent top bar carries BT / sync / power glyphs + version."""
    html = _read(KIT_DIR, "dashboard.html")
    assert 'id="topbar"' in html
    for glyph in ("glyph-bt", "glyph-sync", "glyph-power"):
        assert f'id="{glyph}"' in html, f"top bar missing {glyph}"
    assert 'id="version-chip"' in html


def test_dashboardHtml_hasPageDotMount_and_carouselScript():
    html = _read(KIT_DIR, "dashboard.html")
    assert 'id="dots"' in html
    assert 'id="track"' in html
    assert "carousel.js" in html


def test_dashboardHtml_injectsTokenSameOrigin():
    """Token SSOT: the served HTML carries the placeholder (server injects it)."""
    html = _read(KIT_DIR, "dashboard.html")
    assert "__SPLASH_TOKEN__" in html


def test_carouselJs_readsOnlyStateFiles_neverHardware():
    """Honest-instrument: the shell fetch()es state files; it never polls OBD/I2C
    hardware directly (no smbus / serial / obd imports in the kiosk JS)."""
    js = _read(KIT_DIR, "carousel.js")
    assert 'fetch("/"' in js or "fetch('/'" in js or 'fetch("/" +' in js
    for forbidden in ("smbus", "serial", "/dev/", "i2c", "obd."):
        assert forbidden not in js.lower(), f"kiosk JS must not touch hardware: {forbidden}"


def test_carouselJs_honestInstrument_unavailableFallback():
    """A missing/malformed state file -> `unavailable`, never a crash/fabrication."""
    js = _read(KIT_DIR, "carousel.js")
    assert "unavailable" in js
    assert "try" in js and "catch" in js  # the fetch is guarded


def test_dashboardKitJs_hasNoAlwaysOnConsoleError():
    """S-1 'no console errors': the shipped JS has no unconditional console.error."""
    js = _read(KIT_DIR, "carousel.js")
    assert "console.error" not in js


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_carouselJs_passesNodeSyntaxCheck_s1():
    """S-1 proxy: carousel.js parses cleanly (no syntax/load console errors)."""
    result = subprocess.run(
        ["node", "--check", str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# S-2 -- the pure carousel logic (swipe -> index -> dot) executes correctly.
# ---------------------------------------------------------------------------

_S2_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);
// nextIndex: swipe-next advances, clamps at the last card (no wrap).
assert.strictEqual(c.nextIndex(0, 1, 2), 1, 'next from 0');
assert.strictEqual(c.nextIndex(1, 1, 2), 1, 'clamp at last');
assert.strictEqual(c.nextIndex(1, -1, 2), 0, 'prev from 1');
assert.strictEqual(c.nextIndex(0, -1, 2), 0, 'clamp at first');
// swipeDirection: left (dx<0) -> next(+1); right (dx>0) -> prev(-1); small -> 0.
assert.strictEqual(c.swipeDirection(-60, 40), 1, 'swipe left = next');
assert.strictEqual(c.swipeDirection(60, 40), -1, 'swipe right = prev');
assert.strictEqual(c.swipeDirection(-10, 40), 0, 'below threshold = tap');
// availability classifier (honest-instrument).
assert.strictEqual(c.cardAvailability(null), 'unavailable', 'null');
assert.strictEqual(c.cardAvailability('x'), 'unavailable', 'string');
assert.strictEqual(c.cardAvailability([]), 'unavailable', 'array');
assert.strictEqual(c.cardAvailability({a: 1}), 'available', 'object');
console.log('S2_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_carouselLogic_swipeAdvancesAndDot_s2():
    """S-2: a synthetic swipe advances the card index (and the active dot tracks
    the same index, since the dot render keys off `current`)."""
    result = subprocess.run(
        ["node", "-e", _S2_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "S2_OK" in result.stdout


def test_dashboardCss_tapTargetsAtLeast40px_s2():
    """S-2: dots + menu button are >=40px touch targets."""
    css = _read(KIT_DIR, "dashboard.css")
    assert "--tap-min:        40px;" in css or "--tap-min: 40px;" in css
    # The dots + menu button reference the >=40px token.
    assert "min-width: var(--tap-min)" in css
    assert "min-height: var(--tap-min)" in css


def test_dashboardCss_carriesStopRedToken():
    """The STOP-red ribbon token (US-405) is reserved in the shell palette."""
    css = _read(KIT_DIR, "dashboard.css")
    assert "#F61D2D" in css


# ---------------------------------------------------------------------------
# A-1 -- splash -> dashboard hand-off (OnSuccess=).
# ---------------------------------------------------------------------------


def test_splashBootUnits_handOffToDashboard_a1():
    """A-1: both splash-boot variants start the dashboard OnSuccess (HEALTHY_YIELD)."""
    for variant in ("splash-boot.service.wayland", "splash-boot.service.x11"):
        unit = _read(SPLASH_KIT, variant)
        assert "OnSuccess=eclipse-dashboard.service" in unit, variant


def test_dashboardUnits_touchEnabled_andNoInstallSection_a5():
    """A-5: the kiosk is touch-enabled; A-1: no [Install] (hand-off-started)."""
    for variant in ("dashboard.service.wayland", "dashboard.service.x11"):
        unit = _read(KIT_DIR, variant)
        assert "--touch-events=enabled" in unit, variant
        assert "/dashboard.html" in unit, variant
        # No real [Install] section header (a line that is exactly "[Install]");
        # the prose comment that mentions it does not count.
        section_headers = [ln.strip() for ln in unit.splitlines()]
        assert "[Install]" not in section_headers, (
            f"{variant} must be hand-off-started, not enabled"
        )


def test_dashboardWaylandVariant_usesWayland():
    unit = _read(KIT_DIR, "dashboard.service.wayland")
    assert "ozone-platform=wayland" in unit
    unit_x11 = _read(KIT_DIR, "dashboard.service.x11")
    assert "DISPLAY=:0" in unit_x11


# ---------------------------------------------------------------------------
# A-2 -- the runtime state server serves /opt/dashboard same-origin.
# ---------------------------------------------------------------------------


def test_statesHttpService_servesDashboardAssetsDir_a2():
    """A-2: eclipse-states-http serves BOTH kits (splash + dashboard)."""
    unit = _read(DEPLOY_DIR, "eclipse-states-http.service")
    assert "--assets-dir /opt/splash" in unit
    assert "--assets-dir /opt/dashboard" in unit


def test_deployPi_installsDashboardAssets():
    """deploy-pi.sh installs the served dashboard kit to /opt/dashboard."""
    sh = _read(DEPLOY_DIR, "deploy-pi.sh")
    assert "step_install_dashboard_assets" in sh
    # The function is both defined AND called (defined once, invoked once).
    assert sh.count("step_install_dashboard_assets") >= 2
    assert "/opt/dashboard" in sh


# ---------------------------------------------------------------------------
# install.sh -- V-1/V-2 detection + --dry-run (mirrors the splash installer).
# ---------------------------------------------------------------------------


def _runInstall(*args: str, env_extra: dict[str, str] | None = None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(INSTALL_SH), *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_reportsUserAndSession():
    result = _runInstall(
        "--dry-run",
        env_extra={"DASHBOARD_FORCE_USER": "tunerbox", "DASHBOARD_FORCE_SESSION": "wayland"},
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "tunerbox" in out
    assert "wayland" in out
    assert "dashboard.service.wayland" in out
    assert "DRY" in out.upper()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_picksX11Variant():
    result = _runInstall(
        "--dry-run",
        env_extra={"DASHBOARD_FORCE_USER": "tunerbox", "DASHBOARD_FORCE_SESSION": "x11"},
    )
    assert result.returncode == 0, result.stderr
    assert "dashboard.service.x11" in result.stdout


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_failsLoudly_onUnknownSession():
    result = _runInstall(
        "--dry-run",
        env_extra={"DASHBOARD_FORCE_USER": "tunerbox", "DASHBOARD_FORCE_SESSION": "mystery"},
    )
    assert result.returncode != 0
    assert "session" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_failsLoudly_onIndeterminateUser():
    result = _runInstall(
        "--dry-run",
        env_extra={"DASHBOARD_FORCE_USER": "", "DASHBOARD_FORCE_SESSION": "wayland",
                   "DASHBOARD_USER_HOME_GLOB": "/nonexistent-home-root/*"},
    )
    assert result.returncode != 0
    assert "user" in (result.stdout + result.stderr).lower()


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_installDryRun_doesNotRequireRoot():
    result = _runInstall(
        "--dry-run",
        env_extra={"DASHBOARD_FORCE_USER": "tunerbox", "DASHBOARD_FORCE_SESSION": "wayland"},
    )
    assert "must be run as root" not in (result.stdout + result.stderr)


def test_uninstall_removesUnitAndAssets():
    sh = UNINSTALL_SH.read_text(encoding="utf-8")
    assert "eclipse-dashboard.service" in sh
    assert "/opt/dashboard" in sh
