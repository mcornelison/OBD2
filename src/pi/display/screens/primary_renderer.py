################################################################################
# File Name: primary_renderer.py
# Purpose/Description: Pygame renderer for the US-164 basic-tier primary screen
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
Pygame renderer for the basic-tier primary screen (Sprint 10 Pi Crawl / US-164).

The pure-data layout list comes from ``primary_screen.computeBasicTierLayout``;
this module walks it and draws each ``LayoutElement`` onto a pygame Surface.

Font choice
-----------
We use DejaVuSans — it ships preinstalled on Debian/Raspbian at
``/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`` (via the ``fonts-dejavu``
package that the OSOYOO-style Debian images bundle), and pygame also resolves
it via ``pygame.font.SysFont("dejavusans", size)`` on Windows/Linux. We fall
back to ``pygame.font.Font(None, size)`` (pygame's built-in bitmap font) when
DejaVu is not available — this keeps unit tests running on bare CI boxes.

See offices/ralph/agent.md §Pygame Display for the cross-platform pygame
availability pattern used here.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import pygame
    PYGAME_AVAILABLE = True
except (ImportError, RuntimeError):
    pygame = None  # type: ignore
    PYGAME_AVAILABLE = False

from .primary_screen import BasicTierScreenState, LayoutElement, computeBasicTierLayout

logger = logging.getLogger(__name__)


# ================================================================================
# Constants
# ================================================================================


DEFAULT_BACKGROUND: tuple[int, int, int] = (0, 0, 0)

FONT_SIZES: dict[str, int] = {
    "small": 16,
    "normal": 22,
    "medium": 28,
    "large": 42,
    "xlarge": 56,
}

_COLOR_MAP: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "black": (0, 0, 0),
    "gray": (128, 128, 128),
    "red": (220, 30, 30),
    "green": (30, 200, 30),
    "yellow": (230, 210, 30),
    "orange": (255, 165, 0),
    "blue": (60, 120, 255),
}

_DEJAVU_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


# ================================================================================
# Font loading
# ================================================================================


def _loadFont(size: int) -> Any:
    """Load a DejaVuSans font at ``size``, falling back to pygame default.

    Order: direct Debian path -> SysFont("dejavusans") -> Font(None).
    """
    if not PYGAME_AVAILABLE:
        raise RuntimeError("pygame unavailable — renderer cannot load fonts")

    for path in _DEJAVU_PATHS:
        try:
            return pygame.font.Font(path, size)
        except (FileNotFoundError, OSError):
            continue

    try:
        font = pygame.font.SysFont("dejavusans", size)
        if font is not None:
            return font
    except Exception:
        pass

    return pygame.font.Font(None, size)


def _color(name: str) -> tuple[int, int, int]:
    """Map a color name to an RGB tuple; defaults to white on unknown names."""
    return _COLOR_MAP.get(name, _COLOR_MAP["white"])


# ================================================================================
# Renderer
# ================================================================================


def renderPrimaryScreen(
    state: BasicTierScreenState,
    surface: Any,
    background: tuple[int, int, int] = DEFAULT_BACKGROUND,
) -> None:
    """Render the basic-tier primary screen onto a pygame Surface.

    Computes the layout plan, clears the surface to the background color, and
    draws each LayoutElement. Safe to call repeatedly in a refresh loop.

    Args:
        state: Basic-tier screen state from ``buildBasicTierScreenState``.
        surface: Pygame Surface to draw on. Use
            ``pygame.display.set_mode((480, 320))`` on the Pi or an offscreen
            ``pygame.Surface`` in tests.
        background: RGB background color; defaults to black.

    Raises:
        RuntimeError: If pygame is not available.
    """
    if not PYGAME_AVAILABLE:
        raise RuntimeError(
            "pygame is required for rendering but is not importable"
        )

    width, height = surface.get_size()
    surface.fill(background)

    layout = computeBasicTierLayout(state, width=width, height=height)
    for element in layout:
        _drawElement(element, surface)


def _drawElement(element: LayoutElement, surface: Any) -> None:
    """Dispatch a single LayoutElement to the right pygame primitive."""
    if element.kind == "text":
        _drawText(element, surface)
    elif element.kind == "circle":
        _drawCircle(element, surface)
    elif element.kind == "rect":
        _drawRect(element, surface)
    else:
        logger.debug("Unknown LayoutElement kind: %s", element.kind)


def _drawText(element: LayoutElement, surface: Any) -> None:
    size = FONT_SIZES.get(element.fontSize, FONT_SIZES["normal"])
    font = _loadFont(size)
    textSurface = font.render(element.text, True, _color(element.color))
    surface.blit(textSurface, (element.x, element.y))


def _drawCircle(element: LayoutElement, surface: Any) -> None:
    radius = element.radius if element.radius > 0 else 8
    pygame.draw.circle(
        surface, _color(element.color), (element.x, element.y), radius
    )


def _drawRect(element: LayoutElement, surface: Any) -> None:
    width = element.width if element.width > 0 else 1
    height = element.height if element.height > 0 else 1
    pygame.draw.rect(
        surface,
        _color(element.color),
        (element.x, element.y, width, height),
    )


__all__ = [
    "DEFAULT_BACKGROUND",
    "FONT_SIZES",
    "PYGAME_AVAILABLE",
    "renderPrimaryScreen",
]
