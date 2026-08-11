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
# 2026-06-30    | Ralph (Rex)  | US-402: pygame sunset -- assert the shipped
#               |              | config.json retires the StatusDisplay overlay
#               |              | (F-4: HTML carousel is the sole surface).
# ================================================================================
################################################################################

"""Static + node + dry-run acceptance tests for the US-399 dashboard kit."""

from __future__ import annotations

import os
import re
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
    """S-1: every card the carousel ships has a slot in the markup.

    REVISED BY US-507 (F-124). The count was 6; the CIO called that too many
    screens, so Battery Health + Light + LTFT Trend merged into ONE Health card
    (-2 slots). The invariant this test has always guarded is unchanged and is
    what is re-asserted: the slot inventory in the markup matches the cards the
    carousel actually ships, since the tick discovers cards from the DOM and a
    card with no slot does not exist whatever the JS says.

    The three merged sources are NOT gone -- they are sections of the Health
    card, declared on it via `data-states` (pinned by the dedicated suite,
    tests/ui/test_carousel_health_card.py).

    US-508 THEN FOLDED MOTION INTO THE HOME SLOT, which is what reaches the
    CIO-locked four: Home . System Status . Health . Alerts. Note the count
    stayed 4 across that change for a DIFFERENT REASON, which is exactly the
    kind of coincidence that makes a bare count vacuous -- before, the idle card
    wore `class="card idle-card"` and was not counted at all; now the home slot
    is a plain `.card` and IS. So the inventory below names every slot rather
    than trusting the number.
    """
    html = _read(KIT_DIR, "dashboard.html")
    assert html.count('class="card"') == 4
    assert 'data-state="system-status"' in html
    assert 'data-state="dtc"' in html
    assert 'aria-label="Home"' in html
    assert 'aria-label="Health"' in html
    # The live instrument is a FACE of the home slot, not a slot of its own.
    assert 'data-state="imu"' not in html
    # The merged sources moved rather than vanished: the Health card declares
    # all three state files it consumes.
    assert 'data-states="battery-health light ltft-trend"' in html


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
    # Hardware-access vectors. `serial` also covers WebSerial (navigator.serial).
    # Note: a Python `obd.` token would false-positive on the systemd unit name
    # `eclipse-obd.service` (US-403 menu) -- the JS guard is `python-obd` instead.
    for forbidden in ("smbus", "serial", "/dev/", "i2c", "python-obd", "navigator.usb"):
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
# US-421 -- Power-mode badge (F-098 / BL-014). The powerTile renders the
# `power.mode` SSOT (fed from PowerModeProvider over pi.power.mode): car -> CAR,
# wall -> WALL, and -- honest-instrument -- ANYTHING else (unknown / invalid /
# absent) -> the lowercase `unknown` badge, NEVER a confident wrong CAR/WALL.
# The mode flows through the same emitter JSON the System Status card consumes,
# so this drives the tile both directly and through systemStatusView (the DOM
# render path) with mocked config states.
# ---------------------------------------------------------------------------

_US421_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

// --- car / wall render the confident UPPERCASE badge (external power) --------
const car = c.powerTile({mode: 'car', source: 'external'});
assert.strictEqual(car.value, 'CAR', 'car -> CAR badge');
assert.strictEqual(car.level, 'ok', 'external power -> ok');
const wall = c.powerTile({mode: 'wall', source: 'external'});
assert.strictEqual(wall.value, 'WALL', 'wall -> WALL badge');
assert.strictEqual(wall.level, 'ok', 'external power -> ok');

// --- honest-instrument: explicit unknown -> lowercase `unknown`, ok level -----
const unk = c.powerTile({mode: 'unknown', source: 'external'});
assert.strictEqual(unk.value, 'unknown', 'unknown -> lowercase unknown badge');

// --- invalid / absent config -> unknown, NEVER a confident wrong CAR/WALL -----
const badModes = ['garage', '', 'CAR', 'Wall', 'battery', 42, true, null, undefined];
badModes.forEach(function (m) {
  const t = c.powerTile({mode: m, source: 'external'});
  assert.strictEqual(t.value, 'unknown',
    'invalid mode ' + JSON.stringify(m) + ' -> unknown badge');
  assert.ok(t.value !== 'CAR' && t.value !== 'WALL',
    'invalid mode ' + JSON.stringify(m) + ' NEVER a confident wrong mode');
});
// mode key entirely absent -> unknown (never fabricates a mode).
assert.strictEqual(c.powerTile({source: 'external'}).value, 'unknown',
  'absent mode -> unknown');

// --- on-UPS (battery source) surfaces the mode in the detail, amber level -----
const onUps = c.powerTile({mode: 'car', source: 'battery'});
assert.strictEqual(onUps.level, 'amber', 'battery -> amber');
assert.ok(/car/.test(onUps.detail) && /UPS/.test(onUps.detail),
  'battery detail carries the mode + UPS');
assert.ok(/wall/.test(c.powerTile({mode: 'wall', source: 'battery'}).detail),
  'wall mode surfaced in the UPS detail');

// --- non-object payload -> unavailable, never a crash (honest-instrument) -----
assert.strictEqual(c.powerTile(null).level, 'unavailable', 'null -> unavailable');
assert.strictEqual(c.powerTile('x').level, 'unavailable', 'string -> unavailable');

// --- the DOM render path (systemStatusView) carries the same honest badge -----
function state(mode) {
  return {
    obdLink: {state: 'linked', retries: 0, lastSeenS: 2},
    sync: {lastOkTs: '2026-07-01T19:41:50Z', rows: 1, pending: 0, stale: false},
    power: {mode: mode, source: 'external'},
    drive: {state: 'idle', driveId: null},
    ts: '2026-07-01T19:42:00Z'
  };
}
assert.strictEqual(c.systemStatusView(state('car')).tiles.power.value, 'CAR',
  'DOM path: car config -> CAR');
assert.strictEqual(c.systemStatusView(state('wall')).tiles.power.value, 'WALL',
  'DOM path: wall config -> WALL');
assert.strictEqual(c.systemStatusView(state('garage')).tiles.power.value, 'unknown',
  'DOM path: invalid config -> unknown, never confident-wrong');

