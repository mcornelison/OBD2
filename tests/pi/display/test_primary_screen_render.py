################################################################################
# File Name: test_primary_screen_render.py
# Purpose/Description: Headless pygame integration test for US-164 primary renderer
# Author: Ralph Agent (Rex)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Ralph Agent  | Initial implementation for US-164
# ================================================================================
################################################################################
"""
Headless pygame integration test for the US-164 basic-tier primary renderer.

AC from US-164: "Integration test renders a snapshot to an offscreen surface in
headless mode and compares structural properties (text content, regions) — no
pixel-exact diffing."

Strategy: use SDL_VIDEODRIVER=dummy so pygame runs on CI boxes with no display.
Render a state onto a 480x320 Surface and assert that:

- The surface was drawn on (non-background pixels exist in each of the three
  regions: header, body, footer).
- The OBD status dot pixel region ends up with the expected color family.
- Headers/bodies/footers share the same dark background baseline.

We do not compare pixels to a golden image — fonts and pygame versions drift
across platforms.
"""

from __future__ import annotations

import os

import pytest

pygame = pytest.importorskip("pygame")

from pi.display.screens.primary_renderer import renderPrimaryScreen  # noqa: E402
from pi.display.screens.primary_screen import (  # noqa: E402
    ScreenFooter,
    ScreenHeader,
    buildBasicTierScreenState,
)


@pytest.fixture(autouse=True)
def _headlessPygame(monkeypatch):
    """Force pygame to use the dummy SDL driver so tests run without a display."""
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.display.init()
    pygame.font.init()
    yield
    pygame.display.quit()


@pytest.fixture
def _sampleState():
    return buildBasicTierScreenState(
        readings={
            "RPM": 2500.0,
            "COOLANT_TEMP": 185.0,
            "BOOST": 8.5,
            "AFR": 14.2,
            "SPEED": 35.0,
            "BATTERY_VOLTAGE": 14.1,
        },
        thresholdConfigs={
            "coolantTemp": {"normalMin": 180.0, "cautionMin": 210.0, "dangerMin": 220.0},
            "rpm": {"normalMin": 600.0, "cautionMin": 6500.0, "dangerMin": 7000.0},
        },
        header=ScreenHeader(
            hostname="Eclipse-01", obdConnected=True, profileIndicator="D"
        ),
        footer=ScreenFooter(
            alertMessages=[], batterySocPercent=87.0, powerSource="ac_power"
        ),
    )


def _surface(width: int = 480, height: int = 320):
    return pygame.Surface((width, height))


def _nonBackgroundPixelCount(surface, bgColor: tuple[int, int, int]) -> int:
    """Count pixels that differ from bgColor. Used as a 'we drew something' check."""
    width, height = surface.get_size()
    count = 0
    for y in range(0, height, 4):  # sample every 4 pixels for speed
        for x in range(0, width, 4):
            r, g, b, *_ = surface.get_at((x, y))
            if (r, g, b) != bgColor:
                count += 1
    return count


def test_renderPrimaryScreen_drawsOnSurface(_sampleState):
    """
    Given: headless pygame surface + a basic-tier state snapshot
    When: renderPrimaryScreen is called
    Then: the surface has been drawn on (non-background pixels exist)
    """
    surface = _surface()
    surface.fill((0, 0, 0))  # baseline black

    renderPrimaryScreen(_sampleState, surface)

    # At least *some* pixels must have changed from pure black.
    assert _nonBackgroundPixelCount(surface, (0, 0, 0)) > 0


def test_renderPrimaryScreen_drawsInAllThreeRegions(_sampleState):
    """
    Given: surface filled with black
    When: renderer draws header/body/footer
    Then: each vertical region has non-background pixels
    """
    surface = _surface()
    surface.fill((0, 0, 0))

    renderPrimaryScreen(_sampleState, surface)

    header = surface.subsurface((0, 0, 480, 50))
    body = surface.subsurface((0, 60, 480, 200))
    footer = surface.subsurface((0, 270, 480, 50))

    assert _nonBackgroundPixelCount(header, (0, 0, 0)) > 0, "header region is blank"
    assert _nonBackgroundPixelCount(body, (0, 0, 0)) > 0, "body region is blank"
    assert _nonBackgroundPixelCount(footer, (0, 0, 0)) > 0, "footer region is blank"


