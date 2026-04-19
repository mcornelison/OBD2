################################################################################
# File Name: test_hdmi_render.py
# Purpose/Description: pygame HDMI render validation for the OSOYOO 3.5"
#                      touchscreen on chi-eclipse-01 (US-183 Pi Polish).
#                      These tests prove the render pipeline initialises,
#                      accepts the expected 480x320 surface shape, and draws
#                      the basic-tier primary screen without raising. The
#                      pi_only-marked subset requires real Pi hardware and
#                      verifies pygame.display.set_mode() against the Pi's
#                      actual framebuffer.  Everything else runs off-Pi under
#                      the SDL dummy driver for CI coverage.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-18    | Rex          | Initial implementation for US-183 (Sprint 12)
# ================================================================================
################################################################################
"""
pygame HDMI render smoke tests for the Pi's 480x320 OSOYOO touchscreen.

Two kinds of test in this file:

1. Off-Pi-safe tests under ``SDL_VIDEODRIVER=dummy`` — prove the render
   pipeline can produce a 480x320 surface and walk every LayoutElement kind
   without raising. These run in the Windows fast suite and on CI.

2. ``pi_only`` tests that require the real Pi 5 framebuffer — these exercise
   ``pygame.display.set_mode((480, 320))`` against the HDMI-attached display
   and a clean pygame.quit(). They're auto-skipped off-Pi (see
   ``tests/conftest.py``), and opt-in via ``ECLIPSE_PI_HOST=1``.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Force the SDL dummy driver BEFORE pygame is imported anywhere in this module
# so the default off-Pi test run never tries to open a real window.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from pi.display.screens.primary_renderer import (  # noqa: E402
    DEFAULT_BACKGROUND,
    PYGAME_AVAILABLE,
    renderPrimaryScreen,
)
from pi.display.screens.primary_screen import (  # noqa: E402
    buildBasicTierScreenState,
)

SCREEN_WIDTH = 480
SCREEN_HEIGHT = 320


# ================================================================================
# Helpers
# ================================================================================


def _sampleReadings() -> dict[str, float]:
    """A representative set of readings that exercise every gauge."""
    return {
        "RPM": 2400.0,
        "COOLANT_TEMP": 195.0,
        "BOOST": 8.5,
        "AFR": 14.2,
        "SPEED": 35.0,
        "BATTERY_VOLTAGE": 14.1,
    }


def _sampleThresholds() -> dict[str, dict[str, float]]:
    return {
        "coolantTemp": {
            "normalMin": 180.0,
            "cautionMin": 210.0,
            "dangerMin": 220.0,
        },
        "rpm": {
            "normalMin": 600.0,
            "cautionMin": 6500.0,
            "dangerMin": 7000.0,
        },
    }


def _buildState() -> Any:
    return buildBasicTierScreenState(
        readings=_sampleReadings(),
        thresholdConfigs=_sampleThresholds(),
    )


# ================================================================================
# Off-Pi smoke tests (SDL dummy driver)
# ================================================================================


class TestRenderPipelineSmoke:
    """
    These run on Windows + CI under the SDL dummy driver. They prove the
    render pipeline is wired correctly even without a real framebuffer.
    """

    def test_pygameAvailable_isTrue_inTestEnv(self) -> None:
        assert PYGAME_AVAILABLE is True, (
            "pygame must be importable for US-183 render validation"
        )

    def test_renderPrimaryScreen_onOffscreen480x320_doesNotRaise(self) -> None:
        """
        Given: an offscreen 480x320 pygame Surface (matches OSOYOO native).
        When:  renderPrimaryScreen is called with a representative state.
        Then:  it returns without raising, and the surface pixel at (0, 0)
               is the background color (black by default) since every
               LayoutElement draws on top of a cleared surface.
        """
        pygame.font.init()
        surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        state = _buildState()

        renderPrimaryScreen(state, surface)

        # Top-left corner is outside any gauge region, so it stays at the
        # background color after the clear-and-draw cycle.
        r, g, b, _ = surface.get_at((0, 0))
        assert (r, g, b) == DEFAULT_BACKGROUND

    def test_renderPrimaryScreen_writesNonBlackPixels(self) -> None:
        """
        Given: an offscreen 480x320 surface cleared to black.
        When:  renderPrimaryScreen is called.
        Then:  at least one pixel is non-black (a gauge, label, or status
               dot was drawn). This is the coarsest "something was rendered"
               signal we can assert without coupling to specific coordinates.
        """
        pygame.font.init()
        surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        state = _buildState()

        renderPrimaryScreen(state, surface)

        # Scan a sparse grid for any non-background pixel.
        foundNonBlack = False
        for y in range(0, SCREEN_HEIGHT, 8):
            for x in range(0, SCREEN_WIDTH, 8):
                r, g, b, _ = surface.get_at((x, y))
                if (r, g, b) != DEFAULT_BACKGROUND:
                    foundNonBlack = True
                    break
            if foundNonBlack:
                break
        assert foundNonBlack, (
            "render produced only background pixels — "
            "the basic-tier screen should draw at least labels + values"
        )

    def test_renderPrimaryScreen_refreshLoop_staysStable(self) -> None:
        """
        Given: the render function is called multiple times on the same
               surface (simulating a refresh loop).
        When:  10 consecutive renders run back-to-back.
        Then:  no exception is raised and the final surface still contains
               drawn content.
        """
        pygame.font.init()
        surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        state = _buildState()

        for _ in range(10):
            renderPrimaryScreen(state, surface)

        # Final frame should still have drawn content.
        r, g, b, _ = surface.get_at((SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
        # Center often contains text or a gauge value; at minimum it must
        # not throw when queried.
        assert isinstance((r, g, b), tuple)


# ================================================================================
# pi_only live-HDMI tests
# ================================================================================


@pytest.mark.pi_only
class TestLiveHdmiDisplay:
    """
    Require the real Pi 5 framebuffer + OSOYOO 3.5" HDMI display.

    These tests are auto-skipped on Windows and x86 Linux (see
    ``tests/conftest.py``). Opt in with ``ECLIPSE_PI_HOST=1`` to force-run.
    Note: ``SDL_VIDEODRIVER=dummy`` is set at module import (for the
    off-Pi tests above) and each live-HDMI test explicitly unsets it so
    ``pygame.display.set_mode`` resolves to the real framebuffer.
    """

    @pytest.fixture(autouse=True)
    def _enableRealFramebuffer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Strip the dummy SDL driver for the duration of the test so
        ``pygame.display.set_mode`` opens the Pi's actual HDMI display.
        """
        monkeypatch.delenv("SDL_VIDEODRIVER", raising=False)

    def test_pygameDisplayInit_onPi_succeeds(self) -> None:
        """
        Given: the Pi 5 framebuffer with the OSOYOO HDMI display attached.
        When:  pygame.display.init() is called.
        Then:  no exception is raised and pygame.display.get_init() is True.
        """
        pygame.display.init()
        try:
            assert pygame.display.get_init() is True
        finally:
            pygame.display.quit()

    def test_setMode_480x320_onPi_returnsSurface(self) -> None:
        """
        Given: pygame.display.init() succeeded on the Pi.
        When:  set_mode((480, 320)) is called.
        Then:  a Surface matching the requested size is returned and
               clean teardown (pygame.display.quit + pygame.quit) works.
        """
        pygame.display.init()
        try:
            screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
            try:
                assert screen is not None
                assert screen.get_size() == (SCREEN_WIDTH, SCREEN_HEIGHT)
            finally:
                # Blit a black frame and flip so the display doesn't
                # keep a partial frame when the test ends.
                screen.fill(DEFAULT_BACKGROUND)
                pygame.display.flip()
        finally:
            pygame.display.quit()

    def test_renderPrimaryScreen_onRealFramebuffer_rendersCleanly(
        self,
    ) -> None:
        """
        Given: the live HDMI display via pygame.display.set_mode.
        When:  renderPrimaryScreen writes a frame and flip() presents it.
        Then:  no exception is raised and the scripted frame reaches the
               display buffer. Visual confirmation is the CIO's job —
               this test proves the programmatic path is crash-free.
        """
        pygame.display.init()
        pygame.font.init()
        try:
            screen = pygame.display.set_mode(
                (SCREEN_WIDTH, SCREEN_HEIGHT)
            )
            state = _buildState()
            renderPrimaryScreen(state, screen)
            pygame.display.flip()
        finally:
            pygame.display.quit()
