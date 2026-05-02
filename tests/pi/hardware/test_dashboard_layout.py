################################################################################
# File Name: test_dashboard_layout.py
# Purpose/Description: Tests for canvas-aware dashboard layout (US-257 / B-052)
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Rex          | US-257 initial: 4-quadrant proportional layout
#               |              | + ShutdownStage colors + font scaling. Asserts
#               |              | quadrant geometry at 1920x1080 / 1280x720 /
#               |              | 480x320 (legacy) and font scaling clamps to a
#               |              | minimum size for readable dev/test screens.
# ================================================================================
################################################################################

"""
Tests for the canvas-aware dashboard layout module.

US-257 / B-052 brief:
    The current dashboard renders a vertical strip sized for the legacy
    480x320 OSOYOO touchscreen, which on the Eclipse's HDMI screen occupies a
    small fraction of the available canvas. This module produces a
    proportional 4-quadrant layout (engine NW / power NE / drive SW / alerts
    SE) plus a footer band, with font sizes scaled to the canvas height. The
    480x320 case must still render without regression for dev/testing.

Test scope:
    Pure geometry + enum/color contract. No pygame, no rendering. Exercising
    the rendering path lives in tests/pi/hardware/test_status_display.py
    parameterized over canvas sizes.
"""

from __future__ import annotations

import pytest

from pi.hardware.dashboard_layout import (
    COLOR_AMBER,
    COLOR_GREEN,
    COLOR_ORANGE,
    COLOR_RED,
    STAGE_COLORS,
    DashboardLayout,
    FontScale,
    Rect,
    ShutdownStage,
    computeLayout,
)

# ================================================================================
# Quadrant geometry -- proportional, never zero-dim, NW/NE/SW/SE invariant
# ================================================================================


class TestQuadrantGeometry:
    """Each quadrant occupies its expected canvas region for any canvas size."""

    @pytest.mark.parametrize(
        "canvasWidth,canvasHeight",
        [
            (1920, 1080),
            (1280, 720),
            (480, 320),
        ],
    )
    def test_computeLayout_quadrantsTileTheCanvasBody(
        self, canvasWidth: int, canvasHeight: int
    ):
        """
        Given: any supported canvas size
        When:  computeLayout produces quadrant + footer rects
        Then:  the four quadrants tile the canvas-minus-footer with no gaps
               and no overlaps, and the footer occupies the bottom band.
        """
        layout = computeLayout(canvasWidth, canvasHeight)

        # NW + NE share the top half; SW + SE share the bottom half;
        # footer is the strip below all quadrants.
        assert layout.engine.x == 0
        assert layout.engine.y == 0
        assert layout.power.x == layout.engine.x + layout.engine.width
        assert layout.power.y == 0
        assert layout.drive.x == 0
        assert layout.drive.y == layout.engine.height
        assert layout.alerts.x == layout.power.x
        assert layout.alerts.y == layout.power.height
        assert layout.footer.x == 0
        assert layout.footer.y == layout.drive.y + layout.drive.height

        # No coverage gaps: full canvas width across each row, full height with footer.
        assert layout.engine.width + layout.power.width == canvasWidth
        assert layout.drive.width + layout.alerts.width == canvasWidth
        bodyHeight = layout.engine.height + layout.drive.height
        assert bodyHeight + layout.footer.height == canvasHeight

    @pytest.mark.parametrize(
        "canvasWidth,canvasHeight",
        [
            (1920, 1080),
            (1280, 720),
            (480, 320),
        ],
    )
    def test_computeLayout_noQuadrantIsZeroDim(
        self, canvasWidth: int, canvasHeight: int
    ):
        """Each rect has positive width/height -- text actually fits."""
        layout = computeLayout(canvasWidth, canvasHeight)
        for name, rect in [
            ("engine", layout.engine),
            ("power", layout.power),
            ("drive", layout.drive),
            ("alerts", layout.alerts),
            ("footer", layout.footer),
        ]:
            assert rect.width > 0, f"{name} width must be positive"
            assert rect.height > 0, f"{name} height must be positive"

    def test_computeLayout_largeCanvasHasLargerRects(self):
        """1920x1080 layout has strictly larger quadrants than 480x320."""
        big = computeLayout(1920, 1080)
        small = computeLayout(480, 320)
        assert big.engine.width > small.engine.width
        assert big.engine.height > small.engine.height
        assert big.power.width > small.power.width
        assert big.alerts.height > small.alerts.height


# ================================================================================
# Font scaling -- proportional to canvas height, clamped to a minimum
# ================================================================================


