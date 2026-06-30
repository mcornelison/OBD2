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
# US-400 -- System Status card render logic (S-3 / I-3 / I-4 / F-1).
# ---------------------------------------------------------------------------

_US400_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

// S-3: a non-object (null / malformed-parsed-to-null) -> no view (the shell
// renders `unavailable`); a plain object yields a structured view.
assert.strictEqual(c.systemStatusView(null), null, 'null -> no view');
assert.strictEqual(c.systemStatusView('x'), null, 'string -> no view');
assert.strictEqual(c.systemStatusView([]), null, 'array -> no view');

// I-3: a reconnecting OBD link -> tile shows RECONNECTING (amber), retries
// surfaced; the top-bar BT glyph flips amber.
const reconn = {
  obdLink: {state: 'reconnecting', retries: 3, lastSeenS: 14},
  sync: {lastOkTs: '2026-06-30T19:40:00Z', rows: 10, pending: 0, stale: false},
  power: {mode: 'car', source: 'external'},
  drive: {state: 'recording', driveId: 27},
  ts: '2026-06-30T19:42:00Z'
};
const rv = c.systemStatusView(reconn);
assert.strictEqual(rv.tiles.obdLink.level, 'amber', 'reconnect tile amber');
assert.ok(/RECONNECTING/i.test(rv.tiles.obdLink.value), 'tile says RECONNECTING');
assert.ok(/3/.test(rv.tiles.obdLink.detail), 'retries surfaced');
assert.strictEqual(rv.glyphs.bt, 'amber', 'BT glyph amber on reconnect');

// I-4: a stale-while-driving sync -> sync tile amber + sync glyph amber.
const stale = JSON.parse(JSON.stringify(reconn));
stale.obdLink = {state: 'linked', retries: 0, lastSeenS: 1};
stale.sync.stale = true;
const sv = c.systemStatusView(stale);
assert.strictEqual(sv.tiles.sync.level, 'amber', 'stale sync tile amber');
assert.strictEqual(sv.glyphs.sync, 'amber', 'sync glyph amber when stale');

// F-1 (honest-instrument): a fully-degraded underlying state NEVER renders a
// green/ok tile or glyph.
const degraded = {
  obdLink: {state: 'down', retries: 0, lastSeenS: null},
  sync: {lastOkTs: null, rows: 0, pending: 12, stale: true},
  power: {mode: 'car', source: 'battery'},
  drive: {state: 'idle', driveId: null},
  ts: '2026-06-30T19:42:00Z'
};
const dv = c.systemStatusView(degraded);
assert.strictEqual(dv.tiles.obdLink.level, 'down', 'down link not ok');
assert.strictEqual(dv.tiles.sync.level, 'amber', 'stale sync not ok');
assert.strictEqual(dv.tiles.power.level, 'amber', 'battery power not ok');
const dglyphs = [dv.glyphs.bt, dv.glyphs.sync, dv.glyphs.power];
assert.ok(dglyphs.indexOf('ok') === -1, 'no glyph is ok when degraded');

// A healthy state DOES render green (the positive control -- ok is reachable).
const healthy = {
  obdLink: {state: 'linked', retries: 0, lastSeenS: 2},
  sync: {lastOkTs: '2026-06-30T19:41:50Z', rows: 50, pending: 0, stale: false},
  power: {mode: 'car', source: 'external'},
  drive: {state: 'recording', driveId: 27},
  ts: '2026-06-30T19:42:00Z'
};
const hv = c.systemStatusView(healthy);
assert.strictEqual(hv.tiles.obdLink.level, 'ok', 'linked -> ok');
assert.strictEqual(hv.glyphs.bt, 'ok', 'BT glyph ok when linked');
assert.strictEqual(hv.glyphs.power, 'ok', 'power glyph ok on external');

// A missing sub-object -> that tile is `unavailable`, never green.
const partial = c.systemStatusView({ts: '2026-06-30T19:42:00Z'});
assert.strictEqual(partial.tiles.obdLink.level, 'unavailable', 'missing link tile');
assert.strictEqual(partial.glyphs.bt, 'neutral', 'missing link glyph neutral');

