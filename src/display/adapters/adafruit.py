################################################################################
# File Name: adafruit.py
# Purpose/Description: Adafruit ST7789 1.3" 240x240 TFT display adapter
# Author: Michael Cornelison
# Creation Date: 2026-01-22
# Copyright: (c) 2026 Eclipse OBD-II. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-01-22    | M. Cornelison | Initial implementation for US-008
# 2026-01-22    | Ralph Agent  | US-006: Moved to display/adapters subpackage
# ================================================================================
################################################################################

"""
Adafruit ST7789 1.3" 240x240 TFT display adapter.

This module provides a hardware adapter for the Adafruit 1.3" 240x240 Color IPS
TFT Display with ST7789 controller. It uses Adafruit's CircuitPython libraries
for SPI communication.

Hardware Requirements:
    - Raspberry Pi with SPI enabled
    - Adafruit 1.3" 240x240 Wide Angle TFT LCD Display with MicroSD - ST7789
    - Product ID: 4313

Wiring (default):
    - VCC -> 3.3V
    - GND -> GND
    - SCK -> GPIO 11 (SPI0 SCLK)
    - MOSI -> GPIO 10 (SPI0 MOSI)
    - CS -> GPIO 8 (SPI0 CE0)
    - DC -> GPIO 25
    - RST -> GPIO 24
    - BL -> GPIO 18 (PWM for backlight)

Usage:
    from display.adapters import AdafruitDisplayAdapter, isDisplayHardwareAvailable

    if isDisplayHardwareAvailable():
        adapter = AdafruitDisplayAdapter()
        adapter.initialize()
        adapter.drawText(10, 10, "Hello World")
        adapter.refresh()
        adapter.shutdown()
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import Adafruit libraries
# Note: On non-Raspberry Pi platforms, board may raise NotImplementedError
try:
    import board
    import digitalio
    from adafruit_rgb_display import st7789
    from PIL import Image, ImageDraw, ImageFont
    ADAFRUIT_AVAILABLE = True
except (ImportError, NotImplementedError, RuntimeError) as e:
    logger.debug(f"Adafruit display libraries not available: {e}")
    ADAFRUIT_AVAILABLE = False
    # Placeholders for type hints
    board = None  # type: ignore
    digitalio = None  # type: ignore
    st7789 = None  # type: ignore
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore


# Display constants
DISPLAY_WIDTH = 240
DISPLAY_HEIGHT = 240


# Color definitions (RGB tuples)
@dataclass
class Colors:
    """Color constants for display."""

    WHITE: Tuple[int, int, int] = (255, 255, 255)
    BLACK: Tuple[int, int, int] = (0, 0, 0)
    RED: Tuple[int, int, int] = (255, 0, 0)
    GREEN: Tuple[int, int, int] = (0, 255, 0)
    BLUE: Tuple[int, int, int] = (0, 0, 255)
    YELLOW: Tuple[int, int, int] = (255, 255, 0)
    ORANGE: Tuple[int, int, int] = (255, 165, 0)
    CYAN: Tuple[int, int, int] = (0, 255, 255)
    MAGENTA: Tuple[int, int, int] = (255, 0, 255)
    GRAY: Tuple[int, int, int] = (128, 128, 128)
    DARK_GRAY: Tuple[int, int, int] = (64, 64, 64)
    LIGHT_GRAY: Tuple[int, int, int] = (192, 192, 192)

    @classmethod
    def fromName(cls, name: str) -> Tuple[int, int, int]:
        """
        Get RGB color tuple from color name.

        Args:
            name: Color name (case-insensitive)

        Returns:
            RGB tuple
        """
        colorMap = {
            'white': cls.WHITE,
            'black': cls.BLACK,
            'red': cls.RED,
            'green': cls.GREEN,
            'blue': cls.BLUE,
            'yellow': cls.YELLOW,
            'orange': cls.ORANGE,
            'cyan': cls.CYAN,
            'magenta': cls.MAGENTA,
            'gray': cls.GRAY,
            'grey': cls.GRAY,
            'dark_gray': cls.DARK_GRAY,
            'light_gray': cls.LIGHT_GRAY,
        }
        return colorMap.get(name.lower(), cls.WHITE)


class DisplayAdapterError(Exception):
    """Base exception for display adapter errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.details = details or {}


