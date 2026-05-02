################################################################################
# File Name: dashboard_layout.py
# Purpose/Description: Canvas-aware 4-quadrant dashboard layout (US-257 / B-052)
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex          | US-257 initial: pure-geometry layout module
#               |              | (no pygame imports). Produces proportional
#               |              | quadrant rects + footer band + scaled font
#               |              | sizes for any canvas size. Backwards-compat
#               |              | with the legacy 480x320 case.
# ================================================================================
################################################################################

"""
Canvas-aware dashboard layout for the Eclipse OBD-II HDMI screen.

Per US-257 / B-052, the dashboard renders the same four state surfaces
regardless of canvas size. This module produces the geometry only -- pygame
rendering lives in ``status_display.py`` so this layer remains testable
without an SDL stack.

Quadrant assignments are fixed for muscle memory (per B-052 invariant):

    NW  engine telemetry      |  NE  power state + shutdown stage
    --------------------------+--------------------------
    SW  drive / OBD2 status   |  SE  alerts / issue counts

A footer band below the quadrants holds uptime + IP. Font sizes scale with
canvas height and clamp above a readable minimum at the legacy 480x320 size.

Usage:
    from pi.hardware.dashboard_layout import computeLayout, ShutdownStage
    layout = computeLayout(1920, 1080)
    rect = layout.engine        # Rect(x, y, width, height) for NW quadrant
    fontPx = layout.fonts.title # int pixels, scaled for canvas
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ================================================================================
# Color palette
# ================================================================================

COLOR_BLACK = (0, 0, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_GRAY = (128, 128, 128)
COLOR_BLUE = (0, 100, 255)
COLOR_GREEN = (0, 200, 0)
COLOR_AMBER = (255, 191, 0)
COLOR_ORANGE = (255, 140, 0)
COLOR_RED = (220, 0, 0)


# ================================================================================
# Shutdown stage ladder + color mapping
# ================================================================================


class ShutdownStage(Enum):
    """Mirrors the US-216 / Sprint 21 staged-shutdown ladder."""
    NORMAL = "normal"
    WARNING = "warning"
    IMMINENT = "imminent"
    TRIGGER = "trigger"


STAGE_COLORS: dict[ShutdownStage, tuple[int, int, int]] = {
    ShutdownStage.NORMAL: COLOR_GREEN,
    ShutdownStage.WARNING: COLOR_AMBER,
    ShutdownStage.IMMINENT: COLOR_ORANGE,
    ShutdownStage.TRIGGER: COLOR_RED,
}


# ================================================================================
# Geometry primitives
# ================================================================================


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in canvas pixel coordinates."""
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class FontScale:
    """Pixel font sizes for the four typographic tiers used on the dashboard."""
    title: int
    value: int
    label: int
    detail: int


@dataclass(frozen=True)
class DashboardLayout:
    """The full layout: four quadrants + footer + font sizing + padding."""
    canvasWidth: int
    canvasHeight: int
    engine: Rect
    power: Rect
    drive: Rect
    alerts: Rect
    footer: Rect
    fonts: FontScale
    padding: int


# ================================================================================
# Layout computation
# ================================================================================

# Reference design point: 1920x1080 produces these font sizes.
_REFERENCE_HEIGHT = 1080
_REFERENCE_FONTS = FontScale(title=72, value=64, label=48, detail=32)

# Floor below which fonts become unreadable on the legacy 480x320 screen.
_MIN_FONTS = FontScale(title=20, value=18, label=16, detail=14)


def computeLayout(canvasWidth: int, canvasHeight: int) -> DashboardLayout:
    """
    Build a 4-quadrant + footer layout for the given canvas size.

    Args:
        canvasWidth: Canvas width in pixels (must be > 0).
        canvasHeight: Canvas height in pixels (must be > 0).

    Returns:
        A frozen DashboardLayout with quadrant rects, footer rect, scaled
        font sizes, and proportional padding.

    Raises:
        ValueError: If either dimension is non-positive.
    """
    if canvasWidth <= 0 or canvasHeight <= 0:
        raise ValueError(
            f"Canvas dimensions must be positive; got {canvasWidth}x{canvasHeight}"
        )

    padding = max(4, min(canvasWidth, canvasHeight) // 60)
    footerHeight = max(20, canvasHeight // 12)
    bodyHeight = canvasHeight - footerHeight

    halfWidth = canvasWidth // 2
    halfBodyHeight = bodyHeight // 2

    engine = Rect(0, 0, halfWidth, halfBodyHeight)
    power = Rect(halfWidth, 0, canvasWidth - halfWidth, halfBodyHeight)
    drive = Rect(0, halfBodyHeight, halfWidth, bodyHeight - halfBodyHeight)
    alerts = Rect(
        halfWidth, halfBodyHeight,
        canvasWidth - halfWidth, bodyHeight - halfBodyHeight,
    )
    footer = Rect(0, bodyHeight, canvasWidth, footerHeight)

    scale = canvasHeight / _REFERENCE_HEIGHT
    fonts = FontScale(
        title=max(_MIN_FONTS.title, int(_REFERENCE_FONTS.title * scale)),
        value=max(_MIN_FONTS.value, int(_REFERENCE_FONTS.value * scale)),
        label=max(_MIN_FONTS.label, int(_REFERENCE_FONTS.label * scale)),
        detail=max(_MIN_FONTS.detail, int(_REFERENCE_FONTS.detail * scale)),
    )

    return DashboardLayout(
        canvasWidth=canvasWidth,
        canvasHeight=canvasHeight,
        engine=engine,
        power=power,
        drive=drive,
        alerts=alerts,
        footer=footer,
        fonts=fonts,
        padding=padding,
    )


__all__ = [
    "COLOR_AMBER",
    "COLOR_BLACK",
    "COLOR_BLUE",
    "COLOR_GRAY",
    "COLOR_GREEN",
    "COLOR_ORANGE",
    "COLOR_RED",
    "COLOR_WHITE",
    "STAGE_COLORS",
    "DashboardLayout",
    "FontScale",
    "Rect",
    "ShutdownStage",
    "computeLayout",
]