console.log('US400_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_systemStatusView_renderLogic_s3_i3_i4_f1():
    """US-400: the System Status render logic maps emitter JSON -> honest tiles +
    glyph states (RECONNECTING amber, stale-sync amber, never green-when-broken)."""
    result = subprocess.run(
        ["node", "-e", _US400_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US400_OK" in result.stdout


def test_dashboardCss_carriesTileLevelColors_us400():
    """US-400: the card-tile level styles bind ok/amber/down to the palette so a
    degraded tile is visibly not-green (honest-instrument)."""
    css = _read(KIT_DIR, "dashboard.css")
    assert '.tile' in css
    assert 'data-level="amber"' in css
    assert 'data-level="down"' in css
    assert 'data-level="ok"' in css


# ---------------------------------------------------------------------------
# US-401 -- Battery Health card render logic (F-8 / F-9 / F-10 / F-11 / F-2).
# ---------------------------------------------------------------------------

_US401_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

// A non-object payload -> no view (the shell renders `unavailable`).
assert.strictEqual(c.batteryHealthView(null), null, 'null -> no view');
assert.strictEqual(c.batteryHealthView('x'), null, 'string -> no view');
assert.strictEqual(c.batteryHealthView([]), null, 'array -> no view');

// F-8 (voltage-is-not-percent): vcellV:3.44 with soc:null -> the card shows
// "3.44 V" and OMITS the percent (soc.shown false); "3.44 %" must never appear.
const noPct = {
  vcellV: 3.44, soc: null, socCalibrated: false, crate: -2.0,
  charging: false, draining: false, restedVcellV: null, weakEvents30d: 0,
  restedHistory: [], health: 'attn', fullChargeReached: false,
  runtimeToCutoffS: null, ambientTempC: null,
  lastHealthCheckTs: '2026-05-16T00:00:00Z', ladder: null,
  ts: '2026-06-30T19:42:00Z'
};
const npv = c.batteryHealthView(noPct);
assert.strictEqual(npv.vcell.value, '3.44 V', 'cell shown in volts');
assert.strictEqual(npv.soc.shown, false, 'percent omitted when soc null');
assert.ok(npv.vcell.value.indexOf('%') === -1, 'never a percent on the volts');
assert.strictEqual(npv.label, 'Pi UPS battery', 'F-11: UPS cell, not vehicle');
assert.ok(/UPS|Pi/i.test(npv.vcell.detail), 'F-11: cell labeled UPS/Pi');

// A real SoC renders the percent (positive control) tagged (uncalibrated).
const withPct = JSON.parse(JSON.stringify(noPct));
withPct.soc = 76; withPct.socCalibrated = false;
const wpv = c.batteryHealthView(withPct);
assert.strictEqual(wpv.soc.shown, true, 'percent shown when soc present');
assert.strictEqual(wpv.soc.value, '76%', 'percent rendered');
assert.ok(/uncalibrated/i.test(wpv.soc.detail), 'uncalibrated tag');

// F-9 (stale-green guard): a 45-day-old health check -> a GREEN verdict carries
// "last health check · <date> (<age>)"; GREEN is never shown without its age.
const green = JSON.parse(JSON.stringify(noPct));
green.health = 'green';
green.lastHealthCheckTs = '2026-05-16T00:00:00Z'; // 45 days before ts
const gv = c.batteryHealthView(green);
assert.strictEqual(gv.health.level, 'ok', 'green -> ok');
assert.ok(/last health check/.test(gv.health.detail), 'green carries data-age');
assert.ok(/2026-05-16/.test(gv.health.detail), 'date present');
assert.ok(/45 days ago/.test(gv.health.detail), 'age present');
assert.strictEqual(gv.healthCheck.ageDays, 45, 'age computed from ts');

// F-10 (temp honest): ambientTempC:null -> "not captured", never a number.
assert.strictEqual(gv.temp.value, 'not captured', 'temp not captured');
const warm = JSON.parse(JSON.stringify(green));
warm.ambientTempC = 24;
assert.strictEqual(c.batteryHealthView(warm).temp.value, '24 °C', 'temp number');

// F-2 / A-6 (no false failsafe): draining:false -> NO ladder; draining:true ->
// ladder present. A draining pack with no Spool runtime shows stage, no minutes.
assert.strictEqual(gv.ladder, null, 'draining false -> no ladder DOM');
const drain = JSON.parse(JSON.stringify(green));
drain.draining = true;
drain.ladder = {stage: 'WARNING', thresholds: {warn: 3.70}, runtimeRemainingS: 360};
const dv = c.batteryHealthView(drain);
assert.ok(dv.ladder !== null, 'draining true -> ladder present');
assert.strictEqual(dv.ladder.stage, 'WARNING', 'stage carried');
assert.strictEqual(dv.ladder.runtimeRemainingS, 360, 'runtime carried (Spool S-2)');
const drainNoSpool = JSON.parse(JSON.stringify(green));
drainNoSpool.draining = true; drainNoSpool.ladder = null; // S-2 not delivered
const dnv = c.batteryHealthView(drainNoSpool);
assert.ok(dnv.ladder !== null, 'draining still renders a failsafe');
assert.strictEqual(dnv.ladder.runtimeRemainingS, null, 'no fabricated minutes');
assert.strictEqual(dnv.ladder.stage, 'DRAINING', 'stage defaults honestly');

console.log('US401_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_batteryHealthView_renderLogic_f8_f9_f10_f2():
    """US-401: the Battery Health render logic maps emitter JSON -> an honest
    card (volts-not-percent, stale-green data-age, temp-not-captured, ladder only
    when draining, UPS-not-vehicle labeling)."""
    result = subprocess.run(
        ["node", "-e", _US401_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US401_OK" in result.stdout


def test_dashboardCss_carriesLadderFailsafeStyles_us401():
    """US-401: the failsafe ladder block has styles (rendered only when draining);
    the TRIGGER stage escalates to STOP-red."""
    css = _read(KIT_DIR, "dashboard.css")
    assert ".ladder" in css
    assert 'data-stage="TRIGGER"' in css


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