class TestFontScaling:
    """Fonts scale with canvas height so text is legible at any size."""

    def test_computeLayout_largerCanvasHasLargerFonts(self):
        """1920x1080 fonts are strictly larger than 480x320 fonts."""
        big = computeLayout(1920, 1080)
        small = computeLayout(480, 320)
        assert big.fonts.title > small.fonts.title
        assert big.fonts.value > small.fonts.value
        assert big.fonts.label > small.fonts.label
        assert big.fonts.detail > small.fonts.detail

    def test_computeLayout_smallCanvasFontsAboveMinimum(self):
        """At 480x320, fonts are clamped above a readable minimum (>= 14px)."""
        layout = computeLayout(480, 320)
        assert layout.fonts.title >= 18
        assert layout.fonts.value >= 16
        assert layout.fonts.label >= 14
        assert layout.fonts.detail >= 12

    def test_computeLayout_orderedHierarchy(self):
        """title >= value >= label >= detail across canvas sizes."""
        for canvasWidth, canvasHeight in [(1920, 1080), (1280, 720), (480, 320)]:
            layout = computeLayout(canvasWidth, canvasHeight)
            assert layout.fonts.title >= layout.fonts.value
            assert layout.fonts.value >= layout.fonts.label
            assert layout.fonts.label >= layout.fonts.detail

    def test_computeLayout_textFitsInPowerQuadrant(self):
        """Power quadrant width exceeds title+padding so a stage label fits."""
        for canvasWidth, canvasHeight in [(1920, 1080), (1280, 720), (480, 320)]:
            layout = computeLayout(canvasWidth, canvasHeight)
            estimatedTextWidth = layout.fonts.title * 4
            assert layout.power.width >= estimatedTextWidth + 2 * layout.padding


# ================================================================================
# Padding -- positive, scales with canvas size
# ================================================================================


class TestPaddingScaling:
    """Padding scales with min(canvas_width, canvas_height) and is always positive."""

    def test_computeLayout_paddingPositive(self):
        for canvasWidth, canvasHeight in [(1920, 1080), (1280, 720), (480, 320)]:
            layout = computeLayout(canvasWidth, canvasHeight)
            assert layout.padding > 0

    def test_computeLayout_largerCanvasHasLargerPadding(self):
        big = computeLayout(1920, 1080)
        small = computeLayout(480, 320)
        assert big.padding >= small.padding


# ================================================================================
# Input validation
# ================================================================================


class TestInputValidation:
    """Invalid canvas sizes raise ValueError early."""

    def test_computeLayout_zeroWidth_raisesValueError(self):
        with pytest.raises(ValueError):
            computeLayout(0, 1080)

    def test_computeLayout_zeroHeight_raisesValueError(self):
        with pytest.raises(ValueError):
            computeLayout(1920, 0)

    def test_computeLayout_negativeWidth_raisesValueError(self):
        with pytest.raises(ValueError):
            computeLayout(-1, 1080)

    def test_computeLayout_negativeHeight_raisesValueError(self):
        with pytest.raises(ValueError):
            computeLayout(1920, -1)


# ================================================================================
# ShutdownStage enum + color palette
# ================================================================================


class TestShutdownStageContract:
    """ShutdownStage covers the staged-shutdown ladder + matches the color palette."""

    def test_shutdownStage_hasFourStages(self):
        """NORMAL / WARNING / IMMINENT / TRIGGER -- one per ladder rung."""
        members = {member.name for member in ShutdownStage}
        assert members == {"NORMAL", "WARNING", "IMMINENT", "TRIGGER"}

    def test_stageColors_normalIsGreen(self):
        assert STAGE_COLORS[ShutdownStage.NORMAL] == COLOR_GREEN

    def test_stageColors_warningIsAmber(self):
        assert STAGE_COLORS[ShutdownStage.WARNING] == COLOR_AMBER

    def test_stageColors_imminentIsOrange(self):
        assert STAGE_COLORS[ShutdownStage.IMMINENT] == COLOR_ORANGE

    def test_stageColors_triggerIsRed(self):
        assert STAGE_COLORS[ShutdownStage.TRIGGER] == COLOR_RED

    def test_stageColors_eachIsRgbTuple(self):
        for stage, color in STAGE_COLORS.items():
            assert isinstance(color, tuple), f"{stage} color must be tuple"
            assert len(color) == 3, f"{stage} color must be RGB triple"
            for channel in color:
                assert 0 <= channel <= 255, f"{stage} channel out of range"

    def test_stageColors_distinctPerStage(self):
        """Each stage has a distinct color so the operator can tell them apart."""
        colors = list(STAGE_COLORS.values())
        assert len(set(colors)) == len(colors)


# ================================================================================
# Dataclass shapes -- guard against accidental field renames
# ================================================================================


class TestDataclassContract:
    """DashboardLayout / Rect / FontScale field names are part of the public contract."""

    def test_rect_hasXyWidthHeightFields(self):
        rect = Rect(x=1, y=2, width=3, height=4)
        assert rect.x == 1
        assert rect.y == 2
        assert rect.width == 3
        assert rect.height == 4

    def test_fontScale_hasFourTiers(self):
        fonts = FontScale(title=72, value=64, label=48, detail=32)
        assert fonts.title == 72
        assert fonts.value == 64
        assert fonts.label == 48
        assert fonts.detail == 32

    def test_dashboardLayout_exposesQuadrantsFontsPadding(self):
        layout = computeLayout(1920, 1080)
        assert isinstance(layout, DashboardLayout)
        assert isinstance(layout.engine, Rect)
        assert isinstance(layout.power, Rect)
        assert isinstance(layout.drive, Rect)
        assert isinstance(layout.alerts, Rect)
        assert isinstance(layout.footer, Rect)
        assert isinstance(layout.fonts, FontScale)
        assert isinstance(layout.padding, int)
        assert layout.canvasWidth == 1920
        assert layout.canvasHeight == 1080