console.log('US421_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_powerTile_modeBadgeHonestInstrument_us421():
    """US-421 / BL-014: the power tile renders the pi.power.mode SSOT -- car->CAR,
    wall->WALL, and anything else (unknown / invalid / absent) -> the lowercase
    `unknown` badge, never a confident wrong mode. Verified both directly and
    through the systemStatusView DOM render path with mocked config states."""
    result = subprocess.run(
        ["node", "-e", _US421_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US421_OK" in result.stdout


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

// F-9 (stale-green guard): a 45-day-old health check -> a GOOD verdict carries
// "last health check · <date> (<age>)"; GOOD is never shown without its age.
const green = JSON.parse(JSON.stringify(noPct));
green.health = 'good';
green.lastHealthCheckTs = '2026-05-16T00:00:00Z'; // 45 days before ts
const gv = c.batteryHealthView(green);
assert.strictEqual(gv.health.level, 'ok', 'good -> ok');
assert.strictEqual(gv.health.value, 'GOOD', 'Spool verdict word carried');
assert.ok(/last health check/.test(gv.health.detail), 'good carries data-age');
assert.ok(/2026-05-16/.test(gv.health.detail), 'date present');
assert.ok(/45 days ago/.test(gv.health.detail), 'age present');
assert.strictEqual(gv.healthCheck.ageDays, 45, 'age computed from ts');

// US-504 severity: informational at EVERY state -- a `replace` verdict must
// never reach the alarm tier, and the retired green/attn/low tiers are gone.
const worn = JSON.parse(JSON.stringify(green));
worn.health = 'replace';
assert.strictEqual(c.batteryHealthView(worn).health.level, 'neutral', 'replace never red');
worn.health = 'low';
assert.strictEqual(c.batteryHealthView(worn).health.level, 'unavailable', 'retired tier');

// US-504: the TEMP tile is REMOVED -- the MAX17048 has no temperature register,
// so the tile had no source it could ever read (the column stays for a BMP390).
assert.strictEqual(gv.temp, undefined, 'no temp tile');
const warm = JSON.parse(JSON.stringify(green));
warm.ambientTempC = 24;
assert.strictEqual(c.batteryHealthView(warm).temp, undefined, 'temp stays gone');

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
    card (volts-not-percent, stale-green data-age, no-temp-tile, ladder only
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
    # V-3 (US-428): the installer now also resolves a chromium binary and aborts
    # loudly if none is found (mirrors the V-1/V-2 gates). These off-Pi
    # user/session previews are orthogonal to the browser path, and a dev box has
    # no chromium -- default it so the preview reaches the report, unless a test
    # overrides DASHBOARD_FORCE_CHROMIUM explicitly (e.g. to simulate "none").
    env.setdefault("DASHBOARD_FORCE_CHROMIUM", "/usr/bin/chromium")
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


# ---------------------------------------------------------------------------
# US-485 -- pygame sunset COMPLETED (was US-402 config-disable, A-4 parity-gated):
# the pygame StatusDisplay overlay + its config key are now fully REMOVED, so the
# HTML carousel is the sole dashboard surface (F-4 "pygame + HTML never both
# active"). US-402 flipped `pi.hardware.statusDisplay.enabled` to false; US-485
# deleted status_display.py / dashboard_layout.py + all wiring + the config key.
# The F-4 invariant is now stronger: there is no pygame status-overlay flag left
# to accidentally re-enable.
# ---------------------------------------------------------------------------

import json  # noqa: E402  (grouped with the pygame-sunset cut-over assertions)

CONFIG_JSON = REPO_ROOT / "config.json"


def test_shippedConfig_retiresPygameStatusDisplay_f4():
    """US-485 / F-4: the deployed config.json no longer carries the pygame
    StatusDisplay overlay flag at all (`pi.hardware.statusDisplay` is absent).
    US-402 disabled it (`enabled == false`); US-485 fully retired the pygame
    surface -- status_display.py + dashboard_layout.py + the launch path + the
    config key are gone -- so the HTML carousel kiosk is the only dashboard
    surface and the two can never be active simultaneously (A-4/F-4). Guarding on
    ABSENCE (not `enabled == false`) is the stronger invariant: there is no
    overlay flag left to re-enable."""
    config = json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    statusDisplay = (
        config.get("pi", {})
        .get("hardware", {})
        .get("statusDisplay")
    )
    assert statusDisplay is None, (
        "pi.hardware.statusDisplay must be ABSENT -- the pygame status overlay is "
        "fully retired (US-485); the HTML carousel is the sole dashboard surface. "
        "A lingering flag (even enabled=false) is drift; remove it."
    )


# ---------------------------------------------------------------------------
# US-403 -- System Setup menu + gated service control (F-092 / Atlas A-7/A-8).
# The pure menu logic (long-press ring math, the service allow-list mirror,
# confirm-before-consequential, the powerwatch restart-only guard) is node-
# tested; the gesture/DOM drills (I-8..I-12) are Pi-bench, deferred.
# ---------------------------------------------------------------------------

_US403_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

// Long-press ring math (D-6): the ring fills over the hold; complete at hold.
assert.strictEqual(c.longPressProgress(0, 5000), 0, 'ring empty at start');
assert.strictEqual(c.longPressProgress(2500, 5000), 0.5, 'ring half at half');
assert.strictEqual(c.longPressProgress(6000, 5000), 1, 'ring clamps at full');
assert.strictEqual(c.isLongPressComplete(5000, 5000), true, 'complete at hold');
assert.strictEqual(c.isLongPressComplete(4999, 5000), false, 'not before hold');
// Movement past the threshold cancels the long-press (it is a swipe/scroll).
assert.strictEqual(c.exceedsMoveCancel(20, 0, 10), true, 'horizontal move cancels');
assert.strictEqual(c.exceedsMoveCancel(3, 3, 10), false, 'small jitter holds');

// The service menu mirrors the install-fixed allow-list. powerwatch is the
// safe-shutdown guard -> RESTART-ONLY, no Stop control (D-7 / F-7 / I-10).
const items = c.serviceMenuItems();
assert.strictEqual(items.length, 3, 'three OBD-II services listed');
const pw = items.find(function (i) { return i.unit === 'eclipse-powerwatch.service'; });
assert.ok(pw, 'powerwatch present');
assert.strictEqual(pw.canStop, false, 'powerwatch has no Stop (F-7)');
assert.strictEqual(pw.canRestart, true, 'powerwatch can restart');
const obd = items.find(function (i) { return i.unit === 'eclipse-obd.service'; });
assert.strictEqual(obd.canStop, true, 'eclipse-obd can stop');
assert.strictEqual(obd.canRestart, true, 'eclipse-obd can restart');

// Confirm-before-consequential: Stop (and Exit, a dashboard stop) confirm;
// Restart does not (it self-recovers).
assert.strictEqual(c.requiresConfirm('stop'), true, 'stop confirms');
assert.strictEqual(c.requiresConfirm('restart'), false, 'restart no confirm');

// actionRequest mirrors the server allow-list (defense-in-depth, the server
// re-checks): off-list -> null, powerwatch stop -> null (F-7/S-6/F-13).
const ok = c.actionRequest('eclipse-obd.service', 'restart');
assert.ok(ok && ok.unit === 'eclipse-obd.service' && ok.verb === 'restart', 'allowed action');
assert.strictEqual(c.actionRequest('eclipse-powerwatch.service', 'stop'), null, 'powerwatch stop blocked');
assert.strictEqual(c.actionRequest('ssh.service', 'stop'), null, 'off-list unit blocked');
assert.strictEqual(c.actionRequest('eclipse-obd.service', 'mask'), null, 'off-list verb blocked');
// Exit = stop the dashboard kiosk (A-8), allow-listed + confirms.
const exit = c.actionRequest('eclipse-dashboard.service', 'stop');
assert.ok(exit && exit.confirm === true, 'exit is allowed and confirms');

console.log('US403_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_serviceMenuLogic_allowListAndGuards_us403():
    """US-403: the menu logic exposes the long-press ring math + the allow-list
    mirror with the powerwatch restart-only guard + confirm-before-consequential."""
    result = subprocess.run(
        ["node", "-e", _US403_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US403_OK" in result.stdout


def test_dashboardHtml_hasSetupMenuAndLongPressRing_us403():
    """US-403: the System Setup menu overlay + the long-press ring + a confirm
    modal mount + an always-present back/close affordance are in the HTML."""
    html = _read(KIT_DIR, "dashboard.html")
    assert 'id="setup-menu"' in html
    assert 'id="longpress-ring"' in html
    assert 'id="confirm-modal"' in html
    # menu-btn (the visible shortcut) already exists from the shell.
    assert 'id="menu-btn"' in html
    # A back/close control so the menu never traps the user.
    assert 'id="menu-close"' in html
    # The Exit / Close UI item (A-8).
    assert "Exit" in html or "Close UI" in html


def test_dashboardCss_hasMenuAndRingStyles_us403():
    """US-403: the menu/ring/confirm styles exist and the menu buttons keep the
    >=40px tap target (no accidental consequential tap, F-6)."""
    css = _read(KIT_DIR, "dashboard.css")
    assert "#setup-menu" in css
    assert "#longpress-ring" in css
    assert "#confirm-modal" in css
    # A disabled service button (powerwatch Stop) is visibly inert (I-10/F-7).
    assert ".svc-btn:disabled" in css or "svc-btn[disabled]" in css
    # The menu action buttons reference the >=40px tap target.
    assert css.count("var(--tap-min)") >= 3


# ---------------------------------------------------------------------------
# US-403 -- the net-new 51- polkit rule (A-7 privilege path) + its deploy wiring.
# The kiosk is unprivileged; this rule (NOT a root helper, NOT a widening of the
# 50- poweroff rule) authorizes the fixed allow-list of systemctl actions.
# ---------------------------------------------------------------------------

POLKIT_RULE = DEPLOY_DIR / "polkit-rules" / "51-eclipse-service-control.rules"


def test_polkitRule_scopesManageUnitsToUser_a7():
    """A-7: the rule grants the systemd manage-units action to the kiosk user
    only -- a scoped polkit rule, the I-036 precedent, not a root helper."""
    rule = POLKIT_RULE.read_text(encoding="utf-8")
    assert "org.freedesktop.systemd1.manage-units" in rule
    assert "mcornelison" in rule


def test_polkitRule_keysOnUnitAndVerb_a7():
    """A-7: the decision is keyed on BOTH the unit AND the verb (so a verb can be
    denied per-unit -- the powerwatch restart-only guard needs this)."""
    rule = POLKIT_RULE.read_text(encoding="utf-8")
    assert 'action.lookup("unit")' in rule
    assert 'action.lookup("verb")' in rule


def test_polkitRule_powerwatchRestartOnly_deniesStop_f7():
    """A-7 / D-7 / F-7: eclipse-powerwatch is RESTART-ONLY -- a stop/kill is
    DENIED at the rule itself (an explicit polkit.Result.NO), not merely absent;
    the data services + the dashboard kiosk are granted."""
    rule = POLKIT_RULE.read_text(encoding="utf-8")
    assert "eclipse-powerwatch.service" in rule
    assert "polkit.Result.NO" in rule  # explicit deny, defense-in-depth
    assert "polkit.Result.YES" in rule
    for unit in (
        "eclipse-obd.service",
        "eclipse-sync.service",
        "eclipse-dashboard.service",
    ):
        assert unit in rule, f"allow-listed unit {unit} missing from the rule"


def test_deployPi_installsServiceControlPolkitRule_a7():
    """deploy-pi.sh installs the 51- service-control rule (defined + called),
    sibling to the 50- poweroff rule."""
    sh = _read(DEPLOY_DIR, "deploy-pi.sh")
    assert "step_install_polkit_service_control" in sh
    assert sh.count("step_install_polkit_service_control") >= 2  # defined + called
    assert "51-eclipse-service-control.rules" in sh
    assert "/etc/polkit-1/rules.d/51-eclipse-service-control.rules" in sh


# ---------------------------------------------------------------------------
# US-405 -- DTC takeover + STOP-red ribbon (F-111).
# The takeover fires ONLY on a NEW code (`newSinceTs`), one at a time
# (highest-severity = hero, others fold into "+N more"), severity-styled
# (color + directive + dismiss controls -- STOP has no plain dismiss); the
# persistent ribbon rides every card while a code is present. `na` codes
# (auto-trans on this manual car) never take over or ribbon (design §4/§5.2).
# The takeover-firing + severity-mapping logic is pure + node-tested; the
# auto-surface DOM drill is a Pi-bench item.
# ---------------------------------------------------------------------------

_US405_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

function code(sev, cd, short, status) {
  return { code: cd, severity: sev, short: short || '', status: status || 'stored',
           severityCaveat: null };
}
function dtc(codes, newSinceTs) {
  return { mil: true, codes: codes, newSinceTs: newSinceTs === undefined ? null : newSinceTs,
           clearGate: {}, sessionResetLock: [], ts: '2026-06-30T19:40:05Z' };
}

// --- S-1: takeover renders per severity (color + directive + dismiss) --------
const stopV = c.takeoverView(dtc([code('stop', 'P0301', 'Cyl 1 misfire')], '2026-06-30T19:40:00Z'));
assert.ok(stopV, 'stop new code -> takeover');
assert.strictEqual(stopV.severity, 'stop', 'stop severity');
assert.strictEqual(stopV.code, 'P0301', 'hero code');
assert.ok(/PULL OVER/i.test(stopV.directive), 'stop directive = pull over');
assert.strictEqual(stopV.plainDismiss, false, 'STOP has NO plain dismiss (Acknowledge only)');
assert.ok(/acknowledge/i.test(stopV.dismissLabel), 'stop dismiss label = Acknowledge');
// US-484-b: STOP binds the STATE-ALARM --critical-red, never a brand red (Spool 6d ch.2).
assert.strictEqual(stopV.colorVar, '--critical-red', 'stop uses the state-alarm red, not brand');

const watchV = c.takeoverView(dtc([code('watch', 'P0401', 'EGR flow')], '2026-06-30T19:40:00Z'));
assert.strictEqual(watchV.severity, 'watch', 'watch severity');
assert.ok(/DRIVE GENTLY/i.test(watchV.directive), 'watch directive');
assert.strictEqual(watchV.plainDismiss, true, 'watch is dismissible');
assert.strictEqual(watchV.colorVar, '--amber-warn', 'watch amber');

const minorV = c.takeoverView(dtc([code('minor', 'P0442', 'Evap small leak')], '2026-06-30T19:40:00Z'));
assert.strictEqual(minorV.severity, 'minor', 'minor severity');
assert.ok(/SAFE TO CLEAR/i.test(minorV.directive), 'minor directive');
assert.strictEqual(minorV.plainDismiss, true, 'minor dismissible');
assert.strictEqual(minorV.colorVar, '--green-ok', 'minor green (SSOT token, US-484-a)');

// hero = highest severity; the rest fold into "+N more" (one takeover at a time).
const multiV = c.takeoverView(dtc(
  [code('minor', 'P0442', 'Evap'), code('stop', 'P0301', 'Misfire'), code('watch', 'P0420', 'Cat')],
  '2026-06-30T19:40:00Z'));
assert.strictEqual(multiV.severity, 'stop', 'hero = worst severity');
assert.strictEqual(multiV.code, 'P0301', 'hero code = worst');
assert.strictEqual(multiV.moreCount, 2, '+2 more folded');

// --- S-2: known/old code (newSinceTs null) -> NO takeover; ribbon present ----
const known = dtc([code('stop', 'P0301', 'Cyl 1 misfire')], null);
assert.strictEqual(c.takeoverView(known), null, 'no new code -> no takeover');
const rb = c.ribbonView(known);
assert.ok(rb, 'ribbon present while a code exists');
assert.strictEqual(rb.level, 'stop', 'ribbon level = hero severity');
assert.strictEqual(rb.glyph, '⚠', 'ribbon carries a leading warning glyph');
assert.ok(/P0301/.test(rb.text), 'ribbon carries the hero code');

// --- escalation re-fires: a newer newSinceTs re-shows even after an ack ------
assert.strictEqual(c.takeoverShouldShow(stopV, null), true, 'first fire (nothing acked)');
assert.strictEqual(c.takeoverShouldShow(stopV, '2026-06-30T19:40:00Z'), false,
  'acked exactly -> no re-fire');
assert.strictEqual(c.takeoverShouldShow(stopV, '2026-06-30T18:00:00Z'), true,
  'a newer code (different newSinceTs) re-fires (escalation)');

// --- na (auto-trans on the manual F5M33): NO takeover, NO ribbon (design §4) --
const naData = dtc([code('na', 'P1750', 'Auto-trans solenoid')], '2026-06-30T19:40:00Z');
assert.strictEqual(c.takeoverView(naData), null, 'na -> no takeover');
assert.strictEqual(c.ribbonView(naData), null, 'na -> no ribbon');
// a na code alongside a real code -> the real code drives hero, na is not counted.
const mixed = c.takeoverView(dtc(
  [code('na', 'P1750', 'Auto-trans'), code('watch', 'P0420', 'Cat')], '2026-06-30T19:40:00Z'));
assert.strictEqual(mixed.severity, 'watch', 'na ignored -> watch is hero');
assert.strictEqual(mixed.moreCount, 0, 'na not counted in +N more');

// --- no codes / malformed -> nothing (honest-instrument) ---------------------
assert.strictEqual(c.takeoverView(dtc([], null)), null, 'no codes -> no takeover');
assert.strictEqual(c.ribbonView(dtc([], null)), null, 'no codes -> no ribbon');
assert.strictEqual(c.takeoverView(null), null, 'null -> no takeover');
assert.strictEqual(c.ribbonView('x'), null, 'string -> no ribbon');
assert.strictEqual(c.takeoverView([]), null, 'array -> no takeover');

console.log('US405_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_dtcTakeoverAndRibbonLogic_s1_s2_r2_us405():
    """US-405: the takeover fires only on a new code, severity-styled with the
    correct directive + dismiss controls (STOP = Acknowledge only), hero = worst
    code, and the ribbon persists while any non-na code is present."""
    result = subprocess.run(
        ["node", "-e", _US405_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US405_OK" in result.stdout


def test_dashboardHtml_hasTakeoverAndRibbon_us405():
    """US-405: the full-screen takeover overlay + the persistent ribbon mount are
    present in the HTML (JS fills their content per the polled `dtc` state)."""
    html = _read(KIT_DIR, "dashboard.html")
    assert 'id="dtc-takeover"' in html
    assert 'id="dtc-ribbon"' in html
    # The takeover has both a dismiss action and a view-detail affordance.
    assert 'id="takeover-dismiss"' in html
    assert 'id="takeover-directive"' in html


def test_dashboardCss_ribbonRedDistinctFromBrandRed_r2():
    """R-2: the ribbon rides on cards where brand-red chrome may live, so its STOP
    state must not be a brand red. US-484-b moved it onto the state-alarm
    --critical-red (#D32F2F, SSOT); the brand tier stays declared so the two are
    provably distinct. Plus a leading warning glyph + a subtle pulse animation."""
    css = _read(KIT_DIR, "dashboard.css")
    # Brand tier + alarm tier both defined -> provably distinct (R-2).
    assert "--red:" in css and "#E60012" in css, "brand --red token missing"
    assert "--red-light:" in css and "#F61D2D" in css, "brand --red-light token missing"
    assert "--critical-red:" in css and "#D32F2F" in css, "state-alarm token missing"
    # The ribbon's STOP state uses the state-alarm red, not a brand red.
    assert "#dtc-ribbon" in css
    assert 'data-level="stop"' in css
    # A subtle pulse so the ribbon reads as an alarm, never as decoration.
    assert "@keyframes" in css
    assert "animation" in css
    # A leading warning glyph element.
    assert ".ribbon-glyph" in css


def test_dashboardCss_takeoverPerSeverityStyles_s1_us405():
    """S-1: the takeover overlay is severity-styled (per-tier background)."""
    css = _read(KIT_DIR, "dashboard.css")
    assert "#dtc-takeover" in css
    for sev in ("stop", "watch", "minor"):
        assert f'data-severity="{sev}"' in css, f"takeover missing {sev} styling"


# ---------------------------------------------------------------------------
# US-406 -- DTC Alerts card (Card 5) + detail (F-111 / design §5.3-5.4).
# Hero (worst code + directive) + a tappable list sorted worst-first with `na`
# sorted LAST; a per-code detail view with a severity-GATED fix (🔴/🟡 replace
# the fix with a diagnose directive, NO raw fix even if suggestedFix is non-null;
# 🟢 shows the fix + a 3-state trust badge), the freeze-frame-or-realtime
# fallback, and the log/sync footer. The display maps a tier -> chip/color/
# directive ONLY; it never classifies (reads Spool's severity SSOT). All of it
# is pure + node-tested; the row/detail DOM is thin browser wiring.
# ---------------------------------------------------------------------------

_US406_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

function code(sev, cd, opts) {
  opts = opts || {};
  return {
    code: cd, severity: sev,
    short: opts.short === undefined ? (cd + ' desc') : opts.short,
    long: opts.long || null,
    status: opts.status || 'stored',
    setAtTs: opts.setAtTs || '2026-06-30T19:40:00Z',
    driveId: opts.driveId === undefined ? null : opts.driveId,
    freezeFrame: opts.freezeFrame === undefined ? null : opts.freezeFrame,
    suggestedFix: opts.suggestedFix === undefined ? null : opts.suggestedFix,
    fixProvenance: opts.fixProvenance || 'none',
    severityCaveat: opts.severityCaveat === undefined ? null : opts.severityCaveat,
    logged: opts.logged === undefined ? true : opts.logged,
    syncAcked: opts.syncAcked === undefined ? true : opts.syncAcked,
    clearEligible: opts.clearEligible === undefined ? false : opts.clearEligible,
  };
}
function dtc(codes) {
  return { mil: true, codes: codes, newSinceTs: null, clearGate: {},
           sessionResetLock: [], ts: '2026-06-30T19:40:05Z' };
}

// --- alertsCardView: hero = worst; rows worst-first; na sorts LAST -----------
const v = c.alertsCardView(dtc([
  code('minor', 'P0442', {short: 'Evap small leak'}),
  code('na', 'P1750', {short: 'Auto-trans solenoid'}),
  code('stop', 'P0301', {short: 'Cyl 1 misfire'}),
  code('watch', 'P0420', {short: 'Catalyst low'}),
]));
assert.ok(v, 'valid dtc -> card view');
assert.strictEqual(v.hero.code, 'P0301', 'hero = worst (stop)');
assert.strictEqual(v.hero.level, 'stop', 'hero chip level = stop');
assert.ok(/PULL OVER/i.test(v.hero.directive), 'hero carries the stop directive');
const order = v.rows.map(function (r) { return r.code; });
assert.deepStrictEqual(order, ['P0301', 'P0420', 'P0442', 'P1750'],
  'rows sorted worst-first, na LAST (S-12)');
assert.strictEqual(v.rows[3].chip, 'N/A', 'na row shows the quiet N/A chip');
assert.strictEqual(v.rows[3].isNa, true, 'na row flagged');
assert.strictEqual(v.storedCount, 4, 'stored count');
assert.strictEqual(v.pendingCount, 0, 'pending count');

// --- no-description code -> "No description yet" (I-3), never blank ----------
const nd = c.alertsCardView(dtc([code('unknown', 'P1601', {short: ''})]));
assert.strictEqual(nd.rows[0].short, 'No description yet', 'no-desc -> placeholder');
assert.strictEqual(nd.rows[0].chip, '?', 'unknown chip = ?');

// --- na-only -> NO hero block (S-12: na is never a hero) ---------------------
const naOnly = c.alertsCardView(dtc([code('na', 'P1750', {short: 'A/T'})]));
assert.strictEqual(naOnly.hero, null, 'na-only -> no hero block');
assert.strictEqual(naOnly.rows.length, 1, 'na still listed');

// --- malformed / empty (S-9 the card surface) -------------------------------
assert.strictEqual(c.alertsCardView(null), null, 'null -> unavailable');
assert.strictEqual(c.alertsCardView('x'), null, 'string -> unavailable');
const empty = c.alertsCardView(dtc([]));
assert.ok(empty, 'empty codes still a (no-fault) view');
assert.strictEqual(empty.hero, null, 'no codes -> no hero');
assert.strictEqual(empty.rows.length, 0, 'no rows');

// --- S-4 / F-1: 🔴/🟡 fix REPLACED by a diagnose directive, NO raw fix -------
const stopFix = c.codeDetailView(code('stop', 'P0301', {suggestedFix: 'Replace coil pack'}));
assert.strictEqual(stopFix.fix.mode, 'directive', 'stop fix = directive, not a raw fix');
assert.ok(!/coil pack/i.test(stopFix.fix.text), 'stop NEVER shows the raw fix text (F-1)');
assert.strictEqual(stopFix.fix.badge, null, 'no trust badge on a directive');
assert.ok(/PULL OVER/i.test(stopFix.directive), 'stop detail carries the directive band');
const watchFix = c.codeDetailView(code('watch', 'P0420', {suggestedFix: 'Replace catalytic converter'}));
assert.strictEqual(watchFix.fix.mode, 'directive', 'watch fix = directive');
assert.ok(!/catalytic/i.test(watchFix.fix.text), 'watch NEVER shows the raw fix (F-1)');

// --- S-4: 🟢 shows the fix + a trust badge per fixProvenance -----------------
const minVer = c.codeDetailView(code('minor', 'P0442',
  {suggestedFix: 'Check/tighten fuel cap', fixProvenance: 'spool-validated'}));
assert.strictEqual(minVer.fix.mode, 'fix', 'minor shows the fix');
assert.ok(/fuel cap/i.test(minVer.fix.text), 'minor shows the actual fix text');
assert.strictEqual(minVer.fix.badge.kind, 'verified', 'spool-validated -> verified badge');
const minCom = c.codeDetailView(code('minor', 'P0455',
  {suggestedFix: 'Inspect EVAP hoses', fixProvenance: 'auto-unverified'}));
assert.strictEqual(minCom.fix.badge.kind, 'community', 'auto-unverified -> community badge');
const minOff = c.codeDetailView(code('minor', 'P0440', {suggestedFix: null, fixProvenance: 'none'}));
assert.strictEqual(minOff.fix.badge.kind, 'offline', 'none -> offline badge');
assert.ok(!/null/i.test(minOff.fix.text), 'a missing fix is honest text, never "null"');

// --- S-5: missing freeze-frame -> labeled fallback, never blank -------------
const noFF = c.codeDetailView(code('minor', 'P0442', {freezeFrame: null}));
assert.strictEqual(noFF.freezeFrame.hasFrame, false, 'no freeze frame');
assert.ok(/no freeze frame captured/i.test(noFF.freezeFrame.fallbackText), 'labeled fallback');
assert.ok(noFF.freezeFrame.fallbackText.length > 0, 'never blank');
const withFF = c.codeDetailView(code('stop', 'P0301', {freezeFrame: {rpm: 4250, loadPct: 92}}));
assert.strictEqual(withFF.freezeFrame.hasFrame, true, 'freeze frame present');
assert.strictEqual(withFF.freezeFrame.grid.rpm, 4250, 'grid carries the snapshot');

// --- S-13: severityCaveat -> base chip, tier NOT auto-upgraded --------------
const caveat = c.codeDetailView(code('watch', 'P1300', {severityCaveat: 'stop if knock -- verify'}));
assert.strictEqual(caveat.level, 'watch', 'base tier stays WATCH (NOT auto-upgraded)');
assert.strictEqual(caveat.chip, 'WATCH', 'base chip = WATCH');
assert.ok(/knock/i.test(caveat.caveat), 'the caveat line is rendered');

// --- driveId: null -> "key-on read"; a number -> "Drive N" (US-404 A-9) -----
const koeo = c.codeDetailView(code('minor', 'P0443', {driveId: null}));
assert.ok(/key-on read/i.test(koeo.statusMeta), 'null driveId -> key-on read');
assert.ok(!/Drive/i.test(koeo.statusMeta), 'never fabricates a Drive N for a KOEO read');
const drv = c.codeDetailView(code('minor', 'P0443', {driveId: 27}));
assert.ok(/Drive 27/.test(drv.statusMeta), 'numeric driveId -> Drive N');

// --- na detail is a quiet N/A (no directive, no fix) ------------------------
const naDetail = c.codeDetailView(code('na', 'P1750', {short: 'A/T solenoid'}));
assert.strictEqual(naDetail.isNa, true, 'na flagged');
assert.strictEqual(naDetail.fix.mode, 'na', 'na fix disposition');
assert.strictEqual(naDetail.directive, null, 'na has no directive band');

// --- malformed detail -------------------------------------------------------
assert.strictEqual(c.codeDetailView(null), null, 'null -> no detail');
assert.strictEqual(c.codeDetailView('x'), null, 'string -> no detail');

// --- log/sync footer surfaces the capture-before-clear precondition ---------
const footer = c.codeDetailView(code('minor', 'P0442', {logged: true, syncAcked: true}));
assert.strictEqual(footer.logged, true, 'logged surfaced');
assert.strictEqual(footer.syncAcked, true, 'syncAcked surfaced');

console.log('US406_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_dtcAlertsCardAndDetailLogic_s4_s5_s12_s13_us406():
    """US-406: the Alerts card hero+list sort worst-first (na last), and the
    per-code detail severity-GATES the fix (🔴/🟡 diagnose directive, no raw fix;
    🟢 fix + trust badge), renders the freeze-frame-or-realtime fallback, keeps a
    severityCaveat from auto-upgrading the tier, and shows "key-on read" for a
    null driveId."""
    result = subprocess.run(
        ["node", "-e", _US406_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US406_OK" in result.stdout


def test_dashboardHtml_hasAlertsCardAndDetail_us406():
    """US-406: the Alerts card (Card 5) slot + the per-code detail overlay mount
    are present (JS fills their content per the polled `dtc` state)."""
    html = _read(KIT_DIR, "dashboard.html")
    assert 'data-state="dtc"' in html, "Alerts card slot missing"
    assert 'id="dtc-detail"' in html, "detail overlay mount missing"
    assert 'id="detail-back"' in html, "detail must have a Back control (never trapped)"
    assert 'id="detail-body"' in html


def test_dashboardCss_hasAlertsCardAndDetailStyles_us406():
    """US-406: chip styles per severity tier (incl. the quiet N/A) + the detail
    overlay + trust-badge + fix-directive styles exist."""
    css = _read(KIT_DIR, "dashboard.css")
    assert ".dtc-chip" in css
    for sev in ("stop", "watch", "minor", "na", "unknown"):
        assert f'.dtc-chip[data-level="{sev}"]' in css, f"chip missing {sev} styling"
    assert "#dtc-detail" in css
    assert ".dtc-fix-directive" in css
    assert ".dtc-trust-badge" in css


# ---------------------------------------------------------------------------
# US-407 -- DTC Clear (Mode-04) path (F-111 / design §6, Spool advisory §4).
# The clear button state mirrors the authoritative gate FOR DISPLAY (all stored
# codes MINOR + logged + server-acked; a STOP/WATCH or an un-synced code or a
# re-set code disables it with an honest reason); the hard confirm names the
# freeze-frame-erase + readiness-reset consequences (S-7); the post-clear message
# reports the re-read PROOF ("0 stored, 0 pending, MIL off"), never a bare
# "command sent", and surfaces an instant re-set (I-7 / S-8). The load-bearing
# gate re-check + the Mode-04 write live server-side (tests/pi/splash/
# test_dtc_clear.py + test_states_http_dtc_clear.py); this covers the UI logic.
# ---------------------------------------------------------------------------

_US407_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

function code(sev, cd, opts) {
  opts = opts || {};
  return {
    code: cd, severity: sev, status: opts.status || 'stored',
    logged: opts.logged === undefined ? true : opts.logged,
    syncAcked: opts.syncAcked === undefined ? true : opts.syncAcked,
  };
}
function dtc(codes, lock) {
  return { mil: true, codes: codes, newSinceTs: null,
           clearGate: { enabled: true, reason: 'ok' },
           sessionResetLock: lock || [], ts: '2026-06-30T19:42:00Z' };
}

// --- S-6 ok: all MINOR + logged + synced -> enabled -------------------------
const ok = c.clearButtonView(dtc([code('minor', 'P0443')]));
assert.strictEqual(ok.visible, true, 'clearable -> button visible');
assert.strictEqual(ok.enabled, true, 'S-6 ok -> enabled');
assert.strictEqual(ok.reason, 'ok');

// --- S-6/S-10 display mirror: a STOP present -> disabled, IGNORES clearGate --
const sev = c.clearButtonView(dtc([code('minor', 'P0443'), code('stop', 'P0301')]));
assert.strictEqual(sev.enabled, false, 'stop present -> disabled (re-derived, not trusting clearGate.enabled)');
assert.strictEqual(sev.reason, 'severity_present');
assert.ok(/STOP\/WATCH/i.test(sev.label), 'label names the STOP/WATCH block');

// --- S-6 sync_pending: MINOR not server-acked -> disabled -------------------
const syn = c.clearButtonView(dtc([code('minor', 'P0443', {syncAcked: false})]));
assert.strictEqual(syn.enabled, false);
assert.strictEqual(syn.reason, 'sync_pending');
assert.ok(/server sync/i.test(syn.label), 'label = waiting for server sync');

// --- S-8 session-locked -> disabled, "don't chase the light" ----------------
const lk = c.clearButtonView(dtc([code('minor', 'P0443')], ['P0443']));
assert.strictEqual(lk.enabled, false);
assert.strictEqual(lk.reason, 'session_locked');
assert.ok(/returned|won't fix/i.test(lk.label), 'session-lock label');

// --- nothing clearable -> no button (no codes / na-only) --------------------
assert.strictEqual(c.clearButtonView(dtc([])).visible, false, 'no codes -> no button');
assert.strictEqual(c.clearButtonView(dtc([code('na', 'P1750')])).visible, false,
  'na-only -> no clear button (not a real fault)');
assert.strictEqual(c.clearButtonView(null).visible, false, 'malformed -> no button');

// --- S-7 confirm copy: freeze-frame erase + readiness reset -----------------
const cf = c.confirmClearText();
assert.ok(/freeze.?frame/i.test(cf.body), 'S-7 confirm names the freeze-frame erase');
assert.ok(/readiness|emissions/i.test(cf.body), 'S-7 confirm names the readiness reset');
assert.ok(/drive cycle/i.test(cf.body), 'S-7 names the drive-cycle consequence');
assert.ok(cf.confirmLabel && cf.cancelLabel, 'confirm + cancel labels present');

// --- postClearMessage: cleared (I-6) -> the re-read PROOF, not "command sent"
const m1 = c.postClearMessage(
  {issued: true, cleared: true, storedAfter: [], pendingAfter: [], milAfter: false, reSetCodes: []});
assert.strictEqual(m1.level, 'cleared');
assert.ok(/0 stored/i.test(m1.text) && /mil off/i.test(m1.text), 'proof text');
assert.ok(!/command sent/i.test(m1.text), 'never a bare command-sent');

// --- postClearMessage: instant re-set (I-7 / S-8) ---------------------------
const m2 = c.postClearMessage(
  {issued: true, cleared: false, storedAfter: ['P0443'], pendingAfter: [], milAfter: true, reSetCodes: ['P0443']});
assert.strictEqual(m2.level, 'reset');
assert.ok(/P0443/.test(m2.text) && /returned/i.test(m2.text), 're-set names the code');
assert.ok(/won't fix|real fault/i.test(m2.text), "don't-chase-the-light copy");

// --- postClearMessage: gate rejected server-side -> honest blocked ----------
const m3 = c.postClearMessage({issued: false, reason: 'severity_present'});
assert.strictEqual(m3.level, 'blocked', 'a server-side gate rejection is surfaced honestly');

console.log('US407_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_dtcClearLogic_s6_s7_s8_us407():
    """US-407: the clear button mirrors the authoritative gate for display (S-6/
    S-8), the confirm copy names the freeze-frame + readiness consequences (S-7),
    and the post-clear message reports the re-read proof, never "command sent"."""
    result = subprocess.run(
        ["node", "-e", _US407_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US407_OK" in result.stdout


def test_dashboardHtml_hasClearButtonAndConfirm_us407():
    """US-407: the Clear button + result line + a dedicated hard-confirm modal
    mount are present (JS gates the button + wires the POST /dtc-clear flow)."""
    html = _read(KIT_DIR, "dashboard.html")
    assert 'id="dtc-clear-btn"' in html, "Clear button mount missing"
    assert 'id="dtc-clear-result"' in html, "clear result line missing"
    assert 'id="clear-confirm"' in html, "clear confirm modal missing"
    assert 'id="clear-confirm-ok"' in html, "confirm OK missing"
    assert 'id="clear-confirm-cancel"' in html, "confirm Cancel missing (never trapped)"


def test_dashboardCss_hasClearButtonStyles_us407():
    """US-407: the Clear button carries an enabled + a visibly-inert disabled
    state, and the confirm modal + its ≥40px tap targets exist."""
    css = _read(KIT_DIR, "dashboard.css")
    assert "#dtc-clear-btn" in css
    assert "#dtc-clear-btn:disabled" in css or "#dtc-clear-btn[disabled]" in css, (
        "the disabled Clear button must be visibly inert"
    )
    assert "#clear-confirm" in css


# ---------------------------------------------------------------------------
# US-420 -- LTFT Trend card render logic (F-096). The card is a PURE CONSUMER of
# the `ltft-trend` emitter (which CLASSIFIES the drift + the insufficient guard);
# the view only maps the verdict -> a tile level + bar colours. The honest-
# instrument rule: an insufficient window NEVER renders a green/ok headline, and
# a drift beyond +/-10% is visibly distinct (down) from a healthy trend.
# ---------------------------------------------------------------------------

_US420_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

// A non-object payload -> no view (the shell renders `unavailable`).
assert.strictEqual(c.ltftTrendView(null), null, 'null -> no view');
assert.strictEqual(c.ltftTrendView('x'), null, 'string -> no view');
assert.strictEqual(c.ltftTrendView([]), null, 'array -> no view');

function pt(driveId, avg, level) {
  return { driveId: driveId, ts: null, ltftAvg: avg, level: level };
}
function trend(opts) {
  return {
    pid: 'LONG_FUEL_TRIM_1',
    sufficient: opts.sufficient,
    level: opts.level,
    driveCount: opts.points.length,
    minDrives: 2,
    okAbs: 5.0, driftAbs: 10.0,
    trend: opts.trend === undefined ? null : opts.trend,
    current: opts.points.length ? opts.points[opts.points.length - 1] : null,
    points: opts.points,
    ts: '2026-07-01T12:00:00Z',
  };
}

// --- healthy sufficient window -> headline ok, points carried ----------------
const healthy = c.ltftTrendView(trend({
  sufficient: true, level: 'ok', trend: 'improving',
  points: [pt(31, -8.0, 'amber'), pt(32, -4.0, 'ok'), pt(33, -2.0, 'ok')],
}));
assert.ok(healthy, 'valid state -> a view');
assert.strictEqual(healthy.sufficient, true, 'sufficient carried');
assert.strictEqual(healthy.headline.level, 'ok', 'healthy -> ok headline');
assert.ok(/-2\.00%/.test(healthy.headline.value), 'headline = current drift');
assert.ok(/toward 0/i.test(healthy.headline.detail), 'improving trend surfaced');
assert.strictEqual(healthy.points.length, 3, 'all drive points carried');
assert.deepStrictEqual(healthy.points.map(function (p) { return p.level; }),
  ['amber', 'ok', 'ok'], 'each bar keeps its own drift level');
assert.strictEqual(healthy.points[0].value, '-8.00%', 'bar value formatted');

// --- drift beyond +/-10% -> headline down (visibly distinct from healthy) -----
const drift = c.ltftTrendView(trend({
  sufficient: true, level: 'down', trend: 'worsening',
  points: [pt(31, -6.0, 'amber'), pt(32, -9.0, 'amber'), pt(33, -14.0, 'down')],
}));
assert.strictEqual(drift.headline.level, 'down', 'drift -> down headline');
assert.notStrictEqual(drift.headline.level, healthy.headline.level, 'down != ok');
assert.strictEqual(drift.points[2].level, 'down', 'the drifted drive bar is down');

// --- insufficient window -> NEVER green (honest-instrument, forced here too) --
const thin = c.ltftTrendView(trend({
  sufficient: false, level: 'insufficient', points: [pt(33, -2.0, 'ok')],
}));
assert.strictEqual(thin.sufficient, false, 'insufficient carried');
assert.strictEqual(thin.headline.level, 'insufficient', 'insufficient headline');
assert.notStrictEqual(thin.headline.level, 'ok', 'never green off too little data');
assert.ok(/insufficient/i.test(thin.headline.value), 'value says insufficient');
assert.ok(/need 2\+/i.test(thin.headline.detail), 'detail names the min-drives need');
assert.strictEqual(thin.points.length, 1, 'the single point still listed honestly');

// --- defense-in-depth: a mislabeled ok level with sufficient:false stays muted
const lying = c.ltftTrendView(trend({
  sufficient: false, level: 'ok', points: [pt(33, -2.0, 'ok')],
}));
assert.strictEqual(lying.headline.level, 'insufficient',
  'sufficient:false forces insufficient even if the state claims ok');

// --- empty points -> insufficient, no crash ----------------------------------
const empty = c.ltftTrendView(trend({ sufficient: true, level: 'ok', points: [] }));
assert.strictEqual(empty.sufficient, false, 'no points -> not sufficient');
assert.strictEqual(empty.headline.level, 'insufficient', 'no points -> insufficient');
assert.strictEqual(empty.points.length, 0, 'no bars');

// --- fmtLtftPct: signed 2dp; non-number -> "--" ------------------------------
assert.strictEqual(c.fmtLtftPct(-6.25), '-6.25%', 'negative sign kept');
assert.strictEqual(c.fmtLtftPct(2.1), '+2.10%', 'positive gets a + and 2dp');
assert.strictEqual(c.fmtLtftPct(0), '0.00%', 'zero has no sign');
assert.strictEqual(c.fmtLtftPct(null), '--', 'non-number -> placeholder');

console.log('US420_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_ltftTrendView_renderLogic_f096_us420():
    """US-420: the LTFT Trend view maps the emitter verdict -> an honest headline
    + per-drive bars (healthy ok, drift-beyond-10 down/distinct, insufficient
    never green), formatting signed 2-dp percents."""
    result = subprocess.run(
        ["node", "-e", _US420_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US420_OK" in result.stdout


def test_dashboardHtml_hasFuelTrimSlot_us420_us507():
    """US-420: the fuel-trim surface is present and bound to the `ltft-trend`
    state.

    RETITLED + RELOCATED BY US-507: it is now the "Fuel Trim" SECTION of the
    merged Health card, not a standalone "LTFT Trend" card. The jargon left the
    title; Spool's LTFT semantics did not move at all (the view function and its
    insufficient/drift rules are untouched). The old title is asserted GONE
    rather than merely unasserted -- leaving it in the markup alongside the new
    one is how a half-applied retitle ships.
    """
    html = _read(KIT_DIR, "dashboard.html")
    assert 'data-states="battery-health light ltft-trend"' in html, (
        "the fuel-trim surface is no longer bound to its state file"
    )
    assert "Fuel Trim" in html
    # The old-title pin must read the RENDERED markup, not the comments: the
    # section comment explains the retitle and therefore contains the old title.
    # A pin that greps a defect's NAME otherwise fires on its own documentation.
    markup = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "Fuel Trim" in markup, "the stripper ate the markup -- the pin below is vacuous"
    assert "LTFT Trend" not in markup


def test_dashboardCss_hasLtftTrendStyles_us420():
    """US-420: the per-drive bar styles bind ok/amber/down to the palette so a
    drifted drive is visibly not-green, and the insufficient headline is muted."""
    css = _read(KIT_DIR, "dashboard.css")
    assert ".ltft-bars" in css
    assert ".ltft-bar" in css
    assert '.ltft-bar[data-level="down"]  .ltft-bar-value' in css or (
        '.ltft-bar[data-level="down"]' in css
    )
    assert '.tile[data-level="insufficient"]' in css


# ---------------------------------------------------------------------------
# US-421 -- power-mode badge (F-098 / BL-014): the tile renders CAR / WALL /
# unknown from the PowerModeProvider SSOT value, and NEVER coerces an
# undeterminable/invalid mode into a confident CAR (honest-instrument).
# ---------------------------------------------------------------------------

_US421_NODE_SCRIPT = r"""
const assert = require('assert');
const c = require(process.argv[1]);

// A known car mode on external power -> confident CAR badge.
const car = c.powerTile({mode: 'car', source: 'external'});
assert.strictEqual(car.value, 'CAR', 'car -> CAR');

// A known wall (bench) mode -> confident WALL badge.
const wall = c.powerTile({mode: 'wall', source: 'external'});
assert.strictEqual(wall.value, 'WALL', 'wall -> WALL');

// Explicit unknown -> honest lowercase 'unknown', NOT a confident CAR/WALL.
const unk = c.powerTile({mode: 'unknown', source: 'external'});
assert.strictEqual(unk.value, 'unknown', 'unknown -> unknown badge');

// Absent mode -> unknown (never defaults to CAR -- the BL-014 bug this fixes).
const absent = c.powerTile({source: 'external'});
assert.strictEqual(absent.value, 'unknown', 'absent mode -> unknown, not CAR');

// Invalid/garbage mode -> unknown (honest), never a confident wrong mode.
const bad = c.powerTile({mode: 'garage', source: 'external'});
assert.strictEqual(bad.value, 'unknown', 'invalid mode -> unknown');
const upper = c.powerTile({mode: 'CAR', source: 'external'});
assert.strictEqual(upper.value, 'unknown', 'case-mismatch mode -> unknown');

// On battery the value is BATTERY and the MODE rides in the detail -- it must
// still be honest (unknown mode -> 'unknown ...' in detail, never 'car ...').
const batUnknown = c.powerTile({mode: 'unknown', source: 'battery'});
assert.strictEqual(batUnknown.value, 'BATTERY', 'battery value unchanged');
assert.ok(/unknown/.test(batUnknown.detail), 'battery detail honest for unknown');
assert.ok(!/\bcar\b/.test(batUnknown.detail), 'battery detail not confidently car');
const batWall = c.powerTile({mode: 'wall', source: 'battery'});
assert.ok(/wall/.test(batWall.detail), 'battery detail carries wall');

// End-to-end through the structured view the DOM renderer consumes.
const view = c.systemStatusView({
  obdLink: {state: 'linked', retries: 0, lastSeenS: 2},
  sync: {lastOkTs: '2026-07-01T00:00:00Z', rows: 1, pending: 0, stale: false},
  power: {mode: 'unknown', source: 'external'},
  drive: {state: 'idle', driveId: null},
  ts: '2026-07-01T00:00:01Z'
});
assert.strictEqual(view.tiles.power.value, 'unknown', 'view power tile honest');

console.log('US421_OK');
"""


@pytest.mark.skipif(not _nodeAvailable(), reason="node not available on PATH")
def test_powerTile_renderLogic_carWallUnknown_us421():
    """US-421: the power-mode badge renders CAR / WALL / unknown from the SSOT
    value and never coerces an undeterminable/invalid mode into a confident CAR
    (BL-014 honest-instrument)."""
    result = subprocess.run(
        ["node", "-e", _US421_NODE_SCRIPT, str(KIT_DIR / "carousel.js")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "US421_OK" in result.stdout


# ---------------------------------------------------------------------------
# US-536 (disposition B) -- the kiosk keeps the GPU ON. These guards were built
# for US-522, which shipped `--disable-gpu`; US-548 INVERTED them when the CIO
# ruled disposition B and US-536 (commit 3e67e5d) removed the flag from both
# units. The guards are inverted rather than deleted, because deleting them
# would leave NOTHING pinning "the GPU flag did not come back" -- which is the
# regression US-537's animation-gating work cares about.
#
# THE HISTORY IS KEPT DELIBERATELY, because it is what makes the new assertion
# legible. The bench freeze was a chromium GPU command-buffer hot-loop (6M
# `AllocateRingBuffer() kFatalFailure` in one boot, renderer+GPU CPU-pegged, no
# crash) -- the v3d GPU on a 64 MiB CMA pool exhausted its context under the
# animated carousel. Atlas RCA:
# offices/architect/findings/2026-08-02-pi-ui-freeze-chromium-gpu-command-buffer-hotloop.md
#
# US-522 answered that by DISABLING the GPU. Disposition B rejected that trade:
# `--disable-gpu` is a workaround on trusted hardware, and the durable fix is to
# stop the sustained compositing pressure instead -- auto-rotate off by default
# (US-536 AC-2) plus the US-537 animation gating. So the GPU stays on and the
# repo must now prove the workaround is ABSENT.
#
# WHAT THE REPO STILL CANNOT ASSERT, unchanged by disposition B: the offending
# `--enable-gpu-rasterization` is NOT in this repo. It is a Debian/RPi-OS system
# default exported by `/etc/chromium.d/default-flags`, sourced by the
# `/usr/bin/chromium` wrapper (`exec ... $CHROMIUM_FLAGS "$@"`, verified live on
# the Pi at 10.27.27.100), so the OS flags land FIRST and our argv lands LAST.
# We can only guard OUR argv -- see the deploy-contract blind-spot guard below.
# ---------------------------------------------------------------------------

# The token US-522 shipped and disposition B removed: it takes the whole
# hardware-GL path out. Under US-548 this names the flag that must NOT appear on
# either unit's ExecStart. It is still compared as a TOKEN, never a substring --
# and note the substring trap INVERTS with the guard. Under US-522's PRESENCE
# check, `"--disable-gpu" in text` would have accepted the narrower
# `--disable-gpu-rasterization` as if it were the chosen fix (a false NEGATIVE).
# Under this ABSENCE check, the same naive text search would REJECT a unit that
# legitimately carried `--disable-gpu-rasterization` (a false POSITIVE). Exact
# list membership is correct in both directions; that is why the token parser
# below is preserved rather than simplified.
_GPU_DISABLE_FLAG = "--disable-gpu"
_DASHBOARD_UNITS = ("dashboard.service.wayland", "dashboard.service.x11")


def _execStartFlags(unit: str) -> list[str]:
    """Tokenize a unit's ExecStart command: comments stripped, `\\` joined.

    Returning TOKENS (not the raw text) is deliberate and is what makes the
    US-522 guards mutation-proof in two ways a substring check is not:

    1. `"--disable-gpu" in "--disable-gpu-rasterization"` is True as a
       substring, so a text-level guard would accept the narrower flag as if it
       were the chosen fix. List membership is exact.
    2. A COMMENT that merely discusses the flag can never satisfy the guard --
       the recurring trap from US-501/US-513, where a static check tripped on
       (or was satisfied by) the prose documenting the very thing it guards.
    """
    tokens: list[str] = []
    inExec = False
    for raw in unit.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            continue
        if line.startswith("ExecStart="):
            inExec = True
            line = line[len("ExecStart=") :]
        elif not inExec:
            continue
        continues = line.endswith("\\")
        if continues:
            line = line[:-1].strip()
        tokens.extend(line.split())
        if not continues:
            break
    return tokens


def test_execStartFlagParser_selfTest_us522():
    """The guard's own parser, fed known-bad input (US-513 lesson: a static guard
    without a self-test reports 'clean' forever once its logic rots).

    US-548 raised the stakes on this self-test. While the GPU guard asserted
    PRESENCE, a broken parser failed LOUDLY -- an empty token list could not
    contain the flag. Now that the same guard asserts ABSENCE, a parser that
    returns nothing passes it VACUOUSLY, and so would a parser that silently
    stopped finding the ExecStart at all. The positive control below is what
    replaces the safety net that inverting the guard removed.
    """
    # A commented-out ExecStart must not contribute tokens.
    parsed = _execStartFlags(
        "# ExecStart=/bogus --disable-gpu\n"
        "[Service]\n"
        "ExecStart=/usr/bin/chromium \\\n"
        "  --kiosk \\\n"
        "  http://127.0.0.1:9899/dashboard.html\n"
        "Restart=on-failure\n"
    )
    assert parsed == ["/usr/bin/chromium", "--kiosk", "http://127.0.0.1:9899/dashboard.html"]
    # Inverted meaning under disposition B: a COMMENT that merely discusses the
    # flag must not TRIP the absence guard. This is live, not hypothetical --
    # both shipped units still carry the US-522 rationale in their headers.
    assert _GPU_DISABLE_FLAG not in parsed, "a comment must never trip the guard"
    # POSITIVE CONTROL (US-548): the parser must still FIND the flag when it is
    # genuinely on the ExecStart. Without this, `_GPU_DISABLE_FLAG not in flags`
    # would hold for a parser that had rotted into returning [].
    assert _GPU_DISABLE_FLAG in _execStartFlags(
        f"ExecStart=/usr/bin/chromium {_GPU_DISABLE_FLAG} http://h/\n"
    ), "the absence guard is vacuous unless the parser can still detect the flag"
    # The substring trap, which INVERTS with the guard: under an absence check a
    # naive text search would read the legitimate narrower flag as a violation.
    assert _GPU_DISABLE_FLAG not in _execStartFlags(
        "ExecStart=/usr/bin/chromium --disable-gpu-rasterization http://h/\n"
    ), "--disable-gpu-rasterization must not read as --disable-gpu"
    # Directives after the ExecStart block are not flags.
    assert "Restart=on-failure" not in parsed


def test_dashboardUnits_keepTheGpuOn_us536():
    """US-536 disposition B: NEITHER kiosk variant may disable the GPU.

    The inversion of US-522's guard. `--disable-gpu` was a workaround on trusted
    hardware; the CIO ruled it out in favour of removing the compositing
    pressure itself (auto-rotate off by default + US-537's animation gating).
    This guard is what stops the workaround silently returning the next time
    someone chases a freeze -- the reason the test was inverted, not deleted.
    """
    for variant in _DASHBOARD_UNITS:
        flags = _execStartFlags(_read(KIT_DIR, variant))
        assert _GPU_DISABLE_FLAG not in flags, (
            f"{variant}: ExecStart must NOT carry {_GPU_DISABLE_FLAG} -- disposition B "
            "(US-536) keeps the GPU ON and fixes the freeze by removing the sustained "
            "compositing load instead. Re-adding it reopens a settled architecture call."
        )


def test_dashboardUnits_neverReinjectGpuRasterization_us522():
    """US-522: our units must never (re-)assert GPU rasterization themselves.

    The repo cannot delete the OS-shipped default, but it must not add a second
    copy of it -- that would be arguing with our own override.
    """
    for variant in _DASHBOARD_UNITS:
        flags = _execStartFlags(_read(KIT_DIR, variant))
        assert "--enable-gpu-rasterization" not in flags, variant
        assert "--enable-gpu" not in flags, variant


def test_dashboardUnits_gpuOverrideDoesNotDisplacePriorFlags_us522():
    """US-522 regression fence: adding the override must not drop what the kiosk
    already needed (touch, kiosk mode, the same-origin dashboard URL)."""
    for variant in _DASHBOARD_UNITS:
        flags = _execStartFlags(_read(KIT_DIR, variant))
        assert "--kiosk" in flags, variant
        assert "--touch-events=enabled" in flags, variant
        assert "http://127.0.0.1:9899/dashboard.html" in flags, variant
        # The wayland variant keeps its ozone platform (a dropped ozone flag on
        # Wayland is the D-3 black-screen class).
        if variant.endswith(".wayland"):
            assert "--ozone-platform=wayland" in flags, variant


def test_deployPi_documentsChromiumDDeployBlindSpot_us522():
    """US-522 / A-16 deploy-contract blind spot: chromium's base flags live in an
    OS-shipped `/etc/chromium.d/` file the repo does NOT manage, so a chromium
    package upgrade can re-introduce GPU raster (or add a new flag) with no repo
    change at all. deploy-pi.sh must NAME that surface so it stays known."""
    sh = _read(DEPLOY_DIR, "deploy-pi.sh")
    assert "/etc/chromium.d" in sh, (
        "deploy-pi.sh must document the unmanaged /etc/chromium.d flag surface "
        "(A-16: the deploy contract silently depends on an OS-shipped file)"
    )


# ---------------------------------------------------------------------------
# US-522 (reopen 2026-08-03) -- kiosk keyring popup (Atlas live-tested).
#
# With no `--password-store`, chromium AUTO-DETECTS a Linux backend and picks the
# GNOME keyring for its OSCrypt "Safe Storage" key. The Pi's Default keyring is
# password-protected (`~/.local/share/keyrings/Default_Keyring.keyring`, 0600),
# and under PASSWORDLESS auto-login `pam_gnome_keyring` never unlocks it -- so
# the collection stays LOCKED, chromium's unlock request reaches `gcr-prompter`,
# and an "Authentication Required" dialog is painted OVER the kiosk.
#
# GROUNDED LIVE on the Pi (10.27.27.100), and the timeline is what proves this
# belongs to the DASHBOARD unit and not the splash:
#   gcr-prompter PerformPrompt at Aug 03 05:43:09, 08:33:52, 08:52:23  -- i.e. it
#   RECURS, and every one of them is ~9h AFTER splash-boot exited (Aug 02
#   20:20:21). No prompt fired in the splash's own 9.8s window. The prompts track
#   the long-running dashboard chromium, so the dashboard units are the right
#   (and sufficient) place for the fix. The splash's latent exposure is filed as
#   tech debt rather than silently fixed here -- it is a different unit template.
#
# The fix's EFFECT is also observable in the journal once applied (Atlas's live
# run carried `--enable-logging=stderr`, which the repo deliberately does not):
#   key_storage_linux.cc:116  Selected backend for OSCrypt: BASIC_TEXT
# `basic` keeps the safe-storage key in chromium's own profile -- and this kiosk's
# profile is a WIPED `/tmp/dashboard-chromium` that stores no real password, so
# there is no meaningful security downgrade.
# ---------------------------------------------------------------------------

_PASSWORD_STORE_FLAG = "--password-store=basic"


def _passwordStoreValues(unit: str) -> list[str]:
    """Every `--password-store=<value>` VALUE on the unit's ExecStart.

    Returning the values (not a boolean "is the flag there") is what makes the
    guard able to fail in the direction that actually matters: `--password-store`
    is a VALUED switch, so a prefix/substring check would happily accept
    `--password-store=gnome` -- which is precisely the broken configuration this
    story exists to eliminate, not a fix for it.
    """
    prefix = "--password-store="
    return [t[len(prefix) :] for t in _execStartFlags(unit) if t.startswith(prefix)]


def test_passwordStoreParser_selfTest_us522():
    """The keyring guard's own parser, fed known-bad input (US-513 lesson: an
    un-self-tested static guard reports 'clean' forever once its logic rots)."""
    # The trap this helper exists for: the WRONG backend must not read as a fix.
    assert _passwordStoreValues("ExecStart=/usr/bin/chromium --password-store=gnome http://h/\n") == [
        "gnome"
    ], "a valued switch must be compared by VALUE, not by prefix presence"
    # A comment discussing the flag can never satisfy the guard.
    assert _passwordStoreValues(
        "# ExecStart=/bogus --password-store=basic\nExecStart=/usr/bin/chromium --kiosk http://h/\n"
    ) == []
    assert _passwordStoreValues(f"ExecStart=/usr/bin/chromium {_PASSWORD_STORE_FLAG} http://h/\n") == [
        "basic"
    ]


def test_dashboardUnits_carryPasswordStoreBasic_us522():
    """US-522 reopen: both kiosk variants must pin the OSCrypt backend to `basic`.

    Without it chromium auto-selects the GNOME keyring, whose password-protected
    Default collection is never unlocked under passwordless auto-login -> a
    recurring gcr-prompter "Authentication Required" dialog over the kiosk.
    """
    for variant in _DASHBOARD_UNITS:
        values = _passwordStoreValues(_read(KIT_DIR, variant))
        assert values == ["basic"], (
            f"{variant}: ExecStart must carry exactly {_PASSWORD_STORE_FLAG} "
            f"(found {values!r}) -- an unset or keyring-backed password store "
            "paints a keyring auth popup over the kiosk (Atlas, live-tested)"
        )


def test_dashboardUnits_neverSelectKeyringBackedPasswordStore_us522():
    """US-522 reopen, the awkward direction: no variant may select a LOCKED
    backend. `gnome`/`gnome-libsecret`/`kwallet*` all route through a collection
    that passwordless auto-login leaves locked -- i.e. they re-open the defect
    while still 'having a --password-store flag'."""
    for variant in _DASHBOARD_UNITS:
        for value in _passwordStoreValues(_read(KIT_DIR, variant)):
            assert value == "basic", f"{variant}: --password-store={value} re-opens the keyring popup"


def test_dashboardUnits_keyringFixSurvivedTheGpuRevert_us536():
    """The half of the old coexistence fence that DISPOSITION B DID NOT CHANGE.

    US-522 shipped two flags on one ExecStart and this guard held them together.
    US-536 removed one of them, and the risk it leaves behind is precisely that
    a revert aimed at the GPU flag takes the keyring fix with it -- they are
    adjacent lines in the same continuation block. So the fence stays, with the
    GPU half inverted: keyring PRESENT, GPU-disable ABSENT, both on one pass.
    """
    for variant in _DASHBOARD_UNITS:
        flags = _execStartFlags(_read(KIT_DIR, variant))
        assert _PASSWORD_STORE_FLAG in flags, (
            f"{variant}: lost the US-522 keyring fix -- it explicitly STAYS under "
            "disposition B (US-536 AC-1); only the GPU flag was reverted"
        )
        assert _GPU_DISABLE_FLAG not in flags, f"{variant}: the GPU workaround came back"
        # And the pre-existing kiosk contract still stands.
        assert "--kiosk" in flags, variant
        assert "http://127.0.0.1:9899/dashboard.html" in flags, variant


def test_dashboardUnits_carryNoRemoteDebuggingPort_us522():
    """US-522 reopen -- do NOT import the live box's debug flags along with the fix.

    The hand-patched unit on the Pi carried `--enable-logging=stderr` and
    `--remote-debugging-port=9222` beside Atlas's `--password-store=basic`. Those
    were debugging aids for the live test; an open DevTools port on a
    car-mounted kiosk is an unauthenticated full-page-control surface, and it
    must not reach the repo just because it sat next to the flag being adopted.
    """
    for variant in _DASHBOARD_UNITS:
        flags = _execStartFlags(_read(KIT_DIR, variant))
        offenders = [f for f in flags if f.startswith("--remote-debugging-")]
        assert offenders == [], f"{variant}: kiosk must not expose DevTools ({offenders!r})"
