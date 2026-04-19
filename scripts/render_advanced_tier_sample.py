#!/usr/bin/env python3
################################################################################
# File Name: render_advanced_tier_sample.py
# Purpose/Description: Offscreen pygame render of the US-165 advanced-tier screen
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-165 Spool Gate 2
# ================================================================================
################################################################################
"""
Render a sample advanced-tier primary screen to a PNG.

Used for the Spool Gate 2 review packet: produces an offscreen 480x320
pygame surface with representative simulator data, and dumps it to
``offices/tuner/inbox/us165-gate2/advanced_tier_sample.png`` (or the path
passed via ``--out``).

Usage (Windows dev)::

    python scripts/render_advanced_tier_sample.py
    python scripts/render_advanced_tier_sample.py --scenario caution
    python scripts/render_advanced_tier_sample.py --out /tmp/screen.png

Scenarios (all thresholds match ``config.json`` tieredThresholds):
    normal    -- RPM 2400 / Coolant 195F / everything green
    caution   -- RPM 6700 / Coolant 215F (both orange)
    danger    -- RPM 7500 / Coolant 225F (both red)
    cold      -- Coolant 150F (blue) + other-normal
    fresh     -- no history yet (empty GaugeHistory, placeholder brackets)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Headless pygame: choose the 'dummy' SDL video driver so this script runs
# on CI and SSH sessions without an X server / HDMI output.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from pi.display.screens.primary_screen_advanced import (  # noqa: E402
    AdvancedTierFooter,
    AdvancedTierHeader,
    ConnectionState,
    ConnectivityIndicators,
    GaugeHistory,
    MinMaxMarker,
    buildAdvancedTierScreenState,
    computeAdvancedTierLayout,
)

_DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent
    / "offices"
    / "tuner"
    / "inbox"
    / "us165-gate2"
    / "advanced_tier_sample.png"
)

_THRESHOLDS = {
    "coolantTemp": {"normalMin": 180.0, "cautionMin": 210.0, "dangerMin": 220.0},
    "rpm": {"normalMin": 600.0, "cautionMin": 6500.0, "dangerMin": 7000.0},
}

_SCENARIOS: dict[str, dict[str, float]] = {
    "normal": {
        "RPM": 2400.0,
        "COOLANT_TEMP": 195.0,
        "BOOST": 8.5,
        "AFR": 14.2,
        "SPEED": 35.0,
        "BATTERY_VOLTAGE": 14.1,
    },
    "caution": {
        "RPM": 6700.0,
        "COOLANT_TEMP": 215.0,
        "BOOST": 12.0,
        "AFR": 12.8,
        "SPEED": 65.0,
        "BATTERY_VOLTAGE": 14.0,
    },
    "danger": {
        "RPM": 7500.0,
        "COOLANT_TEMP": 225.0,
        "BOOST": 14.8,
        "AFR": 11.5,
        "SPEED": 85.0,
        "BATTERY_VOLTAGE": 13.9,
    },
    "cold": {
        "RPM": 800.0,
        "COOLANT_TEMP": 150.0,
        "BOOST": -5.0,
        "AFR": 16.0,
        "SPEED": 0.0,
        "BATTERY_VOLTAGE": 14.2,
    },
    "fresh": {
        "RPM": 820.0,
        "COOLANT_TEMP": 185.0,
        "BOOST": 0.0,
        "AFR": 14.7,
        "SPEED": 0.0,
        "BATTERY_VOLTAGE": 14.1,
    },
}

_HISTORY_FIVE_DRIVES = GaugeHistory(
    driveCount=5,
    markers={
        "RPM": MinMaxMarker(minValue=780.0, maxValue=6200.0),
        "COOLANT_TEMP": MinMaxMarker(minValue=150.0, maxValue=212.0),
        "BOOST": MinMaxMarker(minValue=-5.0, maxValue=14.8),
        "AFR": MinMaxMarker(minValue=10.4, maxValue=18.0),
        "SPEED": MinMaxMarker(minValue=0.0, maxValue=75.0),
        "BATTERY_VOLTAGE": MinMaxMarker(minValue=12.4, maxValue=14.6),
    },
)


def _renderSurfaceForScenario(scenario: str) -> pygame.Surface:
    readings = _SCENARIOS[scenario]
    history = GaugeHistory() if scenario == "fresh" else _HISTORY_FIVE_DRIVES
    driveCount = 0 if scenario == "fresh" else 42
    lastSyncSec: float | None = None if scenario == "fresh" else 1_700_000_000.0 - 180
    nowSec = 1_700_000_000.0

    header = AdvancedTierHeader(
        hostname="Eclipse-01",
        connectivity=ConnectivityIndicators(
            obd=(
                ConnectionState.CONNECTED
                if scenario != "fresh"
                else ConnectionState.DISCONNECTED
            ),
            wifi=ConnectionState.CONNECTED,
            sync=(
                ConnectionState.CONNECTED
                if scenario not in ("fresh", "danger")
                else ConnectionState.ERROR if scenario == "danger"
                else ConnectionState.DISCONNECTED
            ),
        ),
    )
    footer = AdvancedTierFooter(
        alertMessages=[],
        lastSyncSeconds=lastSyncSec,
        nowSeconds=nowSec,
        totalDriveCount=driveCount,
        batterySocPercent=87.0,
        powerSource="ac_power",
    )
    state = buildAdvancedTierScreenState(
        readings=readings,
        thresholdConfigs=_THRESHOLDS,
        header=header,
        footer=footer,
        history=history,
    )
    layout = computeAdvancedTierLayout(state, width=480, height=320)

    # Draw using the existing primary_renderer primitives -- we inline the
    # render loop here to avoid depending on a full pygame.display, since
    # that path requires a real window on some platforms.
    from pi.display.screens import primary_renderer

    if not primary_renderer.PYGAME_AVAILABLE:
        raise RuntimeError("pygame is unavailable -- cannot render screenshot")

    pygame.font.init()
    surface = pygame.Surface((480, 320))
    surface.fill(primary_renderer.DEFAULT_BACKGROUND)
    for element in layout:
        # ``_drawElement`` is a module-private helper -- we use it here
        # because we already have the layout + a target surface; re-
        # computing the layout via ``renderPrimaryScreen`` would only draw
        # the basic-tier layout (wrong).
        primary_renderer._drawElement(element, surface)
    return surface


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=sorted(_SCENARIOS.keys()),
        default="normal",
        help="which sample screen to render",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="PNG output path",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="render every scenario into the parent dir of --out",
    )
    args = parser.parse_args()

    pygame.init()
    try:
        if args.all:
            outDir = args.out.parent
            outDir.mkdir(parents=True, exist_ok=True)
            for scenario in sorted(_SCENARIOS.keys()):
                surface = _renderSurfaceForScenario(scenario)
                path = outDir / f"advanced_tier_{scenario}.png"
                pygame.image.save(surface, str(path))
                print(f"wrote {path}")
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            surface = _renderSurfaceForScenario(args.scenario)
            pygame.image.save(surface, str(args.out))
            print(f"wrote {args.out}")
    finally:
        pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