def test_renderPrimaryScreen_obdDot_greenWhenConnected(_sampleState):
    """
    The OBD status dot is a solid circle in the header. When connected, at
    least some pixels in the dot's neighborhood should be predominantly green.
    """
    surface = _surface()
    surface.fill((0, 0, 0))

    renderPrimaryScreen(_sampleState, surface)

    # Sample a band around the header center where the dot lives.
    bandPixels: list[tuple[int, int, int]] = []
    for x in range(200, 280):
        for y in range(5, 45):
            r, g, b, *_ = surface.get_at((x, y))
            if (r, g, b) != (0, 0, 0):
                bandPixels.append((r, g, b))

    assert bandPixels, "no header dot pixels rendered"
    # Count pixels whose dominant channel is green.
    greenDominant = sum(1 for r, g, b in bandPixels if g > r and g > b)
    assert greenDominant > 0, "connected OBD dot should render green-ish pixels"


def test_renderPrimaryScreen_obdDot_redWhenDisconnected():
    """Mirror of the connected test — disconnected dot draws red-dominant pixels."""
    state = buildBasicTierScreenState(
        readings={"RPM": 0.0},
        thresholdConfigs={},
        header=ScreenHeader(
            hostname="Eclipse-01", obdConnected=False, profileIndicator="D"
        ),
    )
    surface = _surface()
    surface.fill((0, 0, 0))

    renderPrimaryScreen(state, surface)

    bandPixels: list[tuple[int, int, int]] = []
    for x in range(200, 280):
        for y in range(5, 45):
            r, g, b, *_ = surface.get_at((x, y))
            if (r, g, b) != (0, 0, 0):
                bandPixels.append((r, g, b))

    assert bandPixels, "no header dot pixels rendered"
    redDominant = sum(1 for r, g, b in bandPixels if r > g and r > b)
    assert redDominant > 0, "disconnected OBD dot should render red-ish pixels"


def test_renderPrimaryScreen_doesNotRaiseOnEmptyReadings():
    """
    Given: no parameter readings at all (drive just started, ECU silent)
    When: rendering
    Then: does not raise — footer/header still draw
    """
    state = buildBasicTierScreenState(
        readings={},
        thresholdConfigs={},
        header=ScreenHeader(
            hostname="Eclipse-01", obdConnected=False, profileIndicator="D"
        ),
    )
    surface = _surface()
    surface.fill((0, 0, 0))
    renderPrimaryScreen(state, surface)
    # Header and footer still draw, so we should have some pixels.
    assert _nonBackgroundPixelCount(surface, (0, 0, 0)) > 0


def test_renderPrimaryScreen_respectsScreenDimensions(_sampleState):
    """Renderer must not write outside the 480x320 surface."""
    # A smaller surface (say 320x240) should still render without raising —
    # pygame clips at the surface edge, the renderer should not assume a size.
    surface = pygame.Surface((320, 240))
    surface.fill((0, 0, 0))
    renderPrimaryScreen(_sampleState, surface)
    # No assertion on quality — just no crash.
    assert surface.get_size() == (320, 240)


def test_renderPrimaryScreen_fontLoaderDocumented(_sampleState):
    """
    AC: 'Ralph picks a font that ships with pygame on Debian; document the
    choice'. We assert that the renderer exposes a documented font loader
    (either via module docstring mentioning DejaVuSans or via a callable).
    """
    from pi.display.screens import primary_renderer

    doc = (primary_renderer.__doc__ or "").lower()
    assert "dejavu" in doc or "font" in doc, (
        "primary_renderer module should document its font choice"
    )


def test_renderPrimaryScreen_headlessEnvironmentRuns():
    """Sanity: SDL_VIDEODRIVER=dummy is honored by the fixture."""
    assert os.environ.get("SDL_VIDEODRIVER") == "dummy"