class DisplayInitializationError(DisplayAdapterError):
    """Raised when display initialization fails."""
    pass


class DisplayRenderError(DisplayAdapterError):
    """Raised when display rendering fails."""
    pass


class AdafruitDisplayAdapter:
    """
    Hardware adapter for Adafruit ST7789 1.3" 240x240 TFT display.

    This adapter provides a simple interface for drawing to the display
    using Adafruit's CircuitPython libraries and PIL for image manipulation.

    The adapter uses double-buffering: all draw operations write to an
    off-screen image buffer, then refresh() blits the buffer to the display.

    Example:
        adapter = AdafruitDisplayAdapter()
        adapter.initialize()
        adapter.clear()
        adapter.drawText(10, 10, "Status: OK", color='green')
        adapter.drawLine(0, 50, 240, 50, color='gray')
        adapter.refresh()
    """

    # Default GPIO pins for Adafruit 1.3" display
    DEFAULT_CS_PIN = 8  # SPI CE0
    DEFAULT_DC_PIN = 25
    DEFAULT_RST_PIN = 24
    DEFAULT_BL_PIN = 18  # Backlight (PWM capable)

    # Font sizes
    FONT_SIZES = {
        'small': 12,
        'normal': 16,
        'medium': 20,
        'large': 28,
        'xlarge': 36,
    }

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        csPin: Optional[int] = None,
        dcPin: Optional[int] = None,
        rstPin: Optional[int] = None,
        blPin: Optional[int] = None,
        rotation: int = 180,
        brightness: int = 100
    ):
        """
        Initialize the Adafruit display adapter.

        Args:
            config: Optional configuration dictionary
            csPin: Chip select GPIO pin (default: 8)
            dcPin: Data/command GPIO pin (default: 25)
            rstPin: Reset GPIO pin (default: 24)
            blPin: Backlight GPIO pin (default: 18)
            rotation: Display rotation in degrees (0, 90, 180, 270)
            brightness: Backlight brightness 0-100 (default: 100)
        """
        self._config = config or {}
        self._csPin = csPin or self._config.get('csPin', self.DEFAULT_CS_PIN)
        self._dcPin = dcPin or self._config.get('dcPin', self.DEFAULT_DC_PIN)
        self._rstPin = rstPin or self._config.get('rstPin', self.DEFAULT_RST_PIN)
        self._blPin = blPin or self._config.get('blPin', self.DEFAULT_BL_PIN)
        self._rotation = rotation
        self._brightness = brightness

        self._display: Any = None
        self._image: Any = None
        self._draw: Any = None
        self._initialized = False
        self._backlightPin: Any = None
        self._fonts: Dict[str, Any] = {}

    @property
    def width(self) -> int:
        """Get display width."""
        return DISPLAY_WIDTH

    @property
    def height(self) -> int:
        """Get display height."""
        return DISPLAY_HEIGHT

    @property
    def isInitialized(self) -> bool:
        """Check if display is initialized."""
        return self._initialized

    def initialize(self) -> bool:
        """
        Initialize the display hardware.

        Creates SPI connection, initializes the ST7789 display driver,
        sets up the image buffer for double-buffering, and configures
        the backlight.

        Returns:
            True if initialization successful, False otherwise

        Raises:
            DisplayInitializationError: If hardware initialization fails
        """
        if not ADAFRUIT_AVAILABLE:
            logger.warning(
                "Adafruit display libraries not available. "
                "Install with: pip install adafruit-circuitpython-rgb-display pillow"
            )
            return False

        try:
            # Configure SPI pins
            cs = digitalio.DigitalInOut(getattr(board, f'D{self._csPin}'))
            dc = digitalio.DigitalInOut(getattr(board, f'D{self._dcPin}'))
            rst = digitalio.DigitalInOut(getattr(board, f'D{self._rstPin}'))

            # Initialize SPI bus
            spi = board.SPI()

            # Create display instance
            self._display = st7789.ST7789(
                spi,
                cs=cs,
                dc=dc,
                rst=rst,
                width=DISPLAY_WIDTH,
                height=DISPLAY_HEIGHT,
                rotation=self._rotation,
            )

            # Create image buffer for double-buffering
            self._image = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT))
            self._draw = ImageDraw.Draw(self._image)

            # Load fonts
            self._loadFonts()

            # Configure backlight
            self._setupBacklight()

            # Clear display
            self.clear()
            self.refresh()

            self._initialized = True
            logger.info(
                f"Adafruit ST7789 display initialized "
                f"({DISPLAY_WIDTH}x{DISPLAY_HEIGHT}, rotation={self._rotation})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Adafruit display: {e}")
            self._initialized = False
            raise DisplayInitializationError(
                f"Display initialization failed: {e}",
                details={'error': str(e)}
            )

    def _loadFonts(self) -> None:
        """Load fonts for text rendering."""
        if not ADAFRUIT_AVAILABLE or ImageFont is None:
            return

        # Try to load TrueType fonts, fall back to default bitmap font
        for sizeName, sizeValue in self.FONT_SIZES.items():
            try:
                # Try DejaVu Sans (commonly available on Raspberry Pi)
                self._fonts[sizeName] = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    sizeValue
                )
            except (IOError, OSError):
                try:
                    # Try Arial as fallback
                    self._fonts[sizeName] = ImageFont.truetype(
                        "arial.ttf",
                        sizeValue
                    )
                except (IOError, OSError):
                    # Use default bitmap font
                    self._fonts[sizeName] = ImageFont.load_default()

    def _setupBacklight(self) -> None:
        """Set up backlight control."""
        if not ADAFRUIT_AVAILABLE or digitalio is None:
            return

        try:
            # Simple on/off backlight (for PWM, use RPi.GPIO or pigpio)
            self._backlightPin = digitalio.DigitalInOut(
                getattr(board, f'D{self._blPin}')
            )
            self._backlightPin.direction = digitalio.Direction.OUTPUT
            self._backlightPin.value = self._brightness > 0
        except Exception as e:
            logger.warning(f"Could not configure backlight: {e}")
            self._backlightPin = None

    def shutdown(self) -> None:
        """
        Shutdown the display and release resources.

        Clears the display, turns off the backlight, and releases
        any held resources.
        """
        if self._initialized:
            try:
                # Clear display
                self.clear()
                self.refresh()

                # Turn off backlight
                if self._backlightPin:
                    self._backlightPin.value = False

                logger.info("Adafruit display shutdown complete")
            except Exception as e:
                logger.warning(f"Error during display shutdown: {e}")

        self._initialized = False
        self._display = None
        self._image = None
        self._draw = None

    def clear(self, color: str = 'black') -> None:
        """
        Clear the display buffer.

        Args:
            color: Background color name (default: 'black')
        """
        if self._draw is None:
            return

        rgbColor = Colors.fromName(color)
        self._draw.rectangle(
            [(0, 0), (DISPLAY_WIDTH, DISPLAY_HEIGHT)],
            fill=rgbColor
        )

    def fill(self, color: str) -> None:
        """
        Fill the entire display with a color.

        Args:
            color: Color name to fill with
        """
        self.clear(color)

    def drawText(
        self,
        x: int,
        y: int,
        text: str,
        size: str = 'normal',
        color: str = 'white'
    ) -> None:
        """
        Draw text at the specified position.

        Args:
            x: X coordinate (pixels from left)
            y: Y coordinate (pixels from top)
            text: Text string to draw
            size: Font size name ('small', 'normal', 'medium', 'large', 'xlarge')
            color: Text color name
        """
        if self._draw is None:
            return

        font = self._fonts.get(size, self._fonts.get('normal'))
        rgbColor = Colors.fromName(color)

        self._draw.text((x, y), text, font=font, fill=rgbColor)

    def drawLine(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: str = 'white',
        width: int = 1
    ) -> None:
        """
        Draw a line between two points.

        Args:
            x1: Start X coordinate
            y1: Start Y coordinate
            x2: End X coordinate
            y2: End Y coordinate
            color: Line color name
            width: Line width in pixels
        """
        if self._draw is None:
            return

        rgbColor = Colors.fromName(color)
        self._draw.line([(x1, y1), (x2, y2)], fill=rgbColor, width=width)

    def drawRect(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        color: str = 'white',
        fill: bool = False,
        outline: Optional[str] = None
    ) -> None:
        """
        Draw a rectangle.

        Args:
            x: Top-left X coordinate
            y: Top-left Y coordinate
            width: Rectangle width
            height: Rectangle height
            color: Fill or outline color
            fill: If True, fill the rectangle; if False, draw outline only
            outline: Optional outline color (when fill is True)
        """
        if self._draw is None:
            return

        rgbColor = Colors.fromName(color)
        outlineColor = Colors.fromName(outline) if outline else None

        if fill:
            self._draw.rectangle(
                [(x, y), (x + width, y + height)],
                fill=rgbColor,
                outline=outlineColor
            )
        else:
            self._draw.rectangle(
                [(x, y), (x + width, y + height)],
                outline=rgbColor
            )

    def drawCircle(
        self,
        x: int,
        y: int,
        radius: int,
        color: str = 'white',
        fill: bool = False
    ) -> None:
        """
        Draw a circle.

        Args:
            x: Center X coordinate
            y: Center Y coordinate
            radius: Circle radius
            color: Fill or outline color
            fill: If True, fill the circle; if False, draw outline only
        """
        if self._draw is None:
            return

        rgbColor = Colors.fromName(color)
        bbox = [(x - radius, y - radius), (x + radius, y + radius)]

        if fill:
            self._draw.ellipse(bbox, fill=rgbColor)
        else:
            self._draw.ellipse(bbox, outline=rgbColor)

    def refresh(self) -> None:
        """
        Refresh the display by blitting the image buffer.

        This should be called after all draw operations are complete
        to update the physical display.
        """
        if self._display is None or self._image is None:
            return

        try:
            self._display.image(self._image)
        except Exception as e:
            logger.error(f"Error refreshing display: {e}")
            raise DisplayRenderError(
                f"Failed to refresh display: {e}",
                details={'error': str(e)}
            )

    def setBrightness(self, brightness: int) -> None:
        """
        Set the display backlight brightness.

        Note: Simple on/off for digital GPIO. For PWM brightness control,
        use RPi.GPIO or pigpio library with the backlight pin.

        Args:
            brightness: Brightness level 0-100 (0 = off, >0 = on)
        """
        self._brightness = max(0, min(100, brightness))

        if self._backlightPin:
            self._backlightPin.value = self._brightness > 0

    def getImage(self) -> Optional[Any]:
        """
        Get the current image buffer.

        Useful for testing or saving screenshots.

        Returns:
            PIL Image object or None if not initialized
        """
        return self._image


def isDisplayHardwareAvailable() -> bool:
    """
    Check if the display hardware libraries are available.

    This checks for the Adafruit libraries, not actual hardware presence.
    Actual hardware availability is checked during initialization.

    Returns:
        True if libraries are available
    """
    return ADAFRUIT_AVAILABLE


def createAdafruitAdapter(config: Optional[Dict[str, Any]] = None) -> AdafruitDisplayAdapter:
    """
    Create an Adafruit display adapter from configuration.

    Args:
        config: Optional configuration dictionary with display settings

    Returns:
        AdafruitDisplayAdapter instance
    """
    displayConfig = config.get('display', {}) if config else {}
    return AdafruitDisplayAdapter(
        config=displayConfig,
        rotation=displayConfig.get('rotation', 180),
        brightness=displayConfig.get('brightness', 100),
    )
